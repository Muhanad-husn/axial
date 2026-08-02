"""Inner unit tests for the argument-coherence eval track (specs/PHASE-C.md
§10.2, §7.13, issue #611 P0-10/P0-11/P0-12)."""

from __future__ import annotations

import json

import pytest

import axial.panel.packet as packet_mod
from axial.panel.coherence_eval import (
    CoherenceEvalReport,
    PaperRecordNotFoundError,
    run_coherence_eval,
)
from axial.panel.review import reviewer_pass_name
from axial.panel.sample import SampleSpec, Stratum

_REVIEWER_VENDORS = ("anthropic/claude-opus-4", "openai/gpt-5", "google/gemini-3-pro")


class FakeClient:
    """Answers every reviewer call from a fixed response (or a queue when
    one is supplied), and records every prompt dispatched."""

    def __init__(self, response=None, responses=None):
        self._response = response
        self._responses = list(responses) if responses is not None else None
        self.prompts: list[str] = []

    def model_for_pass(self, pass_name):
        models = {reviewer_pass_name(i): v for i, v in enumerate(_REVIEWER_VENDORS, start=1)}
        return models.get(pass_name, "deepseek/deepseek-v4-pro")

    def complete(self, prompt, pass_name=None):
        self.prompts.append(prompt)
        if self._responses is not None:
            return self._responses.pop(0)
        return self._response


@pytest.fixture(autouse=True)
def stub_vault(monkeypatch):
    texts = {
        "chunk_a": "Tax receipts fell sharply.",
        "chunk_b": "Militia payrolls expanded.",
        "chunk_c": "Wartime ministries consolidated.",
    }
    monkeypatch.setattr(
        packet_mod,
        "get_chunk",
        lambda ref_id, vault_dir=None: type("C", (), {"chunk_text": texts[ref_id]})(),
    )


def _control_record():
    """Can carry all three plants: two claims with distinct grounds, a
    present counter-position with grounds, and a claim over a thin name."""
    return {
        "paper_brief_id": "pb-control",
        "model_by_pass": {"paper_draft": "deepseek/deepseek-v4-pro", "paper_plan": "z-ai/glm-5.2"},
        "plan": {"sections": [{"section_id": "s1", "heading": "Claim", "role": "claim"}]},
        "drafts": [{"section_id": "s1", "prose": "The state fell [pc-1][pc-2]."}],
        "claims": [
            {
                "paper_claim_id": "pc-1",
                "kind": "a",
                "confidence": "medium",
                "names_touched": ["syria"],
                "grounds": [{"ref_type": "chunk", "ref_id": "chunk_a"}],
            },
            {
                "paper_claim_id": "pc-2",
                "kind": "a",
                "confidence": "high",
                "names_touched": ["lebanon"],
                "grounds": [{"ref_type": "chunk", "ref_id": "chunk_b"}],
            },
        ],
        "counter_position": {
            "present": True,
            "stance": "The state held.",
            "grounds": [{"ref_type": "chunk", "ref_id": "chunk_c"}],
        },
        "coverage_map": {
            "syria": {"coverage_band": "thin", "corpus_note_count": 3},
            "lebanon": {"coverage_band": "rich", "corpus_note_count": 400},
        },
        "confidence": {"overall_band": "medium", "rationale": "..."},
        "bibliography": [],
    }


def _paper_record(paper_brief_id):
    return {
        "paper_brief_id": paper_brief_id,
        "model_by_pass": {"paper_draft": "deepseek/deepseek-v4-pro", "paper_plan": "z-ai/glm-5.2"},
        "plan": {"sections": [{"section_id": "s1", "heading": "Claim", "role": "claim"}]},
        "drafts": [{"section_id": "s1", "prose": "The bureaucracy hollowed out [pc-1]."}],
        "claims": [
            {
                "paper_claim_id": "pc-1",
                "kind": "a",
                "confidence": "medium",
                "names_touched": [],
                "grounds": [{"ref_type": "chunk", "ref_id": "chunk_a"}],
            }
        ],
        "counter_position": {"present": False, "corpus_one_sided": True},
        "coverage_map": {},
        "confidence": {"overall_band": "medium", "rationale": "..."},
        "bibliography": [],
    }


