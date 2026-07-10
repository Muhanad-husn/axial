"""Inner unit tests for the axial tag module (issue #27 slice 01 -- tag
spine: role_in_argument, schema-driven, hard-error, versioned; issue #28
slice 02 -- empirical_scope axis + the scope:country-case country extra
field; issue #29 slice 03 -- field/claim_type/theory_school, the shared
primary+secondary cardinality validator)."""

from __future__ import annotations

import json

import pytest

from axial.codebook import Codebook, TagEntry
from axial.llm import TAG_PASS_NAME, StubLLMClient
from axial.schema import Axis, Schema

_SCHEMA = Schema(
    version="0.1",
    axes={
        "field": Axis(
            name="field",
            applies_to=["prose", "artifact"],
            cardinality="primary_plus_secondary",
            value_count=3,
            tag_ids={"state", "violence", "ideology"},
        ),
        "artifact_role": Axis(
            name="artifact_role",
            applies_to=["artifact"],
            cardinality="single",
            value_count=1,
            tag_ids={"case-study"},
        ),
        "role_in_argument": Axis(
            name="role_in_argument",
            applies_to=["prose"],
            cardinality="single",
            value_count=3,
            tag_ids={"role:claim", "role:evidence", "role:setup"},
        ),
    },
)

_SCHEMA_WITH_COUNTRY = Schema(
    version="0.1",
    axes={
        "empirical_scope": Axis(
            name="empirical_scope",
            applies_to=["prose"],
            cardinality="single",
            value_count=2,
            tag_ids={"scope:country-case", "scope:general"},
        ),
    },
    country_list=["Syria", "Turkey"],
)

_SCHEMA_WITH_MULTI_VALUE_AXES = Schema(
    version="0.1",
    axes={
        "field": Axis(
            name="field",
            applies_to=["prose"],
            cardinality="primary_plus_secondary",
            value_count=3,
            tag_ids={"state", "violence", "ideology"},
            raw={
                "cardinality": "primary_plus_secondary",
                "values": ["state", "violence", "ideology"],
            },
        ),
        "claim_type": Axis(
            name="claim_type",
            applies_to=["prose"],
            cardinality="primary_plus_optional_secondary",
            value_count=2,
            tag_ids={"state-formation", "state-autonomy"},
            raw={
                "cardinality": "primary_plus_optional_secondary",
                "values": [
                    {
                        "id": "state-formation",
                        "subtags": ["formation:bellicist", "formation:colonial-import"],
                    },
                    {"id": "state-autonomy"},
                ],
            },
        ),
        "theory_school": Axis(
            name="theory_school",
            applies_to=["prose"],
            cardinality="primary_plus_optional_secondary",
            value_count=2,
            tag_ids={"bellicist", "structuralist"},
            raw={
                "cardinality": "primary_plus_optional_secondary",
                "status": "candidate",
                "groups": {"state": ["bellicist", "structuralist"]},
            },
        ),
    },
)

_CODEBOOK = Codebook(
    axes={
        "role_in_argument": {
            "role:claim": TagEntry(
                definition="States the author's central argument.",
                positive_example="A clear thesis statement.",
                negative_example="A background fact.",
            ),
            "role:evidence": TagEntry(
                definition="Supports a claim with data or citations.",
                positive_example="A cited statistic.",
                negative_example="An unsupported assertion.",
            ),
            "role:setup": TagEntry(
                definition="Establishes context before the claim.",
                positive_example="Scene-setting background.",
                negative_example="The claim itself.",
            ),
        }
    }
)


# --- listing prose axes -------------------------------------------------


def test_list_prose_axes_includes_role_in_argument_and_excludes_artifact_only():
    from axial.tag import list_prose_axes

    axes = list_prose_axes(_SCHEMA)

    assert "role_in_argument" in axes
    assert "artifact_role" not in axes
    assert "field" in axes  # field applies_to includes both prose and artifact


# --- prompt composition ---------------------------------------------------


def test_compose_tag_prompt_includes_definitions_and_examples_for_each_tag():
    from axial.tag import compose_tag_prompt

    prompt = compose_tag_prompt("Some chunk text.", "role_in_argument", _CODEBOOK)

    assert "Some chunk text." in prompt
    assert "role:claim" in prompt
    assert "States the author's central argument." in prompt
    assert "A clear thesis statement." in prompt
    assert "An unsupported assertion." in prompt


def test_compose_tag_prompt_never_leaks_an_internal_dispatch_marker():
    from axial.tag import compose_tag_prompt

    prompt = compose_tag_prompt("Some chunk text.", "role_in_argument", _CODEBOOK)

    assert "AXIAL_TAG_PASS_V1" not in prompt


# --- response parsing ------------------------------------------------------


def test_parse_tag_response_returns_the_single_value():
    from axial.tag import parse_tag_response

    raw = json.dumps({"role_in_argument": "role:claim"})

    value = parse_tag_response(raw, "role_in_argument")

    assert value == "role:claim"


def test_parse_tag_response_rejects_invalid_json():
    from axial.tag import TagParseError, parse_tag_response

    with pytest.raises(TagParseError):
        parse_tag_response("not json at all", "role_in_argument")


