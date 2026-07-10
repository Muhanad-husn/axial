"""Inner unit tests for the axial artifacts module (issue #30 slice 01 --
artifact classification)."""

from __future__ import annotations

import json

import pytest

from axial.codebook import Codebook, TagEntry
from axial.llm import ARTIFACTS_PASS_NAME, StubLLMClient
from axial.schema import Axis, Schema


def _tree_with_one_artifact() -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [
                    {"type": "prose", "order": "1.1", "text": "Intro body sentence."},
                    {"type": "artifact", "order": "1.2", "label": "table"},
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Discussion",
                "children": [
                    {"type": "prose", "order": "2.1", "text": "Discussion body sentence."},
                ],
            },
        ]
    }


def _tree_with_no_artifacts() -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [{"type": "prose", "order": "1.1", "text": "Intro body sentence."}],
            }
        ]
    }


_SCHEMA = Schema(
    version="1.0",
    axes={
        "artifact_role": Axis(
            name="artifact_role",
            applies_to=["artifact"],
            cardinality="single",
            value_count=6,
            tag_ids={
                "case-study",
                "framework-illustration",
                "quote-pool",
                "framework",
                "reference-material",
                "discard",
            },
        )
    },
)

_CODEBOOK = Codebook(
    axes={
        "artifact_role": {
            "case-study": TagEntry(
                definition="Empirical or quantitative tables.",
                positive_example="A table of case data.",
                negative_example="An unrelated table.",
            ),
            "discard": TagEntry(
                definition="Cover images, running heads, page numbers.",
                positive_example="A running head image.",
                negative_example="A substantive table.",
            ),
        }
    }
)

# --- issue #32 slice 02: schema/codebook fixtures with a `field` axis -------

_SCHEMA_WITH_FIELD = Schema(
    version="1.0",
    axes={
        **_SCHEMA.axes,
        "field": Axis(
            name="field",
            applies_to=["prose", "artifact"],
            cardinality="primary_plus_secondary",
            value_count=3,
            tag_ids={"state", "violence", "ideology"},
        ),
    },
)

_CODEBOOK_WITH_FIELD = Codebook(
    axes={
        **_CODEBOOK.axes,
        "field": {
            "state": TagEntry(
                definition="The state as an object of analysis.",
                positive_example="A passage about state capacity.",
                negative_example="A passage with no bearing on state.",
            ),
            "violence": TagEntry(
                definition="Armed conflict and coercion.",
                positive_example="A passage about violence.",
                negative_example="A passage with no bearing on violence.",
            ),
            "ideology": TagEntry(
                definition="Ideological framing.",
                positive_example="A passage about ideology.",
                negative_example="A passage with no bearing on ideology.",
            ),
        },
    }
)


# --- artifact-node collection + section provenance --------------------------


def test_artifact_nodes_with_section_pairs_each_artifact_with_its_enclosing_heading():
    from axial.artifacts import _artifact_nodes_with_section

    tree = _tree_with_one_artifact()

    pairs = _artifact_nodes_with_section(tree)

    assert len(pairs) == 1
    node, section = pairs[0]
    assert node["order"] == "1.2"
    assert section == "Introduction"


def test_artifact_nodes_with_section_finds_nested_artifacts_recursively():
    from axial.artifacts import _artifact_nodes_with_section

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "text": "wrapper",
                        "children": [{"type": "artifact", "order": "1.1.1", "label": "figure"}],
                    }
                ],
            }
        ]
    }

    pairs = _artifact_nodes_with_section(tree)

    assert len(pairs) == 1
    node, section = pairs[0]
    assert node["order"] == "1.1.1"
    assert section == "Introduction"


def test_artifact_nodes_with_section_returns_empty_for_no_artifacts():
    from axial.artifacts import _artifact_nodes_with_section

    tree = _tree_with_no_artifacts()

    assert _artifact_nodes_with_section(tree) == []


