"""Inner unit tests for the domain schema loader (issue #7, slice 02)."""

import re

import pytest

from axial.schema import (
    MissingSchemaFileError,
    MissingVersionError,
    UnknownCardinalityError,
    load_schema,
)


def _write_schema(domain_dir, text):
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "schema.yaml").write_text(text, encoding="utf-8")


def test_loader_parses_axes_with_applies_to_cardinality_and_values(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          field:
            applies_to: [prose, artifact]
            cardinality: primary_plus_secondary
            values: [state, violence, ideology]
        """,
    )

    schema = load_schema(tmp_path)

    axis = schema.axes["field"]
    assert axis.applies_to == ["prose", "artifact"]
    assert axis.cardinality == "primary_plus_secondary"
    assert axis.value_count == 3


def test_loader_exposes_version_field(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          field:
            applies_to: [prose]
            cardinality: single
            values: [state]
        """,
    )

    schema = load_schema(tmp_path)

    assert schema.version == "0.1"


def test_missing_version_is_a_hard_error(tmp_path):
    _write_schema(
        tmp_path,
        """
        axes:
          field:
            applies_to: [prose]
            cardinality: single
            values: [state]
        """,
    )

    with pytest.raises(MissingVersionError):
        load_schema(tmp_path)


def test_unknown_cardinality_is_a_hard_error_naming_the_axis(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          field:
            applies_to: [prose]
            cardinality: some-made-up-cardinality
            values: [state]
        """,
    )

    with pytest.raises(UnknownCardinalityError, match="field"):
        load_schema(tmp_path)


def test_loader_takes_a_domain_directory_no_country_branching(tmp_path):
    # Regression guard for §4: the loader must not special-case a country
    # name -- any domain directory with a schema.yaml works identically.
    domain_dir = tmp_path / "some-other-domain-not-syria"
    _write_schema(
        domain_dir,
        """
        version: 0.7
        axes:
          field:
            applies_to: [prose]
            cardinality: single
            values: [a, b]
        """,
    )

    schema = load_schema(domain_dir)

    assert schema.version == "0.7"
    assert schema.axes["field"].value_count == 2


def test_missing_schema_yaml_raises_clear_typed_error(tmp_path):
    domain_dir = tmp_path / "empty-domain"
    domain_dir.mkdir()

    with pytest.raises(MissingSchemaFileError, match=re.escape(str(domain_dir / "schema.yaml"))):
        load_schema(domain_dir)


def test_claim_type_shaped_values_count_by_id_entries(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          claim_type:
            applies_to: [prose]
            cardinality: primary_plus_optional_secondary
            values:
              - id: state-formation
                status: firm
                subtags: [formation:bellicist]
              - id: state-autonomy
                status: firm
        """,
    )

    schema = load_schema(tmp_path)

    assert schema.axes["claim_type"].value_count == 2


def test_grouped_values_flatten_for_value_count(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          theory_school:
            applies_to: [prose]
            cardinality: primary_plus_optional_secondary
            status: candidate
            groups:
              state: [bellicist, neo-bellicist]
              violence: [criminological]
        """,
    )

    schema = load_schema(tmp_path)

    assert schema.axes["theory_school"].value_count == 3
