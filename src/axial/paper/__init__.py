"""Phase-C paper authorship (specs/PHASE-C.md).

Stages 1 through 3 and the deterministic parts of 4 and 5. Record assembly,
rendering and the CLI surface are still to come.

**Every stage past intake takes a LIST of analysis records, and a list of one
is not a special case.** That signature is the whole reason the prose layer --
arc plan, draft, citation index, bibliography -- is built here rather than
twice: if Phase B later renders its own answers as argued papers, it calls
this with one record. Phase B is deliberately not reopened to do that now
(§0), because it was closed and benchmarked a day earlier and the sealed
panel's packets are built from the rendered answer.

Phase C's own contribution is what it always was: an arc across several
analyses, and the cross-source (b) claims that span them.

Nothing here imports `axial.answer`, `axial.analyze` or `axial.brief`'s run
path, so §3 non-goal 1 (Phase C never runs Phase B) holds by import graph
rather than by promise.
"""

from __future__ import annotations

from axial.paper.brief import (
    AnalysisIdsError,
    EmptyPaperBriefFieldError,
    MalformedPaperBriefError,
    MissingPaperBriefFieldError,
    MissingPaperBriefFileError,
    NonMappingPaperBriefError,
    NonStringPaperBriefFieldError,
    PaperBrief,
    PaperBriefContent,
    PaperBriefError,
    UnknownPaperBriefFieldError,
    compute_paper_brief_id,
    load_paper_brief,
)
from axial.paper.biblio import (
    BIB_FIELDS,
    BibliographyError,
    build_bibliography,
    format_field,
    source_ids_for_claims,
)
from axial.paper.citations import (
    Citation,
    CitationError,
    UnresolvableGroundsError,
    UnresolvableMarkerError,
    assert_grounds_resolve,
    build_citation_index,
    cited_claim_ids,
    markers_in,
    reduce_to_cited,
)
from axial.paper.coverage import (
    CoverageDisagreementError,
    PaperCoverageError,
    build_coverage_map,
    clamped_band_for,
    overall_confidence,
)
from axial.paper.claims import (
    ConfidenceCeilingError,
    PaperClaimError,
    SingleRecordInferenceError,
    SpeculationError,
    UnknownInventoryClaimError,
    assert_ceilings,
    carried_claim,
    new_b_claim,
)
from axial.paper.draft import (
    DraftError,
    DraftParseError,
    NewClaimDraft,
    SectionDraft,
    UnknownDerivationError,
    assign_claim_ids,
    draft_section,
    remap_local_ids,
)
from axial.paper.intake import (
    InventoryClaim,
    MalformedAnalysisError,
    MixedCorpusPinError,
    PaperIntake,
    PaperIntakeError,
    RefusedAnalysisError,
    UnresolvableAnalysisError,
    run_intake,
)
from axial.paper.lens import (
    DEFAULT_LENSES_DIR,
    Lens,
    LensError,
    NoLensesAvailableError,
    UnknownLensError,
    available_lenses,
    resolve_lens,
)
from axial.paper.plan import (
    COUNTER_POSITION_ROLE,
    ROLES,
    EmptySectionError,
    MissingCounterPositionError,
    Plan,
    PlanError,
    PlanParseError,
    Section,
    UnassignedClaimError,
    UnknownRoleError,
    compose_plan_prompt,
    format_plan,
    parse_plan_response,
    run_plan,
    validate_plan,
)

__all__ = [
    "AnalysisIdsError",
    "BIB_FIELDS",
    "BibliographyError",
    "COUNTER_POSITION_ROLE",
    "Citation",
    "CitationError",
    "ConfidenceCeilingError",
    "CoverageDisagreementError",
    "DEFAULT_LENSES_DIR",
    "DraftError",
    "DraftParseError",
    "EmptyPaperBriefFieldError",
    "EmptySectionError",
    "InventoryClaim",
    "Lens",
    "LensError",
    "MalformedAnalysisError",
    "MalformedPaperBriefError",
    "MissingCounterPositionError",
    "MissingPaperBriefFieldError",
    "MissingPaperBriefFileError",
    "MixedCorpusPinError",
    "NewClaimDraft",
    "NoLensesAvailableError",
    "NonMappingPaperBriefError",
    "NonStringPaperBriefFieldError",
    "PaperBrief",
    "PaperBriefContent",
    "PaperBriefError",
    "PaperClaimError",
    "PaperCoverageError",
    "PaperIntake",
    "PaperIntakeError",
    "Plan",
    "PlanError",
    "PlanParseError",
    "ROLES",
    "RefusedAnalysisError",
    "Section",
    "SectionDraft",
    "SingleRecordInferenceError",
    "SpeculationError",
    "UnassignedClaimError",
    "UnknownDerivationError",
    "UnknownInventoryClaimError",
    "UnknownLensError",
    "UnknownPaperBriefFieldError",
    "UnknownRoleError",
    "UnresolvableAnalysisError",
    "UnresolvableGroundsError",
    "UnresolvableMarkerError",
    "assert_ceilings",
    "assert_grounds_resolve",
    "assign_claim_ids",
    "available_lenses",
    "build_bibliography",
    "build_citation_index",
    "build_coverage_map",
    "carried_claim",
    "cited_claim_ids",
    "clamped_band_for",
    "compose_plan_prompt",
    "compute_paper_brief_id",
    "draft_section",
    "format_field",
    "format_plan",
    "load_paper_brief",
    "markers_in",
    "new_b_claim",
    "overall_confidence",
    "parse_plan_response",
    "reduce_to_cited",
    "remap_local_ids",
    "resolve_lens",
    "run_intake",
    "run_plan",
    "source_ids_for_claims",
    "validate_plan",
]
