"""Inner unit tests for the axial extract module (issue #14, slice 02)."""

import json
from pathlib import Path

import pytest
from docling_core.types.doc.document import DoclingDocument, TableData
from docling_core.types.doc.labels import DocItemLabel

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
