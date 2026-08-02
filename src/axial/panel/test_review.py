"""Inner unit tests for reviewer dispatch, verdict parsing and the spread
(issue #385, §9.4 properties 3, 4, 5)."""

from __future__ import annotations

import json

import pytest

from axial.llm import SYNTHESIZE_PASS_NAME
from axial.panel.packet import PaperReviewPacket, ReviewPacket
from axial.panel.review import (
    DIMENSIONS,
    PAPER_DIMENSIONS,
    PanelError,
    ReviewerCallFailedError,
    TooFewReviewersError,
    format_panel_report,
    review_packet,
    review_paper_packet,
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


def test_analysis_dimensions_are_unaffected_by_the_coherence_addition():
    """§8 P0-10 observable: an analysis packet still scores exactly the
    original three dimensions."""
    assert DIMENSIONS == ("factual_correctness", "citation_grounding", "completeness")
    client = FakeClient(_models(), [_verdict()] * 3)
    report = review_packet(_packet(), client=client)
    assert {d.dimension for d in report.dimensions} == set(DIMENSIONS)
    assert "coherence" not in {d.dimension for d in report.dimensions}


# -- the paper reviewer path (issue #611, specs/PHASE-C.md §7.7/§7.8) --------


def _paper_verdict(coherence="strong", defects=()):
    return json.dumps(
        {
            "factual_correctness": "strong",
            "citation_grounding": "strong",
            "completeness": "strong",
            "coherence": coherence,
            "defects": list(defects),
        }
    )


def _paper_packet():
    return PaperReviewPacket(
        paper_brief_id="pb-001",
        corpus_pin="pin-1",
        packet_id="paper-packet:pb-001",
        paper_markdown="The bureaucracy hollowed out.",
        cited_evidence=(
            {
                "paper_claim_id": "pc-001",
                "kind": "a",
                "confidence": "medium",
                "grounds": [{"ref_id": "src_1_intro_001", "text": "Tax receipts fell."}],
            },
        ),
        bibliography=(),
    )


def _paper_model_by_pass():
    return {"paper_draft": "deepseek/deepseek-v4-pro", "paper_plan": "z-ai/glm-5.2"}


class PaperFakeClient(FakeClient):
    """Three independent-vendor reviewers, distinct from both of
    `_paper_model_by_pass`'s generating models."""

    _REVIEWER_VENDORS = ("anthropic/claude-opus-4", "openai/gpt-5", "google/gemini-3-pro")

    def model_for_pass(self, pass_name):
        models = {
            reviewer_pass_name(index): model
            for index, model in enumerate(self._REVIEWER_VENDORS, start=1)
        }
        return models.get(pass_name, self._models.get("default", "stub/default"))


def test_paper_reviewer_scores_the_coherence_dimension():
    client = PaperFakeClient({}, [_paper_verdict()] * 3)
    report = review_paper_packet(
        _paper_packet(), client=client, model_by_pass=_paper_model_by_pass()
    )
    assert {d.dimension for d in report.dimensions} == set(PAPER_DIMENSIONS)
    coherence = next(d for d in report.dimensions if d.dimension == "coherence")
    assert coherence.aggregate == "strong"


def test_paper_reviewer_report_is_keyed_on_the_paper_brief_id():
    client = PaperFakeClient({}, [_paper_verdict()] * 3)
    report = review_paper_packet(
        _paper_packet(), client=client, model_by_pass=_paper_model_by_pass()
    )
    assert report.brief_id == "pb-001"


def test_paper_reviewer_defect_vocabulary_accepts_arc_break_with_a_section_id():
    defects = [{"claim_id": "", "section_id": "s2", "kind": "arc_break", "note": "non sequitur"}]
    client = PaperFakeClient({}, [_paper_verdict(defects=defects)] + [_paper_verdict()] * 2)
    report = review_paper_packet(
        _paper_packet(), client=client, model_by_pass=_paper_model_by_pass()
    )
    defect = report.reviewers[0].defects[0]
    assert defect.kind == "arc_break"
    assert defect.section_id == "s2"


def test_paper_reviewer_defect_vocabulary_accepts_unmarked_inference():
    defects = [{"claim_id": "pc-001", "kind": "unmarked_inference", "note": "reads as a source"}]
    client = PaperFakeClient({}, [_paper_verdict(defects=defects)] + [_paper_verdict()] * 2)
    report = review_paper_packet(
        _paper_packet(), client=client, model_by_pass=_paper_model_by_pass()
    )
    assert report.reviewers[0].defects[0].kind == "unmarked_inference"


def test_a_reviewer_sharing_the_drafting_models_vendor_is_refused_before_any_call():
    """The vendor guard checks BOTH generating passes -- here the reviewer
    collides with paper_draft."""
    client = PaperFakeClient({}, [_paper_verdict()] * 3)
    model_by_pass = {"paper_draft": "anthropic/claude-opus-4", "paper_plan": "z-ai/glm-5.2"}
    with pytest.raises(VendorCollisionError):
        review_paper_packet(_paper_packet(), client=client, model_by_pass=model_by_pass)
    assert client.prompts == []


def test_a_reviewer_sharing_the_planning_models_vendor_is_refused_before_any_call():
    """Same guard, the other generating pass -- a reviewer that only avoids
    paper_draft's vendor is not enough."""
    client = PaperFakeClient({}, [_paper_verdict()] * 3)
    model_by_pass = {"paper_draft": "deepseek/deepseek-v4-pro", "paper_plan": "openai/gpt-5"}
    with pytest.raises(VendorCollisionError):
        review_paper_packet(_paper_packet(), client=client, model_by_pass=model_by_pass)
    assert client.prompts == []


def test_a_paper_reviewer_needs_at_least_one_generating_model_to_guard_against():
    client = PaperFakeClient({}, [])
    with pytest.raises(PanelError):
        review_paper_packet(_paper_packet(), client=client, model_by_pass={})
    assert client.prompts == []
