"""Outer acceptance test for issue #262, slice 01 of the rung3-gates
subproject (Phase B, sub:analysis-v0): the common gate harness plus the
attribution-fidelity and grounding gates.

Given a directory of analysis records in which all 20 claims across 4 records
      carry a valid kind and resolvable (a)/(b) grounds
  And config gate thresholds of {attribution_completeness: 1.00,
      b_seam_mislabel_rate: 0.05, grounding_support_rate: 0.90}
When  `axial gate run attribution-fidelity --dry-run --records <dir>` runs
Then  the report records metric "attribution_completeness" with value 1.00,
      threshold 1.00, passed true, n 20
  And the report's `trusted` field is false (no corpus pin, no academic cases)
  And the command exits 0

Given the same directory plus one record carrying a claim of kind "a" whose
      grounds point at a chunk_id absent from the vault
When  `axial gate run attribution-fidelity --dry-run --records <dir>` runs
Then  the metric value is below 1.00, passed is false, the command exits
      non-zero, and the report names the failing claim_id

Given a directory of records carrying 10 (a) claims whose grounds resolve
  And a scripted judge answering "supports" for 9 and "does not support" for 1
When  `axial gate run grounding --dry-run --records <dir>` runs
Then  the report records metric "grounding_support_rate" with value 0.90,
      threshold 0.90, passed true, n 10
  And each judge call received the claim text and the resolved chunk text
  And the judge ran under a pass_name distinct from the synthesis pass

Given a config in which the grounding judge pass resolves to the same model as
      the synthesis pass
When  `axial gate run grounding --dry-run --records <dir>` runs
Then  the command exits non-zero with an error naming self-grading, and zero
      judge calls are made (the `explode` provider never fires)

See specs/PHASE-B.md §10 (the rung-3 gates) and §9 (trust/preconditions), plus
issue #262 / plans/rung3-gates/01-gate-harness-attribution-grounding.md for
this slice's own acceptance criterion (identical Gherkin).

Seam decisions
--------------
Runs the CLI via subprocess with cwd set to an isolated `tmp_path` staging
root (mirroring tests/analysis/test_attribution_validator.py and
tests/analysis/test_corpus_pin.py): `resolve_trusted()` reads `evals/
corpus_pin/` and `evals/cases/` as plain paths relative to the process cwd,
and `--records <dir>` is passed as an absolute path so the analysis-record
fixtures can live anywhere under `tmp_path`. An isolated cwd with no `evals/`
directory at all naturally yields `trusted: False` with no setup -- exactly
scenario 1's "no corpus pin, no academic cases" (§9).

`config/pipeline.yaml`'s own `gates:` block already carries the exact §10
starting thresholds this test's Given clause names (1.00 / 0.05 / 0.90), and
this isolated cwd carries no `config/pipeline.yaml` at all, so the harness's
own code-level `DEFAULT_GATE_THRESHOLDS` fallback resolves to the same
numbers -- there is nothing for this test to override.

Scenario 3 uses the `record` provider (mirroring
tests/analysis/test_attribution_validator.py's DEV04 scenario) so the
recorded prompts prove each judge call carried the claim text and the
resolved chunk text, and `AXIAL_STUB_MODEL_BY_PASS` maps the synthesis and
grounding passes to distinct models (otherwise both resolve to the same
fixed "stub"/"record" id and the self-grading guard would, correctly, refuse
to run). Scenario 4 instead uses the `explode` provider: `ExplodingLLMClient.
model_for_pass` answers a FIXED "explode" id regardless of pass_name -- the
synthesis and grounding passes trivially "resolve to the same model" without
any extra scripting -- and its `.complete()` raises the instant it is ever
invoked, so a passing test here is itself the proof that zero judge calls
were made.
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
STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_GROUNDING_RESPONSE_SEQUENCE"

CHUNK_ID = "gate_syr_0001"
MISSING_CHUNK_ID = "gate_syr_9999"


def _chunk_frontmatter(*, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
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
    text = "---\n" + yaml.safe_dump(_chunk_frontmatter(), sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")


def _claim(claim_id: str, *, kind: str, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "kind": kind,
        "text": f"Claim text for {claim_id}.",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
    }


def _write_records(root: Path, records: dict[str, list[dict[str, Any]]]) -> Path:
    """Write `{filename_stem: claims}` as one analysis-record JSON per key
    under a fresh `records/` directory, returning its path."""
    records_dir = root / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    for stem, claims in records.items():
        (records_dir / f"{stem}.json").write_text(json.dumps({"claims": claims}), encoding="utf-8")
    return records_dir


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
    return tmp_path


def _run_gate_cli(
    root: Path, gate: str, records_dir: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop(RECORD_PATH_ENV_VAR, None)
    env.pop(STUB_MODEL_BY_PASS_ENV_VAR, None)
    env.pop(STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR, None)
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


def test_scenario1_all_claims_valid_reports_complete_and_untrusted(fixture_root: Path):
    """Scenario 1: 4 records x 5 claims = 20, all kind "a" with resolvable
    grounds -- attribution_completeness is 1.00, passed, exit 0, and
    `trusted` is false (no corpus pin, no academic cases in this isolated
    cwd)."""
    records = {f"REC-{i}": [_claim(f"c-{i}-{j}", kind="a") for j in range(5)] for i in range(4)}
    records_dir = _write_records(fixture_root, records)

    result = _run_gate_cli(fixture_root, "attribution-fidelity", records_dir)

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(fixture_root, "attribution-fidelity")
    assert report["trusted"] is False
    completeness = next(m for m in report["metrics"] if m["metric"] == "attribution_completeness")
    assert completeness["value"] == 1.00
    assert completeness["threshold"] == 1.00
    assert completeness["passed"] is True
    assert completeness["n"] == 20


def test_scenario2_one_unresolvable_claim_fails_and_names_it(fixture_root: Path):
    """Scenario 2: the same 20 claims plus one more record carrying a
    kind-"a" claim whose grounds point at a missing chunk_id -- the metric
    drops below 1.00, fails, exit non-zero, and the report names the
    failing claim_id."""
    records = {f"REC-{i}": [_claim(f"c-{i}-{j}", kind="a") for j in range(5)] for i in range(4)}
    records["REC-BAD"] = [_claim("c-bad-1", kind="a", chunk_id=MISSING_CHUNK_ID)]
    records_dir = _write_records(fixture_root, records)

    result = _run_gate_cli(fixture_root, "attribution-fidelity", records_dir)

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"

    report = _load_report(fixture_root, "attribution-fidelity")
    completeness = next(m for m in report["metrics"] if m["metric"] == "attribution_completeness")
    assert completeness["value"] < 1.00
    assert completeness["passed"] is False
    assert "c-bad-1" in completeness["failing_claim_ids"]
    assert "c-bad-1" in result.stdout


def test_scenario3_grounding_nine_of_ten_support(fixture_root: Path):
    """Scenario 3: 10 kind-"a" claims whose grounds resolve, a scripted
    judge answering "supports" x9 and "does not support" x1 -- the metric
    is 0.90, passes, each judge call carried the claim text and the
    resolved chunk text, and it ran under a pass_name distinct from
    "synthesize"."""
    records = {"REC-1": [_claim(f"c-{i}", kind="a") for i in range(10)]}
    records_dir = _write_records(fixture_root, records)
    record_path = fixture_root / "record.jsonl"

    responses = [json.dumps({"verdict": "supports"})] * 9 + [
        json.dumps({"verdict": "does_not_support"})
    ]
    result = _run_gate_cli(
        fixture_root,
        "grounding",
        records_dir,
        extra_env={
            PROVIDER_ENV_VAR: "record",
            RECORD_PATH_ENV_VAR: str(record_path),
            STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR: json.dumps(responses),
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"synthesize": "model-a", "grounding": "model-b"}
            ),
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(fixture_root, "grounding")
    metric = report["metrics"][0]
    assert metric["metric"] == "grounding_support_rate"
    assert metric["value"] == pytest.approx(0.90)
    assert metric["threshold"] == 0.90
    assert metric["passed"] is True
    assert metric["n"] == 10

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == 10
    for prompt in prompts:
        assert "Claim text for c-" in prompt
        assert f"SENTINEL_{CHUNK_ID}" in prompt


def test_scenario4_self_grading_guard_blocks_and_makes_zero_judge_calls(fixture_root: Path):
    """Scenario 4: the grounding judge pass resolves to the SAME model as
    the synthesis pass -- the `explode` provider's `model_for_pass` answers
    a fixed id regardless of pass_name, so the two trivially collide with
    no extra scripting, and `explode`'s `.complete()` raising on any call
    means a clean non-zero exit here IS the proof of zero judge calls."""
    records = {"REC-1": [_claim("c-1", kind="a")]}
    records_dir = _write_records(fixture_root, records)

    result = _run_gate_cli(
        fixture_root, "grounding", records_dir, extra_env={PROVIDER_ENV_VAR: "explode"}
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    combined = result.stdout + result.stderr
    assert "self-grading" in combined or "self grading" in combined
    assert "RuntimeError" not in combined, (
        "the explode provider's .complete() must never fire -- a RuntimeError "
        "here would mean a judge call was attempted despite the guard"
    )
