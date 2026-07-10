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


# --- raw control characters inside JSON strings (issue #72 follow-up) -------


def test_parse_model_json_accepts_raw_control_characters_inside_a_string_value():
    """A live model emitted a literal newline/tab inside a JSON string value
    (strict json.loads rejects this as an "Invalid control character").
    That's an unambiguous literal-newline-in-text intent, not malformed
    JSON, so it must parse and preserve the raw characters."""
    from axial.model_json import parse_model_json

    raw = '{"text": "line one\nline two\ttabbed"}'

    assert parse_model_json(raw) == {"text": "line one\nline two\ttabbed"}


def test_parse_model_json_accepts_raw_control_characters_inside_a_fenced_json_string():
    from axial.model_json import parse_model_json

    inner = '{"text": "line one\nline two\ttabbed"}'
    raw = f"```json\n{inner}\n```"

    assert parse_model_json(raw) == {"text": "line one\nline two\ttabbed"}


def test_parse_model_json_still_raises_on_genuinely_broken_json_with_snippet():
    from axial.model_json import ModelJsonError, parse_model_json

    raw = '{"text": "unterminated string with a raw\nnewline in it'

    with pytest.raises(ModelJsonError) as exc_info:
        parse_model_json(raw)

    # the snippet is a `repr()` of raw, so a raw embedded newline shows up
    # escaped (`\n`) rather than literal -- assert on the repr, not `raw`
    # itself, and confirm the decode error is still surfaced.
    assert repr(raw) in str(exc_info.value)
    assert "Unterminated string" in str(exc_info.value)


# --- complete_json: bounded re-ask on complete-but-unparseable JSON (#76) ---


