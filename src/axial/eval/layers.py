"""The per-arm layer comparison (issue #809): a pure reader over the sweep
directories `axial brief sweep` already wrote, one per retrieval arm.

**It computes nothing new.** Every figure printed here was computed by the
sweep and persisted in that sweep's own `summary.json` (`axial.brief.sweep.
write_sweep_summary`): the grounding gate's verdict and rate come off the
persisted `GateReport`, and the per-draw `distinct_sources_cited` comes off
each persisted `DrawOutcome`. No model call, no retrieval, no second
gate-scoring path -- re-scoring a gate here would spend judge calls to
recompute a number already bought.

Two questions, one table (issue #809): `name` against `map` asks whether the
argument map beats the name layer, and `map` against `map+vocab` asks whether
the derived vocabulary adds anything. This command prints the figures for
both and answers neither.

Where the spread binds
--------------------------------------------------------------------------
Founder's standing call for this slice: **the spread binds where per-draw
values exist.** `distinct_sources_cited` is recorded per draw, so its figure
carries a genuine per-brief spread (mean plus min-max across that brief's own
draws). The grounding gate is NOT per draw -- `_score_brief_gates` runs each
gate ONCE per brief over that brief's pooled draw records -- so there is
exactly one grounding number per `(brief, arm)`, printed as the single pooled
figure it is, beside the count of draws it was scored over so no reader can
mistake it for a per-draw mean.

Per stratum, never pooled
--------------------------------------------------------------------------
`axial.panel.coherence_eval` already refuses a pooled system-wide mean, and
this holds the same line: every row is one `(brief, arm)` pair. There is no
field here that could hold a figure averaged across briefs.

No verdicts
--------------------------------------------------------------------------
The source count is a plain count. Nothing here marks an arm better or worse,
and nothing generates interpretive prose -- the interpretation belongs in the
run log, in the founder's own words. Two known misreadings live there too: a
drop in sources cited is not a regression (the argument map validated
*strong* on four sources against the name layer's *adequate* on eight), and a
margin narrower than the model's own variance is not a finding.

Refusals
--------------------------------------------------------------------------
Two sweep directories are only comparable when they cover the same briefs,
the same number of draws, and the same commit -- otherwise the difference the
table shows is not about the arms. Each refusal names the mismatch
specifically. A `commit` of `None` (git was unavailable when that sweep ran)
cannot be compared to anything and is refused rather than treated as a match
against another `None`.

The one case that is reported rather than refused: a brief that IS in every
arm's worklist but produced no usable draw in one of them (every draw FAILed,
so no record, no gate report and no source count). That cell prints
`missing`, never averaged over and never dropped. A brief set that differs
across arms is the other case, and that is a refusal: those directories do
not cover the same worklist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from axial.brief.sweep import FAIL_STATUS
from axial.gates import GROUNDING_GATE_NAME, verdict_text

# The grounding gate's own gated metric (specs/PHASE-B.md section 10,
# `axial.gates.grounding`). Its sibling `b_claim_contradiction_rate` is a
# reported-only number and is deliberately not read here: this table compares
# the gate, and a reported number nothing is measured against yet would read
# like one more verdict.
GROUNDING_METRIC = "grounding_support_rate"

SUMMARY_FILENAME = "summary.json"

_ABSENT = "-"
_MISSING = "missing"
_NOT_SCORED = "not-scored"

_COLUMNS = ("brief", "arm", "grounding", "rate", "gate_draws", "sources", "range", "src_draws")


class LayerComparisonError(Exception):
    """An unreadable sweep directory, or two directories that are not
    comparable. Raised before anything is printed -- a partial table read off
    directories that disagree is worse than no table."""


@dataclass(frozen=True)
class BriefArmFigures:
    """One `(brief, arm)` cell: the grounding gate's single pooled figure and
    the per-draw source counts it sits beside. Never merged with another
    brief's."""

    brief_stem: str
    arm: str
    # How many of this brief's draws produced a record -- the pooled sample
    # the sweep scored the grounding gate over. 0 means none did.
    gate_draws: int
    # Whether the sweep scored the grounding gate at all for this brief
    # (`axial brief smoke` runs with `score_gates=False`, so its directories
    # carry records and no gate reports).
    grounding_scored: bool
    # Tri-state, straight off the persisted `GateReport` (issues #401/#402):
    # `None` is not-scoreable, never collapsed into a pass or a fail.
    grounding_passed: bool | None
    grounding_rate: float | None
    # Each draw's own `distinct_sources_cited`, in draw order, for the draws
    # that reported one.
    source_counts: tuple[int, ...]

    @property
    def missing(self) -> bool:
        """This brief produced no usable draw in this arm."""
        return self.gate_draws == 0 and not self.source_counts

    @property
    def sources_mean(self) -> float | None:
        if not self.source_counts:
            return None
        return sum(self.source_counts) / len(self.source_counts)


