"""`axial paper draft` / `axial paper examine` (specs/PHASE-C.md §8 P0-12).

Offline, stubbed, no network, no real vault -- like `test_paper_pipeline.py`.
Fixture shapes here are deliberately the same as that file's own
(`_claim`/`_record`/`PLAN`/`DRAFTS`): this file exercises the CLI layer over
the identical pipeline the function-level tests already pin, so it is not
re-testing stage behavior, only that the CLI reaches it and reports success
and failure the way an operator needs it to.

Seam decision: a CHILD PROCESS, not `axial.cli.main` called in-process
-----------------------------------------------------------------------
`axial.cli` wires up every subcommand at import time, including `brief`,
`gate` and `panel`, which pulls in `axial.answer`, `axial.analyze` and
`axial.brief` regardless of which subcommand a test actually calls. The
no-Phase-B-import guarantee
(`test_paper_pipeline.py::test_the_no_phase_b_import_guarantee_still_holds`)
protects itself against that by running its own `sys.modules` check in a
clean child interpreter rather than in-process, so it cannot be poisoned by
whatever else the same pytest worker happened to import first (a fix that
predates this revival). This file follows the identical seam for
the same reason, one layer up: a plain `python -c` subprocess (the project
venv's own interpreter, not `uv run`, so there is no per-test
dependency-resolution cost) keeps the CLI's wide import surface confined to
a process this test throws away, and the stub client's own call log is
handed back over a small file so the parent process can still assert on it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def _record(brief_id, claims, coverage_map, *, pin=PIN, disposition="proceed"):
    return {
        "brief_id": brief_id,
        "corpus_pin": pin,
        "lens": "state-formation",
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


def _write_analyses(root: Path) -> Path:
    directory = root / "data" / "analyses"
    directory.mkdir(parents=True)
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
            )
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
            )
        ],
        {"Asef Bayat": {"corpus_note_count": 4, "evidence_note_count": 1, "coverage_band": "thin"}},
    )
    (directory / "brief-a.json").write_text(json.dumps(a), encoding="utf-8")
    (directory / "brief-b.json").write_text(json.dumps(b), encoding="utf-8")
    return directory


def _write_lenses(root: Path) -> None:
    directory = root / "config" / "lenses"
    directory.mkdir(parents=True)
    (directory / "state-formation.yaml").write_text(
        "name: state-formation\ndescription: Reads for how state capacity was built.\n",
        encoding="utf-8",
    )


def _write_paper_brief(
    root: Path,
    *,
    analysis_ids,
    thesis="Which account explains the outcome?",
    lens="state-formation",
) -> Path:
    path = root / "paper_brief.yaml"
    content = {"thesis": thesis, "analysis_ids": list(analysis_ids), "lens": lens}
    path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return path


PLAN = {
    "thesis_statement": "Organized challengers explain the outcome better than mass mobilization alone.",
    "sections": [
        {
            "section_id": "s1",
            "heading": "The bellicist account",
            "role": "claim",
            "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}],
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
    {"prose": "War made the state [pc-001].", "new_claims": []},
    {"prose": "Mobilization did not convert [pc-002].", "new_claims": []},
]


SHAPE_RESPONSE = {"band": "strong", "defects": []}


def _run_paper_cli(
    root: Path,
    args: list[str],
    *,
    plan: dict | None = None,
    drafts: list[dict] | None = None,
    shape: dict | None = None,
) -> tuple[int, str, str, list[str | None]]:
    """Run `axial.cli.main(["paper", ...])` in a throwaway child process with
    a stubbed `get_client`, returning (exit_code, stdout, stderr, calls) --
    `calls` is the stub client's own `pass_name` call log, read back from a
    file the child writes, which is what proves a call count claim (P0-12's
    own acceptance bar) without needing the child's objects back by reference.
    """
    calls_log = root / "_stub_calls.json"
    script = f"""
import json, sys
import axial.cli as cli

