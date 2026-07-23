"""Common rung-3 gate harness (issue #262, specs/PHASE-B.md §10, §8 P0-12).

A **gate** scores one or more named metrics over a directory of analysis
records (§7.3) and writes a JSON report. This module owns the shape every
gate shares: `MetricResult` (one metric's `{metric, value, threshold,
comparison, passed, n}`, plus a free-form `detail` dict for anything a
specific metric needs to name, e.g. failing claim_ids), `GateReport` (the
envelope: `{gate, corpus_pin, trusted, passed, metrics: [...]}`), threshold
resolution from `config/pipeline.yaml`'s `gates:` block (never a literal in
a gate module), and the `trusted` computation.

**A gate report is generic enough to carry more than one metric** because
§10's own gate table names two metrics for attribution fidelity
(`attribution_completeness` + `b_seam_mislabel_rate`) and, per the sprint
plan, two apiece for the synthesis-quality and calibration gates landing in
later slices (issues #263/#264) -- this is the shape those slices plug into
without changing this module.

**`trusted` (§9).** A dry-run number is never a trusted number: `trusted` is
`True` only when BOTH an unambiguous corpus-pin manifest exists
(`evals/corpus_pin/*.json`, `axial.eval.corpus_pin`) AND at least one
academic-authored hard case exists directly under `evals/cases/*.json`
(non-recursive -- the simulated stand-in cases live one level deeper, under
`evals/cases/sim/`, and must never be mistaken for the real referee data,
see docs/decisions DEC-29). Building and dry-running a gate never waits on
either.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from axial.eval.corpus_pin import EVALS_DIR as CORPUS_PIN_DIR
from axial.eval.corpus_pin import CorpusPinError, resolve_pin_id
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH

# Where a gate report lands in dry-run mode (§10: "evals/reports/<run>.json"),
# named after the gate itself -- there is no `--run` flag (this codebase's
# convention: no CLI flag for a data-root path nobody needs to override, see
# axial.eval.corpus_pin's own EVALS_DIR docstring).
REPORTS_DIR = Path("evals") / "reports"

# The academic-authored hard-case directory (§9, eval #1's referee data).
# Deliberately non-recursive: `evals/cases/sim/`'s simulated stand-ins (DEC-29)
# must never count as the real referee data trusted numbers require.
CASES_DIR = Path("evals") / "cases"

Comparison = Literal["gte", "lte"]

# §10's stated starting thresholds -- TUNABLE, never asserted as final
# (tuning them is explicitly out of this issue's scope). config/pipeline.yaml's
# `gates:` block is the carried source of truth; this is only the code-level
# fallback a caller/test gets when the file or a key is absent, mirroring
# every other `DEFAULT_*_BY_PASS` fallback convention in `axial.llm`.
DEFAULT_GATE_THRESHOLDS: dict[str, float] = {
    "attribution_completeness": 1.00,
    "b_seam_mislabel_rate": 0.05,
    "grounding_support_rate": 0.90,
    "premise_catch_rate": 0.80,
}

# The comparison direction is a property of what each metric MEANS, not
# something an operator tunes -- a config option for direction is a config
# option nobody would ever set differently, so it lives in code, not config.
METRIC_COMPARISON: dict[str, Comparison] = {
    "attribution_completeness": "gte",
    "b_seam_mislabel_rate": "lte",
    "grounding_support_rate": "gte",
    "premise_catch_rate": "gte",
}


class GateError(Exception):
    """Base class for all rung-3 gate-harness errors."""


class UnknownMetricError(GateError):
    """Raised when a threshold/comparison is requested for a metric name
    no gate in this harness declares -- a typo'd metric name must not
    silently resolve to some default direction/threshold."""

    def __init__(self, metric: str):
        self.metric = metric
        super().__init__(
            f"unknown gate metric {metric!r}; expected one of {sorted(METRIC_COMPARISON)!r}"
        )


@dataclass(frozen=True)
class MetricResult:
    """One metric's verdict: `value` is `None` only when the metric had
    nothing to evaluate (an empty input) and is being reported as a failed,
    named-reason gate rather than a vacuous pass (module docstring)."""

    metric: str
    value: float | None
    threshold: float
    comparison: Comparison
    passed: bool
    n: int
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "comparison": self.comparison,
            "passed": self.passed,
            "n": self.n,
            **self.detail,
        }


@dataclass(frozen=True)
class GateReport:
    """A gate's whole verdict: one or more `MetricResult`s, the resolved
    corpus_pin id (or `None`), and whether this run's numbers are trusted
    (module docstring). `passed` is the conjunction of every metric's own
    `passed` -- a gate with two metrics ships only when both do."""

    gate: str
    corpus_pin: str | None
    trusted: bool
    metrics: list[MetricResult]

    @property
    def passed(self) -> bool:
        return all(metric.passed for metric in self.metrics)

    def to_json(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "corpus_pin": self.corpus_pin,
            "trusted": self.trusted,
            "passed": self.passed,
            "metrics": [metric.to_json() for metric in self.metrics],
        }


def resolve_threshold(metric: str, config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> float:
    """The tunable starting threshold for `metric` (§10): `config/
    pipeline.yaml`'s `gates.<metric>` key is the carried source of truth,
    falling back to `DEFAULT_GATE_THRESHOLDS` when the file or key is
    absent -- never a literal at a gate's own call site."""
    if metric not in METRIC_COMPARISON:
        raise UnknownMetricError(metric)
    configured: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle) or {}
        configured = document.get("gates", {}) or {}
    if metric in configured:
        return float(configured[metric])
    return DEFAULT_GATE_THRESHOLDS[metric]


