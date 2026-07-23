"""Outer acceptance test for issue #263, slice 02 of the rung3-gates
subproject (Phase B, sub:analysis-v0): the synthesis-quality and calibration
gates.

Given a directory of 20 analysis records of which 10 are contested by the
      analysis-validators contested-detection rule (#259)
  And all 10 contested records are present-or-disclosed
  And config gate threshold counter_position_presence_rate of 0.95
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the report records metric "counter_position_presence_rate" with value
      1.00, threshold 0.95, passed true, n 10
  And the 10 uncontested records are excluded from n, not counted as passes
  And the command exits 0

Given the same directory with two contested records carrying
      {present: false, grounds: [], corpus_one_sided: false}
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the metric value is 0.83 (10/12), passed is false, the command exits
      non-zero, and the report names both failing brief_ids

Given a directory of contested records with a stated counter-position
  And a scripted judge scoring it against the steelman-quality check
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the report also carries metric "steelman_quality" with its threshold
      and pass/fail
  And the judge call was anchored to the record's counter_position grounds
      text
  And the judge ran under a pass_name distinct from the synthesis pass

Given a directory of records carrying disclosed per-claim confidence bands
  And a scripted judge supplying judged correctness per claim
When  `axial gate run calibration --dry-run --records <dir>` runs
Then  the report records metric "band_reliability" with its threshold and
      pass/fail, and a per-band breakdown naming each band's observed rate,
      target rate and n
  And swapping `calibration.band_targets` in config changes the deviation
      with no code change

See specs/PHASE-B.md §10 (the rung-3 gates), §7.4 (the confidence bands) and
§7.8 (counter-position) for the source of truth, and issue #263 /
plans/rung3-gates/02-synthesis-quality-and-calibration-gates.md for this
slice's own planned acceptance criterion.

Spec correction (deliberate deviation from the plan's calibration scenario)
-----------------------------------------------------------------------
The plan (and issue #263's own body) frames the calibration metric choice
as a live, unresolved Open Question ("ECE vs Brier vs a reliability-diagram
summary") to be landed behind a swappable `calibration.metric` config key
with a provisional metric name and an `open_question` report note. That
framing predates -- and is superseded by -- `specs/PHASE-B.md`'s own v1.1
revision (commit e0d572b, 2026-07-20, "Founder-adjudicated pre-build
revision"), landed on `main` before this issue was even dispatched: §10 now
states plainly that calibration is measured **band-wise**, and that
"Expected calibration error and Brier score both presuppose a numeric
confidence the three-band vocabulary deliberately does not produce, so they
are inapplicable here rather than merely unchosen." Building the
issue's `calibration.metric` seam would re-litigate an already-settled
question and ship exactly the kind of one-implementation config knob the
project's own over-engineering tripwires flag. This test (and
`src/axial/gates/calibration.py`) is written against the CURRENT,
authoritative spec text instead -- see that module's own docstring for the
full reasoning. Flagged in the PR body for founder review.

Seam decisions
--------------
Runs the CLI via subprocess with cwd set to an isolated `tmp_path` staging
root, mirroring tests/analysis/test_gate_harness_attribution_grounding.py
exactly. Scenario 3 uses the `stub` provider's `AXIAL_STUB_COUNTER_POSITION_
RESPONSE` override (the synthesis-quality gate's judge reuses
`validate_counter_position`'s own steelman check, pass_name
"counter_position"); scenario 4 uses the `record` provider plus
`AXIAL_STUB_CALIBRATION_RESPONSE_SEQUENCE` to script per-claim verdicts and
prove each judge call carried the claim text and the resolved grounds text.
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
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"
STUB_MODEL_BY_PASS_ENV_VAR = "AXIAL_STUB_MODEL_BY_PASS"
STUB_COUNTER_POSITION_RESPONSE_ENV_VAR = "AXIAL_STUB_COUNTER_POSITION_RESPONSE"
STUB_CALIBRATION_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_CALIBRATION_RESPONSE_SEQUENCE"

CHUNK_A = "gate_sq_bellicist"  # theory_school: bellicist
CHUNK_B = "gate_sq_marxist"  # theory_school: marxist-political-economy (the 2nd school)


def _chunk_frontmatter(chunk_id: str, *, theory_school_primary: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose supporting the claim.",
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
    for chunk_id, school in ((CHUNK_A, "bellicist"), (CHUNK_B, "marxist-political-economy")):
        text = (
            "---\n"
            + yaml.safe_dump(
                _chunk_frontmatter(chunk_id, theory_school_primary=school), sort_keys=False
            )
            + "---\nBody.\n"
        )
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _grounds(*chunk_ids: str) -> list[dict[str, str]]:
    return [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids]


def _contested_claim(claim_id: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Claim text for {claim_id}.",
        "kind": "a",
        "grounds": _grounds(CHUNK_A, CHUNK_B),
        "confidence": "medium",
    }


def _uncontested_claim(claim_id: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Claim text for {claim_id}.",
        "kind": "a",
        "grounds": _grounds(CHUNK_A),
        "confidence": "medium",
    }


def _disclosed_one_sided() -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": "corpus carries no opposing school on this case",
    }


def _absent_counter_position() -> dict[str, Any]:
    return {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _present_counter_position() -> dict[str, Any]:
    return {
        "present": True,
        "stance": "The opposing school holds a competing account.",
        "grounds": _grounds(CHUNK_B),
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }


def _write_records(root: Path, records: dict[str, dict[str, Any]]) -> Path:
    records_dir = root / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    for stem, record in records.items():
        (records_dir / f"{stem}.json").write_text(json.dumps(record), encoding="utf-8")
    return records_dir


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
    return tmp_path


def _run_gate_cli(
    root: Path, gate: str, records_dir: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for var in (
        RECORD_PATH_ENV_VAR,
        STUB_MODEL_BY_PASS_ENV_VAR,
        STUB_COUNTER_POSITION_RESPONSE_ENV_VAR,
        STUB_CALIBRATION_RESPONSE_SEQUENCE_ENV_VAR,
    ):
        env.pop(var, None)
    env[PROVIDER_ENV_VAR] = "stub"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "gate",
            "run",
            gate,
            "--dry-run",
            "--records",
            str(records_dir),
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
            f"expected a real `gate run` behavior path, not an argparse fallback "
            f"(found {marker!r}):\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _load_report(root: Path, gate: str) -> dict[str, Any]:
    report_path = root / "evals" / "reports" / f"{gate}.json"
    assert report_path.is_file(), f"expected a report at {report_path}"
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_scenario1_all_contested_present_or_disclosed_scores_1_0(fixture_root: Path):
    contested = {
        f"DEV{i}": {
            "brief_id": f"DEV{i}",
            "claims": [_contested_claim(f"DEV{i}-c1")],
            "counter_position": _disclosed_one_sided(),
        }
        for i in range(10)
    }
    uncontested = {
        f"UNC{i}": {
            "brief_id": f"UNC{i}",
            "claims": [_uncontested_claim(f"UNC{i}-c1")],
            "counter_position": _absent_counter_position(),
        }
        for i in range(10)
    }
    records_dir = _write_records(fixture_root, {**contested, **uncontested})

    result = _run_gate_cli(fixture_root, "synthesis-quality", records_dir)

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(fixture_root, "synthesis-quality")
    presence = next(m for m in report["metrics"] if m["metric"] == "counter_position_presence_rate")
    assert presence["value"] == 1.00
    assert presence["threshold"] == 0.95
    assert presence["passed"] is True
    assert presence["n"] == 10, "the 10 uncontested records must be excluded from n"


def test_scenario2_two_failing_contested_records_score_0_83_and_are_named(fixture_root: Path):
    passing = {
        f"DEV{i}": {
            "brief_id": f"DEV{i}",
            "claims": [_contested_claim(f"DEV{i}-c1")],
            "counter_position": _disclosed_one_sided(),
        }
        for i in range(10)
    }
    failing = {
        "BAD1": {
            "brief_id": "BAD1",
            "claims": [_contested_claim("BAD1-c1")],
            "counter_position": _absent_counter_position(),
        },
        "BAD2": {
            "brief_id": "BAD2",
            "claims": [_contested_claim("BAD2-c1")],
            "counter_position": _absent_counter_position(),
        },
    }
    records_dir = _write_records(fixture_root, {**passing, **failing})

    result = _run_gate_cli(fixture_root, "synthesis-quality", records_dir)

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"

    report = _load_report(fixture_root, "synthesis-quality")
    presence = next(m for m in report["metrics"] if m["metric"] == "counter_position_presence_rate")
    assert presence["n"] == 12
    assert presence["value"] == pytest.approx(10 / 12)
    assert presence["passed"] is False
    assert set(presence["failing_brief_ids"]) == {"BAD1", "BAD2"}
    assert "BAD1" in result.stdout and "BAD2" in result.stdout


def test_scenario3_steelman_quality_judged_under_its_own_pass_name(fixture_root: Path):
    records = {
        "DEV1": {
            "brief_id": "DEV1",
            "claims": [_contested_claim("DEV1-c1")],
            "counter_position": _present_counter_position(),
        }
    }
    records_dir = _write_records(fixture_root, records)
    record_path = fixture_root / "record.jsonl"

    result = _run_gate_cli(
        fixture_root,
        "synthesis-quality",
        records_dir,
        extra_env={
            PROVIDER_ENV_VAR: "record",
            RECORD_PATH_ENV_VAR: str(record_path),
            STUB_COUNTER_POSITION_RESPONSE_ENV_VAR: json.dumps(
                {"verdict": "steelman", "detail": "strong"}
            ),
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"synthesize": "model-a", "counter_position": "model-b"}
            ),
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(fixture_root, "synthesis-quality")
    steelman = next(m for m in report["metrics"] if m["metric"] == "steelman_quality")
    assert steelman["value"] == 1.0
    assert "threshold" in steelman
    assert steelman["passed"] is True

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == 1
    assert f"SENTINEL_{CHUNK_B}" in prompts[0], "the judge must be anchored to the grounds text"


def test_scenario4_band_reliability_reports_bands_and_config_swaps_targets(fixture_root: Path):
    high_band_claims = [
        {
            "claim_id": f"h-{i}",
            "kind": "a",
            "text": f"High-confidence claim {i}.",
            "confidence": "high",
            "grounds": _grounds(CHUNK_A),
        }
        for i in range(10)
    ]
    records = {"REC-1": {"claims": high_band_claims}}
    records_dir = _write_records(fixture_root, records)
    record_path = fixture_root / "record.jsonl"

    responses = [json.dumps({"verdict": "correct"})] * 9 + [json.dumps({"verdict": "incorrect"})]
    base_env = {
        PROVIDER_ENV_VAR: "record",
        RECORD_PATH_ENV_VAR: str(record_path),
        STUB_CALIBRATION_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(responses),
        STUB_MODEL_BY_PASS_ENV_VAR: json.dumps({"synthesize": "model-a", "calibration": "model-b"}),
    }

    result = _run_gate_cli(fixture_root, "calibration", records_dir, extra_env=base_env)

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(fixture_root, "calibration")
    metric = report["metrics"][0]
    assert metric["metric"] == "band_reliability"
    assert metric["threshold"] == 0.15
    assert metric["bands"]["high"]["observed"] == pytest.approx(0.9)
    assert metric["bands"]["high"]["target"] == 0.85
    assert metric["bands"]["high"]["n"] == 10
    assert metric["passed"] is True
    assert "note" in metric

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == 10
    for prompt in prompts:
        assert "High-confidence claim" in prompt
        assert f"SENTINEL_{CHUNK_A}" in prompt

    # Swapping calibration.band_targets in config changes the deviation with
    # no code change: pin the target far from the observed 0.90 rate.
    record_path.unlink()
    config_path = fixture_root / "config" / "pipeline.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump({"calibration": {"band_targets": {"high": 0.50}}}), encoding="utf-8"
    )

    result2 = _run_gate_cli(fixture_root, "calibration", records_dir, extra_env=base_env)
    _assert_not_argparse_fallback(result2)
    report2 = _load_report(fixture_root, "calibration")
    metric2 = report2["metrics"][0]
    assert metric2["bands"]["high"]["target"] == 0.50
    assert metric2["value"] == pytest.approx(0.40)
    assert metric2["passed"] is False
