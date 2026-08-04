"""Semantic residue resolver (issue #651, DEC-62): a model call over the
argument map's positions for the `arguing_against` targets that no
relational join can reach.

`data/logs/2026-08-04-relational-join-ceiling/summary.md` measured the
ceiling: even the conservative phrase join (`axial.materialize._resolve_
target`, reused here unchanged rather than re-derived) leaves 5,846 of the
corpus's `arguing_against` targets resolved to nothing at any
normalization -- prose descriptions of a position ("the single right-left
continuum of regime typologies") with no distinctive noun phrase the name
index carries. No amount of relational normalization joins free text to
free text; only semantic matching can. `find_unresolved_targets` recomputes
that same residue directly from `data/answers/` and the name layer
(`axial.query.names._build_name_layer`) -- never from the vault's
`notes.db`, so this module never depends on materialize having run.

**The natural target set is the argument map's own positions**
(`data/map/<pin>/positions.jsonl`, issue #572): each is an argument some
author in the corpus actually makes, not a name. Resolving a residue target
against positions is a semantic entailment question -- does this free-text
target describe opposition to that argument -- answered with one model call
per target (`resolve_target`), cheap tier (`deepseek/deepseek-v4-flash`,
the same tier `axial.argmap.build`'s own extraction pass defaults to and
the intake fork-check is planned to use: neither carries a `model_by_pass`
entry in `config/pipeline.yaml`, so both fall through to `llm_tier`'s
production_low). A target that opposes something the map does not hold
must resolve to nothing -- the prompt says so explicitly, and an empty
`matches` list is the expected common case, not a failure.

**Section blocking, measured, not assumed (founder direction on #651).**
Every note carries the chapter/section title its own author wrote
(99.7% populated). `build_section_index` groups positions by the section
titles their own member notes carry, so a target's own note's section
becomes a coarse topical bucket cutting the candidate set before the model
sees it -- standard blocking, the same "narrows where to look, does not
resolve the target" role a section title plays nowhere else in this
codebase. Measured over the real map (2026-08-04): the median bucket holds
exactly ONE position (mean 1.77, max 108) -- a position is a merged
argument spanning many books' worth of member notes, so it very rarely
shares an exact section TITLE with more than a couple of others. Blocking
here may cut recall as often as it cuts noise; `select_candidates` runs
both arms (`use_section_blocking=True/False`) so the sample can report
which.

**A local pass narrows every call's candidate list to `CANDIDATE_TOP_K`,
in both arms, before the paid call ever sees it.** The 1,830-position map's
own argument sentences run to ~365,000 characters -- sending the FULL map
in one prompt costs roughly $0.05/target on flash pricing alone, ~$300
across the residue's ~6,096 targets, not a workable full-pass shape and
nowhere near "cheap tier". `_nearest_candidates` reuses `axial.argmap.
build`'s own local MiniLM encoder (`_default_encoder`, zero model calls --
the exact mechanism `bag_passages`/`build_neighbourhoods` already pay for
before any paid decision) to rank whichever pool a target lands in --
the section bucket, or the full map when blocking is off or the bucket is
empty -- by cosine similarity to the target text, and only the nearest
`CANDIDATE_TOP_K` go in the prompt. This keeps every call's cost roughly
constant across both arms and is not tuned against the sample's own
outcome: it is chosen once, from the cost arithmetic above, before any
candidate was ever sent to a model.

**Content-keyed decision log, the same discipline `axial.merge_names`/
`axial.argmap.build` already use.** `decision_key` hashes the RENDERED
prompt -- target text plus the exact candidate listing sent -- so a re-run
with the same target and the same candidate set re-asks nothing, and a
prompt, model, or `CANDIDATE_TOP_K` change (which changes what gets
rendered) re-asks everything. The two blocking arms naturally share a
decision whenever they land on the same candidate set (a bucket that IS
the fallback, or a target whose bucket ranks the same top-K as the full
pool) -- one call, not two, for that target. The log is a written HISTORY,
not a live set (issue #486): a target's row does not move when the
underlying map or corpus does; a corpus or map rebuild is a new call under
a new key, never a silent overwrite of the old one.

**What this module does not do.** It answers "does target X match position
Y" and appends the answer to `decisions_path`, nothing else -- it never
opens `notes.db` and never writes a store row. `axial.materialize.
build_note_store` is what folds this log into `axial.query.store.
note_opposed_position` (issue #651's own scoping, carried through to that
table): a materialize-time read of `resolve_target`'s already-complete
decision record, not a second resolution mechanism.
"""

