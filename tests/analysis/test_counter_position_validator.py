"""Outer acceptance test for issue #259, slice 02 of the analysis-validators
subproject (Phase B, sub:analysis-v0): the counter-position validator.

Given an analysis record at data/analyses/DEV10.json whose evidence chunks carry
      two distinct theory_school values
  And its counter_position is
      {present: true, stance: "...", grounds: [{ref_type: "chunk",
       ref_id: "syr-0042"}], corpus_one_sided: false, one_sided_reason: null}
When  `axial brief validate DEV10` runs
Then  the command exits 0, the report records the brief as contested with signal
      "theory_school_spread", and the counter-position validator reports pass

Given an analysis record at data/analyses/DEV11.json whose evidence chunks carry
      two distinct theory_school values
  And its counter_position is {present: false, stance: null, grounds: [],
      corpus_one_sided: false, one_sided_reason: null}
When  `axial brief validate DEV11` runs
Then  the command exits non-zero, the report reason is
      "contested_without_counter_position", and no answer is released for DEV11

Given an analysis record at data/analyses/DEV12.json whose evidence is contested
  And its counter_position is {present: false, stance: null, grounds: [],
      corpus_one_sided: true,
      one_sided_reason: "corpus carries no state-capacity school on this case"}
When  `axial brief validate DEV12` runs
Then  the command exits 0 and the validator reports pass by explicit one-sided
      disclosure

Given an analysis record at data/analyses/DEV13.json whose evidence chunks carry
      a single theory_school and no role_in_argument counter-position
When  `axial brief validate DEV13` runs
Then  the command exits 0, the report records the brief as uncontested, and the
      counter-position section is not required

See specs/PHASE-B.md §7.8 (the counter-position section) and §7.9 (the
validators) for the source of truth, and issue #259 /
plans/analysis-validators/02-counter-position-validator.md for this slice's
own acceptance criterion (identical Gherkin).

Seam decisions
--------------
Runs the CLI via subprocess with cwd set to an isolated `tmp_path` staging
root, mirroring tests/analysis/test_attribution_validator.py exactly (same
`axial brief validate <brief_id>` boundary). No `config/pipeline.yaml` exists
under the staging root, so `contested_detection.min_distinct_theory_schools`
falls back to its code-level default of 2 -- exactly the threshold every
scenario here is written against.

The steelman-quality check (DEV10, DEV12: `present: true` with grounds) needs
`AXIAL_STUB_MODEL_BY_PASS` to make `counter_position` resolve to a different
model than `synthesize` -- otherwise the stub client's fixed "stub" id for
every pass_name would (correctly) trip the same-model guard before any
mechanical check even gets asserted on.
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

CHUNK_MAIN = "syr-0001"  # theory_school: bellicist
CHUNK_COUNTER = "syr-0042"  # theory_school: marxist-political-economy (the 2nd school)

DISTINCT_MODELS_ENV = {
    STUB_MODEL_BY_PASS_ENV_VAR: json.dumps({"synthesize": "model-a", "counter_position": "model-b"})
}


def _chunk_frontmatter(chunk_id: str, *, theory_school_primary: str) -> dict[str, Any]:
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
            "primary": theory_school_primary,
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
    for chunk_id, school in (
        (CHUNK_MAIN, "bellicist"),
        (CHUNK_COUNTER, "marxist-political-economy"),
    ):
        text = (
            "---\n"
            + yaml.safe_dump(
                _chunk_frontmatter(chunk_id, theory_school_primary=school), sort_keys=False
            )
            + "---\nBody.\n"
        )
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _claim(claim_id: str, *chunk_ids: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Claim text for {claim_id}.",
        "kind": "a",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids],
        "confidence": "medium",
        "polities_touched": ["Syria"],
    }


def _write_record(
    root: Path, brief_id: str, *, claims: list[dict[str, Any]], counter_position: dict[str, Any]
) -> Path:
    analyses_dir = root / "data" / "analyses"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "brief_id": brief_id,
        "brief": {"brief_id": brief_id, "case": "Syria", "request": "A request.", "lens": None},
        "corpus_pin": "baseline",
        "schema_version": "0.1",
        "lens": "political-economy",
        "interrogation": {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": None,
            "disposition": "proceed",
        },
        "claims": claims,
        "counter_position": counter_position,
        # A complete coverage_map for "Syria" (the only polity every claim
        # here touches) and a non-top-band confidence disclosure -- since
        # #260, `_brief_validate` also runs the coverage/confidence
        # validator, so these fixtures must satisfy it too, not just the
        # counter-position validator under test.
        "coverage_map": {
            "Syria": {
                "corpus_chunk_count": 50,
                "evidence_chunk_count": 1,
                "coverage_band": "moderate",
            }
        },
        "confidence": {"overall_band": "low", "rationale": "fixture"},
        "trajectory": [],
        "model_by_pass": {},
    }
    path = analyses_dir / f"{brief_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
    return tmp_path


def _run_brief_validate_cli(
    root: Path, brief_id: str, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop(STUB_MODEL_BY_PASS_ENV_VAR, None)
    env[PROVIDER_ENV_VAR] = "stub"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "brief", "validate", brief_id],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ("invalid choice", "unrecognized arguments"):
        assert marker not in combined, (
            "expected a real `brief validate` behavior path, not an "
            f"argparse fallback (found {marker!r}):\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def test_scenario_dev10_contested_with_grounds_passes(fixture_root: Path):
    """DEV10: evidence spans two distinct theory_school values (contested,
    signal theory_school_spread); the counter_position section is present
    with non-empty grounds -- exit 0, report names the fired signal, the
    counter-position validator reports pass."""
    _write_record(
        fixture_root,
        "DEV10",
        claims=[_claim("c-1", CHUNK_MAIN), _claim("c-2", CHUNK_COUNTER)],
        counter_position={
            "present": True,
            "stance": "The state-capacity school holds a competing account.",
            "grounds": [{"ref_type": "chunk", "ref_id": CHUNK_COUNTER}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
    )

    result = _run_brief_validate_cli(fixture_root, "DEV10", extra_env=DISTINCT_MODELS_ENV)

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "contested=True" in result.stdout
    assert "theory_school_spread" in result.stdout
    assert "PASS" in result.stdout


def test_scenario_dev11_contested_without_counter_position_blocks_release(fixture_root: Path):
    """DEV11: same contested evidence as DEV10, but counter_position is
    entirely absent/false -- exit non-zero, reason
    contested_without_counter_position, no answer released."""
    _write_record(
        fixture_root,
        "DEV11",
        claims=[_claim("c-1", CHUNK_MAIN), _claim("c-2", CHUNK_COUNTER)],
        counter_position={
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
    )
    analyses_dir = fixture_root / "data" / "analyses"
    before = set(analyses_dir.iterdir())

    result = _run_brief_validate_cli(fixture_root, "DEV11")

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "contested_without_counter_position" in result.stdout

    after = set(analyses_dir.iterdir())
    assert after == before, "the validator must never write/edit any file -- no answer released"


def test_scenario_dev12_one_sided_disclosure_passes(fixture_root: Path):
    """DEV12: contested evidence, counter_position not present but
    explicitly disclosed corpus-one-sided with a non-empty reason -- exit 0,
    pass by explicit disclosure."""
    _write_record(
        fixture_root,
        "DEV12",
        claims=[_claim("c-1", CHUNK_MAIN), _claim("c-2", CHUNK_COUNTER)],
        counter_position={
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": True,
            "one_sided_reason": "corpus carries no state-capacity school on this case",
        },
    )

    result = _run_brief_validate_cli(fixture_root, "DEV12")

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "PASS" in result.stdout


def test_scenario_dev13_uncontested_brief_does_not_require_the_section(fixture_root: Path):
    """DEV13: evidence carries a single theory_school and no
    role_in_argument counter-position -- uncontested, exit 0, the section is
    not required (absent/false is fine)."""
    _write_record(
        fixture_root,
        "DEV13",
        claims=[_claim("c-1", CHUNK_MAIN)],
        counter_position={
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
    )

    result = _run_brief_validate_cli(fixture_root, "DEV13")

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "contested=False" in result.stdout
    assert "PASS" in result.stdout
