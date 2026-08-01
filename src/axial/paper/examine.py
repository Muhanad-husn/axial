"""Stages 1 and 2 only: `axial paper examine` (specs/PHASE-C.md §5, §8 P0-12).

Mirrors `axial.analyze.examine.run_examine`'s inspect-before-spend shape one
layer up: it composes intake, the opposition gap-and-repair pass (stage 1.5,
zero model calls), and arc planning -- exactly the prefix of `run_paper`
(`axial.paper.record`) that runs before a drafting dollar is spent -- and
never imports or calls anything in `axial.paper.draft`.

**`examine`'s zero-drafting-calls property holds by construction, not by a
flag.** This module's own call graph contains no reference to
`draft_section` or `PAPER_DRAFT_PASS_NAME`: there is no code path here that
could reach the drafting call, wrongly configured or otherwise. The
acceptance test pins this by counting calls per `pass_name` on a stub
client, not by reading a comment.

Deliberately composed from the same stage functions `run_paper` calls
(`run_intake`, `run_opposition_repair`, `extend_intake`, `resolve_lens`,
`run_plan`), so the plan and the claim inventory `examine` reports are
exactly what a `draft` run over the same brief would build before it starts
paying for prose -- not a second, divergent path recomputing the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.paper.brief import PaperBrief
from axial.paper.intake import PaperIntake, run_intake
from axial.paper.lens import Lens, resolve_lens
from axial.paper.opposition import OppositionRepair, extend_intake, run_opposition_repair
from axial.paper.plan import Plan, format_plan, run_plan
from axial.paths import ANALYSES_DIR


@dataclass(frozen=True)
class PaperExamineResult:
    """`examine`'s whole return shape: the extended claim inventory (§7.1,
    including any opposition-repair claims, §7.15), the repair pass's own
    gap/trajectory (§7.3's amendment), the resolved lens, and the arc plan
    (§7.2) -- and nothing past it. No drafted prose, no claims, no citation
    index, no record: those do not exist before stage 3."""

    intake: PaperIntake
    repair: OppositionRepair
    lens: Lens
    plan: Plan


def run_paper_examine(
    client: Any,
    paper_brief: PaperBrief,
    *,
    analyses_dir: Path | None = None,
    lenses_dir: Path | None = None,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> PaperExamineResult:
    """Stages 1, 1.5 and 2 -- intake, the opposition gap-and-repair pass, and
    arc planning -- with no path to stage 3. Raises `PaperIntakeError` on any
    of §7.1's three rejections, `LensError` on an unresolvable lens, and
    `PlanError` on a malformed or invalid plan -- exactly the exceptions
    `run_paper` itself can raise up to this same point."""
    intake = run_intake(paper_brief.analysis_ids, analyses_dir=analyses_dir or ANALYSES_DIR)
    repair = run_opposition_repair(intake, vault_dir=vault_dir, names_dir=names_dir)
    intake = extend_intake(intake, repair)

    lens = resolve_lens(paper_brief.lens, lenses_dir=lenses_dir)
    plan = run_plan(client, paper_brief.thesis, lens, intake)

    return PaperExamineResult(intake=intake, repair=repair, lens=lens, plan=plan)


def format_paper_examine_report(paper_brief: PaperBrief, result: PaperExamineResult) -> str:
    """The inspect-before-spend view `axial paper examine` prints: the
    resolved lens, the opposition gap-and-repair pass's headline counts, the
    full claim inventory (every claim available, assigned or not -- §7.2
    notes that a claim assigned nowhere is invisible in the plan alone), and
    the arc plan with each section's assigned claims (`format_plan`, already
    the P0-12 view of §7.2)."""
    lines: list[str] = [
        f"paper_brief_id: {paper_brief.paper_brief_id}",
        f"corpus_pin: {result.intake.corpus_pin}",
        f"lens: {result.lens.for_prompt()}",
        f"source_analyses: {', '.join(result.intake.source_analyses)}",
        (
            f"opposition gap-and-repair: checked {len(result.repair.names_checked)} name(s), "
            f"found {result.repair.gap_found}, repaired {result.repair.gap_repaired}"
        ),
        "",
        f"claim inventory ({len(result.intake.inventory)} claims):",
    ]
    for entry in result.intake.inventory:
        claim = entry.claim
        lines.append(
            f"  ({entry.brief_id} / {entry.claim_id}) [kind {claim.get('kind')}] "
            f"[confidence {claim.get('confidence')}] {claim.get('text')}"
        )

    lines.append("")
    lines.append(format_plan(result.plan))
    return "\n".join(lines)
