"""Inner unit tests for reviewer dispatch, verdict parsing and the spread
(issue #385, §9.4 properties 3, 4, 5)."""

from __future__ import annotations

import json

import pytest

from axial.llm import SYNTHESIZE_PASS_NAME
from axial.panel.packet import ReviewPacket
from axial.panel.review import (
    ReviewerCallFailedError,
    TooFewReviewersError,
    format_panel_report,
    review_packet,
    reviewer_pass_name,
)
from axial.panel.vendor import UnknownVendorError, VendorCollisionError


class FakeClient:
    """Minimal LLMClient stand-in: a per-pass model map and a scripted
    response queue. Records every prompt so a test can assert what a
    reviewer was and was not shown."""

    def __init__(self, models: dict[str, str], responses: list[str]):
        self._models = models
        self._responses = list(responses)
        self.prompts: list[str] = []

    def model_for_pass(self, pass_name):
        return self._models.get(pass_name, self._models.get("default", "stub/default"))

    def complete(self, prompt, pass_name=None):
        self.prompts.append(prompt)
        return self._responses.pop(0)


def _verdict(factual="strong", grounding="strong", completeness="strong", defects=()):
    return json.dumps(
        {
            "factual_correctness": factual,
            "citation_grounding": grounding,
            "completeness": completeness,
            "defects": list(defects),
        }
    )


def _packet():
    return ReviewPacket(
        brief_id="b-001",
        corpus_pin="pin-1",
        analysis_markdown="The state hollowed out its bureaucracy.",
        evidence={"src_1_intro_001": "Tax receipts fell."},
    )


def _models(reviewer_vendors=("anthropic/claude-opus-4", "openai/gpt-5", "google/gemini-3-pro")):
    models = {
        SYNTHESIZE_PASS_NAME: "deepseek/deepseek-v4-pro",
        "default": "deepseek/deepseek-v4-pro",
    }
    for index, model in enumerate(reviewer_vendors, start=1):
        models[reviewer_pass_name(index)] = model
    return models


def test_three_reviewers_each_see_the_same_packet():
    client = FakeClient(_models(), [_verdict()] * 3)
    report = review_packet(_packet(), client=client)
    assert len(report.reviewers) == 3
    assert len(set(client.prompts)) == 1, "every reviewer must judge the identical packet"


def test_fewer_than_three_reviewers_is_refused_before_any_call():
    client = FakeClient(_models(), [])
    with pytest.raises(TooFewReviewersError):
        review_packet(_packet(), client=client, n_reviewers=2)
    assert client.prompts == []


def test_a_same_vendor_reviewer_is_refused_before_any_call():
    """Property 3: the guard raises before a reviewer call is made."""
    client = FakeClient(
        _models(("deepseek/deepseek-r2", "openai/gpt-5", "google/gemini-3-pro")),
        [_verdict()] * 3,
    )
    with pytest.raises(VendorCollisionError):
        review_packet(_packet(), client=client)
    assert client.prompts == []


def test_an_undeclared_reviewer_model_is_refused_before_any_call():
    client = FakeClient(
        _models(("some-new-lab/mystery", "openai/gpt-5", "google/gemini-3-pro")),
        [_verdict()] * 3,
    )
    with pytest.raises(UnknownVendorError):
        review_packet(_packet(), client=client)
    assert client.prompts == []


def test_the_packet_is_the_whole_prompt_body():
    client = FakeClient(_models(), [_verdict()] * 3)
    review_packet(_packet(), client=client)
    prompt = client.prompts[0]
    assert "Tax receipts fell." in prompt
    assert "hollowed out its bureaucracy" in prompt


def test_spread_is_zero_on_unanimity():
    client = FakeClient(_models(), [_verdict(factual="adequate")] * 3)
    report = review_packet(_packet(), client=client)
    factual = next(d for d in report.dimensions if d.dimension == "factual_correctness")
    assert factual.aggregate == "adequate"
    assert factual.spread == 0


def test_a_split_panel_never_renders_like_a_unanimous_one():
    """Property 4: three reviewers splitting weak/adequate/strong and three
    agreeing on adequate are different results."""
    split = FakeClient(
        _models(),
        [_verdict(factual="weak"), _verdict(factual="adequate"), _verdict(factual="strong")],
    )
    unanimous = FakeClient(_models(), [_verdict(factual="adequate")] * 3)

    split_report = review_packet(_packet(), client=split)
    unanimous_report = review_packet(_packet(), client=unanimous)

    split_factual = next(d for d in split_report.dimensions if d.dimension == "factual_correctness")
    unanimous_factual = next(
        d for d in unanimous_report.dimensions if d.dimension == "factual_correctness"
    )
    assert split_factual.aggregate == unanimous_factual.aggregate == "adequate"
    assert split_factual.spread == 2
    assert unanimous_factual.spread == 0
    assert format_panel_report(split_report) != format_panel_report(unanimous_report)


def test_every_reviewer_verdict_is_kept_verbatim():
    client = FakeClient(
        _models(),
        [_verdict(factual="weak"), _verdict(factual="adequate"), _verdict(factual="strong")],
    )
    report = review_packet(_packet(), client=client)
    assert [r.bands["factual_correctness"] for r in report.reviewers] == [
        "weak",
        "adequate",
        "strong",
    ]
    assert [r.vendor for r in report.reviewers] == ["anthropic", "openai", "google"]


def test_an_unparseable_band_is_a_failed_call_not_an_imputed_score():
    client = FakeClient(_models(), [_verdict(factual="excellent"), _verdict(), _verdict()])
    with pytest.raises(ReviewerCallFailedError):
        review_packet(_packet(), client=client)


def test_an_undeclared_defect_kind_is_a_failed_call():
    client = FakeClient(
        _models(),
        [_verdict(defects=[{"claim_id": "c-1", "kind": "vibes", "note": ""}])] + [_verdict()] * 2,
    )
    with pytest.raises(ReviewerCallFailedError):
        review_packet(_packet(), client=client)


def test_report_is_untrusted_unless_the_caller_says_otherwise():
    """The harness never decides on its own that it is trustworthy; only a
    passing positive control does (property 6)."""
    client = FakeClient(_models(), [_verdict()] * 3)
    assert review_packet(_packet(), client=client).trusted is False


def test_rendered_report_always_discloses_the_referee():
    client = FakeClient(_models(), [_verdict()] * 3)
    rendered = format_panel_report(review_packet(_packet(), client=client))
    assert "NOT human expert judgement" in rendered
    assert "spread=" in rendered
