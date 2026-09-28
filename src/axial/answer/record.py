"""The analysis record and `axial brief run` (Phase-B stage 6, specs/PHASE-B.md
§7.3, §8 P0-8/P0-9, issue #257).

`run_brief` is the whole-engine orchestrator: it drives stages 1 (brief
interrogation), 3 (retrieval) and 4 (synthesis) exactly as
`axial.analyze.examine.run_examine` already drives stages 1+3 for
`axial brief examine`, then assembles and persists the §7.3 analysis record
-- the deliverable this slice adds on top of the three already-merged
slices (#252 interrogation, #253/#254 retrieval loop, #255/#256 evidence
assembly + synthesis).

On a `refuse` disposition (§7.2), stages 3-4 never run: `claims` and
`trajectory` are both empty, `model_by_pass` names only the interrogation
pass, and the record is still written -- a refusal is a COMPLETE run, not
an error (§7.2, §8 P0-1). This mirrors `run_examine`'s own inherited
short-circuit and extends it one stage further to skip synthesis too.

`coverage_map` (§7.7) and `confidence` (§7.4) ARE computed here (issue
#400): `build_record` calls `axial.validators.coverage.compute_coverage_map`
over the record's own claims, then derives `confidence` from that map with
`compute_confidence` -- both zero-model-call, deterministic functions the
analysis-validators feature (issue #260) already built and exposed. Neither
was wired into `build_record` until #400; the coverage_map/confidence
release gate (`validate_coverage_and_confidence`, also #260) is unaffected,
since it reads whatever a record persists rather than recomputing it.

`counter_position` (§7.8) IS computed here (issue #399):
`build_record` calls `axial.analyze.synthesis.generate_counter_position` over
the record's own just-parsed claims, mirroring how `coverage_map`/
`confidence` are computed from the same claims. That function reuses
`axial.validators.counter_position.detect_contested` verbatim to decide
whether the brief is contested (zero model calls when it is not), and, when
it is, makes one bounded follow-up model call under its own
`COUNTER_POSITION_GENERATE_PASS_NAME` -- grounded only in a whitelist of
this run's own opposing evidence, never a synthesised-from-nothing stance
(see that function's own docstring for the anti-fabrication design). A
`refuse` disposition's empty claim list is trivially uncontested, so it
still costs zero model calls, exactly as it did with the placeholder.

**A counter-position GENERATION failure never discards the run (issue
#558).** A real paid eval run once died at exactly this call, after
interrogation, fourteen retrieval turns and a 189k-character synthesis had
all already succeeded -- because `generate_counter_position` raised, no
record was written at all, and every earlier stage's paid work was thrown
away with it. `build_record` now catches `CounterPositionGenerationError`
around this call and persists the record anyway, with `counter_position`
marked `failed_counter_position_section(reason)`: a third §7.8 state,
distinguishable from both legitimate outcomes, never laundered into
`corpus_one_sided`. See `build_record`'s own docstring for the full seam.

`source_usage` (§7.13/P0-13, issue #265) IS computed here: `build_record`
assembles every other §7.3 field first, then calls
`axial.answer.source_usage.compute_source_usage` over the record-so-far
(its own `claims`/`trajectory`/`interrogation.disposition`) to fill it in --
zero model calls, pure vault reads plus arithmetic (see that module).

`cost` (§7.14, issue #363) is the token/dollar-cost analogue of
`model_by_pass`, computed here the same way: `build_record` reads each named
pass's accumulated token usage off `client.usage_for_pass` (folded in by the
provider as `run_brief`'s stages made their calls) and prices it against
that pass's resolved model (`axial.llm.estimate_cost`, `PRICE_TABLE_USD_PER_1K`).
An unpriced model's pass carries a `null` `usd` figure, never zero or a
crash (issue #363's own acceptance criterion); the run `total_usd` sums
whatever per-pass costs ARE known, and is itself `null` only when none are.

The rendered markdown answer (§7.10, issue #261) is written alongside the
JSON: `run_brief` calls `persist_markdown`, which renders the just-built
record through `axial.answer.render.render_markdown` (a pure function of
the record -- no model call, no vault read, no clock) and writes it to
`<analyses_dir>/<brief_id>.md`. Since issue #732, `persist_markdown` first
resolves each ground's citation for this deployment's `AXIAL_CITATION_MODE`
(`axial.service.citation.render_record_for_serving`, the same function
`GET /asks/{id}/paper` calls at serve time) on a deep copy of the record --
`render_markdown` itself stays pure; the record `run_brief` persists as
JSON and returns to its own caller never carries a quote either way.

`evidence` (§7.3, issue #545) carries `assembled_count`/`composed_count`:
how many notes the retrieval loop assembled (`EvidenceSet.chunk_ids`) versus
how many `compose_prompt`'s `synthesis.evidence_char_budget` walk actually
let into the synthesis prompt (`ClaimGraph.evidence_composed_count`).
Replaying seven persisted smoke runs, 506 notes were assembled and 146
reached a model -- 360 were paid for and read by nothing, and neither the
record nor the loop could see it before this field existed. Operator-facing
only: nothing about this reaches a prompt, the same discipline `synthesis.
evidence_char_budget` itself is held to (issue #505). Both default to 0,
correct on a `refuse` disposition where stage 3/4 never ran.
"""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.analyze.assembly import assemble_evidence
from axial.analyze.synthesis import (
    Claim,
    CounterPositionGenerationError,
    CounterPositionResult,
    failed_counter_position_section,
    generate_counter_position,
    resolve_lens,
    synthesize,
)
from axial.answer.render import render_markdown
from axial.answer.run_report import PassClock, build_run_report, persist_run_report
from axial.answer.source_usage import compute_source_usage
from axial.argmap.ask import DECOMPOSE_PASS_NAME, AskResult, run_map_ask_for_brief
from axial.argmap.vocabulary_join import (
    ALL_REASONS,
    DEFAULT_VOCABULARY_COLUMN,
    PER_CATEGORY_CAP,
    VocabularyJoinResult,
)
from axial.brief.fork import ForkAnswer, ForkCheckResult
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, interrogate
from axial.eval.corpus_pin import resolve_pin_id
from axial.llm import (
    COUNTER_POSITION_GENERATE_PASS_NAME,
    INTERROGATE_PASS_NAME,
    SYNTHESIZE_PASS_NAME,
    EventCallback,
    LLMClient,
    emit_event,
    usage_and_cost_by_pass,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_analyses_dir, default_vault_dir
from axial.validators.coverage import compute_confidence, compute_coverage_map

# The trivial "nothing measured" fork-check result `build_record` substitutes
# when its caller passes none -- every existing `build_record` call site
# (there are many, in tests and in `run_examine`'s own future callers) stays
# correct without threading a fork-check through it.
_NO_FORK = ForkCheckResult(is_fork=False, measured=False)


class AnswerError(Exception):
    """Base class for all stage-6 (analysis-record) errors."""


# The named retrieval arms `run_brief`'s own `arm` argument recognises
# (issue #807, `plans/derived-vocabulary/03-two-notes-meet-at-a-shared-
# group.md`'s "the join is a step, not a tool"): `MAP_ARM` is the
# argument-map path with no vocabulary step (`use_vocabulary=False` --
# issue #572), `MAP_VOCAB_ARM` adds the vocabulary step onto the same map
# walk (`use_vocabulary=True`). The third arm, the name-layer loop, was
# retired with the vault's name pages (DEC-75, issue #853).
MAP_ARM = "map"
MAP_VOCAB_ARM = "map+vocab"
KNOWN_ARMS = (MAP_ARM, MAP_VOCAB_ARM)


class UnknownArmError(AnswerError):
    """Raised when `run_brief`'s own `arm` names none of `KNOWN_ARMS`
    (issue #807). Refused up front, before interrogation ever runs -- the
    same "fail before any call is made" discipline the corpus-pin
    resolution already follows -- rather than silently falling back to a
    default arm, which would spend a real interrogation call on a typo
    before anyone learned the arm was never recognised."""

    def __init__(self, arm: str):
        self.arm = arm
        super().__init__(
            f"unknown retrieval arm {arm!r} -- the arms that exist are "
            f"{', '.join(KNOWN_ARMS)}"
        )


def _interrogation_conclusion_message(result: InterrogationResult) -> str:
    """The plain-language half of the interrogation stage's own "outcome"
    event (issue #533): what interrogation concluded, worded from
    `InterrogationResult`'s own fields, never from the raw prompt or the
    model's own JSON shape. A `refuse` disposition states the reason
    (§7.2's own `refusal.reason`); any other disposition states how many
    premises/bounds interrogation found -- the two facts §7.2 says this
    stage produces."""
    if result.disposition == "refuse":
        reason = (result.refusal or {}).get("reason") or "the question is out of scope"
        return f"interrogation concluded: this cannot be answered from the corpus -- {reason}"
    n_premises = len(result.premises_found)
    n_bounds = len(result.bounds_applied)
    premise_word = "premise" if n_premises == 1 else "premises"
    bound_word = "bound" if n_bounds == 1 else "bounds"
    return f"interrogation concluded: found {n_premises} {premise_word}, applied {n_bounds} {bound_word}"


def _brief_to_dict(brief: Brief) -> dict[str, Any]:
    """The brief, verbatim (§7.1, §7.3: "the brief (§7.1), verbatim").
    `weights` (issue #639) is `{}`, never `None`, when the brief carried
    none -- `Brief.weights` already defaults that way, so this is a
    straight passthrough, not a normalisation. `fork_answer` (issue #649) is
    `None`, `Brief.fork_answer`'s own default, when the brief carried none."""
    return {
        "brief_id": brief.brief_id,
        "case": brief.case,
        "request": brief.request,
        "lens": brief.lens,
        "weights": dict(brief.weights),
        "fork_answer": dict(brief.fork_answer) if brief.fork_answer is not None else None,
    }


def _claim_to_dict(claim: Claim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "text": claim.text,
        "kind": claim.kind,
        "grounds": [{"ref_type": g.ref_type, "ref_id": g.ref_id} for g in claim.grounds],
        "confidence": claim.confidence,
        "names_touched": list(claim.names_touched),
    }


def _vocabulary_to_dict(
    result: VocabularyJoinResult, assembled_chunk_ids: Sequence[str]
) -> dict[str, Any]:
    """The vocabulary step's own audit trail (issue #807), the `map+vocab`
    arm's counterpart to `landed`/`corridor` above: the column and level it
    joined on, the per-category cap it enforced, and every category the
    landed set's own notes reached -- including one that contributed zero
    neighbours (a real, reached, singleton category, `CategoryReach`'s own
    docstring), never silently dropped from this list.

    **Two counts per category, because they differ by a factor of six.**
    `offered_note_count` is what the join handed to assembly; `assembled_
    note_count` is how many of those survived `assemble_map_evidence`'s
    SHARED cap of 90, which is a different cap from this block's own
    per-category `cap` and its `cap_applied` flag -- a category can be well
    under 20 and still lose most of its notes to the shared budget, so the
    two counts differing is not evidence the per-category cap bit. The
    first live run offered 240 notes across twelve categories and assembled
    38 of them. A single `note_count` invited exactly one misreading -- that
    the vocabulary step contributed 240 passages to an answer built from 90
    -- and issue #809 reads these figures to decide whether the derived
    vocabulary pays. `source_count` stays a count over what was OFFERED,
    which is what the per-category cap selected on.

    **`reasons` records the category-assignment outcome of every landed
    note (issue #822).** One count per landed note, keyed on `ALL_REASONS`
    with every reason present even at zero: `assigned` reached a category,
    `refused` is the model declining, `out-of-scheme` is an answer naming
    no committed category, `not-found` is a note never assigned in this
    column at all. `assigned` is not the same as "produced an edge": an
    assigned note whose category is a singleton, or whose every neighbour
    position is already excluded, is counted `assigned` and contributes
    nothing. Without it a thin run is unreadable -- a scheme that
    does not fit this corpus and a column half of whose notes were never
    assigned produce the same small `categories` list, which is exactly the
    conflation §7.18 records as having cost #805 a 50.7%-vs-88.5%
    misreading. A zero is a measurement; an absent key would not be."""
    assembled = set(assembled_chunk_ids)
    return {
        "column": result.column,
        "level": result.level,
        "cap": result.cap,
        "reasons": {reason: int(result.reasons.get(reason, 0)) for reason in ALL_REASONS},
        "categories": [
            {
                "category_id": category.category_id,
                "name": category.category_name,
                "offered_note_count": len(category.chunk_ids),
                "assembled_note_count": sum(
                    1 for chunk_id in category.chunk_ids if chunk_id in assembled
                ),
                "source_count": category.source_count,
                "cap_applied": category.cap_applied,
            }
            for category in result.categories
        ],
    }


def _map_retrieval_to_dict(ask_result: AskResult) -> dict[str, Any]:
    """The argument-map path's own audit trail (issue #572, PR 4 of 4): the
    stated arguments, which positions landed and at what score, which
    positions the corridor reached and the relation labels that pulled them
    in, and the assembled chunk ids -- exactly what a §7.6 trajectory
    audits for the name-layer loop, in the map's own terms. The map path
    makes no name-layer tool call and so produces no trajectory of its own;
    this is the honest substitute, never a trajectory entry manufactured to
    keep a downstream reader fed.

    `pin` (issue #583) is `ask_result.pin` verbatim -- the map directory's
    own name, whatever `run_map_ask_for_brief` actually resolved and read,
    whether that came from an explicit override or the corpus-computed
    default. Without it two runs against two different maps of the same
    corpus (a rebuild after a prompt change, a `--force` rotation) produce
    records indistinguishable on their face.

    `vocabulary` (issue #807) is present ONLY when `ask_result.vocabulary`
    is not `None` -- the `map+vocab` arm ran the vocabulary step -- and
    absent entirely on a plain `map` run, never a fabricated empty block.
    That is the observable the outer acceptance test reads to tell the two
    map arms apart: `"vocabulary" in record["map_retrieval"]`."""
    payload: dict[str, Any] = {
        "used": True,
        "pin": ask_result.pin,
        "asks": list(ask_result.asks),
        "landed": [
            {"position_id": position.position_id, "score": position.score}
            for position in ask_result.landed
        ],
        "corridor": [
            {"position_id": position.position_id, "labels": list(position.labels)}
            for position in ask_result.corridor
        ],
        "assembled_chunk_ids": list(ask_result.assembled_chunk_ids),
    }
    if ask_result.vocabulary is not None:
        payload["vocabulary"] = _vocabulary_to_dict(
            ask_result.vocabulary, ask_result.assembled_chunk_ids
        )
    return payload


@dataclass(frozen=True)
class BriefRunResult:
    """`run_brief`'s own return shape: the persisted §7.3 record, the path
    it was written to, the path of the rendered markdown answer written
    alongside it (§7.10), and the §7.15 run report plus the path IT was
    written to (issue #491). The report is a separate artifact rather than a
    field on the record, because §7.3's shape is locked and the report is a
    derived view of it."""

    record: dict[str, Any]
    path: Path
    markdown_path: Path
    report: dict[str, Any]
    report_path: Path


def build_record(
    brief: Brief,
    interrogation_result: InterrogationResult,
    *,
    corpus_pin: str,
    lens: str,
    claims: list[Claim],
    trajectory: list[dict[str, Any]],
    model_by_pass: dict[str, str],
    client: LLMClient,
    vault_dir: Path | None = None,
    clock: PassClock | None = None,
    evidence_assembled_count: int = 0,
    evidence_composed_count: int = 0,
    map_retrieval: dict[str, Any] | None = None,
    session_id: str | None = None,
    fork_result: ForkCheckResult | None = None,
    fork_answer: ForkAnswer | None = None,
    fork_effect: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Assemble the §7.3 analysis record. `claims`/`trajectory` are the
    caller's already-computed stage-4/stage-3 output (empty on a `refuse`
    disposition). `evidence_assembled_count`/`evidence_composed_count`
    (issue #545) default to 0, correct for a `refuse` disposition where
    stage 3/4 never ran, exactly like `claims`/`trajectory` defaulting empty
    on that path -- a real run passes both from `EvidenceSet.chunk_ids` and
    `ClaimGraph.evidence_composed_count` (`run_brief`).

    `map_retrieval` (issue #572, PR 4 of 4) is `None` on the default
    name-layer path and on `refuse` -- an explicit, honest absence, never a
    trajectory-shaped stand-in -- and `_map_retrieval_to_dict`'s own dict
    when `run_brief(use_map=True)` retrieved through the argument map
    instead. `trajectory` is genuinely empty on that path (the map makes no
    name-layer tool call), which every trajectory reader downstream
    (`coverage_map`, `source_usage`, the run report) already handles as a
    fact about a run that queried no name, not a bug -- the same path a
    `refuse` disposition's empty trajectory already takes.

    `session_id` (issue #534, §7.3, additive) is `None` for a plain
    `axial brief run` over a hand-authored brief -- there is no session --
    and the joining id `axial.ask` threads through every turn of an
    interactive `axial ask` session otherwise. It is recorded verbatim and
    never inspected here; nothing about it changes what runs.

    `counter_position` (§7.8) is computed for real (issue #399)
    from the record's own claims via `generate_counter_position` -- zero
    model calls on an uncontested brief, one bounded follow-up call
    otherwise (see that function's own docstring). When that call actually
    ran (`CounterPositionResult.model_called`), its pass name is folded into
    THIS record's own `model_by_pass`/`cost` -- never the caller's
    `model_by_pass` argument, which `run_brief` built before this generation
    step ever ran and cannot know in advance whether it will fire (contested-
    ness is a property of the claim graph `run_brief` doesn't inspect) --
    mirroring the existing "a pass is named only when it really ran"
    contract retrieve/synthesize already carry on a `refuse` disposition.
    `coverage_map` (§7.7) and `confidence` (§7.4) are computed for real
    (issues #400 and #490) from the record's own claims AND trajectory --
    `compute_coverage_map` first, then `compute_confidence` over its result,
    both zero-model-call and deterministic. The trajectory is what scopes the
    map to the names this brief is about rather than every name its evidence
    mentions (see `axial.validators.coverage`). `source_usage` (§7.13) is computed over the record's
    own `claims`/`trajectory`/`interrogation` -- assembled last here, once
    every field it reads is already in the dict. `cost` (§7.14, issue #363)
    reads `client`'s accumulated per-pass token usage
    (`axial.llm.usage_and_cost_by_pass`, promoted there by issue #591 so
    `axial.paper.record` can share it) -- `client` is needed for that AND
    for `generate_counter_position`'s own possible model call.

    **A `CounterPositionGenerationError` never aborts this function (issue
    #558).** By the time this call runs, interrogation, retrieval and
    synthesis have already succeeded and already cost real money -- a real
    paid eval run was once destroyed in full because this stage's own raise
    propagated all the way out and nothing had been persisted. Catching it
    here, at the exact call site, means every caller of `build_record` (and
    so `run_brief`, and so `axial.brief.sweep`) gets the resilience for free
    without touching its own error handling: the record is still assembled
    and returned, with `counter_position` marked `failed_counter_position_
    section` -- distinguishable from both legitimate §7.8 outcomes, never
    laundered into `corpus_one_sided`. `generate_counter_position` itself is
    unchanged and still raises (every existing unit test asserting that
    still passes); only this call site decides to catch it. `model_called`
    is still `True` in this branch: a real model call was attempted (the
    brief was contested, which is the only way this call is ever reached at
    all), so its pass name still belongs in `model_by_pass`/`cost` exactly
    as it would have on success.

    `fork_result`/`fork_answer`/`fork_effect` (issue #649, all `None` for
    every caller before this field existed) are the intake fork-check's own
    disclosure (module docstring): what it measured and asked, what the
    analyst answered (or `None`, unanswered), and what the compiled
    constraint actually did to the assembled evidence set. `fork_result`
    defaults to the trivial "nothing measured" result (`_NO_FORK`) so every
    existing caller keeps recording an honest, empty `intake_fork` block.
    `intake_fork.failed` is `None` on that shape and on every real verdict;
    `run_brief` is the sole caller that ever supplies a `fork_result` with
    `failed` set -- when the check itself could not be completed, or when a
    genuine constraint reached retrieval and still came back with nothing
    to cite (issue #649's own live-run finding, round 3: guidance is guidance,
    it must never be able to silently end a run with an empty evidence set)."""
    clock = clock if clock is not None else PassClock()
    claim_dicts = [_claim_to_dict(claim) for claim in claims]
    coverage_map = compute_coverage_map(claim_dicts, trajectory=trajectory, vault_dir=vault_dir)
    # The counter-position pass is timed here rather than in `run_brief`
    # because only this function knows whether it fired at all: contestedness
    # is a property of the claim graph, and an uncontested brief makes zero
    # calls under that pass name (§7.8). A caller that passed no clock gets a
    # throwaway one, so this reads the same either way.
    with clock.time(COUNTER_POSITION_GENERATE_PASS_NAME):
        try:
            counter_position_result = generate_counter_position(
                claim_dicts, brief, client=client, trajectory=trajectory, vault_dir=vault_dir
            )
        except CounterPositionGenerationError as exc:
            print(
                "build_record: counter-position generation failed -- persisting the "
                f"record anyway with the section marked failed: {exc}",
                file=sys.stderr,
            )
            counter_position_result = CounterPositionResult(
                section=failed_counter_position_section(str(exc)), model_called=True
            )
    record_model_by_pass = dict(model_by_pass)
    if counter_position_result.model_called:
        record_model_by_pass[COUNTER_POSITION_GENERATE_PASS_NAME] = client.model_for_pass(
            COUNTER_POSITION_GENERATE_PASS_NAME
        )
    fork_result = fork_result if fork_result is not None else _NO_FORK
    record = {
        "brief_id": brief.brief_id,
        "brief": _brief_to_dict(brief),
        "session_id": session_id,
        "corpus_pin": corpus_pin,
        "lens": lens,
        "interrogation": interrogation_result.to_dict(),
        "claims": claim_dicts,
        "counter_position": counter_position_result.section,
        "coverage_map": coverage_map,
        "confidence": compute_confidence(coverage_map),
        "evidence": {
            "assembled_count": evidence_assembled_count,
            "composed_count": evidence_composed_count,
        },
        "trajectory": list(trajectory),
        "map_retrieval": map_retrieval,
        "intake_fork": {
            "measured": fork_result.measured,
            "is_fork": fork_result.is_fork,
            "failed": fork_result.failed,
            "concept": fork_result.concept,
            "kind": fork_result.kind,
            "question": fork_result.question,
            "options": [
                {
                    "label": option.label,
                    "drop_source_ids": list(option.drop_source_ids),
                    "per_source_cap": option.per_source_cap,
                    "guidance": option.guidance,
                }
                for option in fork_result.options
            ],
            "answer": (
                {"option": fork_answer.option, "free_text": fork_answer.free_text}
                if fork_answer is not None
                else None
            ),
            "effect": fork_effect,
        },
        "model_by_pass": record_model_by_pass,
        "cost": usage_and_cost_by_pass(client, record_model_by_pass),
    }
    record["source_usage"] = compute_source_usage(record, vault_dir=vault_dir)
    return record


def persist_record(
    brief_id: str,
    record: dict[str, Any],
    *,
    analyses_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> Path:
    """Write `record` to `<analyses_dir>/<brief_id>.json` (§7.3), keyed
    deterministically on `brief_id` exactly like
    `axial.brief.interrogate.persist_interrogation` -- re-running the same
    brief overwrites the same file rather than accumulating one per run."""
    if analyses_dir is None:
        analyses_dir = default_analyses_dir(config_path)
    analyses_dir = Path(analyses_dir)
    analyses_dir.mkdir(parents=True, exist_ok=True)
    path = analyses_dir / f"{brief_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def persist_markdown(
    brief_id: str,
    record: dict[str, Any],
    *,
    analyses_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    vault_dir: Path | None = None,
) -> Path:
    """Render `record` to markdown (§7.10, `axial.answer.render.render_markdown`)
    and write it to `<analyses_dir>/<brief_id>.md`, alongside the JSON record
    written by `persist_record` -- keyed on `brief_id` the same way, so
    re-running the same brief overwrites the same file rather than
    accumulating one per run.

    Issue #732: `axial ask`/`axial brief run` writes this file at the end
    of a run, the same way `GET /asks/{id}/paper` serves the record at
    request time (issue #690) -- so citations are resolved here through
    the SAME `axial.service.citation.render_record_for_serving` the API
    calls, on a deep copy of `record`, never `record` itself: `persist_record`
    (called by `run_brief` just before this) has already written the
    unresolved JSON, and the record `run_brief` returns to its own caller
    must stay exactly what `build_record` produced, quote-free regardless
    of citation mode. `citation_mode` reads `AXIAL_CITATION_MODE` the same
    way the API does, defaulting to `passage` (issue #785) -- a local run is
    unconfigured exactly like a fresh API deployment. Imported lazily so the base
    pipeline does not require the optional `service` dependency group
    (mirrors `axial.cli`'s own `_publish` handler, issue #684)."""
    from axial.service.citation import render_record_for_serving, resolve_citation_mode

    if analyses_dir is None:
        analyses_dir = default_analyses_dir(config_path)
    analyses_dir = Path(analyses_dir)
    analyses_dir.mkdir(parents=True, exist_ok=True)
    path = analyses_dir / f"{brief_id}.md"
    resolved_vault_dir = vault_dir if vault_dir is not None else default_vault_dir(config_path)
    rendered_record = render_record_for_serving(
        copy.deepcopy(record),
        citation_mode=resolve_citation_mode(),
        vault_dir=resolved_vault_dir,
    )
    path.write_text(render_markdown(rendered_record), encoding="utf-8")
    return path


def run_brief(
    brief: Brief,
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    analyses_dir: Path | None = None,
    runs_dir: Path | None = None,
    evals_dir: Path | None = None,
    lenses_dir: Path | None = None,
    cases_dir: Path | None = None,
    case_id: str | None = None,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
    use_map: bool = False,
    arm: str | None = None,
    map_dir: Path | None = None,
    sources_dir: Path | None = None,
    map_pin: str | None = None,
    vocabulary_column: str = DEFAULT_VOCABULARY_COLUMN,
    vocabulary_level: int | None = None,
    vocabulary_dir: Path | None = None,
    vocabulary_cap: int = PER_CATEGORY_CAP,
    on_event: EventCallback | None = None,
    session_id: str | None = None,
    on_fork: Callable[[ForkCheckResult], ForkAnswer | None] | None = None,
) -> BriefRunResult:
    """Run the full engine (stages 1-6) over `brief` and persist the §7.3
    analysis record to `<analyses_dir>/<brief_id>.json` plus the §7.15 run
    report to `<runs_dir>/<brief_id>.json`, returning both.

    `session_id` (issue #534, §7.3, additive) is forwarded verbatim to
    `build_record`: `None` for a plain brief run, or the joining id an
    `axial ask` session threads through its own turns.

    `on_event` (issue #533) is the one event seam the whole engine narrates
    itself through: called `on_event(plain_sentence, detail)` as each stage
    starts and concludes -- interrogating the question and what it
    concluded, each retrieval turn (`axial.retrieve.loop`'s own per-turn
    events), assembling passages, writing the answer, and checking it --
    `None` (the default) falls back to printing the same sentence to
    stderr (`axial.llm.emit_event`), so a caller that wires nothing loses
    no real-time visibility versus before this issue.

    **Per-pass wall clock is captured here and nowhere else** (§7.15): only
    the running process holds it, so each stage is timed as it is driven and
    the report's total is the sum of those figures rather than a second
    stopwatch around the whole call.

    `case_id` joins this run to its §9.3 sim case (`evals/cases/sim/
    <case_id>.json`) so the report can score the mechanical retrieval-hit
    oracle. It is the brief file's own stem at every call site, since that
    is the join the case set uses; a brief with no case file simply has no
    oracle and the report says so. The report makes NO model call: the two
    judged accuracy numbers are left not-scored here and are run separately
    by a caller that wants to pay for them.

    The corpus pin (§7.12) is resolved FIRST, before any model call -- it is
    a configuration-level precondition of the run, not something the brief's
    own content affects, so a misconfigured install fails fast rather than
    after spending an interrogation call.

    On a `refuse` disposition (§7.2), stages 3 (retrieval) and 4
    (synthesis) never run: `claims` and `trajectory` are both empty and
    `model_by_pass` names only the interrogation pass. This is a COMPLETE
    run -- the record is still written and this function still returns
    normally; translating that into exit 0 is the CLI's job.

    **Retrieval is always the argument map now (DEC-75)**: the name-layer
    tool loop (`find_names`/`get_name`/`name_neighbors`/`who_cites`/
    `who_argues_against`/`where_names_meet`/`names_arguing_against`/
    `opposition_pairs` as loop tools, and the name pages they walked) was
    retired with the vault's name pages -- issue #853. Stage 3 is always
    `axial.argmap.ask.run_map_ask_for_brief`'s door/landing/corridor/
    assembly walk, which hands back an ordered list of chunk ids that feeds
    the same `assemble_evidence`/`synthesize` call either arm ever used.
    `use_map`/`arm` (issue #572/#807) are kept as parameters so
    `axial.brief.sweep`/`axial.brief.smoke`/the CLI do not need their own
    signatures to change, but neither one selects a different retrieval
    path any more -- `arm`, when given, must still name one of `KNOWN_ARMS`
    (`"map"` or `"map+vocab"`; `"name"` now raises `UnknownArmError`, the
    same as any other unrecognised string) and only ever decides whether
    the vocabulary join runs. `map_dir`/`sources_dir`/`map_pin` are
    forwarded verbatim.

    `brief.weights` (issue #639) has no retrieval effect on the map path
    (`run_map_ask_for_brief` builds its own ordered chunk list and never
    reaches the round-robin `brief.weights` used to bite on the retired
    name-layer path) -- it is still recorded verbatim in the persisted
    record (§7.1).

    found, it is recorded in the persisted record's `intake_fork` block with
    `answer: null` -- there is no fork left to answer.

    `arm` (issue #807, one of `KNOWN_ARMS`, `None` by default) is the named
    retrieval arm this run takes: `arm="map"` (or `None`, the default) is
    the map walk with no vocabulary step, `arm="map+vocab"` adds the
    vocabulary step (`axial.argmap.vocabulary_join.vocabulary_neighbours`)
    onto the same map walk, between the corridor and assembly. A string
    naming none of `KNOWN_ARMS` raises `UnknownArmError` immediately, before
    interrogation or any other call -- the join is a deterministic step in
    the map arm's own walk (module docstring's "the join is a step, not a
    tool"), never a tool a caller could otherwise silently mis-name.
    **All four `vocabulary_*` arguments are forwarded to `run_map_ask_for_
    brief` verbatim (issue #822)**, and every one of them is ignored on any
    arm but `map+vocab`: which column to join on, which level of its
    scheme, where the built vocabulary lives, and how many neighbours one
    category may hand to assembly. The first cut carried `vocabulary_dir`
    alone, which was the wrong one to pick -- the live run showed the cap
    binding on every category, so it is the knob a measurement actually
    turns, and #809 turns it. Their defaults are `run_map_ask_for_brief`'s
    own, named here from the same constants rather than restated as
    literals."""
    if arm is not None and arm not in KNOWN_ARMS:
        raise UnknownArmError(arm)
    # `use_map` is accepted but no longer selects a retrieval path (DEC-75,
    # issue #853): the name-layer arm it used to toggle away from is gone,
    # so the map walk always runs. Kept as a parameter only so
    # `axial.brief.sweep`/`axial.brief.smoke`/the CLI keep their existing
    # signatures.
    resolved_use_vocabulary = arm == MAP_VOCAB_ARM

    corpus_pin = resolve_pin_id(evals_dir)
    clock = PassClock()

    emit_event(
        on_event, "interrogating the question", {"stage": "interrogate", "brief_id": brief.brief_id}
    )
    with clock.time(INTERROGATE_PASS_NAME):
        interrogation_result = interrogate(brief, client=client, vault_dir=vault_dir)
    emit_event(
        on_event,
        _interrogation_conclusion_message(interrogation_result),
        {"stage": "interrogate", **interrogation_result.to_dict()},
    )
    model_by_pass: dict[str, str] = {
        INTERROGATE_PASS_NAME: client.model_for_pass(INTERROGATE_PASS_NAME)
    }

    if interrogation_result.disposition == "refuse":
        lens = resolve_lens(brief.lens, lenses_dir=lenses_dir)
        claims: list[Claim] = []
        trajectory: list[dict[str, Any]] = []
        evidence_assembled_count = 0
        evidence_composed_count = 0
        map_retrieval: dict[str, Any] | None = None
        fork_result: ForkCheckResult = _NO_FORK
        fork_answer: ForkAnswer | None = None
        fork_effect: dict[str, int] | None = None
    else:
        # No fork-check and no name-layer trajectory any more (DEC-75,
        # issue #853): the retired name-layer path was the only caller of
        # both. `fork_result`/`fork_answer`/`fork_effect` stay in the
        # returned record shape, at the same "nothing was asked" values a
        # `refuse` disposition already reports, so no downstream reader
        # (coverage_map, source_usage, the run report) needs a new case.
        fork_result = _NO_FORK
        fork_answer = None
        fork_effect = None
        emit_event(on_event, "retrieving evidence through the argument map", {"stage": "retrieve"})
        with clock.time(DECOMPOSE_PASS_NAME):
            ask_result = run_map_ask_for_brief(
                brief,
                client=client,
                map_dir=map_dir,
                envelopes_dir=envelopes_dir,
                sources_dir=sources_dir,
                config_path=config_path,
                pin=map_pin,
                use_vocabulary=resolved_use_vocabulary,
                vocabulary_column=vocabulary_column,
                vocabulary_level=vocabulary_level,
                vocabulary_dir=vocabulary_dir,
                vocabulary_cap=vocabulary_cap,
            )
        model_by_pass[DECOMPOSE_PASS_NAME] = client.model_for_pass(DECOMPOSE_PASS_NAME)
        evidence_ids: list[str] = list(ask_result.assembled_chunk_ids)
        emit_event(
            on_event,
            f"found {len(evidence_ids)} passage(s) through the argument map",
            {"stage": "retrieve", "evidence_count": len(evidence_ids)},
        )
        # The map path makes no name-layer tool call, so it has no §7.6
        # trajectory of its own -- an honest empty list, never a
        # fabricated one built to keep a downstream reader fed. Every
        # trajectory consumer (coverage_map, source_usage, the run
        # report) already treats an empty trajectory as "this run
        # queried no name", the same fact a `refuse` disposition's
        # empty trajectory already states; what the map path actually
        # did is recorded in `map_retrieval` instead.
        trajectory = []
        map_retrieval = _map_retrieval_to_dict(ask_result)

        # Evidence assembly is timed under the synthesis pass it feeds: it
        # makes no model call of its own and has no pass name to report
        # under, and leaving it untimed would make the per-pass figures sum
        # to less than the run really took.
        with clock.time(SYNTHESIZE_PASS_NAME):
            emit_event(
                on_event,
                "assembling passages",
                {"stage": "assemble", "evidence_ids": len(evidence_ids)},
            )
            evidence = assemble_evidence(evidence_ids, vault_dir=vault_dir)
            emit_event(
                on_event,
                f"assembled {len(evidence.chunk_ids)} passage(s)",
                {"stage": "assemble", "assembled_count": len(evidence.chunk_ids)},
            )
            emit_event(on_event, "writing the answer", {"stage": "synthesize"})
            claim_graph = synthesize(
                evidence,
                brief,
                client=client,
                vault_dir=vault_dir,
                lenses_dir=lenses_dir,
                config_path=config_path,
                question_scope=interrogation_result.question_scope,
            )
            emit_event(
                on_event,
                f"wrote the answer -- {len(claim_graph.claims)} claim(s)",
                {"stage": "synthesize", "claim_count": len(claim_graph.claims)},
            )
        model_by_pass[SYNTHESIZE_PASS_NAME] = client.model_for_pass(SYNTHESIZE_PASS_NAME)

        lens = (
            claim_graph.lens
            if claim_graph is not None
            else resolve_lens(brief.lens, lenses_dir=lenses_dir)
        )
        claims = claim_graph.claims if claim_graph is not None else []
        evidence_assembled_count = len(evidence.chunk_ids)
        evidence_composed_count = (
            claim_graph.evidence_composed_count if claim_graph is not None else 0
        )

    emit_event(on_event, "checking the answer", {"stage": "check"})
    record = build_record(
        brief,
        interrogation_result,
        corpus_pin=corpus_pin,
        lens=lens,
        claims=claims,
        trajectory=trajectory,
        model_by_pass=model_by_pass,
        client=client,
        vault_dir=vault_dir,
        clock=clock,
        evidence_assembled_count=evidence_assembled_count,
        evidence_composed_count=evidence_composed_count,
        map_retrieval=map_retrieval,
        session_id=session_id,
        fork_result=fork_result,
        fork_answer=fork_answer,
        fork_effect=fork_effect,
    )
    emit_event(
        on_event,
        f"checked the answer -- confidence {record['confidence']['overall_band']}",
        {
            "stage": "check",
            "confidence": record["confidence"],
            "coverage_map": record["coverage_map"],
        },
    )
    path = persist_record(
        brief.brief_id, record, analyses_dir=analyses_dir, config_path=config_path
    )
    markdown_path = persist_markdown(
        brief.brief_id,
        record,
        analyses_dir=analyses_dir,
        config_path=config_path,
        vault_dir=vault_dir,
    )
    report = build_run_report(
        record,
        latency_by_pass=clock.seconds_by_pass(),
        vault_dir=vault_dir,
        case_id=case_id,
        cases_dir=cases_dir,
        config_path=config_path,
    )
    report_path = persist_run_report(
        brief.brief_id, report, runs_dir=runs_dir, config_path=config_path
    )
    return BriefRunResult(
        record=record,
        path=path,
        markdown_path=markdown_path,
        report=report,
        report_path=report_path,
    )