from __future__ import annotations

import hashlib
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx
import numpy as np

from axial.argmap.ask import _load_map
from axial.argmap.build import WORKERS as BUILD_WORKERS
from axial.argmap.build import _default_encoder, compute_corpus_pin
from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.envelope import _default_envelopes_dir
from axial.interrogate import _default_answers_dir
from axial.llm import LLMClient, LLMError, estimate_cost, get_client
from axial.materialize import _resolve_target, _target_phrase_index
from axial.model_json import ModelJsonError, parse_model_json
from axial.names import load_answer_records
from axial.paths import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    default_map_dir,
    default_names_dir,
    default_sources_dir,
)
from axial.pidguard import claim_single_instance
from axial.query.names import _build_name_layer, as_string_list
from axial.query.reader import is_abstention

Encoder = Callable[[Sequence[str]], np.ndarray]

# The pass name `config/pipeline.yaml`'s `llm.model_by_pass`/
# `reasoning_by_pass` would key off of. Deliberately absent from that file,
# same as `axial.argmap.build.PASS_NAME` (position extraction) -- both fall
# through to `llm_tier`'s default (production_low / deepseek-v4-flash),
# which is what "cheap tier" means here rather than a hardcoded model id.
PASS_NAME = "residue_resolve"

# Every model call's candidate listing is narrowed to its own nearest this
# many positions by local embedding similarity (module docstring: sending
# the full ~1,830-position map costs ~$0.05/target and ~$300 across the
# full residue). Not tuned against the sample's own outcome -- set once
# from that cost arithmetic, applied identically to both blocking arms.
CANDIDATE_TOP_K = 20


@dataclass(frozen=True)
class UnresolvedTarget:
    """One `arguing_against` target that resolves to no name at any
    normalization (`axial.materialize._resolve_target`'s own conservative
    phrase join) -- `chunk_id`/`source_id` are the note that stated it,
    `target` the free text, `section` that note's own chapter/section
    heading (`None` when absent, ~0.3% of notes)."""

    chunk_id: str
    source_id: str | None
    target: str
    section: str | None


def _chunk_sections(records: Sequence[dict[str, Any]]) -> dict[str, str]:
    """`chunk_id -> section title`, over every answer record that carries a
    non-blank one -- built once and reused both to stamp each
    `UnresolvedTarget`'s own section and to bucket the argument map's
    positions by the sections their own member notes carry
    (`build_section_index`)."""
    sections: dict[str, str] = {}
    for record in records:
        section = record.get("section")
        chunk_id = record.get("chunk_id")
        if isinstance(section, str) and section.strip() and isinstance(chunk_id, str):
            sections[chunk_id] = section.strip()
    return sections


