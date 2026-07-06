"""Domain codebook loader (PRD §7.1, Appendix G, line 400).

Reads `<domain-dir>/codebook.yaml`, which mirrors the domain schema's axes
and tags, adding a `definition`, `positive_example`, and `negative_example`
per tag. Locked shape:

    axes:
      <axis_name>:
        <tag_id>:
          definition: "..."
          positive_example: "..."
          negative_example: "..."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class CodebookError(Exception):
    """Base class for all domain codebook loading errors."""


class MissingCodebookFileError(CodebookError):
    """Raised when `<domain-dir>/codebook.yaml` does not exist."""

    def __init__(self, codebook_path: Path):
        self.codebook_path = codebook_path
        super().__init__(f"missing codebook file: {codebook_path}")


class MalformedCodebookError(CodebookError):
    """Raised when `<domain-dir>/codebook.yaml` is not valid YAML."""

    def __init__(self, codebook_path: Path, reason: str):
        self.codebook_path = codebook_path
        self.reason = reason
        super().__init__(f"codebook at {codebook_path} is not valid YAML: {reason}")


class NonMappingAxisError(CodebookError):
    """Raised when a codebook axis's body is not a mapping of tag entries."""

    def __init__(self, axis_name: str, axis_raw: Any):
        self.axis_name = axis_name
        self.axis_raw = axis_raw
        super().__init__(
            f"codebook axis {axis_name!r} must be a mapping of tag id -> "
            f"entry, got {type(axis_raw).__name__}"
        )


class NonMappingTagEntryError(CodebookError):
    """Raised when a tag entry is not a mapping of definition/examples."""

    def __init__(self, axis_name: str, tag_id: str, entry_raw: Any):
        self.axis_name = axis_name
        self.tag_id = tag_id
        self.entry_raw = entry_raw
        super().__init__(
            f"codebook entry for tag {tag_id!r} on axis {axis_name!r} must be "
            f"a mapping (definition, positive_example, negative_example), "
            f"got {type(entry_raw).__name__}"
        )


@dataclass
class TagEntry:
    definition: str | None = None
    positive_example: str | None = None
    negative_example: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Codebook:
    axes: dict[str, dict[str, TagEntry]]


def load_codebook(domain_dir: str | Path) -> Codebook:
    """Load and validate the codebook at `<domain_dir>/codebook.yaml`."""
    domain_dir = Path(domain_dir)
    codebook_path = domain_dir / "codebook.yaml"

    if not codebook_path.is_file():
        raise MissingCodebookFileError(codebook_path)

    with codebook_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise MalformedCodebookError(codebook_path, str(exc)) from exc

    axes: dict[str, dict[str, TagEntry]] = {}
    for axis_name, axis_raw in (raw.get("axes") or {}).items():
        if not isinstance(axis_raw, dict):
            raise NonMappingAxisError(axis_name, axis_raw)

        tag_entries: dict[str, TagEntry] = {}
        for tag_id, entry_raw in axis_raw.items():
            if not isinstance(entry_raw, dict):
                raise NonMappingTagEntryError(axis_name, tag_id, entry_raw)

            tag_entries[tag_id] = TagEntry(
                definition=entry_raw.get("definition"),
                positive_example=entry_raw.get("positive_example"),
                negative_example=entry_raw.get("negative_example"),
                raw=entry_raw,
            )

        axes[axis_name] = tag_entries

    return Codebook(axes=axes)