@dataclass(frozen=True)
class ArmSweep:
    """One arm's persisted sweep, as this reader needs it. `figures` is keyed
    by brief stem in the order the sweep recorded them."""

    arm: str
    path: Path
    commit: str | None
    draws: int
    figures: dict[str, BriefArmFigures]

    @property
    def brief_stems(self) -> tuple[str, ...]:
        return tuple(self.figures)


@dataclass(frozen=True)
class LayerComparison:
    """Every arm's figures over one shared worklist, draw count and commit --
    `compare_arms` has already refused anything else, so the shared values are
    read off the first arm rather than stored twice. Rows are brief-major,
    arms in the order their directories were given."""

    arms: tuple[ArmSweep, ...]

    @property
    def commit(self) -> str:
        return str(self.arms[0].commit)

    @property
    def draws(self) -> int:
        return self.arms[0].draws

    @property
    def brief_stems(self) -> tuple[str, ...]:
        return self.arms[0].brief_stems

    def rows(self) -> list[BriefArmFigures]:
        return [arm.figures[stem] for stem in self.brief_stems for arm in self.arms]


def _grounding_figures(gate_reports: Any) -> tuple[bool, bool | None, float | None]:
    """`(scored, passed, rate)` off the persisted grounding `GateReport`.
    `passed` is read from the report's own persisted value rather than
    recomputed from its metrics -- `GateReport.to_json` writes the tri-state
    property out, and this reader never re-derives a verdict."""
    if not isinstance(gate_reports, dict):
        return False, None, None
    report = gate_reports.get(GROUNDING_GATE_NAME)
    if not isinstance(report, dict):
        return False, None, None
    rate = None
    for metric in report.get("metrics") or []:
        if isinstance(metric, dict) and metric.get("metric") == GROUNDING_METRIC:
            value = metric.get("value")
            rate = float(value) if isinstance(value, (int, float)) else None
            break
    return True, report.get("passed"), rate


def _brief_figures(payload: dict[str, Any], arm: str) -> BriefArmFigures:
    draws = [draw for draw in payload.get("draws") or [] if isinstance(draw, dict)]
    # The sweep's own definition of an available draw: one that produced a
    # record, which is exactly the set `_score_brief_gates` was handed. A
    # FAILed draw produced nothing.
    gate_draws = sum(1 for draw in draws if draw.get("status") != FAIL_STATUS)
    counts = tuple(
        int(draw["distinct_sources_cited"])
        for draw in draws
        if isinstance(draw.get("distinct_sources_cited"), int)
    )
    scored, passed, rate = _grounding_figures(payload.get("gate_reports"))
    return BriefArmFigures(
        brief_stem=str(payload.get("brief_stem")),
        arm=arm,
        gate_draws=gate_draws,
        grounding_scored=scored,
        grounding_passed=passed,
        grounding_rate=rate,
        source_counts=counts,
    )


