"""Inner unit tests for the axial chunk module: section selection and the
`build_chunk_records`/`_slugify` provenance helpers shared by the recursive/
structural chunk stage (the sole mechanism as of issue #191; see
test_chunk_recursive_unit.py for its own dedicated unit tests).
"""

from __future__ import annotations

import json

import pytest


def _tree_with_sections(*, middle_body: bool = True) -> dict:
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [{"type": "prose", "order": "1.1", "text": "Intro body sentence."}],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Comparative Cases",
                "children": (
                    [{"type": "prose", "order": "2.1", "text": "Middle body sentence."}]
                    if middle_body
                    else []
                ),
            },
            {
                "type": "prose",
                "order": "3",
                "text": "Conclusion",
                "children": [
                    {"type": "prose", "order": "3.1", "text": "Conclusion body sentence."}
                ],
            },
        ]
    }


# --- context assembly -------------------------------------------------------


def test_section_nodes_selects_only_top_level_headed_sections():
    from axial.chunk import _section_nodes

    tree = _tree_with_sections()

    sections = _section_nodes(tree)

    assert [s["text"] for s in sections] == ["Introduction", "Comparative Cases", "Conclusion"]


# --- chunk_id / section provenance -------------------------------------------


def test_build_chunk_records_have_stable_ids_and_section_provenance():
    from axial.chunk import build_chunk_records

    records = build_chunk_records(
        "paper-abc123", "2", "Comparative Cases", [{"text": "a"}, {"text": "b"}]
    )

    assert [r["chunk_id"] for r in records] == [
        "paper-abc123_2_comparative-cases_001",
        "paper-abc123_2_comparative-cases_002",
    ]
    assert all(r["section"] == "Comparative Cases" for r in records)


def test_build_chunk_records_is_deterministic_across_calls():
    from axial.chunk import build_chunk_records

    chunks = [{"text": "a"}, {"text": "b"}]
    first = build_chunk_records("paper-abc123", "3", "Conclusion", chunks)
    second = build_chunk_records("paper-abc123", "3", "Conclusion", chunks)

    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second]


def test_build_chunk_records_does_not_collide_across_sections_sharing_a_heading():
    """extract.py's tree-builder opens a fresh top-level section node per
    heading occurrence (unnested), so a real source can have two distinct
    sections both titled e.g. "Introduction" -- folding the section's own
    `order` into chunk_id must keep their chunk_ids from colliding even
    though the heading slug is identical (review finding: chunk_id
    collisions on duplicate section headings)."""
    from axial.chunk import build_chunk_records

    chunks = [{"text": "a"}]
    first_chapter = build_chunk_records("paper-abc123", "1", "Introduction", chunks)
    second_chapter = build_chunk_records("paper-abc123", "4", "Introduction", chunks)

    assert first_chapter[0]["chunk_id"] != second_chapter[0]["chunk_id"]
    assert first_chapter[0]["section"] == second_chapter[0]["section"] == "Introduction"


# --- _slugify cap (issue #94: bounded note filenames) -----------------------


def test_slugify_caps_long_heading_at_80_chars():
    from axial.chunk import _slugify

    heading = "Word " * 60  # slugifies far past the 80-char cap
    slug = _slugify(heading)

    assert len(slug) <= 80


def test_slugify_cuts_at_hyphen_boundary_not_mid_word():
    from axial.chunk import _slugify

    # Built from 4-char words ("aaaa-bbbb-...") so the raw 80-char cut point
    # falls mid-word; the capped slug must back up to the preceding hyphen
    # rather than emit a truncated word fragment.
    words = [chr(ord("a") + (i % 26)) * 4 for i in range(30)]
    heading = " ".join(words)
    slug = _slugify(heading)

    assert len(slug) <= 80
    for chunk in slug.split("-"):
        assert chunk == chunk[:4] and len(chunk) == 4, (
            f"expected every hyphen-separated piece of the capped slug to be "
            f"a whole 4-char word, got fragment {chunk!r} in slug {slug!r}"
        )


def test_slugify_never_returns_a_trailing_hyphen():
    from axial.chunk import _slugify

    heading = "Word " * 60
    slug = _slugify(heading)

    assert not slug.endswith("-")


def test_slugify_unchanged_for_short_headings_below_the_cap():
    from axial.chunk import _slugify

    assert _slugify("Comparative Cases") == "comparative-cases"
    assert _slugify("Introduction") == "introduction"


def test_slugify_all_symbol_heading_still_falls_back_to_section():
    from axial.chunk import _slugify

    assert _slugify("!!! ??? ***") == "section"


# --- read_chunks: the on-disk artifact reader (issue #154, PRD §7.7) --------


def test_read_chunks_returns_records_in_file_order(tmp_path):
    from axial.chunk import read_chunks

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    records = [
        {
            "chunk_id": "paper_1_intro_001",
            "section": "Introduction",
            "section_order": "1",
            "text": "a",
        },
        {
            "chunk_id": "paper_1_intro_002",
            "section": "Introduction",
            "section_order": "1",
            "text": "b",
        },
        {
            "chunk_id": "paper_2_concl_001",
            "section": "Conclusion",
            "section_order": "2",
            "text": "c",
        },
    ]
    (chunks_dir / "paper.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )

    result = read_chunks("paper", chunks_dir=chunks_dir)

    assert result == records


def test_read_chunks_raises_missing_chunk_artifact_error_when_absent(tmp_path):
    from axial.chunk import MissingChunkArtifactError, read_chunks

    chunks_dir = tmp_path / "chunks"

    with pytest.raises(MissingChunkArtifactError) as exc_info:
        read_chunks("does-not-exist", chunks_dir=chunks_dir)

    assert "axial chunk" in str(exc_info.value)


def test_read_chunks_resolves_the_same_path_run_chunk_recursive_writes_to(monkeypatch, tmp_path):
    """Reader and writer must agree byte-for-byte on where the artifact
    lives -- both resolve via `_default_chunks_dir`/`chunks_checkpoint_path`
    (module docstring)."""
    import axial.chunk as chunk_mod

    chunks_dir = tmp_path / "chunks"
    monkeypatch.setattr(chunk_mod, "CHUNKS_DIR", chunks_dir)

    with pytest.raises(chunk_mod.MissingChunkArtifactError) as exc_info:
        chunk_mod.read_chunks("paper-abc123")

    assert exc_info.value.path == chunk_mod.chunks_checkpoint_path("paper-abc123", chunks_dir)
