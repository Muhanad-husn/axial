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


def test_build_artifact_record_omits_caption_key_when_none_given():
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
        role="case-study",
    )

    assert "caption" not in record


def test_build_artifact_record_carries_caption_when_given():
    from axial.artifacts import build_artifact_record

    record = build_artifact_record(
        source_id="paper-abc123",
        node={"type": "artifact", "order": "1.2"},
        section="Introduction",
        role="case-study",
        caption="A caption describing the figure.",
    )

    assert record["caption"] == "A caption describing the figure."


# --- issue #168: router-routed artifact collection + caption attachment -----


def _tree_with_caption_table_and_apparatus() -> dict:
    """One section with a table, a picture, an immediately-following caption,
    and a document_index (TOC) block; a second, back-matter-titled section
    with a footnote block. Mirrors tests/test_artifacts.py's own outer
    fixture (issue #168) at a smaller scale for inner-unit coverage."""
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "children": [
                    {"type": "artifact", "order": "1.1", "label": "table", "text": "Table body."},
                    {
                        "type": "artifact",
                        "order": "1.2",
                        "label": "picture",
                        "text": "Figure body.",
                    },
                    {
                        "type": "prose",
                        "order": "1.3",
                        "label": "caption",
                        "text": "Caption body.",
                    },
                    {
                        "type": "prose",
                        "order": "1.4",
                        "label": "document_index",
                        "text": "TOC body.",
                    },
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Endnotes",
                "children": [
                    {
                        "type": "prose",
                        "order": "2.1",
                        "label": "footnote",
                        "text": "Footnote body.",
                    },
                ],
            },
        ]
    }


def test_routed_artifact_blocks_includes_caption_and_excludes_apparatus():
    from axial.artifacts import _routed_artifact_blocks

    tree = _tree_with_caption_table_and_apparatus()
    blocks = _routed_artifact_blocks(tree)

    orders = [node["order"] for node, _section in blocks]
    assert orders == ["1.1", "1.2", "1.3"]
    assert all(section == "Findings" for _node, section in blocks)


def test_routed_artifact_blocks_still_collects_type_artifact_regardless_of_label():
    """Back-compat carve-out (issue #168): a genuine `type == 'artifact'`
    node (extract.py's own docling TableItem/PictureItem classification) is
    always collected even when its `label` isn't one of the router's own
    artifact labels -- guards a real artifact from vanishing on an
    unrecognized-label edge case (see e.g.
    tests/test_tag_artifacts_input_guard.py's `label: 'figure'` fixture)."""
    from axial.artifacts import _routed_artifact_blocks

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "children": [
                    {
                        "type": "artifact",
                        "order": "1.1",
                        "label": "figure",
                        "text": "Odd-label artifact.",
                    },
                ],
            }
        ]
    }

    blocks = _routed_artifact_blocks(tree)

    assert [node["order"] for node, _section in blocks] == ["1.1"]


def test_attach_captions_moves_caption_text_onto_the_preceding_artifact():
    from axial.artifacts import _attach_captions, _routed_artifact_blocks

    tree = _tree_with_caption_table_and_apparatus()
    blocks = _routed_artifact_blocks(tree)

    entries = _attach_captions(blocks)

    assert [entry["node"]["order"] for entry in entries] == ["1.1", "1.2"]
    assert entries[0]["caption"] is None
    assert entries[1]["caption"] == "Caption body."


def test_attach_captions_orphan_caption_with_no_preceding_artifact_becomes_standalone():
    """Fallback (issue #168 plan): a caption with no resolvable prior
    artifact never crashes and is never silently dropped -- it becomes its
    own standalone entry."""
    from axial.artifacts import _attach_captions

    orphan_caption = {
        "type": "prose",
        "order": "1.1",
        "label": "caption",
        "text": "Orphan caption.",
    }

    entries = _attach_captions([(orphan_caption, "Findings")])

    assert len(entries) == 1
    assert entries[0]["node"] is orphan_caption
    assert entries[0]["caption"] is None


