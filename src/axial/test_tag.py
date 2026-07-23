"""Inner unit tests for the axial tag module (issue #27 slice 01 -- tag
spine: role_in_argument, schema-driven, hard-error, versioned; issue #28
slice 02 -- empirical_scope axis + the scope:country-case polity extra
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

_SCHEMA_WITH_POLITY = Schema(
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
    polity_examples=["Syria", "Turkey"],
)

_SCHEMA_WITH_POLITIES_TOUCHED = Schema(
    version="0.1",
    axes={
        "polities_touched": Axis(
            name="polities_touched",
            applies_to=["prose"],
            cardinality="many",
            value_count=0,
            tag_ids=set(),
            raw={"cardinality": "many", "values": "free_text"},
        ),
    },
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


# --- compose_multi_axis_tag_prompt: polity examples-not-menu framing +
# polities_touched facet description (issue #194 slice 05) --------------


def test_compose_multi_axis_tag_prompt_surfaces_polity_examples():
    from axial.tag import compose_multi_axis_tag_prompt

    prompt = compose_multi_axis_tag_prompt(
        "Some chunk text.",
        ["role_in_argument"],
        _CODEBOOK,
        _SCHEMA,
        polity_examples=["Syria", "Turkey"],
    )

    assert "Syria" in prompt
    assert "Turkey" in prompt


def test_compose_multi_axis_tag_prompt_frames_polity_examples_as_not_a_closed_menu():
    """Item 1 of issue #194 slice 05: the polity list is examples, not a
    closed menu -- the tagger is instructed to name the true polity
    faithfully even when absent, historical, defunct, or supra-national."""
    from axial.tag import compose_multi_axis_tag_prompt

    prompt = compose_multi_axis_tag_prompt(
        "Some chunk text.",
        ["role_in_argument"],
        _CODEBOOK,
        _SCHEMA,
        polity_examples=["Syria", "Turkey"],
    )

    assert "not a closed menu" in prompt
    assert "polity" in prompt
    assert "historical" in prompt
    assert "supra-national" in prompt


def test_compose_multi_axis_tag_prompt_still_accepts_zero_polity_examples():
    from axial.tag import compose_multi_axis_tag_prompt

    prompt = compose_multi_axis_tag_prompt(
        "Some chunk text.", ["role_in_argument"], _CODEBOOK, _SCHEMA, polity_examples=None
    )

    assert "Some chunk text." in prompt


def test_compose_multi_axis_tag_prompt_describes_polities_touched_as_many_valued_free_text():
    """The `polities_touched` axis (cardinality: many) gets a free-text
    facet description -- "engaged, not name-dropped" -- rather than a
    vocabulary listing, dispatched on its cardinality, never its name."""
    from axial.tag import compose_multi_axis_tag_prompt

    prompt = compose_multi_axis_tag_prompt(
        "Some chunk text.",
        ["polities_touched"],
        _CODEBOOK,
        _SCHEMA_WITH_POLITIES_TOUCHED,
    )

    assert "polities_touched" in prompt
    assert "engaged" in prompt
    assert "name-dropped" in prompt


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

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case", "polity": "Syria"}})

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
    """`{'value': <str>, 'polity': ...}` -- deepseek-v4-flash's modal dialect
    for scope:country-case chunks (issue #88 point 2)."""
    from axial.tag import parse_tag_response

    raw = json.dumps({"empirical_scope": {"value": "scope:country-case", "polity": "Syria"}})

    value = parse_tag_response(raw, "empirical_scope")

    assert value == "scope:country-case"


def test_parse_tag_response_accepts_the_value_as_key_dialect():
    """`{'scope:country-case': 'scope:country-case', 'polity': ...}` -- the
    other modal dialect (issue #88 point 3): exactly one remaining entry
    (after excluding 'polity'/'secondary'/'subtags') with a string value."""
    from axial.tag import parse_tag_response

    raw = json.dumps(
        {"empirical_scope": {"scope:country-case": "scope:country-case", "polity": "Syria"}}
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

    raw = json.dumps({"empirical_scope": {"polity": "Syria", "secondary": []}})

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


# --- axis-prefixed value normalization (issue #96) --------------------------


def test_validate_tag_normalizes_axis_prefixed_value_when_suffix_in_vocab():
    """`field:ideology` -- the field axis's own name prefixed onto its real
    'ideology' value -- normalizes to 'ideology' instead of raising."""
    from axial.tag import validate_tag

    result = validate_tag(_SCHEMA, "field", "field:ideology")

    assert result == "ideology"


def test_validate_tag_still_rejects_prefixed_but_out_of_vocab_value():
    """`field:ethnicity` carries the field-axis-name prefix, but 'ethnicity'
    is not a real field value either -- normalization must not rescue it."""
    from axial.tag import TagNotInSchemaError, validate_tag

    with pytest.raises(TagNotInSchemaError) as exc_info:
        validate_tag(_SCHEMA, "field", "field:ethnicity")

    message = str(exc_info.value)
    assert "field" in message
    assert "field:ethnicity" in message


def test_validate_tag_still_rejects_bare_out_of_vocab_value():
    """A bare out-of-vocab value with no prefix at all is unaffected by the
    new normalization and still raises."""
    from axial.tag import TagNotInSchemaError, validate_tag

    with pytest.raises(TagNotInSchemaError) as exc_info:
        validate_tag(_SCHEMA, "field", "ethnicity")

    message = str(exc_info.value)
    assert "field" in message
    assert "ethnicity" in message


def test_validate_tag_does_not_touch_an_axis_whose_own_vocabulary_is_prefixed():
    """`role_in_argument`'s own vocabulary is itself prefix-shaped
    (`role:*`); its real value `role:setup` is already in-vocabulary, so
    normalization never even fires (the first condition, 'raw value NOT in
    vocabulary', is false) and the value survives verbatim."""
    from axial.tag import validate_tag

    result = validate_tag(_SCHEMA, "role_in_argument", "role:setup")

    assert result == "role:setup"


def test_validate_tag_non_string_value_is_unaffected_and_still_rejected():
    """A non-string value can never carry a `'<axis_name>:'` prefix, so
    normalization is a no-op (and must not raise e.g. AttributeError trying
    string operations on it) -- it still fails schema validation as before."""
    from axial.tag import TagNotInSchemaError, validate_tag

    with pytest.raises(TagNotInSchemaError) as exc_info:
        validate_tag(_SCHEMA, "field", 123)

    assert "123" in str(exc_info.value)


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


def test_parse_multi_value_tag_response_coerces_bare_string_to_primary_for_optional_secondary_axis():
    """Issue #105: a bare string for a `primary_plus_optional_secondary`
    axis (e.g. `{"theory_school": "bellicist"}`) is coerced to
    `{"primary": "bellicist"}` before the shape check, rather than rejected
    as a shape error."""
    from axial.tag import parse_multi_value_tag_response

    raw = json.dumps({"theory_school": "bellicist"})

    parsed = parse_multi_value_tag_response(
        raw, _SCHEMA_WITH_MULTI_VALUE_AXES.axes["theory_school"]
    )

    assert parsed == {"primary": "bellicist", "secondary": None}


def test_parse_multi_value_tag_response_still_rejects_a_bare_scalar_for_primary_plus_secondary_axis():
    """Issue #105 scope guard: the bare-string coercion is limited to
    `primary_plus_optional_secondary` axes -- a bare string for a
    `primary_plus_secondary` axis (e.g. `field`, which always requires a
    `secondary` list) is still a genuine shape error, never coerced."""
    from axial.tag import TagParseError, parse_multi_value_tag_response

    with pytest.raises(TagParseError):
        parse_multi_value_tag_response(
            json.dumps({"field": "state"}), _SCHEMA_WITH_MULTI_VALUE_AXES.axes["field"]
        )


def test_parse_multi_value_tag_response_bare_string_coercion_feeds_vocab_validation():
    """Issue #105: coercion runs BEFORE vocabulary validation, never
    bypasses it -- an in-vocab bare string validates cleanly with that value
    as `primary`, while an out-of-vocab bare string is coerced to shape but
    still raises `TagNotInSchemaError` (which drives the existing #102
    correction re-ask upstream in `run_tag`, not tested here)."""
    from axial.tag import (
        TagNotInSchemaError,
        parse_multi_value_tag_response,
        validate_multi_value_tag,
    )

    axis = _SCHEMA_WITH_MULTI_VALUE_AXES.axes["theory_school"]

    in_vocab_parsed = parse_multi_value_tag_response(
        json.dumps({"theory_school": "bellicist"}), axis
    )
    validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "theory_school", in_vocab_parsed)
    assert in_vocab_parsed["primary"] == "bellicist"

    out_of_vocab_parsed = parse_multi_value_tag_response(
        json.dumps({"theory_school": "not-a-real-theory-school"}), axis
    )
    with pytest.raises(TagNotInSchemaError):
        validate_multi_value_tag(
            _SCHEMA_WITH_MULTI_VALUE_AXES, "theory_school", out_of_vocab_parsed
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


def test_validate_multi_value_tag_normalizes_a_prefixed_primary_in_place():
    """`validate_multi_value_tag` mutates `parsed["primary"]` to the
    normalized suffix (issue #96), so callers reading `parsed` afterward
    (both `run_tag` and `axial.artifacts`) see the normalized value."""
    from axial.tag import validate_multi_value_tag

    parsed = {"primary": "field:ideology", "secondary": []}
    validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "field", parsed)

    assert parsed["primary"] == "ideology"


def test_validate_multi_value_tag_normalizes_prefixed_secondary_entries_in_place():
    """Each `secondary` list entry is normalized the same way as `primary`."""
    from axial.tag import validate_multi_value_tag

    parsed = {"primary": "state", "secondary": ["field:ideology", "violence"]}
    validate_multi_value_tag(_SCHEMA_WITH_MULTI_VALUE_AXES, "field", parsed)

    assert parsed["secondary"] == ["ideology", "violence"]


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


# --- polity-case extra field (issue #28 slice 02) --------------------------


def test_parse_polity_response_returns_the_polity():
    from axial.tag import parse_polity_response

    raw = json.dumps({"empirical_scope": "scope:country-case", "polity": "Syria"})

    assert parse_polity_response(raw) == "Syria"


def test_parse_polity_response_rejects_a_missing_polity_key():
    from axial.tag import CountryCaseMissingPolityError, parse_polity_response

    raw = json.dumps({"empirical_scope": "scope:country-case"})

    with pytest.raises(CountryCaseMissingPolityError):
        parse_polity_response(raw)


def test_parse_polity_response_rejects_an_empty_polity_value():
    from axial.tag import CountryCaseMissingPolityError, parse_polity_response

    raw = json.dumps({"empirical_scope": "scope:country-case", "polity": ""})

    with pytest.raises(CountryCaseMissingPolityError):
        parse_polity_response(raw)


def test_parse_polity_response_accepts_a_nested_polity_when_top_level_absent():
    from axial.tag import parse_polity_response

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case", "polity": "Syria"}})

    assert parse_polity_response(raw, "empirical_scope") == "Syria"


def test_parse_polity_response_prefers_the_top_level_polity_over_a_nested_one():
    from axial.tag import parse_polity_response

    raw = json.dumps(
        {
            "empirical_scope": {"primary": "scope:country-case", "polity": "Iraq"},
            "polity": "Syria",
        }
    )

    assert parse_polity_response(raw, "empirical_scope") == "Syria"


def test_parse_polity_response_rejects_missing_polity_in_both_places():
    from axial.tag import CountryCaseMissingPolityError, parse_polity_response

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case"}})

    with pytest.raises(CountryCaseMissingPolityError):
        parse_polity_response(raw, "empirical_scope")


def test_parse_polity_response_rejects_a_non_string_nested_polity():
    from axial.tag import TagParseError, parse_polity_response

    raw = json.dumps({"empirical_scope": {"primary": "scope:country-case", "polity": 7}})

    with pytest.raises(TagParseError):
        parse_polity_response(raw, "empirical_scope")


def test_parse_polity_response_accepts_a_nested_polity_with_the_value_key_dialect():
    """`parse_polity_response` reads `data[axis_name]['polity']` regardless
    of how the axis's own value was extracted -- confirms the nested-polity
    fallback composes with the 'value' key dialect (issue #88)."""
    from axial.tag import parse_polity_response

    raw = json.dumps({"empirical_scope": {"value": "scope:country-case", "polity": "Syria"}})

    assert parse_polity_response(raw, "empirical_scope") == "Syria"


def test_parse_polity_response_accepts_a_nested_polity_with_the_value_as_key_dialect():
    """Same, for the value-as-key dialect (issue #88)."""
    from axial.tag import parse_polity_response

    raw = json.dumps(
        {"empirical_scope": {"scope:country-case": "scope:country-case", "polity": "Syria"}}
    )

    assert parse_polity_response(raw, "empirical_scope") == "Syria"


def test_log_polity_not_in_list_is_silent_for_an_in_list_value(capsys):
    from axial.tag import log_polity_not_in_list

    log_polity_not_in_list(_SCHEMA_WITH_POLITY, "Syria")  # does not raise

    captured = capsys.readouterr()
    assert captured.err == ""


def test_log_polity_not_in_list_logs_an_out_of_list_value_to_stderr(capsys):
    from axial.tag import log_polity_not_in_list

    log_polity_not_in_list(_SCHEMA_WITH_POLITY, "Atlantis")  # does not raise

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Atlantis" in captured.err
    assert "polity_examples" in captured.err


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
    assert "polity" not in record


def test_build_tagged_record_carries_empirical_scope_and_polity_when_given():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "id1", "section": "Introduction", "text": "x"}

    record = build_tagged_record(
        chunk_record,
        "role:claim",
        "0.1",
        empirical_scope="scope:country-case",
        polity="Syria",
    )

    assert record["empirical_scope"] == "scope:country-case"
    assert record["polity"] == "Syria"


