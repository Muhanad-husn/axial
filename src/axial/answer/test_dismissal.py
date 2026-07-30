"""Inner unit tests for the instant-dismissal judge (§10.0, §9.3, issue
#491): the sharpest oracle the sim case set holds, and the one nothing in
`src/` read before this slice.
"""

from __future__ import annotations

import json

import pytest

from axial.answer.dismissal import (
    DismissalCheckFailedError,
    SelfGradingError,
    judge_instant_dismissal,
)
from axial.llm import (
    INSTANT_DISMISSAL_PASS_NAME,
    STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE_ENV_VAR,
    STUB_MODEL_BY_PASS_ENV_VAR,
    SYNTHESIZE_PASS_NAME,
    StubLLMClient,
)

RECORD = {
    "brief_id": "DEV90",
    "brief": {"case": "Syria", "request": "R?"},
    "interrogation": {"disposition": "proceed"},
    "claims": [
        {
            "claim_id": "c1",
            "text": "The state grew stronger because it survived.",
            "kind": "a",
            "grounds": [{"ref_type": "chunk", "ref_id": "x_0_a_001"}],
            "confidence": "medium",
        }
    ],
    "counter_position": {"present": False},
    "coverage_map": {},
    "confidence": {"overall_band": "low", "rationale": "r"},
}

CRITERION = "Any analysis arguing the state is stronger merely because it survived."


@pytest.fixture(autouse=True)
def _independent_judge(monkeypatch):
    """Route the judge onto a different model than synthesis, so the
    self-grading guard is satisfied for every test that is not about it."""
    monkeypatch.setenv(
        STUB_MODEL_BY_PASS_ENV_VAR,
        json.dumps({INSTANT_DISMISSAL_PASS_NAME: "an-independent-judge-model"}),
    )


def test_a_violation_is_counted_and_the_criterion_is_named(monkeypatch):
    monkeypatch.setenv(
        STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE_ENV_VAR,
        json.dumps([json.dumps({"verdict": "violation"})]),
    )
    result = judge_instant_dismissal(RECORD, [CRITERION], client=StubLLMClient())
    assert result.violations == 1
    assert result.criteria_count == 1
    assert result.violated_criteria == [CRITERION]
    assert result.rate == 1.0


def test_a_clean_answer_reports_zero_violations_over_its_real_denominator(monkeypatch):
    monkeypatch.setenv(
        STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE_ENV_VAR,
        json.dumps([json.dumps({"verdict": "no_violation"})] * 2),
    )
    result = judge_instant_dismissal(
        RECORD, [CRITERION, "A second criterion."], client=StubLLMClient()
    )
    assert result.violations == 0
    assert result.criteria_count == 2
    assert result.rate == 0.0


def test_no_criteria_makes_zero_calls_and_reports_a_null_rate():
    """A case that states no criterion has nothing to judge -- reported as a
    `None` rate, never a vacuous 0 out of 0 that reads like a clean bill."""
    client = StubLLMClient()
    result = judge_instant_dismissal(RECORD, [], client=client)
    assert client.call_count == 0
    assert result.rate is None


def test_the_generating_model_may_never_rule_on_its_own_answer(monkeypatch):
    """The guard raises BEFORE any judge call, so a self-grading
    configuration costs nothing rather than producing a worthless number."""
    same_model = StubLLMClient().model_for_pass(SYNTHESIZE_PASS_NAME)
    monkeypatch.setenv(
        STUB_MODEL_BY_PASS_ENV_VAR, json.dumps({INSTANT_DISMISSAL_PASS_NAME: same_model})
    )
    client = StubLLMClient()
    with pytest.raises(SelfGradingError):
        judge_instant_dismissal(RECORD, [CRITERION], client=client)
    assert client.call_count == 0


def test_an_unparseable_verdict_is_a_named_error_not_a_silent_no_violation(monkeypatch):
    monkeypatch.setenv(
        STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE_ENV_VAR,
        json.dumps([json.dumps({"verdict": "maybe"})]),
    )
    with pytest.raises(DismissalCheckFailedError):
        judge_instant_dismissal(RECORD, [CRITERION], client=StubLLMClient())