def read_arm_sweep(sweep_dir: str | Path) -> ArmSweep:
    """One arm's `summary.json`, read and nothing more. Raises
    `LayerComparisonError` when the directory holds no sweep summary or an
    unreadable one -- never a partial read."""
    path = Path(sweep_dir) / SUMMARY_FILENAME
    if not path.is_file():
        raise LayerComparisonError(
            f"no sweep summary at {path} -- 'axial eval layers' reads the "
            f"{SUMMARY_FILENAME} that 'axial brief sweep' writes"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LayerComparisonError(f"unreadable sweep summary at {path}: {exc}") from exc
    if not isinstance(payload, dict) or "arm" not in payload or "briefs" not in payload:
        raise LayerComparisonError(f"{path} is not a sweep summary: no 'arm' and 'briefs' keys")

    arm = str(payload["arm"])
    briefs = [entry for entry in payload["briefs"] or [] if isinstance(entry, dict)]
    figures = {}
    for entry in briefs:
        cell = _brief_figures(entry, arm)
        figures[cell.brief_stem] = cell
    # One sweep draws every brief the same number of times, so the arm's draw
    # count is the most any of its briefs was drawn -- the MOST, because a
    # brief whose file never loaded records a single synthetic outcome
    # (`axial.brief.sweep`, `draw_index=-1`) that is not a draw anyone asked
    # for. Reading that as this arm's draw count would refuse the whole
    # comparison over a brief that never ran.
    draw_counts = [len(entry.get("draws") or []) for entry in briefs]
    return ArmSweep(
        arm=arm,
        path=Path(sweep_dir),
        commit=payload.get("commit"),
        draws=max(draw_counts) if draw_counts else 0,
        figures=figures,
    )


def _refuse_duplicate_arms(arms: Sequence[ArmSweep]) -> None:
    seen: dict[str, ArmSweep] = {}
    for arm in arms:
        first = seen.get(arm.arm)
        if first is not None:
            raise LayerComparisonError(
                f"arm {arm.arm!r} is recorded by two directories ({first.path} and "
                f"{arm.path}); each --arm-dir must be a different arm"
            )
        seen[arm.arm] = arm


def _refuse_different_briefs(reference: ArmSweep, other: ArmSweep) -> None:
    difference = sorted(set(reference.brief_stems) ^ set(other.brief_stems))
    if not difference:
        return
    stem = difference[0]
    present, absent = (
        (other.arm, reference.arm) if stem in other.brief_stems else (reference.arm, other.arm)
    )
    raise LayerComparisonError(
        f"brief {stem!r} present in arm {present!r} and missing from arm {absent!r}"
    )


def _refuse_different_draws(reference: ArmSweep, other: ArmSweep) -> None:
    if reference.draws != other.draws:
        raise LayerComparisonError(
            f"arm {reference.arm!r} ran {reference.draws} draws, "
            f"arm {other.arm!r} ran {other.draws}"
        )


def _refuse_uncomparable_commits(arms: Sequence[ArmSweep]) -> None:
    for arm in arms:
        if arm.commit is None:
            raise LayerComparisonError(
                f"arm {arm.arm!r} recorded no commit, so it cannot be compared "
                f"against any other arm -- git was unavailable when that sweep ran"
            )
    reference = arms[0]
    for other in arms[1:]:
        if other.commit != reference.commit:
            raise LayerComparisonError(
                f"arm {reference.arm!r} built at {reference.commit}, "
                f"arm {other.arm!r} at {other.commit}"
            )


def compare_arms(sweep_dirs: Sequence[str | Path]) -> LayerComparison:
    """Read every arm's sweep directory and check they are comparable.

    Two arms are accepted as well as three, and so is any larger number: the
    arm count is whatever was given. Zero is refused, and so are two
    directories recording the same arm -- that is an operator mistake, not a
    comparison."""
    if not sweep_dirs:
        raise LayerComparisonError(
            "no sweep directory given -- 'axial eval layers' needs at least one --arm-dir"
        )

    arms = tuple(read_arm_sweep(sweep_dir) for sweep_dir in sweep_dirs)
    _refuse_duplicate_arms(arms)
    # The acceptance criterion's own order -- same briefs, same draw count,
    # same commit -- so an operator comparing directories that differ in two
    # ways is told about the worklist first, which is the one that decides
    # whether the other two even matter.
    reference = arms[0]
    for other in arms[1:]:
        _refuse_different_briefs(reference, other)
    for other in arms[1:]:
        _refuse_different_draws(reference, other)
    _refuse_uncomparable_commits(arms)

    return LayerComparison(arms=arms)


def _cells(figures: BriefArmFigures) -> tuple[str, ...]:
    if figures.missing:
        return (
            figures.brief_stem,
            figures.arm,
            _MISSING,
            _ABSENT,
            "0",
            _MISSING,
            _ABSENT,
            "0",
        )
    if figures.grounding_scored:
        grounding = verdict_text(figures.grounding_passed)
        rate = _ABSENT if figures.grounding_rate is None else f"{figures.grounding_rate:.3f}"
    else:
        grounding, rate = _NOT_SCORED, _ABSENT
    counts = figures.source_counts
    mean = _ABSENT if figures.sources_mean is None else f"{figures.sources_mean:.1f}"
    spread = _ABSENT if not counts else f"{min(counts)}-{max(counts)}"
    return (
        figures.brief_stem,
        figures.arm,
        grounding,
        rate,
        str(figures.gate_draws),
        mean,
        spread,
        str(len(counts)),
    )


def _table(rows: Sequence[tuple[str, ...]]) -> list[str]:
    widths = [
        max(len(cells[index]) for cells in (_COLUMNS, *rows)) for index in range(len(_COLUMNS))
    ]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()

    return [line(_COLUMNS), line(["-" * width for width in widths])] + [line(row) for row in rows]


_LEGEND = (
    "grounding:   the gate's verdict for that (brief, arm). The sweep scores it",
    "             ONCE over that brief's pooled draw records, so it is one figure,",
    "             not a per-draw mean. NOT-SCOREABLE is neither a pass nor a fail.",
    "rate:        grounding_support_rate, the gate's own metric (specs/PHASE-B.md",
    "             section 10). '-' where the gate reported no value.",
    "gate_draws:  how many of that brief's draws produced a record -- the pooled",
    "             sample the grounding figure was scored over.",
    "sources:     distinct sources cited, averaged across that brief's own draws.",
    "range:       min-max of that same per-draw count; src_draws is how many draws",
    "             reported one. This is the spread, and it is per brief.",
    "not-scored:  that sweep ran without gate scoring, so no grounding figure",
    "             exists to read.",
    "missing:     that brief produced no usable draw in that arm. Reported, never",
    "             averaged over and never dropped.",
)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def format_layer_comparison(comparison: LayerComparison) -> str:
    """The table, in plain ASCII. Every cell is space-free, so a row is
    machine-splittable as well as readable."""
    arm_names = [arm.arm for arm in comparison.arms]
    header = [
        f"layer comparison: {_plural(len(arm_names), 'arm')} ({', '.join(arm_names)}), "
        f"{_plural(len(comparison.brief_stems), 'brief')}, "
        f"{_plural(comparison.draws, 'draw')} per brief per arm, "
        f"all at commit {comparison.commit}",
    ]
    if len(arm_names) > 1:
        pairs = "; ".join(f"{left} vs {right}" for left, right in zip(arm_names, arm_names[1:]))
        header.append(f"comparisons, in the order the arms were given: {pairs}")
    header.append("figures are per brief; nothing here is pooled across briefs")
    header.append("")

    rows = [_cells(figures) for figures in comparison.rows()]
    return "\n".join(header + _table(rows) + [""] + list(_LEGEND))
