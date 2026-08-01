"""Phase-C paper authorship (specs/PHASE-C.md).

**Paused mid-build, 2026-08-01, and deliberately not wired to anything.** The
four modules here are stages 1 and 5's deterministic halves -- paper-brief
intake, record resolution and the claim inventory, the unioned coverage map
and confidence ceiling, and the citation index. All four are model-free.

What is NOT here yet, and why: arc planning and drafting (stages 2-3), the
bibliography, and rendering. The founder's ruling of 2026-08-01 is that a
Phase-B answer must itself read as an argued paper rather than a bulleted
claim inventory, so the prose layer -- plan, draft, cite, render -- is common
infrastructure serving ONE analysis record as readily as several, and Phase B
owns the single-record case. Building it here first would have built it twice.
Phase C's own contribution narrows to what it always was: an arc across
several analyses, and the cross-source (b) claims that span them.

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

__all__ = [
    "AnalysisIdsError",
    "Citation",
    "CitationError",
    "CoverageDisagreementError",
    "EmptyPaperBriefFieldError",
    "InventoryClaim",
    "MalformedAnalysisError",
    "MalformedPaperBriefError",
    "MissingPaperBriefFieldError",
    "MissingPaperBriefFileError",
    "MixedCorpusPinError",
    "NonMappingPaperBriefError",
    "NonStringPaperBriefFieldError",
    "PaperBrief",
    "PaperBriefContent",
    "PaperBriefError",
    "PaperCoverageError",
    "PaperIntake",
    "PaperIntakeError",
    "RefusedAnalysisError",
    "UnknownPaperBriefFieldError",
    "UnresolvableAnalysisError",
    "UnresolvableGroundsError",
    "UnresolvableMarkerError",
    "assert_grounds_resolve",
    "build_citation_index",
    "build_coverage_map",
    "cited_claim_ids",
    "clamped_band_for",
    "compute_paper_brief_id",
    "load_paper_brief",
    "markers_in",
    "overall_confidence",
    "reduce_to_cited",
    "run_intake",
]