def test_parse_tag_response_accepts_a_markdown_fenced_response():
    """issue #72: deepseek-v4-flash sometimes wraps its JSON answer in a
    markdown fence despite the prompt's "no fences" instruction."""
    from axial.tag import parse_tag_response

    raw = f"```json\n{json.dumps({'role_in_argument': 'role:claim'})}\n```"

    assert parse_tag_response(raw, "role_in_argument") == "role:claim"


def test_parse_tag_response_rejects_prose_with_a_snippet_in_the_message():
    """issue #72: parse errors must quote the raw response so failures are
    diagnosable from worker logs."""
    from axial.tag import TagParseError, parse_tag_response

    raw = "I cannot tag this claim."

    with pytest.raises(TagParseError) as exc_info:
        parse_tag_response(raw, "role_in_argument")

    assert raw in str(exc_info.value)


def test_parse_tag_response_rejects_missing_axis_key():
    from axial.tag import TagParseError, parse_tag_response

    with pytest.raises(TagParseError):
        parse_tag_response(json.dumps({"nope": "role:claim"}), "role_in_argument")


def test_parse_tag_response_rejects_zero_values():
    from axial.tag import TagCardinalityError, parse_tag_response

    with pytest.raises(TagCardinalityError):
        parse_tag_response(json.dumps({"role_in_argument": []}), "role_in_argument")


def test_parse_tag_response_rejects_multiple_values():
    from axial.tag import TagCardinalityError, parse_tag_response

    with pytest.raises(TagCardinalityError):
        parse_tag_response(
            json.dumps({"role_in_argument": ["role:claim", "role:evidence"]}),
            "role_in_argument",
        )


def test_parse_tag_response_rejects_a_two_candidate_dict_value_as_a_tag_error():
    """A dict with two remaining (non-auxiliary) string-valued entries and no
    'primary'/'value' key is never a silent pick -- issue #88 point 3 widens
    single-candidate object dialects, but a genuine multi-candidate object
    still errors."""
    from axial.tag import TagError, parse_tag_response

    raw = json.dumps({"role_in_argument": {"a": "x", "b": "y"}})

    with pytest.raises(TagError):
        parse_tag_response(raw, "role_in_argument")


def test_parse_tag_response_rejects_a_single_element_list_of_a_dict_as_a_tag_error():
    from axial.tag import TagError, parse_tag_response

    raw = json.dumps({"role_in_argument": [{"nested": "oops"}]})

    with pytest.raises(TagError):
        parse_tag_response(raw, "role_in_argument")


# --- object-shaped single-axis dialect (issue #62) --------------------------


def test_parse_tag_response_accepts_an_object_shaped_value_using_its_primary():
    from axial.tag import parse_tag_response

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case", "country": "Syria"}})

    value = parse_tag_response(raw, "empirical_scope")

    assert value == "scope:country-case"


def test_parse_tag_response_rejects_an_object_shaped_value_with_a_non_empty_secondary_list():
    from axial.tag import TagCardinalityError, parse_tag_response

    raw = json.dumps(
        {"role_in_argument": {"primary": "role:claim", "secondary": ["role:evidence"]}}
    )

    with pytest.raises(TagCardinalityError):
        parse_tag_response(raw, "role_in_argument")


def test_parse_tag_response_rejects_an_object_shaped_value_with_a_non_empty_secondary_string():
    from axial.tag import TagCardinalityError, parse_tag_response

    raw = json.dumps({"role_in_argument": {"primary": "role:claim", "secondary": "role:evidence"}})

    with pytest.raises(TagCardinalityError):
        parse_tag_response(raw, "role_in_argument")


def test_parse_tag_response_accepts_an_object_shaped_value_with_an_empty_secondary_list():
    from axial.tag import parse_tag_response

    raw = json.dumps({"role_in_argument": {"primary": "role:claim", "secondary": []}})

    value = parse_tag_response(raw, "role_in_argument")

    assert value == "role:claim"


def test_parse_tag_response_accepts_an_object_shaped_value_with_a_none_secondary():
    from axial.tag import parse_tag_response

    raw = json.dumps({"role_in_argument": {"primary": "role:claim", "secondary": None}})

    value = parse_tag_response(raw, "role_in_argument")

    assert value == "role:claim"


def test_parse_tag_response_rejects_an_object_shaped_value_without_a_string_primary():
    from axial.tag import TagParseError, parse_tag_response

    raw = json.dumps({"role_in_argument": {"secondary": "role:evidence"}})

    with pytest.raises(TagParseError):
        parse_tag_response(raw, "role_in_argument")


# --- widened single-axis object dialects (issue #88) ------------------------


def test_parse_tag_response_accepts_an_object_shaped_value_using_its_value_key():
    """`{'value': <str>, 'country': ...}` -- deepseek-v4-flash's modal dialect
    for scope:country-case chunks (issue #88 point 2)."""
    from axial.tag import parse_tag_response

    raw = json.dumps({"empirical_scope": {"value": "scope:country-case", "country": "Syria"}})

    value = parse_tag_response(raw, "empirical_scope")

    assert value == "scope:country-case"


def test_parse_tag_response_accepts_the_value_as_key_dialect():
    """`{'scope:country-case': 'scope:country-case', 'country': ...}` -- the
    other modal dialect (issue #88 point 3): exactly one remaining entry
    (after excluding 'country'/'secondary'/'subtags') with a string value."""
    from axial.tag import parse_tag_response

    raw = json.dumps(
        {"empirical_scope": {"scope:country-case": "scope:country-case", "country": "Syria"}}
    )

    value = parse_tag_response(raw, "empirical_scope")

    assert value == "scope:country-case"


