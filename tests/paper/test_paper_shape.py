"""Unit tests for `axial.paper.shape`, the post-draft shape check (specs/
PHASE-C.md §7.16, issue #578).

Covers the eight acceptance criteria at the function level: one call
regardless of section count is pinned in `test_paper_pipeline.py` (where
`run_paper` actually drives it); this file pins the check's own contract --
parsing, the self-grading guard, and the prompt carrying the plan's stated
intent.
"""

from __future__ import annotations

import json

import pytest

from axial.paper.shape import (
    ShapeDefect,
    ShapeParseError,
    SelfGradingError,
    compose_shape_prompt,
    parse_shape_response,
    run_shape_check,
)


def _sections():
    return [
        {"section_id": "s1", "heading": "Setup", "role": "setup", "prose": "..."},
        {
            "section_id": "s2",
            "heading": "The case against",
            "role": "counter-position",
            "prose": "...",
        },
    ]


class _StubClient:
    """Mirrors the paper-pipeline tests' own stub shape (model_for_pass,
    usage_for_pass, complete) without depending on that file."""

    def __init__(self, model_by_pass, response):
        self.model_by_pass = model_by_pass
        self._response = response
        self.prompts: list[tuple[str, str]] = []

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)

    def usage_for_pass(self, pass_name=None):
        return {"prompt_tokens": 100, "completion_tokens": 50}

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        return json.dumps(self._response)


def test_a_strong_band_needs_no_defects():
    band, defects, title = parse_shape_response(json.dumps({"band": "strong", "defects": []}))
    assert band == "strong"
    assert defects == []
    assert title is None


def test_a_weak_band_with_a_named_defect_parses():
    band, defects, _title = parse_shape_response(
        json.dumps(
            {"band": "weak", "defects": [{"section_id": "s2", "note": "reads as a summary"}]}
        )
    )
    assert band == "weak"
    assert defects == [ShapeDefect(section_id="s2", note="reads as a summary")]


def test_a_weak_band_with_an_empty_defect_list_is_a_parse_error_not_a_pass():
    """Issue #578 acceptance criterion 3, stated explicitly."""
    with pytest.raises(ShapeParseError):
        parse_shape_response(json.dumps({"band": "weak", "defects": []}))


def test_an_adequate_band_with_no_defects_key_at_all_is_a_parse_error():
    with pytest.raises(ShapeParseError):
        parse_shape_response(json.dumps({"band": "adequate"}))


def test_an_out_of_vocabulary_band_is_a_parse_error():
    with pytest.raises(ShapeParseError):
        parse_shape_response(json.dumps({"band": "excellent", "defects": []}))


def test_a_defect_naming_no_section_id_is_a_parse_error():
    with pytest.raises(ShapeParseError):
        parse_shape_response(json.dumps({"band": "weak", "defects": [{"note": "no id"}]}))


def test_the_prompt_carries_the_thesis_and_every_sections_assigned_role():
    prompt = compose_shape_prompt("Organized challengers explain the outcome.", _sections())
    assert "Organized challengers explain the outcome." in prompt
    assert "assigned role: setup" in prompt
    assert "assigned role: counter-position" in prompt


def test_a_plan_with_different_roles_produces_a_different_prompt():
    """Acceptance criterion 2: same prose, different roles, different prompt."""
    same_prose_sections = [
        {"section_id": "s1", "heading": "X", "role": "claim", "prose": "same text"},
    ]
    other_role_sections = [
        {"section_id": "s1", "heading": "X", "role": "evidence", "prose": "same text"},
    ]
    first = compose_shape_prompt("thesis", same_prose_sections)
    second = compose_shape_prompt("thesis", other_role_sections)
    assert first != second


def test_the_rubric_scores_a_synthesis_verdict_as_success_not_overreach():
    """The whole reason #577 had to land before this issue: a `synthesis`
    section reaching the paper's own verdict must read as the section doing
    its job, not as speculation beyond the evidence."""
    prompt = compose_shape_prompt("thesis", _sections())
    assert "THAT IS SUCCESS, never overreach" in prompt


def test_the_prompt_requires_section_by_section_reasoning_before_the_band():
    """Issue #600: calibrated against planted defects, the bare-band prompt
    (just `{"band", "defects"}`) caught 1 of 12 planted defects across four
    replicates each (data/logs/2026-08-02-shape-check-calibration/). Asking
    for one sentence of reasoning per section BEFORE the band raised that to
    6 of 12, with the response schema still asking for `band` and `defects`
    after the per-section review. This pins the prompt shape the calibration
    measured against, not the model's actual sensitivity -- a live model
    check is what data/logs holds; this is a fast, deterministic guard
    against silently reverting to a bare-band prompt."""
    prompt = compose_shape_prompt("thesis", _sections())
    assert "section_review" in prompt
    assert "before naming a band" in prompt.lower()
    # The instruction to review every section, not just suspected ones,
    # is what keeps a diligent-looking "strong" from being a skipped check.
    assert "not just ones you suspect are weak" in prompt
    # The example response still shows band/defects after the review --
    # the persisted record's contract (§7.3 `shape`) is unchanged.
    section_review_pos = prompt.index('"section_review"')
    band_pos = prompt.rindex('"band"')
    assert section_review_pos < band_pos


