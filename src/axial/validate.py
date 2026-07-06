"""Schema <-> codebook cross-validator (PRD §7.1, §8 P0-6, Appendix G).

Compares a loaded `Schema`'s per-axis tag ids against a loaded `Codebook`'s
per-axis tag entries and reports every discrepancy: a schema tag with no
codebook entry, a codebook tag the schema never declares (P0-6: "a tag not
in the schema is a hard error"), and a codebook entry missing a required
definition/example field. An empty finding list means the pair is
consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from axial.codebook import Codebook, TagEntry
from axial.schema import Schema

REQUIRED_TAG_ENTRY_FIELDS = ("definition", "positive_example", "negative_example")


@dataclass
class Finding:
    axis: str
    tag: str
    kind: str  # "missing_from_codebook" | "missing_from_schema" | "missing_field"
    message: str


def _missing_field_findings(axis_name: str, tag_id: str, entry: TagEntry) -> list[Finding]:
    findings = []
    for field_name in REQUIRED_TAG_ENTRY_FIELDS:
        if not getattr(entry, field_name):
            findings.append(
                Finding(
                    axis=axis_name,
                    tag=tag_id,
                    kind="missing_field",
                    message=(
                        f"codebook entry for tag {tag_id!r} on axis {axis_name!r} "
                        f"is missing required field {field_name!r}"
                    ),
                )
            )
    return findings


def cross_validate(schema: Schema, codebook: Codebook) -> list[Finding]:
    """Return every discrepancy between `schema` and `codebook`, per axis."""
    findings: list[Finding] = []

    axis_names = set(schema.axes) | set(codebook.axes)
    for axis_name in sorted(axis_names):
        schema_tags = schema.axes[axis_name].tag_ids if axis_name in schema.axes else set()
        codebook_entries = codebook.axes.get(axis_name, {})
        codebook_tags = set(codebook_entries)

        for tag_id in sorted(schema_tags - codebook_tags):
            findings.append(
                Finding(
                    axis=axis_name,
                    tag=tag_id,
                    kind="missing_from_codebook",
                    message=(f"schema tag {tag_id!r} on axis {axis_name!r} has no codebook entry"),
                )
            )

        for tag_id in sorted(codebook_tags - schema_tags):
            findings.append(
                Finding(
                    axis=axis_name,
                    tag=tag_id,
                    kind="missing_from_schema",
                    message=(
                        f"codebook tag {tag_id!r} on axis {axis_name!r} is not declared by the schema"
                    ),
                )
            )

        for tag_id in sorted(schema_tags & codebook_tags):
            findings.extend(_missing_field_findings(axis_name, tag_id, codebook_entries[tag_id]))

    return findings