def test_parse_tag_response_primary_wins_over_value_when_both_present():
    from axial.tag import parse_tag_response

    raw = json.dumps({"role_in_argument": {"primary": "role:claim", "value": "role:evidence"}})

    value = parse_tag_response(raw, "role_in_argument")

    assert value == "role:claim"


def test_parse_tag_response_value_key_wins_over_a_bare_single_candidate_entry():
    """'value' beats the value-as-key fallback when both a 'value' key and
    another candidate entry are present."""
    from axial.tag import parse_tag_response

    raw = json.dumps(
        {"role_in_argument": {"value": "role:claim", "role:evidence": "role:evidence"}}
    )

    value = parse_tag_response(raw, "role_in_argument")

    assert value == "role:claim"


def test_parse_tag_response_rejects_an_object_with_only_auxiliary_keys_and_no_candidate():
    from axial.tag import TagParseError, parse_tag_response

    raw = json.dumps({"empirical_scope": {"country": "Syria", "secondary": []}})

    with pytest.raises(TagParseError):
        parse_tag_response(raw, "empirical_scope")


def test_parse_tag_response_rejects_a_single_candidate_object_whose_value_is_not_a_string():
    from axial.tag import TagParseError, parse_tag_response

    raw = json.dumps({"role_in_argument": {"nested": ["not", "a", "string"]}})

    with pytest.raises(TagParseError):
        parse_tag_response(raw, "role_in_argument")


def test_parse_tag_response_rejects_a_single_non_echo_string_entry():
    """Rule 3 is narrowed to the observed value-as-key ECHO dialect (key ==
    value) only -- a lone entry whose key and value differ (e.g. free-form
    'reasoning' prose) is never a candidate, since accepting any lone string
    entry would let real prose parse cleanly here only to die fatally at
    `validate_tag` outside the re-ask budget, rather than staying a
    re-askable `TagParseError` (review finding on issue #88)."""
    from axial.tag import TagParseError, parse_tag_response

    raw = json.dumps({"role_in_argument": {"reasoning": "some prose"}})

    with pytest.raises(TagParseError):
        parse_tag_response(raw, "role_in_argument")


def test_parse_tag_response_extracted_object_value_still_honors_secondary_cardinality_error():
    """The widened extraction paths (value-key, value-as-key) still route
    through the same non-empty-secondary cardinality check the 'primary'
    path already had."""
    from axial.tag import TagCardinalityError, parse_tag_response

    raw = json.dumps({"role_in_argument": {"value": "role:claim", "secondary": ["role:evidence"]}})

    with pytest.raises(TagCardinalityError):
        parse_tag_response(raw, "role_in_argument")


# --- schema validation -------------------------------------------------------


def test_validate_tag_accepts_an_in_schema_value():
    from axial.tag import validate_tag

    validate_tag(_SCHEMA, "role_in_argument", "role:claim")  # does not raise


def test_validate_tag_rejects_an_absent_value_naming_axis_and_tag():
    from axial.tag import TagNotInSchemaError, validate_tag

    with pytest.raises(TagNotInSchemaError) as exc_info:
        validate_tag(_SCHEMA, "role_in_argument", "role:not-a-real-tag")

    message = str(exc_info.value)
    assert "role_in_argument" in message
    assert "role:not-a-real-tag" in message


# --- shared primary+secondary multi-value axis parsing/validation
# (issue #29 slice 03) ---------------------------------------------------


def test_parse_multi_value_tag_response_primary_plus_secondary_defaults_empty_list():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps({"field": {"primary": "state"}})

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["field"])

    assert parsed == {"primary": "state", "secondary": []}


def test_parse_multi_value_tag_response_primary_plus_secondary_keeps_given_list():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps({"field": {"primary": "state", "secondary": ["violence", "ideology"]}})

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["field"])

    assert parsed["secondary"] == ["violence", "ideology"]


def test_parse_multi_value_tag_response_optional_secondary_defaults_to_none():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps({"claim_type": {"primary": "state-formation"}})

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["claim_type"])

    assert parsed["secondary"] is None


def test_parse_multi_value_tag_response_optional_secondary_empty_list_becomes_none():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps({"claim_type": {"primary": "state-formation", "secondary": []}})

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["claim_type"])

    assert parsed["secondary"] is None


def test_parse_multi_value_tag_response_optional_secondary_single_element_list_becomes_scalar():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps(
        {"claim_type": {"primary": "state-formation", "secondary": ["state-autonomy"]}}
    )

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["claim_type"])

    assert parsed["secondary"] == "state-autonomy"


def test_parse_multi_value_tag_response_optional_secondary_rejects_a_multi_element_list():
    from axial.tag import TagParseError, parse_multi_value_tag_response

    raw = json.dumps(
        {
            "claim_type": {
                "primary": "state-formation",
                "secondary": ["state-autonomy", "state-formation"],
            }
        }
    )

    with pytest.raises(TagParseError):
        parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["claim_type"])


def test_parse_multi_value_tag_response_optional_secondary_rejects_a_single_element_list_of_non_string():
    from axial.tag import TagParseError, parse_multi_value_tag_response

    raw = json.dumps({"claim_type": {"primary": "state-formation", "secondary": [3]}})

    with pytest.raises(TagParseError):
        parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["claim_type"])


