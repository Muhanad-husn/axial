"""Brief intake + interrogation pre-pass (Phase-B stage 1, specs/PHASE-B.md §6).

Issue #247 landed intake: `load_brief` / `compute_brief_id` / `Brief`. Issue
#252 adds the interrogation pre-pass (§7.2, P0-1): `interrogate` /
`disposition_for` / `InterrogationResult` / `persist_interrogation`.
"""

from __future__ import annotations

from axial.brief.intake import (
    Brief,
    BriefContent,
    BriefError,
    EmptyFieldError,
    MalformedBriefError,
    MissingBriefFileError,
    MissingFieldError,
    NonMappingBriefError,
    NonStringFieldError,
    UnknownFieldError,
    compute_brief_id,
    load_brief,
)
from axial.brief.interrogate import (
    InterrogationError,
    InterrogationFailedError,
    InterrogationParseError,
    InterrogationResult,
    InvalidAssessmentError,
    PremiseAssessment,
    disposition_for,
    interrogate,
    parse_interrogation_response,
    persist_interrogation,
)

__all__ = [
    "Brief",
    "BriefContent",
    "BriefError",
    "EmptyFieldError",
    "InterrogationError",
    "InterrogationFailedError",
    "InterrogationParseError",
    "InterrogationResult",
    "InvalidAssessmentError",
    "MalformedBriefError",
    "MissingBriefFileError",
    "MissingFieldError",
    "NonMappingBriefError",
    "NonStringFieldError",
    "PremiseAssessment",
    "UnknownFieldError",
    "compute_brief_id",
    "disposition_for",
    "interrogate",
    "load_brief",
    "parse_interrogation_response",
    "persist_interrogation",
]
