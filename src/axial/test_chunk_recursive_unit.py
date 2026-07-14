"""Inner unit tests for the recursive/structural chunk mechanism (issue
#165, slice 06 of the chunk-redesign subproject). Complements
tests/test_chunk_recursive.py (the LOCKED outer acceptance test) with
unit-level coverage of the pieces it only proves end-to-end: the
`AXIAL_CHUNK_MECHANISM` selector, the separator-hierarchy splitter's
fall-through behavior at each level, the two-sided band guard reused/adapted
for this mechanism, `run_chunk_recursive` end-to-end against a monkeypatched
tree, and the zero-embedding/zero-LLM cost proof at the unit level.
"""

from __future__ import annotations

import json

import pytest

import axial.chunk as chunk_mod
from axial.chunk import (
    CHUNK_MAX,
    CHUNK_MECHANISM_ENV_VAR,
    CHUNK_MECHANISM_RECURSIVE,
    CHUNK_MIN,
    EMBEDDER_ENV_VAR,
    HashingEmbedder,
    _enforce_max_recursive,
    _recursive_section_chunks,
    _recursive_split_text,
    get_chunk_mechanism,
    run_chunk_embedding,
    run_chunk_recursive,
)

from .test_chunk_embedding import _patch_tree, _tree_with_sections

# --- selector -----------------------------------------------------------


def test_get_chunk_mechanism_recursive_value_selects_recursive(monkeypatch):
    monkeypatch.setenv(CHUNK_MECHANISM_ENV_VAR, "recursive")
    assert get_chunk_mechanism() == CHUNK_MECHANISM_RECURSIVE


def test_get_chunk_mechanism_unset_falls_back_to_default(monkeypatch):
    monkeypatch.delenv(CHUNK_MECHANISM_ENV_VAR, raising=False)
    assert get_chunk_mechanism() != CHUNK_MECHANISM_RECURSIVE


def test_get_chunk_mechanism_other_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(CHUNK_MECHANISM_ENV_VAR, "something-else")
    assert get_chunk_mechanism() != CHUNK_MECHANISM_RECURSIVE


# --- separator hierarchy: fall-through behavior --------------------------


def test_recursive_split_clean_paragraphs_splits_at_paragraph_level():
    """The WHOLE text exceeds `chunk_max` (forcing a split at all), but each
    individual paragraph fits -- the paragraph level alone is enough."""
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
    assert len(text) > 30
    pieces = _recursive_split_text(text, chunk_max=30)
    assert pieces == [
        "First paragraph here.",
        "Second paragraph here.",
        "Third paragraph here.",
    ]


def test_recursive_split_no_paragraph_break_falls_through_to_line():
    """No `\n\n` anywhere, but internal `\n` line breaks exist -- the
    paragraph level finds nothing to split on and falls through to line."""
    text = "First line here.\nSecond line here.\nThird line here."
    assert len(text) > 25
    pieces = _recursive_split_text(text, chunk_max=25)
    assert pieces == ["First line here.", "Second line here.", "Third line here."]


def test_recursive_split_run_on_paragraph_falls_through_to_sentence():
    """No `\n\n` and no `\n` at all, but ordinary sentence punctuation
    exists -- both structural levels find nothing to split on, so the
    hierarchy falls through to the sentence level."""
    sentence = "The regional survey recorded steady conditions across the district. "
    text = (sentence * 60).strip()
    assert "\n" not in text
    assert len(text) > CHUNK_MAX

    pieces = _recursive_split_text(text, chunk_max=200)

    assert len(pieces) >= 2
    assert all(len(piece) <= 200 for piece in pieces)
    # No text lost: rejoining every piece with a space reproduces the
    # original run-on (segment_sentences strips per-sentence whitespace).
    assert " ".join(pieces) == " ".join(text.split())


def test_recursive_split_single_unsplittable_sentence_falls_through_to_char():
    """No `\n\n`, no `\n`, and no sentence-ending punctuation anywhere -- the
    hierarchy exhausts every structural level and falls back to a raw
    character split, still respecting `chunk_max` unconditionally."""
    huge_run_on = "a" * 500
    pieces = _recursive_split_text(huge_run_on, chunk_max=200)

    assert len(pieces) >= 2
    assert all(len(piece) <= 200 for piece in pieces)
    assert "".join(pieces) == huge_run_on


def test_recursive_split_empty_text_yields_no_pieces():
    assert _recursive_split_text("", chunk_max=1000) == []
    assert _recursive_split_text("   ", chunk_max=1000) == []


def test_recursive_split_text_within_max_returns_unchanged():
    text = "A short paragraph well under the cap."
    assert _recursive_split_text(text, chunk_max=1000) == [text]


# --- MAX side -------------------------------------------------------------


def test_recursive_split_text_never_exceeds_chunk_max_across_all_levels():
    """A pathological mixed text (paragraphs, some with only line breaks,
    one a giant run-on) -- every returned piece still respects chunk_max,
    regardless of which level it fell through to."""
    text = "Paragraph one is short.\n\nLine one only.\nLine two only.\nLine three only.\n\n" + (
        "Run-on sentence about the survey findings today. " * 50
    )
    pieces = _recursive_split_text(text, chunk_max=150)
    assert all(len(piece) <= 150 for piece in pieces)


def test_enforce_max_recursive_resplits_an_over_band_merged_group():
    """The MIN-side merge can push a group's joined text back over
    `chunk_max`; the recursive safety net re-splits it via the SAME
    separator hierarchy, with zero embedding calls."""
    groups = [["a" * 90], ["b" * 90], ["c" * 90]]
    result = _enforce_max_recursive(groups, chunk_max=100)
    assert all(len(" ".join(group)) <= 100 for group in result)


