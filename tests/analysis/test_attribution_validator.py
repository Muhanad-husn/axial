"""Outer acceptance test for issue #258, slice 01 of the analysis-validators
subproject (Phase B, sub:analysis-v0): the attribution validator.

Given a vault containing chunk "syr-0001" and artifact "art-0007"
  And an analysis record at data/analyses/DEV01.json whose claims all carry a
      kind in {a,b,c} and whose every (a)/(b) grounds pointer resolves
When  `axial brief validate DEV01` runs
Then  the command exits 0
  And the attribution validator reports pass with zero failures

Given an analysis record at data/analyses/DEV02.json carrying one claim
      "c-003" with no `kind` field
When  `axial brief validate DEV02` runs
Then  the command exits non-zero
  And the report names "c-003" with reason "missing_kind"
  And no answer is released for DEV02

Given an analysis record at data/analyses/DEV03.json carrying one claim
      "c-005" of kind "a" whose grounds is
      [{"ref_type": "chunk", "ref_id": "syr-9999"}]
  And the vault contains no chunk "syr-9999"
When  `axial brief validate DEV03` runs
Then  the command exits non-zero
  And the report names "c-005" with reason "unresolvable_grounds"
  And no answer is released for DEV03

Given an analysis record at data/analyses/DEV04.json carrying one claim
      "c-002" of kind "b" whose text reads as a source assertion
  And the LLM provider is the `record` provider scripted to flag "c-002"
When  `axial brief validate DEV04` runs
Then  the report names "c-002" with reason "b_seam_voiced_as_source"
  And the check ran under a pass_name distinct from the synthesis pass

See specs/PHASE-B.md §7.9 (the validators) and §7.4 (the claim graph) for
the source of truth, and issue #258 /
plans/analysis-validators/01-attribution-validator.md for this slice's own
acceptance criterion (identical Gherkin).

Seam decisions
--------------
Runs the CLI via subprocess with cwd set to an isolated `tmp_path` staging
root (mirroring tests/analysis/test_brief_run_analysis_record.py) -- the
fixture vault and the pre-written analysis records are plain paths relative
to the process cwd, never the real, shared `data/` tree. `axial brief
validate <brief_id>` takes a brief_id, not a brief file path (unlike every
other `brief` subcommand): it reads an already-persisted record, it never
loads or re-interrogates a brief.

Scenario 4 (DEV04) needs `AXIAL_STUB_MODEL_BY_PASS` (issue #258's own new
seam) to make the stub/record clients' `model_for_pass` answer differently
for the synthesis pass vs. the attribution pass -- otherwise both resolve to
the fixed "stub" id and the same-model guard would (correctly) refuse to run
the check at all. A companion scenario proves that guard fires when the two
DO resolve to the same model.
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
STUB_ATTRIBUTION_RESPONSE_ENV_VAR = "AXIAL_STUB_ATTRIBUTION_RESPONSE"
STUB_MODEL_BY_PASS_ENV_VAR = "AXIAL_STUB_MODEL_BY_PASS"

CHUNK_ID = "syr-0001"
ARTIFACT_ID = "art-0007"
MISSING_CHUNK_ID = "syr-9999"


def _chunk_frontmatter(*, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
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


def _artifact_frontmatter(*, artifact_id: str = ARTIFACT_ID) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_role": "case-study",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "source_id": "syr",
        "section": "Synthetic Section",
        "retrievable": True,
        "cited_by": [],
    }


def _write_fixture_vault(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(_chunk_frontmatter(), sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")

    artifacts_dir = root / "data" / "vault" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(_artifact_frontmatter(), sort_keys=False) + "---\nBody.\n"
    (artifacts_dir / f"{ARTIFACT_ID}.md").write_text(text, encoding="utf-8")


def _bare_claim(
    claim_id: str, *, kind: str | None, grounds: list[dict[str, Any]]
) -> dict[str, Any]:
    """A minimally-shaped §7.4 claim -- only the fields this validator
    reads, since a fixture record's job is to drive the validator, not to
    round-trip every §7.4 field."""
    claim: dict[str, Any] = {
        "claim_id": claim_id,
        "text": f"Claim text for {claim_id}.",
        "grounds": grounds,
        "confidence": "medium",
        "polities_touched": [],
    }
    if kind is not None:
        claim["kind"] = kind
    return claim


def _write_record(root: Path, brief_id: str, claims: list[dict[str, Any]]) -> Path:
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
        "coverage_map": {},
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
    """Always forces `AXIAL_LLM_PROVIDER=stub` as a baseline -- `_brief_validate`
    calls `get_client()` unconditionally (mirroring `_brief_run`), and an
    unconfigured install has no secrets.toml/API key, so leaving the
    provider unset would raise `LLMConfigError` before any of this
    validator's own mechanical checks even run. `extra_env` overrides this
    baseline (e.g. `AXIAL_LLM_PROVIDER=record`) for scenarios that need the
    (b)-seam check to actually fire."""
    env = dict(os.environ)
    env.pop(RECORD_PATH_ENV_VAR, None)
    env.pop(STUB_ATTRIBUTION_RESPONSE_ENV_VAR, None)
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


def test_scenario1_clean_record_passes_with_zero_failures(fixture_root: Path):
    """Scenario 1 (DEV01): every claim carries a valid kind, every (a)/(b)
    grounds pointer resolves -- exit 0, zero failures."""
    _write_record(
        fixture_root,
        "DEV01",
        claims=[
            _bare_claim("c-001", kind="a", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}]),
            _bare_claim(
                "c-002",
                kind="b",
                grounds=[
                    {"ref_type": "chunk", "ref_id": CHUNK_ID},
                    {"ref_type": "artifact", "ref_id": ARTIFACT_ID},
                ],
            ),
            _bare_claim("c-003", kind="c", grounds=[]),
        ],
    )

    result = _run_brief_validate_cli(
        fixture_root,
        "DEV01",
        extra_env={
            # A kind-"b" claim triggers the bounded (b)-seam check; the
            # stub provider's `model_for_pass` otherwise answers the same
            # fixed "stub" id for every pass_name, which would (correctly)
            # trip the same-model guard. Distinct models let the happy path
            # actually reach the (default: nothing-flagged) canned check.
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"synthesize": "model-a", "attribution": "model-b"}
            )
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "PASS" in result.stdout
    assert "0 failure" in result.stdout


def test_scenario2_missing_kind_blocks_release(fixture_root: Path):
    """Scenario 2 (DEV02): claim "c-003" has no `kind` field -- exit
    non-zero, report names it with reason "missing_kind", no answer file
    appears (this command never writes any file)."""
    _write_record(fixture_root, "DEV02", claims=[_bare_claim("c-003", kind=None, grounds=[])])
    analyses_dir = fixture_root / "data" / "analyses"
    before = set(analyses_dir.iterdir())

    result = _run_brief_validate_cli(fixture_root, "DEV02")

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "c-003" in result.stdout
    assert "missing_kind" in result.stdout

    after = set(analyses_dir.iterdir())
    assert after == before, "the validator must never write/edit any file -- no answer released"


def test_scenario3_unresolvable_grounds_blocks_release(fixture_root: Path):
    """Scenario 3 (DEV03): claim "c-005" (kind "a") points at a chunk_id
    the vault does not contain -- exit non-zero, reason
    "unresolvable_grounds", no answer released."""
    _write_record(
        fixture_root,
        "DEV03",
        claims=[
            _bare_claim(
                "c-005", kind="a", grounds=[{"ref_type": "chunk", "ref_id": MISSING_CHUNK_ID}]
            )
        ],
    )
    analyses_dir = fixture_root / "data" / "analyses"
    before = set(analyses_dir.iterdir())

    result = _run_brief_validate_cli(fixture_root, "DEV03")

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "c-005" in result.stdout
    assert "unresolvable_grounds" in result.stdout

    after = set(analyses_dir.iterdir())
    assert after == before, "the validator must never write/edit any file -- no answer released"


def test_scenario4_b_seam_check_flags_a_source_voiced_claim(fixture_root: Path):
    """Scenario 4 (DEV04): claim "c-002" (kind "b") is scripted, via the
    `record` provider, to be flagged by the independent (b)-seam check --
    the report names it with reason "b_seam_voiced_as_source". The check
    runs under `pass_name="attribution"`, distinct from
    `pass_name="synthesize"` -- proven by `AXIAL_STUB_MODEL_BY_PASS` mapping
    the two to DIFFERENT models (so the same-model guard does not fire) and
    by exactly one recorded LLM call (there is no synthesis pass in `brief
    validate` at all -- only the b-seam check could have made it)."""
    _write_record(
        fixture_root,
        "DEV04",
        claims=[
            _bare_claim("c-002", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}])
        ],
    )
    record_path = fixture_root / "record.jsonl"

    result = _run_brief_validate_cli(
        fixture_root,
        "DEV04",
        extra_env={
            PROVIDER_ENV_VAR: "record",
            RECORD_PATH_ENV_VAR: str(record_path),
            STUB_ATTRIBUTION_RESPONSE_ENV_VAR: json.dumps({"flagged_claim_ids": ["c-002"]}),
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"synthesize": "model-a", "attribution": "model-b"}
            ),
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0, f"expected non-zero exit, got 0\nstdout: {result.stdout!r}"
    assert "c-002" in result.stdout
    assert "b_seam_voiced_as_source" in result.stdout

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == 1, (
        f"expected exactly one recorded LLM call (the (b)-seam check -- "
        f"`brief validate` makes no interrogation/retrieval/synthesis call "
        f"at all), got {len(prompts)}: {prompts!r}"
    )


def test_same_model_config_raises_a_clear_error(fixture_root: Path):
    """The same-model guard (§7.9): when `AXIAL_STUB_MODEL_BY_PASS` maps
    the synthesis pass and the attribution pass to the SAME model, the
    command errors out loudly instead of silently running the (b)-seam
    check under the generating model."""
    _write_record(
        fixture_root,
        "DEV05",
        claims=[
            _bare_claim("c-009", kind="b", grounds=[{"ref_type": "chunk", "ref_id": CHUNK_ID}])
        ],
    )

    result = _run_brief_validate_cli(
        fixture_root,
        "DEV05",
        extra_env={
            PROVIDER_ENV_VAR: "record",
            RECORD_PATH_ENV_VAR: str(fixture_root / "record.jsonl"),
            STUB_MODEL_BY_PASS_ENV_VAR: json.dumps(
                {"synthesize": "same-model", "attribution": "same-model"}
            ),
        },
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0
    assert "same-model" in result.stdout + result.stderr
    assert "synthesize" in result.stdout + result.stderr or "synthesis" in (
        result.stdout + result.stderr
    )


def test_disposition_refuse_record_passes_vacuously(fixture_root: Path):
    """§7.2: a `refuse` disposition carries an empty `claims` list -- the
    validator passes vacuously, nothing to check."""
    _write_record(fixture_root, "DEV06", claims=[])

    result = _run_brief_validate_cli(fixture_root, "DEV06")

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0 on an empty claim list, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "PASS" in result.stdout


def test_missing_record_is_a_named_non_zero_error(fixture_root: Path):
    """A brief_id with no persisted record is a named, non-zero error --
    never a silent pass."""
    result = _run_brief_validate_cli(fixture_root, "NO-SUCH-BRIEF")

    _assert_not_argparse_fallback(result)
    assert result.returncode != 0
    assert "NO-SUCH-BRIEF" in result.stdout + result.stderr
