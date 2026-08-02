"""The drafting prompt's new-claim invitation (specs/PHASE-C.md §7.4), and the
regression for issue #596.

Phase C's first live drafting call aborted on section 1. The plan's `setup`
section carried no assigned claims and no earlier section had cited any, so
nothing was visible for a new claim to derive from -- and the prompt invited one
anyway. The drafter minted a kind-(c) verdict with an empty `derived_from`, and
#588's guard refused it, correctly.
"""

from axial.paper.draft import compose_draft_prompt
from axial.paper.lens import resolve_lens
from axial.paper.plan import Section

THESIS = "Control over the material foundations of rule, not sovereignty."


def _prompt(
    section: Section, *, has_visible_claims: bool, cross_source_possible: bool = True
) -> str:
    return compose_draft_prompt(
        THESIS,
        resolve_lens("political-economy"),
        section,
        "(this section is assigned no claims)" if not section.assigned_claims else "- [pc-001] ...",
        "(no earlier section has cited a claim)",
        has_visible_claims=has_visible_claims,
        cross_source_possible=cross_source_possible,
    )


def test_a_section_with_nothing_visible_is_told_to_introduce_no_claims():
    setup = Section(section_id="s1", heading="The puzzle", role="setup")

    prompt = _prompt(setup, has_visible_claims=False)

    assert 'return "new_claims" as an empty list' in prompt
    # The invitation is what minted the ungroundable verdict. It must be gone,
    # not merely qualified.
    assert "You may introduce new claims of your own" not in prompt
    # And the drafter is told where a verdict actually belongs.
    assert "synthesis" in prompt


def test_a_section_with_claims_keeps_the_invitation():
    body = Section(
        section_id="s3",
        heading="Rent dependence",
        role="claim",
        assigned_claims=(("fd0c2636d456d0fc", "71ccf81d2b99bad6"),),
    )

    prompt = _prompt(body, has_visible_claims=True)

    assert "You may introduce new claims of your own" in prompt
    assert 'return "new_claims" as an empty list' not in prompt


def test_a_single_record_paper_is_not_offered_the_b_kind_at_all():
    """§7.4 makes a (b) claim impossible on one record, so the prompt that
    invites one is inviting a rejection (#597)."""
    body = Section(
        section_id="s2",
        heading="The counter-position",
        role="counter-position",
        assigned_claims=(("fd0c2636d456d0fc", "eb063cd49a9b6ec9"),),
    )

    prompt = _prompt(body, has_visible_claims=True, cross_source_possible=False)

    assert "This paper stands on ONE analysis record" in prompt
    assert 'kind "b", a cross-source inference' not in prompt
    assert 'kind "c", this paper\'s own verdict' in prompt
    # The example is the strongest instruction in a prompt (#592), so it must
    # not demonstrate the one kind that cannot be accepted here.
    assert '"kind": "b"' not in prompt
    assert '"kind": "c"' in prompt


def test_a_multi_record_paper_is_offered_both_kinds():
    body = Section(
        section_id="s3",
        heading="Rent dependence",
        role="claim",
        assigned_claims=(("124f7ba6ff8927c7", "71ccf81d2b99bad6"),),
    )

    prompt = _prompt(body, has_visible_claims=True, cross_source_possible=True)

    assert 'kind "b", a cross-source inference' in prompt
    assert 'kind "c", this paper\'s own verdict' in prompt
    assert "This paper stands on ONE analysis record" not in prompt
    assert '"kind": "b"' in prompt


def test_a_section_with_nothing_visible_shows_an_empty_example():
    setup = Section(section_id="s1", heading="The puzzle", role="setup")

    prompt = _prompt(setup, has_visible_claims=False)

    assert '"new_claims": []' in prompt


def test_a_claimless_section_that_can_see_earlier_claims_keeps_the_invitation():
    """The condition is "nothing visible", not "role is setup" (#596).

    A `setup` section placed later in an arc sees earlier sections' claims and
    may ground a new claim on them. Keying the rule to the role would forbid
    that, and would still permit the failure in any other first-and-claimless
    section."""
    late_setup = Section(section_id="s4", heading="A second frame", role="setup")

    prompt = _prompt(late_setup, has_visible_claims=True)

    assert "You may introduce new claims of your own" in prompt