def _papers_dir(tmp_path, ids):
    directory = tmp_path / "papers"
    directory.mkdir()
    (directory / "pb-control.json").write_text(json.dumps(_control_record()), encoding="utf-8")
    for paper_brief_id in ids:
        (directory / f"{paper_brief_id}.json").write_text(
            json.dumps(_paper_record(paper_brief_id)), encoding="utf-8"
        )
    return directory


def _spec():
    return SampleSpec(
        sample_id="coherence-2026-08-02",
        corpus_pin="sim-2026-07-30",
        control_paper_id="pb-control",
        strata=(
            Stratum(
                stratum_id="s-medium-baseline",
                tier="medium",
                model_combination="baseline",
                paper_brief_ids=("pb-001", "pb-002"),
            ),
            Stratum(
                stratum_id="s-high-open",
                tier="high",
                model_combination="open",
                paper_brief_ids=("pb-003",),
            ),
        ),
    )


def _generous_verdict():
    return json.dumps(
        {
            "factual_correctness": "strong",
            "citation_grounding": "strong",
            "completeness": "strong",
            "coherence": "strong",
            "defects": [],
        }
    )


def test_the_sample_is_still_reviewed_on_a_failed_control(tmp_path):
    client = FakeClient(response=_generous_verdict())
    papers_dir = _papers_dir(tmp_path, ["pb-001", "pb-002", "pb-003"])
    report = run_coherence_eval(_spec(), client=client, papers_dir=papers_dir)

    assert isinstance(report, CoherenceEvalReport)
    assert report.control.passed is False
    assert report.trusted is False
    assert len(report.strata) == 2


def test_stratum_figures_are_never_pooled_across_strata(tmp_path):
    client = FakeClient(response=_generous_verdict())
    papers_dir = _papers_dir(tmp_path, ["pb-001", "pb-002", "pb-003"])
    report = run_coherence_eval(_spec(), client=client, papers_dir=papers_dir)

    by_id = {stratum.stratum_id: stratum for stratum in report.strata}
    assert by_id["s-medium-baseline"].n_reviewer_scores == 6  # 2 papers x 3 reviewers
    assert by_id["s-high-open"].n_reviewer_scores == 3  # 1 paper x 3 reviewers
    assert by_id["s-medium-baseline"].argument_coherence_rate == 1.0
    assert by_id["s-high-open"].argument_coherence_rate == 1.0
    # No field anywhere on the report pools these into a single number.
    assert "argument_coherence_rate" not in report.to_json()
    assert "mean" not in json.dumps(report.to_json())


def test_report_frame_carries_the_whole_section_7_13_disclosure(tmp_path):
    client = FakeClient(response=_generous_verdict())
    papers_dir = _papers_dir(tmp_path, ["pb-001", "pb-002", "pb-003"])
    report = run_coherence_eval(_spec(), client=client, papers_dir=papers_dir)

    frame = report.frame
    assert frame["sample_id"] == "coherence-2026-08-02"
    assert frame["paper_brief_ids"] == ["pb-001", "pb-002", "pb-003"]
    assert frame["tiers"] == ["high", "medium"]
    assert frame["model_combinations"] == ["baseline", "open"]
    assert frame["corpus_pin"] == "sim-2026-07-30"
    assert frame["panel"]["n_reviewers"] == 3


def test_a_missing_paper_record_raises_before_any_reviewer_call(tmp_path):
    client = FakeClient(response=_generous_verdict())
    papers_dir = _papers_dir(tmp_path, ["pb-001"])  # pb-002/pb-003 never written
    with pytest.raises(PaperRecordNotFoundError):
        run_coherence_eval(_spec(), client=client, papers_dir=papers_dir)


def test_a_missing_control_record_raises_before_the_sample_is_touched(tmp_path):
    directory = tmp_path / "papers"
    directory.mkdir()
    for paper_brief_id in ("pb-001", "pb-002", "pb-003"):
        (directory / f"{paper_brief_id}.json").write_text(
            json.dumps(_paper_record(paper_brief_id)), encoding="utf-8"
        )
    client = FakeClient(response=_generous_verdict())
    with pytest.raises(PaperRecordNotFoundError):
        run_coherence_eval(_spec(), client=client, papers_dir=directory)
    assert client.prompts == []