# --- MIN side ---------------------------------------------------------------


def test_recursive_section_chunks_coalesces_short_paragraphs_forward():
    text = "Short one.\n\nShort two.\n\nShort three, a bit longer than the rest here."
    chunks = _recursive_section_chunks(text, chunk_min=40, chunk_max=1000)
    assert len(chunks) < 3, "expected forward coalescing to merge the short paragraphs"
    for chunk in chunks[:-1]:
        assert len(chunk) >= 40


def test_recursive_section_chunks_whole_short_section_stays_below_min():
    text = "Just one short paragraph."
    chunks = _recursive_section_chunks(text, chunk_min=1000, chunk_max=3000)
    assert chunks == [text]


def test_recursive_section_chunks_never_exceeds_max():
    sentence = "The provincial survey recorded shifting conditions across districts. "
    text = (sentence * 200).strip()
    chunks = _recursive_section_chunks(text, chunk_min=CHUNK_MIN, chunk_max=CHUNK_MAX)
    assert len(chunks) >= 2
    assert all(len(chunk) <= CHUNK_MAX for chunk in chunks)


def test_recursive_section_chunks_empty_body_yields_no_chunks():
    assert _recursive_section_chunks("", chunk_min=CHUNK_MIN, chunk_max=CHUNK_MAX) == []
    assert _recursive_section_chunks("   ", chunk_min=CHUNK_MIN, chunk_max=CHUNK_MAX) == []


def test_run_chunk_recursive_min_side_merge_never_crosses_a_section_boundary(monkeypatch, tmp_path):
    """Two adjacent sections, each individually shorter than chunk_min --
    the MIN-side coalesce must never merge the tail of one section forward
    into the next section's own chunk."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections(
        {
            "Overview": ["A short overview paragraph, well under the band minimum."],
            "Details": ["A short details paragraph, also well under the band minimum."],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree)
    monkeypatch.setenv(CHUNK_MECHANISM_ENV_VAR, CHUNK_MECHANISM_RECURSIVE)

    records = run_chunk_recursive(
        source, chunks_dir=tmp_path / "chunks", chunk_min=10_000, chunk_max=CHUNK_MAX
    )

    sections_seen = {r["section"] for r in records}
    assert sections_seen == {"Overview", "Details"}
    for record in records:
        if record["section"] == "Overview":
            assert "details" not in record["text"].lower()
        if record["section"] == "Details":
            assert "overview" not in record["text"].lower()


# --- artifact parity + determinism ------------------------------------------


def test_run_chunk_recursive_writes_jsonl_with_stable_chunk_ids(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections(
        {"Introduction": ["Intro sentence one.\n\nIntro sentence two.\n\nIntro sentence three."]}
    )
    _patch_tree(monkeypatch, tmp_path, tree)
    chunks_dir = tmp_path / "chunks"

    first = run_chunk_recursive(source, chunks_dir=chunks_dir)
    second = run_chunk_recursive(source, chunks_dir=chunks_dir)

    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second]
    for record in first:
        assert set(record) == {"chunk_id", "section", "section_order", "text"}
        assert record["section"] == "Introduction"
        assert record["section_order"] == "1"


def test_run_chunk_recursive_section_then_position_order(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections(
        {
            "Overview": ["First section body sentence one.\n\nFirst section body sentence two."],
            "Details": ["Second section body sentence one.\n\nSecond section body sentence two."],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_recursive(source, chunks_dir=tmp_path / "chunks")

    orders = [r["section_order"] for r in records]
    assert orders == sorted(orders)


# --- zero-cost: no embedder, no cache, no LLM -------------------------------


def test_run_chunk_recursive_constructs_no_embedder(monkeypatch, tmp_path):
    """`run_chunk_recursive` never even calls `get_embedder`, let alone
    constructs a `_CachingEmbedder` or reads `data/chunk_cache/`."""

    def _explode(*_args, **_kwargs):
        raise AssertionError("get_embedder must never be called on the recursive path")

    monkeypatch.setattr(chunk_mod, "get_embedder", _explode)
    monkeypatch.setattr(chunk_mod.HashingEmbedder, "encode", _explode)

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections({"Overview": ["Some ordinary prose body text about the survey."]})
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_recursive(source, chunks_dir=tmp_path / "chunks")
    assert records


def test_run_chunk_recursive_never_needs_an_llm_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections({"Overview": ["A short section with a few words of body text."]})
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_recursive(source, chunks_dir=tmp_path / "chunks")
    assert records


def test_run_chunk_recursive_touches_no_chunk_cache_dir(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections({"Overview": ["Some ordinary prose body text about the survey."]})
    _patch_tree(monkeypatch, tmp_path, tree)
    cache_dir = tmp_path / "data" / "chunk_cache"
    monkeypatch.setattr(chunk_mod, "CHUNK_CACHE_DIR", cache_dir)

    run_chunk_recursive(source, chunks_dir=tmp_path / "chunks")

    assert not cache_dir.exists()


# --- default (unset selector) path is unaffected ----------------------------


def test_run_chunk_embedding_still_the_default_when_mechanism_unset(monkeypatch, tmp_path):
    monkeypatch.delenv(CHUNK_MECHANISM_ENV_VAR, raising=False)
    assert get_chunk_mechanism() != CHUNK_MECHANISM_RECURSIVE

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections({"Overview": ["Some ordinary prose body text about the survey."]})
    _patch_tree(monkeypatch, tmp_path, tree)

    records = run_chunk_embedding(
        source, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )
    assert records