def test_build_tagged_record_omits_polity_when_not_given():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "id1", "section": "Introduction", "text": "x"}

    record = build_tagged_record(chunk_record, "role:claim", "0.1", empirical_scope="scope:general")

    assert record["empirical_scope"] == "scope:general"
    assert "polity" not in record


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


def test_build_tagged_record_adds_one_key_per_many_valued_axis():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "id1", "section": "Introduction", "text": "x"}

    record = build_tagged_record(
        chunk_record,
        "role:claim",
        "0.1",
        many_valued_axes={"polities_touched": ["Syria", "Iraq"]},
    )

    assert record["polities_touched"] == ["Syria", "Iraq"]


def test_build_tagged_record_omits_many_valued_axis_when_not_given():
    from axial.tag import build_tagged_record

    chunk_record = {"chunk_id": "id1", "section": "Introduction", "text": "x"}

    record = build_tagged_record(chunk_record, "role:claim", "0.1")

    assert "polities_touched" not in record


# --- polities_touched: many-valued free-text axis parsing (issue #194
# slice 05, Appendix C/G) -----------------------------------------------


def test_parse_many_valued_tag_response_returns_the_given_list():
    from axial.tag import parse_many_valued_tag_response

    raw = json.dumps({"polities_touched": ["Syria", "Iraq"]})

    assert parse_many_valued_tag_response(raw, "polities_touched") == ["Syria", "Iraq"]


