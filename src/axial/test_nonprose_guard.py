"""Unit tests for the shared non-prose input guard (issue #132)."""

from __future__ import annotations

from axial.nonprose_guard import MAX_CHARS, garble_only_skip_reason, non_prose_skip_reason


def test_normal_prose_is_not_skipped():
    assert non_prose_skip_reason("Ordinary prose, well under both thresholds.") is None


def test_empty_text_is_not_skipped():
    assert non_prose_skip_reason("") is None


def test_oversized_text_is_skipped_with_size_reason():
    text = "a" * (MAX_CHARS + 1)
    reason = non_prose_skip_reason(text)
    assert reason is not None
    assert "exceeds size limit" in reason


def test_text_at_exactly_max_chars_is_not_skipped_on_size_alone():
    text = "a" * MAX_CHARS
    assert non_prose_skip_reason(text) is None


def test_high_non_alpha_ratio_text_is_skipped_with_ratio_reason():
    # 1000 chars, mostly digits/punctuation -- well over the ratio threshold,
    # well under the size threshold.
    text = "1, 2, 3; " * 200
    reason = non_prose_skip_reason(text)
    assert reason is not None
    assert "high non-alpha ratio" in reason


def test_thresholds_are_overridable():
    text = "abc12"  # 2/5 = 0.4 non-alpha, at the default threshold exactly
    assert non_prose_skip_reason(text) is None
    assert non_prose_skip_reason(text, max_non_alpha_ratio=0.1) is not None
    assert non_prose_skip_reason(text, max_chars=4) is not None


# --- garble_only_skip_reason (issue #169, source-router slice 04) ---------


def test_garble_only_normal_prose_is_not_skipped():
    assert garble_only_skip_reason("Ordinary prose, well under the ratio threshold.") is None


def test_garble_only_empty_text_is_not_skipped():
    assert garble_only_skip_reason("") is None


def test_garble_only_never_skips_on_size_alone():
    # Large, low-non-alpha prose: non_prose_skip_reason's size arm would
    # skip this; garble_only_skip_reason must never skip on size.
    text = "The council debated policy long into the night. " * 1000
    assert len(text) > MAX_CHARS
    assert garble_only_skip_reason(text) is None


def test_garble_only_still_skips_high_non_alpha_ratio_text():
    text = "1, 2, 3; " * 200
    reason = garble_only_skip_reason(text)
    assert reason is not None
    assert "high non-alpha ratio" in reason


def test_garble_only_ratio_threshold_is_overridable():
    text = "abc12"  # 2/5 = 0.4 non-alpha, at the default threshold exactly
    assert garble_only_skip_reason(text) is None
    assert garble_only_skip_reason(text, max_non_alpha_ratio=0.1) is not None