# --- artifact_id / record shape ----------------------------------------------


def test_build_artifact_record_keeps_dotted_order_verbatim():
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
        role="case-study",
    )

    assert record["artifact_id"] == "paper-abc123_art_1.2"
    assert record["section"] == "Introduction"
    assert record["source_id"] == "paper-abc123"
    assert record["artifact_role"] == "case-study"


def test_build_artifact_record_is_deterministic():
    from axial.artifacts import build_artifact_record

    node = {"type": "artifact", "order": "3"}
    first = build_artifact_record(
        source_id="paper-abc123", node=node, section="Introduction", role="case-study"
    )
    second = build_artifact_record(
        source_id="paper-abc123", node=node, section="Introduction", role="case-study"
    )

    assert first == second


def test_build_artifact_record_omits_field_key_when_none_given():
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
        role="case-study",
    )

    assert "field" not in record


def test_build_artifact_record_carries_field_when_given():
    from axial.artifacts import build_artifact_record

    field = {"primary": "state", "secondary": ["ideology"]}
    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
        role="case-study",
        field=field,
    )

    assert record["field"] == field


# --- prompt composition ------------------------------------------------------


def test_compose_artifact_prompt_includes_codebook_definitions_and_examples():
    from axial.artifacts import compose_artifact_prompt

    prompt = compose_artifact_prompt("Introduction", _CODEBOOK)

    assert "Empirical or quantitative tables." in prompt
    assert "A table of case data." in prompt
    assert "case-study" in prompt
    assert "discard" in prompt


def test_compose_artifact_prompt_includes_field_codebook_entries():
    from axial.artifacts import compose_artifact_prompt

    prompt = compose_artifact_prompt("Introduction", _CODEBOOK_WITH_FIELD)

    assert "The state as an object of analysis." in prompt
    assert "state" in prompt
    assert "ideology" in prompt


# --- role parsing + schema validation ----------------------------------------


def test_parse_artifact_role_extracts_the_role_string():
    from axial.artifacts import parse_artifact_role

    raw = json.dumps({"artifact_role": "case-study"})

    assert parse_artifact_role(raw) == "case-study"


def test_parse_artifact_role_rejects_invalid_json():
    from axial.artifacts import ArtifactParseError, parse_artifact_role

    with pytest.raises(ArtifactParseError):
        parse_artifact_role("not json")


def test_parse_artifact_role_accepts_a_markdown_fenced_response():
    """issue #72: deepseek-v4-flash sometimes wraps its JSON answer in a
    markdown fence despite the prompt's "no fences" instruction."""
    from axial.artifacts import parse_artifact_role

    raw = f"```json\n{json.dumps({'artifact_role': 'case-study'})}\n```"

    assert parse_artifact_role(raw) == "case-study"


def test_parse_artifact_role_rejects_prose_with_a_snippet_in_the_message():
    """issue #72: parse errors must quote the raw response so failures are
    diagnosable from worker logs."""
    from axial.artifacts import ArtifactParseError, parse_artifact_role

    raw = "I cannot classify this section."

    with pytest.raises(ArtifactParseError) as exc_info:
        parse_artifact_role(raw)

    assert raw in str(exc_info.value)


def test_validate_artifact_role_accepts_an_in_schema_role():
    from axial.artifacts import validate_artifact_role

    validate_artifact_role("case-study", _SCHEMA)  # must not raise


def test_validate_artifact_role_accepts_discard_as_a_valid_role():
    from axial.artifacts import validate_artifact_role

    validate_artifact_role("discard", _SCHEMA)  # must not raise


def test_validate_artifact_role_rejects_an_out_of_schema_role():
    from axial.artifacts import TagNotInSchemaError, validate_artifact_role

    with pytest.raises(TagNotInSchemaError) as exc_info:
        validate_artifact_role("not-a-real-role", _SCHEMA)

    message = str(exc_info.value)
    assert "not-a-real-role" in message
    assert "artifact_role" in message