def test_attach_captions_a_second_caption_attaches_to_the_orphan_entry_in_turn():
    from axial.artifacts import _attach_captions

    orphan_caption = {
        "type": "prose",
        "order": "1.1",
        "label": "caption",
        "text": "Orphan caption.",
    }
    second_caption = {
        "type": "prose",
        "order": "1.2",
        "label": "caption",
        "text": "Second caption.",
    }

    entries = _attach_captions([(orphan_caption, "Findings"), (second_caption, "Findings")])

    assert len(entries) == 1
    assert entries[0]["caption"] == "Second caption."


def test_run_artifacts_attaches_caption_to_figure_and_excludes_apparatus(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(
        artifacts_mod, "extract", lambda path: _tree_with_caption_table_and_apparatus()
    )
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    class _StaticClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps({"artifact_role": "case-study"})

    records = artifacts_mod.run_artifacts(source, client=_StaticClient())

    assert len(records) == 2
    table_record = next(r for r in records if r["artifact_id"].endswith("_art_1.1"))
    figure_record = next(r for r in records if r["artifact_id"].endswith("_art_1.2"))

    assert "caption" not in table_record
    assert figure_record["caption"] == "Caption body."


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


# --- run_artifacts: degeneracy re-ask on empty axis values (issue #90) ------


def test_reject_degenerate_artifact_values_accepts_a_non_degenerate_response():
    from axial.artifacts import reject_degenerate_artifact_values

    raw = json.dumps(
        {"artifact_role": "case-study", "field": {"primary": "state", "secondary": ["ideology"]}}
    )

    reject_degenerate_artifact_values(raw, _SCHEMA_WITH_FIELD)  # must not raise


def test_reject_degenerate_artifact_values_rejects_a_blank_artifact_role():
    from axial.artifacts import ArtifactParseError, reject_degenerate_artifact_values

    raw = json.dumps({"artifact_role": "  ", "field": {"primary": "state"}})

    with pytest.raises(ArtifactParseError):
        reject_degenerate_artifact_values(raw, _SCHEMA_WITH_FIELD)


def test_reject_degenerate_artifact_values_rejects_a_blank_field_primary():
    from axial.artifacts import ArtifactParseError, reject_degenerate_artifact_values

    raw = json.dumps({"artifact_role": "case-study", "field": {"primary": ""}})

    with pytest.raises(ArtifactParseError):
        reject_degenerate_artifact_values(raw, _SCHEMA_WITH_FIELD)


def test_reject_degenerate_artifact_values_rejects_a_blank_field_secondary_entry():
    from axial.artifacts import ArtifactParseError, reject_degenerate_artifact_values

    raw = json.dumps(
        {"artifact_role": "case-study", "field": {"primary": "state", "secondary": [""]}}
    )

    with pytest.raises(ArtifactParseError):
        reject_degenerate_artifact_values(raw, _SCHEMA_WITH_FIELD)


def test_reject_degenerate_artifact_values_ignores_field_when_schema_lacks_the_axis():
    """A schema without a `field` axis (e.g. this module's minimal
    `_SCHEMA` fixture) is not checked for field degeneracy at all -- mirrors
    `run_artifacts`'s own `field_axis is not None` gate."""
    from axial.artifacts import reject_degenerate_artifact_values

    raw = json.dumps({"artifact_role": "case-study"})

    reject_degenerate_artifact_values(raw, _SCHEMA)  # must not raise


def test_run_artifacts_reasks_then_succeeds_on_an_empty_field_primary(monkeypatch, tmp_path):
    """issue #90: an empty-string `field.primary` from the model must
    trigger a bounded re-ask (via `complete_json`'s `validate` seam), never
    reach `validate_multi_value_tag` and die as a raw, unwrapped
    `TagNotInSchemaError` for tag `''`."""
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA_WITH_FIELD)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK_WITH_FIELD)

    degenerate = json.dumps({"artifact_role": "case-study", "field": {"primary": ""}})
    valid = json.dumps(
        {"artifact_role": "case-study", "field": {"primary": "state", "secondary": []}}
    )

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, valid]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    records = artifacts_mod.run_artifacts(source, client=client)

    assert len(records) == 1
    assert records[0]["field"]["primary"] == "state"
    assert client.call_count == 2


