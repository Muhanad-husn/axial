"""Inner unit tests for the post-split fragment floor (issue #193, PRD §7.8
"Post-split fragment floor (#193)" / "Genuine short prose is protected
(#193)"). Complements tests/chunk/test_chunk_fragment_floor.py (the LOCKED
outer acceptance test) with unit-level coverage of the pure classification
helper `_fragment_floor_reason` and its wiring into `_write_chunk_sections`
via `run_chunk_recursive`.
"""

from __future__ import annotations

import json

from axial.chunk import _fragment_floor_reason, chunks_skips_sidecar_path, run_chunk_recursive
from axial.envelope import compute_source_id

from .conftest import patch_tree, tree_with_sections

# --- `_fragment_floor_reason`: blank-page notice ----------------------------


def test_fragment_floor_drops_exact_blank_page_notice():
    reason = _fragment_floor_reason("this page intentionally left blank")
    assert reason is not None
    assert "blank" in reason.lower()


def test_fragment_floor_drops_blank_page_notice_mixed_case_and_doubled_whitespace():
    reason = _fragment_floor_reason("This Page  Intentionally   Left Blank")
    assert reason is not None
    assert "blank" in reason.lower()


def test_fragment_floor_blank_page_reason_distinct_from_zero_alpha_reason():
    blank_reason = _fragment_floor_reason("this page intentionally left blank")
    zero_alpha_reason = _fragment_floor_reason("13).")
    assert blank_reason != zero_alpha_reason


# --- `_fragment_floor_reason`: no-alphabetic-content fragment ---------------


def test_fragment_floor_drops_digits_and_punctuation_only_fragment():
    reason = _fragment_floor_reason("13).")
    assert reason is not None
    assert "alphabetic" in reason.lower()


def test_fragment_floor_drops_bare_number():
    assert _fragment_floor_reason("6") is not None


def test_fragment_floor_drops_ellipsized_number():
    assert _fragment_floor_reason("200...") is not None


# --- protection invariant: any alphabetic word survives, length never drops -


def test_fragment_floor_keeps_genuine_short_sentence():
    assert _fragment_floor_reason("They consist essentially of three elements.") is None


def test_fragment_floor_keeps_single_short_word():
    """Length alone must never trigger a drop -- a real word, however short,
    survives."""
    assert _fragment_floor_reason("Ok.") is None


def test_fragment_floor_keeps_long_genuine_prose():
    text = "This is a long paragraph of genuine prose. " * 20
    assert _fragment_floor_reason(text) is None


def test_fragment_floor_reason_none_for_empty_string():
    assert _fragment_floor_reason("") is None


# --- wiring into `_write_chunk_sections` via `run_chunk_recursive` ---------


def test_run_chunk_recursive_drops_fragment_floor_tail_and_records_skip(monkeypatch, tmp_path):
    """Two paragraphs comfortably >= chunk_min (so neither merges into the
    other or into the tail), followed by a below-chunk_min zero-alpha tail --
    the section's own LAST piece, so the MIN-side band guard (`_enforce_min`,
    which only ever merges a below-min group FORWARD into what follows it)
    leaves it as its own isolated candidate chunk for the fragment floor to
    see, mirroring the outer test's fixture design."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    paragraph_one = "First paragraph sentence about the survey findings across districts. " * 3
    paragraph_two = "Second paragraph sentence about the survey findings across districts. " * 3
    tree = tree_with_sections(
        {"Findings": [paragraph_one, paragraph_two, "13)."]},
    )
    patch_tree(monkeypatch, tmp_path, tree)
    chunks_dir = tmp_path / "chunks"

    records = run_chunk_recursive(source, chunks_dir=chunks_dir, chunk_min=50, chunk_max=200)

    all_texts = [r["text"] for r in records]
    assert "13)." not in all_texts

    source_id = compute_source_id(source)
    skips_path = chunks_skips_sidecar_path(source_id, chunks_dir)
    assert skips_path.exists()
    skip_records = [
        json.loads(line) for line in skips_path.read_text().splitlines() if line.strip()
    ]
    reasons = [r["reason"] for r in skip_records]
    assert any("fragment floor" in r for r in reasons)