def test_a_response_carrying_section_review_still_parses_to_only_band_and_defects():
    """The new `section_review` field is scratch work for the model, never
    persisted (§7.3's `shape` record is unchanged: `band`, `defects`,
    `model`, `cost`). `parse_shape_response` must accept and ignore it."""
    raw = json.dumps(
        {
            "section_review": [
                {"section_id": "s1", "meets_bar": True, "reason": "orients toward the thesis"},
                {"section_id": "s2", "meets_bar": False, "reason": "states a weak foil"},
            ],
            "band": "weak",
            "defects": [{"section_id": "s2", "note": "weak foil, not the strongest case"}],
        }
    )
    band, defects, _title = parse_shape_response(raw)
    assert band == "weak"
    assert defects == [ShapeDefect(section_id="s2", note="weak foil, not the strongest case")]


def test_self_grading_raises_before_any_call_and_names_both_passes():
    client = _StubClient(
        {"paper_draft": "same/model", "paper_shape": "same/model"},
        {"band": "strong", "defects": []},
    )
    with pytest.raises(SelfGradingError) as excinfo:
        run_shape_check(client, "thesis", _sections())

    assert "paper_shape" in str(excinfo.value)
    assert "paper_draft" in str(excinfo.value)
    # Zero calls made when the guard fires.
    assert client.prompts == []


def test_a_different_model_lets_the_check_run_and_reports_model_and_cost():
    client = _StubClient(
        {"paper_draft": "drafter/model", "paper_shape": "judge/model"},
        {"band": "adequate", "defects": [{"section_id": "s2", "note": "weak steelman"}]},
    )
    result = run_shape_check(client, "thesis", _sections())

    assert result.band == "adequate"
    assert result.defects == (ShapeDefect(section_id="s2", note="weak steelman"),)
    assert result.model == "judge/model"
    assert len(client.prompts) == 1 and client.prompts[0][0] == "paper_shape"
    # "judge/model" carries no PRICE_TABLE_USD_PER_1K entry, so cost is
    # `None` -- never a fabricated zero (mirrors `estimate_cost`'s own
    # unpriced-model convention).
    assert result.cost is None
    # No title in this response -- lenient parsing, not a raise (issue #712).
    assert result.title is None


# -- Title (issue #712): the shape check names the finished paper -----------
#
# `compose_shape_prompt` asks for a title costing zero additional model
# calls; `parse_shape_response` never raises on a bad one, because a title
# is not worth turning a graded paper into a failed run (§7.16 reports, it
# never blocks).


def test_the_prompt_asks_for_a_title_after_band_and_defects():
    prompt = compose_shape_prompt("thesis", _sections())
    assert "title" in prompt.lower()
    band_pos = prompt.rindex('"band"')
    defects_pos = prompt.rindex('"defects"')
    title_pos = prompt.rindex('"title"')
    assert band_pos < title_pos
    assert defects_pos < title_pos


def test_a_present_title_is_parsed_and_stripped():
    band, defects, title = parse_shape_response(
        json.dumps({"band": "strong", "defects": [], "title": "  Organized Challengers Win  "})
    )
    assert band == "strong"
    assert defects == []
    assert title == "Organized Challengers Win"


def test_run_shape_check_carries_the_judges_title_onto_the_result():
    client = _StubClient(
        {"paper_draft": "drafter/model", "paper_shape": "judge/model"},
        {"band": "strong", "defects": [], "title": "Organized Challengers Win"},
    )
    result = run_shape_check(client, "thesis", _sections())
    assert result.title == "Organized Challengers Win"
    assert result.to_json()["title"] == "Organized Challengers Win"


@pytest.mark.parametrize(
    "raw_title",
    [None, "", "   ", 42, [], {"text": "a title"}],
    ids=["missing", "empty", "blank", "non-string-int", "non-string-list", "non-string-dict"],
)
def test_a_missing_or_unusable_title_falls_back_to_none_without_raising(raw_title):
    response = {"band": "strong", "defects": []}
    if raw_title is not None:
        response["title"] = raw_title
    band, defects, title = parse_shape_response(json.dumps(response))
    assert band == "strong"
    assert title is None
