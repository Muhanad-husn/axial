"""Acceptance (issue #797): a drafted marker with the hyphen dropped resolves
rather than killing the run at the last stage.

`[pc010]` for `[pc-010]` was one of 36 drafts in the #787 slice-01
measurement -- a terminal failure at citation indexing, after every model
call had been paid for. The §7.5 refusal itself is correct and stays: what
this asserts is that a marker which corrects to exactly one claim id the
record already carries is a lookup, not a guess, and that anything else
still raises.

Drives the whole pipeline against a scripted stub client and fixture
records, the way `test_paper_pipeline.py` does -- no network, no vault.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.llm import StubLLMClient
from axial.paper.brief import PaperBrief
from axial.paper.citations import UnresolvableMarkerError
from axial.paper.reader import render_reader_paper
from axial.paper.record import run_paper

PIN = "sim-2026-07-30"


# Grounds carry their citation from the Phase-B record, which is what the
# reader render turns into a parenthetical. Present here so the third
# assertion below -- that a corrected marker becomes a citation and not a
# raw token -- has something to resolve against.
_TILLY = {
    "source_id": "tilly-1978-aaa",
    "author": "Charles Tilly",
    "title": "As Sociology Meets History",
    "date": "1978",
    "chapter": None,
    "section": None,
}
_BAYAT = {
    "source_id": "bayat-2017-bbb",
    "author": "Asef Bayat",
    "title": "Revolution Without Revolutionaries",
    "date": "2017",
    "chapter": None,
    "section": None,
}


def _claim(claim_id, kind, text, band, chunk_id, names, citation):
    return {
        "claim_id": claim_id,
        "kind": kind,
        "text": text,
        "confidence": band,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id, "citation": citation}],
        "names_touched": names,
    }


def _record(brief_id, claims, coverage_map):
    return {
        "brief_id": brief_id,
        "corpus_pin": PIN,
        "lens": "state-formation",
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
    a = _record(
        "brief-a",
        [
            _claim(
                "a1",
                "a",
                "Tilly makes war the mechanism.",
                "high",
                "tilly-1978-aaa_1_war_001",
                ["Charles Tilly"],
                _TILLY,
            ),
            _claim(
                "a2",
                "a",
                "Extraction follows coercion.",
                "high",
                "tilly-1978-aaa_2_extraction_001",
                ["Charles Tilly"],
                _TILLY,
            ),
        ],
        {
            "Charles Tilly": {
                "corpus_note_count": 154,
                "evidence_note_count": 8,
                "coverage_band": "dense",
            }
        },
    )
    b = _record(
        "brief-b",
        [
            _claim(
                "b1",
                "a",
                "Bayat sees revolution without revolutionaries.",
                "high",
                "bayat-2017-bbb_3_refolution_001",
                ["Asef Bayat"],
                _BAYAT,
            )
        ],
        {
            "Asef Bayat": {
                "corpus_note_count": 40,
                "evidence_note_count": 9,
                "coverage_band": "dense",
            }
        },
    )
    (directory / "brief-a.json").write_text(json.dumps(a), encoding="utf-8")
    (directory / "brief-b.json").write_text(json.dumps(b), encoding="utf-8")
    return directory


@pytest.fixture
def lenses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "lenses"
    directory.mkdir()
    (directory / "state-formation.yaml").write_text(
        "name: state-formation\ndescription: Reads for how state capacity was built.\n",
        encoding="utf-8",
    )
    return directory


SHAPE_RESPONSE = {"band": "strong", "defects": []}
ABSTRACT_RESPONSE = "This paper argues that organized challengers explain the outcome."


class StubClient(StubLLMClient):
    model_by_pass = {
        "paper_plan": "stub/plan",
        "paper_draft": "stub/draft",
        "paper_shape": "stub/shape",
        "paper_abstract": "stub/abstract",
    }

    def __init__(self, plan, drafts):
        super().__init__()
        self._plan = plan
        self._drafts = list(drafts)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        if pass_name == "paper_plan":
            return json.dumps(self._plan)
        if pass_name == "paper_shape":
            return json.dumps(SHAPE_RESPONSE)
        if pass_name == "paper_abstract":
            return json.dumps({"abstract": ABSTRACT_RESPONSE})
        return json.dumps(self._drafts.pop(0))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)


PLAN = {
    "thesis_statement": "Organized challengers explain the outcome better than mass mobilization.",
    "sections": [
        {
            "section_id": "s1",
            "heading": "The bellicist account",
            "role": "claim",
            "assigned_claims": [
                {"brief_id": "brief-a", "claim_id": "a1"},
                {"brief_id": "brief-a", "claim_id": "a2"},
            ],
        },
        {
            "section_id": "s2",
            "heading": "The case against",
            "role": "counter-position",
            "assigned_claims": [{"brief_id": "brief-b", "claim_id": "b1"}],
        },
    ],
}

# The failure #797 recorded: section s1's second marker drops the hyphen.
DRAFTS_WITH_A_DROPPED_HYPHEN = [
    {"prose": "War made the state [pc-001]. Extraction followed [pc002].", "new_claims": []},
    {"prose": "Mobilization did not convert [pc-003].", "new_claims": []},
]

# A marker that corrects to nothing the record carries.
DRAFTS_WITH_AN_UNKNOWN_MARKER = [
    {"prose": "War made the state [pc-001]. Extraction followed [pc-099].", "new_claims": []},
    {"prose": "Mobilization did not convert [pc-003].", "new_claims": []},
]


def _run(tmp_path, analyses_dir, lenses_dir, drafts):
    client = StubClient(PLAN, drafts)
    brief = PaperBrief(
        paper_brief_id="pb-797",
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a", "brief-b"),
        lens="state-formation",
    )
    return run_paper(
        client,
        brief,
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        source_meta_dir=tmp_path / "source_meta",
        papers_dir=tmp_path / "papers",
    )


def test_a_dropped_hyphen_does_not_kill_the_draft(tmp_path, analyses_dir, lenses_dir):
    """The run completes, and the index names the real claim id."""
    record = _run(tmp_path, analyses_dir, lenses_dir, DRAFTS_WITH_A_DROPPED_HYPHEN)

    cited = [entry["paper_claim_id"] for entry in record["citations"]]
    assert cited == ["pc-001", "pc-002", "pc-003"]
    assert {claim["paper_claim_id"] for claim in record["claims"]} == {
        "pc-001",
        "pc-002",
        "pc-003",
    }


def test_the_corrected_marker_reaches_the_reader_as_a_citation(tmp_path, analyses_dir, lenses_dir):
    """`reader.py`'s marker regex matches only `[pc-...]`, so a correction
    confined to the index would leave a raw `[pc002]` in released prose."""
    record = _run(tmp_path, analyses_dir, lenses_dir, DRAFTS_WITH_A_DROPPED_HYPHEN)
    reader = render_reader_paper(record)

    assert "[pc002]" not in reader
    assert "[pc-002]" not in reader
    assert "Extraction followed (Tilly, 1978)" in reader


def test_a_marker_that_corrects_to_nothing_still_fails(tmp_path, analyses_dir, lenses_dir):
    """§7.5's refusal is untouched: a marker naming no claim is still fatal."""
    with pytest.raises(UnresolvableMarkerError) as excinfo:
        _run(tmp_path, analyses_dir, lenses_dir, DRAFTS_WITH_AN_UNKNOWN_MARKER)
    assert "pc-099" in str(excinfo.value)