def test_parse_many_valued_tag_response_returns_empty_list_when_key_absent():
    """An absent key is `[]`, not a parse error -- a chunk may substantively
    engage no polity at all (Appendix C's own "empty is allowed" rule)."""
    from axial.tag import parse_many_valued_tag_response

    raw = json.dumps({"role_in_argument": "role:claim"})

    assert parse_many_valued_tag_response(raw, "polities_touched") == []


def test_parse_many_valued_tag_response_accepts_an_explicit_empty_list():
    from axial.tag import parse_many_valued_tag_response

    raw = json.dumps({"polities_touched": []})

    assert parse_many_valued_tag_response(raw, "polities_touched") == []


def test_parse_many_valued_tag_response_rejects_invalid_json():
    from axial.tag import TagParseError, parse_many_valued_tag_response

    with pytest.raises(TagParseError):
        parse_many_valued_tag_response("not json at all", "polities_touched")


def test_parse_many_valued_tag_response_rejects_a_non_list_value():
    from axial.tag import TagParseError, parse_many_valued_tag_response

    raw = json.dumps({"polities_touched": "Syria"})

    with pytest.raises(TagParseError):
        parse_many_valued_tag_response(raw, "polities_touched")


def test_parse_many_valued_tag_response_rejects_a_non_string_entry():
    from axial.tag import TagParseError, parse_many_valued_tag_response

    raw = json.dumps({"polities_touched": ["Syria", 7]})

    with pytest.raises(TagParseError):
        parse_many_valued_tag_response(raw, "polities_touched")


def test_parse_many_valued_tag_response_never_applies_a_vocabulary_check():
    """No `TagNotInSchemaError` -- or any error at all -- for a value that
    would be out-of-vocabulary on a closed-set axis: `polities_touched` has
    no controlled vocabulary (`values: free_text`)."""
    from axial.tag import parse_many_valued_tag_response

    raw = json.dumps({"polities_touched": ["Ottoman Empire", "Atlantis"]})

    assert parse_many_valued_tag_response(raw, "polities_touched") == [
        "Ottoman Empire",
        "Atlantis",
    ]


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
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: [])

    stub_client = StubLLMClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=stub_client, domain_dir=domain_dir, votes=1
    )

    assert records == []
    assert stub_client.call_count == 0


def test_run_tag_produces_one_record_per_chunk_with_role_and_schema_version(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path)
    chunk_records = [
        {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"},
        {"chunk_id": "src_1_intro_002", "section": "Introduction", "text": "chunk two"},
    ]
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: chunk_records)

    stub_client = StubLLMClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=stub_client, domain_dir=domain_dir, votes=1
    )

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
        "read_chunks",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    calls = []

    class _CapturingClient:
        def complete(self, prompt, pass_name=None):
            calls.append(pass_name)
            return json.dumps({"role_in_argument": "role:claim"})

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    tag_mod.run_tag(
        tmp_path / "paper.pdf", client=_CapturingClient(), domain_dir=domain_dir, votes=1
    )

    assert calls == [TAG_PASS_NAME]


