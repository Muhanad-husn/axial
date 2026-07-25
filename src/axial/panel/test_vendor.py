"""Inner unit tests for the different-vendor bar (issue #385, §9.4
property 3)."""

from __future__ import annotations

import pytest

from axial.panel.vendor import (
    UnknownVendorError,
    VendorCollisionError,
    guard_distinct_vendor,
    vendor_of,
)


def test_vendor_of_reads_the_publisher_segment():
    assert vendor_of("anthropic/claude-opus-4") == "anthropic"
    assert vendor_of("deepseek/deepseek-v4-pro") == "deepseek"


def test_vendor_of_is_case_folded():
    assert vendor_of("DeepSeek/DeepSeek-V4") == "deepseek"


def test_publisher_is_not_assumed_to_be_the_lab():
    """`z-ai` is Zhipu. The table exists precisely because the publisher
    segment is not always the training lab."""
    assert vendor_of("z-ai/glm-5.2") == "zhipu"
    assert vendor_of("zhipuai/glm-4") == "zhipu"


def test_unknown_model_is_a_hard_error_not_an_assumed_distinct_default():
    """The whole point of the bar: defaulting an unrecognised id to
    'probably different' would let a family-mate through silently."""
    with pytest.raises(UnknownVendorError):
        vendor_of("some-new-lab/mystery-model-v1")


def test_empty_model_id_raises():
    with pytest.raises(UnknownVendorError):
        vendor_of("")


def test_guard_passes_across_vendors():
    vendor = guard_distinct_vendor(
        reviewer_model="anthropic/claude-opus-4",
        generating_model="deepseek/deepseek-v4-pro",
    )
    assert vendor == "anthropic"


def test_guard_rejects_a_same_vendor_reviewer():
    with pytest.raises(VendorCollisionError):
        guard_distinct_vendor(
            reviewer_model="deepseek/deepseek-r2",
            generating_model="deepseek/deepseek-v4-pro",
        )


def test_guard_rejects_a_family_mate_that_a_different_model_id_check_would_pass():
    """Strictly stronger than the five gates' SelfGradingError, which only
    requires a different model id."""
    reviewer, generator = "z-ai/glm-5.2", "zhipuai/glm-4"
    assert reviewer != generator
    with pytest.raises(VendorCollisionError):
        guard_distinct_vendor(reviewer_model=reviewer, generating_model=generator)
