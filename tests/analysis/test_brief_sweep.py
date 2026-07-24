"""Outer acceptance test for issue #368 (parent #362 slice 1): the
brief-sweep harness -- N draws per brief, concurrent, resumable, gate-scored.

Restates the issue's own gherkin as four scenarios:

  1. A worklist of 2 fixture briefs and `--draws 2`: 4 analysis records are
     written, each to a distinct `(brief, draw)` path, none overwriting
     another.
  2. A sweep interrupted after brief A's both draws completed but before
     brief B started, re-invoked over the same (now wider) worklist: brief
     A's draws are skipped (not re-run, files untouched), brief B's draws
     are attempted.
  3. A worklist where one draw's underlying `run_brief()` raises: that
     `(brief, draw)` is recorded FAILED, the sweep continues, and the other
     draws/briefs complete normally.
  4. A completed sweep over 2 briefs: each brief has its own gate-report
     metrics (scored over just its own draws) and its own quorum-accuracy
     figure, never a single number pooled across both.

Scenarios 1-2 run through the real `axial brief sweep` CLI subprocess with
`AXIAL_LLM_PROVIDER=stub` (issue #368's own scope discipline: 2-3 fixture
briefs, `--draws 2`, the same scale every other acceptance test in this repo
uses -- never the real 30-brief sweep). Scenarios 3-4 call `run_sweep()`
directly: scenario 3 needs a deterministic per-DRAW failure, which a single
shared stub-provider subprocess has no seam to script (every env-var
override in `axial.llm` is process-global, so it cannot fail one specific
draw of one specific brief while leaving its sibling draw and the other
brief clean); scenario 4 asserts on `run_sweep`'s own structured return
value, which a subprocess's stdout would only offer to re-parse.

Fixtures reused, no new fixture content: the real dev briefs
`config/briefs/dev/fixture-syria-displacement.yaml` and
`fixture-iraq-tribal-authority.yaml` (issue #247), and the same
vault/pin/lenses fixture shape `tests/analysis/test_brief_run_analysis_record.py`
already established for driving `run_brief`/`axial brief run` end to end.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

import axial.brief.sweep as sweep_mod

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SYRIA_BRIEF_PATH = REPO_ROOT / "config" / "briefs" / "dev" / "fixture-syria-displacement.yaml"
IRAQ_BRIEF_PATH = REPO_ROOT / "config" / "briefs" / "dev" / "fixture-iraq-tribal-authority.yaml"
REPO_LENSES_DIR = REPO_ROOT / "config" / "lenses"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

SYRIA_A = "brswp_001_syria_a"
IRAQ_A = "brswp_002_iraq_a"

SYRIA_STEM = "fixture-syria-displacement"
IRAQ_STEM = "fixture-iraq-tribal-authority"


def _chunk_frontmatter(*, chunk_id: str, polities_touched: list[str]) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {
            "value": "scope:country-case",
            "polity": polities_touched[0] if polities_touched else None,
        },
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


def _write_fixture_vault(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    notes = [
        _chunk_frontmatter(chunk_id=SYRIA_A, polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id=IRAQ_A, polities_touched=["Iraq"]),
    ]
    for frontmatter in notes:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")


def _write_fixture_pin(root: Path, name: str = "baseline") -> None:
    evals_dir = root / "evals" / "corpus_pin"
    evals_dir.mkdir(parents=True, exist_ok=True)
    (evals_dir / f"{name}.json").write_text(
        json.dumps({"sources": [], "ingest_code_sha": "deadbeef", "vault_snapshot_hash": "abc"}),
        encoding="utf-8",
    )


def _write_fixture_lenses(root: Path) -> None:
    shutil.copytree(REPO_LENSES_DIR, root / "config" / "lenses")


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
    _write_fixture_pin(tmp_path)
    _write_fixture_lenses(tmp_path)
    return tmp_path


def _write_worklist(root: Path, brief_paths: list[Path]) -> Path:
    worklist = root / "worklist.txt"
    worklist.write_text("\n".join(str(path) for path in brief_paths) + "\n", encoding="utf-8")
    return worklist


def _run_sweep_cli(
    root: Path, worklist: Path, *, draws: int, sweep_dir: str = "sweep_out"
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "stub"
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "brief",
            "sweep",
            str(worklist),
            "--draws",
            str(draws),
            "--sweep-dir",
            sweep_dir,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ("invalid choice", "unrecognized arguments"):
        assert marker not in combined, (
            f"expected a real `brief sweep` behavior path, not an argparse "
            f"fallback (found {marker!r}):\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


# --- Scenario 1: no clobbering ------------------------------------------------


def test_sweep_writes_one_record_per_brief_per_draw_with_no_clobbering(fixture_root: Path):
    worklist = _write_worklist(fixture_root, [SYRIA_BRIEF_PATH, IRAQ_BRIEF_PATH])

    result = _run_sweep_cli(fixture_root, worklist, draws=2)

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    sweep_dir = fixture_root / "sweep_out"
    record_files = sorted(sweep_dir.glob("analyses/*/draw*/*.json"))
    assert len(record_files) == 4, record_files
    assert len(set(record_files)) == 4, "every (brief, draw) must land at its own distinct path"

    stems = {path.parent.parent.name for path in record_files}
    assert stems == {SYRIA_STEM, IRAQ_STEM}
    for stem in stems:
        draw_names = {path.parent.name for path in record_files if path.parent.parent.name == stem}
        assert draw_names == {"draw0", "draw1"}

    # Every written record is well-formed and self-consistent with its own
    # path (the brief_id in the filename matches the record's own field).
    for path in record_files:
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["brief_id"] == path.stem
        assert record["interrogation"]["disposition"] == "proceed"


# --- Scenario 2: resume -------------------------------------------------------


def test_sweep_resume_skips_completed_brief_and_attempts_the_new_one(fixture_root: Path):
    worklist_a = _write_worklist(fixture_root, [SYRIA_BRIEF_PATH])
    first = _run_sweep_cli(fixture_root, worklist_a, draws=2)
    assert first.returncode == 0, first.stderr

    sweep_dir = fixture_root / "sweep_out"
    syria_files = sorted(sweep_dir.glob(f"analyses/{SYRIA_STEM}/draw*/*.json"))
    assert len(syria_files) == 2
    mtimes_before = {path: path.stat().st_mtime_ns for path in syria_files}

    # A coarse filesystem mtime clock (some platforms resolve to ~1s) must
    # not itself hide a real re-write.
    time.sleep(1.1)

    worklist_both = _write_worklist(fixture_root, [SYRIA_BRIEF_PATH, IRAQ_BRIEF_PATH])
    second = _run_sweep_cli(fixture_root, worklist_both, draws=2)
    assert second.returncode == 0, second.stderr

    for path, mtime_before in mtimes_before.items():
        assert path.stat().st_mtime_ns == mtime_before, (
            f"{path} was rewritten on the second invocation -- expected a resume-skip"
        )
    assert "skip" in second.stdout.lower() or "SKIP" in second.stdout

    iraq_files = sorted(sweep_dir.glob(f"analyses/{IRAQ_STEM}/draw*/*.json"))
    assert len(iraq_files) == 2


# --- Scenario 3: failure isolation (direct run_sweep, see module docstring) --


def test_sweep_isolates_one_failing_draw_and_the_rest_complete_normally(
    fixture_root: Path, monkeypatch
):
    from axial.llm import StubLLMClient

    worklist = _write_worklist(fixture_root, [SYRIA_BRIEF_PATH, IRAQ_BRIEF_PATH])
    sweep_dir = fixture_root / "sweep_out"

    real_run_brief = sweep_mod.run_brief
    failing_dir = sweep_mod.draw_dir(sweep_dir, SYRIA_STEM, 0)

    def _flaky_run_brief(brief, *, analyses_dir, **kwargs):
        if Path(analyses_dir) == failing_dir:
            raise sweep_mod.AnswerError("synthetic failure injected for this one draw")
        return real_run_brief(brief, analyses_dir=analyses_dir, **kwargs)

    monkeypatch.setattr(sweep_mod, "run_brief", _flaky_run_brief)

    summary = sweep_mod.run_sweep(
        worklist,
        draws=2,
        sweep_dir=sweep_dir,
        client_factory=StubLLMClient,
        vault_dir=fixture_root / "data" / "vault",
        evals_dir=fixture_root / "evals" / "corpus_pin",
        lenses_dir=fixture_root / "config" / "lenses",
    )

    assert summary.total_draws == 4
    assert summary.fail_count == 1
    assert summary.ok_count == 3

    syria_result = next(r for r in summary.briefs if r.brief_stem == SYRIA_STEM)
    iraq_result = next(r for r in summary.briefs if r.brief_stem == IRAQ_STEM)

    statuses = {outcome.draw_index: outcome.status for outcome in syria_result.draws}
    assert statuses[0] == sweep_mod.FAIL_STATUS
    assert "synthetic failure" in next(o.reason for o in syria_result.draws if o.draw_index == 0)
    assert statuses[1] == sweep_mod.OK_STATUS

    # The sibling brief's own draws were never touched by the injected fault.
    assert all(outcome.status == sweep_mod.OK_STATUS for outcome in iraq_result.draws)


# --- Scenario 4: per-brief gate reports + quorum, never pooled ---------------


def test_sweep_scores_gates_and_quorum_per_brief_never_pooled(fixture_root: Path, monkeypatch):
    from axial.llm import StubLLMClient

    worklist = _write_worklist(fixture_root, [SYRIA_BRIEF_PATH, IRAQ_BRIEF_PATH])
    sweep_dir = fixture_root / "sweep_out"

    captured_gate_calls: list[tuple[str, set[str]]] = []
    real_run_gate = sweep_mod.run_gate

    def _capturing_run_gate(gate_name, records, **kwargs):
        captured_gate_calls.append((gate_name, {r["brief_id"] for r in records}))
        return real_run_gate(gate_name, records, **kwargs)

    monkeypatch.setattr(sweep_mod, "run_gate", _capturing_run_gate)

    summary = sweep_mod.run_sweep(
        worklist,
        draws=2,
        sweep_dir=sweep_dir,
        client_factory=StubLLMClient,
        vault_dir=fixture_root / "data" / "vault",
        evals_dir=fixture_root / "evals" / "corpus_pin",
        lenses_dir=fixture_root / "config" / "lenses",
    )

    assert len(summary.briefs) == 2
    assert len(captured_gate_calls) == 2 * len(sweep_mod.SWEEP_GATE_NAMES)

    # Every single gate call's records share exactly ONE brief_id -- proves
    # gate scoring is never pooled across briefs.
    for _gate_name, brief_ids in captured_gate_calls:
        assert len(brief_ids) == 1

    for result in summary.briefs:
        assert set(result.gate_reports) == set(sweep_mod.SWEEP_GATE_NAMES)
        assert result.quorum.n_draws == 2
        # The stub provider is fully deterministic across draws, so both
        # self-consistency figures are the (degenerate but honest) maximum.
        assert result.quorum.disposition_agreement_rate == 1.0
        assert result.quorum.claim_kind_agreement_rate == 1.0

        gate_report_files = sorted(sweep_mod.gates_dir(sweep_dir, result.brief_stem).glob("*.json"))
        assert len(gate_report_files) == 4

        # Issue #368 amendment: per-brief cost carries both token counts and
        # dollar cost, broken down per pass -- not just a flattened total.
        assert result.cost["total_tokens"] > 0
        assert set(result.cost["by_pass"]) == {"interrogate", "retrieve", "synthesize"}
        for entry in result.cost["by_pass"].values():
            assert entry["total_tokens"] > 0
            assert entry["usd"] is None  # "stub" is never in the real price table

    # Two DIFFERENT briefs' gate-report directories are two different paths
    # on disk -- the concrete proof this is per-brief, not one shared report.
    syria_gates_dir = sweep_mod.gates_dir(sweep_dir, SYRIA_STEM)
    iraq_gates_dir = sweep_mod.gates_dir(sweep_dir, IRAQ_STEM)
    assert syria_gates_dir != iraq_gates_dir
    assert syria_gates_dir.is_dir() and iraq_gates_dir.is_dir()