def test_run_tag_raises_a_hard_error_for_an_out_of_schema_tag(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "read_chunks",
        lambda *args, **kwargs: [
            {"chunk_id": "src_1_intro_001", "section": "Introduction", "text": "chunk one"}
        ],
    )

    class _OutOfSchemaClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps({"role_in_argument": "role:not-a-real-tag"})

    with pytest.raises(tag_mod.TagNotInSchemaError):
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(
            tmp_path / "paper.pdf", client=_OutOfSchemaClient(), domain_dir=domain_dir, votes=1
        )


# --- run_tag: empirical_scope + polity-case extra field (issue #28 slice 02) --


def _write_domain_with_empirical_scope(
    tmp_path, polity_examples: tuple[str, ...] = ("Syria", "Turkey")
):
    """Write a minimal schema.yaml + codebook.yaml covering both
    role_in_argument and empirical_scope (with a polity_examples), for
    `run_tag` polity-case unit tests."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    polities_block = ", ".join(polity_examples)
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
        f"polity_examples: [{polities_block}]\n",
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


def _one_chunk_read_chunks(monkeypatch, tag_mod):
    monkeypatch.setattr(
        tag_mod,
        "read_chunks",
        lambda *args, **kwargs: [
            {"chunk_id": "c1", "section": "Introduction", "text": "chunk one"}
        ],
    )


def test_run_tag_polity_case_record_carries_empirical_scope_and_polity(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": "scope:country-case",
                    "polity": "Syria",
                }
            )

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1
    )

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert records[0]["empirical_scope"] == "scope:country-case"
    assert records[0]["polity"] == "Syria"


def test_run_tag_non_polity_case_record_carries_no_polity(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:general"}
            )

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1
    )

    assert records[0]["empirical_scope"] == "scope:general"
    assert "polity" not in records[0]


def test_run_tag_polity_case_missing_polity_raises_hard_error(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:country-case"}
            )

    with pytest.raises(tag_mod.CountryCaseMissingPolityError):
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1)


def test_run_tag_polity_case_out_of_list_polity_is_accepted_and_logged(
    monkeypatch, tmp_path, capsys
):
    """Spec-drift #77 (adjudicated 2026-07-10): an out-of-list polity is
    no longer fatal -- it is accepted verbatim on the record and logged to
    stderr as a candidate addition, naming the value and 'polity_examples'."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": "scope:country-case",
                    "polity": "Atlantis",
                }
            )

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1
    )

    assert records[0]["polity"] == "Atlantis"

    captured = capsys.readouterr()
    assert "Atlantis" in captured.err
    assert "polity_examples" in captured.err


def test_run_tag_polity_case_missing_polity_then_clean_reasks_and_succeeds(monkeypatch, tmp_path):
    """A polity-case response missing `polity` is degenerate model noise
    (issue #92), the same species as a blank tag (#85/#80): it re-asks
    within `complete_json`'s bounded budget rather than dying fatally, and a
    clean follow-up response succeeds after exactly one re-ask."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    missing_polity = json.dumps(
        {"role_in_argument": "role:claim", "empirical_scope": "scope:country-case"}
    )
    clean = json.dumps(
        {
            "role_in_argument": "role:claim",
            "empirical_scope": "scope:country-case",
            "polity": "Syria",
        }
    )

    class _ScriptedClient:
        def __init__(self):
            self._responses = [missing_polity, clean]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["empirical_scope"] == "scope:country-case"
    assert records[0]["polity"] == "Syria"
    assert client.call_count == 2


def test_run_tag_polity_case_persistent_missing_polity_raises_after_three_attempts(
    monkeypatch, tmp_path
):
    """PERSISTENT polity absence (#77 adjudication) stays a hard error: once
    `complete_json`'s bounded re-ask budget (3 attempts) is exhausted, the
    final attempt's `CountryCaseMissingPolityError` propagates unchanged."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:country-case"}
            )

    client = _CountingClient()

    with pytest.raises(tag_mod.CountryCaseMissingPolityError):
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert client.call_count == 3


def test_run_tag_polity_case_polity_present_makes_exactly_one_call(monkeypatch, tmp_path):
    """A polity-case response WITH a non-empty polity never re-asks -- the
    new validator check is a no-op on the already-valid, common case."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": "scope:country-case",
                    "polity": "Syria",
                }
            )

    client = _CountingClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert records[0]["polity"] == "Syria"
    assert client.call_count == 1


def test_run_tag_non_polity_case_scope_with_no_polity_is_unaffected(monkeypatch, tmp_path):
    """A non-polity-case `empirical_scope` (e.g. `scope:general`) never
    requires `polity` at all -- the new check is scoped strictly to
    `scope:country-case` and never fires for any other scope value, so this
    still makes exactly one call."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:general"}
            )

    client = _CountingClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert records[0]["empirical_scope"] == "scope:general"
    assert "polity" not in records[0]
    assert client.call_count == 1


def test_run_tag_makes_exactly_one_llm_call_per_chunk_even_with_two_tagged_axes(
    monkeypatch, tmp_path
):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    calls = []

    class _Client:
        def complete(self, prompt, pass_name=None):
            calls.append(pass_name)
            return json.dumps(
                {"role_in_argument": "role:claim", "empirical_scope": "scope:general"}
            )

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1)

    assert calls == [TAG_PASS_NAME]


