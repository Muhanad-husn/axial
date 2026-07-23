"""Outer acceptance test for issue #260, slice 03 of the analysis-validators
subproject (Phase B, sub:analysis-v0): the coverage/confidence validator.

Given a vault in which coverage_count reports 240 chunks for polity "Syria"
      and 6 chunks for polity "Yemen"
  And an analysis record at data/analyses/DEV20.json whose claims carry
      polities_touched ["Syria", "Yemen"] across their grounds
  And config coverage_bands of {thin: <20, moderate: 20-99, dense: >=100}
When  `axial brief validate DEV20` runs
Then  the command exits 0
  And coverage_map["Syria"].coverage_band is "dense" with
      corpus_chunk_count 240
  And coverage_map["Yemen"].coverage_band is "thin" with corpus_chunk_count 6
  And zero LLM calls were made building the map (the `explode` provider
      never fires)

Given an analysis record at data/analyses/DEV21.json whose claims touch
      "Yemen"
  And whose coverage_map has no "Yemen" entry
When  `axial brief validate DEV21` runs
Then  the command exits non-zero, the report reason is
      "missing_coverage_entry" naming "Yemen", and no answer is released

Given an analysis record at data/analyses/DEV22.json with a complete
      coverage_map
  And whose confidence is {overall_band: null, rationale: ""}
When  `axial brief validate DEV22` runs
Then  the command exits non-zero with reason "missing_confidence_disclosure"

Given an analysis record at data/analyses/DEV23.json whose coverage_map
      contains a "thin" polity and whose confidence.overall_band is the top
      band
When  `axial brief validate DEV23` runs
Then  the command exits non-zero with reason "confidence_exceeds_coverage"
      naming the thin polity

See specs/PHASE-B.md §7.7 (the coverage map) and §7.9 (the validators) for
the source of truth, and issue #260 /
plans/analysis-validators/03-coverage-and-confidence.md for this slice's own
acceptance criterion (identical Gherkin).

Seam decisions
--------------
Runs the CLI via subprocess with cwd set to an isolated `tmp_path` staging
root, mirroring tests/analysis/test_attribution_validator.py exactly (`axial
brief validate <brief_id>` reads an already-persisted record; it never loads
or re-interrogates a brief). Every claim here is `kind: "c"` (speculation,
empty grounds) -- the coverage/confidence checks are driven entirely by
`polities_touched` and the persisted `coverage_map`/`confidence` fields, so
no fixture vault or grounds resolution is needed, and the attribution
validator (which also runs inside `brief validate`) passes vacuously on
every claim here, isolating each scenario's assertion to the
coverage/confidence reason under test.

`AXIAL_LLM_PROVIDER=explode` is used for every scenario (not `stub`, unlike
the attribution acceptance test): the coverage/confidence validator takes no
LLM client at all, and no fixture claim here is `kind: b`, so a real
poison-client crash would surface immediately if anything on this path ever
attempted a model call -- directly proving the acceptance criterion's "the
explode provider is installed in tests and never fires."
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"


def _speculative_claim(claim_id: str, *, polities_touched: list[str]) -> dict[str, Any]:
    """A minimally-shaped §7.4 claim: kind "c" (speculation) carries no
    grounds requirement, so these fixtures need no fixture vault at all --
    only `polities_touched` (the coverage/confidence checks' own input) and
    the fields the attribution validator's mechanical checks read."""
    return {
        "claim_id": claim_id,
        "text": f"Speculative claim text for {claim_id}.",
        "kind": "c",
        "grounds": [],
        "confidence": "medium",
        "polities_touched": polities_touched,
    }


def _write_record(
    root: Path,
    brief_id: str,
    *,
    claims: list[dict[str, Any]],
    coverage_map: dict[str, Any],
    confidence: dict[str, Any],
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
        "counter_position": {
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "coverage_map": coverage_map,
        "confidence": confidence,
        "trajectory": [],
        "model_by_pass": {},
    }
    path = analyses_dir / f"{brief_id}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    return tmp_path


def _run_brief_validate_cli(root: Path, brief_id: str) -> subprocess.CompletedProcess:
    """Forces `AXIAL_LLM_PROVIDER=explode`: the coverage/confidence
    validator never calls a client, and every fixture claim here is kind
    "c" (so the attribution validator's bounded (b)-seam check never fires
    either) -- a real model call anywhere on this path would crash the
    process instead of passing quietly."""
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"
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


def test_scenario1_complete_map_and_valid_confidence_passes(fixture_root: Path):
    """Scenario 1 (DEV20): a vault where coverage_count would report 240
    Syria chunks and 6 Yemen chunks -- here disclosed directly via the
    persisted coverage_map (mirroring what `compute_coverage_map` would
    produce over such a vault, unit-tested separately in
    src/axial/validators/test_coverage.py). Both touched polities have a
    complete entry, confidence is disclosed with a non-empty rationale, and
    confidence is not the top band -- exit 0, zero LLM calls (the `explode`
    provider is never invoked)."""
    _write_record(
        fixture_root,
        "DEV20",
        claims=[_speculative_claim("c-1", polities_touched=["Syria", "Yemen"])],
        coverage_map={
            "Syria": {
                "corpus_chunk_count": 240,
                "evidence_chunk_count": 1,
                "coverage_band": "dense",
            },
            "Yemen": {
                "corpus_chunk_count": 6,
                "evidence_chunk_count": 1,
                "coverage_band": "thin",
            },
        },
        confidence={
            "overall_band": "medium",
            "rationale": "240 corpus chunks on Syria, 6 on Yemen; disclosed accordingly.",
        },
    )

    result = _run_brief_validate_cli(fixture_root, "DEV20")

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "PASS" in result.stdout
    assert "dense" in result.stdout
    assert "thin" in result.stdout
    assert "240" in result.stdout
    assert "6" in result.stdout


def test_scenario2_missing_coverage_entry_blocks_release(fixture_root: Path):
    """Scenario 2 (DEV21): claims touch "Yemen" but coverage_map carries no
    Yemen entry at all -- exit non-zero, reason "missing_coverage_entry"
    naming "Yemen", no answer file appears (this command never writes any
    file)."""
    _write_record(
        fixture_root,
        "DEV21",
        claims=[_speculative_claim("c-1", polities_touched=["Yemen"])],
        coverage_map={},
        confidence={"overall_band": "medium", "rationale": "no coverage entry was computed"},
    )
    analyses_dir = fixture_root / "data" / "analyses"
    before = set(analyses_dir.iterdir())

    result = _run_brief_validate_cli(fixture_root, "DEV21")

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "missing_coverage_entry" in result.stdout
    assert "Yemen" in result.stdout

    after = set(analyses_dir.iterdir())
    assert after == before, "the validator must never write/edit any file -- no answer released"


def test_scenario3_missing_confidence_disclosure_blocks_release(fixture_root: Path):
    """Scenario 3 (DEV22): a complete coverage_map, but confidence is
    `{overall_band: null, rationale: ""}` -- exit non-zero, reason
    "missing_confidence_disclosure"."""
    _write_record(
        fixture_root,
        "DEV22",
        claims=[_speculative_claim("c-1", polities_touched=["Syria"])],
        coverage_map={
            "Syria": {
                "corpus_chunk_count": 240,
                "evidence_chunk_count": 1,
                "coverage_band": "dense",
            }
        },
        confidence={"overall_band": None, "rationale": ""},
    )

    result = _run_brief_validate_cli(fixture_root, "DEV22")

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "missing_confidence_disclosure" in result.stdout


def test_scenario4_confidence_exceeds_coverage_blocks_release(fixture_root: Path):
    """Scenario 4 (DEV23): coverage_map contains a "thin" polity (Yemen)
    while confidence.overall_band is the top band ("high") -- exit
    non-zero, reason "confidence_exceeds_coverage" naming "Yemen"."""
    _write_record(
        fixture_root,
        "DEV23",
        claims=[_speculative_claim("c-1", polities_touched=["Syria", "Yemen"])],
        coverage_map={
            "Syria": {
                "corpus_chunk_count": 240,
                "evidence_chunk_count": 1,
                "coverage_band": "dense",
            },
            "Yemen": {
                "corpus_chunk_count": 6,
                "evidence_chunk_count": 1,
                "coverage_band": "thin",
            },
        },
        confidence={
            "overall_band": "high",
            "rationale": "240 corpus chunks on Syria, 6 on Yemen.",
        },
    )

    result = _run_brief_validate_cli(fixture_root, "DEV23")

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "confidence_exceeds_coverage" in result.stdout
    assert "Yemen" in result.stdout


def test_refuse_disposition_empty_claims_passes_vacuously(fixture_root: Path):
    """§7.2: a `refuse` disposition carries an empty `claims` list -- the
    coverage-entry check passes vacuously (no touched polities); confidence
    is still required and disclosed here, so the whole command exits 0."""
    _write_record(
        fixture_root,
        "DEV24",
        claims=[],
        coverage_map={},
        confidence={"overall_band": "low", "rationale": "refused; no synthesis was attempted"},
    )

    result = _run_brief_validate_cli(fixture_root, "DEV24")

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0 on an empty claim list, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "PASS" in result.stdout
