"""Brief intake + interrogation pre-pass (Phase-B stage 1, specs/PHASE-B.md §6).

This slice (#247) lands intake only: `load_brief` / `compute_brief_id` /
`Brief`. The interrogation pre-pass (§7.2, P0-1) is a later sprint.
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

__all__ = [
    "Brief",
    "BriefContent",
    "BriefError",
    "EmptyFieldError",
    "MalformedBriefError",
    "MissingBriefFileError",
    "MissingFieldError",
    "NonMappingBriefError",
    "NonStringFieldError",
    "UnknownFieldError",
    "compute_brief_id",
    "load_brief",
]
