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
#
# `target_words` (issue #787 slice 02): an optional total the arc planner
# allocates a per-section share of. Length is an input the analyst sets, not
# a constant derived anywhere in this module.
KNOWN_KEYS = {"thesis", "analysis_ids", "lens", "title", "target_words"}

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


class InvalidTargetWordsError(PaperBriefError):
    """Raised when `target_words` is present but not a positive integer.

    Same typed-error shape as the other single-field rejections in this
    module: names the path and the offending value, never coerces."""

    def __init__(self, path: Path, value: Any):
        self.path = path
        self.field = "target_words"
        self.value = value
        super().__init__(
            f"paper brief at {path} has an invalid 'target_words': {value!r} "
            "(expected a positive integer)"
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
    lens: str | None = None
    title: str | None = None
    target_words: int | None = None


@dataclass(frozen=True)
class PaperBrief:
    """A fully loaded, validated paper brief (§7.1)."""

    paper_brief_id: str
    thesis: str
    analysis_ids: tuple[str, ...]
    lens: str | None = None
    title: str | None = None
    target_words: int | None = None


def compute_paper_brief_id(content: PaperBriefContent) -> str:
    """Compute a stable, deterministic id over `content`. No randomness, no
    timestamps, no filename input.

    `analysis_ids` is hashed in the ORDER THE BRIEF DECLARED, not sorted: §7.3
    persists `source_analyses` "in brief order", so the order is content the
    operator chose and re-ordering it is a different paper brief.

    `target_words` is hashed only when the brief actually declares one
    (issue #787 slice 02). A different target length is genuinely a
    different paper, so including it is correct -- but the four-key dict
    below is exactly what every id on disk before this slice was computed
    over, and adding a fifth key unconditionally, even as `null`, would
    change every one of them. Omitting the key when there is no target
    keeps a brief that never mentions length hashing to its original id."""
    canonical: dict[str, Any] = {
        "thesis": content.thesis,
        "analysis_ids": list(content.analysis_ids),
        "lens": content.lens,
        "title": content.title,
    }
    if content.target_words is not None:
        canonical["target_words"] = content.target_words
    canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
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


def _optional_nonblank(path: Path, raw: dict[str, Any], field_name: str) -> str | None:
    """An optional field whose KEY is optional but whose VALUE is not (§7.1).

    Covers `lens` and `title`, which share the contract `axial.brief.intake`
    already applies to a Phase-B `lens`: omitting the key -- or setting it to
    `null` -- is the only way to ask the stage to choose (a lens) or fall back
    (a title, to the thesis). A present-but-blank value is rejected rather
    than silently coerced into that meaning, because "" and "you pick" are
    different instructions and a typo should not become the second."""
    if field_name not in raw or raw[field_name] is None:
        return None
    value = raw[field_name]
    if not isinstance(value, str):
        raise NonStringPaperBriefFieldError(path, field_name, value)
    stripped = value.strip()
    if not stripped:
        raise EmptyPaperBriefFieldError(path, field_name)
    return stripped


def _validate_target_words(path: Path, raw: dict[str, Any]) -> int | None:
    """`target_words` is optional (§7.1 slice 02): absent or `null` means the
    paper carries no length target, exactly as it did before this field
    existed. A present value must be a positive integer -- `bool` is
    rejected explicitly because Python's `bool` is an `int` subclass, and
    `True`/`False` are not word counts."""
    if "target_words" not in raw or raw["target_words"] is None:
        return None
    value = raw["target_words"]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidTargetWordsError(path, value)
    return value


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
    lens = _optional_nonblank(path, raw, "lens")
    title = _optional_nonblank(path, raw, "title")
    target_words = _validate_target_words(path, raw)

    return PaperBriefContent(
        thesis=thesis,
        analysis_ids=analysis_ids,
        lens=lens,
        title=title,
        target_words=target_words,
    )


def build_paper_brief(content: PaperBriefContent) -> PaperBrief:
    """A `PaperBrief` over already-validated `content`, carrying the id
    `compute_paper_brief_id` derives from it. The seam for a caller that
    holds a paper brief in memory rather than on disk -- `axial ask` builds
    one from the question it just answered (issue #668) -- so that caller
    and `load_paper_brief` compute the id exactly one way. It validates
    nothing: `PaperBriefContent` is the validated shape, and the file path
    every §7.1 rejection names does not exist here."""
    return PaperBrief(
        paper_brief_id=compute_paper_brief_id(content),
        thesis=content.thesis,
        analysis_ids=content.analysis_ids,
        lens=content.lens,
        title=content.title,
        target_words=content.target_words,
    )


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

    return build_paper_brief(_validate_paper_brief_dict(path, raw))
