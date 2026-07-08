"""Inner unit tests for the axial extract module (issue #14 slice 02;
issue #15 slice 03 -- extraction fallback)."""

import json
from pathlib import Path

import pytest
from docling_core.types.doc.document import DoclingDocument, TableData
from docling_core.types.doc.labels import DocItemLabel
from unstructured.documents.elements import Header, NarrativeText, Table, Title

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "extract"

PROSE_AND_TABLE_PDF = FIXTURES_DIR / "prose_and_table.pdf"


def _synthetic_document() -> DoclingDocument:
    """Build a small in-memory docling document without running ML models.

    Mirrors the fixture's shape (a heading, two paragraphs, a table, a
    second heading, a paragraph) so normalize() can be unit-tested fast,
    independent of the real docling conversion pipeline.
    """
    doc = DoclingDocument(name="synthetic")
    doc.add_heading(text="Introduction", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="First paragraph.")
    doc.add_text(label=DocItemLabel.TEXT, text="Second paragraph.")
    doc.add_table(data=TableData(num_rows=1, num_cols=1))
    doc.add_heading(text="Discussion", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="Closing paragraph.")
    return doc


def test_normalize_classifies_text_block_as_prose():
    from axial.extract import normalize

    tree = normalize(_synthetic_document())

    section = tree["children"][0]
    paragraph = section["children"][0]
    assert paragraph["type"] == "prose"
    assert paragraph["text"] == "First paragraph."


def test_normalize_classifies_table_as_artifact():
    from axial.extract import normalize

    tree = normalize(_synthetic_document())

    section = tree["children"][0]
    table_node = section["children"][2]
    assert table_node["type"] == "artifact"


def test_normalize_assigns_stable_dotted_order_preserving_source_position():
    from axial.extract import normalize

    tree = normalize(_synthetic_document())

    first_section, second_section = tree["children"]
    assert first_section["order"] == "1"
    assert second_section["order"] == "2"
    assert [child["order"] for child in first_section["children"]] == ["1.1", "1.2", "1.3"]
    assert [child["order"] for child in second_section["children"]] == ["2.1"]


def test_normalize_produces_a_nested_tree_not_a_flat_list():
    from axial.extract import normalize

    tree = normalize(_synthetic_document())

    # Root -> section -> content: depth > 1.
    assert tree["children"], "expected at least one top-level node"
    section = tree["children"][0]
    assert section["children"], "expected the section to nest its content"


def test_normalize_flattens_content_before_first_section_header_to_top_level():
    from axial.extract import normalize

    doc = DoclingDocument(name="preamble")
    doc.add_text(label=DocItemLabel.TEXT, text="Preamble paragraph.")
    doc.add_heading(text="Introduction", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="First paragraph.")

    tree = normalize(doc)

    preamble, section = tree["children"]
    assert preamble["type"] == "prose"
    assert preamble["order"] == "1"
    assert preamble["text"] == "Preamble paragraph."
    assert "children" not in preamble

    assert section["order"] == "2"
    assert section["children"][0]["order"] == "2.1"


def test_normalize_empty_document_yields_empty_children_without_crashing():
    from axial.extract import normalize

    doc = DoclingDocument(name="empty")

    tree = normalize(doc)

    assert tree == {"children": []}


def test_normalize_is_deterministic_across_runs():
    from axial.extract import normalize

    first = normalize(_synthetic_document())
    second = normalize(_synthetic_document())

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_extract_missing_file_raises_source_validation_error_naming_it():
    from axial.extract import SourceValidationError, extract

    missing = FIXTURES_DIR / "does_not_exist.pdf"
    with pytest.raises(SourceValidationError) as exc_info:
        extract(missing)

    assert missing.name in str(exc_info.value)


@pytest.mark.slow
def test_extract_runs_docling_end_to_end_on_the_fixture_and_normalizes_it():
    """The docling wrapper (convert + normalize) on a real fixture PDF."""
    from axial.extract import extract

    tree = extract(PROSE_AND_TABLE_PDF)

    assert isinstance(tree, dict)
    assert tree["children"], "expected a non-empty tree for the prose+table fixture"

    def _iter(node):
        for child in node.get("children", []):
            yield child
            yield from _iter(child)

    node_types = {node["type"] for node in _iter(tree)}
    assert "prose" in node_types
    assert "artifact" in node_types


