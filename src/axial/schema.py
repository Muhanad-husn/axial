"""Domain schema loader (PRD §7.1, Appendix G).

Reads `<domain-dir>/schema.yaml` and exposes the axis list, each axis's
cardinality, its controlled values (and value count), and the schema
`version`. Per PRD §4 the loader takes a domain *directory* -- no code path
here branches on country; swapping domains means pointing at a different
directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Cardinality vocabulary the loader recognises (PRD §7.1 / Appendices A-F).
KNOWN_CARDINALITIES = {
    "single",
    "primary_plus_secondary",
    "primary_plus_optional_secondary",
}


class SchemaError(Exception):
    """Base class for all domain schema loading errors."""


class MissingSchemaFileError(SchemaError):
    """Raised when `<domain-dir>/schema.yaml` does not exist."""

    def __init__(self, schema_path: Path):
        self.schema_path = schema_path
        super().__init__(f"missing schema file: {schema_path}")


class MalformedSchemaError(SchemaError):
    """Raised when `<domain-dir>/schema.yaml` is not valid YAML."""

    def __init__(self, schema_path: Path, reason: str):
        self.schema_path = schema_path
        self.reason = reason
        super().__init__(f"schema at {schema_path} is not valid YAML: {reason}")


class MissingVersionError(SchemaError):
    """Raised when the schema has no top-level `version` field."""

    def __init__(self, schema_path: Path):
        self.schema_path = schema_path
        super().__init__(f"schema at {schema_path} is missing a required 'version' field")


class NonMappingAxisError(SchemaError):
    """Raised when an axis's body is not a mapping (e.g. a bare scalar)."""

    def __init__(self, axis_name: str, axis_raw: Any):
        self.axis_name = axis_name
        self.axis_raw = axis_raw
        super().__init__(
            f"axis {axis_name!r} must be a mapping of its fields "
            f"(applies_to, cardinality, values/groups), got {type(axis_raw).__name__}"
        )


class MissingValuesOrGroupsError(SchemaError):
    """Raised when an axis declares neither `values` nor `groups`."""

    def __init__(self, axis_name: str):
        self.axis_name = axis_name
        super().__init__(
            f"axis {axis_name!r} declares neither 'values' nor 'groups'; "
            "a controlled vocabulary is required"
        )


class UnknownCardinalityError(SchemaError):
    """Raised when an axis declares a cardinality not in KNOWN_CARDINALITIES."""

    def __init__(self, axis_name: str, cardinality: Any):
        self.axis_name = axis_name
        self.cardinality = cardinality
        super().__init__(
            f"axis {axis_name!r} declares unknown cardinality {cardinality!r}; "
            f"expected one of {sorted(KNOWN_CARDINALITIES)}"
        )


class MissingTagIdError(SchemaError):
    """Raised when a `values` entry is a mapping but omits the `id` key."""

    def __init__(self, axis_name: str, entry: Any):
        self.axis_name = axis_name
        self.entry = entry
        super().__init__(
            f"axis {axis_name!r} has a values entry missing required 'id' key: {entry!r}"
        )


def _flatten_value_count(axis_name: str, raw_values: Any, raw_groups: Any) -> int:
    """Count an axis's controlled-vocabulary entries regardless of shape.

    Handles: a flat list of scalars (e.g. field), a list of {id, ...} tag
    objects (e.g. claim_type), or a mapping of group-name -> list of values
    (e.g. theory_school's grouped vocabulary).
    """
    if raw_groups is not None:
        return sum(len(group_values) for group_values in raw_groups.values())
    if raw_values is not None:
        return len(raw_values)
    raise MissingValuesOrGroupsError(axis_name)


def _flatten_tag_ids(axis_name: str, raw_values: Any, raw_groups: Any) -> set[str]:
    """Extract the set of tag ids an axis declares, regardless of shape.

    Mirrors `_flatten_value_count`'s shape-handling: a flat list of scalars
    (e.g. field) yields the scalars themselves; a list of {id, ...} tag
    objects (e.g. claim_type) yields each `id`; a mapping of group-name ->
    list of values (e.g. theory_school) yields the flattened leaf values.
    """
    if raw_groups is not None:
        return {value for group_values in raw_groups.values() for value in group_values}
    if raw_values is not None:
        tag_ids: set[str] = set()
        for value in raw_values:
            if isinstance(value, dict):
                if "id" not in value:
                    raise MissingTagIdError(axis_name, value)
                tag_ids.add(value["id"])
            else:
                tag_ids.add(value)
        return tag_ids
    raise MissingValuesOrGroupsError(axis_name)


@dataclass
class Axis:
    name: str
    applies_to: list[str]
    cardinality: str
    value_count: int
    tag_ids: set[str] = field(default_factory=set)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Schema:
    version: str
    axes: dict[str, Axis]
    country_list: list[str] = field(default_factory=list)


def load_schema(domain_dir: str | Path) -> Schema:
    """Load and validate the schema at `<domain_dir>/schema.yaml`."""
    domain_dir = Path(domain_dir)
    schema_path = domain_dir / "schema.yaml"

    if not schema_path.is_file():
        raise MissingSchemaFileError(schema_path)

    with schema_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise MalformedSchemaError(schema_path, str(exc)) from exc

    if "version" not in raw or raw["version"] is None:
        raise MissingVersionError(schema_path)

    axes: dict[str, Axis] = {}
    for axis_name, axis_raw in (raw.get("axes") or {}).items():
        if not isinstance(axis_raw, dict):
            raise NonMappingAxisError(axis_name, axis_raw)

        cardinality = axis_raw.get("cardinality")
        if cardinality not in KNOWN_CARDINALITIES:
            raise UnknownCardinalityError(axis_name, cardinality)

        axes[axis_name] = Axis(
            name=axis_name,
            applies_to=axis_raw.get("applies_to", []),
            cardinality=cardinality,
            value_count=_flatten_value_count(
                axis_name, axis_raw.get("values"), axis_raw.get("groups")
            ),
            tag_ids=_flatten_tag_ids(axis_name, axis_raw.get("values"), axis_raw.get("groups")),
            raw=axis_raw,
        )

    return Schema(
        version=str(raw["version"]),
        axes=axes,
        country_list=raw.get("country_list", []),
    )
