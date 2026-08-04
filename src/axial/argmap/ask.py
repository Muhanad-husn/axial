"""The argument map's read side (issue #572): door, landing, corridor, and
assembly order -- a port of the scratchpad run this issue measured over the
real corpus (`stage3_brief_on_map.py`), not a redesign. PR 1/2 built the
position and relation layers (`axial.argmap.build`); this is the way a
question reaches them, all the way through to an ordered list of chunk ids
a synthesis prompt can read.

Two steps:

  **Door** (`decompose_brief`). One model call reads a brief's `case` and
  `request` and states the arguments the question is actually about, as
  standalone contestable sentences -- never as keywords, names, or a summary
  of the question. It never sees the corpus, so it cannot be led by what
  happens to be there (the same failure this whole issue is about: a name
  layer that only finds what a passage happened to mention). `pass_name`
  `"brief_decompose"`, reasoning `"high"` set through
  `config/pipeline.yaml`'s `llm.reasoning_by_pass` -- the convention PR 1
  established; nothing here mutates a client's reasoning table in code.

  **Landing** (`land_arguments`). Each stated argument is matched against the
  map's own position `argument` sentences by cosine similarity (the same
  local encoder the build used -- `_check_encoder` refuses to compare vectors
  from two different ones, loudly, rather than silently). The top
  `POSITIONS_PER_ASK` positions per argument are kept; a position reached by
  more than one argument is kept once, at its best score, and the result is
  ordered by that score, descending.

**The corridor** (`build_corridor`, issue #572, PR 4 of 4). Stage 2's own
relations (`relations.jsonl`, keyed on `position_id`, never on the argument
sentence) are read back here: every relation touching a landed position
pulls its counterpart in, in both directions -- a relation running INTO a
landed position and one running OUT OF it are different facts about the
position it reaches, and both are kept. This is where the account the
answer must reject comes from, and it arrives BECAUSE it argues with what
landed, never because a stated argument happened to name it. A landed
position is never also a corridor position. Corridor positions are ordered
by how many relations connect them to the landed set, descending.

**The assembly order** (`assemble_map_evidence`), which is the real
retrieval. `axial.analyze.synthesis.synthesize`'s own `evidence_char_budget`
admits only a prefix of whatever is assembled -- ~56 notes at the shipped
250,000 (issue #574) -- so the order notes are emitted in decides what the
answer actually sees. Round-robin, twice over: across positions first
(landed in score order, then corridor in relation-count order), and within
one position across its own sources (`round_robin_by_source`), so a
position holding forty notes from one book and two from another does not
spend the whole prefix on the first. Chunk ids are deduplicated across
positions -- a note two positions both carry is emitted once, at whichever
position's turn reaches it first.

Both are a port of the scratchpad's own measured `stage3_brief_on_map.py`,
not a redesign; see that module's docstring reproduced in the scratchpad
for the run this ports. This is the last slice of issue #572: with the
corridor and the assembly order in place, the read side -- door, landing,
corridor, assembly -- is complete.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import httpx
import numpy as np

from axial.argmap.build import ENCODER_MODEL, Encoder, _default_encoder, compute_corpus_pin
from axial.brief.intake import Brief, load_brief
from axial.envelope import _default_envelopes_dir
from axial.llm import LLMClient, LLMError, get_client
from axial.model_json import ModelJsonError, parse_model_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_map_dir, default_sources_dir
from axial.query.reader import MalformedChunkIdError, source_id_from_chunk_id
from axial.query.relations import chunk_ids_for_name

# The pass name `config/pipeline.yaml`'s `llm.reasoning_by_pass` keys off of.
DECOMPOSE_PASS_NAME = "brief_decompose"

# Every stated argument lands on this many positions (scratchpad measurement,
# issue #572 step 3) -- kept once each even where two arguments both reach
# the same position, at whichever score is higher.
#
# **Not a knob.** Widening this does nothing: the scratchpad measurement swept
# 2-24 and the composed-books count was flat throughout, because
# `round_robin_by_source`'s own first rotation already covers the whole
# `evidence_char_budget` prefix -- there just aren't enough turns in the
# budget for a wider landing to matter. Spreading the landing across authors
# instead of by score was tried and measured WORSE (19 positions -> 11,
# dropping three books entirely) -- see `land_arguments`'s own score-order
# result, unchanged. Both are settled findings, not defaults awaiting a
# future sweep.
POSITIONS_PER_ASK = 4

# Assembly stops here regardless of how many positions the corridor reaches
# (scratchpad measurement, issue #572 step 3: brief B assembled 90 notes,
# composed 20 once `evidence_char_budget` cut the prefix). Generous headroom
# above what any budget setting has used so far (~56 notes at the shipped
# 250_000, issue #574) rather than a stopping point tuned to it -- raising
# the budget again should not also require moving this.
ASSEMBLE_CAP = 90

# Ported verbatim from `stage3_brief_on_map.py`'s `DECOMPOSE_PROMPT` (issue
# #572 step 3): every rule here is load-bearing and was measured on the real
# corpus, not authored fresh for this port. In particular "name no authors
# and no books" is what keeps the door blind to what the corpus happens to
# hold, and "six to ten arguments" is what keeps it from collapsing the
# question into one summary sentence or exploding into a list of trivia.
DECOMPOSE_PROMPT = """A researcher has asked the question below of a body of academic work.