# --- slice 03: extraction fallback (issue #15) -----------------------------


def test_is_degenerate_flags_an_empty_docling_document():
    from axial.extract import is_degenerate

    empty_doc = DoclingDocument(name="empty")

    assert is_degenerate(empty_doc) is True


def test_is_degenerate_is_false_for_a_document_with_real_items():
    from axial.extract import is_degenerate

    assert is_degenerate(_synthetic_document()) is False


def test_extract_routes_a_raised_docling_exception_to_the_unstructured_fallback(
    monkeypatch, tmp_path
):
    """A docling exception must not crash extract(); it must route to the
    Unstructured adapter and still yield a normalized tree."""
    import axial.extract as extract_mod

    def _boom(path):
        raise RuntimeError("simulated docling crash")

    fake_elements = [Title(text="Section"), NarrativeText(text="Body text.")]

    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path)
    monkeypatch.setattr(extract_mod, "convert", _boom)
    monkeypatch.setattr(extract_mod, "_partition_with_unstructured", lambda path: fake_elements)

    tree = extract_mod.extract(PROSE_AND_TABLE_PDF)

    assert tree["children"], "expected a fallback tree, not a crash"
    assert tree["children"][0]["type"] == "prose"


def test_extract_falls_back_when_docling_output_is_degenerate(monkeypatch, tmp_path):
    """Degenerate (empty/structureless) docling output must also route to the
    Unstructured fallback, without raising."""
    import axial.extract as extract_mod

    fake_elements = [Title(text="Section"), NarrativeText(text="Body text.")]

    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path)
    monkeypatch.setattr(extract_mod, "convert", lambda path: DoclingDocument(name="empty"))
    monkeypatch.setattr(extract_mod, "_partition_with_unstructured", lambda path: fake_elements)

    tree = extract_mod.extract(PROSE_AND_TABLE_PDF)

    assert tree["children"], "expected a fallback tree for degenerate docling output"


def test_normalize_unstructured_emits_the_same_prose_artifact_tree_shape():
    from axial.extract import _normalize_unstructured

    elements = [
        Title(text="Introduction"),
        NarrativeText(text="First paragraph."),
        Table(text="a table cell"),
        Title(text="Discussion"),
        NarrativeText(text="Closing paragraph."),
    ]

    tree = _normalize_unstructured(elements)

    first_section, second_section = tree["children"]
    assert first_section["type"] == "prose"
    assert first_section["order"] == "1"
    assert [child["type"] for child in first_section["children"]] == ["prose", "artifact"]
    assert [child["order"] for child in first_section["children"]] == ["1.1", "1.2"]

    assert second_section["order"] == "2"
    assert second_section["children"][0]["order"] == "2.1"


def test_normalize_unstructured_header_does_not_open_a_section():
    """Regression: Unstructured's `Header` element is running/page-header
    furniture (e.g. a Word section header), not a heading over body content.
    It must not open a section -- prose that follows it belongs at the top
    level (or under whatever real Title section is open), never nested as
    the header's child."""
    from axial.extract import _normalize_unstructured

    elements = [
        Header(text="Running header"),
        NarrativeText(text="Preamble prose."),
    ]

    tree = _normalize_unstructured(elements)

    header_node, prose_node = tree["children"]
    assert header_node["type"] == "prose"
    assert "children" not in header_node, "Header must not open a section"
    assert prose_node["type"] == "prose"
    assert prose_node["order"] == "2", "prose must sit at the top level, not nested under Header"


