"""Inner unit tests for the domain schema loader (issue #7, slice 02)."""

import re

import pytest

from axial.schema import (
    MalformedSchemaError,
    MissingSchemaFileError,
    MissingTagIdError,
    MissingValuesOrGroupsError,
    MissingVersionError,
    NonMappingAxisError,
    SchemaError,
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


def test_invalid_yaml_is_a_clear_typed_error_not_a_traceback(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          field: [this is not, valid: yaml: mapping
        """,
    )

    with pytest.raises(MalformedSchemaError, match=re.escape(str(tmp_path / "schema.yaml"))):
        load_schema(tmp_path)


def test_malformed_schema_error_is_a_schema_error(tmp_path):
    _write_schema(tmp_path, "version: 0.1\naxes: [not, a, mapping, :::")

    with pytest.raises(SchemaError):
        load_schema(tmp_path)


def test_non_mapping_axis_body_is_a_hard_error_naming_the_axis(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          field: just_a_string
        """,
    )

    with pytest.raises(NonMappingAxisError, match="field"):
        load_schema(tmp_path)


def test_axis_missing_values_and_groups_is_a_hard_error_naming_the_axis(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          field:
            applies_to: [prose]
            cardinality: single
            vals: [state]
        """,
    )

    with pytest.raises(MissingValuesOrGroupsError, match="field"):
        load_schema(tmp_path)


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


def test_tag_ids_for_flat_scalar_axis_are_the_scalars_themselves(tmp_path):
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

    assert schema.axes["field"].tag_ids == {"state", "violence", "ideology"}


def test_tag_ids_for_claim_type_shaped_values_are_the_ids(tmp_path):
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

    assert schema.axes["claim_type"].tag_ids == {"state-formation", "state-autonomy"}


def test_tag_ids_for_grouped_values_are_the_flattened_leaf_values(tmp_path):
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

    assert schema.axes["theory_school"].tag_ids == {"bellicist", "neo-bellicist", "criminological"}


def test_tag_ids_raises_typed_error_for_claim_type_entry_missing_id(tmp_path):
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
              - status: firm
        """,
    )

    with pytest.raises(MissingTagIdError, match=re.escape("claim_type")) as exc_info:
        load_schema(tmp_path)

    assert exc_info.value.axis_name == "claim_type"


# --- polity_examples (issue #194 slice 05, Appendix G rename from
# country_list) ---------------------------------------------------------


def test_schema_exposes_polity_examples_loaded_from_the_renamed_key(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          field:
            applies_to: [prose]
            cardinality: single
            values: [state]
        polity_examples: [Syria, Turkey, Lebanon]
        """,
    )

    schema = load_schema(tmp_path)

    assert schema.polity_examples == ["Syria", "Turkey", "Lebanon"]


def test_schema_polity_examples_defaults_to_empty_list_when_absent(tmp_path):
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

    assert schema.polity_examples == []


# --- "many" cardinality / free-text axis (issue #194 slice 05, Appendix
# C/G's polities_touched: cardinality: many, values: free_text) ----------


def test_many_cardinality_with_free_text_values_is_accepted(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          polities_touched:
            applies_to: [prose]
            cardinality: many
            values: free_text
        """,
    )

    schema = load_schema(tmp_path)

    axis = schema.axes["polities_touched"]
    assert axis.cardinality == "many"


def test_many_cardinality_free_text_axis_has_zero_value_count(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          polities_touched:
            applies_to: [prose]
            cardinality: many
            values: free_text
        """,
    )

    schema = load_schema(tmp_path)

    assert schema.axes["polities_touched"].value_count == 0


def test_many_cardinality_free_text_axis_has_empty_tag_ids(tmp_path):
    _write_schema(
        tmp_path,
        """
        version: 0.1
        axes:
          polities_touched:
            applies_to: [prose]
            cardinality: many
            values: free_text
        """,
    )

    schema = load_schema(tmp_path)

    assert schema.axes["polities_touched"].tag_ids == set()