# --- run_artifacts: end-to-end with monkeypatched extract/schema/codebook ---


def test_run_artifacts_classifies_discard_normally(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    class _DiscardClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps({"artifact_role": "discard"})

    records = artifacts_mod.run_artifacts(source, client=_DiscardClient())

    assert len(records) == 1
    assert records[0]["artifact_role"] == "discard"
    assert records[0]["section"] == "Introduction"


def test_run_artifacts_zero_artifacts_yields_zero_records_and_no_llm_call(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_no_artifacts())

    stub_client = StubLLMClient()
    records = artifacts_mod.run_artifacts(source, client=stub_client)

    assert records == []
    assert stub_client.call_count == 0


def test_run_artifacts_raises_on_out_of_schema_role(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    class _BogusClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps({"artifact_role": "not-a-real-role"})

    with pytest.raises(artifacts_mod.TagNotInSchemaError):
        artifacts_mod.run_artifacts(source, client=_BogusClient())


def test_artifacts_tag_not_in_schema_error_is_the_shared_tag_module_class():
    """Issue #32 slice 02 carry-in: the locally-defined `TagNotInSchemaError`
    is dropped; `axial.artifacts.TagNotInSchemaError` must be the exact same
    class object as `axial.tag.TagNotInSchemaError`, not a lookalike."""
    import axial.artifacts as artifacts_mod
    import axial.tag as tag_mod

    assert artifacts_mod.TagNotInSchemaError is tag_mod.TagNotInSchemaError


def test_run_artifacts_classifies_field_alongside_artifact_role(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA_WITH_FIELD)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK_WITH_FIELD)

    class _FieldClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {
                    "artifact_role": "case-study",
                    "field": {"primary": "state", "secondary": ["ideology"]},
                }
            )

    records = artifacts_mod.run_artifacts(source, client=_FieldClient())

    assert len(records) == 1
    assert records[0]["field"] == {"primary": "state", "secondary": ["ideology"]}


def test_run_artifacts_raises_on_out_of_schema_field_primary(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA_WITH_FIELD)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK_WITH_FIELD)

    class _BogusFieldClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps(
                {"artifact_role": "case-study", "field": {"primary": "not-a-real-field"}}
            )

    with pytest.raises(artifacts_mod.TagNotInSchemaError):
        artifacts_mod.run_artifacts(source, client=_BogusFieldClient())


def test_run_artifacts_calls_the_client_with_the_artifacts_pass_name(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    calls = []

    class _CapturingClient:
        def complete(self, prompt, pass_name=None):
            calls.append(pass_name)
            return json.dumps({"artifact_role": "case-study"})

    artifacts_mod.run_artifacts(source, client=_CapturingClient())

    assert calls == [ARTIFACTS_PASS_NAME]


def test_run_artifacts_missing_source_file_raises_missing_source_error(tmp_path):
    from axial.artifacts import MissingSourceError, run_artifacts

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError):
        run_artifacts(missing, client=StubLLMClient())


# --- run_artifacts: bounded re-ask on complete-but-unparseable JSON (#76) ---


def test_run_artifacts_succeeds_when_first_completion_is_malformed_json(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    valid = json.dumps({"artifact_role": "discard"})

    class _ScriptedClient:
        def __init__(self):
            self._responses = ["not json at all", valid]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = artifacts_mod.run_artifacts(source, client=client)

    assert len(records) == 1
    assert records[0]["artifact_role"] == "discard"
    assert client.call_count == 2


def test_run_artifacts_raises_artifact_parse_error_on_persistently_malformed_json(
    monkeypatch, tmp_path
):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    class _AlwaysBrokenClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return "not json at all"

    client = _AlwaysBrokenClient()

    with pytest.raises(artifacts_mod.ArtifactParseError):
        artifacts_mod.run_artifacts(source, client=client)

    assert client.call_count == 3
