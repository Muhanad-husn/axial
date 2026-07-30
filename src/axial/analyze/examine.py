"""Stage-4 pre-pass entry point: `axial brief examine` (issue #255,
specs/PHASE-B.md §5 stage 4, §7.5, §8 P0-4/P0-9).

Runs stage 1 (interrogation) and stage 3 (retrieval), then assembles the
retrieved evidence into one inspectable `EvidenceSet` -- all BEFORE the
stage-4 synthesis call, which this module never makes (P0-9's
inspect-before-spend affordance, mirroring `axial chunk examine`,
PRODUCT.md §7.7 -- no synthesis pass exists anywhere in this module's
import graph to call; that call is slice 02, issue #256). `run_examine`
writes nothing to disk: it neither persists the interrogation result
(`axial.brief.interrogate.persist_interrogation`, a separate, explicit call
the `brief interrogate` subcommand makes) nor any analysis record (§7.3,
also out of this slice's scope).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axial.analyze.assembly import EvidenceSet, assemble_evidence
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, interrogate
from axial.llm import LLMClient
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.retrieve.loop import RetrievalResult, run_planned_retrieval


@dataclass(frozen=True)
class ExamineResult:
    """`examine`'s own full return shape: the §7.2 interrogation result, the
    §7.6 retrieval trajectory + evidence ids, and the assembled evidence
    set -- everything `axial brief examine` reports, and nothing more (no
    claim graph, no analysis record; those are slice 02, #256)."""

    interrogation: InterrogationResult
    retrieval: RetrievalResult
    evidence: EvidenceSet


def run_examine(
    brief: Brief,
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
) -> ExamineResult:
    """Run stages 1 and 3 over `brief` and assemble the evidence set stage 4
    would consume -- zero stage-4 synthesis calls by construction, and
    nothing written to disk (this function persists nothing; the CLI layer
    decides what, if anything, to report).

    On a `refuse` disposition (§7.2), `run_planned_retrieval` itself
    short-circuits before any retrieval call is made (its own documented
    contract) -- `examine` inherits that for free: the trajectory and
    evidence set both come back empty, and the interrogation result alone
    carries the refusal for the caller to report."""
    interrogation_result = interrogate(brief, client=client, vault_dir=vault_dir)
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
    evidence = assemble_evidence(retrieval_result.evidence_ids, vault_dir=vault_dir)
    return ExamineResult(
        interrogation=interrogation_result, retrieval=retrieval_result, evidence=evidence
    )


def format_examine_report(brief: Brief, result: ExamineResult) -> str:
    """Render `ExamineResult` into the human-readable report `axial brief
    examine` prints (mirroring `axial.chunk.format_examine_report`'s own
    separation of stats from rendering): the §7.2 interrogation result
    (disposition, premises_found, bounds_applied, refusal), the retrieved
    `chunk_id`s in retrieval order with each note's own one-sentence `claim`,
    and a plain count of assembled notes per name.

    That count is an INSPECTION count, not the §7.7 coverage map (issue
    #489): no band, no corpus denominator, no confidence. The banded map is
    computed from `names_touched` over the claim graph, which does not exist
    before the synthesis call this command exists to precede. An abstained
    field never appears here, because `assemble_evidence` already dropped
    it."""
    lines: list[str] = []

    lines.append(f"brief_id: {brief.brief_id}")
    lines.append(f"disposition: {result.interrogation.disposition}")
    for premise in result.interrogation.premises_found:
        lines.append(f"  premise ({premise.assessment}): {premise.premise}")
    for bound in result.interrogation.bounds_applied:
        lines.append(f"  bound: {bound}")
    if result.interrogation.refusal is not None:
        lines.append(f"refusal: {result.interrogation.refusal['reason']}")

    lines.append(f"retrieved chunk_ids (retrieval order): {len(result.evidence.chunk_ids)}")
    for chunk in result.evidence.chunks:
        claim = chunk.answers.get("claim")
        lines.append(f"  {chunk.chunk_id}" + (f" | claim: {claim}" if claim else ""))

    lines.append("names in the assembled evidence (notes per name):")
    for name, count in result.evidence.name_counts.items():
        lines.append(f"  {name}: {count}")

    return "\n".join(lines)
