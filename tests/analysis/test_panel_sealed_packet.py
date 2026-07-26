"""Outer acceptance test for issue #385: the sealed-packet peer-reviewer
panel (specs/PHASE-B.md §9.4, DEC-40/DEC-43).

Given a sample of analysis records, a control record that can carry all three
      planted defects, and three reviewers on three different training labs
  And a scripted panel that names every planted defect
When  `axial panel run --records <dir> --control-record <path>` runs
Then  the positive control passes, every report is `trusted: true`, and the
      command exits 0

Given the same inputs but a generous panel that names no defect at all
When  the same command runs
Then  the control fails, every report is `trusted: false`, the output says no
      number is reportable, and the command exits non-zero

Given a reviewer configured on the SAME training lab as the synthesis pass
When  the same command runs
Then  the command exits non-zero naming the vendor collision, and ZERO
      reviewer calls are made

Given a run that is not asked to write its verdicts
When  the same command runs
Then  nothing is written anywhere under the staging root (DEC-23: a
      reviewer's free-text note can quote source text)

See specs/PHASE-B.md §9.4 for the seven integrity properties, and issue #385.

Seam decisions
--------------
Runs the CLI via subprocess with cwd set to an isolated `tmp_path` staging
root, mirroring tests/analysis/test_gate_harness_attribution_grounding.py.
The fixture vault lives under that root so grounds resolve.

`AXIAL_STUB_MODEL_BY_PASS` puts the synthesis pass and the three reviewers on
four distinct model ids from four distinct training labs -- without it every
pass resolves to the same fixed "stub" id and the different-vendor guard
would, correctly, refuse to run. That the default IS a collision is itself
worth knowing: the guard is on by default, not opt-in.

`AXIAL_STUB_PANEL_REVIEW_RESPONSE_SEQUENCE` scripts one verdict per (packet,
reviewer) call in dispatch order. The panel dispatches strictly sequentially,
so the sequence is deterministic here (unlike the concurrent-dispatch race of
issue #370). Scenario 3 uses the `explode` provider, whose `.complete()`
raises the instant it is invoked -- so a passing test is itself the proof
that zero reviewer calls were made.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
STUB_MODEL_BY_PASS_ENV_VAR = "AXIAL_STUB_MODEL_BY_PASS"
PANEL_SEQUENCE_ENV_VAR = "AXIAL_STUB_PANEL_REVIEW_RESPONSE_SEQUENCE"

CHUNK_IDS = ("panel_syr_0001", "panel_syr_0002", "panel_syr_0003")

# Four distinct training labs: the generating model and three reviewers.
DISTINCT_MODELS = {
    "synthesize": "deepseek/deepseek-v4-pro",
    "panel_review.1": "anthropic/claude-opus-4",
    "panel_review.2": "openai/gpt-5",
    "panel_review.3": "google/gemini-3-pro",
}


def _chunk_frontmatter(chunk_id: str) -> dict[str, Any]:
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
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }


def _write_fixture_vault(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for chunk_id in CHUNK_IDS:
        text = (
            "---\n" + yaml.safe_dump(_chunk_frontmatter(chunk_id), sort_keys=False) + "---\nBody.\n"
        )
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _record() -> dict[str, Any]:
    """An analysis record that can carry all three plants: two claims with
    different grounds, a present counter-position, and a thin-coverage
    polity carrying a below-high claim."""
    return {
        "brief_id": "panel-b-001",
        "claims": [
            {
                "claim_id": "c-1",
                "kind": "a",
                "text": "Bureaucratic capacity fell.",
                "polities_touched": ["syria"],
                "confidence": "medium",
                "grounds": [{"ref_type": "chunk", "ref_id": CHUNK_IDS[0]}],
            },
            {
                "claim_id": "c-2",
                "kind": "a",
                "text": "Militia payrolls grew.",
                "polities_touched": ["lebanon"],
                "confidence": "high",
                "grounds": [{"ref_type": "chunk", "ref_id": CHUNK_IDS[1]}],
            },
        ],
        "counter_position": {
            "present": True,
            "stance": "War strengthened the state.",
            "grounds": [{"ref_type": "chunk", "ref_id": CHUNK_IDS[2]}],
        },
        "coverage_map": {
            "syria": {"coverage_band": "thin", "corpus_chunk_count": 3},
            "lebanon": {"coverage_band": "rich", "corpus_chunk_count": 400},
        },
        "confidence": {"overall_band": "medium", "rationale": "Thin on one polity."},
    }


def _verdict(defects: list[dict[str, str]]) -> str:
    return json.dumps(
        {
            "factual_correctness": "adequate",
            "citation_grounding": "adequate",
            "completeness": "adequate",
            "defects": defects,
        }
    )


def _catching_sequence() -> str:
    """One verdict per call, in dispatch order: three reviewers per plant
    across three plants, then three reviewers over the one sample record.
    Every reviewer names the plant it is looking at."""
    plants = [
        {"claim_id": "c-1", "kind": "mis_grounded", "note": ""},
        {"claim_id": "<counter_position>", "kind": "strawman_counter_position", "note": ""},
        {"claim_id": "c-1", "kind": "overconfident", "note": ""},
    ]
    verdicts = [_verdict([plant]) for plant in plants for _ in range(3)]
    verdicts += [_verdict([])] * 3
    return json.dumps(verdicts)


def _stage(tmp_path: Path) -> tuple[Path, Path]:
    _write_fixture_vault(tmp_path)
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    (records_dir / "panel-b-001.json").write_text(json.dumps(_record()), encoding="utf-8")
    control_path = tmp_path / "control.json"
    control_path.write_text(json.dumps(_record()), encoding="utf-8")
    return records_dir, control_path


def _run(tmp_path: Path, records_dir: Path, control: Path, env_extra: dict[str, str], *args: str):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        [
            "uv",
            "run",
            "axial",
            "panel",
            "run",
            "--records",
            str(records_dir),
            "--control-record",
            str(control),
            *args,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.slow
def test_a_catching_panel_passes_its_control_and_reports_trusted(tmp_path: Path):
    records_dir, control = _stage(tmp_path)
    result = _run(
        tmp_path,
        records_dir,
        control,
        {
            PROVIDER_ENV_VAR: "stub",
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(DISTINCT_MODELS),
            PANEL_SEQUENCE_ENV_VAR: _catching_sequence(),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "CAUGHT" in result.stdout
    assert "passed: True" in result.stdout
    assert "trusted: True" in result.stdout
    assert "NOT human expert judgement" in result.stdout


@pytest.mark.slow
def test_a_generous_panel_fails_its_control_and_reports_untrusted(tmp_path: Path):
    """The default canned verdict names no defect -- exactly the systematic
    generosity the control exists to catch."""
    records_dir, control = _stage(tmp_path)
    result = _run(
        tmp_path,
        records_dir,
        control,
        {
            PROVIDER_ENV_VAR: "stub",
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(DISTINCT_MODELS),
        },
    )
    assert result.returncode != 0
    assert "MISSED" in result.stdout
    assert "no panel number is reportable" in result.stdout
    assert "trusted: False" in result.stdout


@pytest.mark.slow
def test_a_same_vendor_reviewer_is_refused_before_any_reviewer_call(tmp_path: Path):
    """Property 3, enforced before dispatch: the `explode` provider raises
    the instant it is invoked, so exiting on the guard proves zero calls."""
    records_dir, control = _stage(tmp_path)
    result = _run(
        tmp_path,
        records_dir,
        control,
        {PROVIDER_ENV_VAR: "explode"},
    )
    assert result.returncode != 0
    assert "training lab" in result.stderr or "different VENDOR" in result.stderr


@pytest.mark.slow
def test_nothing_is_written_without_an_explicit_out_path(tmp_path: Path):
    """DEC-23, property 7: a reviewer's free-text note can quote source
    text, so a panel run never writes into the tree by default."""
    records_dir, control = _stage(tmp_path)
    before = {path for path in tmp_path.rglob("*")}
    _run(
        tmp_path,
        records_dir,
        control,
        {
            PROVIDER_ENV_VAR: "stub",
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(DISTINCT_MODELS),
            PANEL_SEQUENCE_ENV_VAR: _catching_sequence(),
        },
    )
    assert {path for path in tmp_path.rglob("*")} == before