def find_unresolved_targets(
    answers_dir: Path, names_dir: Path
) -> tuple[list[UnresolvedTarget], dict[str, str]]:
    """Every `arguing_against` target across `answers_dir` that
    `axial.materialize._resolve_target` joins to nothing, against the name
    layer at `names_dir` -- the same conservative (>=2-token phrase) join
    the vault's own `note_arguing_against.resolved_canonical` column uses,
    recomputed directly from already-persisted artifacts rather than from
    `notes.db` (issue #651's own dispatch: the live vault was mid-rewrite
    when this ran).

    Deterministic order (`chunk_id`, `target`) regardless of file iteration
    order, matching `seeded_sample_targets`'s own requirement to replay
    identically under a fixed seed. Returns the unresolved list alongside
    `chunk_id -> section`, reused by `build_section_index` so a caller
    never re-scans `answers_dir` a second time for it."""
    records = load_answer_records(answers_dir)
    sections = _chunk_sections(records)
    layer = _build_name_layer(names_dir)
    phrases = _target_phrase_index(layer.folded)
    longest = max((len(phrase.split()) for phrase in phrases), default=0)

    unresolved: list[UnresolvedTarget] = []
    for record in records:
        answers = record.get("answers")
        if not isinstance(answers, dict):
            continue
        targets = answers.get("arguing_against")
        if is_abstention(targets):
            continue
        chunk_id = record.get("chunk_id", "")
        source_id = record.get("source_id")
        for target in dict.fromkeys(as_string_list(targets)):
            if _resolve_target(target, phrases, longest):
                continue
            unresolved.append(UnresolvedTarget(chunk_id, source_id, target, sections.get(chunk_id)))
    unresolved.sort(key=lambda t: (t.chunk_id, t.target))
    return unresolved, sections


def seeded_sample_targets(
    unresolved: Sequence[UnresolvedTarget], size: int, seed: int
) -> list[UnresolvedTarget]:
    """A plain seeded sample of up to `size` targets: sorted to a stable
    base order first, then shuffled by `seed` -- the same replay-identical-
    under-a-fixed-seed shape `axial.gather_eval.seeded_sample` already
    uses, reused rather than re-derived (that function's own records carry
    no `chunk_id`/`target` pair to sort on, so it is not reused directly)."""
    ordered = sorted(unresolved, key=lambda t: (t.chunk_id, t.target))
    rng = random.Random(seed)
    rng.shuffle(ordered)
    return ordered[:size]


def build_section_index(
    positions: Sequence[dict[str, Any]], chunk_sections: dict[str, str]
) -> dict[str, list[str]]:
    """`section title -> sorted [position_id, ...]`, over every position
    that has at least one member note (`chunk_ids`) whose own section is
    that title. A position spans as many sections as its own member notes
    do -- a cross-book merged argument routinely touches several -- so it
    can appear under more than one title here. `[]` implicitly for a
    section no position ever touches (absent from the dict, never a key
    with an empty list)."""
    index: dict[str, set[str]] = {}
    for position in positions:
        titles = {
            chunk_sections[chunk_id]
            for chunk_id in position.get("chunk_ids") or ()
            if chunk_id in chunk_sections
        }
        for title in titles:
            index.setdefault(title, set()).add(position["position_id"])
    return {title: sorted(ids) for title, ids in index.items()}


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def embed_positions(positions: Sequence[dict[str, Any]], encode: Encoder) -> dict[str, np.ndarray]:
    """`position_id -> L2-normalized embedding of its own argument`,
    computed ONCE for the whole map. `_nearest_candidates` reuses this
    rather than re-embedding a target's own candidate pool from scratch:
    embedding the ~1,830-position map costs the same whether it is queried
    once or 6,096 times, and re-encoding even a single target's full-map
    fallback pool on every call would make a 100-target sample take CPU
    minutes it does not need, and a full pass over the residue
    computationally, not just financially, impractical."""
    ordered = sorted(positions, key=lambda position: position["position_id"])
    vectors = encode([position["argument"] for position in ordered])
    return {
        position["position_id"]: _normalize(vector) for position, vector in zip(ordered, vectors)
    }


