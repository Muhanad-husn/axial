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
exactly one grounding number per `(brief, arm)`. It sits beside the count of
draws it was scored over -- exactly where a mean and its `n` sit two columns
along -- so the column is NAMED `pooled_rate`, a header line above the table
says which figures are pooled over draws and which are per draw, and the
legend says it a third time. A decimal beside a draw count reads as a mean
unless the page refuses to let it.

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

_COLUMNS = (
    "brief",
    "arm",
    "grounding",
    "pooled_rate",
    "gate_draws",
    "sources",
    "range",
    "src_draws",
)


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
    # the sweep scored the grounding gate over. 0 means none did. A RESUMED
    # draw counts, because its record was already on disk (`_brief_figures`).
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
    # The set `_score_brief_gates` was handed is `run_sweep`'s
    # `available_records`: the draws whose record is not None. A draw's own
    # `record_path` is set when and only when that record exists, so it is
    # the exact mirror -- and the only one. Status is not: a SKIPped draw is
    # a RESUMED draw, its record is on disk and the sweep scores it, so
    # `== OK_STATUS` would undercount every resumed draw (the #809 corpus
    # run has one in every arm). `!= FAIL_STATUS` happens to agree today but
    # says nothing about records, which is what the number means.
    gate_draws = sum(1 for draw in draws if draw.get("record_path"))
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


def _arm_label(arm: ArmSweep) -> str:
    """An arm named the way an operator can act on it. The label comes from
    inside `summary.json`; the directory is what they typed. A refusal
    naming only the label leaves them to map it back to a path themselves,
    which is exactly the mistake -- pointing at a stale directory -- that
    most of these refusals catch."""
    return f"{arm.arm!r} ({arm.path})"


def _brief_list(stems: Sequence[str]) -> str:
    return ("brief " if len(stems) == 1 else "briefs ") + ", ".join(repr(stem) for stem in stems)


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
    """Every differing brief, grouped by the arm that has it -- not the
    first one. Arms that differ by four briefs are one mistake, and an
    operator told about one of them fixes it, reruns, and is refused
    again."""
    only_reference = sorted(set(reference.brief_stems) - set(other.brief_stems))
    only_other = sorted(set(other.brief_stems) - set(reference.brief_stems))
    if not only_reference and not only_other:
        return
    parts = [
        f"{_brief_list(stems)} present in arm {_arm_label(present)} "
        f"and missing from arm {_arm_label(absent)}"
        for present, absent, stems in (
            (reference, other, only_reference),
            (other, reference, only_other),
        )
        if stems
    ]
    raise LayerComparisonError("; ".join(parts))


def _refuse_different_draws(reference: ArmSweep, other: ArmSweep) -> None:
    if reference.draws != other.draws:
        raise LayerComparisonError(
            f"arm {_arm_label(reference)} ran {_plural(reference.draws, 'draw')}, "
            f"arm {_arm_label(other)} ran {_plural(other.draws, 'draw')}"
        )


def _refuse_uncomparable_commits(arms: Sequence[ArmSweep]) -> None:
    for arm in arms:
        if arm.commit is None:
            raise LayerComparisonError(
                f"arm {_arm_label(arm)} recorded no commit, so it cannot be compared "
                f"against any other arm -- git was unavailable when that sweep ran"
            )
    reference = arms[0]
    for other in arms[1:]:
        if other.commit != reference.commit:
            raise LayerComparisonError(
                f"arm {_arm_label(reference)} built at {reference.commit}, "
                f"arm {_arm_label(other)} at {other.commit}"
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


_COLUMN_LEGEND = (
    "columns",
    "  grounding:   the gate's verdict for that (brief, arm). The sweep scores it",
    "               ONCE over that brief's pooled draw records, so it is one",
    "               verdict, not a per-draw majority. NOT-SCOREABLE is neither a",
    "               pass nor a fail.",
    "  pooled_rate: grounding_support_rate (specs/PHASE-B.md section 10), the",
    "               gate's own metric -- the same single number that verdict came",
    "               from, over the same pooled draw records. NOT a per-draw mean.",
    "  gate_draws:  how many of that brief's draws produced a record -- the pooled",
    "               sample grounding and pooled_rate were scored over, not a",
    "               sample size a mean was divided by.",
    "  sources:     distinct sources cited, averaged across that brief's own draws.",
    "               This one IS a per-draw mean.",
    "  range:       min-max of that same per-draw count. The spread, per brief.",
    "  src_draws:   how many of that brief's draws reported a source count -- the",
    "               n of the sources mean and of the range beside it.",
)

# Printed only where such a cell is actually in the table: a glossary entry
# for a value nothing on the page shows is noise the reader has to rule out.
_CELL_LEGEND: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        _MISSING,
        (
            "  missing:     that brief produced no usable draw in that arm. Reported,",
            "               never averaged over and never dropped.",
        ),
    ),
    (
        _NOT_SCORED,
        (
            "  not-scored:  that sweep ran without gate scoring, so no grounding",
            "               figure exists to read.",
        ),
    ),
    (
        _ABSENT,
        (
            "  -:           no figure to print. Under pooled_rate, the gate reported",
            "               no value; under sources and range, no draw of that brief",
            "               reported a source count.",
        ),
    ),
)


def _cell_legend(rows: Sequence[tuple[str, ...]]) -> list[str]:
    on_the_page = {cell for row in rows for cell in row}
    lines: list[str] = []
    for value, entry in _CELL_LEGEND:
        if value in on_the_page:
            lines.extend(entry)
    return ["", "cell values", *lines] if lines else []


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
    header.append("figures are per brief; no figure here is pooled across briefs")
    header.append(
        "grounding and pooled_rate: ONE figure per row, scored over that brief's "
        "pooled draw records"
    )
    header.append(
        "sources, range and src_draws: a mean, a spread and an n, across that brief's own draws"
    )
    header.append("")

    rows = [_cells(figures) for figures in comparison.rows()]
    legend = list(_COLUMN_LEGEND) + _cell_legend(rows)
    return "\n".join(header + _table(rows) + [""] + legend)