def test_parse_multi_value_tag_response_defaults_subtags_empty_when_axis_declares_them():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps({"claim_type": {"primary": "state-formation"}})

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["claim_type"])

    assert parsed["subtags"] == []


def test_parse_multi_value_tag_response_keeps_given_subtags():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps(
        {"claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]}}
    )

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["claim_type"])

    assert parsed["subtags"] == ["formation:bellicist"]


def test_parse_multi_value_tag_response_omits_subtags_when_axis_has_no_subtag_concept():
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps({"field": {"primary": "state"}})

    parsed = parse_multi_value_tag_response(raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["field"])

    assert "subtags" not in parsed


def test_parse_multi_value_tag_response_rejects_missing_axis_key():
    from axial.tag import TagParseError, parse_multi_value_tag_response

    with pytest.raises(TagParseError):
        parse_multi_value_tag_response(
            json.dumps({"nope": {"primary": "state"}}), _SCHEMA_WITH_MULTI_VALUE_AXES.axes["field"]
        )


def test_parse_multi_value_tag_response_rejects_a_bare_scalar_value():
    from axial.tag import TagParseError, parse_multi_value_tag_response

    with pytest.raises(TagParseError):
        parse_multi_value_tag_response(
            json.dumps({"field": "state"}), _SCHEMA_WITH_MULTI_VALUE_AXES.axes["field"]
        )


def test_validate_multi_value_tag_accepts_a_fully_in_schema_value():
    from axial.tag import validate_multi_value_tag

    parsed = {"primary": "state", "secondary": ["violence"]}
    validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "field", parsed)  # does not raise


def test_validate_multi_value_tag_rejects_an_out_of_schema_primary_naming_axis_and_tag():
    from axial.tag import TagNotInSchemaError, validate_multi_value_tag

    parsed = {"primary": "field:not-a-real-field", "secondary": []}

    with pytest.raises(TagNotInSchemaError) as exc_info:
        validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "field", parsed)

    message = str(exc_info.value)
    assert "field" in message
    assert "field:not-a-real-field" in message


def test_validate_multi_value_tag_rejects_an_out_of_schema_secondary():
    from axial.tag import TagNotInSchemaError, validate_multi_value_tag

    parsed = {"primary": "state", "secondary": ["not-a-real-secondary"]}

    with pytest.raises(TagNotInSchemaError):
        validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "field", parsed)


def test_validate_multi_value_tag_accepts_a_subtag_declared_under_its_own_primary():
    from axial.tag import validate_multi_value_tag

    parsed = {"primary": "state-formation", "secondary": None, "subtags": ["formation:bellicist"]}
    validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "claim_type", parsed)  # does not raise


def test_validate_multi_value_tag_rejects_an_undeclared_subtag_naming_axis_and_subtag():
    from axial.tag import TagNotInSchemaError, validate_multi_value_tag

    parsed = {"primary": "state-formation", "secondary": None, "subtags": ["not-a-real-subtag"]}

    with pytest.raises(TagNotInSchemaError) as exc_info:
        validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "claim_type", parsed)

    message = str(exc_info.value)
    assert "claim_type" in message
    assert "not-a-real-subtag" in message


def test_validate_multi_value_tag_rejects_a_subtag_declared_under_a_different_primary():
    """A subtag valid under one claim_type id is not automatically valid
    under another (Appendix B)."""
    from axial.tag import TagNotInSchemaError, validate_multi_value_tag

    # "state-autonomy" declares no subtags at all, so this one -- which only
    # belongs to "state-formation" -- must be rejected here.
    parsed = {"primary": "state-autonomy", "secondary": None, "subtags": ["formation:bellicist"]}

    with pytest.raises(TagNotInSchemaError):
        validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "claim_type", parsed)


def test_axis_extras_surfaces_a_schema_declared_status():
    from axial.tag import _axis_extras

    extras = _axis_extras(_SCHEMA_WITH_MULTI_VALUE_AXES.axes["theory_school"])

    assert extras == {"status": "candidate"}


def test_axis_extras_is_empty_when_the_axis_declares_no_status():
    from axial.tag import _axis_extras

    extras = _axis_extras(_SCHEMA_WITH_MULTI_VALUE_AXES.axes["field"])

    assert extras == {}


# --- country-case extra field (issue #28 slice 02) --------------------------


def test_parse_country_response_returns_the_country():
    from axial.tag import parse_country_response

    raw = json.dumps({"empirical_scope": "scope:country-case", "country": "Syria"})

    assert parse_country_response(raw) == "Syria"


def test_parse_country_response_rejects_a_missing_country_key():
    from axial.tag import CountryCaseMissingCountryError, parse_country_response

    raw = json.dumps({"empirical_scope": "scope:country-case"})

    with pytest.raises(CountryCaseMissingCountryError):
        parse_country_response(raw)


def test_parse_country_response_rejects_an_empty_country_value():
    from axial.tag import CountryCaseMissingCountryError, parse_country_response

    raw = json.dumps({"empirical_scope": "scope:country-case", "country": ""})

    with pytest.raises(CountryCaseMissingCountryError):
        parse_country_response(raw)


def test_parse_country_response_accepts_a_nested_country_when_top_level_absent():
    from axial.tag import parse_country_response

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case", "country": "Syria"}})

    assert parse_country_response(raw, "empirical_scope") == "Syria"


