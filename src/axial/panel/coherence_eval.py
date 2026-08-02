"""The argument-coherence eval track (specs/PHASE-C.md §10.2, §7.13, issue
#611 P0-10/P0-11/P0-12).

Offline, sampled, blocks nothing (§9, §10.2): no paper run reaches this, no
per-run gate (§10.1) ever reads its output, and it never runs against a
single paper -- its whole point is a measurement across a stratified sample.
`axial eval coherence` is a separate command from `axial paper` for exactly
that reason: it measures the system rather than producing one.

**The positive control runs first**, exactly as `axial.panel.run.run_panel`
already does for analysis records: its result decides whether any stratum
figure below is reportable as `trusted`, never whether it is computed. The
sample is still reviewed on a failed control (§7.9) -- suppressing the
numbers would hide which papers a broken referee mis-scored. `trusted`
qualifies this run's own instrument, never any paper: a failing control
blocks no paper's release and fails no per-run gate.

**Ships unrun.** A coherence sample must span more than one performance
tier and more than one model combination (§7.13); the corpus holds exactly
one paper record as of this PR, so no sample spec meeting that bar can be
built yet, let alone committed. This module and its CLI surface are
complete and tested against fixtures -- the first real run is gated on
having enough papers to stratify, not on anything left to build here.

**No pooled system-wide mean, ever** (§7.13, charter Principle V). Every
figure below is a `StratumCoherenceReport`; nothing in `CoherenceEvalReport`
averages across strata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from axial.llm import LLMClient
from axial.panel.control import ControlReport, Plant, plant_all, score_control
from axial.panel.packet import build_paper_packet
from axial.panel.review import BANDS, MIN_REVIEWERS, PanelReport, review_paper_packet
from axial.panel.sample import SampleSpec
from axial.paper.record import PAPERS_DIR

_SCORE_BY_BAND = {"weak": 0.0, "adequate": 0.5, "strong": 1.0}
_BAND_RANK = {band: rank for rank, band in enumerate(BANDS)}


class CoherenceEvalError(Exception):
    """Base class for coherence-eval-run failures."""


class PaperRecordNotFoundError(CoherenceEvalError):
    """Raised when a sample spec names a paper record that does not exist
    on disk. Raised before any packet is built or any reviewer is called."""

    def __init__(self, paper_brief_id: str, path: Path):
        self.paper_brief_id = paper_brief_id
        self.path = path
        super().__init__(f"no paper record for {paper_brief_id!r} at {path}")


def _load_paper_record(paper_brief_id: str, papers_dir: Path) -> dict[str, Any]:
    path = papers_dir / f"{paper_brief_id}.json"
    if not path.is_file():
        raise PaperRecordNotFoundError(paper_brief_id, path)
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class StratumCoherenceReport:
    """One stratum's own figure (§7.13). Never pooled with any other
    stratum's, and never averaged into a system-wide number -- there is no
    field anywhere in this module that could hold one."""

    stratum_id: str
    tier: str
    model_combination: str
    paper_brief_ids: tuple[str, ...]
    n_reviewer_scores: int
    argument_coherence_rate: float
    reviewer_spread: int

    def to_json(self) -> dict[str, Any]:
        return {
            "stratum_id": self.stratum_id,
            "tier": self.tier,
            "model_combination": self.model_combination,
            "paper_brief_ids": list(self.paper_brief_ids),
            "n_reviewer_scores": self.n_reviewer_scores,
            "argument_coherence_rate": self.argument_coherence_rate,
            "reviewer_spread": self.reviewer_spread,
        }


@dataclass(frozen=True)
class CoherenceEvalReport:
    sample_id: str
    corpus_pin: str
    control: ControlReport
    strata: list[StratumCoherenceReport]
    frame: dict[str, Any] = field(default_factory=dict)

    @property
    def trusted(self) -> bool:
        # §7.9: the control qualifies the INSTRUMENT, never a paper. A
        # failing control never blocks a paper's release and fails no
        # per-run gate (§10.1) -- it only means this run's own numbers are
        # not reportable as trusted.
        return self.control.passed

    def to_json(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "corpus_pin": self.corpus_pin,
            "trusted": self.trusted,
            "referee": "model panel (specs/PHASE-C.md §7.7-§7.9) -- never a human expert",
            "frame": dict(self.frame),
            "control": self.control.to_json(),
            "strata": [stratum.to_json() for stratum in self.strata],
        }


def _run_paper_control(
    control_record: dict[str, Any],
    *,
    client: LLMClient,
    corpus_pin: str,
    model_by_pass: dict[str, str],
    vault_dir: Path | None,
    n_reviewers: int,
) -> ControlReport:
    results: list[tuple[Plant, PanelReport]] = []
    for mutated, plant in plant_all(control_record):
        packet = build_paper_packet(mutated, corpus_pin=corpus_pin, vault_dir=vault_dir)
        report = review_paper_packet(
            packet,
            client=client,
            model_by_pass=model_by_pass,
            n_reviewers=n_reviewers,
            trusted=False,
            frame={"positive_control": plant.kind},
        )
        results.append((plant, report))
    return score_control(results)


def _stratum_figure(reports: list[PanelReport]) -> tuple[float, int, int]:
    """Pool every reviewer's `coherence` score across every paper in ONE
    stratum -- pooling within a stratum is exactly what a per-stratum
    figure means; pooling across strata is the pooled mean §7.13 forbids,
    and nothing here does that."""
    scores: list[float] = []
    ranks: list[int] = []
    for report in reports:
        for reviewer in report.reviewers:
            band = reviewer.bands.get("coherence")
            if band is None:
                continue
            scores.append(_SCORE_BY_BAND[band])
            ranks.append(_BAND_RANK[band])
    if not scores:
        return 0.0, 0, 0
    return sum(scores) / len(scores), max(ranks) - min(ranks), len(scores)


def run_coherence_eval(
    spec: SampleSpec,
    *,
    client: LLMClient,
    papers_dir: Path | None = None,
    vault_dir: Path | None = None,
    n_reviewers: int = MIN_REVIEWERS,
) -> CoherenceEvalReport:
    """The §10.2 measurement run. Every figure travels with its full frame
    (§7.13): `sample_id`, every paper id read, strata and their tiers,
    model combinations, panel configuration, and `corpus_pin`."""
    papers_dir = Path(papers_dir) if papers_dir is not None else PAPERS_DIR

    control_record = _load_paper_record(spec.control_paper_id, papers_dir)
    control = _run_paper_control(
        control_record,
        client=client,
        corpus_pin=spec.corpus_pin,
        model_by_pass=control_record.get("model_by_pass") or {},
        vault_dir=vault_dir,
        n_reviewers=n_reviewers,
    )

    strata: list[StratumCoherenceReport] = []
    for stratum in spec.strata:
        reports: list[PanelReport] = []
        for paper_brief_id in stratum.paper_brief_ids:
            record = _load_paper_record(paper_brief_id, papers_dir)
            packet = build_paper_packet(record, corpus_pin=spec.corpus_pin, vault_dir=vault_dir)
            reports.append(
                review_paper_packet(
                    packet,
                    client=client,
                    model_by_pass=record.get("model_by_pass") or {},
                    n_reviewers=n_reviewers,
                    trusted=control.passed,
                    frame={
                        "sample_id": spec.sample_id,
                        "stratum_id": stratum.stratum_id,
                        "tier": stratum.tier,
                        "model_combination": stratum.model_combination,
                    },
                )
            )
        rate, spread, n_scores = _stratum_figure(reports)
        strata.append(
            StratumCoherenceReport(
                stratum_id=stratum.stratum_id,
                tier=stratum.tier,
                model_combination=stratum.model_combination,
                paper_brief_ids=stratum.paper_brief_ids,
                n_reviewer_scores=n_scores,
                argument_coherence_rate=rate,
                reviewer_spread=spread,
            )
        )

    frame = {
        "sample_id": spec.sample_id,
        "paper_brief_ids": spec.paper_brief_ids(),
        "strata": [stratum.stratum_id for stratum in spec.strata],
        "tiers": sorted({stratum.tier for stratum in spec.strata}),
        "model_combinations": sorted({stratum.model_combination for stratum in spec.strata}),
        "panel": {"n_reviewers": n_reviewers},
        "corpus_pin": spec.corpus_pin,
    }
    return CoherenceEvalReport(
        sample_id=spec.sample_id,
        corpus_pin=spec.corpus_pin,
        control=control,
        strata=strata,
        frame=frame,
    )


def format_coherence_eval_report(report: CoherenceEvalReport) -> str:
    lines = [f"sample: {report.sample_id}", f"corpus_pin: {report.corpus_pin}"]
    for key, value in sorted(report.frame.items()):
        lines.append(f"frame.{key}: {value}")
    lines.append(f"positive control passed: {report.control.passed}")
    lines.append(f"trusted: {report.trusted}")
    if not report.trusted:
        lines.append(
            "no stratum figure below is reportable as trusted (§7.9) -- the "
            "control, not any paper, failed"
        )
    lines.append("")
    for stratum in report.strata:
        lines.append(
            f"  {stratum.stratum_id} (tier={stratum.tier}, "
            f"model_combination={stratum.model_combination}): "
            f"argument_coherence_rate={stratum.argument_coherence_rate:.3f} "
            f"(spread={stratum.reviewer_spread}, n={stratum.n_reviewer_scores}, "
            f"papers={list(stratum.paper_brief_ids)})"
        )
    lines.append("referee: model panel (specs/PHASE-C.md §7.7-§7.9) -- NOT human expert judgement")
    lines.append("no pooled system-wide mean is ever reported (§7.13)")
    return "\n".join(lines)
