"""Stage-5 analysis validators: deterministic post-passes that run after
synthesis and before any answer is released (specs/PHASE-B.md §7.9, §5 stage
5). Slice 01 (issue #258) lands the attribution validator, slice 02 (issue
#259) the counter-position validator; coverage/confidence (issue #260) is a
sibling that extends this package later -- see
plans/analysis-validators/README.md.

Named `axial.validators` (plural), not `axial.validate` (singular): the
latter already exists as `src/axial/validate.py`, Phase A's schema<->codebook
cross-validator (PRD §7.1, `axial schema validate`) -- an unrelated,
already-shipped module. A package directory cannot share a name with an
existing top-level module in the same namespace, and renaming that
unrelated Phase-A module just to free up the plan's suggested singular name
would be a needless, out-of-scope blast-radius increase for this slice. See
this slice's PR body for the same note.
"""

from __future__ import annotations

from axial.validators.attribution import (
    AttributionFailure,
    AttributionReport,
    AttributionValidatorError,
    SamePassModelError,
    format_attribution_report,
    validate_attribution,
)
from axial.validators.coverage import (
    REASON_CONFIDENCE_EXCEEDS_COVERAGE,
    REASON_MISSING_COVERAGE_ENTRY,
    REASON_MISSING_CONFIDENCE_DISCLOSURE,
    CoverageConfidenceFailure,
    CoverageConfidenceReport,
    compute_coverage_map,
    coverage_band_for,
    format_coverage_confidence_report,
    format_coverage_map,
    validate_coverage_and_confidence,
)
from axial.validators.counter_position import (
    CounterPositionFailure,
    CounterPositionReport,
    CounterPositionValidatorError,
)
from axial.validators.counter_position import (
    SamePassModelError as CounterPositionSamePassModelError,
)
from axial.validators.counter_position import (
    format_counter_position_report,
    validate_counter_position,
)

__all__ = [
    "AttributionFailure",
    "AttributionReport",
    "AttributionValidatorError",
    "SamePassModelError",
    "format_attribution_report",
    "validate_attribution",
    "REASON_CONFIDENCE_EXCEEDS_COVERAGE",
    "REASON_MISSING_COVERAGE_ENTRY",
    "REASON_MISSING_CONFIDENCE_DISCLOSURE",
    "CoverageConfidenceFailure",
    "CoverageConfidenceReport",
    "compute_coverage_map",
    "coverage_band_for",
    "format_coverage_confidence_report",
    "format_coverage_map",
    "validate_coverage_and_confidence",
    "CounterPositionFailure",
    "CounterPositionReport",
    "CounterPositionValidatorError",
    "CounterPositionSamePassModelError",
    "format_counter_position_report",
    "validate_counter_position",
]
