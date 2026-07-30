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

**`trusted` (§9.2).** A dry-run number is never a trusted number: `trusted`
is `True` exactly when an unambiguous corpus-pin manifest resolves
(`evals/corpus_pin/*.json`, `axial.eval.corpus_pin`). Building and
dry-running a gate never waits on it.

This used to carry a second conjunct -- at least one academic-authored hard
case directly under `evals/cases/*.json` -- which was correct while academic
cases were merely pending. With #250/#295 closed not-planned nothing will
ever land there, so the conjunct was permanently false and every one of the
five gates reported `trusted: false` forever, including the four that never
needed academic input at all (issue #380). All five are **corpus-anchored**:
each judgment is anchored to material the repo or vault already holds, so
none needs a human referee (§9.1). The conjunct is deleted rather than left
inert, along with the `evals/cases/` seam it read -- an unsatisfiable
condition guarding a directory nothing will ever populate is dead weight
that reads as a live requirement. `evals/cases/sim/` (DEC-29) is unaffected:
it is sim-case input data, never a trust condition.

Answer quality is not scored here at all. It is measured offline by the
§9.4 sealed-packet reviewer panel, which carries its own trust condition (a
passing positive control) and reports in the separate refereed tier. No
gate report waits on a panel verdict (§9.2).
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
from axial.yaml_loader import SAFE_LOADER

# Where a gate report lands in dry-run mode (§10: "evals/reports/<run>.json"),
# named after the gate itself -- there is no `--run` flag (this codebase's
# convention: no CLI flag for a data-root path nobody needs to override, see
# axial.eval.corpus_pin's own EVALS_DIR docstring).
REPORTS_DIR = Path("evals") / "reports"

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
    # Synthesis quality (issue #263, §10 Principle IV).
    "counter_position_presence_rate": 0.95,
    # steelman_quality has no spec-stated number -- §10 names only "the eval
    # #1 rubric bar", not authored yet (out of this slice's scope). 0.90 is a
    # starting hypothesis in the same spirit as the other judged-sample
    # thresholds above, tuned once the rubric lands.
    "steelman_quality": 0.90,
    # Calibration (issue #263, §10 Principle V, §7.4): the band-wise
    # reliability tolerance -- how far an observed band's judged-correctness
    # rate may sit from that band's stated target rate. See
    # src/axial/gates/calibration.py's module docstring for why this is the
    # metric §10 v1.1 settled on (band-wise, not ECE/Brier).
    "band_reliability": 0.15,
    "premise_catch_rate": 0.80,
}

