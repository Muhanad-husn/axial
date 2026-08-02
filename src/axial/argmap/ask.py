"""The argument map's door and landing (issue #572, PR 3 of 4): a port of
the scratchpad run this issue measured over the real corpus
(`stage3_brief_on_map.py`'s `DECOMPOSE_PROMPT` and its landing step), not a
redesign. PR 1 built the position layer (`axial.argmap.build`); this is the
way a question reaches it.

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

The corridor (following a landed position's relations to what argues with
it) and the assembly order are PR 4, and depend on PR 2's relations layer --
out of scope here.
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

# The pass name `config/pipeline.yaml`'s `llm.reasoning_by_pass` keys off of.
DECOMPOSE_PASS_NAME = "brief_decompose"

# Every stated argument lands on this many positions (scratchpad measurement,
# issue #572 step 3) -- kept once each even where two arguments both reach
# the same position, at whichever score is higher.
POSITIONS_PER_ASK = 4

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
class AskResult:
    """What `run_map_ask` hands back: the brief it read, the arguments the
    door stated, and the positions the landing reached, in landing order."""

    brief: Brief
    asks: tuple[str, ...]
    landed: tuple[LandedPosition, ...]


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


def _check_encoder(manifest: dict[str, Any], outdir: Path, encoder_model: str) -> None:
    built_with = manifest.get("encoder")
    if built_with != encoder_model:
        raise EncoderMismatchError(outdir, encoder_model, built_with)


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
) -> AskResult:
    """Load `brief_path`, land it on the pinned argument map, and return the
    result: the door's stated arguments plus the positions they landed on,
    in landing order.

    `pin` defaults to `compute_corpus_pin(envelopes_dir, sources_dir)` -- the
    same pin `axial map build` writes under -- but a caller may pass one
    explicitly (the same override every other `run_*` function in this
    codebase exposes) to read a fixture map without a real
    `data/envelopes/`+`data/sources/` on disk. `client`/`encode` default to
    `axial.llm.get_client()` and the real MiniLM encoder; both are injection
    seams for tests.

    Raises `BriefError` (a malformed or missing brief), `MapNotBuiltError`
    (no map at this pin), `EncoderMismatchError` (the map was built with a
    different encoder), or `DecomposeError` (the door call failed or
    returned nothing usable)."""
    brief = load_brief(brief_path)

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

    if client is None:
        client = get_client(config_path=config_path)
    if encode is None:
        encode = _default_encoder()

    asks = decompose_brief(brief, client)
    landed = land_arguments(asks, positions, encode, top_k=top_k)

    return AskResult(brief=brief, asks=tuple(asks), landed=tuple(landed))
