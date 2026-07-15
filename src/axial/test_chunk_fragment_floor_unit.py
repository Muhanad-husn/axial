"""Inner unit tests for the post-split fragment floor (issue #193,
generalized in #197; PRD §7.8 "Post-split fragment floor (#193, generalized
in #197)" / "Genuine short prose is protected (#193)"). Complements
tests/chunk/test_chunk_fragment_floor.py and
tests/chunk/test_chunk_low_alpha_floor.py (the LOCKED outer acceptance
tests) with unit-level coverage of the pure classification helper
`_fragment_floor_reason` and its wiring into `_write_chunk_sections` via
`run_chunk_recursive`.
"""

from __future__ import annotations

import json

from axial.chunk import (
    LOW_ALPHA_RATIO_THRESHOLD,
    _fragment_floor_reason,
    chunks_skips_sidecar_path,
    run_chunk_recursive,
)
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


# --- `_fragment_floor_reason`: low-alpha-ratio band (0 < ratio < 0.45, #197) -


def test_fragment_floor_drops_bare_citation_crumb_in_new_low_alpha_band():
    """`"Berman 1996: 78 )."` has alphabetic ratio 6/18 ~= 0.33 -- nonzero,
    so #193's old zero-alpha-only rule would NOT have caught it, but it
    still sits below the 0.45 threshold and must drop under #197's
    generalized ratio test."""
    text = "Berman 1996: 78 )."
    ratio = sum(1 for c in text if c.isalpha()) / len(text)
    assert 0 < ratio < LOW_ALPHA_RATIO_THRESHOLD
    reason = _fragment_floor_reason(text)
    assert reason is not None
    assert "alphabetic" in reason.lower()


def test_fragment_floor_reason_distinct_from_apparatus_and_garble_families():
    """The low-alpha reason must stay distinct from the pre-existing
    apparatus (`"apparatus: ..."`) and garble-backstop (`"high non-alpha
    ratio (...)"`) reason families (§7.8)."""
    reason = _fragment_floor_reason("Berman 1996: 78 ).")
    assert reason is not None
    assert not reason.startswith("apparatus:")
    assert not reason.startswith("high non-alpha ratio")


def test_fragment_floor_boundary_just_below_threshold_drops():
    """A ratio just under the threshold must still drop."""
    # 8 alpha chars out of 18 total = 0.4444... < 0.45.
    text = "abcdefgh__________"[:18]
    ratio = sum(1 for c in text if c.isalpha()) / len(text)
    assert ratio < LOW_ALPHA_RATIO_THRESHOLD
    assert _fragment_floor_reason(text) is not None


def test_fragment_floor_boundary_at_threshold_is_kept():
    """A ratio exactly at the threshold must be kept -- the drop condition
    is strictly `< LOW_ALPHA_RATIO_THRESHOLD`, never `<=`."""
    # 9 alpha chars out of 20 total = 0.45 exactly.
    text = "abcdefghi" + "_" * 11
    assert len(text) == 20
    ratio = sum(1 for c in text if c.isalpha()) / len(text)
    assert ratio == LOW_ALPHA_RATIO_THRESHOLD
    assert _fragment_floor_reason(text) is None


# --- protection invariant: any alphabetic word survives, length never drops -


def test_fragment_floor_keeps_genuine_short_sentence():
    assert _fragment_floor_reason("They consist essentially of three elements.") is None


def test_fragment_floor_keeps_protected_sentence_above_low_alpha_threshold():
    """`"Yet, the U.S."` has alphabetic ratio 8/13 ~= 0.6154 -- above the
    0.45 threshold -- and must survive verbatim, however short (PRD §7.8's
    own protected worked example)."""
    text = "Yet, the U.S."
    ratio = sum(1 for c in text if c.isalpha()) / len(text)
    assert ratio >= LOW_ALPHA_RATIO_THRESHOLD
    assert _fragment_floor_reason(text) is None


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
