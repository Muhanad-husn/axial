"""Acceptance test for issue #700 half 2: the mechanical cross-section
repetition figure on the §7.16 shape report (specs/PHASE-C.md §7.16, §7.3).

Six live Phase C drafts were pulled up by independent judges for repeating
whole sentences and citation blocks across sections, while the model-graded
shape check returned `strong` on all six -- it checks each section against
its own assigned role, and a repetitive draft still satisfies that. This
pins the replacement measurement: a pure, zero-model-call n-gram check that
(1) flags real verbatim cross-section repetition and (2) does not fire on
the incidental overlap any two sections of one paper legitimately share
(shared citation markers, the paper's own recurring key terms), and (3) is
carried on `ShapeResult`/the persisted `shape` record.

`data/` does not exist in this worktree (see CLAUDE.local.md), so this
exercises the metric against constructed fixtures rather than the six real
drafts; the orchestrator runs the same function directly over the real
records in the main checkout (see this module's own docstring reference in
the builder's report).
"""

from __future__ import annotations

import json

from axial.llm import StubLLMClient
from axial.paper.shape import RepetitionResult, compute_repetition, run_shape_check
from axial.paper.render import render_paper


# -- exact shingle arithmetic, so the fraction is pinned to a known number --


def test_two_sections_sharing_all_their_prose_score_full_overlap_between_them():
    """A and B are word-for-word identical (10 words -> 3 distinct 8-grams,
    all shared); C is unrelated (3 more distinct 8-grams, none shared). Of
    the paper's 6 distinct shingles, 3 recur across sections -- 0.5."""
    sections = [
        {"section_id": "A", "prose": "one two three four five six seven eight nine ten"},
        {"section_id": "B", "prose": "one two three four five six seven eight nine ten"},
        {"section_id": "C", "prose": "alpha beta gamma delta epsilon zeta eta theta iota kappa"},
    ]

    result = compute_repetition(sections)

    assert isinstance(result, RepetitionResult)
    assert result.fraction == 0.5
    assert result.pairs == ({"section_a": "A", "section_b": "B", "shared_ngrams": 3},)
    assert result.n == 8


def test_no_shared_prose_at_all_scores_zero():
    sections = [
        {"section_id": "A", "prose": "one two three four five six seven eight nine ten"},
        {"section_id": "C", "prose": "alpha beta gamma delta epsilon zeta eta theta iota kappa"},
    ]

    result = compute_repetition(sections)

    assert result.fraction == 0.0
    assert result.pairs == ()


# -- distinguishing real repetition from incidental overlap -----------------


def _clean_draft():
    """Two independently-argued sections on the same thesis: they share a
    citation marker style, the paper's own key term ('state-building'), and
    short attribution phrasing, but never eight consecutive words."""
    return [
        {
            "section_id": "s1",
            "prose": (
                "Heydemann and Sayigh argue that state-building in Syria relied on "
                "informal patronage networks rooted in provincial notables and "
                "military patronage circuits established under the mandate period "
                "[pc-001]. The regime's durability rested on this fusion of "
                "coercion and clientelism."
            ),
        },
        {
            "section_id": "s2",
            "prose": (
                "Caspersen treats state-building as a question of external "
                "recognition rather than internal patronage, and her account of "
                "unrecognized states extends the concept to entities the "
                "international system refuses to acknowledge [pc-002]. "
                "State-building, on her reading, is a legal and diplomatic "
                "accomplishment as much as an administrative one."
            ),
        },
        {
            "section_id": "s3",
            "prose": (
                "As Heydemann and Sayigh argue, and as Caspersen's account "
                "extends the concept further still, state-building resists a "
                "single settled definition across this literature [pc-003]."
            ),
        },
    ]


def _repetitive_draft():
    """The shape judges' actual complaint: a whole sentence and its citation
    block, copied verbatim into a second section instead of built on."""
    shared_sentence = (
        "Heydemann and Sayigh argue that the durability of the regime rested "
        "on a fusion of coercion and clientelism established under the "
        "mandate period [pc-001]."
    )
    return [
        {
            "section_id": "setup",
            "prose": f"{shared_sentence} This section situates that claim within the wider literature.",
        },
        {
            "section_id": "synthesis",
            "prose": f"Restating the point once more: {shared_sentence} Nothing in the "
            "counter-position section moved this conclusion.",
        },
    ]


def test_a_clean_draft_sharing_only_citations_and_key_terms_scores_zero():
    result = compute_repetition(_clean_draft())
    assert result.fraction == 0.0
    assert result.pairs == ()


def test_a_draft_with_a_copied_sentence_and_citation_block_scores_above_zero():
    result = compute_repetition(_repetitive_draft())
    assert result.fraction > 0.0
    assert result.pairs
    pair = result.pairs[0]
    assert {pair["section_a"], pair["section_b"]} == {"setup", "synthesis"}
    assert pair["shared_ngrams"] > 0


def test_the_repetitive_draft_scores_higher_than_the_clean_one():
    """The comparison the metric exists to make: distinguishing the six
    known-bad drafts from ordinary same-paper overlap is a relative
    judgment, not an absolute one -- pinned directly rather than through an
    added band/threshold (issue #700's own instruction not to add a second
    threshold ahead of evidence)."""
    clean = compute_repetition(_clean_draft())
    repetitive = compute_repetition(_repetitive_draft())
    assert repetitive.fraction > clean.fraction


# -- wired onto the shape report, with zero extra model calls ---------------


class _StubClient(StubLLMClient):
    def __init__(self, model_by_pass, response):
        super().__init__()
        self.model_by_pass = model_by_pass
        self._response = response
        self.prompts: list[tuple[str, str]] = []

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)

    def usage_for_pass(self, pass_name=None):
        return {"prompt_tokens": 10, "completion_tokens": 10}

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        return json.dumps(self._response)


def test_run_shape_check_carries_repetition_with_no_extra_model_call():
    client = _StubClient(
        {"paper_draft": "drafter/model", "paper_shape": "judge/model"},
        {"band": "strong", "defects": []},
    )
    sections = [
        {"section_id": s["section_id"], "heading": s["section_id"], "role": "evidence", **s}
        for s in _repetitive_draft()
    ]

    result = run_shape_check(client, "thesis", sections)

    assert result.repetition.fraction > 0.0
    assert len(client.prompts) == 1  # the band/defects call only -- repetition costs no call
    payload = result.to_json()
    assert payload["repetition"]["fraction"] == result.repetition.fraction
    assert payload["repetition"]["n"] == 8


def test_the_rendered_paper_carries_the_repetition_figure():
    record = {
        "shape": {
            "band": "strong",
            "defects": [],
            "model": "judge/model",
            "cost": None,
            "repetition": {"fraction": 0.5, "n": 8, "pairs": []},
        }
    }
    rendered = render_paper(record)
    assert "50.00%" in rendered
