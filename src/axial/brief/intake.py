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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from axial.yaml_loader import SAFE_LOADER

# The only top-level keys a brief file may declare (§7.1 minus `brief_id`,
# which is computed, never read from the file). An unrecognised key is
# rejected rather than silently dropped, so a typo'd field is caught at
# intake instead of vanishing.
KNOWN_KEYS = {"case", "request", "lens", "weights"}

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
    """Raised when a field is present but blank/whitespace-only. Covers
    both required fields (`case`, `request`) and optional-but-non-blank
    fields (`lens`, §7.1) -- the wording must stay accurate for both, so it
    never claims a field is "required" when only its *value*, not its
    presence, is."""

    def __init__(self, path: Path, field_name: str):
        self.path = path
        self.field = field_name
        super().__init__(f"brief at {path}: field {field_name!r} is present but empty")


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


class NonMappingWeightsError(BriefError):
    """Raised when `weights` (issue #639, §7.1) is present but is not a
    mapping of `source_id` to a number."""

    def __init__(self, path: Path, value: Any):
        self.path = path
        self.value = value
        super().__init__(
            f"brief at {path} has a non-mapping `weights` field: "
            f"{type(value).__name__} (expected a mapping of source_id to a number)"
        )


class InvalidWeightKeyError(BriefError):
    """Raised when a `weights` entry's key is not a non-empty string
    `source_id`."""

    def __init__(self, path: Path, key: Any):
        self.path = path
        self.key = key
        super().__init__(f"brief at {path} has an invalid `weights` key: {key!r}")


class InvalidWeightValueError(BriefError):
    """Raised when a `weights` entry's value is not a non-negative number.
    A weight is a rotation-slot instruction (`_round_robin_by_source`,
    issue #639), never a filter -- a negative value has no meaning under
    that contract, so it is rejected here rather than silently clamped."""

    def __init__(self, path: Path, source_id: str, value: Any):
        self.path = path
        self.source_id = source_id
        self.value = value
        super().__init__(
            f"brief at {path} has an invalid weight for {source_id!r}: {value!r} "
            "(expected a number >= 0)"
        )


@dataclass(frozen=True)
class BriefContent:
    """The validated, id-free content of a brief (§7.1 minus `brief_id`) --
    exactly the material `compute_brief_id` hashes over. Two briefs with
    equal content always compute the same id, whatever their file's name,
    path, or on-disk key order.

    `weights` (issue #639, §7.1) maps `source_id` to a non-negative float:
    the analyst's own instruction for how many rotation slots that source
    gets in `axial.retrieve.loop._round_robin_by_source`'s walk, never a
    filter (see that function's own docstring). Defaults to an empty dict,
    never `None`, so every reader can treat it uniformly -- an omitted
    `weights` key and an explicit empty mapping mean the same thing: every
    source stays at the implicit default of 1.0."""

    case: str
    request: str
    lens: str | None = None
    weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Brief:
    """A fully loaded, validated brief (§7.1): `{brief_id, case, request, lens?, weights?}`."""

    brief_id: str
    case: str
    request: str
    lens: str | None = None
    weights: dict[str, float] = field(default_factory=dict)


def compute_brief_id(content: BriefContent) -> str:
    """Compute a stable, deterministic id over `content`. No randomness, no
    timestamps, no filename input: hashes `case`, `request`, and `lens`
    always, via a sorted-key JSON canonicalisation so presentation details
    (source key order, trailing whitespace -- already stripped by the time a
    `BriefContent` exists) never affect the id.

    **`weights` (issue #639) is hashed only when non-empty.** Every brief
    ever persisted before this field existed has no `weights` key at all,
    and hashing an always-present (even if empty) `weights` key would
    change EVERY existing `brief_id` and silently orphan every analysis
    record already on disk (`data/analyses/<brief_id>.json`). An unweighted
    brief -- the overwhelming default -- therefore keeps the exact id it
    had before this field existed; only a brief that actually supplies a
    weight gets a new one."""
    payload: dict[str, Any] = {
        "case": content.case,
        "request": content.request,
        "lens": content.lens,
    }
    if content.weights:
        payload["weights"] = content.weights
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
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
    """Validate an optional `lens` (§7.1): the key is optional, but its
    value is not. Omitting the key -- or setting it explicitly to `null` --
    is the only way to ask the stage to choose, and yields `None`. A
    *present* `lens` must be a non-empty string after whitespace stripping;
    a blank or whitespace-only value is rejected exactly like a blank
    `case` or `request` (issue #275), not silently coerced to "the stage
    chooses"."""
    if "lens" not in raw or raw["lens"] is None:
        return None
    value = raw["lens"]
    if not isinstance(value, str):
        raise NonStringFieldError(path, "lens", value)
    stripped = value.strip()
    if not stripped:
        raise EmptyFieldError(path, "lens")
    return stripped


def _validate_weights(path: Path, raw: dict[str, Any]) -> dict[str, float]:
    """Validate an optional `weights` field (§7.1, issue #639). The key is
    optional, and so is having anything in it: omitting it, or an explicit
    empty mapping, both mean "every source stays at 1.0" -- the same
    id-stability rule `compute_brief_id` follows. A present entry's key
    must be a non-empty string `source_id`; its value must be a number
    (never `bool`, which is a `int` subclass in Python and not a weight
    anyone means to write) that is `>= 0` -- a weight is a rotation-slot
    count, never a filter, and a negative slot count has no meaning."""
    if "weights" not in raw or raw["weights"] is None:
        return {}
    value = raw["weights"]
    if not isinstance(value, dict):
        raise NonMappingWeightsError(path, value)
    weights: dict[str, float] = {}
    for source_id, weight in value.items():
        if not isinstance(source_id, str) or not source_id.strip():
            raise InvalidWeightKeyError(path, source_id)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise InvalidWeightValueError(path, source_id, weight)
        weight_f = float(weight)
        if weight_f < 0:
            raise InvalidWeightValueError(path, source_id, weight)
        weights[source_id.strip()] = weight_f
    return weights


def _validate_brief_dict(path: Path, raw: Any) -> BriefContent:
    if not isinstance(raw, dict):
        raise NonMappingBriefError(path, raw)

    unknown_keys = set(raw) - KNOWN_KEYS
    if unknown_keys:
        raise UnknownFieldError(path, unknown_keys)

    case = _require_nonempty_string(path, raw, "case")
    request = _require_nonempty_string(path, raw, "request")
    lens = _validate_lens(path, raw)
    weights = _validate_weights(path, raw)

    return BriefContent(case=case, request=request, lens=lens, weights=weights)


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
            raw = yaml.load(f, Loader=SAFE_LOADER)
        except yaml.YAMLError as exc:
            raise MalformedBriefError(path, str(exc)) from exc

    if raw is None:
        raw = {}

    content = _validate_brief_dict(path, raw)
    brief_id = compute_brief_id(content)

    return Brief(
        brief_id=brief_id,
        case=content.case,
        request=content.request,
        lens=content.lens,
        weights=content.weights,
    )