def test_parse_country_response_prefers_the_top_level_country_over_a_nested_one():
    from axial.tag import parse_country_response

    raw = json.dumps(
        {
            "empirical_scope": {"primary": "scope:country-case", "country": "Iraq"},
            "country": "Syria",
        }
    )

    assert parse_country_response(raw, "empirical_scope") == "Syria"


def test_parse_country_response_rejects_missing_country_in_both_places():
    from axial.tag import CountryCaseMissingCountryError, parse_country_response

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case"}})

    with pytest.raises(CountryCaseMissingCountryError):
        parse_country_response(raw, "empirical_scope")


def test_parse_country_response_rejects_a_non_string_nested_country():
    from axial.tag import TagParseError, parse_country_response

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case", "country": 7}})

    with pytest.raises(TagParseError):
        parse_country_response(raw, "empirical_scope")


def test_parse_country_response_accepts_a_nested_country_with_the_value_key_dialect():
    """`parse_country_response` reads `data[axis_name]['country']` regardless
    of how the axis's own value was extracted -- confirms the nested-country
    fallback composes with the 'value' key dialect (issue #88)."""
    from axial.tag import parse_country_response

    raw = json.dumps({"empirical_scope": {"value": "scope:country-case", "country": "Syria"}})

    assert parse_country_response(raw, "empirical_scope") == "Syria"


def test_parse_country_response_accepts_a_nested_country_with_the_value_as_key_dialect():
    """Same, for the value-as-key dialect (issue #88)."""
    from axial.tag import parse_country_response

    raw = json.dumps(
        {"empirical_scope": {"scope:country-case": "scope:country-case", "country": "Syria"}}
    )

    assert parse_country_response(raw, "empirical_scope") == "Syria"


def test_log_country_not_in_list_is_silent_for_an_in_list_value(capsys):
    from axial.tag import log_country_not_in_list

    log_country_not_in_list(_SCHEMA_WITH_COUNTRY, "Syria")  # does not raise

    captured = capsys.readouterr()
    assert captured.err == ""


def test_log_country_not_in_list_logs_an_out_of_list_value_to_stderr(capsys):
    from axial.tag import log_country_not_in_list

    log_country_not_in_list(_SCHEMA_WITH_COUNTRY, "Atlantis")  # does not raise

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Atlantis" in captured.err
    assert "country_list" in captured.err


# --- record assembly ---------------------------------------------------------


def test_build_tagged_record_carries_provenance_and_schema_version():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "paper-abc123_1_intro_001", "section": "Introduction", "text": "x"}

    record = build_tagged_record(chunk_record, "role:claim", _SCHEMA.version)

    assert record["chunk_id"] == "paper-abc123_1_intro_001"
    assert record["section"] == "Introduction"
    assert record["chunk_text"] == "x"
    assert record["role_in_argument"] == "role:claim"
    assert record["schema_version"] == "0.1"
    assert "empirical_scope" not in record
    assert "country" not in record


def test_build_tagged_record_carries_empirical_scope_and_country_when_given():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "id1", "section": "Introduction", "text": "x"}

    record = build_tagged_record(
        chunk_record,
        "role:claim",
        "0.1",
        empirical_scope="scope:country-case",
        country="Syria",
    )

    assert record["empirical_scope"] == "scope:country-case"
    assert record["country"] == "Syria"


def test_build_tagged_record_omits_country_when_not_given():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "id1", "section": "Introduction", "text": "x"}

    record = build_tagged_record(chunk_record, "role:claim", "0.1", empirical_scope="scope:general")

    assert record["empirical_scope"] == "scope:general"
    assert "country" not in record


def test_build_tagged_record_adds_one_key_per_multi_value_axis():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "id1", "section": "Introduction", "text": "x"}

    record = build_tagged_record(
        chunk_record,
        "role:claim",
        "0.1",
        multi_value_axes={
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "secondary": None, "subtags": []},
        },
    )

    assert record["field"] == {"primary": "state", "secondary": []}
    assert record["claim_type"] == {"primary": "state-formation", "secondary": None, "subtags": []}
    assert "theory_school" not in record


# --- run_tag: zero chunks, happy path, hard error ----------------------------