# The comparison direction is a property of what each metric MEANS, not
# something an operator tunes -- a config option for direction is a config
# option nobody would ever set differently, so it lives in code, not config.
METRIC_COMPARISON: dict[str, Comparison] = {
    "attribution_completeness": "gte",
    "b_seam_mislabel_rate": "lte",
    "grounding_support_rate": "gte",
    "counter_position_presence_rate": "gte",
    "steelman_quality": "gte",
    "band_reliability": "lte",
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
    """One metric's verdict: `value` is `None` when the metric had nothing
    (or not enough) to evaluate.

    `passed` is tri-state (issues #401/#402): `True`/`False` are a real
    verdict; `None` is **not-scoreable** -- the sample was empty or too small
    to mean anything, and the metric is neither a pass nor a fail. A sample
    too small to mean anything must say so, not manufacture a verdict in
    either direction: a metric that vacuously "passes" on zero observations
    reads as a green light for a check that never ran, and a metric that
    "fails" an input it never had anything to evaluate sends a reader
    debugging the wrong thing. Every caller that folds `passed` into an
    aggregate (`GateReport.passed` below, `axial.brief.sweep`'s per-brief
    console summary) must keep `None` distinguishable from both real
    verdicts -- collapsing it back to a boolean one level up defeats the
    whole point.

    A fourth condition -- **not-applicable** (issue #405) -- is not a fourth
    `passed` value: it is a real pass (`True`, so it never blocks release)
    carrying `detail[NOT_APPLICABLE_DETAIL_KEY] = True`, set by
    `not_applicable_metric` below. Use it only when a SIBLING metric's own
    passing verdict already accounts for why this one has nothing to
    measure (e.g. `steelman_quality` when `counter_position_presence_rate`
    passed because every contested record was cleanly disclosed, never
    withheld) -- never as a shortcut back to #401's plain vacuous pass.
    `metric_verdict_text` renders it distinctly from an ordinary pass."""

    metric: str
    value: float | None
    threshold: float
    comparison: Comparison
    passed: bool | None
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
    (module docstring). `passed` is tri-state, mirroring `MetricResult.
    passed` one level up (issues #401/#402): `False` if any metric actually
    failed (a not-scoreable metric elsewhere never hides a real failure),
    else `None` if any metric is not-scoreable (the gate never fully ran, so
    it cannot report a clean pass either), else `True` only when every
    metric ran and passed."""

    gate: str
    corpus_pin: str | None
    trusted: bool
    metrics: list[MetricResult]

    @property
    def passed(self) -> bool | None:
        if any(metric.passed is False for metric in self.metrics):
            return False
        if any(metric.passed is None for metric in self.metrics):
            return None
        return True

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
            document = yaml.load(handle, Loader=SAFE_LOADER) or {}
        configured = document.get("gates", {}) or {}
    if metric in configured:
        return float(configured[metric])
    return DEFAULT_GATE_THRESHOLDS[metric]


def comparison_for(metric: str) -> Comparison:
    if metric not in METRIC_COMPARISON:
        raise UnknownMetricError(metric)
    return METRIC_COMPARISON[metric]


# A rate that lands exactly on its threshold can still miss a raw `<=`/`>=`
# comparison by a single float ULP (issue #402: a computed 0.15000000000000002
# reported `passed: false` against a 0.15 threshold that was, in every sense
# that matters, exactly met -- and the observed run showed that boundary was
# the BEST result any brief achieved, not a rare edge). `compare` absorbs
# float-representation error only; it is many orders of magnitude below any
# real difference this harness's rate metrics ever produce (their smallest
# meaningful step is 1/n for whatever sample size scored them).
_FLOAT_TOLERANCE = 1e-9


def compare(value: float, threshold: float, comparison: Comparison) -> bool:
    """Compare `value` against `threshold` in the direction `comparison`
    names, tolerant of float-representation error at the boundary. The one
    shared comparison every gate's own pass/fail check should route through,
    including gates (like `axial.gates.calibration`) that build their
    `MetricResult` by hand rather than through `build_metric_result`."""
    if comparison == "gte":
        return value >= threshold - _FLOAT_TOLERANCE
    return value <= threshold + _FLOAT_TOLERANCE


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
        passed=compare(value, threshold, comparison),
        n=denominator,
        detail=detail,
    )


def not_scoreable_metric(
    metric: str,
    *,
    reason: str,
    n: int = 0,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    detail: dict[str, Any] | None = None,
) -> MetricResult:
    """Build a **not-scoreable** `MetricResult` (issues #401/#402):
    `value: None`, `passed: None`, a named `reason` -- distinct from both of
    `build_metric_result`'s own empty-denominator branches (a vacuous pass,
    or a hard fail), which stay exactly as they were for the gates that
    already rely on that two-way choice (module docstring).

    The shared seam for "this sample is empty, or too small to mean
    anything" wherever a gate needs it: `axial.gates.synthesis_quality` at
    `n: 0` (steelman_quality's own zero-counter-positions case, and
    counter_position_presence_rate's zero-contested-subset case) and
    `axial.gates.calibration` at n below the per-band minimum sample size.
    """
    threshold = resolve_threshold(metric, config_path)
    comparison = comparison_for(metric)
    merged_detail = dict(detail or {})
    merged_detail["reason"] = reason
    return MetricResult(
        metric=metric,
        value=None,
        threshold=threshold,
        comparison=comparison,
        passed=None,
        n=n,
        detail=merged_detail,
    )


# A `detail` marker distinguishing "not-applicable" from an ordinary pass
# (issue #405, a #401 follow-up): `passed` alone cannot carry the
# distinction, since both a real pass and "nothing to measure" report
# `True` -- a report reader (and `format_report`) checks this key instead.
NOT_APPLICABLE_DETAIL_KEY = "not_applicable"


def not_applicable_metric(
    metric: str,
    *,
    reason: str,
    n: int = 0,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    detail: dict[str, Any] | None = None,
) -> MetricResult:
    """Build a **not-applicable** `MetricResult` (issue #405, following
    #401/#402): the check had legitimately nothing to measure -- not because
    the sample was too small or genuinely unknown (`not_scoreable_metric`
    above), but because a SIBLING metric's own passing verdict already
    accounts for the absence. `steelman_quality` has nothing to judge when
    every contested record was cleanly disclosed as one-sided
    (specs/PHASE-B.md §7.8: disclosure is an equal-standing clean outcome,
    not a degraded one) and `counter_position_presence_rate` already scored
    that as a pass. `passed: True` so this never blocks release the way a
    real failure or a not-scoreable metric would, but `reason` names the
    disclosure that made the check unnecessary, never a success -- never to
    be mistaken for #401's vacuous `passed: true` on a check that simply
    never ran for no accounted reason."""
    threshold = resolve_threshold(metric, config_path)
    comparison = comparison_for(metric)
    merged_detail = dict(detail or {})
    merged_detail["reason"] = reason
    merged_detail[NOT_APPLICABLE_DETAIL_KEY] = True
    return MetricResult(
        metric=metric,
        value=None,
        threshold=threshold,
        comparison=comparison,
        passed=True,
        n=n,
        detail=merged_detail,
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


def resolve_trusted(*, evals_dir: Path | None = None) -> tuple[str | None, bool]:
    """`(corpus_pin, trusted)`: `trusted` is `True` exactly when an
    unambiguous corpus pin resolves (§9.2, issue #380). There is no second
    condition -- see the module docstring for why the academic-case
    conjunct was removed rather than merely left unsatisfied."""
    corpus_pin = resolve_corpus_pin(evals_dir)
    return corpus_pin, corpus_pin is not None


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


def verdict_text(passed: bool | None) -> str:
    """Render a tri-state `passed` (`MetricResult.passed`/`GateReport.
    passed`) as text: `None` (not-scoreable) is never collapsed into "FAIL"
    just because it is falsy in Python, and never into "PASS" either --
    that collapse is the exact bug issues #401/#402 are about."""
    if passed is None:
        return "NOT-SCOREABLE"
    return "PASS" if passed else "FAIL"


def metric_verdict_text(metric: MetricResult) -> str:
    """Render one `MetricResult`'s verdict, distinguishing a real pass from
    "not-applicable" (issue #405) -- `verdict_text` alone cannot, since both
    report `passed: True`. Checks `NOT_APPLICABLE_DETAIL_KEY` on top of the
    tri-state `passed` `verdict_text` already renders."""
    if metric.detail.get(NOT_APPLICABLE_DETAIL_KEY):
        return "PASS (not applicable)"
    return verdict_text(metric.passed)


def format_report(report: GateReport) -> str:
    """Human-readable rendering for the CLI: one line per metric, naming
    value/threshold/pass-fail, then the overall verdict and trust flag."""
    lines = [f"gate: {report.gate}"]
    for metric in report.metrics:
        verdict = metric_verdict_text(metric)
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
        failing_brief_ids = metric.detail.get("failing_brief_ids")
        if failing_brief_ids:
            lines.append(f"    failing brief_ids: {', '.join(failing_brief_ids)}")
        missed_brief_ids = metric.detail.get("missed_brief_ids")
        if missed_brief_ids:
            lines.append(f"    missed brief_ids: {', '.join(missed_brief_ids)}")
    lines.append(f"overall: {verdict_text(report.passed)}")
    lines.append(f"corpus_pin: {report.corpus_pin}")
    lines.append(f"trusted: {report.trusted}")
    return "\n".join(lines)
