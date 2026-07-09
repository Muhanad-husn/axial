"""Inner unit tests for the shared model-response JSON parser (issue #72 --
tolerate a markdown-fenced completion; quote the raw text on parse errors)."""

from __future__ import annotations

import json

import pytest


# --- plain JSON pass-through -------------------------------------------------


def test_parse_model_json_parses_plain_json_object():
    from axial.model_json import parse_model_json

    raw = json.dumps({"a": 1})

    assert parse_model_json(raw) == {"a": 1}


def test_parse_model_json_parses_plain_json_with_surrounding_whitespace():
    from axial.model_json import parse_model_json

    raw = f"  \n{json.dumps({'a': 1})}\n  "

    assert parse_model_json(raw) == {"a": 1}


# --- fence stripping ---------------------------------------------------------


def test_parse_model_json_strips_a_bare_triple_backtick_fence():
    from axial.model_json import parse_model_json

    raw = f"```\n{json.dumps({'a': 1})}\n```"

    assert parse_model_json(raw) == {"a": 1}


def test_parse_model_json_strips_a_json_tagged_fence():
    from axial.model_json import parse_model_json

    raw = f"```json\n{json.dumps({'a': 1})}\n```"

    assert parse_model_json(raw) == {"a": 1}


def test_parse_model_json_strips_a_fence_with_surrounding_whitespace_and_trailing_newline():
    from axial.model_json import parse_model_json

    raw = f"  \n```json\n{json.dumps({'a': 1})}\n```  \n"

    assert parse_model_json(raw) == {"a": 1}


def test_fenced_and_unfenced_equivalents_parse_identically():
    from axial.model_json import parse_model_json

    payload = {"chunks": [{"text": "a"}, {"text": "b"}]}
    unfenced = json.dumps(payload)
    fenced = f"```json\n{unfenced}\n```"

    assert parse_model_json(fenced) == parse_model_json(unfenced) == payload


# --- error cases --------------------------------------------------------------


def test_parse_model_json_raises_on_prose_refusal_with_snippet_in_message():
    from axial.model_json import ModelJsonError, parse_model_json

    raw = "I cannot produce that classification."

    with pytest.raises(ModelJsonError) as exc_info:
        parse_model_json(raw)

    assert raw in str(exc_info.value)
    assert "Expecting value" in str(exc_info.value)


def test_parse_model_json_truncates_a_long_snippet_with_a_length_note():
    from axial.model_json import ModelJsonError, parse_model_json

    raw = "not json " * 60  # well over 300 chars, still not valid JSON
    assert len(raw) > 300

    with pytest.raises(ModelJsonError) as exc_info:
        parse_model_json(raw)

    message = str(exc_info.value)
    assert raw[:300] in message
    assert raw not in message  # the full (untruncated) text must not appear
    assert str(len(raw)) in message
    assert "truncat" in message.lower()


def test_parse_model_json_raises_when_fenced_content_still_isnt_json():
    from axial.model_json import ModelJsonError, parse_model_json

    raw = "```json\nnot actually json\n```"

    with pytest.raises(ModelJsonError) as exc_info:
        parse_model_json(raw)

    assert "not actually json" in str(exc_info.value)