PLAN = {json.dumps(plan if plan is not None else PLAN)}
DRAFTS = {json.dumps(drafts if drafts is not None else DRAFTS)}
SHAPE = {json.dumps(shape if shape is not None else SHAPE_RESPONSE)}


class StubClient:
    # `paper_shape` deliberately resolves to a DIFFERENT model than
    # `paper_draft` -- the shape check's own self-grading guard (issue #578)
    # raises if the two ever match.
    model_by_pass = {{
        "paper_plan": "stub/plan",
        "paper_draft": "stub/draft",
        "paper_shape": "stub/shape",
    }}

    def __init__(self):
        self._drafts = list(DRAFTS)
        self.calls = []

    def complete(self, prompt, pass_name=None, **_):
        self.calls.append(pass_name)
        if pass_name == "paper_plan":
            return json.dumps(PLAN)
        if pass_name == "paper_draft":
            return json.dumps(self._drafts.pop(0))
        if pass_name == "paper_shape":
            return json.dumps(SHAPE)
        raise AssertionError("unexpected pass_name: " + str(pass_name))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)

    def usage_for_pass(self, pass_name=None):
        return None


client = StubClient()
cli.get_client = lambda: client
exit_code = cli.main({json.dumps(args)})
with open({str(calls_log)!r}, "w", encoding="utf-8") as f:
    json.dump(client.calls, f)
sys.exit(exit_code)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root, capture_output=True, text=True
    )
    calls = json.loads(calls_log.read_text(encoding="utf-8")) if calls_log.exists() else []
    return result.returncode, result.stdout, result.stderr, calls


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _write_analyses(tmp_path)
    _write_lenses(tmp_path)
    return tmp_path


def test_draft_writes_the_record_and_the_rendered_paper(root):
    brief_path = _write_paper_brief(root, analysis_ids=["brief-a", "brief-b"])

    exit_code, out, err, calls = _run_paper_cli(root, ["paper", "draft", str(brief_path)])

    assert exit_code == 0, f"stdout: {out!r}\nstderr: {err!r}"
    json_files = list((root / "data" / "papers").glob("*.json"))
    md_files = list((root / "data" / "papers").glob("*.md"))
    assert len(json_files) == 1, f"expected exactly one paper record, got {json_files}"
    assert len(md_files) == 1, f"expected exactly one rendered paper, got {md_files}"
    assert json_files[0].stem == md_files[0].stem

    record = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert record["corpus_pin"] == PIN
    assert record["claims"], "expected the persisted record to carry cited claims"

    assert "paper_brief_id" in out
    # The printed paths are cwd-relative (`run_paper`'s own default dirs),
    # so compare on the filename rather than the fixture's absolute path.
    assert json_files[0].name in out
    assert md_files[0].name in out
    assert calls == ["paper_plan", "paper_draft", "paper_draft", "paper_shape"]
    assert record["shape"]["band"] == "strong"


def test_draft_exits_nonzero_on_a_weak_shape_band_but_still_writes_the_files(root):
    """Issue #578 acceptance criterion 7: a `weak` shape band makes `axial
    paper draft` exit non-zero, and the record and rendered paper are still
    on disk after it."""
    brief_path = _write_paper_brief(root, analysis_ids=["brief-a", "brief-b"])
    weak_shape = {
        "band": "weak",
        "defects": [{"section_id": "s2", "note": "reads as a summary, not an argument"}],
    }

    exit_code, out, err, calls = _run_paper_cli(
        root, ["paper", "draft", str(brief_path)], shape=weak_shape
    )

    assert exit_code == 1, f"stdout: {out!r}\nstderr: {err!r}"
    assert "weak" in err.lower()
    json_files = list((root / "data" / "papers").glob("*.json"))
    md_files = list((root / "data" / "papers").glob("*.md"))
    assert len(json_files) == 1, "the record must still be written on a weak shape band"
    assert len(md_files) == 1, "the rendered paper must still be written on a weak shape band"

    record = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert record["shape"]["band"] == "weak"
    assert record["shape"]["defects"]


