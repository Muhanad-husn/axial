"""Paper-brief intake: load, validate, and deterministically id a paper brief.

Phase-C stage 1 input contract (specs/PHASE-C.md §7.1, [FIRM]): a paper brief
is a versioned file whose shape is `{paper_brief_id, thesis, analysis_ids[],
title?}`. This module reads that file from disk, validates its shape, and
computes `paper_brief_id` as a stable hash over the brief's *content* -- no
randomness, no timestamps, no filename input, so re-running the same paper
brief is traceable.

Deliberately the same shape of module as `axial.brief.intake`, which does this
job one layer down. What it does NOT do is resolve the named analysis records:
that is `axial.paper.intake`, because resolution reads the corpus and this
does not. A paper brief naming a record that does not exist is well-formed and
unresolvable, which are different failures reported at different stages.

LLM-free and embedding-free by construction: every path here is pure file I/O
plus deterministic hashing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.yaml_loader import SAFE_LOADER

# The only top-level keys a paper brief may declare (§7.1 minus
# `paper_brief_id`, which is computed, never read from the file). An
# unrecognised key is rejected rather than silently dropped.
KNOWN_KEYS = {"thesis", "analysis_ids", "title"}

# Truncation length, matching `axial.brief.intake._BRIEF_ID_LENGTH`: long
# enough to be effectively collision-free at this corpus's scale, short enough
# to stay a readable filesystem stem (it names data/papers/<id>.json, §7.3).
_PAPER_BRIEF_ID_LENGTH = 16


class PaperBriefError(Exception):
    """Base class for all paper-brief intake errors."""


class MissingPaperBriefFileError(PaperBriefError):
    """Raised when the paper-brief file does not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"missing paper brief file: {path}")


class MalformedPaperBriefError(PaperBriefError):
    """Raised when the paper-brief file is not valid YAML."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"paper brief at {path} is not valid YAML: {reason}")


class NonMappingPaperBriefError(PaperBriefError):
    """Raised when the parsed YAML is not a mapping of fields."""

    def __init__(self, path: Path, raw: Any):
        self.path = path
        self.raw = raw
        super().__init__(
            f"paper brief at {path} must be a mapping with fields "
            f"{sorted(KNOWN_KEYS)!r}, got {type(raw).__name__}"
        )


class UnknownPaperBriefFieldError(PaperBriefError):
    """Raised when the paper brief declares a key outside KNOWN_KEYS."""

    def __init__(self, path: Path, unknown_keys: set[str]):
        self.path = path
        self.unknown_keys = unknown_keys
        super().__init__(
            f"paper brief at {path} has unknown field(s) {sorted(unknown_keys)!r}; "
            f"expected only {sorted(KNOWN_KEYS)!r}"
        )


class MissingPaperBriefFieldError(PaperBriefError):
    """Raised when a required field is absent or null."""

    def __init__(self, path: Path, field_name: str):
        self.path = path
        self.field = field_name
        super().__init__(f"paper brief at {path} is missing required field {field_name!r}")


class EmptyPaperBriefFieldError(PaperBriefError):
    """Raised when a field is present but blank/whitespace-only."""

    def __init__(self, path: Path, field_name: str):
        self.path = path
        self.field = field_name
        super().__init__(f"paper brief at {path}: field {field_name!r} is present but empty")


class NonStringPaperBriefFieldError(PaperBriefError):
    """Raised when a field is present but not a string."""

    def __init__(self, path: Path, field_name: str, value: Any):
        self.path = path
        self.field = field_name
        self.value = value
        super().__init__(
            f"paper brief at {path} has a non-string field {field_name!r}: "
            f"{type(value).__name__} (expected a string)"
        )


class AnalysisIdsError(PaperBriefError):
    """Raised when `analysis_ids` is not a non-empty list of distinct,
    non-empty strings. §7.1 requires it present and non-empty; a duplicate id
    is rejected here rather than silently deduplicated, because a paper brief
    naming the same record twice is a mistake the operator should see."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"paper brief at {path} has an invalid 'analysis_ids': {reason}")


@dataclass(frozen=True)
class PaperBriefContent:
    """The validated, id-free content of a paper brief (§7.1 minus
    `paper_brief_id`) -- exactly the material `compute_paper_brief_id` hashes
    over. Two paper briefs with equal content always compute the same id,
    whatever their file's name, path, or on-disk key order."""

    thesis: str
    analysis_ids: tuple[str, ...]
    title: str | None = None


