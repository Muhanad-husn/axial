"""Stage-5 analysis validators: deterministic post-passes that run after
synthesis and before any answer is released (specs/PHASE-B.md §7.9, §5 stage
5). Slice 01 (issue #258) lands the attribution validator; counter-position
and coverage/confidence (issues #259, #260) are siblings that extend this
package later -- see plans/analysis-validators/README.md.

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

__all__ = [
    "AttributionFailure",
    "AttributionReport",
    "AttributionValidatorError",
    "SamePassModelError",
    "format_attribution_report",
    "validate_attribution",
]
