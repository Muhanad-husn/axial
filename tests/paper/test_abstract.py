"""Issue #787 slice 04: every finished paper opens with an abstract of
roughly 200 words summarising the argument the paper actually made.

The acceptance criterion (plan `04-every-paper-carries-an-abstract.md`):

    Given a paper brief with two analysis records
    When  an operator runs `uv run axial paper draft <that brief>`
    Then  the persisted record under data/papers/ carries an abstract of
          roughly 200 words
    And   the reader-facing markdown opens with that abstract, under the
          title and before the first section
    And   the abstract states the paper's own thesis and what it concluded,
          not a description of the sources
    And   the abstract carries no claim markers and no citations

The last clause is a property of the prompt, not of the stub's canned
response, so it is asserted against the prompt the run actually sent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.llm import PAPER_ABSTRACT_PASS_NAME, StubLLMClient
from axial.paper.brief import PaperBrief, PaperBriefContent, compute_paper_brief_id
from axial.paper.reader import render_reader_paper
from axial.paper.record import run_paper
from axial.paper.render import render_paper


def _claim(claim_id, text, chunk_id, names):
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": text,
        "confidence": "high",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "names_touched": names,
    }


def _analysis(brief_id, claims, coverage_map):
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
    for index, brief_id in enumerate(("brief-a", "brief-b"), start=1):
        record = _analysis(
            brief_id,
            [
                _claim(
                    f"a{index}",
                    "The mechanism runs through extraction.",
                    f"src-{index}_1_a_001",
                    ["A Author"],
                ),
                _claim(
                    f"b{index}",
                    "The opposing account holds otherwise.",
                    f"src-{index}_2_b_001",
                    ["A Author"],
                ),
            ],
            {
                "A Author": {
                    "corpus_note_count": 154,
                    "evidence_note_count": 8,
                    "coverage_band": "dense",
                }
            },
        )
        (directory / f"{brief_id}.json").write_text(json.dumps(record), encoding="utf-8")
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


THESIS_STATEMENT = "The mechanism explains the outcome better than the alternative."

PLAN = {
    "thesis_statement": THESIS_STATEMENT,
    "sections": [
        {
            "section_id": "s1",
            "heading": "The mechanism",
            "role": "claim",
            "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}],
        },
        {
            "section_id": "s2",
            "heading": "The case against",
            "role": "counter-position",
            "assigned_claims": [{"brief_id": "brief-b", "claim_id": "b2"}],
        },
    ],
}

SHAPE_RESPONSE = {"band": "strong", "defects": [], "title": "Extraction, not sovereignty"}

# ~200 words, no markers, no parentheticals: what a good response looks like.
ABSTRACT = (
    "This paper argues that control over the material foundations of rule, not formal "
    "sovereignty, explains why the regime survived the period under study. "
    + " ".join(["The account holds against the institutionalist alternative."] * 24)
)


class StubClient(StubLLMClient):
    model_by_pass = {
        "paper_plan": "stub/plan",
        "paper_draft": "stub/draft",
        "paper_shape": "stub/shape",
        PAPER_ABSTRACT_PASS_NAME: "stub/abstract",
    }

    def __init__(self, drafts, abstract=ABSTRACT, abstract_response=None):
        super().__init__()
        self._drafts = list(drafts)
        self._abstract_response = (
            abstract_response
            if abstract_response is not None
            else json.dumps({"abstract": abstract})
        )
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        if pass_name == "paper_plan":
            return json.dumps(PLAN)
        if pass_name == "paper_shape":
            return json.dumps(SHAPE_RESPONSE)
        if pass_name == PAPER_ABSTRACT_PASS_NAME:
            return self._abstract_response
        return json.dumps(self._drafts.pop(0))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)


def _run(tmp_path, analyses_dir, lenses_dir, **client_kwargs):
    drafts = [
        {"prose": "Rent dependence loosened the bargain [pc-001].", "new_claims": []},
        {"prose": "The institutionalist account reads it otherwise [pc-002].", "new_claims": []},
    ]
    client = StubClient(drafts, **client_kwargs)
    content = PaperBriefContent(
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a", "brief-b"),
        lens="political-economy",
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
    return record, client, tmp_path / "papers"


# ---------------------------------------------------------------------------
# The record carries it, and survives the round trip through record.py.
# ---------------------------------------------------------------------------


def test_the_persisted_record_carries_an_abstract_of_roughly_two_hundred_words(
    tmp_path, analyses_dir, lenses_dir
):
    record, _, papers_dir = _run(tmp_path, analyses_dir, lenses_dir)
    assert record["abstract"] == ABSTRACT

    persisted = json.loads(
        (papers_dir / f"{record['paper_brief_id']}.json").read_text(encoding="utf-8")
    )
    assert persisted["abstract"] == ABSTRACT

    # "Roughly 200": the same +/-25% band slice 02 uses for its own target.
    assert 150 <= len(persisted["abstract"].split()) <= 250


def test_the_abstract_pass_is_scoped_into_cost_and_model_by_pass_like_the_shape_check(
    tmp_path, analyses_dir, lenses_dir
):
    record, _, _ = _run(tmp_path, analyses_dir, lenses_dir)
    assert record["model_by_pass"][PAPER_ABSTRACT_PASS_NAME] == "stub/abstract"
    assert PAPER_ABSTRACT_PASS_NAME in record["cost"]["by_pass"]
    # Never retried, exactly like the shape check: a key that can never be
    # non-zero is not a fact about the run.
    assert PAPER_ABSTRACT_PASS_NAME not in record["retries"]


def test_the_abstract_call_reads_the_drafted_prose_not_the_plan(tmp_path, analyses_dir, lenses_dir):
    _, client, _ = _run(tmp_path, analyses_dir, lenses_dir)
    prompts = [prompt for name, prompt in client.prompts if name == PAPER_ABSTRACT_PASS_NAME]
    assert len(prompts) == 1
    assert "Rent dependence loosened the bargain" in prompts[0]
    assert "The institutionalist account reads it otherwise" in prompts[0]
    assert THESIS_STATEMENT in prompts[0]


def test_the_abstract_prompt_forbids_claim_markers_and_citations(
    tmp_path, analyses_dir, lenses_dir
):
    _, client, _ = _run(tmp_path, analyses_dir, lenses_dir)
    prompt = next(p for name, p in client.prompts if name == PAPER_ABSTRACT_PASS_NAME).lower()
    assert "marker" in prompt
    assert "citation" in prompt


# ---------------------------------------------------------------------------
# Both renders show it.
# ---------------------------------------------------------------------------


def test_the_reader_render_places_the_abstract_under_the_title_before_the_first_section(
    tmp_path, analyses_dir, lenses_dir
):
    record, _, papers_dir = _run(tmp_path, analyses_dir, lenses_dir)
    rendered = (papers_dir / f"{record['paper_brief_id']}.md").read_text(encoding="utf-8")

    assert ABSTRACT in rendered
    assert rendered.index("# Extraction, not sovereignty") < rendered.index(ABSTRACT)
    assert rendered.index(ABSTRACT) < rendered.index("## The mechanism")

    # The #784 standfirst stays adjacent to the title it disambiguates; the
    # abstract is the first block of body prose, not a second subtitle.
    assert rendered.index(THESIS_STATEMENT) < rendered.index(ABSTRACT)


def test_the_audit_render_carries_the_abstract_too(tmp_path, analyses_dir, lenses_dir):
    record, _, papers_dir = _run(tmp_path, analyses_dir, lenses_dir)
    audit = (papers_dir / f"{record['paper_brief_id']}.audit.md").read_text(encoding="utf-8")
    assert ABSTRACT in audit
    assert audit.index(ABSTRACT) < audit.index("## The mechanism")


def test_a_stray_marker_in_the_abstract_is_never_turned_into_a_citation():
    """`replace_markers` runs on section prose, never on the abstract. A
    marker the prompt forbade but the model wrote anyway stays visible --
    the same rule the reader render already holds for an unresolved
    reference -- rather than becoming a citation inside a block that is
    supposed to carry none."""
    record = {
        "paper_brief_id": "p1",
        "paper_brief": {"thesis": "Did war make the state?", "title": None},
        "abstract": "War made the state [pc-001].",
        "plan": {
            "thesis_statement": "War made the state.",
            "sections": [{"section_id": "s1", "heading": "The argument", "role": "claim"}],
        },
        "drafts": [{"section_id": "s1", "prose": "War made the state [pc-001]."}],
        "claims": [
            {
                "paper_claim_id": "pc-001",
                "kind": "a",
                "confidence": "high",
                "source_ids": ["vignal-2021"],
                "grounds": [
                    {
                        "ref_type": "chunk",
                        "ref_id": "vignal-2021_30_x_002",
                        "citation": {
                            "source_id": "vignal-2021",
                            "author": "Leila Vignal",
                            "title": "War-Torn",
                            "date": "2021",
                        },
                    }
                ],
            }
        ],
        "citations": [],
        "counter_position": {"present": True},
        "bibliography": [],
    }
    rendered = render_reader_paper(record)
    abstract_block = rendered.split("## The argument")[0]
    assert "[pc-001]" in abstract_block
    assert "Vignal" not in abstract_block


# ---------------------------------------------------------------------------
# The field is additive: an existing record renders exactly as it does today,
# and a failed abstract call never turns a drafted paper into a failed run.
# ---------------------------------------------------------------------------


def _record_without_abstract(tmp_path, analyses_dir, lenses_dir):
    record, _, _ = _run(tmp_path, analyses_dir, lenses_dir)
    record.pop("abstract")
    return record


def test_a_record_with_no_abstract_renders_exactly_as_it_does_today(
    tmp_path, analyses_dir, lenses_dir
):
    record = _record_without_abstract(tmp_path, analyses_dir, lenses_dir)
    with_null = dict(record, abstract=None)

    for rendered in (render_reader_paper(record), render_paper(record)):
        assert "Abstract" not in rendered
        assert ABSTRACT not in rendered

    assert render_reader_paper(with_null) == render_reader_paper(record)
    assert render_paper(with_null) == render_paper(record)


def test_a_malformed_abstract_response_leaves_the_paper_drafted_and_the_field_null(
    tmp_path, analyses_dir, lenses_dir
):
    record, _, papers_dir = _run(
        tmp_path, analyses_dir, lenses_dir, abstract_response=json.dumps({"abstract": ""})
    )
    assert record["abstract"] is None
    assert record["shape"]["band"] == "strong"
    assert len(record["drafts"]) == 2

    rendered = (papers_dir / f"{record['paper_brief_id']}.md").read_text(encoding="utf-8")
    assert "Abstract" not in rendered
