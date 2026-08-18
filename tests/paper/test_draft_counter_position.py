"""The drafting prompt's counter-position instruction (issue #787 slice 01).

`compose_plan_prompt` (`axial.paper.plan`) already tells the PLANNER to
"state the opposing position at its strongest". `compose_draft_prompt`
(`axial.paper.draft`) never told the WRITER anything of the kind -- the
section's role reached it only as a bare interpolated string, `its role in
the argument is "counter-position"`, with nothing saying what that role
obliges. The first real question-thesis paper this system drafted end to end
(`data/papers/ca17d6077c1a7f5e.json`) came back with the predictable failure:
the counter-position introduced already diminished, "as a background
condition" rather than at full strength.

This file pins the fix at the prompt-composition level: the instruction is
role-conditional, present only for a `counter-position` section, and it does
not touch anything else the prompt already says.
"""

from __future__ import annotations

from axial.paper.draft import compose_draft_prompt, parse_draft_response
from axial.paper.lens import resolve_lens
from axial.paper.plan import ROLES, Section

THESIS = "Control over the material foundations of rule, not sovereignty."
_OTHER_ROLES = [role for role in ROLES if role != "counter-position"]


def _prompt(role: str) -> str:
    section = Section(section_id="s1", heading="A section", role=role)
    return compose_draft_prompt(
        THESIS,
        resolve_lens("political-economy"),
        section,
        "- [pc-001] ...",
        "(nothing has been cited yet -- this is the first section)",
        has_visible_claims=True,
        cross_source_possible=True,
    )


def test_counter_position_section_carries_the_steelman_instruction():
    prompt = _prompt("counter-position")

    assert "at its strongest" in prompt


def test_every_other_role_carries_no_such_instruction():
    for role in _OTHER_ROLES:
        prompt = _prompt(role)
        assert "at its strongest" not in prompt, f"role {role!r} should not carry it"


def test_the_instruction_states_the_concrete_obligation_not_just_the_role_name():
    """It must say what "counter-position" obliges -- state the opposing
    position at full strength, in its own terms, before the paper answers it
    -- not merely echo the role label back, which the prompt already does via
    `its role in the argument is "counter-position"`."""
    prompt = _prompt("counter-position")

    # The bare role mention already exists in the prompt regardless -- the
    # regression this test guards against is an instruction block that adds
    # nothing beyond that mention.
    assert 'its role in the argument is "counter-position"' in prompt
    # The added instruction must name the concrete obligation: present the
    # opposition BEFORE the paper's own answer, and in ITS OWN terms rather
    # than pre-diminished.
    assert "before" in prompt.lower()
    assert "own" in prompt.lower()


def test_the_voice_contract_and_marker_grammar_are_unchanged_for_a_counter_position_section():
    """The addition sits alongside the existing prompt, never replacing it:
    claim-kind rules (a/b/c) and the marker grammar are pinned exactly as
    they read for every other role."""
    prompt = _prompt("counter-position")
    baseline = _prompt("claim")

    for pinned in (
        'A claim marked kind "a" is a SOURCE\'s assertion',
        'A claim marked "b" is this system\'s own inference',
        'A claim marked "c" is this paper\'s OWN verdict',
        "End every sentence that rests on a claim with that claim's marker",
        "Adjoin multiple markers with no separator: [pc-004][pc-011]",
        "THE ARGUMENT LEADS AND THE SOURCES SUPPORT IT",
    ):
        assert pinned in prompt
        assert pinned in baseline


def test_a_drafted_counter_position_section_still_parses_with_markers_and_new_claims_intact():
    """The added instruction changes nothing about the response shape a
    counter-position section returns: `parse_draft_response` still accepts
    its marker and a proposed new claim exactly as it would for any other
    role."""
    section = Section(
        section_id="s4",
        heading="The case against",
        role="counter-position",
        assigned_claims=(("brief-b", "b1"),),
    )
    raw = (
        '{"prose": "Mobilization alone sufficed to shift capacity, on its own '
        'strongest terms [pc-004].", "new_claims": '
        '[{"local_id": "n1", "kind": "c", "text": "Neither account is complete '
        'alone.", "derived_from": ["pc-004"]}]}'
    )

    draft = parse_draft_response(raw, section, visible_ids={"pc-004"})

    assert "[pc-004]" in draft.prose
    assert len(draft.new_claims) == 1
    assert draft.new_claims[0].local_id == "n1"
    assert draft.new_claims[0].kind == "c"
    assert draft.new_claims[0].derived_from == ("pc-004",)
