"""Brief-sweep harness (issue #368, parent #362 slice 1): run a worklist of
briefs N times each ("draws"), against a real LLM client, concurrently and
resumably, then score each brief's own draws against the rung-3 gates and a
code-only self-consistency ("quorum accuracy") figure.

This is the mechanism issue #362's real 30-brief x 3-draw benchmark sweep
needs; running that real sweep is a separate operational step (out of this
module's own scope -- see its own docstring's "do NOT build" list, mirrored
here).

Why a standalone driver, not an extension of `axial.run`'s `PASS_REGISTRY`
--------------------------------------------------------------------------
`axial.run.run_pass` (issue #277) drives one pass over a worklist of SOURCES,
one attempt per source, with a single `(pass, source_id)`-keyed ledger. A
brief sweep's unit of work is `(brief, draw_index)` -- one brief attempted N
times, each draw needing its OWN output location (see "no clobbering"
below), plus a post-loop step (gate scoring + quorum) scoped per BRIEF, not
per attempt. Wedging that shape into a registry keyed by `(pass, source_id)`
would mean either inventing a fake per-draw "source_id" (source_id ==
f"{brief}::draw{i}", a synthetic key #277 was never designed to carry) or
teaching the ledger and its done-predicate about a concept -- multiple
attempts of the SAME unit of work, each needing its own directory -- #277's
shape has no notion of. A purpose-built driver calling `run_brief()` directly
is cleaner and does not touch or generalize #277's own (deliberately serial)
runner at all.

No clobbering (the landmine this module exists to avoid)
--------------------------------------------------------------------------
`run_brief(..., analyses_dir=X)` writes `<X>/<brief_id>.json`, keyed only by
the brief's content-derived id (`axial.brief.intake.compute_brief_id`) --
NOT by draw number. Pointing every draw at the same `analyses_dir` would
have draw 2 silently overwrite draw 1's record. Each `(brief, draw)` pair
gets its own `analyses_dir`: `draw_dir(sweep_dir, brief_stem, draw_index)`,
`<sweep_dir>/analyses/<brief_stem>/draw<i>/`.

Resume and failure isolation
--------------------------------------------------------------------------
A `(brief, draw)` pair whose output record already exists on disk is
skipped -- no `run_brief()` call, so an interrupted sweep re-invoked over the
same worklist costs nothing for already-done pairs (mirrors #277's own
resume philosophy, restated for a per-draw unit of work). A pair whose
`run_brief()` call raises one of its own declared error types is recorded
FAILED and the sweep continues -- one bad draw never stops the run (module-
level `BRIEF_RUN_ERRORS`, the exact tuple `axial.cli._brief_run` itself
catches, never a bare `except Exception`).

Concurrency
--------------------------------------------------------------------------
Brief runs only call OpenRouter, never docling -- unlike #277's runner (which
stays serial, untouched, for an unrelated reason: docling itself is not safe
to run concurrently, see docs). `run_sweep`'s `workers` (default 3, matching
this project's other concurrent-worker precedents) bounds a
`ThreadPoolExecutor` over the flat list of every `(brief, draw)` pair.

One client per draw, not one shared client for the whole sweep
--------------------------------------------------------------------------
`OpenRouterClient.usage_for_pass` (and `StubLLMClient`'s) accumulates
CUMULATIVELY across every call made on that one client instance -- it has no
notion of "this run's own usage" vs. "everything this instance has ever
seen". `axial.answer.record.build_record` reads it assuming it reflects only
the current `run_brief()` call (true for `axial brief run`, a fresh
per-process client). Sharing ONE client across many draws -- sequentially or
concurrently -- would silently accumulate every prior draw's tokens into
each later draw's own recorded cost, corrupting the very cost figures this
module reports. `run_sweep` therefore builds a FRESH client per draw via
`client_factory` (default: `axial.llm.get_client`, the same construction path
`axial brief run` itself uses -- never a one-off). This also sidesteps any
thread-safety question about concurrent draws sharing one instance's mutable
usage-accumulator dict.

Quorum accuracy (self-consistency)
--------------------------------------------------------------------------
Pure code, zero model calls (`compute_quorum`): across one brief's own
available (OK or resumed) draws, compares `interrogation.disposition` and
each draw's per-kind (a/b/c) claim-count "signature", reporting what
fraction of draws agree with the modal value of each. This measures
pipeline STABILITY across repeat draws of the same brief -- there is no gold
referee for sim briefs, so this is never a correctness claim.

Per-brief cost/token summary
--------------------------------------------------------------------------
Each record already carries `cost` (§7.14, issue #363): per-pass
`{prompt_tokens, completion_tokens, total_tokens, usd}` plus a run
`total_usd`. `aggregate_brief_cost` sums those across a brief's own
available draws, per pass -- raw token counts, not just dollars, because
$/token varies by model and a model-combination comparison (issue #362's own
purpose for this sweep) needs to see whether a token difference is
concentrated in one pass (e.g. retrieve vs. synthesize), not just an
aggregate figure. A pass whose `usd` was `None` on ANY draw (an unpriced
model) keeps that pass's summed `usd` `None` too -- summing `None` as 0
would silently understate cost for a brief mixing priced and unpriced
passes, the same "never a fabricated zero" rule `_usage_and_cost_by_pass`
itself already follows.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.analyze.synthesis import SynthesisError
from axial.answer.record import AnswerError, run_brief
from axial.brief.intake import Brief, BriefError, load_brief
from axial.brief.interrogate import InterrogationError
from axial.eval.corpus_pin import CorpusPinError
from axial.gates import (
    ATTRIBUTION_FIDELITY_GATE_NAME,
    CALIBRATION_GATE_NAME,
    GROUNDING_GATE_NAME,
    SYNTHESIS_QUALITY_GATE_NAME,
    CalibrationGateError,
    GateError,
    GateReport,
    GroundingGateError,
    resolve_trusted,
    run_gate,
    write_report,
)
from axial.ingest import WorklistError, read_worklist
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient, get_client
from axial.query.reader import QueryError
from axial.validators import AttributionValidatorError, CounterPositionValidatorError

OK_STATUS = "OK"
FAIL_STATUS = "FAIL"
SKIP_STATUS = "SKIP"

# The declared error surface a single (brief, draw)'s `run_brief()` call may
# raise -- exactly `axial.cli._brief_run`'s own catch tuple. Never a bare
# `except Exception`: an undeclared bug still propagates and is not mistaken
# for a recoverable per-draw outcome.
BRIEF_RUN_ERRORS = (InterrogationError, QueryError, SynthesisError, CorpusPinError, AnswerError)

# The declared error surface one gate's `run_gate()` call may raise -- the
# same tuple `axial.cli._gate_run` itself catches, minus `AdversarialGateError`
# (the adversarial gate is out of scope here, module docstring).
GATE_RUN_ERRORS = (
    GateError,
    AttributionValidatorError,
    GroundingGateError,
    CounterPositionValidatorError,
    CalibrationGateError,
)

# The four rung-3 gates applicable to a sim brief's draws (module docstring):
# `adversarial` is excluded -- it scores seeded briefs with an
# `expected_disposition` key, not analysis records (§10, issue #264).
SWEEP_GATE_NAMES = (
    ATTRIBUTION_FIDELITY_GATE_NAME,
    GROUNDING_GATE_NAME,
    SYNTHESIS_QUALITY_GATE_NAME,
    CALIBRATION_GATE_NAME,
)

# This project's existing concurrent-worker precedent (stage-4 retag, gold
# ingest topology) -- overridable via `run_sweep(workers=...)`.
DEFAULT_WORKERS = 3

CLAIM_KINDS = ("a", "b", "c")


class SweepError(Exception):
    """Fatal, before-any-draw sweep errors: an unreadable worklist, an
    invalid `draws` count."""


@dataclass(frozen=True)
class DrawOutcome:
    """One `(brief, draw)` pair's outcome. `brief_id` is `None` only when
    the brief itself never loaded (a `BriefError`, never attempted as a
    draw at all -- `draw_index` is `-1` for that one synthetic outcome)."""

    brief_path: str
    brief_stem: str
    brief_id: str | None
    draw_index: int
    status: str
    reason: str
    latency_seconds: float | None
    record_path: Path | None


@dataclass(frozen=True)
class QuorumResult:
    """Self-consistency across one brief's own available draws (module
    docstring). `*_agreement_rate` is `None` only when there were zero
    available draws to compare (every draw failed, or the brief itself never
    loaded) -- never a vacuous 1.0 or 0.0 standing in for "no data"."""

    n_draws: int
    dispositions: tuple[str | None, ...]
    disposition_agreement_rate: float | None
    claim_kind_counts: tuple[dict[str, int], ...]
    claim_kind_agreement_rate: float | None


@dataclass(frozen=True)
class BriefSweepResult:
    """One brief's whole sweep outcome: every draw attempted, that brief's
    OWN gate reports (scored only over its own available draws, never
    pooled across briefs), its own quorum figure, and its own cost/token
    summary (`aggregate_brief_cost`)."""

    brief_path: str
    brief_stem: str
    brief_id: str | None
    draws: list[DrawOutcome]
    gate_reports: dict[str, GateReport]
    quorum: QuorumResult
    cost: dict[str, Any]


@dataclass(frozen=True)
class SweepSummary:
    briefs: list[BriefSweepResult]
    total_draws: int
    ok_count: int
    fail_count: int
    skip_count: int


def draw_dir(sweep_dir: Path, brief_stem: str, draw_index: int) -> Path:
    """Where one `(brief, draw)` pair's `run_brief()` output lands (module
    docstring's "no clobbering" section): `<sweep_dir>/analyses/<brief_stem>/
    draw<i>/`, passed as `run_brief`'s own `analyses_dir=`."""
    return Path(sweep_dir) / "analyses" / brief_stem / f"draw{draw_index}"


def gates_dir(sweep_dir: Path, brief_stem: str) -> Path:
    """Where one brief's own 4 gate reports are written -- deliberately NOT
    the shared `evals/reports/<gate>.json` default `write_report` would
    otherwise use, which would have every brief in the sweep clobber the
    same 4 files."""
    return Path(sweep_dir) / "analyses" / brief_stem / "gates"


def _record_path(sweep_dir: Path, brief_stem: str, draw_index: int, brief_id: str) -> Path:
    return draw_dir(sweep_dir, brief_stem, draw_index) / f"{brief_id}.json"


def _claim_kind_counts(record: dict[str, Any]) -> dict[str, int]:
    counts = dict.fromkeys(CLAIM_KINDS, 0)
    for claim in record.get("claims") or []:
        kind = claim.get("kind")
        if kind in counts:
            counts[kind] += 1
    return counts


def compute_quorum(records: list[dict[str, Any]]) -> QuorumResult:
    """Self-consistency across `records` -- every available draw of ONE
    brief (module docstring). `records` may include resumed (previously
    persisted) draws alongside freshly-run ones; a FAILed draw contributes
    no record at all, so it is simply absent from `records`, not a `None`
    entry -- callers pass only what actually exists."""
    n = len(records)
    if n == 0:
        return QuorumResult(0, (), None, (), None)

    dispositions = tuple(
        (record.get("interrogation") or {}).get("disposition") for record in records
    )
    modal_disposition = Counter(dispositions).most_common(1)[0][0]
    disposition_agreement = sum(1 for d in dispositions if d == modal_disposition) / n

    kind_counts = tuple(_claim_kind_counts(record) for record in records)
    signatures = [tuple(sorted(counts.items())) for counts in kind_counts]
    modal_signature = Counter(signatures).most_common(1)[0][0]
    claim_kind_agreement = sum(1 for s in signatures if s == modal_signature) / n

    return QuorumResult(
        n_draws=n,
        dispositions=dispositions,
        disposition_agreement_rate=disposition_agreement,
        claim_kind_counts=kind_counts,
        claim_kind_agreement_rate=claim_kind_agreement,
    )


_EMPTY_COST_SUMMARY: dict[str, Any] = {"by_pass": {}, "total_tokens": 0, "total_usd": None}


def aggregate_brief_cost(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum `record["cost"]` (§7.14) across `records` -- one brief's own
    available draws (module docstring's "per-brief cost/token summary"
    section). Returns `{by_pass: {pass_name: {prompt_tokens,
    completion_tokens, total_tokens, usd}}, total_tokens, total_usd}`;
    `total_tokens` sums every pass's `total_tokens` across every draw,
    `total_usd` sums every pass's summed `usd` that IS known (never a
    fabricated zero for an unpriced/uncaptured pass, mirroring
    `axial.answer.record._usage_and_cost_by_pass`'s own rule one level up)."""
    if not records:
        return dict(_EMPTY_COST_SUMMARY)

    by_pass: dict[str, dict[str, Any]] = {}
    for record in records:
        for pass_name, entry in ((record.get("cost") or {}).get("by_pass") or {}).items():
            agg = by_pass.setdefault(
                pass_name,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "usd": 0.0,
                    "usd_known": True,
                },
            )
            agg["prompt_tokens"] += entry.get("prompt_tokens", 0)
            agg["completion_tokens"] += entry.get("completion_tokens", 0)
            agg["total_tokens"] += entry.get("total_tokens", 0)
            usd = entry.get("usd")
            if usd is None:
                agg["usd_known"] = False
            else:
                agg["usd"] += usd

    by_pass_out: dict[str, Any] = {}
    total_tokens = 0
    known_usds: list[float] = []
    for pass_name, agg in by_pass.items():
        usd_value = agg["usd"] if agg["usd_known"] else None
        by_pass_out[pass_name] = {
            "prompt_tokens": agg["prompt_tokens"],
            "completion_tokens": agg["completion_tokens"],
            "total_tokens": agg["total_tokens"],
            "usd": usd_value,
        }
        total_tokens += agg["total_tokens"]
        if usd_value is not None:
            known_usds.append(usd_value)

    return {
        "by_pass": by_pass_out,
        "total_tokens": total_tokens,
        "total_usd": sum(known_usds) if known_usds else None,
    }


def _run_one_draw(
    brief_path: str,
    brief: Brief,
    draw_index: int,
    *,
    client_factory: Callable[[], LLMClient],
    sweep_dir: Path,
    vault_dir: Path | None,
    envelopes_dir: Path | None,
    config_path: Path,
    evals_dir: Path | None,
    lenses_dir: Path | None,
    step_budget: int | None,
    thin_result_floor: int | None,
) -> tuple[DrawOutcome, dict[str, Any] | None]:
    """Run (or resume) one `(brief, draw)` pair. Returns the outcome plus
    the resulting analysis record dict (`None` for a FAILed draw)."""
    brief_stem = Path(brief_path).stem
    analyses_dir = draw_dir(sweep_dir, brief_stem, draw_index)
    record_file = _record_path(sweep_dir, brief_stem, draw_index, brief.brief_id)

    if record_file.is_file():
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = None  # a torn prior write -- fall through and re-run
        if record is not None:
            outcome = DrawOutcome(
                brief_path,
                brief_stem,
                brief.brief_id,
                draw_index,
                SKIP_STATUS,
                "",
                None,
                record_file,
            )
            return outcome, record

    start = time.monotonic()
    try:
        result = run_brief(
            brief,
            client=client_factory(),
            vault_dir=vault_dir,
            envelopes_dir=envelopes_dir,
            config_path=config_path,
            analyses_dir=analyses_dir,
            evals_dir=evals_dir,
            lenses_dir=lenses_dir,
            step_budget=step_budget,
            thin_result_floor=thin_result_floor,
        )
    except BRIEF_RUN_ERRORS as exc:
        outcome = DrawOutcome(
            brief_path,
            brief_stem,
            brief.brief_id,
            draw_index,
            FAIL_STATUS,
            str(exc),
            time.monotonic() - start,
            None,
        )
        return outcome, None

    outcome = DrawOutcome(
        brief_path,
        brief_stem,
        brief.brief_id,
        draw_index,
        OK_STATUS,
        "",
        time.monotonic() - start,
        result.path,
    )
    return outcome, result.record


def _score_brief_gates(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None,
    config_path: Path,
    corpus_pin: str | None,
    trusted: bool,
    reports_dir: Path,
) -> dict[str, GateReport]:
    """Score `SWEEP_GATE_NAMES` over `records` -- one brief's own draws,
    never pooled across briefs (module docstring). A gate whose own call
    raises its declared error is recorded absent from the returned dict
    (with a printed warning) rather than aborting the other 3 gates or the
    rest of the sweep -- gate scoring is a post-processing report over
    already-persisted draws, not the sweep's own critical path."""
    reports: dict[str, GateReport] = {}
    for gate_name in SWEEP_GATE_NAMES:
        try:
            report = run_gate(
                gate_name,
                records,
                client=client,
                vault_dir=vault_dir,
                corpus_pin=corpus_pin,
                trusted=trusted,
                config_path=config_path,
            )
        except GATE_RUN_ERRORS as exc:
            print(f"warning: gate {gate_name!r} failed to score: {exc}")
            continue
        write_report(report, reports_dir=reports_dir)
        reports[gate_name] = report
    return reports


def run_sweep(
    worklist_path: str | Path,
    *,
    draws: int,
    sweep_dir: str | Path,
    client_factory: Callable[[], LLMClient] | None = None,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    evals_dir: Path | None = None,
    lenses_dir: Path | None = None,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
    workers: int = DEFAULT_WORKERS,
) -> SweepSummary:
    """Run every brief in `worklist_path` `draws` times each, bounded to
    `workers` concurrent `(brief, draw)` attempts (module docstring), then
    score each brief's own 4 rung-3 gates and quorum-accuracy figure over
    just its own available draws.

    `client_factory` builds ONE fresh client per draw (default:
    `axial.llm.get_client`) -- see the module docstring for why sharing one
    client instance across draws would corrupt per-draw cost accounting.

    Raises `SweepError` before any draw is attempted for an unreadable
    worklist or `draws < 1`. A brief that fails to load (`BriefError`) gets
    no draw attempted; it is recorded as its own single FAILed outcome and
    the sweep continues with the remaining briefs -- mirrors the per-draw
    failure-isolation rule one level up.
    """
    if draws < 1:
        raise SweepError(f"draws must be >= 1, got {draws}")

    try:
        brief_paths = read_worklist(worklist_path)
    except WorklistError as exc:
        raise SweepError(str(exc)) from exc

    sweep_dir = Path(sweep_dir)
    if client_factory is None:
        client_factory = lambda: get_client(config_path=config_path)  # noqa: E731

    loaded: list[tuple[str, Brief | None, str]] = []
    for brief_path in brief_paths:
        try:
            loaded.append((brief_path, load_brief(brief_path), ""))
        except BriefError as exc:
            loaded.append((brief_path, None, str(exc)))

    work_items = [
        (brief_path, brief, draw_index)
        for brief_path, brief, _reason in loaded
        if brief is not None
        for draw_index in range(draws)
    ]

    outcomes_by_key: dict[tuple[str, int], DrawOutcome] = {}
    records_by_key: dict[tuple[str, int], dict[str, Any] | None] = {}

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
        futures = {
            executor.submit(
                _run_one_draw,
                brief_path,
                brief,
                draw_index,
                client_factory=client_factory,
                sweep_dir=sweep_dir,
                vault_dir=vault_dir,
                envelopes_dir=envelopes_dir,
                config_path=config_path,
                evals_dir=evals_dir,
                lenses_dir=lenses_dir,
                step_budget=step_budget,
                thin_result_floor=thin_result_floor,
            ): (brief_path, draw_index)
            for brief_path, brief, draw_index in work_items
        }
        for future in as_completed(futures):
            key = futures[future]
            outcome, record = future.result()
            outcomes_by_key[key] = outcome
            records_by_key[key] = record

    # Post-processing (module docstring): per brief, never pooled.
    corpus_pin, trusted = resolve_trusted(evals_dir=evals_dir)
    gate_client = client_factory()

    brief_results: list[BriefSweepResult] = []
    for brief_path, brief, load_reason in loaded:
        brief_stem = Path(brief_path).stem

        if brief is None:
            failed_load = DrawOutcome(
                brief_path, brief_stem, None, -1, FAIL_STATUS, load_reason, None, None
            )
            brief_results.append(
                BriefSweepResult(
                    brief_path,
                    brief_stem,
                    None,
                    [failed_load],
                    {},
                    QuorumResult(0, (), None, (), None),
                    dict(_EMPTY_COST_SUMMARY),
                )
            )
            continue

        draw_outcomes = [outcomes_by_key[(brief_path, i)] for i in range(draws)]
        available_records = [
            records_by_key[(brief_path, i)]
            for i in range(draws)
            if records_by_key.get((brief_path, i)) is not None
        ]

        gate_reports = (
            _score_brief_gates(
                available_records,
                client=gate_client,
                vault_dir=vault_dir,
                config_path=config_path,
                corpus_pin=corpus_pin,
                trusted=trusted,
                reports_dir=gates_dir(sweep_dir, brief_stem),
            )
            if available_records
            else {}
        )
        quorum = compute_quorum(available_records)
        cost = aggregate_brief_cost(available_records)

        brief_results.append(
            BriefSweepResult(
                brief_path, brief_stem, brief.brief_id, draw_outcomes, gate_reports, quorum, cost
            )
        )

    all_outcomes = [outcome for result in brief_results for outcome in result.draws]
    ok_count = sum(1 for outcome in all_outcomes if outcome.status == OK_STATUS)
    skip_count = sum(1 for outcome in all_outcomes if outcome.status == SKIP_STATUS)
    fail_count = len(all_outcomes) - ok_count - skip_count

    return SweepSummary(brief_results, len(all_outcomes), ok_count, fail_count, skip_count)


def format_sweep_summary(summary: SweepSummary) -> str:
    """Human-readable rendering for the CLI: one block per brief (draw
    statuses, quorum agreement, gate verdicts), then an end-of-sweep tally."""
    lines: list[str] = []
    for result in summary.briefs:
        lines.append(f"brief: {result.brief_stem} (brief_id={result.brief_id})")
        for outcome in result.draws:
            reason = f" ({outcome.reason})" if outcome.reason else ""
            lines.append(f"  draw {outcome.draw_index}: {outcome.status}{reason}")
        quorum = result.quorum
        if quorum.n_draws:
            lines.append(
                f"  quorum: n={quorum.n_draws} "
                f"disposition_agreement={quorum.disposition_agreement_rate:.2f} "
                f"claim_kind_agreement={quorum.claim_kind_agreement_rate:.2f}"
            )
        else:
            lines.append("  quorum: n=0 (no available draws)")
        usd_str = "n/a" if result.cost["total_usd"] is None else f"{result.cost['total_usd']:.4f}"
        lines.append(f"  cost: total_tokens={result.cost['total_tokens']} total_usd={usd_str}")
        for pass_name, entry in result.cost["by_pass"].items():
            pass_usd_str = "n/a" if entry["usd"] is None else f"{entry['usd']:.4f}"
            lines.append(
                f"    {pass_name}: prompt_tokens={entry['prompt_tokens']} "
                f"completion_tokens={entry['completion_tokens']} "
                f"total_tokens={entry['total_tokens']} usd={pass_usd_str}"
            )
        for gate_name, report in result.gate_reports.items():
            lines.append(f"  gate {gate_name}: {'PASS' if report.passed else 'FAIL'}")
    lines.append(
        f"sweep: briefs={len(summary.briefs)} total_draws={summary.total_draws} "
        f"ok={summary.ok_count} skipped={summary.skip_count} failed={summary.fail_count}"
    )
    return "\n".join(lines)
