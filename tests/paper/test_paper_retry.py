"""Bounded retry on a validator rejection (specs/PHASE-C.md §7.2, §7.17,
issue #598).

Phase C feeds a non-deterministic generator into strict validators with no
retry anywhere: a single rejected plan or draft used to abort the whole run
and discard every call before it. This pins the fix -- a rejected response is
re-asked with the error text appended, never repaired -- and its two hard
boundaries: the plan's counter-position guard is explicitly NOT retried, and
giving up after the bound still raises exactly the validator's own error.
"""

from __future__ import annotations

import json

import pytest

from axial.paper.draft import (
    DraftParseError,
    InvalidNewClaimKindError,
    Section as DraftSection,
    draft_section,
)
from axial.paper.intake import InventoryClaim, PaperIntake
from axial.paper.lens import resolve_lens
from axial.paper.plan import (
    EmptySectionError,
    MissingCounterPositionError,
    run_plan,
)

BRIEF_ID = "brief-a"
CLAIM_A = "claim-a"
CLAIM_B = "claim-b"
LENS = resolve_lens("political-economy")


def _intake(with_counter_claim: bool = True) -> PaperIntake:
    claims = [
        InventoryClaim(
            brief_id=BRIEF_ID,
            claim_id=CLAIM_A,
            claim={"kind": "a", "confidence": "high", "text": "War made the state."},
        ),
    ]
    if with_counter_claim:
        claims.append(
            InventoryClaim(
                brief_id=BRIEF_ID,
                claim_id=CLAIM_B,
                claim={"kind": "a", "confidence": "medium", "text": "Mobilization mattered too."},
            )
        )
    inventory = tuple(claims)
    return PaperIntake(
        corpus_pin="sim-2026-08-02",
        source_analyses=(BRIEF_ID,),
        records={
            BRIEF_ID: {
                "claims": [entry.claim for entry in inventory],
                "counter_position": {"present": False, "corpus_one_sided": False},
            }
        },
        inventory=inventory,
    )


def _valid_plan_json() -> str:
    """A plan with a `setup` and a `counter-position` section -- passes both
    `parse_plan_response` and `validate_plan`."""
    return json.dumps(
        {
            "thesis_statement": "The paper's own sentence.",
            "sections": [
                {"section_id": "s1", "heading": "Setup", "role": "setup", "assigned_claims": []},
                {
                    "section_id": "s2",
                    "heading": "The case against",
                    "role": "counter-position",
                    "assigned_claims": [{"brief_id": BRIEF_ID, "claim_id": CLAIM_A}],
                },
            ],
        }
    )


def _empty_section_plan_json() -> str:
    """Section `s2` carries role `claim` (not `setup`) and no assigned
    claims -- the exact §7.2 rule issue #598 measured failing 2 of 7 draws."""
    return json.dumps(
        {
            "thesis_statement": "The paper's own sentence.",
            "sections": [
                {"section_id": "s1", "heading": "Setup", "role": "setup", "assigned_claims": []},
                {"section_id": "s2", "heading": "Starved", "role": "claim", "assigned_claims": []},
            ],
        }
    )


def _no_counter_position_plan_json() -> str:
    """Well-formed and every claim assigned, but carries no `counter-position`
    section and the one named record does not disclose one-sidedness --
    `MissingCounterPositionError`, raised by `validate_plan` rather than the
    parser."""
    return json.dumps(
        {
            "thesis_statement": "The paper's own sentence.",
            "sections": [
                {
                    "section_id": "s1",
                    "heading": "The claim",
                    "role": "claim",
                    "assigned_claims": [{"brief_id": BRIEF_ID, "claim_id": CLAIM_A}],
                },
            ],
        }
    )


class _QueueClient:
    """Returns one queued response per call to a given `pass_name`, in
    order, and records every prompt sent."""

    def __init__(self, responses: dict[str, list[str]]):
        self._responses = {name: list(queue) for name, queue in responses.items()}
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        return self._responses[pass_name].pop(0)

    def model_for_pass(self, pass_name=None):
        return f"stub/{pass_name}"

    def usage_for_pass(self, pass_name=None):
        return None


# ---------------------------------------------------------------------------
# Planning (plan.py)
# ---------------------------------------------------------------------------


def test_run_plan_retries_once_on_an_empty_section_error():
    client = _QueueClient({"paper_plan": [_empty_section_plan_json(), _valid_plan_json()]})

    plan = run_plan(client, "A thesis.", LENS, _intake())

    assert len(client.prompts) == 2
    assert plan.retries == 1
    assert plan.sections[1].role == "counter-position"