def test_run_tag_regresses_role_in_argument_when_empirical_scope_axis_absent(monkeypatch, tmp_path):
    """A domain that doesn't declare empirical_scope (e.g. slice 01's
    minimal fixture domain) must still tag role_in_argument alone, with no
    empirical_scope/polity keys added and no error for the axis the schema
    doesn't define."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    stub_client = StubLLMClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=stub_client, domain_dir=domain_dir, votes=1
    )

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert "empirical_scope" not in records[0]
    assert "polity" not in records[0]


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
    _one_chunk_read_chunks(monkeypatch, tag_mod)

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

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1
    )

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
    _one_chunk_read_chunks(monkeypatch, tag_mod)

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
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1)

    message = str(exc_info.value)
    assert "field" in message
    assert "not-a-real-field" in message


def test_run_tag_raises_a_hard_error_for_an_undeclared_claim_type_subtag(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

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
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1)

    message = str(exc_info.value)
    assert "claim_type" in message
    assert "not-a-real-subtag" in message


def test_run_tag_succeeds_when_first_completion_is_malformed_json(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "read_chunks",
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
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert client.call_count == 2


def test_run_tag_raises_tag_parse_error_on_persistently_malformed_json(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "read_chunks",
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
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert client.call_count == 3


# --- run_tag: polities_touched, a many-valued free-text axis (issue #194
# slice 05, Appendix C/G) -----------------------------------------------


def test_polities_touched_axis_is_a_tagged_axis():
    from axial.tag import POLITIES_TOUCHED_AXIS, TAGGED_AXES

    assert POLITIES_TOUCHED_AXIS == "polities_touched"
    assert POLITIES_TOUCHED_AXIS in TAGGED_AXES


def _write_domain_with_polities_touched(tmp_path):
    """Write a minimal schema.yaml + codebook.yaml covering role_in_argument
    plus the many-valued free-text `polities_touched` axis (Appendix G:
    `cardinality: many`, `values: free_text`), for `run_tag` polities_touched
    unit tests."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    (domain_dir / "schema.yaml").write_text(
        "version: 0.1\n"
        "axes:\n"
        "  role_in_argument:\n"
        "    applies_to: [prose]\n"
        "    cardinality: single\n"
        "    values: [role:claim]\n"
        "  polities_touched:\n"
        "    applies_to: [prose]\n"
        "    cardinality: many\n"
        "    values: free_text\n",
        encoding="utf-8",
    )
    (domain_dir / "codebook.yaml").write_text(
        "axes:\n"
        "  role_in_argument:\n"
        "    role:claim: {definition: d, positive_example: p, negative_example: n}\n",
        encoding="utf-8",
    )
    return domain_dir


def test_run_tag_carries_polities_touched_list_verbatim(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_polities_touched(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {"role_in_argument": "role:claim", "polities_touched": ["Syria", "Iraq"]}
            )

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1
    )

    assert len(records) == 1
    assert records[0]["polities_touched"] == ["Syria", "Iraq"]


def test_run_tag_polities_touched_defaults_to_empty_list_when_key_absent(monkeypatch, tmp_path):
    """Appendix C: "empty is allowed" -- a chunk that substantively engages
    no polity gets `[]`, never a missing key or a hard error."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_polities_touched(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _Client:
        def complete(self, prompt, pass_name=None):
            return json.dumps({"role_in_argument": "role:claim"})

    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=_Client(), domain_dir=domain_dir, votes=1
    )

    assert records[0]["polities_touched"] == []


def test_run_tag_polities_touched_never_applies_a_vocabulary_check(monkeypatch, tmp_path):
    """A `polities_touched` entry outside any known example list is accepted
    verbatim with zero re-asks -- no `TagNotInSchemaError`, since the axis
    is free text with no controlled vocabulary at all."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_polities_touched(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {"role_in_argument": "role:claim", "polities_touched": ["Ottoman Empire"]}
            )

    client = _CountingClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert records[0]["polities_touched"] == ["Ottoman Empire"]
    assert client.call_count == 1


def test_run_tag_regresses_role_in_argument_when_polities_touched_axis_absent(
    monkeypatch, tmp_path
):
    """A domain that doesn't declare polities_touched must still tag
    role_in_argument alone, with no polities_touched key added and no error
    for the axis the schema doesn't define."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    stub_client = StubLLMClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(
        tmp_path / "paper.pdf", client=stub_client, domain_dir=domain_dir, votes=1
    )

    assert len(records) == 1
    assert "polities_touched" not in records[0]


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
        "read_chunks",
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
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert client.call_count == 2


def test_run_tag_raises_tag_parse_error_on_persistently_empty_string_primary(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "read_chunks",
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
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert client.call_count == 3


# --- run_tag: TagParseError quarantine when a checkpoint is active
# (issue #325) -----------------------------------------------------------
#
# The two tests above prove `TagParseError` still hard-errors when no
# `tags_dir` is supplied -- untouched by this issue. These mirror them with
# `tags_dir` supplied (checkpoint active): the exact same persistent
# malformation quarantines just the poisoned chunk instead of aborting the
# whole source, exactly like the existing `ContentRefusedError`/
# `ModelJsonError` quarantine (`tests/ingestion/test_tag_quarantine.py`).


def _three_chunk_records() -> list[dict[str, str]]:
    return [
        {
            "chunk_id": f"src_1_body_{i:03d}",
            "section": "Body",
            "text": f"ordinary prose chunk number {i:03d} of 3",
        }
        for i in range(3)
    ]


def _valid_multi_value_response() -> str:
    return json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )


def test_run_tag_quarantines_a_persistently_bare_scalar_field_response(monkeypatch, tmp_path):
    """Real 2026-07-22 failure (`mann-sources-of-social-power-v1`): a
    `primary_plus_secondary` axis (`field`) persistently answered with a
    bare scalar (`'state'`) instead of the required `{"primary": ...,
    "secondary": [...]}` object is a genuine shape error -- the locked
    `test_parse_multi_value_tag_response_still_rejects_a_bare_scalar_for_
    primary_plus_secondary_axis` contract is untouched, this response is
    never coerced. With a checkpoint active, `run_tag` quarantines just
    that chunk and the source completes; every other chunk tags normally."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    chunk_records = _three_chunk_records()
    poisoned_text = chunk_records[1]["text"]
    survivors = [c["chunk_id"] for i, c in enumerate(chunk_records) if i != 1]
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: chunk_records)

    bare_scalar_field = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": "state",
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )

    class _Client:
        def __init__(self):
            self.calls_for_poisoned = 0

        def complete(self, prompt, pass_name=None):
            if poisoned_text in prompt:
                self.calls_for_poisoned += 1
                return bare_scalar_field
            return _valid_multi_value_response()

    client = _Client()
    tags_dir = tmp_path / "data" / "tags"
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")

    result = tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=client,
        domain_dir=domain_dir,
        tags_dir=tags_dir,
        votes=1,
    )

    tagged_ids = [r["chunk_id"] for r in result]
    assert chunk_records[1]["chunk_id"] not in tagged_ids
    assert tagged_ids == survivors
    assert result.quarantine_count == 1
    # complete_json's own bounded retry (reject_degenerate_tag_values as its
    # validate) must run to exhaustion before quarantining -- never a
    # short-circuit on the first bad draw.
    assert client.calls_for_poisoned == 3