def _write_minimal_domain(tmp_path, tag_ids: tuple[str, ...] = ("role:claim", "role:evidence")):
    """Write a minimal schema.yaml + codebook.yaml under a fresh domain dir,
    covering just the role_in_argument axis for `run_tag` unit tests."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    values_block = ", ".join(tag_ids)
    entries_block = "".join(
        f"    {tag_id}: {{definition: d, positive_example: p, negative_example: n}}\n"
        for tag_id in tag_ids
    )
    (domain_dir / "schema.yaml").write_text(
        f"version: 0.1\naxes:\n  role_in_argument:\n"
        f"    applies_to: [prose]\n    cardinality: single\n"
        f"    values: [{values_block}]\n",
        encoding="utf-8",
    )
    (domain_dir / "codebook.yaml").write_text(
        f"axes:\n  role_in_argument:\n{entries_block}",
        encoding="utf-8",
    )
    return domain_dir


def test_run_tag_zero_chunks_yields_zero_tagged_records_without_a_tag_llm_call(
    monkeypatch, tmp_path
):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path)
    monkeypatch.setattr(tag_mod, "run_chunk", lambda *args, **kwargs: [])

    stub_client = StubLLMClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=stub_client, domain_dir=domain_dir)

    assert records == []
    assert stub_client.call_count == 0


def test_run_tag_produces_one_record_per_chunk_with_role_and_schema_version(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path)
    chunk_records = [
        {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"},
        {"chunk_id": "src_1_intro_002", "section": "Introduction", "text": "chunk two"},
    ]
    monkeypatch.setattr(tag_mod, "run_chunk", lambda *args, **kwargs: chunk_records)

    stub_client = StubLLMClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=stub_client, domain_dir=domain_dir)

    assert len(records) == 2
    assert stub_client.call_count == 2
    for record, chunk_record in zip(records, chunk_records):
        assert record["chunk_id"] == chunk_record["chunk_id"]
        assert record["section"] == chunk_record["section"]
        assert record["chunk_text"] == chunk_record["text"]
        assert record["role_in_argument"] == "role:claim"
        assert record["schema_version"] == "0.1"


def test_run_tag_calls_the_client_with_the_tag_pass_name(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    calls = []

    class _CapturingClient:
        def complete(self, prompt, pass_name=None):
            calls.append(pass_name)
            return json.dumps({"role_in_argument": "role:claim"})

    tag_mod.run_tag(tmp_path / "paper.pdf", client=_CapturingClient(), domain_dir=domain_dir)

    assert calls == [TAG_PASS_NAME]


def test_run_tag_raises_a_hard_error_for_an_out_of_schema_tag(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    class _OutOfSchemaClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps({"role_in_argument": "role:not-a-real-tag"})

    with pytest.raises(tag_mod.TagNotInSchemaError):
        tag_mod.run_tag(tmp_path / "paper.pdf", client=_OutOfSchemaClient(), domain_dir=domain_dir)


# --- run_tag: empirical_scope + country-case extra field (issue #28 slice 02) --


def _write_domain_with_empirical_scope(
    tmp_path, country_list: tuple[str, ...] = ("Syria", "Turkey")
):
    """Write a minimal schema.yaml + codebook.yaml covering both
    role_in_argument and empirical_scope (with a country_list), for
    `run_tag` country-case unit tests."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    countries_block = ", ".join(country_list)
    (domain_dir / "schema.yaml").write_text(
        "version: 0.1\n"
        "axes:\n"
        "  role_in_argument:\n"
        "    applies_to: [prose]\n"
        "    cardinality: single\n"
        "    values: [role:claim, role:evidence]\n"
        "  empirical_scope:\n"
        "    applies_to: [prose]\n"
        "    cardinality: single\n"
        "    values: [scope:country-case, scope:general]\n"
        f"country_list: [{countries_block}]\n",
        encoding="utf-8",
    )
    (domain_dir / "codebook.yaml").write_text(
        "axes:\n"
        "  role_in_argument:\n"
        "    role:claim: {definition: d, positive_example: p, negative_example: n}\n"
        "    role:evidence: {definition: d, positive_example: p, negative_example: n}\n"
        "  empirical_scope:\n"
        "    scope:country-case: {definition: d, positive_example: p, negative_example: n}\n"
        "    scope:general: {definition: d, positive_example: p, negative_example: n}\n",
        encoding="utf-8",
    )
    return domain_dir


def _one_chunk_run_chunk(monkeypatch, tag_mod):
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "c1", "section": "Introduction", "text": "chunk one"}
        ],
    )


def test_run_tag_country_case_record_carries_empirical_scope_and_country(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": "scope:country-case",
                    "country": "Syria",
                }
            )

    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert records[0]["empirical_scope"] == "scope:country-case"
    assert records[0]["country"] == "Syria"


def test_run_tag_non_country_case_record_carries_no_country(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:general"}
            )

    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)

    assert records[0]["empirical_scope"] == "scope:general"
    assert "country" not in records[0]


def test_run_tag_country_case_missing_country_raises_hard_error(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:country-case"}
            )

    with pytest.raises(tag_mod.CountryCaseMissingCountryError):
        tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)


def test_run_tag_country_case_out_of_list_country_is_accepted_and_logged(
    monkeypatch, tmp_path, capsys
):
    """Spec-drift #77 (adjudicated 2026-07-10): an out-of-list country is
    no longer fatal -- it is accepted verbatim on the record and logged to
    stderr as a candidate addition, naming the value and 'country_list'."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": "scope:country-case",
                    "country": "Atlantis",
                }
            )

    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)

    assert records[0]["country"] == "Atlantis"

    captured = capsys.readouterr()
    assert "Atlantis" in captured.err
    assert "country_list" in captured.err


def test_run_tag_makes_exactly_one_llm_call_per_chunk_even_with_two_tagged_axes(
    monkeypatch, tmp_path
):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    calls = []

    class _Client:
        def complete(self, prompt, pass_name=None):
            calls.append(pass_name)
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:general"}
            )

    tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)

    assert calls == [TAG_PASS_NAME]


def test_run_tag_regresses_role_in_argument_when_empirical_scope_axis_absent(monkeypatch, tmp_path):
    """A domain that doesn't declare empirical_scope (e.g. slice 01's
    minimal fixture domain) must still tag role_in_argument alone, with no
    empirical_scope/country keys added and no error for the axis the schema
    doesn't define."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    stub_client = StubLLMClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=stub_client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert "empirical_scope" not in records[0]
    assert "country" not in records[0]