def test_fallback_logs_source_filename_and_reason_to_stderr(monkeypatch, capsys):
    import axial.extract as extract_mod

    fake_elements = [Title(text="Section"), NarrativeText(text="Body text.")]
    monkeypatch.setattr(extract_mod, "_partition_with_unstructured", lambda path: fake_elements)

    extract_mod._fallback(PROSE_AND_TABLE_PDF, "docling raised an exception: boom")

    captured = capsys.readouterr()
    assert captured.out == "", "the fallback log must go to stderr, not stdout"
    stderr_lower = captured.err.lower()
    assert "docling" in stderr_lower
    assert "unstructured" in stderr_lower
    assert "fallback" in stderr_lower
    assert PROSE_AND_TABLE_PDF.name in captured.err


# --- tree persistence/reuse (issue #45) -------------------------------------


def test_extract_persists_the_returned_tree_keyed_by_source_id(monkeypatch, tmp_path):
    """A fresh source_id (no persisted tree yet) must be written to
    `<trees_dir>/<source_id>.json`, with content identical to what extract()
    returns."""
    import axial.extract as extract_mod
    from axial.envelope import compute_source_id

    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path)
    monkeypatch.setattr(extract_mod, "convert", lambda path: _synthetic_document())

    tree = extract_mod.extract(PROSE_AND_TABLE_PDF)

    source_id = compute_source_id(PROSE_AND_TABLE_PDF)
    persisted_path = tmp_path / f"{source_id}.json"
    assert persisted_path.exists()
    assert json.loads(persisted_path.read_text(encoding="utf-8")) == tree


def test_extract_reuses_a_persisted_tree_without_converting(monkeypatch, tmp_path):
    """When a persisted tree already exists for the source's source_id,
    extract() must return it verbatim and must never call docling/Unstructured
    conversion again."""
    import axial.extract as extract_mod
    from axial.envelope import compute_source_id

    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path)

    source_id = compute_source_id(PROSE_AND_TABLE_PDF)
    persisted_path = tmp_path / f"{source_id}.json"
    sentinel_tree = {"children": [{"type": "prose", "order": "0", "text": "sentinel"}]}
    persisted_path.write_text(json.dumps(sentinel_tree), encoding="utf-8")

    def _fail_if_called(path):
        raise AssertionError("docling conversion must not run when a persisted tree exists")

    monkeypatch.setattr(extract_mod, "convert", _fail_if_called)
    monkeypatch.setattr(extract_mod, "_partition_with_unstructured", _fail_if_called)

    tree = extract_mod.extract(PROSE_AND_TABLE_PDF)

    assert tree == sentinel_tree


def test_extract_persists_the_tree_from_the_unstructured_fallback_path(monkeypatch, tmp_path):
    """Reuse must cover the fallback path too: when docling fails/degenerates
    and Unstructured produces the tree instead, that tree is still persisted
    keyed by source_id."""
    import axial.extract as extract_mod
    from axial.envelope import compute_source_id

    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path)

    def _boom(path):
        raise RuntimeError("simulated docling crash")

    fake_elements = [Title(text="Section"), NarrativeText(text="Body text.")]
    monkeypatch.setattr(extract_mod, "convert", _boom)
    monkeypatch.setattr(extract_mod, "_partition_with_unstructured", lambda path: fake_elements)

    tree = extract_mod.extract(PROSE_AND_TABLE_PDF)

    source_id = compute_source_id(PROSE_AND_TABLE_PDF)
    persisted_path = tmp_path / f"{source_id}.json"
    assert persisted_path.exists()
    assert json.loads(persisted_path.read_text(encoding="utf-8")) == tree


def test_extract_does_not_fall_back_when_docling_succeeds(monkeypatch, capsys, tmp_path):
    """No-regression: a successful docling conversion must not invoke the
    Unstructured fallback or log anything about it."""
    import axial.extract as extract_mod

    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path)
    monkeypatch.setattr(extract_mod, "convert", lambda path: _synthetic_document())

    def _fail_if_called(path):
        raise AssertionError("unstructured fallback must not run when docling succeeds")

    monkeypatch.setattr(extract_mod, "_partition_with_unstructured", _fail_if_called)

    tree = extract_mod.extract(PROSE_AND_TABLE_PDF)

    assert tree["children"], "expected the normal docling tree"
    captured = capsys.readouterr()
    assert "fallback" not in captured.err.lower()