def comparison_for(metric: str) -> Comparison:
    if metric not in METRIC_COMPARISON:
        raise UnknownMetricError(metric)
    return METRIC_COMPARISON[metric]


def _compare(value: float, threshold: float, comparison: Comparison) -> bool:
    if comparison == "gte":
        return value >= threshold
    return value <= threshold


def build_metric_result(
    metric: str,
    *,
    numerator: int,
    denominator: int,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    detail: dict[str, Any] | None = None,
    empty_denominator_fails: bool,
) -> MetricResult:
    """Build one `MetricResult` for a `numerator/denominator` rate metric.

    `empty_denominator_fails` distinguishes the two cases this harness's
    inner-loop checklist calls out: a *hard* gate metric (`attribution_
    completeness`, `grounding_support_rate`) whose denominator is zero
    because nothing was found to evaluate at all must report `passed:
    False` with a named reason -- never a vacuous 1.00 (module docstring;
    plan inner unit test 5). A *sampled* metric restricted to a claim kind
    (`b_seam_mislabel_rate` over kind-"b" claims) legitimately has nothing
    to sample when a non-empty record set simply carries no claim of that
    kind -- that is a real "zero violations found because zero applicable"
    state, reported with `n: 0` and a passing (vacuous-but-honest) rate,
    never silently omitted from the report.
    """
    threshold = resolve_threshold(metric, config_path)
    comparison = comparison_for(metric)
    detail = dict(detail or {})

    if denominator == 0:
        if empty_denominator_fails:
            detail.setdefault("reason", "no claims found to evaluate")
            return MetricResult(
                metric=metric,
                value=None,
                threshold=threshold,
                comparison=comparison,
                passed=False,
                n=0,
                detail=detail,
            )
        value = 0.0
    else:
        value = numerator / denominator

    return MetricResult(
        metric=metric,
        value=value,
        threshold=threshold,
        comparison=comparison,
        passed=_compare(value, threshold, comparison),
        n=denominator,
        detail=detail,
    )


def load_records(records_dir: Path) -> list[dict[str, Any]]:
    """Every `*.json` file directly under `records_dir`, parsed and sorted
    by filename for determinism -- the dev-brief-or-hand-built analysis
    records a gate scores in `--dry-run` mode (§9), never the full vault."""
    if not records_dir.is_dir():
        raise GateError(f"no records directory found at {records_dir}")
    records = []
    for path in sorted(records_dir.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def resolve_corpus_pin(evals_dir: Path | None = None) -> str | None:
    """The resolved corpus-pin id, or `None` when no unambiguous pin exists
    (missing or ambiguous both count as "no trusted pin" -- see module
    docstring)."""
    try:
        return resolve_pin_id(evals_dir if evals_dir is not None else CORPUS_PIN_DIR)
    except CorpusPinError:
        return None


def academic_cases_present(cases_dir: Path | None = None) -> bool:
    """Whether at least one academic-authored hard case exists directly
    under `cases_dir` (default `CASES_DIR`) -- non-recursive, so the
    simulated stand-ins under `evals/cases/sim/` never count (module
    docstring)."""
    directory = cases_dir if cases_dir is not None else CASES_DIR
    if not directory.is_dir():
        return False
    return any(directory.glob("*.json"))


def resolve_trusted(
    *, evals_dir: Path | None = None, cases_dir: Path | None = None
) -> tuple[str | None, bool]:
    """`(corpus_pin, trusted)`: `trusted` is `True` only when both an
    unambiguous corpus pin AND at least one real academic case exist (§9)."""
    corpus_pin = resolve_corpus_pin(evals_dir)
    trusted = corpus_pin is not None and academic_cases_present(cases_dir)
    return corpus_pin, trusted


def write_report(report: GateReport, *, reports_dir: Path | None = None) -> Path:
    """Write `report` to `<reports_dir>/<gate>.json` (default `REPORTS_DIR`),
    returning the written path. Byte-for-byte deterministic for a fixed
    report (sorted keys, no timestamp), mirroring `axial.eval.corpus_pin.
    write_pin`'s own serialization convention."""
    directory = reports_dir if reports_dir is not None else REPORTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    out_path = directory / f"{report.gate}.json"
    out_path.write_text(
        json.dumps(report.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


def format_report(report: GateReport) -> str:
    """Human-readable rendering for the CLI: one line per metric, naming
    value/threshold/pass-fail, then the overall verdict and trust flag."""
    lines = [f"gate: {report.gate}"]
    for metric in report.metrics:
        verdict = "PASS" if metric.passed else "FAIL"
        value_str = "n/a" if metric.value is None else f"{metric.value:.4f}"
        lines.append(
            f"  {metric.metric}: {verdict} (value={value_str}, "
            f"threshold={metric.threshold}, n={metric.n})"
        )
        reason = metric.detail.get("reason")
        if reason:
            lines.append(f"    reason: {reason}")
        failing_claim_ids = metric.detail.get("failing_claim_ids")
        if failing_claim_ids:
            lines.append(f"    failing claim_ids: {', '.join(failing_claim_ids)}")
        missed_brief_ids = metric.detail.get("missed_brief_ids")
        if missed_brief_ids:
            lines.append(f"    missed brief_ids: {', '.join(missed_brief_ids)}")
    lines.append(f"overall: {'PASS' if report.passed else 'FAIL'}")
    lines.append(f"corpus_pin: {report.corpus_pin}")
    lines.append(f"trusted: {report.trusted}")
    return "\n".join(lines)