def test_run_tag_quarantines_a_persistently_blank_claim_type_secondary_response(
    monkeypatch, tmp_path
):
    """Real 2026-07-22 failure signature: `claim_type.secondary[0] tag value
    is empty/whitespace-only: ''`. With a checkpoint active, `run_tag`
    quarantines just that chunk and the source completes; every other chunk
    tags normally."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    chunk_records = _three_chunk_records()
    poisoned_text = chunk_records[1]["text"]
    survivors = [c["chunk_id"] for i, c in enumerate(chunk_records) if i != 1]
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: chunk_records)

    blank_secondary = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "secondary": [""], "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )

    class _Client:
        def __init__(self):
            self.calls_for_poisoned = 0

        def complete(self, prompt, pass_name=None):
            if poisoned_text in prompt:
                self.calls_for_poisoned += 1
                return blank_secondary
            return _valid_multi_value_response()

    client = _Client()
    tags_dir = tmp_path / "data" / "tags"
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")

    result = tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=client,
        domain_dir=domain_dir,
        tags_dir=tags_dir,
        votes=1,
    )

    tagged_ids = [r["chunk_id"] for r in result]
    assert chunk_records[1]["chunk_id"] not in tagged_ids
    assert tagged_ids == survivors
    assert result.quarantine_count == 1
    assert client.calls_for_poisoned == 3


def test_run_tag_quarantine_log_and_reason_for_a_parse_error(monkeypatch, tmp_path, capsys):
    """The quarantine log line and checkpoint reason for a `TagParseError`
    match the `QUARANTINE_REASON_PARSE_ERROR` constant, exactly mirroring
    the `content_filter`/`malformed_json` quarantine log contract (#120)."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    chunk_records = _three_chunk_records()
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: chunk_records)

    bare_scalar_field = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": "state",
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )

    class _Client:
        def complete(self, prompt, pass_name=None):
            if chunk_records[1]["text"] in prompt:
                return bare_scalar_field
            return _valid_multi_value_response()

    tags_dir = tmp_path / "data" / "tags"
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    source_id = tag_mod.compute_source_id(tmp_path / "paper.pdf")
    checkpoint_path = tag_mod.tags_checkpoint_path(source_id, tags_dir)

    tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=_Client(),
        domain_dir=domain_dir,
        tags_dir=tags_dir,
        votes=1,
    )

    captured = capsys.readouterr()
    poisoned_id = chunk_records[1]["chunk_id"]
    assert (
        f"tag: quarantining chunk {poisoned_id}: {tag_mod.QUARANTINE_REASON_PARSE_ERROR}"
        in captured.err
    )

    checkpoint_records = {
        r["chunk_id"]: r
        for r in (
            json.loads(line) for line in checkpoint_path.read_text(encoding="utf-8").splitlines()
        )
    }
    assert (
        checkpoint_records[poisoned_id]["quarantine_reason"]
        == tag_mod.QUARANTINE_REASON_PARSE_ERROR
    )


# --- run_tag: TagCardinalityError quarantine when a checkpoint is active
# (issue #326) -------------------------------------------------------------
#
# Real production failure (`beshara-origins-of-syrian-nationhood`, 2026-07-22
# live corpus re-tag run): `empirical_scope` (a single-cardinality axis)
# answered with 3 values instead of exactly one, and `TagCardinalityError`
# had no handler anywhere in the votes loop -- it propagated uncaught and
# aborted the whole source after 804/900 chunks were already checkpointed.
# These two tests cover both places `TagCardinalityError` can actually
# surface (traced via `_parse_and_validate_tags`'s and `reject_degenerate_
# tag_values`'s shared use of `parse_tag_response`): `reject_degenerate_tag_
# values` surviving `complete_json`'s own bounded retry budget, and the #102
# correction re-ask's own fresh, unvetted "reply with the FULL JSON object
# again" answer breaking a DIFFERENT axis's cardinality than the one being
# corrected.


