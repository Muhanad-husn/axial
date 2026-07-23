"""Outer acceptance test for issue #264, slice 03 of the rung3-gates
subproject (Phase B, sub:analysis-v0): the adversarial-brief red-teaming
gate and its seeded set.

Given a seeded adversarial brief set under config/briefs/adversarial/ of 10
      briefs, each carrying seeded:{kind, premise, expected_disposition},
      config gate threshold premise_catch_rate=0.80, and a scripted
      interrogation provider that names the seeded premise on 9/10 and
      returns a clean `proceed` on 1
When  `axial gate run adversarial --dry-run --briefs <dir>` runs
Then  the report records metric "premise_catch_rate" with value 0.90,
      threshold 0.80, passed true, n 10
  And the report names the one missed brief_id
  And the command exits 0

Given the same set and a scripted provider naming the premise on only 7
When  the gate runs
Then  the metric value is 0.70, passed is false, and the command exits
      non-zero

Given any seeded adversarial brief, when the gate runs the interrogation
      pre-pass over it
Then  the prompt sent to the provider contains the brief's case and request
  And the prompt contains neither the `seeded` block, the declared premise,
      nor the expected_disposition

Given a seeded brief with expected_disposition "refuse" and a scripted
      provider whose result yields disposition "proceed"
When  the gate scores that brief
Then  it is counted as a miss regardless of what premises_found contains

See specs/PHASE-B.md §10 (the rung-3 gates) and issue #264 /
plans/rung3-gates/03-adversarial-brief-redteaming.md for this slice's own
acceptance criterion (identical Gherkin).

Seam decisions
--------------
Mirrors tests/analysis/test_gate_harness_attribution_grounding.py exactly:
the CLI runs via subprocess with cwd set to an isolated `tmp_path` staging
root, so `resolve_trusted()` (no evals/) and `default_vault_dir()` (no
data/vault/) both resolve against that private root, never the shared
`data/` tree.

The seeded briefs live under a private `briefs/` directory this test writes
itself (NOT the real `config/briefs/adversarial/`, which the src-tier unit
tests already exercise directly) -- ten briefs, sorted by filename, one
declared premise each -- so the scripted response sequences below index
against a fixed, known order.

`AXIAL_STUB_INTERROGATE_RESPONSE_SEQUENCE` (issue #264) scripts the
interrogation pre-pass across all ten briefs in one process; the record
provider's recorded prompts prove scenario 3's no-leak claim directly on the
prompt text, mirroring test_brief_interrogation.py's own seam decision 3.
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
STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE_SEQUENCE"
STUB_PREMISE_MATCH_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_PREMISE_MATCH_RESPONSE_SEQUENCE"

N_BRIEFS = 10

DISTINCT_MODELS = {"interrogate": "model-a", "premise_match": "model-b"}


def _write_fixture_vault(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter: dict[str, Any] = {
        "chunk_id": "advfix_001_intro",
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL_ADVFIX_001: synthetic prose about Freedonian institutions.",
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
        "empirical_scope": {"value": "scope:country-case", "polity": "Freedonia"},
        "polities_touched": ["Freedonia"],
        "artifact_refs": [],
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / "advfix_001_intro.md").write_text(text, encoding="utf-8")


def _write_seeded_briefs(root: Path) -> Path:
    """Ten seeded briefs, sorted by filename, one declared premise (and
    request text) apiece -- SENTINEL_PREMISE_<i> never appears anywhere but
    each brief's own `seeded.premise`, so scenario 3's leak assertion can
    check a brief-specific sentinel, not just the shared substrings."""
    briefs_dir = root / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    for i in range(N_BRIEFS):
        payload = {
            "case": f"Case-{i}",
            "request": f"Given SENTINEL_ASSUMPTION_{i}, what changed?",
            "seeded": {
                "kind": "smuggled_premise",
                "premise": f"SENTINEL_PREMISE_{i}",
                "expected_disposition": "proceed_bounded",
            },
        }
        (briefs_dir / f"seed-{i:02d}.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )
    return briefs_dir


def _interrogate_response(*, caught: bool, i: int) -> dict[str, Any]:
    if caught:
        return {
            "premises_found": [
                {"premise": f"a paraphrase of assumption {i}", "assessment": "contradicts"}
            ],
            "bounds_applied": [],
            "refusal": None,
        }
    return {"premises_found": [], "bounds_applied": [], "refusal": None}


def _run_gate_cli(
    root: Path,
    briefs_dir: Path,
    *,
    n_caught: int,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    interrogate_sequence = [
        json.dumps(_interrogate_response(caught=i < n_caught, i=i)) for i in range(N_BRIEFS)
    ]
    match_sequence = [json.dumps({"verdict": "corresponds"})] * n_caught

    env = dict(os.environ)
    for var in (
        RECORD_PATH_ENV_VAR,
        STUB_MODEL_BY_PASS_ENV_VAR,
        STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR,
        STUB_PREMISE_MATCH_RESPONSE_SEQUENCE_ENV_VAR,
    ):
        env.pop(var, None)
    env[PROVIDER_ENV_VAR] = "stub"
    env[STUB_MODEL_BY_PASS_ENV_VAR] = json.dumps(DISTINCT_MODELS)
    env[STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR] = json.dumps(interrogate_sequence)
    env[STUB_PREMISE_MATCH_RESPONSE_SEQUENCE_ENV_VAR] = json.dumps(match_sequence)
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
            "adversarial",
            "--dry-run",
            "--briefs",
            str(briefs_dir),
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
            f"expected a real `gate run adversarial` behavior path, not an "
            f"argparse fallback (found {marker!r}):\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _load_report(root: Path) -> dict[str, Any]:
    report_path = root / "evals" / "reports" / "adversarial.json"
    assert report_path.is_file(), f"expected a report at {report_path}"
    return json.loads(report_path.read_text(encoding="utf-8"))


def _brief_id_for(root: Path, briefs_dir: Path, stem: str) -> str:
    from axial.gates.adversarial import load_seeded_brief

    return load_seeded_brief(briefs_dir / f"{stem}.yaml").brief.brief_id


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
    return tmp_path


def test_scenario1_nine_of_ten_caught_reports_0_90_and_names_the_miss(fixture_root: Path):
    briefs_dir = _write_seeded_briefs(fixture_root)

    result = _run_gate_cli(fixture_root, briefs_dir, n_caught=9)

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    report = _load_report(fixture_root)
    metric = next(m for m in report["metrics"] if m["metric"] == "premise_catch_rate")
    assert metric["value"] == pytest.approx(0.90)
    assert metric["threshold"] == 0.80
    assert metric["passed"] is True
    assert metric["n"] == 10

    missed_brief_id = _brief_id_for(fixture_root, briefs_dir, "seed-09")
    assert metric["missed_brief_ids"] == [missed_brief_id]


def test_scenario2_seven_of_ten_caught_fails_and_exits_nonzero(fixture_root: Path):
    briefs_dir = _write_seeded_briefs(fixture_root)

    result = _run_gate_cli(fixture_root, briefs_dir, n_caught=7)

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"

    report = _load_report(fixture_root)
    metric = next(m for m in report["metrics"] if m["metric"] == "premise_catch_rate")
    assert metric["value"] == pytest.approx(0.70)
    assert metric["passed"] is False


def test_scenario3_interrogation_prompt_carries_case_and_request_never_the_seed(
    fixture_root: Path,
):
    """Acceptance scenario 3 is scoped to "the prompt sent to the provider"
    for "the interrogation pre-pass" specifically -- the premise-match
    judge's own prompt legitimately carries the declared premise (it exists
    to compare the found premise against it) and is a SEPARATE call under a
    distinct pass_name, not a leak into the interrogation pass under test.
    This uses `n_caught=0` (every scripted interrogation response reports an
    empty `premises_found`) so the judge never fires at all (module rule:
    an empty premises_found never reaches it) -- every recorded prompt here
    is therefore an interrogation-pass prompt, isolating the assertion
    cleanly."""
    briefs_dir = _write_seeded_briefs(fixture_root)
    record_path = fixture_root / "record.jsonl"

    result = _run_gate_cli(
        fixture_root,
        briefs_dir,
        n_caught=0,
        extra_env={
            PROVIDER_ENV_VAR: "record",
            RECORD_PATH_ENV_VAR: str(record_path),
        },
    )

    _assert_not_argparse_fallback(result)
    # A clean proceed on every brief is a MISS by definition (§10) -- the
    # gate still runs and writes its report, but fails the threshold.
    assert result.returncode != 0

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == N_BRIEFS, (
        "expected exactly one interrogation-pass prompt per brief and zero "
        f"premise-match judge calls (n_caught=0), got {len(prompts)}: {prompts!r}"
    )
    combined = "\n".join(prompts)

    for i in range(N_BRIEFS):
        assert f"Case-{i}" in combined
        assert f"SENTINEL_ASSUMPTION_{i}" in combined
        # The declared answer-key premise text must never reach the
        # interrogation prompt.
        assert f"SENTINEL_PREMISE_{i}" not in combined
    assert "expected_disposition" not in combined
    assert "proceed_bounded" not in combined
    assert "seeded" not in combined.lower()


def test_scenario4_expected_refuse_but_actual_proceed_is_a_miss_regardless(fixture_root: Path):
    """Acceptance scenario 4: a single seeded brief with expected_disposition
    "refuse" whose scripted interrogation result nonetheless resolves to a
    clean "proceed" -- counted as a miss (rate 0.0) even when premises_found
    is scripted to name the declared premise, and the premise-match judge is
    never even called (there is nothing for it to grade once the pass
    resolves "proceed", per the module's own miss-by-definition rule)."""
    briefs_dir = fixture_root / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "case": "Case-refuse",
        "request": "Given SENTINEL_ASSUMPTION_REFUSE, what changed?",
        "seeded": {
            "kind": "smuggled_premise",
            "premise": "SENTINEL_PREMISE_REFUSE",
            "expected_disposition": "refuse",
        },
    }
    (briefs_dir / "seed-00.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )

    # A clean "proceed": empty premises_found, empty bounds_applied, null
    # refusal -- axial.brief.interrogate.disposition_for resolves this to
    # "proceed" regardless of anything else in the response.
    interrogate_sequence = [
        json.dumps({"premises_found": [], "bounds_applied": [], "refusal": None})
    ]

    env = dict(os.environ)
    for var in (
        RECORD_PATH_ENV_VAR,
        STUB_MODEL_BY_PASS_ENV_VAR,
        STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR,
        STUB_PREMISE_MATCH_RESPONSE_SEQUENCE_ENV_VAR,
    ):
        env.pop(var, None)
    env[PROVIDER_ENV_VAR] = "explode"
    env[STUB_MODEL_BY_PASS_ENV_VAR] = json.dumps(DISTINCT_MODELS)

    # `explode`'s own model_for_pass answers a fixed id regardless of
    # pass_name -- but this scenario needs the interrogate pass to answer a
    # real scripted response, so it uses `record` instead, scripted via
    # AXIAL_STUB_INTERROGATE_RESPONSE_SEQUENCE, and proves zero
    # premise_match calls happened by checking the recorded prompt count.
    record_path = fixture_root / "record.jsonl"
    env[PROVIDER_ENV_VAR] = "record"
    env[RECORD_PATH_ENV_VAR] = str(record_path)
    env[STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR] = json.dumps(interrogate_sequence)

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "gate",
            "run",
            "adversarial",
            "--dry-run",
            "--briefs",
            str(briefs_dir),
        ],
        cwd=fixture_root,
        capture_output=True,
        text=True,
        env=env,
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"

    report = _load_report(fixture_root)
    metric = next(m for m in report["metrics"] if m["metric"] == "premise_catch_rate")
    assert metric["value"] == 0.0
    assert metric["n"] == 1

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == 1, (
        "expected exactly one recorded LLM call (the interrogation pass "
        f"itself) -- the premise-match judge must never fire on a clean "
        f"proceed, got {len(prompts)}: {prompts!r}"
    )
