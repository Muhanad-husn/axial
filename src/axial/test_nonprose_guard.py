"""Unit tests for the shared non-prose input guard (issue #132)."""

from __future__ import annotations

from axial.nonprose_guard import MAX_CHARS, MAX_NON_ALPHA_RATIO, non_prose_skip_reason


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