# --- run_tag: field/claim_type/theory_school (issue #29 slice 03) -----------


def _write_domain_with_multi_value_axes(tmp_path):
    """Write a schema.yaml + codebook.yaml covering role_in_argument plus
    the three primary+secondary axes (field, claim_type with its own
    per-tag subtags, theory_school with an axis-level status), for
    `run_tag` multi-value-axis unit tests."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    (domain_dir / "schema.yaml").write_text(
        "version: 0.1\n"
        "axes:\n"
        "  role_in_argument:\n"
        "    applies_to: [prose]\n"
        "    cardinality: single\n"
        "    values: [role:claim]\n"
        "  field:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_secondary\n"
        "    values: [state, violence, ideology]\n"
        "  claim_type:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_optional_secondary\n"
        "    values:\n"
        "      - id: state-formation\n"
        "        subtags: [formation:bellicist, formation:colonial-import]\n"
        "      - id: state-autonomy\n"
        "  theory_school:\n"
        "    applies_to: [prose]\n"
        "    cardinality: primary_plus_optional_secondary\n"
        "    status: candidate\n"
        "    groups:\n"
        "      state: [bellicist, structuralist]\n",
        encoding="utf-8",
    )
    (domain_dir / "codebook.yaml").write_text(
        "axes:\n"
        "  role_in_argument:\n"
        "    role:claim: {definition: d, positive_example: p, negative_example: n}\n"
        "  field:\n"
        "    state: {definition: d, positive_example: p, negative_example: n}\n"
        "    violence: {definition: d, positive_example: p, negative_example: n}\n"
        "    ideology: {definition: d, positive_example: p, negative_example: n}\n"
        "  claim_type:\n"
        "    state-formation: {definition: d, positive_example: p, negative_example: n}\n"
        "    state-autonomy: {definition: d, positive_example: p, negative_example: n}\n"
        "  theory_school:\n"
        "    bellicist: {definition: d, positive_example: p, negative_example: n}\n"
        "    structuralist: {definition: d, positive_example: p, negative_example: n}\n",
        encoding="utf-8",
    )
    return domain_dir


def test_run_tag_assigns_field_claim_type_theory_school_in_the_appendix_h_shape(
    monkeypatch, tmp_path
):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "field": {"primary": "state", "secondary": ["ideology"]},
                    "claim_type": {
                        "primary": "state-formation",
                        "subtags": ["formation:bellicist"],
                    },
                    "theory_school": {"primary": "bellicist"},
                }
            )

    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)

    assert len(records) == 1
    record = records[0]
    assert record["field"] == {"primary": "state", "secondary": ["ideology"]}
    assert record["claim_type"] == {
        "primary": "state-formation",
        "secondary": None,
        "subtags": ["formation:bellicist"],
    }
    # theory_school.status always comes from the schema, never the model
    # (which omitted it here entirely).
    assert record["theory_school"] == {
        "primary": "bellicist",
        "secondary": None,
        "status": "candidate",
    }


def test_run_tag_raises_a_hard_error_for_an_out_of_schema_field_primary(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "field": {"primary": "not-a-real-field", "secondary": []},
                    "claim_type": {"primary": "state-formation", "subtags": []},
                    "theory_school": {"primary": "bellicist"},
                }
            )

    with pytest.raises(tag_mod.TagNotInSchemaError) as exc_info:
        tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)

    message = str(exc_info.value)
    assert "field" in message
    assert "not-a-real-field" in message


def test_run_tag_raises_a_hard_error_for_an_undeclared_claim_type_subtag(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "field": {"primary": "state", "secondary": []},
                    "claim_type": {"primary": "state-formation", "subtags": ["not-a-real-subtag"]},
                    "theory_school": {"primary": "bellicist"},
                }
            )

    with pytest.raises(tag_mod.TagNotInSchemaError) as exc_info:
        tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir)

    message = str(exc_info.value)
    assert "claim_type" in message
    assert "not-a-real-subtag" in message


def test_run_tag_succeeds_when_first_completion_is_malformed_json(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    valid = json.dumps({"role_in_argument": "role:claim"})

    class _ScriptedClient:
        def __init__(self):
            self._responses = ["not json at all", valid]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert client.call_count == 2


def test_run_tag_raises_tag_parse_error_on_persistently_malformed_json(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    class _AlwaysBrokenClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return "not json at all"

    client = _AlwaysBrokenClient()

    with pytest.raises(tag_mod.TagParseError):
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert client.call_count == 3


# --- run_tag: degenerate (empty-string) tag values re-ask, not fatal (#80) --


def test_run_tag_reasks_and_succeeds_when_primary_axis_value_is_first_empty_string(
    monkeypatch, tmp_path
):
    """A single-cardinality axis's value coming back as `''` (valid JSON,
    degenerate content) must not immediately raise `TagNotInSchemaError` --
    it re-asks within complete_json's bounded budget and succeeds on a clean
    second response."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    degenerate = json.dumps({"role_in_argument": ""})
    clean = json.dumps({"role_in_argument": "role:claim"})

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, clean]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert client.call_count == 2