def test_run_tag_quarantines_a_persistently_multi_valued_role_in_argument_response(
    monkeypatch, tmp_path
):
    """A single-cardinality axis (`role_in_argument`) persistently answered
    with more than one value is a genuine `TagCardinalityError` --
    `reject_degenerate_tag_values` (this call's own `validate`, run inside
    `complete_json`'s bounded retry budget) raises it exactly like a shape
    error. With a checkpoint active, `run_tag` quarantines just that chunk
    and the source completes; every other chunk tags normally."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    chunk_records = _three_chunk_records()
    poisoned_text = chunk_records[1]["text"]
    survivors = [c["chunk_id"] for i, c in enumerate(chunk_records) if i != 1]
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: chunk_records)

    multi_valued_role = json.dumps(
        {
            "role_in_argument": ["role:claim", "role:claim"],
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )

    class _Client:
        def __init__(self):
            self.calls_for_poisoned = 0

        def complete(self, prompt, pass_name=None):
            if poisoned_text in prompt:
                self.calls_for_poisoned += 1
                return multi_valued_role
            return _valid_multi_value_response()

    client = _Client()
    tags_dir = tmp_path / "data" / "tags"
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    source_id = tag_mod.compute_source_id(tmp_path / "paper.pdf")
    checkpoint_path = tag_mod.tags_checkpoint_path(source_id, tags_dir)

    result = tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=client,
        domain_dir=domain_dir,
        tags_dir=tags_dir,
        votes=1,
    )

    tagged_ids = [r["chunk_id"] for r in result]
    poisoned_id = chunk_records[1]["chunk_id"]
    assert poisoned_id not in tagged_ids
    assert tagged_ids == survivors
    assert result.quarantine_count == 1
    # complete_json's own bounded retry (reject_degenerate_tag_values as its
    # validate) must run to exhaustion before quarantining -- never a
    # short-circuit on the first bad draw.
    assert client.calls_for_poisoned == 3

    checkpoint_records = {
        r["chunk_id"]: r
        for r in (
            json.loads(line) for line in checkpoint_path.read_text(encoding="utf-8").splitlines()
        )
    }
    assert (
        checkpoint_records[poisoned_id]["quarantine_reason"]
        == tag_mod.QUARANTINE_REASON_CARDINALITY_ERROR
    )


def test_run_tag_quarantines_a_cardinality_error_surfaced_by_a_correction_reask(
    monkeypatch, tmp_path
):
    """The #102 correction re-ask's prompt asks the model to "Reply with the
    FULL JSON object again", so a fresh, entirely unvetted answer can break a
    DIFFERENT axis's cardinality than the one the correction targeted --
    exactly the beshara shape: the original response's out-of-vocab `field`
    triggers the re-ask, and the re-ask's own answer breaks
    `role_in_argument`'s single-cardinality instead. With a checkpoint
    active, `run_tag` quarantines just that chunk and the source completes."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    chunk_records = _three_chunk_records()
    poisoned_text = chunk_records[1]["text"]
    survivors = [c["chunk_id"] for i, c in enumerate(chunk_records) if i != 1]
    monkeypatch.setattr(tag_mod, "read_chunks", lambda *args, **kwargs: chunk_records)

    out_of_vocab_field = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "not-a-real-field", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )
    corrected_but_multi_valued_role = json.dumps(
        {
            "role_in_argument": ["role:claim", "role:claim"],
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )

    class _Client:
        def __init__(self):
            self.calls_for_poisoned = 0

        def complete(self, prompt, pass_name=None):
            if poisoned_text not in prompt:
                return _valid_multi_value_response()
            self.calls_for_poisoned += 1
            if "CORRECTION REQUIRED" in prompt:
                return corrected_but_multi_valued_role
            return out_of_vocab_field

    client = _Client()
    tags_dir = tmp_path / "data" / "tags"
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    source_id = tag_mod.compute_source_id(tmp_path / "paper.pdf")
    checkpoint_path = tag_mod.tags_checkpoint_path(source_id, tags_dir)

    result = tag_mod.run_tag(
        tmp_path / "paper.pdf",
        client=client,
        domain_dir=domain_dir,
        tags_dir=tags_dir,
        votes=1,
    )

    tagged_ids = [r["chunk_id"] for r in result]
    poisoned_id = chunk_records[1]["chunk_id"]
    assert poisoned_id not in tagged_ids
    assert tagged_ids == survivors
    assert result.quarantine_count == 1
    # exactly one initial call plus one bounded #102 correction re-ask --
    # never complete_json's own JSON/degeneracy retry budget, since the
    # initial response is well-formed and non-degenerate.
    assert client.calls_for_poisoned == 2

    checkpoint_records = {
        r["chunk_id"]: r
        for r in (
            json.loads(line) for line in checkpoint_path.read_text(encoding="utf-8").splitlines()
        )
    }
    assert (
        checkpoint_records[poisoned_id]["quarantine_reason"]
        == tag_mod.QUARANTINE_REASON_CARDINALITY_ERROR
    )


def test_run_tag_reasks_and_succeeds_when_secondary_entry_is_first_empty_string(
    monkeypatch, tmp_path
):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

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
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["field"] == {"primary": "state", "secondary": ["ideology"]}
    assert client.call_count == 2


def test_run_tag_reasks_and_succeeds_when_subtag_is_first_empty_string(monkeypatch, tmp_path):
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

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
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["claim_type"]["subtags"] == ["formation:bellicist"]
    assert client.call_count == 2


def test_run_tag_reasks_and_succeeds_when_polities_touched_entry_is_first_empty_string(
    monkeypatch, tmp_path
):
    """A blank `polities_touched` entry is the same species of degenerate
    response noise as a blank primary/secondary/subtag (#80) -- it re-asks
    within `complete_json`'s bounded budget rather than failing outright,
    even though the axis itself has no vocabulary to validate against."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_polities_touched(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    degenerate = json.dumps({"role_in_argument": "role:claim", "polities_touched": [""]})
    clean = json.dumps({"role_in_argument": "role:claim", "polities_touched": ["Syria"]})

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, clean]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["polities_touched"] == ["Syria"]
    assert client.call_count == 2


def test_run_tag_out_of_vocab_non_empty_tag_hard_errors_after_one_bounded_reask(
    monkeypatch, tmp_path
):
    """A genuine non-empty out-of-vocabulary tag is NEVER treated as
    degenerate -- but issue #102 (P0-6 refinement) grants it EXACTLY ONE
    bounded correction re-ask (showing the axis's controlled vocabulary)
    before the hard error. A model that stays out-of-vocab on the correction
    re-ask still raises `TagNotInSchemaError`, and the re-ask fired exactly
    once (two client calls: one original ask + one bounded correction), never
    looping further -- distinct from `complete_json`'s 3-attempt JSON/
    degeneracy budget."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "read_chunks",
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
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert client.call_count == 2


# --- run_tag: widened single-axis object dialects (issue #88) ---------------


def test_run_tag_zaum_payload_carries_scope_and_polity_with_zero_reasks(monkeypatch, tmp_path):
    """The exact zaum payload that killed a 5h36m run (issue #88): the model
    answers empirical_scope in the `{'value': ..., 'polity': ...}` dialect.
    Must parse cleanly on the first response -- zero re-asks needed -- and
    the record carries both empirical_scope and polity."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path, polity_examples=("East Timor",))
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {
                    "role_in_argument": "role:claim",
                    "empirical_scope": {"value": "scope:country-case", "polity": "East Timor"},
                }
            )

    client = _CountingClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["empirical_scope"] == "scope:country-case"
    assert records[0]["polity"] == "East Timor"
    assert client.call_count == 1


def test_run_tag_value_as_key_dialect_carries_scope_and_polity_with_zero_reasks(
    monkeypatch, tmp_path
):
    """The other modal dialect (issue #88 point 3): the axis value's dict has
    exactly one non-auxiliary entry, keyed by the tag value itself."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_empirical_scope(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

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
                        "polity": "Syria",
                    },
                }
            )

    client = _CountingClient()
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["empirical_scope"] == "scope:country-case"
    assert records[0]["polity"] == "Syria"
    assert client.call_count == 1


