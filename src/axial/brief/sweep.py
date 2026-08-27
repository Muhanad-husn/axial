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
passes, the same "never a fabricated zero" rule `axial.llm.usage_and_cost_by_pass`
itself already follows.

Named arms, not a boolean (issue #808)
--------------------------------------------------------------------------
`run_sweep`'s `arm` parameter (default `"name"`) is forwarded to every
`(brief, draw)`'s own `_run_one_draw` call and recorded on that draw's
`DrawOutcome.arm` -- the same string for every draw in one invocation,
never inferred draw-by-draw. Today only `arm == "map"` changes what
actually runs (`run_brief(use_map=True)`, the argument-map path); any other
string -- including one no arm elsewhere has given meaning to yet -- runs
the name-layer default. This module deliberately holds no whitelist of
valid arm names: it never rejects an unrecognized one, so a slice adding a
real third arm (issue #807) does so by teaching a lower layer what that
name means, with no edit here. `use_map: bool` stays as the legacy knob
`axial.brief.smoke.run_smoke` still calls with; `arm`, when given, takes
precedence, and `use_map=True` with no `arm` given is still read as
`arm="map"`.

**The mixed-arm refusal.** A `sweep_dir` holding draws from two arms would
produce a comparison figure (issue #809) that is quietly meaningless, so
`run_sweep` writes a one-line `arm.txt` marker into `sweep_dir` before any
draw is attempted, and refuses -- naming the arm already there -- when a
later invocation asks for a different one. Checked before the worklist's
briefs are even loaded, so a mismatched resume costs nothing: no client
built, no model call made.

**The commit.** `SweepSummary.commit` is this checkout's `git rev-parse
HEAD` at the moment the sweep ran (`None` only when `git` itself is
unavailable), because issue #809 compares sweep directories and two built
from different code produce a difference that is not about the arms --
this is where that fact is known, recording it here is cheaper than
reconstructing it later.

**`distinct_sources_cited`.** Already computed on every persisted analysis
record (`len(record["source_usage"]["sources"])`, §7.13) -- read off here
onto `DrawOutcome.distinct_sources_cited` rather than recomputed, so issue
#809's per-arm comparison is a pure reader of `summary.json` and never has
to open each draw's own record.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.analyze.synthesis import SynthesisError
from axial.answer.record import AnswerError, run_brief
from axial.argmap.ask import AskError
from axial.brief.fork import ForkCheckError
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
    verdict_text,
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
# raise -- exactly `axial.cli._brief_run`'s own catch tuple, including
# `AskError` (issue #572, PR 4 of 4): `run_brief(use_map=True)` can raise it
# (no map built at this pin, an encoder mismatch, an unusable door response)
# exactly where the name-layer path can raise `QueryError`/`SynthesisError`,
# and a `--map` draw hitting one must be recorded FAILED, not crash the
# whole sweep. `ForkCheckError` (issue #649) is the intake fork-check's own
# declared failure -- a transport error or an out-of-vocabulary model
# response on the name-layer path -- and must be recorded FAILED the same
# way. Never a bare `except Exception`: an undeclared bug still propagates
# and is not mistaken for a recoverable per-draw outcome.
BRIEF_RUN_ERRORS = (
    InterrogationError,
    ForkCheckError,
    QueryError,
    SynthesisError,
    CorpusPinError,
    AnswerError,
    AskError,
)

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

# The one arm name `run_sweep` gives real meaning to today (module
# docstring's "named arms" section) -- not a whitelist, since any other
# string is still accepted and simply runs the name-layer default.
MAP_ARM = "map"
DEFAULT_ARM = "name"

# The mixed-arm-refusal marker's filename, written into `sweep_dir` itself
# (module docstring).
ARM_MARKER_FILENAME = "arm.txt"


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
    # The §7.15 run report written alongside the record (issue #491). Its
    # path is derived, not measured: `run_brief` writes it under this draw's
    # own directory keyed on the same `brief_id`, so a RESUMED draw's report
    # is found the same way a fresh one's is.
    report_path: Path | None = None
    # The arm (issue #808) this draw ran through -- `run_sweep`'s own
    # resolved arm, identical across every draw in one invocation (the
    # mixed-arm refusal enforces that a `sweep_dir` never mixes two), so
    # two sweep directories are told apart by this field alone.
    arm: str = DEFAULT_ARM
    # `len(record["source_usage"]["sources"])` (§7.13, issue #808) -- the
    # number of distinct sources this draw's grounds actually cite, already
    # computed by `build_record` and read off here rather than recomputed.
    # `None` only for a FAILed draw, which produced no record at all.
    distinct_sources_cited: int | None = None


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
    # issue #808: the arm every draw in this sweep ran through, and the
    # commit `run_sweep` ran at (module docstring's "named arms"/"the
    # commit" sections).
    arm: str = DEFAULT_ARM
    commit: str | None = None


def draw_dir(sweep_dir: Path, brief_stem: str, draw_index: int) -> Path:
    """Where one `(brief, draw)` pair's `run_brief()` output lands (module
    docstring's "no clobbering" section): `<sweep_dir>/analyses/<brief_stem>/
    draw<i>/`, passed as `run_brief`'s own `analyses_dir=`."""
    return Path(sweep_dir) / "analyses" / brief_stem / f"draw{draw_index}"


def runs_dir(sweep_dir: Path, brief_stem: str, draw_index: int) -> Path:
    """Where one `(brief, draw)` pair's §7.15 run report lands: a `runs/`
    directory inside that draw's own output directory. Same no-clobbering
    rule as `draw_dir` above, for the same reason -- the report is keyed on
    `brief_id` alone, so a shared directory would have draw 2 overwrite draw
    1's report."""
    return draw_dir(sweep_dir, brief_stem, draw_index) / "runs"


def gates_dir(sweep_dir: Path, brief_stem: str) -> Path:
    """Where one brief's own 4 gate reports are written -- deliberately NOT
    the shared `evals/reports/<gate>.json` default `write_report` would
    otherwise use, which would have every brief in the sweep clobber the
    same 4 files."""
    return Path(sweep_dir) / "analyses" / brief_stem / "gates"


def _record_path(sweep_dir: Path, brief_stem: str, draw_index: int, brief_id: str) -> Path:
    return draw_dir(sweep_dir, brief_stem, draw_index) / f"{brief_id}.json"


def _report_path(sweep_dir: Path, brief_stem: str, draw_index: int, brief_id: str) -> Path:
    return runs_dir(sweep_dir, brief_stem, draw_index) / f"{brief_id}.json"


def _distinct_sources_cited(record: dict[str, Any] | None) -> int | None:
    """`len(record["source_usage"]["sources"])` (§7.13, issue #808) --
    already computed by `build_record` on every persisted record; read off
    here rather than recomputed. `None` when there is no record to read (a
    FAILed draw) or an old record predates `source_usage` entirely."""
    if record is None:
        return None
    source_usage = record.get("source_usage")
    if not isinstance(source_usage, dict):
        return None
    sources = source_usage.get("sources")
    if not isinstance(sources, dict):
        return None
    return len(sources)


def _current_commit_sha() -> str | None:
    """This checkout's `git rev-parse HEAD` (module docstring's "the
    commit" section) -- `None`, never a fabricated placeholder, when `git`
    itself is unavailable or this checkout has no history to ask."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha or None


def _check_and_record_arm(sweep_dir: Path, arm: str) -> None:
    """The mixed-arm refusal (module docstring, issue #808): a `sweep_dir`
    already holding draws from one arm refuses a resume under a different
    one, naming the arm already there. Checked and recorded before any
    draw is attempted -- a mismatch costs nothing, since the worklist has
    not even been loaded yet. A fresh `sweep_dir` (no marker yet) simply
    records the arm it starts with."""
    sweep_dir.mkdir(parents=True, exist_ok=True)
    marker_path = sweep_dir / ARM_MARKER_FILENAME
    if marker_path.is_file():
        existing_arm = marker_path.read_text(encoding="utf-8").strip()
        if existing_arm and existing_arm != arm:
            raise SweepError(
                f"{sweep_dir} already holds draws for arm {existing_arm!r}; "
                f"refusing to run arm {arm!r} in the same directory"
            )
        return
    marker_path.write_text(arm + "\n", encoding="utf-8")


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
    `axial.llm.usage_and_cost_by_pass`'s own rule one level up)."""
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
    cases_dir: Path | None,
    step_budget: int | None,
    thin_result_floor: int | None,
    arm: str = DEFAULT_ARM,
) -> tuple[DrawOutcome, dict[str, Any] | None]:
    """Run (or resume) one `(brief, draw)` pair. Returns the outcome plus
    the resulting analysis record dict (`None` for a FAILed draw).

    `arm` (issue #808, module docstring's "named arms" section) is
    recorded on the returned `DrawOutcome` verbatim, and translated to
    `run_brief`'s own `use_map` boolean (`arm == MAP_ARM`) -- this module
    has no other opinion on which retrieval path a draw takes, it only
    drives whichever one the caller asked for the same resumable,
    failure-isolated way."""
    use_map = arm == MAP_ARM
    brief_stem = Path(brief_path).stem
    analyses_dir = draw_dir(sweep_dir, brief_stem, draw_index)
    record_file = _record_path(sweep_dir, brief_stem, draw_index, brief.brief_id)
    report_file = _report_path(sweep_dir, brief_stem, draw_index, brief.brief_id)

    print(f"sweep: {brief_stem} draw {draw_index} starting", file=sys.stderr)

    if record_file.is_file():
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = None  # a torn prior write -- fall through and re-run
        if record is not None:
            print(f"sweep: {brief_stem} draw {draw_index} SKIP (already recorded)", file=sys.stderr)
            outcome = DrawOutcome(
                brief_path,
                brief_stem,
                brief.brief_id,
                draw_index,
                SKIP_STATUS,
                "",
                None,
                record_file,
                report_file if report_file.is_file() else None,
                arm=arm,
                distinct_sources_cited=_distinct_sources_cited(record),
            )
            return outcome, record

    start = time.monotonic()
    client = client_factory()
    # Follow-up to #362's benchmark sweep: tag this draw's own client with a
    # run_id (`OpenRouterClient.set_run_id`) so its `llm_call_request`/
    # `llm_call_response` log lines can be attributed back to this brief/draw
    # -- a plain `getattr` duck-type check, not a `LLMClient` Protocol
    # method, since only the real provider client logs those lines at all
    # (every stub/record/exploding test client, and a bare `client_factory
    # = lambda: object()` in this module's own tests, simply has no such
    # method and is left untouched).
    set_run_id = getattr(client, "set_run_id", None)
    if set_run_id is not None:
        set_run_id(f"{brief_stem}:draw{draw_index}")
    try:
        result = run_brief(
            brief,
            client=client,
            vault_dir=vault_dir,
            envelopes_dir=envelopes_dir,
            config_path=config_path,
            analyses_dir=analyses_dir,
            runs_dir=runs_dir(sweep_dir, brief_stem, draw_index),
            evals_dir=evals_dir,
            lenses_dir=lenses_dir,
            cases_dir=cases_dir,
            # The brief file's own stem is the join to `evals/cases/sim/`
            # (§9.3), so a swept brief scores the mechanical retrieval-hit
            # oracle exactly as `axial brief run` does.
            case_id=brief_stem,
            step_budget=step_budget,
            thin_result_floor=thin_result_floor,
            use_map=use_map,
        )
    except BRIEF_RUN_ERRORS as exc:
        elapsed = time.monotonic() - start
        print(
            f"sweep: {brief_stem} draw {draw_index} FAIL ({elapsed:.1f}s): {exc}",
            file=sys.stderr,
        )
        outcome = DrawOutcome(
            brief_path,
            brief_stem,
            brief.brief_id,
            draw_index,
            FAIL_STATUS,
            str(exc),
            elapsed,
            None,
            None,
            arm=arm,
        )
        return outcome, None

    elapsed = time.monotonic() - start
    print(f"sweep: {brief_stem} draw {draw_index} OK ({elapsed:.1f}s)", file=sys.stderr)
    outcome = DrawOutcome(
        brief_path,
        brief_stem,
        brief.brief_id,
        draw_index,
        OK_STATUS,
        "",
        elapsed,
        result.path,
        result.report_path,
        arm=arm,
        distinct_sources_cited=_distinct_sources_cited(result.record),
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
    brief_stem = reports_dir.parent.name
    reports: dict[str, GateReport] = {}
    for gate_name in SWEEP_GATE_NAMES:
        print(
            f"sweep: {brief_stem} gate {gate_name!r} scoring {len(records)} draw(s)",
            file=sys.stderr,
        )
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
        print(
            f"sweep: {brief_stem} gate {gate_name!r} done, verdict={verdict_text(report.passed)}",
            file=sys.stderr,
        )
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
    cases_dir: Path | None = None,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
    workers: int = DEFAULT_WORKERS,
    score_gates: bool = True,
    use_map: bool = False,
    arm: str | None = None,
) -> SweepSummary:
    """Run every brief in `worklist_path` `draws` times each, bounded to
    `workers` concurrent `(brief, draw)` attempts (module docstring), then
    score each brief's own 4 rung-3 gates and quorum-accuracy figure over
    just its own available draws.

    `client_factory` builds ONE fresh client per draw (default:
    `axial.llm.get_client`) -- see the module docstring for why sharing one
    client instance across draws would corrupt per-draw cost accounting.

    `arm` (issue #808, module docstring's "named arms" section) is the
    retrieval arm every draw runs through, recorded verbatim on each
    `DrawOutcome` and on the returned `SweepSummary`. `None` (the default)
    falls back to `"map"` when `use_map=True` is still given (the legacy
    knob `axial.brief.smoke.run_smoke` calls this with) or `"name"`
    otherwise; when `arm` is given, it takes precedence over `use_map`.
    Only `arm == "map"` changes what actually runs today -- any other
    string, including one no arm elsewhere has given meaning to yet, runs
    the name-layer default; this function holds no whitelist of valid arm
    names and never rejects one. A `sweep_dir` already holding draws from a
    different arm than the one requested here raises `SweepError` naming
    the arm already there, before any draw is attempted.

    `score_gates=False` (issue #491) skips the four rung-3 gates entirely
    and makes ZERO gate calls: the grounding gate calls an independent
    model per (a) claim, which is a quality judgment and a bill, and
    `axial brief smoke` -- a mechanical smoke alarm running under a cost
    budget -- would otherwise measure that bill instead of the run's. One
    boolean seam rather than a second driver: everything else here (resume,
    one fresh client per draw, per-draw latency, cost aggregation,
    `summary.json`) is exactly what a smoke run needs.

    Raises `SweepError` before any draw is attempted for an unreadable
    worklist, `draws < 1`, or a mismatched arm on an existing `sweep_dir`.
    A brief that fails to load (`BriefError`) gets no draw attempted; it is
    recorded as its own single FAILed outcome and the sweep continues with
    the remaining briefs -- mirrors the per-draw failure-isolation rule one
    level up.
    """
    if draws < 1:
        raise SweepError(f"draws must be >= 1, got {draws}")

    try:
        brief_paths = read_worklist(worklist_path)
    except WorklistError as exc:
        raise SweepError(str(exc)) from exc

    sweep_dir = Path(sweep_dir)
    resolved_arm = arm if arm is not None else (MAP_ARM if use_map else DEFAULT_ARM)
    _check_and_record_arm(sweep_dir, resolved_arm)

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
                cases_dir=cases_dir,
                step_budget=step_budget,
                thin_result_floor=thin_result_floor,
                arm=resolved_arm,
            ): (brief_path, draw_index)
            for brief_path, brief, draw_index in work_items
        }
        for future in as_completed(futures):
            key = futures[future]
            outcome, record = future.result()
            outcomes_by_key[key] = outcome
            records_by_key[key] = record

    # Post-processing (module docstring): per brief, never pooled. With
    # `score_gates=False` no gate client is ever constructed, so a gate-free
    # sweep cannot make a model call by accident.
    corpus_pin, trusted = resolve_trusted(evals_dir=evals_dir)
    gate_client = client_factory() if score_gates else None

    brief_results: list[BriefSweepResult] = []
    for brief_path, brief, load_reason in loaded:
        brief_stem = Path(brief_path).stem

        if brief is None:
            failed_load = DrawOutcome(
                brief_path,
                brief_stem,
                None,
                -1,
                FAIL_STATUS,
                load_reason,
                None,
                None,
                None,
                arm=resolved_arm,
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
            if (available_records and gate_client is not None)
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

    summary = SweepSummary(
        brief_results,
        len(all_outcomes),
        ok_count,
        fail_count,
        skip_count,
        arm=resolved_arm,
        commit=_current_commit_sha(),
    )
    write_sweep_summary(summary, sweep_dir)
    return summary


def _draw_outcome_to_json(outcome: DrawOutcome) -> dict[str, Any]:
    return {
        "brief_path": outcome.brief_path,
        "brief_stem": outcome.brief_stem,
        "brief_id": outcome.brief_id,
        "draw_index": outcome.draw_index,
        "status": outcome.status,
        "reason": outcome.reason,
        "latency_seconds": outcome.latency_seconds,
        "record_path": str(outcome.record_path) if outcome.record_path is not None else None,
        "report_path": str(outcome.report_path) if outcome.report_path is not None else None,
        "arm": outcome.arm,
        "distinct_sources_cited": outcome.distinct_sources_cited,
    }


def _quorum_to_json(quorum: QuorumResult) -> dict[str, Any]:
    return {
        "n_draws": quorum.n_draws,
        "dispositions": list(quorum.dispositions),
        "disposition_agreement_rate": quorum.disposition_agreement_rate,
        "claim_kind_counts": list(quorum.claim_kind_counts),
        "claim_kind_agreement_rate": quorum.claim_kind_agreement_rate,
    }


def _brief_result_to_json(result: BriefSweepResult) -> dict[str, Any]:
    return {
        "brief_path": result.brief_path,
        "brief_stem": result.brief_stem,
        "brief_id": result.brief_id,
        "draws": [_draw_outcome_to_json(outcome) for outcome in result.draws],
        "gate_reports": {name: report.to_json() for name, report in result.gate_reports.items()},
        "quorum": _quorum_to_json(result.quorum),
        "cost": result.cost,
    }


def sweep_summary_to_json(summary: SweepSummary) -> dict[str, Any]:
    """`summary`'s whole JSON-serializable shape -- every field
    `format_sweep_summary` prints, plus the per-draw `latency_seconds` and
    `record_path` its text rendering omits. `write_sweep_summary` is this
    function's only caller in this module; it is exported separately so a
    caller wanting just the dict (no file write) can still get it."""
    return {
        "briefs": [_brief_result_to_json(result) for result in summary.briefs],
        "total_draws": summary.total_draws,
        "ok_count": summary.ok_count,
        "fail_count": summary.fail_count,
        "skip_count": summary.skip_count,
        "arm": summary.arm,
        "commit": summary.commit,
    }


def write_sweep_summary(summary: SweepSummary, sweep_dir: Path) -> Path:
    """Persist `summary` to `<sweep_dir>/summary.json` -- the machine-
    readable counterpart of `format_sweep_summary`'s console text. `run_sweep`
    calls this itself (once, at the end of every invocation, including a
    resumed one) so the figures survive a restart: `console.log` output is
    plain text appended across restarts and a resumed pair's `latency_seconds`
    prints as SKIP with no number (module docstring), so the only place the
    full, current-as-of-this-invocation summary exists as data is this file."""
    sweep_dir = Path(sweep_dir)
    sweep_dir.mkdir(parents=True, exist_ok=True)
    out_path = sweep_dir / "summary.json"
    out_path.write_text(
        json.dumps(sweep_summary_to_json(summary), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return out_path


def format_sweep_summary(summary: SweepSummary) -> str:
    """Human-readable rendering for the CLI: the arm and commit this sweep
    ran at (issue #808), one block per brief (draw statuses, quorum
    agreement, gate verdicts), then an end-of-sweep tally."""
    commit_str = summary.commit if summary.commit is not None else "unknown"
    lines: list[str] = [f"arm: {summary.arm} commit: {commit_str}"]
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
            lines.append(f"  gate {gate_name}: {verdict_text(report.passed)}")
    lines.append(
        f"sweep: briefs={len(summary.briefs)} total_draws={summary.total_draws} "
        f"ok={summary.ok_count} skipped={summary.skip_count} failed={summary.fail_count}"
    )
    return "\n".join(lines)