def test_run_tag_raises_tag_parse_error_on_persistently_empty_string_primary(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    class _AlwaysEmptyClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps({"role_in_argument": ""})

    client = _AlwaysEmptyClient()

    with pytest.raises(tag_mod.TagParseError):
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert client.call_count == 3


def test_run_tag_reasks_and_succeeds_when_secondary_entry_is_first_empty_string(
    monkeypatch, tmp_path
):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    degenerate = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": [""]},
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )
    clean = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": ["ideology"]},
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, clean]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["field"] == {"primary": "state", "secondary": ["ideology"]}
    assert client.call_count == 2


def test_run_tag_reasks_and_succeeds_when_subtag_is_first_empty_string(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    degenerate = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": [""]},
            "theory_school": {"primary": "bellicist"},
        }
    )
    clean = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {
                "primary": "state-formation",
                "subtags": ["formation:bellicist"],
            },
            "theory_school": {"primary": "bellicist"},
        }
    )

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, clean]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["claim_type"]["subtags"] == ["formation:bellicist"]
    assert client.call_count == 2


def test_run_tag_out_of_vocab_non_empty_tag_is_immediately_fatal_with_no_reask(
    monkeypatch, tmp_path
):
    """A genuine non-empty out-of-vocabulary tag must NEVER be treated as
    degenerate -- it stays immediately fatal (`TagNotInSchemaError`), with
    exactly one client call, never re-asked (issue #80: the P0-6 schema-gap
    signal is untouched by the degenerate-response re-ask)."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps({"role_in_argument": "role:not-a-real-tag"})

    client = _CountingClient()

    with pytest.raises(tag_mod.TagNotInSchemaError):
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert client.call_count == 1


# --- run_tag: widened single-axis object dialects (issue #88) ---------------


def test_run_tag_zaum_payload_carries_scope_and_country_with_zero_reasks(monkeypatch, tmp_path):
    """The exact zaum payload that killed a 5h36m run (issue #88): the model
    answers empirical_scope in the `{'value': ..., 'country': ...}` dialect.
    Must parse cleanly on the first response -- zero re-asks needed -- and
    the record carries both empirical_scope and country."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path, country_list=("East Timor",))
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": {"value": "scope:country-case", "country": "East Timor"},
                }
            )

    client = _CountingClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["empirical_scope"] == "scope:country-case"
    assert records[0]["country"] == "East Timor"
    assert client.call_count == 1


def test_run_tag_value_as_key_dialect_carries_scope_and_country_with_zero_reasks(
    monkeypatch, tmp_path
):
    """The other modal dialect (issue #88 point 3): the axis value's dict has
    exactly one non-auxiliary entry, keyed by the tag value itself."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_run_chunk(monkeypatch, tag_mod)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": {
                        "scope:country-case": "scope:country-case",
                        "country": "Syria",
                    },
                }
            )

    client = _CountingClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["empirical_scope"] == "scope:country-case"
    assert records[0]["country"] == "Syria"
    assert client.call_count == 1


def test_run_tag_two_candidate_object_dialect_still_errors(monkeypatch, tmp_path):
    """A genuine multi-candidate object is never a silent pick -- it stays a
    (re-askable) TagParseError, and since it never resolves cleanly within
    complete_json's bounded budget, run_tag ultimately raises."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    class _AlwaysAmbiguousClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps({"role_in_argument": {"a": "role:claim", "b": "role:claim"}})

    client = _AlwaysAmbiguousClient()

    with pytest.raises(tag_mod.TagParseError):
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert client.call_count == 3


def test_run_tag_reasks_and_succeeds_when_value_key_extracted_value_is_first_empty_string(
    monkeypatch, tmp_path
):
    """The #85 degenerate-response re-ask composes automatically with the
    widened extraction paths: an empty string extracted via the 'value' key
    still routes through `reject_degenerate_tag_values` and re-asks rather
    than failing schema validation on ''."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "run_chunk",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    degenerate = json.dumps({"role_in_argument": {"value": ""}})
    clean = json.dumps({"role_in_argument": {"value": "role:claim"}})

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, clean]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert client.call_count == 2


def test_default_domain_dir_returns_configured_path_when_present(tmp_path):
    """`_default_domain_dir` reads `paths.domain_dir` from `config/
    pipeline.yaml` (mirrors `axial.envelope._default_envelopes_dir`'s own
    `paths.envelopes_dir` behavior) -- issue #38."""
    import axial.tag as tag_mod

    configured_dir = tmp_path / "configured-domain"
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        f"paths:\n  domain_dir: {configured_dir.as_posix()}\n",
        encoding="utf-8",
    )

    assert tag_mod._default_domain_dir(config_path) == configured_dir


def test_default_domain_dir_falls_back_to_syria_when_key_absent(tmp_path):
    """An absent `paths.domain_dir` key (other `paths:` keys present) falls
    back to `DEFAULT_DOMAIN_DIR` (config/domains/syria) -- issue #38."""
    import axial.tag as tag_mod

    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "paths:\n  envelopes_dir: some/other/dir\n",
        encoding="utf-8",
    )

    assert tag_mod._default_domain_dir(config_path) == tag_mod.DEFAULT_DOMAIN_DIR


def test_default_domain_dir_falls_back_to_syria_when_config_file_absent(tmp_path):
    """A nonexistent config_path also falls back to `DEFAULT_DOMAIN_DIR`,
    never raising -- issue #38."""
    import axial.tag as tag_mod

    config_path = tmp_path / "does-not-exist.yaml"

    assert tag_mod._default_domain_dir(config_path) == tag_mod.DEFAULT_DOMAIN_DIR
