"""Arc planning's prompt and its parser (specs/PHASE-C.md §7.2), and the
regression for issue #592.

`plan.py` had no test of its own before this file. Its only coverage came from
pipeline and CLI stubs that emit correctly-shaped JSON by construction, so
nothing ever asked whether the prompt shows the inventory in the shape the
response schema asks for. It did not, and Phase C's first live run could not
produce a single valid plan.
"""

import pytest

from axial.paper.intake import InventoryClaim, PaperIntake
from axial.paper.lens import resolve_lens
from axial.paper.plan import (
    UnassignedClaimError,
    compose_plan_prompt,
    parse_plan_response,
)

BRIEF_ID = "fd0c2636d456d0fc"
CLAIM_ID = "2a395ce341f1ddee"


def _intake() -> PaperIntake:
    inventory = (
        InventoryClaim(
            brief_id=BRIEF_ID,
            claim_id=CLAIM_ID,
            claim={
                "kind": "a",
                "confidence": "high",
                "text": "French colonial rule deliberately fragmented the territory.",
            },
        ),
        InventoryClaim(
            brief_id=BRIEF_ID,
            claim_id="71ccf81d2b99bad6",
            claim={
                "kind": "b",
                "confidence": "medium",
                "text": "Autonomy was derived from domestic social classes.",
            },
        ),
    )
    return PaperIntake(
        corpus_pin="sim-2026-07-26",
        source_analyses=(BRIEF_ID,),
        records={BRIEF_ID: {"claims": [entry.claim for entry in inventory]}},
        inventory=inventory,
    )


def _prompt() -> str:
    return compose_plan_prompt("A thesis.", resolve_lens("political-economy"), _intake())


def _plan_json(assigned: list[dict]) -> str:
    import json

    return json.dumps(
        {
            "thesis_statement": "The paper's own sentence.",
            "sections": [
                {
                    "section_id": "s1",
                    "heading": "Setup",
                    "role": "setup",
                    "assigned_claims": [],
                },
                {
                    "section_id": "s2",
                    "heading": "The mandate",
                    "role": "claim",
                    "assigned_claims": assigned,
                },
            ],
        }
    )


def test_inventory_lines_name_the_two_fields_the_schema_asks_for():
    """The prompt's display format and its answer format must agree (#592)."""
    prompt = _prompt()

    assert f"brief_id={BRIEF_ID} claim_id={CLAIM_ID}" in prompt
    # The compound form is what the planner could not split. If it comes back,
    # the bug comes back with it.
    assert f"({BRIEF_ID} / {CLAIM_ID})" not in prompt


def test_a_plan_copying_both_fields_verbatim_parses():
    plan = parse_plan_response(
        _plan_json([{"brief_id": BRIEF_ID, "claim_id": CLAIM_ID}]), _intake()
    )

    assert tuple(plan.sections[1].assigned_claims) == ((BRIEF_ID, CLAIM_ID),)


@pytest.mark.parametrize(
    "assigned, label",
    [
        (
            [
                {
                    "brief_id": f"{BRIEF_ID} / {CLAIM_ID}",
                    "claim_id": "French colonial fragmentation and juridical sovereignty",
                }
            ],
            "draw 1: the compound blob in brief_id, a prose label in claim_id",
        ),
        (
            [
                {
                    "brief_id": f"{BRIEF_ID} / {CLAIM_ID}",
                    "claim_id": f"{BRIEF_ID} / {CLAIM_ID}",
                }
            ],
            "draw 2: the compound blob in both fields",
        ),
    ],
)
def test_the_two_live_failure_shapes_are_rejected_and_named(assigned, label):
    """Both shapes are verbatim from Phase C's first live run.

    They are still rejected -- the parser was never the bug -- but the message
    now reports the two fields separately, so the reader sees a misfilled pair
    rather than an apparently invented claim."""
    with pytest.raises(UnassignedClaimError) as caught:
        parse_plan_response(_plan_json(assigned), _intake())

    message = str(caught.value)
    assert "brief_id=" in message and "claim_id=" in message, label
    assert "copy both fields verbatim" in message
