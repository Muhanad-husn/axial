"""One panel measurement run, control first (issue #385, specs/PHASE-B.md
§9.4, DEC-43).

The order is the whole point: **the positive control runs before the sample,
and its result decides whether any number from the sample is reportable.**
A panel that has not caught planted defects is not a referee yet, so this
module never lets a caller reach `trusted: true` by asserting it.

This is an offline instrument, not a pipeline stage. Nothing in a brief run
calls into this module, no analysis record gains a reviewer field, and no
rung-3 gate report waits on a verdict here (§9.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from axial.llm import LLMClient
from axial.panel.control import ControlReport, Plant, plant_all, score_control
from axial.panel.packet import build_packet
from axial.panel.review import MIN_REVIEWERS, PanelReport, format_panel_report, review_packet
from axial.panel.control import format_control_report


@dataclass(frozen=True)
class PanelRun:
    """A measurement run: its control, its per-record reports, and the frame
    every number in it must be read against."""

    control: ControlReport
    reports: list[PanelReport]
    frame: dict[str, Any] = field(default_factory=dict)

    @property
    def trusted(self) -> bool:
        return self.control.passed

    def to_json(self) -> dict[str, Any]:
        return {
            "trusted": self.trusted,
            "referee": "model panel (specs/PHASE-B.md §9.4) -- never a human expert",
            "frame": dict(self.frame),
            "control": self.control.to_json(),
            "reports": [report.to_json() for report in self.reports],
        }


def run_control(
    control_record: dict[str, Any],
    *,
    client: LLMClient,
    corpus_pin: str | None,
    vault_dir: Path | None = None,
    n_reviewers: int = MIN_REVIEWERS,
) -> ControlReport:
    """Plant all three defects into `control_record`, review each mutated
    copy, and score whether the panel named them. Raises
    `PlantNotApplicableError` if the record cannot carry all three."""
    results: list[tuple[Plant, PanelReport]] = []
    for mutated, plant in plant_all(control_record):
        packet = build_packet(mutated, corpus_pin=corpus_pin, vault_dir=vault_dir)
        report = review_packet(
            packet,
            client=client,
            n_reviewers=n_reviewers,
            trusted=False,
            frame={"positive_control": plant.kind},
        )
        results.append((plant, report))
    return score_control(results)


def run_panel(
    records: list[dict[str, Any]],
    control_record: dict[str, Any],
    *,
    client: LLMClient,
    corpus_pin: str | None,
    vault_dir: Path | None = None,
    n_reviewers: int = MIN_REVIEWERS,
    frame: dict[str, Any] | None = None,
) -> PanelRun:
    """Run the control, then review every record in the sample.

    Every report carries `trusted` = the control's own verdict, so a panel
    with a known blind spot cannot emit a trusted number even by accident.
    The sample is still reviewed on a failed control -- the numbers are
    exactly as informative as the control says they are, and suppressing
    them would hide which packets a broken referee mis-scored.
    """
    control = run_control(
        control_record,
        client=client,
        corpus_pin=corpus_pin,
        vault_dir=vault_dir,
        n_reviewers=n_reviewers,
    )
    stated_frame = dict(frame or {})
    stated_frame.setdefault("corpus_pin", corpus_pin)
    stated_frame.setdefault("n_records", len(records))
    stated_frame.setdefault("n_reviewers", n_reviewers)

    reports = [
        review_packet(
            build_packet(record, corpus_pin=corpus_pin, vault_dir=vault_dir),
            client=client,
            n_reviewers=n_reviewers,
            trusted=control.passed,
            frame=stated_frame,
        )
        for record in records
    ]
    return PanelRun(control=control, reports=reports, frame=stated_frame)


def format_panel_run(run: PanelRun) -> str:
    lines = [format_control_report(run.control), ""]
    for report in run.reports:
        lines.append(format_panel_report(report))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
