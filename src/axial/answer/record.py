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
short-circuit (`run_planned_retrieval` itself returns an empty trajectory
on `refuse`) and extends it one stage further to skip synthesis too.

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
`<analyses_dir>/<brief_id>.md`.

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

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, interrogate
from axial.eval.corpus_pin import resolve_pin_id
from axial.llm import (
    COUNTER_POSITION_GENERATE_PASS_NAME,
    INTERROGATE_PASS_NAME,
    RETRIEVE_PASS_NAME,
    SYNTHESIZE_PASS_NAME,
    LLMClient,
    estimate_cost,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_analyses_dir
from axial.retrieve.loop import run_planned_retrieval
from axial.validators.coverage import compute_confidence, compute_coverage_map


class AnswerError(Exception):
    """Base class for all stage-6 (analysis-record) errors."""


def _brief_to_dict(brief: Brief) -> dict[str, Any]:
    """The brief, verbatim (§7.1, §7.3: "the brief (§7.1), verbatim")."""
    return {
        "brief_id": brief.brief_id,
        "case": brief.case,
        "request": brief.request,
        "lens": brief.lens,
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


def _usage_and_cost_by_pass(client: LLMClient, model_by_pass: dict[str, str]) -> dict[str, Any]:
    """The §7.14 `cost` field (issue #363): per-pass token usage + computed
    dollar cost, summed to a run total -- the cost/token analogue of
    `model_by_pass` (same precedent, same per-pass shape). Reads
    `client.usage_for_pass` for every pass that actually ran (`model_by_pass`'s
    own keys), never guesses at a pass that did not.

    A pass whose usage was never captured (a client that reports none, or a
    real response that carried no `usage` object) contributes zero token
    counts and a `null` `usd` -- never zero cost pretending to be real. A
    pass whose model has no `PRICE_TABLE_USD_PER_1K` entry likewise gets a
    `null` `usd` (`estimate_cost` itself logs that gap once). `total_usd` is
    the sum of whatever per-pass costs ARE known; it is `null` only when
    NONE of the passes priced, so one unpriced/uncaptured pass does not
    blank out an otherwise-real total for a multi-pass run."""
    by_pass: dict[str, Any] = {}
    for pass_name, model in model_by_pass.items():
        usage = client.usage_for_pass(pass_name)
        prompt_tokens = usage["prompt_tokens"] if usage else 0
        completion_tokens = usage["completion_tokens"] if usage else 0
        total_tokens = usage["total_tokens"] if usage else 0
        usd = estimate_cost(model, prompt_tokens, completion_tokens) if usage else None
        by_pass[pass_name] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "usd": usd,
        }
    known = [entry["usd"] for entry in by_pass.values() if entry["usd"] is not None]
    total_usd = sum(known) if known else None
    return {"by_pass": by_pass, "total_usd": total_usd}


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
) -> dict[str, Any]:
    """Assemble the §7.3 analysis record. `claims`/`trajectory` are the
    caller's already-computed stage-4/stage-3 output (empty on a `refuse`
    disposition). `evidence_assembled_count`/`evidence_composed_count`
    (issue #545) default to 0, correct for a `refuse` disposition where
    stage 3/4 never ran, exactly like `claims`/`trajectory` defaulting empty
    on that path -- a real run passes both from `EvidenceSet.chunk_ids` and
    `ClaimGraph.evidence_composed_count` (`run_brief`). `counter_position` (§7.8) is computed for real (issue #399)
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
    (`_usage_and_cost_by_pass`) -- `client` is needed for that AND for
    `generate_counter_position`'s own possible model call.

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
    as it would have on success."""
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
    record = {
        "brief_id": brief.brief_id,
        "brief": _brief_to_dict(brief),
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
        "model_by_pass": record_model_by_pass,
        "cost": _usage_and_cost_by_pass(client, record_model_by_pass),
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
) -> Path:
    """Render `record` to markdown (§7.10, `axial.answer.render.render_markdown`)
    and write it to `<analyses_dir>/<brief_id>.md`, alongside the JSON record
    written by `persist_record` -- keyed on `brief_id` the same way, so
    re-running the same brief overwrites the same file rather than
    accumulating one per run."""
    if analyses_dir is None:
        analyses_dir = default_analyses_dir(config_path)
    analyses_dir = Path(analyses_dir)
    analyses_dir.mkdir(parents=True, exist_ok=True)
    path = analyses_dir / f"{brief_id}.md"
    path.write_text(render_markdown(record), encoding="utf-8")
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
) -> BriefRunResult:
    """Run the full engine (stages 1-6) over `brief` and persist the §7.3
    analysis record to `<analyses_dir>/<brief_id>.json` plus the §7.15 run
    report to `<runs_dir>/<brief_id>.json`, returning both.

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
    normally; translating that into exit 0 is the CLI's job."""
    corpus_pin = resolve_pin_id(evals_dir)
    clock = PassClock()

    with clock.time(INTERROGATE_PASS_NAME):
        interrogation_result = interrogate(brief, client=client, vault_dir=vault_dir)
    model_by_pass: dict[str, str] = {
        INTERROGATE_PASS_NAME: client.model_for_pass(INTERROGATE_PASS_NAME)
    }

    if interrogation_result.disposition == "refuse":
        lens = resolve_lens(brief.lens, lenses_dir=lenses_dir)
        claims: list[Claim] = []
        trajectory: list[dict[str, Any]] = []
        evidence_assembled_count = 0
        evidence_composed_count = 0
    else:
        with clock.time(RETRIEVE_PASS_NAME):
            retrieval_result = run_planned_retrieval(
                client,
                brief,
                interrogation_result,
                vault_dir=vault_dir,
                envelopes_dir=envelopes_dir,
                config_path=config_path,
                step_budget=step_budget,
                thin_result_floor=thin_result_floor,
            )
        model_by_pass[RETRIEVE_PASS_NAME] = client.model_for_pass(RETRIEVE_PASS_NAME)

        # Evidence assembly is timed under the synthesis pass it feeds: it
        # makes no model call of its own and has no pass name to report
        # under, and leaving it untimed would make the per-pass figures sum
        # to less than the run really took.
        with clock.time(SYNTHESIZE_PASS_NAME):
            evidence = assemble_evidence(retrieval_result.evidence_ids, vault_dir=vault_dir)
            claim_graph = synthesize(
                evidence,
                brief,
                client=client,
                vault_dir=vault_dir,
                lenses_dir=lenses_dir,
                config_path=config_path,
                question_scope=interrogation_result.question_scope,
            )
        model_by_pass[SYNTHESIZE_PASS_NAME] = client.model_for_pass(SYNTHESIZE_PASS_NAME)

        lens = claim_graph.lens
        claims = claim_graph.claims
        trajectory = retrieval_result.trajectory
        evidence_assembled_count = len(evidence.chunk_ids)
        evidence_composed_count = claim_graph.evidence_composed_count

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
    )
    path = persist_record(
        brief.brief_id, record, analyses_dir=analyses_dir, config_path=config_path
    )
    markdown_path = persist_markdown(
        brief.brief_id, record, analyses_dir=analyses_dir, config_path=config_path
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