def test_examine_makes_zero_drafting_calls(root):
    brief_path = _write_paper_brief(root, analysis_ids=["brief-a", "brief-b"])

    exit_code, out, err, calls = _run_paper_cli(root, ["paper", "examine", str(brief_path)])

    assert exit_code == 0, f"stdout: {out!r}\nstderr: {err!r}"
    # The acceptance bar, pinned by a count: zero calls to the drafting pass.
    assert calls.count("paper_draft") == 0
    assert calls.count("paper_plan") == 1
    assert calls == ["paper_plan"]

    papers_dir = root / "data" / "papers"
    assert not papers_dir.exists() or not any(papers_dir.iterdir()), (
        "`examine` must write nothing under data/papers/"
    )

    assert "claim inventory" in out
    assert "brief-a / a1" in out and "brief-b / b1" in out
    # Each section's own assigned claims (format_plan's per-section view).
    assert "[claim] The bellicist account" in out
    assert "[counter-position] The case against" in out
    assert (
        "brief-a / a1"
        in out.split("[claim] The bellicist account")[1].split("[counter-position]")[0]
    )


def test_draft_rejects_an_unresolvable_analysis_id(root):
    brief_path = _write_paper_brief(root, analysis_ids=["brief-a", "brief-missing"])

    exit_code, out, err, calls = _run_paper_cli(root, ["paper", "draft", str(brief_path)])

    assert exit_code == 1
    assert "brief-missing" in err
    assert "Phase C never runs Phase B" in err
    assert not (root / "data" / "papers").exists()
    assert calls == []


def test_draft_rejects_a_refused_analysis_record(root):
    refused = _record("brief-r", [], {}, disposition="refuse")
    (root / "data" / "analyses" / "brief-r.json").write_text(json.dumps(refused), encoding="utf-8")
    brief_path = _write_paper_brief(root, analysis_ids=["brief-a", "brief-r"])

    exit_code, out, err, calls = _run_paper_cli(root, ["paper", "draft", str(brief_path)])

    assert exit_code == 1
    assert "brief-r" in err
    assert "refus" in err.lower()


def test_draft_rejects_a_hand_mixed_corpus_pin(root):
    """An operator naming records off two different corpus pins by hand must
    see a named, non-crashing rejection (§7.1), not a traceback -- the dev
    briefs under config/paper_briefs/dev/ deliberately never exercise this,
    since they were built to share one pin."""
    stale = _record("brief-s", [], {}, pin="sim-2026-01-01")
    (root / "data" / "analyses" / "brief-s.json").write_text(json.dumps(stale), encoding="utf-8")
    brief_path = _write_paper_brief(root, analysis_ids=["brief-a", "brief-s"])

    exit_code, out, err, calls = _run_paper_cli(root, ["paper", "draft", str(brief_path)])

    assert exit_code == 1
    assert "brief-a" in err and "brief-s" in err
    assert not (root / "data" / "papers").exists()


def test_examine_rejects_the_same_three_intake_errors(root):
    brief_path = _write_paper_brief(root, analysis_ids=["brief-a", "brief-missing"])

    exit_code, out, err, calls = _run_paper_cli(root, ["paper", "examine", str(brief_path)])

    assert exit_code == 1
    assert "brief-missing" in err
    assert calls == []


def test_a_malformed_paper_brief_is_a_brief_error_not_a_crash(root):
    brief_path = root / "broken_brief.yaml"
    # Missing the required 'thesis' field entirely.
    brief_path.write_text("analysis_ids:\n  - brief-a\n", encoding="utf-8")

    exit_code, out, err, calls = _run_paper_cli(root, ["paper", "draft", str(brief_path)])

    assert exit_code == 1
    assert "error:" in err
    assert "thesis" in err
    assert "Traceback" not in err
    assert calls == []


def test_a_missing_paper_brief_file_is_reported_not_a_traceback(root):
    exit_code, out, err, calls = _run_paper_cli(
        root, ["paper", "examine", str(root / "does_not_exist.yaml")]
    )

    assert exit_code == 1
    assert "does_not_exist.yaml" in err
    assert "Traceback" not in err
