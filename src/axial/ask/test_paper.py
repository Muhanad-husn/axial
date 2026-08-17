"""`axial.ask.paper` -- the composition that turns one finished ask into a
Phase C paper (issue #784, lifted out of `cli._ask_paper` where it has lived
since issue #668 so the service can run it too).

Every test here runs the real `run_paper` against a scripted stub client and
a fixture record. No network, no vault, no corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.ask.paper import draft_paper_for_turn
from axial.brief.intake import Brief
from axial.llm import StubLLMClient

PIN = "sim-2026-08-10"
BRIEF_ID = "b1"
QUESTION = "Did the mandate build the institutions the Baath inherited?"


def _claim(claim_id: str, text: str) -> dict:
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": text,
        "confidence": "medium",
        "grounds": [{"ref_type": "chunk", "ref_id": f"src-1999_1_intro_{claim_id}"}],
        "names_touched": ["Syria"],
    }


def _record(*, disposition: str = "proceed_bounded") -> dict:
    return {
        "brief_id": BRIEF_ID,
        "brief": {"brief_id": BRIEF_ID, "case": "Syria", "request": QUESTION},
        "corpus_pin": PIN,
        "lens": "state-formation",
        "interrogation": {"disposition": disposition},
        "claims": [
            _claim("c1", "The mandate built a centralised bureaucracy."),
            _claim("c2", "Rural notables were co-opted into it."),
        ],
        "counter_position": {
            "present": True,
            "stance": "the apparatus was rebuilt after 1963",
            "grounds": [{"ref_type": "chunk", "ref_id": "src-1999_1_intro_c1"}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "coverage_map": {
            "Syria": {"corpus_note_count": 40, "evidence_note_count": 8, "coverage_band": "medium"}
        },
        "confidence": {"overall_band": "medium", "rationale": "8 of 40 notes"},
    }


PLAN = {
    "thesis_statement": "The institutions were built under the mandate.",
    "sections": [
        {
            "section_id": "s1",
            "heading": "The mandate's bureaucracy",
            "role": "claim",
            "assigned_claims": [{"brief_id": BRIEF_ID, "claim_id": "c1"}],
        },
        {
            "section_id": "s2",
            "heading": "The case for a rebuild",
            "role": "counter-position",
            "assigned_claims": [{"brief_id": BRIEF_ID, "claim_id": "c2"}],
        },
    ],
}

DRAFTS = [
    {"prose": "A centralised bureaucracy was built [pc-001].", "new_claims": []},
    {"prose": "Against this, it was rebuilt after 1963 [pc-002].", "new_claims": []},
]


class _StubClient(StubLLMClient):
    model_by_pass = {
        "paper_plan": "deepseek/deepseek-v4-flash",
        "paper_draft": "deepseek/deepseek-v4-flash",
        "paper_shape": "stub/shape",
    }

    def __init__(self) -> None:
        super().__init__()
        self._drafts = list(DRAFTS)
        self.passes: list[str] = []

    def complete(self, prompt, pass_name=None, **_):
        self.passes.append(pass_name)
        if pass_name == "paper_plan":
            return json.dumps(PLAN)
        if pass_name == "paper_shape":
            return json.dumps({"band": "strong", "defects": []})
        return json.dumps(self._drafts.pop(0))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)


@pytest.fixture
def analyses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "analyses"
    directory.mkdir()
    (directory / f"{BRIEF_ID}.json").write_text(json.dumps(_record()), encoding="utf-8")
    return directory


def _turn(record: dict, path: Path) -> Turn:
    return Turn(
        session_id="s1",
        turn_index=1,
        question=QUESTION,
        case="Syria",
        brief=Brief(brief_id=BRIEF_ID, case="Syria", request=QUESTION),
        result=BriefRunResult(
            record=record, path=path, markdown_path=path, report={}, report_path=path
        ),
    )


def _draft(client, analyses_dir: Path, tmp_path: Path, *, record: dict | None = None):
    record = record if record is not None else _record()
    return draft_paper_for_turn(
        client,
        _turn(record, analyses_dir / f"{BRIEF_ID}.json"),
        analyses_dir=analyses_dir,
        papers_dir=tmp_path / "papers",
        source_meta_dir=tmp_path / "source_meta",
    )


def test_the_thesis_is_the_question_and_the_one_record_is_the_source(
    analyses_dir: Path, tmp_path: Path
):
    """PHASE-C §7.1 defines `thesis` as "the paper's organizing question",
    which is what an ask supplies. The record the turn just persisted is the
    brief's whole `analysis_ids`."""
    record = _draft(_StubClient(), analyses_dir, tmp_path)

    assert record["paper_brief"]["thesis"] == QUESTION
    assert record["paper_brief"]["analysis_ids"] == [BRIEF_ID]
    assert record["paper_brief"]["lens"] is None
    assert record["source_analyses"] == [BRIEF_ID]


def test_a_refusal_is_skipped_without_a_single_model_call(analyses_dir: Path, tmp_path: Path):
    """§7.1 rejects a refused record at paper intake because it carries no
    claims. Drafting one would turn a valid Phase-B outcome into an error, so
    the composition declines before intake ever sees it."""
    client = _StubClient()

    assert _draft(client, analyses_dir, tmp_path, record=_record(disposition="refuse")) is None
    assert client.passes == []


def test_the_paper_lands_where_the_caller_said_not_in_the_repo(
    analyses_dir: Path, tmp_path: Path
):
    """`run_paper`'s own `PAPERS_DIR` is a bare relative `data/papers`, which
    is right for the CLI and wrong for a hosted worker writing under a
    principal's own directory. The caller names the directory; nothing here
    falls back to the repo."""
    record = _draft(_StubClient(), analyses_dir, tmp_path)

    papers_dir = tmp_path / "papers"
    paper_id = record["paper_brief_id"]
    assert Path(record["paper_markdown_path"]) == papers_dir / f"{paper_id}.md"
    assert sorted(path.name for path in papers_dir.iterdir()) == [
        f"{paper_id}.audit.md",
        f"{paper_id}.json",
        f"{paper_id}.md",
    ]


def test_the_same_question_over_the_same_record_is_the_same_paper(
    analyses_dir: Path, tmp_path: Path
):
    """`paper_brief_id` is a content hash over the brief (§7.1), so a repeat
    ask resolves to one artifact rather than accumulating near-duplicates --
    the property the service's own cache leans on."""
    first = _draft(_StubClient(), analyses_dir, tmp_path)
    second = _draft(_StubClient(), analyses_dir, tmp_path)

    assert first["paper_brief_id"] == second["paper_brief_id"]