def test_the_retry_prompt_carries_the_rejected_attempts_error_text():
    client = _QueueClient({"paper_plan": [_empty_section_plan_json(), _valid_plan_json()]})

    run_plan(client, "A thesis.", LENS, _intake())

    first_prompt = client.prompts[0][1]
    second_prompt = client.prompts[1][1]
    # Not a repair loop: the retry is the ORIGINAL prompt plus the error,
    # never a patched version of the rejected plan.
    assert second_prompt.startswith(first_prompt)
    assert "no assigned claims" in second_prompt
    assert "attempt 1 of 3" in second_prompt


def test_run_plan_gives_up_after_the_bound_and_raises_the_validators_own_error():
    client = _QueueClient(
        {"paper_plan": [_empty_section_plan_json()] * 3}  # every draw fails the same way
    )

    with pytest.raises(EmptySectionError):
        run_plan(client, "A thesis.", LENS, _intake())

    assert len(client.prompts) == 3  # first attempt + two re-asks, no more


def test_run_plan_does_not_retry_the_counter_position_guard():
    """Issue #598 explicitly scopes retry to four parse/assignment errors and
    excludes `MissingCounterPositionError`, which `validate_plan` raises only
    after a parse already succeeded."""
    client = _QueueClient({"paper_plan": [_no_counter_position_plan_json()]})

    with pytest.raises(MissingCounterPositionError):
        run_plan(client, "A thesis.", LENS, _intake())

    assert len(client.prompts) == 1  # never re-asked


def test_a_rejected_plan_attempt_logs_pass_attempt_and_validator(capsys):
    client = _QueueClient({"paper_plan": [_empty_section_plan_json(), _valid_plan_json()]})

    run_plan(client, "A thesis.", LENS, _intake())

    err = capsys.readouterr().err
    assert "paper_retry" in err
    assert "pass=paper_plan" in err
    assert "attempt=1/3" in err
    assert "validator=EmptySectionError" in err


# ---------------------------------------------------------------------------
# Drafting (draft.py)
# ---------------------------------------------------------------------------

SECTION = DraftSection(
    section_id="s1",
    heading="The claim",
    role="claim",
    assigned_claims=(("brief-a", "pc-key"),),
)
CLAIM_IDS = {("brief-a", "pc-key"): "pc-001"}
CLAIMS_BY_ID = {
    "pc-001": {"kind": "a", "confidence": "high", "text": "War made the state."},
}


def _valid_draft_json() -> str:
    return json.dumps({"prose": "War made the state [pc-001].", "new_claims": []})


def _malformed_draft_json() -> str:
    return json.dumps({"new_claims": []})  # no 'prose' -> DraftParseError


def _bad_kind_draft_json() -> str:
    return json.dumps(
        {
            "prose": "War made the state [pc-001], and so [n1].",
            "new_claims": [
                {"local_id": "n1", "text": "An assertion.", "kind": "a", "derived_from": ["pc-001"]}
            ],
        }
    )


def test_draft_section_retries_once_on_a_draft_parse_error():
    client = _QueueClient({"paper_draft": [_malformed_draft_json(), _valid_draft_json()]})

    draft = draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    assert len(client.prompts) == 2
    assert draft.retries == 1
    assert draft.prose == "War made the state [pc-001]."


def test_draft_section_retries_on_the_new_claim_kind_validation_error():
    client = _QueueClient({"paper_draft": [_bad_kind_draft_json(), _valid_draft_json()]})

    draft = draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    assert draft.retries == 1


def test_the_draft_retry_prompt_carries_the_rejected_attempts_error_text():
    client = _QueueClient({"paper_draft": [_malformed_draft_json(), _valid_draft_json()]})

    draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    first_prompt = client.prompts[0][1]
    second_prompt = client.prompts[1][1]
    assert second_prompt.startswith(first_prompt)
    assert "'prose' is missing or empty" in second_prompt


def test_draft_section_gives_up_after_the_bound_and_raises_draft_parse_error():
    client = _QueueClient({"paper_draft": [_malformed_draft_json()] * 3})

    with pytest.raises(DraftParseError):
        draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    assert len(client.prompts) == 3


def test_a_rejected_draft_attempt_logs_pass_section_attempt_and_validator(capsys):
    client = _QueueClient({"paper_draft": [_malformed_draft_json(), _valid_draft_json()]})

    draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    err = capsys.readouterr().err
    assert "paper_retry" in err
    assert "pass=paper_draft" in err
    assert "section=s1" in err
    assert "attempt=1/3" in err
    assert "validator=DraftParseError" in err


def test_invalid_new_claim_kind_error_is_retryable_not_just_draft_parse_error():
    """Guards against narrowing the retry to `DraftParseError` alone -- the
    issue also names 'the new-claim validation errors' as retryable."""
    client = _QueueClient({"paper_draft": [_bad_kind_draft_json()] * 3})

    with pytest.raises(InvalidNewClaimKindError):
        draft_section(client, "Thesis.", LENS, SECTION, CLAIM_IDS, CLAIMS_BY_ID, [])

    assert len(client.prompts) == 3