CASE: {case}

QUESTION: {request}

Before anything is looked up, say what arguments this question is actually about. Write each one as a standalone sentence that a scholar could assert and another could deny -- the position itself, not a description of it and not a topic.

Include, as separate entries:
- each account the question asks to weigh, stated in its own strongest terms as its holder would state it;
- the mechanism each account relies on, stated as its own claim;
- the specific test the question demands, stated as a claim about that test.

Answer as JSON only, no other text:

{{"arguments": ["<one contestable sentence>", "..."]}}

Rules:
- Name no authors and no books. You are stating positions, not attributing them.
- Do not hedge and do not balance. Each account gets its strongest statement, including the one the question may end up rejecting.
- Six to ten arguments."""


class AskError(Exception):
    """Base class for every error `axial.argmap.ask` raises."""


class DecomposeError(AskError):
    """Raised when the door call itself fails, returns a response that
    isn't a usable JSON object, or returns no usable arguments. All three
    are the same failure class from a caller's point of view -- there is no
    brief-as-arguments result to land with -- so this must fail loudly
    rather than let an empty or malformed set silently land on nothing."""


class MapNotBuiltError(AskError):
    """Raised when `<map_dir>/<pin>/` carries no `map.json`/`positions.jsonl`
    -- no build has ever run for this pin -- or `positions.jsonl` is empty."""

    def __init__(self, outdir: Path):
        self.outdir = outdir
        super().__init__(f"no argument map built at {outdir} -- run `axial map build` first")


class EncoderMismatchError(AskError):
    """Raised when the map at `outdir` was built with a different encoder
    than the one this call is about to compare vectors with. Refused rather
    than computed: a cosine similarity between two different embedding
    spaces is a number, but not a meaningful one, and it fails silently --
    there is no error a mismatched vector comparison would ever raise on its
    own."""

    def __init__(self, outdir: Path, expected: str, built_with: Any):
        self.outdir = outdir
        self.expected = expected
        self.built_with = built_with
        super().__init__(
            f"argument map at {outdir} was built with encoder {built_with!r}, "
            f"but this command's encoder is {expected!r} -- landing requires "
            "the same encoder the build used"
        )


@dataclass(frozen=True)
class LandedPosition:
    """One position the map landed a question on: `score` is the best cosine
    similarity any stated argument reached it at, `size` is how many
    passages stand behind it (the position's own passage count, not the
    number of arguments that landed on it), and `chunk_ids` is carried
    through for PR 4's assembly step so it need not re-read `positions.jsonl`
    to resolve what it landed on."""

    position_id: str
    score: float
    argument: str
    size: int
    sources: tuple[str, ...]
    authors: tuple[str, ...]
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class CorridorPosition:
    """One position pulled into the corridor (issue #572, PR 4 of 4)
    because it argues with what landed -- never because a stated argument
    named it. `labels` is every relation that reached it, each stamped with
    the direction it ran: `"<relation> ->"` when the relation runs FROM a
    landed position INTO this one, `"<relation> <-"` the other way --
    direction is a fact about the relation (`build.py`'s own record), kept
    rather than collapsed. `relation_count` (`len(labels)`) is the
    corridor's own ordering key, descending: a position several relations
    reach argues with more of what landed than one only a single relation
    touches. A landed position never also appears here -- see
    `build_corridor`'s own guard."""

    position_id: str
    relation_count: int
    labels: tuple[str, ...]
    argument: str
    size: int
    sources: tuple[str, ...]
    authors: tuple[str, ...]
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class AskResult:
    """What `run_map_ask` hands back: the brief it read, the arguments the
    door stated, the positions the landing reached (in landing order), the
    positions the corridor reached (in relation-count order, issue #572 PR
    4 of 4), and the final assembled chunk ids (`assembled_chunk_ids`) the
    round-robin walk emitted, in the order a synthesis prompt would read
    them. `corridor`/`assembled_chunk_ids` default empty for a caller that
    only wants the door and the landing (PR 3's own original contract).
    `pin` (issue #583) is the map directory's own name -- whatever this
    call actually resolved and read, whether the caller passed one
    explicitly or `run_map_ask_for_brief` computed it from the corpus --
    so a caller downstream (`axial.answer.record.run_brief`) can record
    which map answered the brief without re-deriving the pin itself."""

    brief: Brief
    asks: tuple[str, ...]
    landed: tuple[LandedPosition, ...]
    corridor: tuple[CorridorPosition, ...] = ()
    assembled_chunk_ids: tuple[str, ...] = ()
    pin: str | None = None


def render_decompose_prompt(brief: Brief) -> str:
    """The door prompt rendered for `brief`: `DECOMPOSE_PROMPT` with only
    `case`/`request` filled in. Never touches `brief.lens` -- the door asks
    what the question is about, not how to read it."""
    return DECOMPOSE_PROMPT.format(case=brief.case, request=brief.request)


def decompose_brief(
    brief: Brief, client: LLMClient, pass_name: str = DECOMPOSE_PASS_NAME
) -> list[str]:
    """The door: one model call, returning the stated arguments as a list of
    non-empty, stripped strings. Raises `DecomposeError` -- never returns an
    empty list -- when the call fails, the response isn't parseable JSON,
    the response is valid JSON shaped as something other than the expected
    object, or every entry in `arguments` is missing, blank, or not a
    string."""
    prompt = render_decompose_prompt(brief)
    try:
        parsed = parse_model_json(client.complete(prompt, pass_name=pass_name))
        arguments = parsed.get("arguments")
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise DecomposeError(f"door call did not return usable JSON: {exc}") from exc
    except (AttributeError, TypeError) as exc:
        # Valid JSON shaped as something other than the expected object
        # (e.g. a bare list) -- `.get(...)` itself is what fails here, same
        # fault class `extract_positions_for_slice` in build.py catches.
        raise DecomposeError(f"door response was not a JSON object: {exc}") from exc

    asks = [a.strip() for a in (arguments or []) if isinstance(a, str) and a.strip()]
    if not asks:
        raise DecomposeError("door returned no usable arguments")
    return asks


def land_arguments(
    asks: Sequence[str],
    positions: Sequence[dict[str, Any]],
    encode: Encoder,
    top_k: int = POSITIONS_PER_ASK,
) -> list[LandedPosition]:
    """The landing: each of `asks` matched against `positions`' own
    `argument` sentences by cosine similarity (both encoded by `encode`,
    which must be the same encoder the map was built with -- callers reach
    this only through `run_map_ask`, which checks that first). The top
    `top_k` positions per ask are kept; a position several asks reach is
    kept once, at its best score. Returns positions ordered by that score,
    descending."""
    if not asks or not positions:
        return []

    argument_vectors = encode([position["argument"] for position in positions])
    ask_vectors = encode(list(asks))

    best: dict[int, float] = {}
    for vector in ask_vectors:
        scores = argument_vectors @ vector
        for index in np.argsort(-scores)[:top_k]:
            index = int(index)
            score = float(scores[index])
            if score > best.get(index, float("-inf")):
                best[index] = score

    order = sorted(best, key=lambda i: -best[i])
    return [
        LandedPosition(
            position_id=positions[i]["position_id"],
            score=best[i],
            argument=positions[i]["argument"],
            size=positions[i]["size"],
            sources=tuple(positions[i]["sources"]),
            authors=tuple(positions[i]["authors"]),
            chunk_ids=tuple(positions[i]["chunk_ids"]),
        )
        for i in order
    ]


def build_corridor(
    landed: Sequence[LandedPosition],
    positions_by_id: dict[str, dict[str, Any]],
    relations: Sequence[dict[str, Any]],
) -> list[CorridorPosition]:
    """The corridor (issue #572, PR 4 of 4): every relation touching a
    landed position pulls its counterpart in, in both directions -- this is
    where the account the answer must reject comes from, and it arrives
    BECAUSE it argues with what landed, never because a stated argument
    named it. Relations key on `position_id` (`from_position_id`/
    `to_position_id`), never on the argument sentence (issue #572's own
    settled rule: a sentence-to-index rejoin silently drops any relation
    whose sentence is not unique across positions).

    A relation between two ALREADY-landed positions contributes nothing --
    `far not in landed_ids` excludes it, so a landed position never also
    shows up in the corridor. A relation naming a position id that is not
    in `positions_by_id` at all (should not happen; `build.py` already
    drops an invented handle at the relate stage) is skipped defensively
    rather than raised, the same tolerance this codebase gives every other
    cross-stage id join.

    Ordered by how many relations connect a position to the landed set,
    descending; ties broken by `position_id` so the result is deterministic
    regardless of `relations`' own arrival order."""
    landed_ids = {position.position_id for position in landed}
    labels_by_far: dict[str, list[str]] = {}
    for relation in relations:
        src = relation.get("from_position_id")
        dst = relation.get("to_position_id")
        label = relation.get("relation", "")
        for near, far, arrow in ((src, dst, "->"), (dst, src, "<-")):
            if near in landed_ids and far not in landed_ids and far in positions_by_id:
                labels_by_far.setdefault(far, []).append(f"{label} {arrow}")

    ordered_ids = sorted(labels_by_far, key=lambda pid: (-len(labels_by_far[pid]), pid))
    corridor: list[CorridorPosition] = []
    for position_id in ordered_ids:
        position = positions_by_id[position_id]
        labels = tuple(labels_by_far[position_id])
        corridor.append(
            CorridorPosition(
                position_id=position_id,
                relation_count=len(labels),
                labels=labels,
                argument=position["argument"],
                size=position["size"],
                sources=tuple(position["sources"]),
                authors=tuple(position["authors"]),
                chunk_ids=tuple(position["chunk_ids"]),
            )
        )
    return corridor


def round_robin_by_source(chunk_ids: Sequence[str]) -> list[str]:
    """`chunk_ids` regrouped by source (`axial.query.reader.
    source_id_from_chunk_id`), each group keeping its own relative order,
    then interleaved one id per group in rotation -- the same
    `_round_robin_by_source` pattern `axial.query.names` already uses for a
    name page's own capped window (issue #562), applied here so a position
    holding forty notes from one book and two from another spends its
    early turns on one note per book, not forty in a row. A chunk_id that
    does not parse (`MalformedChunkIdError`) groups under `""`, which sorts
    first -- the same placement that pattern gives an unparsed member,
    reused rather than invented a second time, so it stays reachable
    instead of silently dropped."""
    groups: dict[str, list[str]] = {}
    for chunk_id in chunk_ids:
        try:
            source_id = source_id_from_chunk_id(chunk_id)
        except MalformedChunkIdError:
            source_id = ""
        groups.setdefault(source_id, []).append(chunk_id)

    keys = sorted(groups)
    ordered: list[str] = []
    round_index = 0
    while len(ordered) < len(chunk_ids):
        for key in keys:
            bucket = groups[key]
            if round_index < len(bucket):
                ordered.append(bucket[round_index])
        round_index += 1
    return ordered


def assemble_map_evidence(
    positions: Sequence[LandedPosition | CorridorPosition | MatchedPosition],
    *,
    cap: int = ASSEMBLE_CAP,
) -> list[str]:
    """The assembly order (issue #572, PR 4 of 4) -- this IS the retrieval.
    `axial.analyze.synthesis.synthesize`'s own `evidence_char_budget` admits
    only a prefix of whatever is assembled here (~56 notes at the shipped
    250_000, issue #574), so the order these ids are emitted in decides
    what the answer actually sees.

    Round-robin, twice over: `positions` is walked in the order given
    (landed positions in score order, then corridor positions in
    relation-count order -- both already sorted by their own callers), one
    id from each position's own `round_robin_by_source` queue per turn, so
    neither a position that happened to sort first nor a source within it
    can spend the whole prefix on itself. A chunk id already emitted by an
    earlier position's turn is skipped, never re-emitted -- a note two
    positions both carry counts once, at whichever position's turn reaches
    it first. A position's own queue emptying mid-walk drops it out of the
    rotation rather than stalling it: the remaining queues simply keep
    turning."""
    queues = [
        list(round_robin_by_source(position.chunk_ids))
        for position in positions
        if position.chunk_ids
    ]
    assembled: list[str] = []
    seen: set[str] = set()
    while queues and len(assembled) < cap:
        for queue in list(queues):
            chunk_id = queue.pop(0)
            if chunk_id not in seen:
                seen.add(chunk_id)
                assembled.append(chunk_id)
            if not queue:
                queues.remove(queue)
            if len(assembled) >= cap:
                break
    return assembled


# `(envelopes_dir, sources_dir) -> pin`, process-lifetime, for
# `resolve_pinned_map_dir` -- see its docstring for why a repeat call must
# not re-hash the corpus.
_PIN_CACHE: dict[tuple[Path, Path], str | None] = {}


@dataclass(frozen=True)
class MatchedPosition:
    """One position the note store joined a name onto (issue #650): the map's
    own `argument` sentence and passage set, plus `matched_note_count` -- how
    many of the position's own passages carry the name asked about. This is
    not `LandedPosition`: nothing here is encoded or scored, and no model
    call is made. The join is `positions.chunk_ids` against `note_names`,
    which is a table lookup."""

    position_id: str
    argument: str
    size: int
    sources: tuple[str, ...]
    authors: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    matched_note_count: int


def positions_on(
    name: str,
    limit: int,
    *,
    map_dir: Path | None,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> tuple[list[MatchedPosition], list[str], int]:
    """The argument map's positions that a given name reaches, as a
    retrieval target in the §7.5 tool loop (issue #650, DEC-62).

    A position is the unit a question can land on directly instead of hoping
    the right proper noun was mentioned -- #572 measured the map's own
    substrate stronger on citation grounding than the name layer (strong vs
    adequate, half the defects) -- and until now it was reachable only
    through `axial map ask`'s own arm, behind a model call and the encoder.
    This reaches it the relational way the rest of issue #650 works: the map
    already records which passages stand behind each position, and the note
    store already records which notes carry a name, so the two join on
    `chunk_id` with no encoder, no decompose call and no rebuild. The name
    is a FILTER on positions, exactly as it is a filter on notes elsewhere.

    Returns `(positions, chunk_ids, total)`. `chunk_ids` is assembled by
    `assemble_map_evidence` -- one id per position per rotation, each
    position's own ids spread across its sources -- capped at `limit`, and
    `total` is the true pre-cap count of distinct ids across every matched
    position. `positions` are the ones actually represented in `chunk_ids`.

    **Determinism:** positions are ordered by `matched_note_count`
    descending, ties by `position_id` ascending -- a total order. Ranking by
    the position's own `size` is deliberately NOT used: size-ranking drifts
    to the corpus's biggest objects regardless of relevance (measured, PR
    #522 and issue #632's door slate), while the matched count is a count of
    the thing actually asked for.

    Empty is a real answer: no map built at `map_dir` (or `map_dir` `None`),
    no store in the vault, or a name no position's passages carry, all
    return `([], [], 0)` rather than raising."""
    if map_dir is None:
        return [], [], 0
    try:
        positions, _manifest = _load_map(Path(map_dir))
    except MapNotBuiltError:
        return [], [], 0

    members = chunk_ids_for_name(name, vault_dir=vault_dir, names_dir=names_dir)
    if not members:
        return [], [], 0

    matched: list[MatchedPosition] = []
    for position in positions:
        chunk_ids = tuple(position["chunk_ids"])
        hits = len(members.intersection(chunk_ids))
        if hits:
            matched.append(
                MatchedPosition(
                    position_id=position["position_id"],
                    argument=position["argument"],
                    size=position["size"],
                    sources=tuple(position["sources"]),
                    authors=tuple(position["authors"]),
                    chunk_ids=chunk_ids,
                    matched_note_count=hits,
                )
            )
    matched.sort(key=lambda p: (-p.matched_note_count, p.position_id))

    total = len({chunk_id for position in matched for chunk_id in position.chunk_ids})
    assembled = assemble_map_evidence(matched, cap=limit)
    reached = set(assembled)
    contributing = [p for p in matched if reached.intersection(p.chunk_ids)]
    return contributing, assembled, total


def resolve_pinned_map_dir(
    *,
    map_dir: Path | None = None,
    pin: str | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> Path | None:
    """The built map directory for this corpus, or `None` when there is not
    one (issue #650) -- the tolerant counterpart to the resolution
    `run_map_ask_for_brief` does inline, which raises `MapNotBuiltError`
    instead.

    `positions_on` is one tool among fourteen in a retrieval loop that runs
    with or without a built map, so "no map" must degrade to an empty tool
    result, never to a failed run. Any failure to compute the pin at all --
    no envelopes directory, a malformed envelope, a raw source file that has
    moved -- means the same thing here, "there is no verified map for this
    corpus", and is answered with `None` rather than raised: this is an
    optional capability check, not a stage.

    **Two costs are deliberately bounded.** The pin is computed only once the
    map root actually exists, so a checkout with no map pays nothing. And the
    result is cached for the process, because `compute_corpus_pin` reads and
    hashes every raw source file (`axial.eval.corpus_pin._build_sources`) --
    seconds over a real corpus, and `axial ask` calls `run_brief` once per
    turn in a single process. **Taking the pin unverified is not the cheaper
    option it looks like:** a map built from an older corpus carries chunk
    ids the current vault no longer holds, which would put unresolvable ids
    into an evidence set."""
    root = Path(map_dir) if map_dir is not None else default_map_dir(config_path)
    if not root.is_dir():
        return None
    if pin is None:
        if envelopes_dir is None:
            envelopes_dir = _default_envelopes_dir(config_path)
        if sources_dir is None:
            sources_dir = default_sources_dir(config_path)
        key = (Path(envelopes_dir).resolve(), Path(sources_dir).resolve())
        if key in _PIN_CACHE:
            pin = _PIN_CACHE[key]
        else:
            try:
                pin = compute_corpus_pin(envelopes_dir, sources_dir)
            except Exception:
                pin = None
            _PIN_CACHE[key] = pin
        if pin is None:
            return None
    outdir = root / pin
    return outdir if (outdir / "positions.jsonl").is_file() else None


def _load_map(outdir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """`positions.jsonl` and `map.json` under `outdir`, or `MapNotBuiltError`
    when either is missing or `positions.jsonl` is empty."""
    manifest_path = outdir / "map.json"
    positions_path = outdir / "positions.jsonl"
    if not manifest_path.is_file() or not positions_path.is_file():
        raise MapNotBuiltError(outdir)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    positions = [
        json.loads(line)
        for line in positions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not positions:
        raise MapNotBuiltError(outdir)
    return positions, manifest


def _load_relations(outdir: Path) -> list[dict[str, Any]]:
    """`relations.jsonl` under `outdir`, or an empty list when the file
    does not exist -- a map built before PR 2 shipped, or a test fixture
    that only exercises the door and the landing, still lands cleanly with
    an empty corridor rather than raising."""
    relations_path = outdir / "relations.jsonl"
    if not relations_path.is_file():
        return []
    return [
        json.loads(line)
        for line in relations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _check_encoder(manifest: dict[str, Any], outdir: Path, encoder_model: str) -> None:
    built_with = manifest.get("encoder")
    if built_with != encoder_model:
        raise EncoderMismatchError(outdir, encoder_model, built_with)


def run_map_ask_for_brief(
    brief: Brief,
    *,
    map_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    encode: Encoder | None = None,
    encoder_model: str = ENCODER_MODEL,
    pin: str | None = None,
    top_k: int = POSITIONS_PER_ASK,
    assemble_cap: int = ASSEMBLE_CAP,
) -> AskResult:
    """Everything `run_map_ask` does except loading the brief from disk:
    land an already-loaded `brief` on the pinned argument map and walk it
    all the way through assembly -- door, landing, corridor, and the
    round-robin assembly order.

    This is the seam `axial.answer.record.run_brief` uses directly (issue
    #572, PR 4 of 4): that caller already holds a loaded `Brief` (its own
    stage-1 interrogation ran over it first), and re-reading the same brief
    file a second time here would be pointless I/O for no new information.
    `run_map_ask` (the CLI's own entry point) still takes a path, and calls
    straight through to this function once it has loaded one.

    `pin` defaults to `compute_corpus_pin(envelopes_dir, sources_dir)` -- the
    same pin `axial map build` writes under -- but a caller may pass one
    explicitly (the same override every other `run_*` function in this
    codebase exposes) to read a fixture map without a real
    `data/envelopes/`+`data/sources/` on disk. `client`/`encode` default to
    `axial.llm.get_client()` and the real MiniLM encoder; both are injection
    seams for tests.

    Raises `MapNotBuiltError` (no map at this pin), `EncoderMismatchError`
    (the map was built with a different encoder), or `DecomposeError` (the
    door call failed or returned nothing usable)."""
    if map_dir is None:
        map_dir = default_map_dir(config_path)
    if pin is None:
        if envelopes_dir is None:
            envelopes_dir = _default_envelopes_dir(config_path)
        if sources_dir is None:
            sources_dir = default_sources_dir(config_path)
        # The same pin `axial map build` computes and writes under
        # (`axial.argmap.build.compute_corpus_pin`) -- reused directly so a
        # corpus change moves both to the same new directory together.
        pin = compute_corpus_pin(envelopes_dir, sources_dir)

    outdir = Path(map_dir) / pin
    positions, manifest = _load_map(outdir)
    _check_encoder(manifest, outdir, encoder_model)
    relations = _load_relations(outdir)

    if client is None:
        client = get_client(config_path=config_path)
    if encode is None:
        encode = _default_encoder()

    asks = decompose_brief(brief, client)
    landed = land_arguments(asks, positions, encode, top_k=top_k)
    positions_by_id = {position["position_id"]: position for position in positions}
    corridor = build_corridor(landed, positions_by_id, relations)
    assembled = assemble_map_evidence((*landed, *corridor), cap=assemble_cap)

    return AskResult(
        brief=brief,
        asks=tuple(asks),
        landed=tuple(landed),
        corridor=tuple(corridor),
        assembled_chunk_ids=tuple(assembled),
        pin=pin,
    )


def run_map_ask(
    brief_path: str | Path,
    *,
    map_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    encode: Encoder | None = None,
    encoder_model: str = ENCODER_MODEL,
    pin: str | None = None,
    top_k: int = POSITIONS_PER_ASK,
    assemble_cap: int = ASSEMBLE_CAP,
) -> AskResult:
    """Load `brief_path` and run it through `run_map_ask_for_brief` -- the
    CLI's own entry point (`axial map ask <brief.yaml>`). See that
    function's docstring for the full contract; this wrapper only adds
    `BriefError` to what a caller must handle, for a malformed or missing
    brief file."""
    brief = load_brief(brief_path)
    return run_map_ask_for_brief(
        brief,
        map_dir=map_dir,
        envelopes_dir=envelopes_dir,
        sources_dir=sources_dir,
        config_path=config_path,
        client=client,
        encode=encode,
        encoder_model=encoder_model,
        pin=pin,
        top_k=top_k,
        assemble_cap=assemble_cap,
    )
