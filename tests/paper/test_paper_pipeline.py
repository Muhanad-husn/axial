"""Phase-C acceptance: a paper brief over two analysis records becomes a
record and a rendered paper (specs/PHASE-C.md §7.1-§7.11, §8 P0-1..P0-7).

Runs the whole pipeline against a scripted stub client and fixture records --
no network, no vault, no corpus. What it asserts is the contract, not the
prose: the three intake rejections, that a carried claim takes its origin's
CLAMPED band, that a new (b) claim must span two records, that the record's
claims are exactly what the prose cited, and that rendering is deterministic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from axial.paper.brief import PaperBrief
from axial.paper.claims import SingleRecordInferenceError
from axial.paper.intake import (
    MixedCorpusPinError,
    RefusedAnalysisError,
    UnresolvableAnalysisError,
    run_intake,
)
from axial.paper.record import run_paper
from axial.paper.render import render_paper

PIN = "sim-2026-07-30"


def _claim(claim_id, kind, text, band, chunk_id, names):
    return {
        "claim_id": claim_id,
        "kind": kind,
        "text": text,
        "confidence": band,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "names_touched": names,
    }


def _record(
    brief_id, claims, coverage_map, *, pin=PIN, disposition="proceed", lens="state-formation"
):
    return {
        "brief_id": brief_id,
        "corpus_pin": pin,
        "lens": lens,
        "interrogation": {"disposition": disposition},
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

    # `Tilly` is dense in A and thin in B's own map. A claim's clamp reads its
    # OWN record's map, which is what makes the two differ.
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
            ),
            _claim(
                "a2",
                "a",
                "Extraction follows coercion.",
                "high",
                "tilly-1978-aaa_2_extraction_001",
                ["Charles Tilly"],
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
            # Emitted `high`, but its only name is thin -- so its CLAMPED band
            # is `low`, and that is what a carried claim must take.
            _claim(
                "b1",
                "a",
                "Bayat sees revolution without revolutionaries.",
                "high",
                "bayat-2017-bbb_3_refolution_001",
                ["Asef Bayat"],
            ),
        ],
        {"Asef Bayat": {"corpus_note_count": 4, "evidence_note_count": 1, "coverage_band": "thin"}},
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


class StubClient:
    """Returns scripted JSON per pass, and records what it was asked."""

    model_by_pass = {"paper_plan": "stub/plan", "paper_draft": "stub/draft"}

    def __init__(self, plan, drafts):
        self._plan = plan
        self._drafts = list(drafts)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        if pass_name == "paper_plan":
            return json.dumps(self._plan)
        return json.dumps(self._drafts.pop(0))

    def cost_report(self):
        return {"total_usd": 0.0, "by_pass": {}}


PLAN = {
    "thesis_statement": "Organized challengers explain the outcome better than mass mobilization alone.",
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

DRAFTS = [
    {"prose": "War made the state [pc-001]. Extraction followed [pc-002].", "new_claims": []},
    {
        "prose": "Mobilization did not convert [pc-003]. The two accounts diverge on organization [n1].",
        "new_claims": [
            {
                "local_id": "n1",
                "text": "The accounts disagree about what organization is for.",
                "derived_from": ["pc-001", "pc-003"],
            }
        ],
    },
]


def test_intake_rejects_an_unresolvable_record(analyses_dir: Path):
    with pytest.raises(UnresolvableAnalysisError) as excinfo:
        run_intake(("brief-a", "brief-missing"), analyses_dir=analyses_dir)
    assert "brief-missing" in str(excinfo.value)
    assert "Phase C never runs Phase B" in str(excinfo.value)


def test_intake_rejects_a_refusal(analyses_dir: Path):
    refused = _record("brief-r", [], {}, disposition="refuse")
    (analyses_dir / "brief-r.json").write_text(json.dumps(refused), encoding="utf-8")
    with pytest.raises(RefusedAnalysisError):
        run_intake(("brief-a", "brief-r"), analyses_dir=analyses_dir)


def test_intake_rejects_a_mixed_pin_set(analyses_dir: Path):
    stale = _record("brief-s", [], {}, pin="sim-2026-01-01")
    (analyses_dir / "brief-s.json").write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(MixedCorpusPinError) as excinfo:
        run_intake(("brief-a", "brief-s"), analyses_dir=analyses_dir)
    assert "brief-a" in str(excinfo.value) and "brief-s" in str(excinfo.value)


def test_contradicting_records_are_never_rejected(analyses_dir: Path):
    """§7.14: contradiction is the scholarly substance, not an intake error."""
    intake = run_intake(("brief-a", "brief-b"), analyses_dir=analyses_dir)
    assert intake.corpus_pin == PIN
    assert len(intake.inventory) == 3


def _run(tmp_path, analyses_dir, lenses_dir, drafts=None):
    client = StubClient(PLAN, drafts if drafts is not None else DRAFTS)
    brief = PaperBrief(
        paper_brief_id="pb-test",
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a", "brief-b"),
        lens="state-formation",
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


def test_a_carried_claim_takes_its_origins_clamped_band(tmp_path, analyses_dir, lenses_dir):
    """§7.4: the clamped band, not the band the record persisted."""
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    by_origin = {
        (claim["origin"]["brief_id"], claim["origin"]["claim_id"]): claim
        for claim in record["claims"]
        if claim.get("origin")
    }
    # b1 was persisted `high`; its only name is thin, so the paper carries `low`.
    assert by_origin[("brief-b", "b1")]["confidence"] == "low"
    # a1 was persisted `high` against a dense name, so it is unchanged.
    assert by_origin[("brief-a", "a1")]["confidence"] == "high"


def test_a_new_b_claim_spans_two_records_and_is_capped(tmp_path, analyses_dir, lenses_dir):
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    new_claims = [claim for claim in record["claims"] if claim["origin"] is None]
    assert len(new_claims) == 1
    new = new_claims[0]
    assert new["kind"] == "b"
    # Grounds are the union of what it derives from, never the drafter's.
    assert len(new["grounds"]) == 2
    # Capped at the weakest it stands on: pc-003 carries `low`.
    assert new["confidence"] == "low"


def test_a_single_record_inference_is_rejected(tmp_path, analyses_dir, lenses_dir):
    drafts = [
        {
            "prose": "War made the state [pc-001]. And so [n1].",
            "new_claims": [
                {"local_id": "n1", "text": "A restatement.", "derived_from": ["pc-001", "pc-002"]}
            ],
        },
        {"prose": "Mobilization did not convert [pc-003].", "new_claims": []},
    ]
    with pytest.raises(SingleRecordInferenceError):
        _run(tmp_path, analyses_dir, lenses_dir, drafts)


def test_claims_are_exactly_what_the_prose_cited(tmp_path, analyses_dir, lenses_dir):
    """§7.5: a claim assigned but never cited is dropped, not carried."""
    drafts = [
        {"prose": "War made the state [pc-001].", "new_claims": []},
        {"prose": "Mobilization did not convert [pc-003].", "new_claims": []},
    ]
    record, _ = _run(tmp_path, analyses_dir, lenses_dir, drafts)
    cited = {claim["paper_claim_id"] for claim in record["claims"]}
    assert cited == {"pc-001", "pc-003"}
    assert all(citation["paper_claim_id"] in cited for citation in record["citations"])


def test_the_drafter_is_called_once_per_section_and_never_sees_the_whole_inventory(
    tmp_path, analyses_dir, lenses_dir
):
    """§4: one call per section, over that section's claims alone."""
    _, client = _run(tmp_path, analyses_dir, lenses_dir)
    draft_prompts = [prompt for pass_name, prompt in client.prompts if pass_name == "paper_draft"]
    assert len(draft_prompts) == len(PLAN["sections"])
    # Section 1's call must not carry section 2's claim text.
    assert "revolution without revolutionaries" not in draft_prompts[0]