def _nearest_candidates(
    target_text: str,
    candidates: Sequence[dict[str, Any]],
    position_vectors: dict[str, np.ndarray],
    encode: Encoder,
    top_k: int,
) -> list[dict[str, Any]]:
    """`candidates` (each a position dict carrying at least `position_id`
    and `argument`), narrowed to the `top_k` nearest to `target_text` by
    cosine similarity against `position_vectors` (`embed_positions`'s own
    precomputed map) -- only `target_text` is embedded here, one sentence
    per call, never the candidate pool itself. Ties broken by
    `position_id` ascending, so the result -- and therefore
    `decision_key`'s hash of it -- is deterministic regardless of
    `candidates`' own arrival order. `[]` in, `[]` out; `candidates` at or
    under `top_k` already is returned re-ranked, not merely truncated,
    since the render still lists nearest-first. A candidate absent from
    `position_vectors` (should not happen once `embed_positions` has run
    over the same map) is skipped rather than raising."""
    if not candidates:
        return []
    target_vector = _normalize(encode([target_text])[0])
    scored = [
        (position, float(np.dot(position_vectors[position["position_id"]], target_vector)))
        for position in candidates
        if position["position_id"] in position_vectors
    ]
    scored.sort(key=lambda pair: (-pair[1], pair[0]["position_id"]))
    return [position for position, _similarity in scored[:top_k]]


def select_candidates(
    target: UnresolvedTarget,
    positions_by_id: dict[str, dict[str, Any]],
    section_index: dict[str, list[str]],
    position_vectors: dict[str, np.ndarray],
    encode: Encoder,
    *,
    use_section_blocking: bool,
    top_k: int = CANDIDATE_TOP_K,
) -> list[dict[str, Any]]:
    """The candidate positions one call for `target` will see: the section
    bucket (`section_index[target.section]`) when `use_section_blocking` is
    on and that bucket is non-empty, else every position in
    `positions_by_id` -- the founder's own fallback rule on #651. Either
    way, narrowed to `top_k` by `_nearest_candidates` before it is ever
    rendered (module docstring: cost, not a second blocking decision).
    `position_vectors` is `embed_positions`'s own precomputed map, built
    once per run and shared across every target and both blocking arms."""
    bucket = section_index.get(target.section or "") if use_section_blocking else None
    pool = (
        [positions_by_id[position_id] for position_id in bucket if position_id in positions_by_id]
        if bucket
        else list(positions_by_id.values())
    )
    return _nearest_candidates(target.target, pool, position_vectors, encode, top_k)


RESIDUE_PROMPT = """An academic passage says it argues against the position below, in its own words -- no scholar or work is named distinctly enough to look up directly.

TARGET: "{target}"

Below are candidate positions from the same corpus's argument map, each an argument some author in the corpus actually makes:

{candidates}

Which of these, if any, is TARGET plainly opposing? Answer as JSON only, no other text:

{{"matches": ["pos-0007", ...]}}

Rules:
- Include a position only when TARGET is opposing what it claims, not merely sharing a topic with it.
- An empty list is the common, correct answer for most targets -- most opposed positions are not on this list at all. Never pick the closest one just because something must be chosen.
- Never invent a position id not shown above."""


def render_residue_prompt(target: str, candidates: Sequence[dict[str, Any]]) -> str:
    """The one prompt shape `resolve_target` and `decision_key` both key
    off of -- candidates listed nearest-first, each `[position_id]
    argument`."""
    listing = "\n".join(f"[{c['position_id']}] {c['argument']}" for c in candidates)
    return RESIDUE_PROMPT.format(target=target, candidates=listing or "(no candidates)")