def test_run_artifacts_raises_typed_error_on_persistently_empty_field_primary(
    monkeypatch, tmp_path
):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA_WITH_FIELD)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK_WITH_FIELD)

    degenerate = json.dumps({"artifact_role": "case-study", "field": {"primary": ""}})

    class _AlwaysDegenerateClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return degenerate

    client = _AlwaysDegenerateClient()

    with pytest.raises(artifacts_mod.ArtifactParseError):
        artifacts_mod.run_artifacts(source, client=client)

    assert client.call_count == 3


def test_run_artifacts_reasks_then_succeeds_on_a_blank_artifact_role(monkeypatch, tmp_path):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    degenerate = json.dumps({"artifact_role": "   "})
    valid = json.dumps({"artifact_role": "discard"})

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, valid]
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


def test_run_artifacts_out_of_vocab_field_primary_hard_errors_after_one_bounded_reask(
    monkeypatch, tmp_path
):
    """A genuine (non-empty) out-of-vocabulary `field.primary` is NEVER
    smoothed over by the degeneracy re-ask -- but issue #102 (P0-6
    refinement) grants it EXACTLY ONE bounded correction re-ask, identical to
    the tag pass, before the hard error. A model that stays out-of-vocab on
    the correction re-ask still raises `TagNotInSchemaError`, and the re-ask
    fired exactly once (two LLM calls), never looping further."""
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_one_artifact())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA_WITH_FIELD)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK_WITH_FIELD)

    class _BogusFieldClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps(
                {"artifact_role": "case-study", "field": {"primary": "not-a-real-field"}}
            )

    client = _BogusFieldClient()

    with pytest.raises(artifacts_mod.TagNotInSchemaError):
        artifacts_mod.run_artifacts(source, client=client)

    assert client.call_count == 2


# --- issue #98: per-artifact checkpoint/resume -------------------------------


def _tree_with_two_artifacts() -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Findings",
                "children": [
                    {"type": "prose", "order": "1.1", "text": "Findings body sentence."},
                    {"type": "artifact", "order": "1.2", "label": "table"},
                    {"type": "artifact", "order": "1.3", "label": "table"},
                ],
            }
        ]
    }


def test_artifacts_checkpoint_append_load_round_trips(tmp_path):
    from axial.artifacts import append_artifact_checkpoint, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src-abc.jsonl"
    record_one = {"artifact_id": "src-abc_art_1", "artifact_role": "case-study"}
    record_two = {"artifact_id": "src-abc_art_2", "artifact_role": "discard"}

    append_artifact_checkpoint(path, record_one)
    append_artifact_checkpoint(path, record_two)

    loaded = load_artifact_checkpoint(path)
    assert loaded == [record_one, record_two]


def test_artifacts_checkpoint_path_is_keyed_by_source_id(tmp_path):
    from axial.artifacts import artifacts_checkpoint_path

    path = artifacts_checkpoint_path("src-abc123", tmp_path)
    assert path == tmp_path / "src-abc123.jsonl"


def test_load_artifact_checkpoint_missing_file_returns_empty_list(tmp_path):
    from axial.artifacts import load_artifact_checkpoint

    assert load_artifact_checkpoint(tmp_path / "nonexistent.jsonl") == []


def test_load_artifact_checkpoint_drops_torn_final_line(tmp_path):
    from axial.artifacts import append_artifact_checkpoint, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src-abc.jsonl"
    intact = {"artifact_id": "src-abc_art_1", "artifact_role": "case-study"}
    append_artifact_checkpoint(path, intact)

    full_second = json.dumps({"artifact_id": "src-abc_art_2", "artifact_role": "discard"})
    torn_tail = full_second[:15]
    assert not torn_tail.endswith("}")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(torn_tail)  # no trailing newline: simulates a torn in-flight write

    loaded = load_artifact_checkpoint(path)
    assert loaded == [intact]


