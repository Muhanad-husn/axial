"""Brief intake: load, validate, and deterministically id a brief.

Phase-B stage 1 input contract (specs/PHASE-B.md §7.1, [FIRM]): a brief is a
versioned file whose shape is `{brief_id, case, request, lens?}`. This module
reads that file from disk, validates it, and computes `brief_id` as a stable
hash over the brief's *content* -- no randomness, no timestamps, no filename
input, so the same content yields the same id on every run and every
machine. A malformed brief fails loudly with a clear, field-naming error and
emits no partially-constructed brief (issue #247, slice 01).

LLM-free and embedding-free by construction: every path here is pure
file I/O plus deterministic hashing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# The only top-level keys a brief file may declare (§7.1 minus `brief_id`,
# which is computed, never read from the file). An unrecognised key is
# rejected rather than silently dropped, so a typo'd field is caught at
# intake instead of vanishing.
KNOWN_KEYS = {"case", "request", "lens"}

# `brief_id` truncation length: long enough to be effectively collision-free
# for this corpus's scale, short enough to stay a readable filesystem stem
# (it names data/analyses/<brief_id>.json, §7.3).
_BRIEF_ID_LENGTH = 16


class BriefError(Exception):
    """Base class for all brief intake errors."""


class MissingBriefFileError(BriefError):
    """Raised when the brief file does not exist."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"missing brief file: {path}")


class MalformedBriefError(BriefError):
    """Raised when the brief file is not valid YAML."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"brief at {path} is not valid YAML: {reason}")


class NonMappingBriefError(BriefError):
    """Raised when the parsed YAML is not a mapping of fields."""

    def __init__(self, path: Path, raw: Any):
        self.path = path
        self.raw = raw
        super().__init__(
            f"brief at {path} must be a mapping with fields "
            f"{sorted(KNOWN_KEYS)!r}, got {type(raw).__name__}"
        )


class UnknownFieldError(BriefError):
    """Raised when the brief declares a top-level key outside KNOWN_KEYS."""

    def __init__(self, path: Path, unknown_keys: set[str]):
        self.path = path
        self.unknown_keys = unknown_keys
        super().__init__(
            f"brief at {path} has unknown field(s) {sorted(unknown_keys)!r}; "
            f"expected only {sorted(KNOWN_KEYS)!r}"
        )


class MissingFieldError(BriefError):
    """Raised when a required field is absent or null."""

    def __init__(self, path: Path, field_name: str):
        self.path = path
        self.field = field_name
        super().__init__(f"brief at {path} is missing required field {field_name!r}")


class EmptyFieldError(BriefError):
    """Raised when a required field is present but blank/whitespace-only."""

    def __init__(self, path: Path, field_name: str):
        self.path = path
        self.field = field_name
        super().__init__(f"brief at {path} has an empty required field {field_name!r}")


class NonStringFieldError(BriefError):
    """Raised when a field is present but not a string (case/request/lens)."""

    def __init__(self, path: Path, field_name: str, value: Any):
        self.path = path
        self.field = field_name
        self.value = value
        super().__init__(
            f"brief at {path} has a non-string field {field_name!r}: "
            f"{type(value).__name__} (expected a string)"
        )


@dataclass(frozen=True)
class BriefContent:
    """The validated, id-free content of a brief (§7.1 minus `brief_id`) --
    exactly the material `compute_brief_id` hashes over. Two briefs with
    equal content always compute the same id, whatever their file's name,
    path, or on-disk key order."""

    case: str
    request: str
    lens: str | None = None


@dataclass(frozen=True)
class Brief:
    """A fully loaded, validated brief (§7.1): `{brief_id, case, request, lens?}`."""

    brief_id: str
    case: str
    request: str
    lens: str | None = None


def compute_brief_id(content: BriefContent) -> str:
    """Compute a stable, deterministic id over `content`. No randomness, no
    timestamps, no filename input: hashes only `case`, `request`, and
    `lens`, via a sorted-key JSON canonicalisation so presentation details
    (source key order, trailing whitespace -- already stripped by the time a
    `BriefContent` exists) never affect the id."""
    canonical = json.dumps(
        {"case": content.case, "request": content.request, "lens": content.lens},
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:_BRIEF_ID_LENGTH]


def _require_nonempty_string(path: Path, raw: dict[str, Any], field_name: str) -> str:
    if field_name not in raw or raw[field_name] is None:
        raise MissingFieldError(path, field_name)
    value = raw[field_name]
    if not isinstance(value, str):
        raise NonStringFieldError(path, field_name, value)
    stripped = value.strip()
    if not stripped:
        raise EmptyFieldError(path, field_name)
    return stripped


def _validate_lens(path: Path, raw: dict[str, Any]) -> str | None:
    if "lens" not in raw or raw["lens"] is None:
        return None
    value = raw["lens"]
    if not isinstance(value, str):
        raise NonStringFieldError(path, "lens", value)
    stripped = value.strip()
    return stripped or None


def _validate_brief_dict(path: Path, raw: Any) -> BriefContent:
    if not isinstance(raw, dict):
        raise NonMappingBriefError(path, raw)

    unknown_keys = set(raw) - KNOWN_KEYS
    if unknown_keys:
        raise UnknownFieldError(path, unknown_keys)

    case = _require_nonempty_string(path, raw, "case")
    request = _require_nonempty_string(path, raw, "request")
    lens = _validate_lens(path, raw)

    return BriefContent(case=case, request=request, lens=lens)


def load_brief(path: str | Path) -> Brief:
    """Load and validate the brief at `path`, returning a `Brief` carrying
    its computed `brief_id`. Raises a `BriefError` subclass naming the
    offending field on any validation failure; no partially-constructed
    `Brief` is ever returned or raised alongside the error."""
    path = Path(path)

    if not path.is_file():
        raise MissingBriefFileError(path)

    with path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise MalformedBriefError(path, str(exc)) from exc

    if raw is None:
        raw = {}

    content = _validate_brief_dict(path, raw)
    brief_id = compute_brief_id(content)

    return Brief(brief_id=brief_id, case=content.case, request=content.request, lens=content.lens)