def decision_key(prompt: str) -> str:
    """Content hash of the exact RENDERED prompt -- the decision log's key
    (module docstring): a re-run with the same target and the same
    candidate listing re-asks nothing, and anything that changes what gets
    rendered (target text, candidate set, `CANDIDATE_TOP_K`, the prompt
    wording itself) is, correctly, a different decision."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class ResidueDecisionsCorruptError(Exception):
    """Raised by `load_decisions` on a non-torn-tail corrupt line in the
    residue decision log -- the same healed-tail-vs-real-corruption split
    every other checkpoint log in this codebase (`axial.checkpoint`)
    applies."""

    def __init__(self, path: Path, line_no: int, cause: Exception) -> None:
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(f"corrupt residue decision log at {path}:{line_no}: {cause}")


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    """Every recorded decision, keyed by `decision_key` -- `{}` before the
    first run, the same shape `axial.merge_names.load_decisions` returns
    for its own log."""
    records = load_checkpoint_records(path, ResidueDecisionsCorruptError)
    return {record["key"]: record for record in records}


def resolve_target(
    target: UnresolvedTarget,
    candidates: Sequence[dict[str, Any]],
    client: LLMClient,
    *,
    mode: str,
    pass_name: str = PASS_NAME,
) -> dict[str, Any]:
    """One model call: does `target` describe opposition to any of
    `candidates`. Returns a decision record keyed by `decision_key` of the
    exact rendered prompt, carrying `chunk_id`/`source_id`/`target`/
    `section` (for the run log and the eventual store write, not consumed
    here), `mode` ("blocked"/"unblocked", reporting only -- never part of
    the key), the candidate ids actually offered, `matches` (filtered to
    ids that were actually offered -- an invented id is dropped, never
    repaired, the same rule `axial.argmap.build.extract_positions_for_slice`
    applies to invented handles), and -- only on failure -- `error`.

    A transport failure, a refused/malformed response, or a response
    shaped as something other than the expected object are all caught here
    and recorded as `error` rather than raised, so one bad call never
    aborts a multi-target sample or pass."""
    prompt = render_residue_prompt(target.target, candidates)
    candidate_ids = {candidate["position_id"] for candidate in candidates}
    record: dict[str, Any] = {
        "key": decision_key(prompt),
        "chunk_id": target.chunk_id,
        "source_id": target.source_id,
        "target": target.target,
        "section": target.section,
        "mode": mode,
        "candidate_ids": sorted(candidate_ids),
        "matches": [],
    }
    try:
        parsed = parse_model_json(client.complete(prompt, pass_name=pass_name))
        record["matches"] = sorted(
            {match for match in (parsed.get("matches") or []) if match in candidate_ids}
        )
    except (LLMError, httpx.HTTPError, ModelJsonError, AttributeError, TypeError) as exc:
        record["error"] = str(exc)[:200]
    return record


@dataclass(frozen=True)
class ModeResult:
    """One blocking arm's own sample outcome: how many of `total` targets
    resolved to >=1 position, how many calls this run actually made versus
    reused from `decisions_path`, token usage and wall time for THIS arm
    alone (its own `pass_name`, never mixed with the other arm's), and the
    full per-target `records` for a hand-check of matches."""

    mode: str
    total: int
    resolved: int
    calls_made: int
    calls_reused: int
    prompt_tokens: int
    completion_tokens: int
    wall_time_sec: float
    records: list[dict[str, Any]] = field(default_factory=list)


# Concurrent residue-resolve workers (issue #651 follow-up): the same
# I/O-bound shape (one blind completion call per unit of work, nothing else
# to overlap) `axial.argmap.build.run_extraction` already measured ~20x on
# the real corpus at this worker count -- reused directly rather than a
# second tuned number for what is the same call pattern.
WORKERS = BUILD_WORKERS


def run_residue_sample(
    targets: Sequence[UnresolvedTarget],
    positions: Sequence[dict[str, Any]],
    chunk_sections: dict[str, str],
    *,
    client: LLMClient,
    decisions_path: Path,
    encode: Encoder,
    modes: Sequence[str] = ("blocked", "unblocked"),
    top_k: int = CANDIDATE_TOP_K,
    workers: int = WORKERS,
    log: Callable[[str], None] = print,
) -> dict[str, ModeResult]:
    """Run `targets` through both blocking arms (or whichever `modes`
    names), against `decisions_path` as the shared, content-keyed decision
    log -- a decision already on disk under a rendered prompt's key is
    never re-asked, in this run or the next. Each mode gets its own
    `pass_name` (`residue_resolve_<mode>`) so `client.usage_for_pass`
    reports that arm's own tokens rather than a running total across both.

    `positions` is turned into `positions_by_id`, `section_index`, and
    `embed_positions`'s own precomputed embedding map once, shared by both
    arms -- building any of them per-arm would double the setup cost for no
    different result, since none depends on `mode`.

    **Threaded within a mode, sequential across modes** (issue #651 follow-
    up): candidate selection (local encoder, no network) for every target in
    a mode is done up front on this thread, in target order; only the actual
    paid calls run concurrently (`workers`), through a `ThreadPoolExecutor`
    with every checkpoint write happening back on this one collecting
    thread -- the same pattern `axial.argmap.build.run_extraction` already
    uses, so a mid-run kill can never race two threads onto the same
    decision-log line. Modes stay sequential at the outer loop specifically
    so the second mode's resume check sees every decision the first mode's
    run just wrote -- the founder's own observation that the two arms
    "naturally share a decision" whenever they land on the same candidate
    set depends on that ordering, not on running both arms at once.

    Records are re-assembled in `targets`' own order once the pool drains,
    not completion order, so a caller reading `ModeResult.records` sees the
    same sequence regardless of worker count or network timing. **One
    intentional gap:** two different targets that happen to render the
    identical prompt (same text, same candidate set) can each fire their own
    paid call if both are still pending when the pool starts, since neither
    thread sees the other's in-flight key -- a resumed run then dedupes
    correctly, because only the content on disk matters, but this run may
    pay for one extra, unnecessary call. Coordinating that across threads
    was not worth the added lock for a case this rare (no target pair in the
    #651 sample or from `find_unresolved_targets`'s own per-note dedup ever
    produced one)."""
    positions_by_id = {position["position_id"]: position for position in positions}
    section_index = build_section_index(positions, chunk_sections)
    position_vectors = embed_positions(positions, encode)
    decisions = load_decisions(decisions_path)

    results: dict[str, ModeResult] = {}
    for mode in modes:
        pass_name = f"{PASS_NAME}_{mode}"
        started = time.monotonic()

        prepared = [
            (
                target,
                select_candidates(
                    target,
                    positions_by_id,
                    section_index,
                    position_vectors,
                    encode,
                    use_section_blocking=(mode == "blocked"),
                    top_k=top_k,
                ),
            )
            for target in targets
        ]
        keys = [
            decision_key(render_residue_prompt(target.target, candidates))
            for target, candidates in prepared
        ]

        records: list[dict[str, Any] | None] = [None] * len(prepared)
        calls_reused = 0
        pending: list[int] = []
        for index, key in enumerate(keys):
            if key in decisions:
                records[index] = decisions[key]
                calls_reused += 1
            else:
                pending.append(index)

        calls_made = 0
        if pending:
            log(f"{mode}: {len(pending)} call(s) to make this run ({calls_reused} reused)")
            with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
                futures = {
                    pool.submit(
                        resolve_target,
                        prepared[index][0],
                        prepared[index][1],
                        client,
                        mode=mode,
                        pass_name=pass_name,
                    ): index
                    for index in pending
                }
                completed = 0
                for future in as_completed(futures):
                    index = futures[future]
                    record = future.result()
                    append_checkpoint_record(decisions_path, record)
                    decisions[record["key"]] = record
                    records[index] = record
                    calls_made += 1
                    completed += 1
                    log(
                        f"  {mode}: resolved {completed}/{len(pending)} "
                        f"(chunk {record['chunk_id']})"
                    )

        resolved = sum(1 for record in records if record and record.get("matches"))
        usage = client.usage_for_pass(pass_name) or {}
        results[mode] = ModeResult(
            mode=mode,
            total=len(targets),
            resolved=resolved,
            calls_made=calls_made,
            calls_reused=calls_reused,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            wall_time_sec=time.monotonic() - started,
            records=[record for record in records if record is not None],
        )
        log(
            f"{mode}: {resolved}/{len(targets)} resolved "
            f"({calls_made} call(s) made, {calls_reused} reused)"
        )
    return results


def mode_cost(client: LLMClient, result: ModeResult) -> float | None:
    """`estimate_cost` for one `ModeResult`, off the model this run's own
    `pass_name` actually resolved to -- `None` when that model carries no
    `PRICE_TABLE_USD_PER_1K` entry, the same "unpriced, not zero" reading
    `axial.llm.estimate_cost` itself gives an unpriced model."""
    model = client.model_for_pass(f"{PASS_NAME}_{result.mode}")
    return estimate_cost(model, result.prompt_tokens, result.completion_tokens)


def run_residue_pass(
    *,
    answers_dir: Path | None = None,
    names_dir: Path | None = None,
    map_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    encode: Encoder | None = None,
    pin: str | None = None,
    modes: Sequence[str] = ("blocked", "unblocked"),
    workers: int = WORKERS,
    guard: bool = True,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """`axial map residue` (issue #651): the full-corpus counterpart to
    `run_residue_sample`'s own calibration run -- every unresolved
    `arguing_against` target (`find_unresolved_targets`), both blocking
    arms, threaded (`run_residue_sample`'s own `workers`).

    Requires an argument map already built at this corpus's pin
    (`axial map build` first) -- `positions.jsonl` is the target set this
    pass matches against, and this pass writes its own decision log,
    `residue_decisions.jsonl`, as a SIBLING of it in the same `<map_dir>/
    <pin>/` directory, on purpose: `axial.materialize.build_note_store`
    derives `positions.jsonl`'s path from `residue_decisions_path` alone, so
    a caller never has to pass two paths that must always agree. Raises
    `MapNotBuiltError` (reused from `axial.argmap.ask`, not redefined here)
    when no map exists at this pin.

    `pin` defaults to `compute_corpus_pin(envelopes_dir, sources_dir)` -- the
    same pin `axial map build` writes under. `client`/`encode` default to
    `axial.llm.get_client()` and the real MiniLM encoder; both are injection
    seams for tests, the same shape every other `run_*` function in this
    codebase exposes.

    `guard` (default on) claims `<outdir>/RUNNING.pid`
    (`axial.pidguard.claim_single_instance`) for the run's duration -- the
    same lock `axial map build` takes over the identical directory, so a
    build and a residue pass can never write `positions.jsonl`/
    `residue_decisions.jsonl` out from under each other."""
    if answers_dir is None:
        answers_dir = _default_answers_dir(config_path)
    if names_dir is None:
        names_dir = default_names_dir(config_path)
    if map_dir is None:
        map_dir = default_map_dir(config_path)
    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)
    if sources_dir is None:
        sources_dir = default_sources_dir(config_path)
    if pin is None:
        pin = compute_corpus_pin(envelopes_dir, sources_dir)
    if client is None:
        client = get_client(config_path=config_path)
    if encode is None:
        encode = _default_encoder()

    outdir = Path(map_dir) / pin
    positions, _manifest = _load_map(outdir)  # raises MapNotBuiltError
    if guard:
        claim_single_instance(outdir)
    log(f"corpus pin {pin} -> {outdir} | positions {len(positions)}")

    unresolved, chunk_sections = find_unresolved_targets(answers_dir, names_dir)
    log(f"unresolved arguing_against targets: {len(unresolved)}")

    decisions_path = outdir / "residue_decisions.jsonl"
    results = run_residue_sample(
        unresolved,
        positions,
        chunk_sections,
        client=client,
        decisions_path=decisions_path,
        encode=encode,
        modes=modes,
        workers=workers,
        log=log,
    )

    union_resolved = len(
        {
            (record["chunk_id"], record["target"])
            for result in results.values()
            for record in result.records
            if record.get("matches")
        }
    )
    if guard:
        (outdir / "RUNNING.pid").unlink(missing_ok=True)

    return {
        "pin": pin,
        "outdir": str(outdir),
        "decisions_path": str(decisions_path),
        "positions_count": len(positions),
        "unresolved_count": len(unresolved),
        "union_resolved": union_resolved,
        "modes": {
            mode: {
                "resolved": result.resolved,
                "calls_made": result.calls_made,
                "calls_reused": result.calls_reused,
                "wall_time_sec": result.wall_time_sec,
                "cost_usd": mode_cost(client, result),
            }
            for mode, result in results.items()
        },
    }
