"""Inner unit tests for the axial tag module (issue #27 slice 01 -- tag
spine: role_in_argument, schema-driven, hard-error, versioned)."""

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