def test_run_tag_two_candidate_object_dialect_still_errors(monkeypatch, tmp_path):
    """A genuine multi-candidate object is never a silent pick -- it stays a
    (re-askable) TagParseError, and since it never resolves cleanly within
    complete_json's bounded budget, run_tag ultimately raises."""
    import axial.tag as tag_mod

    domain_dir = _write_minimal_domain(tmp_path, tag_ids=("role:claim",))
    monkeypatch.setattr(
        tag_mod,
        "read_chunks",
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
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

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
        "read_chunks",
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
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["role_in_argument"] == "role:claim"
    assert client.call_count == 2


# --- run_tag: bounded correction re-ask on out-of-vocab tags (issue #102) ---


class _ScriptedTagClient:
    """A tag-pass client that returns each scripted response in turn, then
    repeats the last one for any further call, counting every call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def complete(self, prompt, pass_name=None):
        response = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return response


def test_run_tag_out_of_vocab_primary_corrects_on_bounded_reask(monkeypatch, tmp_path):
    """An out-of-vocab claim_type primary on the first answer, corrected to a
    genuinely in-vocab primary on the single bounded re-ask, tags the chunk
    with the CORRECTED value and succeeds -- exactly two client calls (issue
    #102)."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    bad = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "not-a-real-claim-type", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )
    good = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-autonomy", "subtags": []},
            "theory_school": {"primary": "bellicist"},
        }
    )

    client = _ScriptedTagClient([bad, good])
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["claim_type"]["primary"] == "state-autonomy"
    assert client.call_count == 2


def test_run_tag_out_of_vocab_subtag_corrects_on_bounded_reask(monkeypatch, tmp_path):
    """An out-of-vocab claim_type subtag on the first answer, corrected to a
    genuinely declared subtag on the single bounded re-ask, tags the chunk
    with the CORRECTED subtag -- never the original bad one (issue #102)."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    bad = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": ["sub:bogus"]},
            "theory_school": {"primary": "bellicist"},
        }
    )
    good = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]},
            "theory_school": {"primary": "bellicist"},
        }
    )

    client = _ScriptedTagClient([bad, good])
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert records[0]["claim_type"]["subtags"] == ["formation:bellicist"]
    assert client.call_count == 2


def test_run_tag_persistent_out_of_vocab_hard_errors_after_exactly_one_reask(monkeypatch, tmp_path):
    """A subtag out-of-vocab on BOTH the original ask and the bounded
    correction re-ask still raises `TagNotInSchemaError` (the P0-6 hard
    error), and the re-ask fired exactly once -- two calls total, never a
    third (issue #102's 'single bounded re-ask')."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    bad = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": ["sub:bogus"]},
            "theory_school": {"primary": "bellicist"},
        }
    )

    client = _ScriptedTagClient([bad])

    with pytest.raises(tag_mod.TagNotInSchemaError) as exc_info:
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert "claim_type" in str(exc_info.value)
    assert "sub:bogus" in str(exc_info.value)
    assert client.call_count == 2


def test_run_tag_correction_reask_that_returns_none_hard_errors(monkeypatch, tmp_path):
    """A correction re-ask whose answer replaces the invalid value with the
    literal `NONE` is a hard error (issue #102 / P0-6: the model must return a
    valid value or NONE, and NONE means the genuine schema gap stands) -- NONE
    is in no axis's vocabulary, so re-validation raises `TagNotInSchemaError`
    after the single bounded re-ask."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    bad = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": ["sub:bogus"]},
            "theory_school": {"primary": "bellicist"},
        }
    )
    none_answer = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": ["NONE"]},
            "theory_school": {"primary": "bellicist"},
        }
    )

    client = _ScriptedTagClient([bad, none_answer])

    with pytest.raises(tag_mod.TagNotInSchemaError):
        (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
        tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert client.call_count == 2


def test_run_tag_in_vocab_first_answer_never_triggers_a_correction_reask(monkeypatch, tmp_path):
    """An already-in-vocab first answer tags immediately, with exactly one
    client call -- the correction path never fires (issue #102: the happy
    path pays no extra cost)."""
    import axial.tag as tag_mod

    domain_dir = _write_domain_with_multi_value_axes(tmp_path)
    _one_chunk_read_chunks(monkeypatch, tag_mod)

    good = json.dumps(
        {
            "role_in_argument": "role:claim",
            "field": {"primary": "state", "secondary": []},
            "claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]},
            "theory_school": {"primary": "bellicist"},
        }
    )

    client = _ScriptedTagClient([good])
    (tmp_path / "paper.pdf").write_bytes(b"fake pdf bytes")
    records = tag_mod.run_tag(tmp_path / "paper.pdf", client=client, domain_dir=domain_dir, votes=1)

    assert len(records) == 1
    assert client.call_count == 1


def test_compose_correction_prompt_shows_the_failing_positions_vocabulary():
    """The bounded correction re-ask prompt names the invalid value, the axis,
    and lists the controlled vocabulary legal for the failing position (issue
    #102) -- for a subtag failure, that primary's own declared subtags, not
    the axis's primary vocabulary."""
    from axial.tag import TagNotInSchemaError, compose_correction_prompt

    exc = TagNotInSchemaError(
        "claim_type",
        "sub:bogus",
        vocabulary={"formation:bellicist", "formation:colonial-import"},
        position="as a subtag of the primary 'state-formation'",
    )

    prompt = compose_correction_prompt("BASE PROMPT BODY", exc)

    assert "BASE PROMPT BODY" in prompt
    assert "sub:bogus" in prompt
    assert "claim_type" in prompt
    assert "formation:bellicist" in prompt
    assert "formation:colonial-import" in prompt
    assert "NONE" in prompt
    assert "state-formation" in prompt


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