class _ScriptedClient:
    """Stub `LLMClient` whose `.complete()` returns a scripted sequence of
    responses, one per call, mirroring `_CapturingClient`/`_Client` fakes
    used across the pass-level test modules (test_chunk.py, test_tag.py,
    etc.)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def complete(self, prompt, pass_name=None):
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


def test_complete_json_returns_raw_text_after_one_valid_completion():
    from axial.model_json import complete_json

    valid = json.dumps({"a": 1})
    client = _ScriptedClient([valid])

    raw = complete_json(client, "prompt")

    assert raw == valid
    assert client.call_count == 1


def test_complete_json_reasks_once_on_malformed_then_succeeds():
    from axial.model_json import complete_json

    valid = json.dumps({"a": 1})
    client = _ScriptedClient(["not json at all", valid])

    raw = complete_json(client, "prompt")

    assert raw == valid
    assert client.call_count == 2


def test_complete_json_raises_model_json_error_with_snippet_after_all_attempts():
    from axial.model_json import ModelJsonError, complete_json

    garbage = "still not json"
    client = _ScriptedClient([garbage, garbage, garbage, garbage])

    with pytest.raises(ModelJsonError) as exc_info:
        complete_json(client, "prompt")

    assert client.call_count == 3
    assert garbage in str(exc_info.value)


def test_complete_json_rejects_attempts_less_than_one_without_calling_the_client():
    from axial.model_json import complete_json

    client = _ScriptedClient([])

    with pytest.raises(ValueError):
        complete_json(client, "prompt", attempts=0)

    assert client.call_count == 0


# --- complete_json: optional `validate` callback (issue #80) ---------------


def test_complete_json_reasks_once_when_validate_rejects_then_accepts():
    from axial.model_json import complete_json

    degenerate = json.dumps({"a": ""})
    clean = json.dumps({"a": 1})
    client = _ScriptedClient([degenerate, clean])

    def validate(raw):
        data = json.loads(raw)
        if data.get("a") == "":
            raise ValueError("degenerate 'a'")

    raw = complete_json(client, "prompt", validate=validate)

    assert raw == clean
    assert client.call_count == 2


def test_complete_json_raises_validators_exception_after_all_attempts():
    from axial.model_json import complete_json

    degenerate = json.dumps({"a": ""})
    client = _ScriptedClient([degenerate, degenerate, degenerate, degenerate])

    class _Degenerate(ValueError):
        pass

    def validate(raw):
        raise _Degenerate("always degenerate")

    with pytest.raises(_Degenerate):
        complete_json(client, "prompt", validate=validate)

    assert client.call_count == 3


def test_complete_json_never_calls_validate_when_json_itself_is_invalid():
    from axial.model_json import ModelJsonError, complete_json

    garbage = "not json at all"
    client = _ScriptedClient([garbage, garbage, garbage])

    calls = []

    def validate(raw):
        calls.append(raw)

    with pytest.raises(ModelJsonError):
        complete_json(client, "prompt", validate=validate)

    assert client.call_count == 3
    assert calls == []


def test_complete_json_returns_raw_after_one_valid_completion_with_validate_passing():
    from axial.model_json import complete_json

    valid = json.dumps({"a": 1})
    client = _ScriptedClient([valid])

    calls = []

    def validate(raw):
        calls.append(raw)

    raw = complete_json(client, "prompt", validate=validate)

    assert raw == valid
    assert client.call_count == 1
    assert calls == [valid]


# --- invalid-escape repair (issue #100) --------------------------------------


def test_parse_model_json_repairs_an_invalid_python_style_apostrophe_escape():
    from axial.model_json import parse_model_json

    raw = '{"text": "ra\\\'is"}'  # literal bytes: ra BACKSLASH ' is

    assert parse_model_json(raw) == {"text": "ra'is"}


def test_parse_model_json_repairs_an_invalid_escape_of_an_arbitrary_letter():
    from axial.model_json import parse_model_json

    raw = '{"text": "a\\qb"}'  # literal bytes: a BACKSLASH q b

    assert parse_model_json(raw) == {"text": "aqb"}


def test_parse_model_json_leaves_an_escaped_backslash_followed_by_apostrophe_untouched():
    """`\\\\'` is TWO tokens -- a legal escaped backslash, then a literal
    apostrophe -- not an invalid `\\'` pair. The scanner must consume the
    escape pair first, left to right, so it never misreads the apostrophe as
    part of the backslash's escape."""
    from axial.model_json import parse_model_json

    raw = '{"text": "ra\\\\\'is"}'  # literal bytes: ra BACKSLASH BACKSLASH ' is

    assert parse_model_json(raw) == {"text": "ra\\'is"}


def test_parse_model_json_leaves_u_escapes_untouched():
    from axial.model_json import parse_model_json

    raw = '{"text": "caf\\u00e9"}'

    assert parse_model_json(raw) == {"text": "café"}


@pytest.mark.parametrize(
    "payload",
    [
        {"a": 1},
        {"text": 'quote " backslash \\ newline \n tab \t and café'},
        {"chunks": [{"text": "one"}, {"text": "two"}]},
        {"nested": {"list": [1, 2, {"k": "v\\ended"}]}},
    ],
)
def test_parse_model_json_is_a_no_op_on_already_valid_json(payload):
    from axial.model_json import parse_model_json

    raw = json.dumps(payload, ensure_ascii=False)

    assert parse_model_json(raw) == payload


def test_parse_model_json_still_raises_on_truncated_json_with_an_invalid_escape():
    from axial.model_json import ModelJsonError, parse_model_json

    raw = '{"text": "ra\\\'is starts here but the object never clos'

    with pytest.raises(ModelJsonError):
        parse_model_json(raw)


def test_complete_json_passes_pass_name_through_to_every_completion():
    from axial.model_json import complete_json

    valid = json.dumps({"a": 1})
    client = _ScriptedClient(["not json", valid])

    calls = []
    original_complete = client.complete

    def _tracking_complete(prompt, pass_name=None):
        calls.append(pass_name)
        return original_complete(prompt, pass_name=pass_name)

    client.complete = _tracking_complete

    complete_json(client, "prompt", pass_name="chunk")

    assert calls == ["chunk", "chunk"]