@dataclass(frozen=True)
class PaperBrief:
    """A fully loaded, validated paper brief (§7.1)."""

    paper_brief_id: str
    thesis: str
    analysis_ids: tuple[str, ...]
    title: str | None = None


def compute_paper_brief_id(content: PaperBriefContent) -> str:
    """Compute a stable, deterministic id over `content`. No randomness, no
    timestamps, no filename input.

    `analysis_ids` is hashed in the ORDER THE BRIEF DECLARED, not sorted: §7.3
    persists `source_analyses` "in brief order", so the order is content the
    operator chose and re-ordering it is a different paper brief."""
    canonical = json.dumps(
        {
            "thesis": content.thesis,
            "analysis_ids": list(content.analysis_ids),
            "title": content.title,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:_PAPER_BRIEF_ID_LENGTH]


def _require_nonempty_string(path: Path, raw: dict[str, Any], field_name: str) -> str:
    if field_name not in raw or raw[field_name] is None:
        raise MissingPaperBriefFieldError(path, field_name)
    value = raw[field_name]
    if not isinstance(value, str):
        raise NonStringPaperBriefFieldError(path, field_name, value)
    stripped = value.strip()
    if not stripped:
        raise EmptyPaperBriefFieldError(path, field_name)
    return stripped


def _validate_title(path: Path, raw: dict[str, Any]) -> str | None:
    """An optional `title` (§7.1): the key is optional, its value is not.
    Omitting it -- or setting it to `null` -- means the renderer uses the
    thesis. A present-but-blank title is rejected rather than coerced to that,
    exactly as `axial.brief.intake` treats a blank `lens`."""
    if "title" not in raw or raw["title"] is None:
        return None
    value = raw["title"]
    if not isinstance(value, str):
        raise NonStringPaperBriefFieldError(path, "title", value)
    stripped = value.strip()
    if not stripped:
        raise EmptyPaperBriefFieldError(path, "title")
    return stripped


def _validate_analysis_ids(path: Path, raw: dict[str, Any]) -> tuple[str, ...]:
    if "analysis_ids" not in raw or raw["analysis_ids"] is None:
        raise MissingPaperBriefFieldError(path, "analysis_ids")
    value = raw["analysis_ids"]
    if not isinstance(value, list):
        raise AnalysisIdsError(path, f"expected a list, got {type(value).__name__}")
    if not value:
        raise AnalysisIdsError(path, "the list is empty; §7.1 requires at least one record")

    ids: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str):
            raise AnalysisIdsError(
                path, f"entry {index} is a {type(entry).__name__}, expected a string"
            )
        stripped = entry.strip()
        if not stripped:
            raise AnalysisIdsError(path, f"entry {index} is empty")
        ids.append(stripped)

    duplicates = sorted({entry for entry in ids if ids.count(entry) > 1})
    if duplicates:
        raise AnalysisIdsError(path, f"duplicate id(s) {duplicates!r}")

    return tuple(ids)


def _validate_paper_brief_dict(path: Path, raw: Any) -> PaperBriefContent:
    if not isinstance(raw, dict):
        raise NonMappingPaperBriefError(path, raw)

    unknown_keys = set(raw) - KNOWN_KEYS
    if unknown_keys:
        raise UnknownPaperBriefFieldError(path, unknown_keys)

    thesis = _require_nonempty_string(path, raw, "thesis")
    analysis_ids = _validate_analysis_ids(path, raw)
    title = _validate_title(path, raw)

    return PaperBriefContent(thesis=thesis, analysis_ids=analysis_ids, title=title)


def load_paper_brief(path: str | Path) -> PaperBrief:
    """Load and validate the paper brief at `path`, returning a `PaperBrief`
    carrying its computed `paper_brief_id`. Raises a `PaperBriefError`
    subclass naming the offending field on any validation failure; no
    partially-constructed `PaperBrief` is ever returned alongside the error."""
    path = Path(path)

    if not path.is_file():
        raise MissingPaperBriefFileError(path)

    with path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.load(f, Loader=SAFE_LOADER)
        except yaml.YAMLError as exc:
            raise MalformedPaperBriefError(path, str(exc)) from exc

    if raw is None:
        raw = {}

    content = _validate_paper_brief_dict(path, raw)
    return PaperBrief(
        paper_brief_id=compute_paper_brief_id(content),
        thesis=content.thesis,
        analysis_ids=content.analysis_ids,
        title=content.title,
    )
