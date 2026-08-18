"""Arc planning's length allocation (specs/PHASE-C.md §7.2, issue #787 slice
02). A paper brief may declare `target_words`; when it does, the planner is
asked to allocate a per-section share, and the parsed `Plan` carries each
section's `word_budget`. Nothing here truncates anything -- allocation is the
planner's decision, made before a drafting dollar is spent, exactly like the
rest of the arc.
"""

import json

import pytest

from axial.paper.intake import InventoryClaim, PaperIntake
from axial.paper.lens import resolve_lens
from axial.paper.plan import (
    COUNTER_POSITION_ROLE,
    PlanParseError,
    Section,
    compose_plan_prompt,
    parse_plan_response,
)

BRIEF_ID = "fd0c2636d456d0fc"
CLAIM_A = "2a395ce341f1ddee"
CLAIM_B = "71ccf81d2b99bad6"


def _intake() -> PaperIntake:
    inventory = (
        InventoryClaim(
            brief_id=BRIEF_ID,
            claim_id=CLAIM_A,
            claim={"kind": "a", "confidence": "high", "text": "First claim."},
        ),
        InventoryClaim(
            brief_id=BRIEF_ID,
            claim_id=CLAIM_B,
            claim={"kind": "a", "confidence": "high", "text": "Second claim."},
        ),
    )
    return PaperIntake(
        corpus_pin="sim-2026-07-26",
        source_analyses=(BRIEF_ID,),
        records={BRIEF_ID: {"claims": [entry.claim for entry in inventory]}},
        inventory=inventory,
    )


def _plan_json(sections: list[dict]) -> str:
    return json.dumps({"thesis_statement": "The paper's own sentence.", "sections": sections})


def _section(section_id, heading, role, claim_id, word_budget=None):
    entry = {
        "section_id": section_id,
        "heading": heading,
        "role": role,
        "assigned_claims": [{"brief_id": BRIEF_ID, "claim_id": claim_id}],
    }
    if word_budget is not None:
        entry["word_budget"] = word_budget
    return entry


def test_compose_plan_prompt_without_a_target_says_nothing_about_length():
    prompt = compose_plan_prompt("A thesis.", resolve_lens("political-economy"), _intake())
    assert "word_budget" not in prompt
    assert "target length" not in prompt


def test_compose_plan_prompt_with_a_target_states_it_and_asks_for_a_share():
    prompt = compose_plan_prompt(
        "A thesis.", resolve_lens("political-economy"), _intake(), target_words=3000
    )
    assert "3000" in prompt
    assert "word_budget" in prompt
    # The counter-position section is named, not left to be squeezed by default.
    assert COUNTER_POSITION_ROLE in prompt.split("word_budget")[1][:600] or "smallest share" in prompt


def test_a_plan_with_budgets_summing_to_the_target_parses_and_carries_them():
    sections = [
        _section("s1", "The claim", "claim", CLAIM_A, word_budget=1500),
        _section("s2", "The case against", COUNTER_POSITION_ROLE, CLAIM_B, word_budget=1500),
    ]
    plan = parse_plan_response(_plan_json(sections), _intake(), target_words=3000)

    assert plan.sections[0].word_budget == 1500
    assert plan.sections[1].word_budget == 1500
    assert sum(section.word_budget for section in plan.sections) == 3000
    assert plan.to_json()["sections"][0]["word_budget"] == 1500


def test_a_plan_response_with_no_target_carries_no_word_budget_key():
    sections = [
        _section("s1", "The claim", "claim", CLAIM_A),
        _section("s2", "The case against", COUNTER_POSITION_ROLE, CLAIM_B),
    ]
    plan = parse_plan_response(_plan_json(sections), _intake())

    assert plan.sections[0].word_budget is None
    assert "word_budget" not in plan.to_json()["sections"][0]


def test_a_target_set_but_a_section_missing_its_budget_is_rejected():
    sections = [
        _section("s1", "The claim", "claim", CLAIM_A, word_budget=3000),
        _section("s2", "The case against", COUNTER_POSITION_ROLE, CLAIM_B),  # no budget
    ]
    with pytest.raises(PlanParseError):
        parse_plan_response(_plan_json(sections), _intake(), target_words=3000)


def test_budgets_that_do_not_sum_to_the_target_are_rejected():
    sections = [
        _section("s1", "The claim", "claim", CLAIM_A, word_budget=1000),
        _section("s2", "The case against", COUNTER_POSITION_ROLE, CLAIM_B, word_budget=1000),
    ]
    with pytest.raises(PlanParseError) as excinfo:
        parse_plan_response(_plan_json(sections), _intake(), target_words=3000)
    assert "3000" in str(excinfo.value)


def test_the_counter_position_section_is_never_the_smallest_share():
    """The floor this slice ships: a counter-position section's own budget
    must never come in below the smallest share any other section carries --
    the failure mode named in the plan is a tight budget crushing the
    counter-position section first."""
    sections = [
        _section("s1", "The claim", "claim", CLAIM_A, word_budget=2500),
        _section("s2", "The case against", COUNTER_POSITION_ROLE, CLAIM_B, word_budget=500),
    ]
    with pytest.raises(PlanParseError) as excinfo:
        parse_plan_response(_plan_json(sections), _intake(), target_words=3000)
    assert "counter-position" in str(excinfo.value)


def test_an_equal_share_for_the_counter_position_is_not_a_violation():
    sections = [
        _section("s1", "The claim", "claim", CLAIM_A, word_budget=1500),
        _section("s2", "The case against", COUNTER_POSITION_ROLE, CLAIM_B, word_budget=1500),
    ]
    # No raise: a tie is not "the smallest share".
    plan = parse_plan_response(_plan_json(sections), _intake(), target_words=3000)
    assert plan.sections[1].word_budget == 1500


def test_section_to_json_omits_word_budget_when_none():
    section = Section(section_id="s1", heading="h", role="setup")
    assert "word_budget" not in section.to_json()


def test_section_to_json_carries_word_budget_when_set():
    section = Section(section_id="s1", heading="h", role="setup", word_budget=400)
    assert section.to_json()["word_budget"] == 400