def test_load_artifact_checkpoint_raises_naming_path_and_line_for_a_non_final_torn_line(tmp_path):
    from axial.artifacts import ArtifactCheckpointCorruptError, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    intact_first = json.dumps({"artifact_id": "a"})
    torn_middle = '{"artifact_id": "b", "broken'
    intact_last = json.dumps({"artifact_id": "c"})
    path.write_text(f"{intact_first}\n{torn_middle}\n{intact_last}\n", encoding="utf-8")

    with pytest.raises(ArtifactCheckpointCorruptError) as exc_info:
        load_artifact_checkpoint(path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "2" in message  # 1-indexed line number of the torn (non-final) line


def test_append_artifact_checkpoint_heals_a_torn_tail_before_appending(tmp_path):
    from axial.artifacts import append_artifact_checkpoint, load_artifact_checkpoint

    path = tmp_path / "artifacts" / "src.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"artifact_id": "a"}\n{"artifact_id": "b", "brok', encoding="utf-8")

    append_artifact_checkpoint(path, {"artifact_id": "c"})

    loaded = load_artifact_checkpoint(path)
    assert loaded == [{"artifact_id": "a"}, {"artifact_id": "c"}]


def test_run_artifacts_writes_a_source_keyed_checkpoint_when_artifacts_dir_given(
    monkeypatch, tmp_path
):
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    source_id = artifacts_mod.compute_source_id(source)
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_two_artifacts())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    class _StaticClient:
        def complete(self, prompt, pass_name=None):
            return json.dumps({"artifact_role": "case-study"})

    records = artifacts_mod.run_artifacts(
        source, client=_StaticClient(), artifacts_dir=artifacts_dir
    )

    checkpoint = artifacts_dir / f"{source_id}.jsonl"
    assert checkpoint.is_file()
    persisted = artifacts_mod.load_artifact_checkpoint(checkpoint)
    assert [r["artifact_id"] for r in persisted] == [r["artifact_id"] for r in records]
    assert len(persisted) == 2


def test_run_artifacts_resume_skips_already_checkpointed_artifacts(monkeypatch, tmp_path):
    """Skip-set arithmetic (issue #98): an artifact already present in the
    checkpoint is reused verbatim and never re-sent to the model -- only the
    missing artifact(s) are classified."""
    import axial.artifacts as artifacts_mod
    from axial.artifacts import append_artifact_checkpoint, artifacts_checkpoint_path

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    source_id = artifacts_mod.compute_source_id(source)
    artifacts_dir = tmp_path / "artifacts"

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_two_artifacts())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    # Pre-seed the checkpoint with the first artifact only.
    checkpoint = artifacts_checkpoint_path(source_id, artifacts_dir)
    seeded = {
        "artifact_id": f"{source_id}_art_1.2",
        "artifact_role": "discard",
        "source_id": source_id,
        "section": "Findings",
    }
    append_artifact_checkpoint(checkpoint, seeded)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps({"artifact_role": "case-study"})

    counting = _CountingClient()
    records = artifacts_mod.run_artifacts(source, client=counting, artifacts_dir=artifacts_dir)

    # Only the missing (second) artifact was classified.
    assert counting.call_count == 1
    assert [r["artifact_id"] for r in records] == [
        f"{source_id}_art_1.2",
        f"{source_id}_art_1.3",
    ]
    # The seeded record is reused verbatim (its role is unchanged).
    assert records[0]["artifact_role"] == "discard"

    persisted = artifacts_mod.load_artifact_checkpoint(checkpoint)
    assert len(persisted) == 2  # no duplicate line for the already-checkpointed artifact


def test_run_artifacts_checkpoint_disabled_by_default(monkeypatch, tmp_path):
    """When `artifacts_dir` is omitted (today's `axial artifacts` behavior,
    unchanged), no checkpoint file is ever written and every run
    re-classifies every artifact from scratch (issue #98's "direct axial
    artifacts ... invocations unchanged")."""
    import axial.artifacts as artifacts_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(artifacts_mod, "extract", lambda path: _tree_with_two_artifacts())
    monkeypatch.setattr(artifacts_mod, "load_schema", lambda domain_dir: _SCHEMA)
    monkeypatch.setattr(artifacts_mod, "load_codebook", lambda domain_dir: _CODEBOOK)

    class _CountingClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return json.dumps({"artifact_role": "case-study"})

    first_client = _CountingClient()
    artifacts_mod.run_artifacts(source, client=first_client)
    assert first_client.call_count == 2

    # A second run with no artifacts_dir re-classifies everything again --
    # proof no checkpoint was written/consulted by the first run.
    second_client = _CountingClient()
    artifacts_mod.run_artifacts(source, client=second_client)
    assert second_client.call_count == 2
