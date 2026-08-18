"""Issue #787 slice 02: a paper brief may declare `target_words`, the arc
planner allocates a share of it to each section, and the drafter is told its
own section's budget. Nothing is truncated after drafting -- if the paper
misses the target, that is a fact to read off the finished paper, never a cut.

The acceptance criterion (plan `02-length-is-a-plan-target.md`):

    Given a paper brief that declares target_words: 3000
    When  an operator runs `uv run axial paper draft <that brief>`
    Then  the persisted plan assigns each section its own share of the target
    And   the drafting prompt for each section states that section's budget
    And   the rendered paper's word count lands within a stated tolerance of
          the target, with nothing cut after drafting
    And   a brief declaring no target_words drafts exactly as it does today
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.llm import StubLLMClient
from axial.paper.brief import (
    InvalidTargetWordsError,
    PaperBrief,
    PaperBriefContent,
    compute_paper_brief_id,
)
from axial.paper.draft import compose_draft_prompt
from axial.paper.lens import resolve_lens
from axial.paper.plan import Section
from axial.paper.reader import render_reader_paper
from axial.paper.record import run_paper

# ---------------------------------------------------------------------------
# The hazard, pinned first: a brief with no target_words must hash to exactly
# its current id. Content copied verbatim from data/papers/273aea05df54e2df's
# own persisted `paper_brief` block, so this is a pin against a real record on
# disk, not an invented example.
# ---------------------------------------------------------------------------

_KNOWN_EXISTING_ID = "273aea05df54e2df"
_KNOWN_CONTENT = PaperBriefContent(
    thesis=(
        "Somaliland substituted diaspora remittances for a patron state and "
        "inter-clan consensus for imposed unity, and that substitution "
        "produced statehood that works relative to its collapsed parent "
        "while carrying its own structural strain: clan-skewed remittance "
        "flows, militarized spending, and democratic backsliding after 2006. "
        "The account rests on a thin evidential base, and saying so is part "
        "of the finding rather than a caveat attached to it."
    ),
    analysis_ids=("c2afb6d42f713e1c",),
    lens="political-economy",
    title=None,
)


def test_a_brief_with_no_target_words_hashes_to_its_known_existing_id():
    assert compute_paper_brief_id(_KNOWN_CONTENT) == _KNOWN_EXISTING_ID


def test_a_brief_declaring_target_words_hashes_differently_from_the_same_brief_without_it():
    with_target = PaperBriefContent(
        thesis=_KNOWN_CONTENT.thesis,
        analysis_ids=_KNOWN_CONTENT.analysis_ids,
        lens=_KNOWN_CONTENT.lens,
        title=_KNOWN_CONTENT.title,
        target_words=3000,
    )
    assert compute_paper_brief_id(with_target) != _KNOWN_EXISTING_ID


def test_two_different_target_words_hash_differently_too():
    a = PaperBriefContent(thesis="x", analysis_ids=("a",), target_words=1500)
    b = PaperBriefContent(thesis="x", analysis_ids=("a",), target_words=3000)
    assert compute_paper_brief_id(a) != compute_paper_brief_id(b)


# ---------------------------------------------------------------------------
# `target_words` validation: rejected when present but not a positive
# integer, with the same typed-error shape the other brief fields use.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [0, -5, 3.5, "3000", True, False])
def test_target_words_must_be_a_positive_integer(tmp_path: Path, bad_value):
    from axial.paper.brief import load_paper_brief

    path = tmp_path / "brief.yaml"
    path.write_text(
        json.dumps(
            {
                "thesis": "A thesis.",
                "analysis_ids": ["a"],
                "target_words": bad_value,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvalidTargetWordsError) as excinfo:
        load_paper_brief(path)
    assert "target_words" in str(excinfo.value)


def test_target_words_absent_or_null_is_fine(tmp_path: Path):
    from axial.paper.brief import load_paper_brief

    no_key = tmp_path / "no_key.yaml"
    no_key.write_text(json.dumps({"thesis": "A thesis.", "analysis_ids": ["a"]}), encoding="utf-8")
    assert load_paper_brief(no_key).target_words is None

    null_key = tmp_path / "null_key.yaml"
    null_key.write_text(
        json.dumps({"thesis": "A thesis.", "analysis_ids": ["a"], "target_words": None}),
        encoding="utf-8",
    )
    assert load_paper_brief(null_key).target_words is None


def test_a_positive_integer_target_words_is_accepted(tmp_path: Path):
    from axial.paper.brief import load_paper_brief

    path = tmp_path / "brief.yaml"
    path.write_text(
        json.dumps({"thesis": "A thesis.", "analysis_ids": ["a"], "target_words": 3000}),
        encoding="utf-8",
    )
    brief = load_paper_brief(path)
    assert brief.target_words == 3000


# ---------------------------------------------------------------------------
# The drafting prompt: states this section's own budget when the plan
# assigned one, and is byte-identical to slice 01's prompt when it did not.
# ---------------------------------------------------------------------------

THESIS = "Control over the material foundations of rule, not sovereignty."


def _draft_prompt(word_budget=None):
    section = Section(
        section_id="s3",
        heading="Rent dependence",
        role="claim",
        assigned_claims=(("fd0c2636d456d0fc", "71ccf81d2b99bad6"),),
    )
    return compose_draft_prompt(
        THESIS,
        resolve_lens("political-economy"),
        section,
        "- [pc-001] ...",
        "(no earlier section has cited a claim)",
        word_budget=word_budget,
    )


def test_a_section_with_no_word_budget_is_byte_identical_to_omitting_the_argument():
    assert _draft_prompt(word_budget=None) == compose_draft_prompt(
        THESIS,
        resolve_lens("political-economy"),
        Section(
            section_id="s3",
            heading="Rent dependence",
            role="claim",
            assigned_claims=(("fd0c2636d456d0fc", "71ccf81d2b99bad6"),),
        ),
        "- [pc-001] ...",
        "(no earlier section has cited a claim)",
    )
    assert "budget" not in _draft_prompt(word_budget=None).lower()


def test_a_section_with_a_word_budget_states_its_own_number():
    prompt = _draft_prompt(word_budget=650)
    assert "650" in prompt
    assert "budget" in prompt.lower()


# ---------------------------------------------------------------------------
# The acceptance criterion, end to end against a scripted stub client.
# ---------------------------------------------------------------------------


def _claim(claim_id, text, chunk_id, names):
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": text,
        "confidence": "high",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "names_touched": names,
    }


def _record(brief_id, claims, coverage_map):
    return {
        "brief_id": brief_id,
        "corpus_pin": "sim-2026-08-18",
        "lens": "political-economy",
        "interrogation": {"disposition": "proceed"},
        "claims": claims,
        "coverage_map": coverage_map,
        "counter_position": {
            "present": True,
            "stance": "the opposing account",
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "confidence": {"overall_band": "high", "rationale": "..."},
    }


@pytest.fixture
def analyses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "analyses"
    directory.mkdir()
    record = _record(
        "brief-a",
        [
            _claim("a1", "The mechanism runs through extraction.", "src-1_1_a_001", ["A Author"]),
            _claim("a2", "The opposing account holds otherwise.", "src-1_2_b_001", ["A Author"]),
        ],
        {"A Author": {"corpus_note_count": 154, "evidence_note_count": 8, "coverage_band": "dense"}},
    )
    (directory / "brief-a.json").write_text(json.dumps(record), encoding="utf-8")
    return directory


@pytest.fixture
def lenses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "lenses"
    directory.mkdir()
    (directory / "political-economy.yaml").write_text(
        "name: political-economy\ndescription: Reads for who pays and who decides.\n",
        encoding="utf-8",
    )
    return directory


SHAPE_RESPONSE = {"band": "strong", "defects": []}

TARGET_WORDS = 400
SECTION_BUDGET = 200


def _plan_with_budgets():
    return {
        "thesis_statement": "The mechanism explains the outcome better than the alternative.",
        "sections": [
            {
                "section_id": "s1",
                "heading": "The mechanism",
                "role": "claim",
                "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}],
                "word_budget": SECTION_BUDGET,
            },
            {
                "section_id": "s2",
                "heading": "The case against",
                "role": "counter-position",
                "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a2"}],
                "word_budget": SECTION_BUDGET,
            },
        ],
    }


def _plan_without_budgets():
    plan = _plan_with_budgets()
    for section in plan["sections"]:
        section.pop("word_budget")
    return plan


def _prose(n_words: int, marker: str) -> str:
    body = " ".join(["argument"] * (n_words - 1))
    return f"{body} point{marker}."


class StubClient(StubLLMClient):
    model_by_pass = {
        "paper_plan": "stub/plan",
        "paper_draft": "stub/draft",
        "paper_shape": "stub/shape",
        "paper_abstract": "stub/abstract",
    }

    def __init__(self, plan, drafts, shape=None):
        super().__init__()
        self._plan = plan
        self._drafts = list(drafts)
        self._shape = shape if shape is not None else SHAPE_RESPONSE
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        if pass_name == "paper_plan":
            return json.dumps(self._plan)
        if pass_name == "paper_shape":
            return json.dumps(self._shape)
        if pass_name == "paper_abstract":
            return json.dumps({"abstract": "This paper argues its own case."})
        return json.dumps(self._drafts.pop(0))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)


def _run(tmp_path, analyses_dir, lenses_dir, *, plan, target_words):
    drafts = [
        {"prose": _prose(SECTION_BUDGET, "[pc-001]"), "new_claims": []},
        {"prose": _prose(SECTION_BUDGET, "[pc-002]"), "new_claims": []},
    ]
    client = StubClient(plan, drafts)
    content = PaperBriefContent(
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a",),
        lens="political-economy",
        target_words=target_words,
    )
    brief = PaperBrief(
        paper_brief_id=compute_paper_brief_id(content),
        thesis=content.thesis,
        analysis_ids=content.analysis_ids,
        lens=content.lens,
        title=content.title,
        target_words=content.target_words,
    )
    record = run_paper(
        client,
        brief,
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        source_meta_dir=tmp_path / "source_meta",
        papers_dir=tmp_path / "papers",
    )
    return record, client


def test_the_persisted_plan_carries_each_sections_own_share(tmp_path, analyses_dir, lenses_dir):
    record, _ = _run(
        tmp_path, analyses_dir, lenses_dir, plan=_plan_with_budgets(), target_words=TARGET_WORDS
    )
    sections = record["plan"]["sections"]
    assert [s["word_budget"] for s in sections] == [SECTION_BUDGET, SECTION_BUDGET]
    assert sum(s["word_budget"] for s in sections) == TARGET_WORDS


def test_the_draft_prompt_for_each_section_states_its_own_budget(tmp_path, analyses_dir, lenses_dir):
    _, client = _run(
        tmp_path, analyses_dir, lenses_dir, plan=_plan_with_budgets(), target_words=TARGET_WORDS
    )
    draft_prompts = [prompt for name, prompt in client.prompts if name == "paper_draft"]
    assert len(draft_prompts) == 2
    for prompt in draft_prompts:
        assert str(SECTION_BUDGET) in prompt


# The tolerance for "lands near the target": +/-25% of `target_words`. Chosen
# because the drafter is only INSTRUCTED to hit its section's share, never
# forced to -- there is no truncation path -- and this fixture's own
# rendering overhead (title, two section headings, citation parentheticals
# swapped in for bracket markers) already spends several words per section
# before a real model's own variance is even in play. A miss inside a
# quarter of the target is the planner and drafter doing their job; a paper
# at double or half its target is not, and that is what this bar catches.
_TOLERANCE = 0.25


def test_the_rendered_papers_word_count_lands_within_tolerance_of_the_target(
    tmp_path, analyses_dir, lenses_dir
):
    record, _ = _run(
        tmp_path, analyses_dir, lenses_dir, plan=_plan_with_budgets(), target_words=TARGET_WORDS
    )
    rendered = render_reader_paper(record)
    actual_words = len(rendered.split())

    assert abs(actual_words - TARGET_WORDS) <= _TOLERANCE * TARGET_WORDS, (
        f"drafted {actual_words} words against a target of {TARGET_WORDS}, outside "
        f"the {_TOLERANCE:.0%} tolerance"
    )

    # Nothing was cut: both sections' full prose survives in the rendered
    # paper, not a truncated prefix of it.
    assert "The mechanism" in rendered
    assert "The case against" in rendered


def test_a_brief_declaring_no_target_words_drafts_exactly_as_it_does_today(
    tmp_path, analyses_dir, lenses_dir
):
    record, client = _run(
        tmp_path, analyses_dir, lenses_dir, plan=_plan_without_budgets(), target_words=None
    )
    assert "word_budget" not in json.dumps(record["plan"])
    draft_prompts = [prompt for name, prompt in client.prompts if name == "paper_draft"]
    for prompt in draft_prompts:
        assert "budget" not in prompt.lower()

    plan_prompt = next(prompt for name, prompt in client.prompts if name == "paper_plan")
    assert "word_budget" not in plan_prompt