def test_the_lens_reaches_the_model_with_its_description(tmp_path, analyses_dir, lenses_dir):
    """§0: a lens is not a filename."""
    _, client = _run(tmp_path, analyses_dir, lenses_dir)
    plan_prompt = next(p for name, p in client.prompts if name == "paper_plan")
    assert "Reads for how state capacity was built." in plan_prompt


def test_rendering_is_deterministic_and_discloses_bands_with_counts(
    tmp_path, analyses_dir, lenses_dir
):
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    first = render_paper(record)
    assert first == render_paper(record)

    assert "Organized challengers explain" in first
    assert "## Confidence and coverage" in first
    # A band never renders alone (§7.10).
    assert "corpus notes" in first and "cited claims" in first
    # Kind is legible in the citation table.
    assert "(carried)" in first and "(this paper's)" in first
    # Engine telemetry belongs to examine, never to the reader's paper (§0).
    assert "usage_ratio" not in first


def test_the_record_and_the_paper_are_persisted_side_by_side(tmp_path, analyses_dir, lenses_dir):
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    papers = tmp_path / "papers"
    assert (papers / "pb-test.json").is_file()
    assert (papers / "pb-test.md").is_file()
    assert record["corpus_pin"] == PIN
    assert record["lens"] == "state-formation"
    assert record["source_lenses"] == {"brief-a": "state-formation", "brief-b": "state-formation"}


def test_the_no_phase_b_import_guarantee_still_holds():
    """Phase C never runs Phase B (§3 non-goal 1) -- relocated here from the
    deleted `test_paper_opposition.py` (issue #577 riders): this guarantee is
    about the whole `axial.paper` package, not about the opposition pass that
    file was named for, and it must survive that file's deletion.

    Runs in a CLEAN interpreter, and has to. `sys.modules` is process-wide, so
    an in-process version of this test asserts about whatever the same worker
    imported before it: any test that touches `axial.cli` -- which wires every
    Phase-B subcommand at module load -- makes it fail without Phase C having
    imported anything. Under `-n auto` that is decided by which worker gets
    which file, so the guarantee would pass or fail by luck. A structural
    guarantee that flakes gets marked xfail and then deleted."""
    probe = (
        "import sys, json\n"
        "import axial.paper.record\n"
        "print(json.dumps(sorted(\n"
        "    name for name in sys.modules\n"
        "    if name.startswith(('axial.answer', 'axial.analyze', 'axial.brief'))\n"
        ")))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert json.loads(completed.stdout) == []
