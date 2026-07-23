"""Outer acceptance test for issue #265, slice 01 of the source-usage
subproject (Phase B, sub:analysis-v0): the §7.13 `source_usage` field,
disclosed on every analysis record with its denominator.

Given a fixture vault holding 100 chunks matching the filter
      field:political-science + claim_type:causal, of which 22 belong to
      source_id "tilly" and 78 belong to other sources
  And a fixture brief config/briefs/dev/fixture-source-usage.yaml whose
      model passes are driven by the `record` provider (a fixed-response
      stand-in for `stub`, issue #257's own seam)
  And the run's trajectory records a query_by_tag call with exactly that
      filter
  And the run's claims carry grounds over 10 distinct chunks, 6 of them from
      source_id "tilly"
When  `axial brief run config/briefs/dev/fixture-source-usage.yaml` runs
Then  the command exits 0
  And data/analyses/<brief_id>.json carries a source_usage whose
      filters_observed contains that tag filter
  And source_usage.sources entry for "tilly" is
      {evidence_chunk_count: 6, evidence_share: 0.6,
       available_chunk_count: 22, available_share: 0.22,
       usage_ratio: 0.6/0.22}
  And every entry carries evidence_share and available_share together

Given a hand-built analysis record at data/analyses/DEV31.json whose claims'
      grounds all resolve to chunks of a single source_id "gellner"
When  the source-usage computation runs over that record and the fixture
      vault with the `explode` provider installed
Then  zero LLM calls are made
  And source_usage.sources has exactly one entry, for "gellner", with
      evidence_share 1.0 and its real available_share from the fixture vault
  And the record still releases -- no failure, no non-zero exit, no
      validator reason reacts to the concentration

Given a hand-built analysis record at data/analyses/DEV32.json with
      disposition "refuse" and empty claims
When  the source-usage computation runs over that record
Then  source_usage is present with filters_observed from the trajectory and
      an empty sources list

Given a hand-built analysis record at data/analyses/DEV33.json whose
      trajectory filters match zero chunks of source_id "zaum" while its
      grounds cite one
When  the source-usage computation runs over that record
Then  the "zaum" entry has available_chunk_count 0, available_share 0, and
      usage_ratio null

See specs/PHASE-B.md §7.13 (the source-usage disclosure), §7.3 (the record
shape, locked -- this slice only adds the field), and §7.6 (the trajectory
log `filters_observed` reads from) for the source of truth, and issue #265
for this slice's own acceptance criterion (identical Gherkin).

Seam decisions
--------------
Scenario 1 mirrors tests/analysis/test_brief_run_analysis_record.py's own
CLI seam: an isolated `tmp_path` staging root, `AXIAL_LLM_PROVIDER=record`
with scripted responses, the brief file passed by absolute path.

Scenarios 2-4 read "the source-usage computation runs over that record" at
face value: they call `axial.answer.source_usage.compute_source_usage`
directly over a hand-built record (persisted first to
data/analyses/DEV3<N>.json under an isolated root, mirroring the gherkin's
own literal path), never through the full CLI -- there is no engine call to
script for a record that is already finished, and no validator exists yet
in this phase to react to it (issues #258-260), so "the record still
releases" is proven by the computation itself completing without raising
and the record file remaining exactly as written plus the new field.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.answer.record import persist_record
from axial.answer.source_usage import compute_source_usage

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_BRIEF_PATH = REPO_ROOT / "config" / "briefs" / "dev" / "fixture-source-usage.yaml"
REPO_LENSES_DIR = REPO_ROOT / "config" / "lenses"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"
STUB_TOOL_CALLS_ENV_VAR = "AXIAL_STUB_TOOL_CALLS"
STUB_SYNTHESIZE_RESPONSE_ENV_VAR = "AXIAL_STUB_SYNTHESIZE_RESPONSE"

_BRIEF_ID_PATTERN = re.compile(r"brief_id:\s*(\S+)")

FIELD_FILTER = "field:political-science"
CLAIM_TYPE_FILTER = "claim:causal"

TILLY_COUNT = 22
OTHER_COUNT = 78
TILLY_GROUNDS_COUNT = 6
OTHER_GROUNDS_COUNT = 4


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
        "field": {"primary": FIELD_FILTER, "secondary": []},
        "claim_type": {"primary": CLAIM_TYPE_FILTER, "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": None},
        "polities_touched": [],
        "artifact_refs": [],
    }


def _write_fixture_vault_100_chunks(root: Path) -> None:
    """100 chunks all matching field:political-science + claim_type:causal
    (the gherkin's own filter): 22 under source_id "tilly", 78 under
    source_id "other"."""
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for i in range(TILLY_COUNT):
        frontmatter = _chunk_frontmatter(f"tilly_0_intro_{i:03d}")
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    for i in range(OTHER_COUNT):
        frontmatter = _chunk_frontmatter(f"other_0_intro_{i:03d}")
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
    dest = root / "config" / "lenses"
    shutil.copytree(REPO_LENSES_DIR, dest)


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault_100_chunks(tmp_path)
    _write_fixture_pin(tmp_path)
    _write_fixture_lenses(tmp_path)
    return tmp_path


def _run_brief_run_cli(
    root: Path,
    *,
    record_path: Path,
    stub_interrogate_response: dict[str, Any],
    stub_tool_calls: list[dict[str, Any] | None] | None = None,
    stub_synthesize_response: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "record"
    env[RECORD_PATH_ENV_VAR] = str(record_path)
    env[STUB_INTERROGATE_RESPONSE_ENV_VAR] = json.dumps(stub_interrogate_response)
    if stub_tool_calls is not None:
        env[STUB_TOOL_CALLS_ENV_VAR] = json.dumps(stub_tool_calls)
    if stub_synthesize_response is not None:
        env[STUB_SYNTHESIZE_RESPONSE_ENV_VAR] = json.dumps(stub_synthesize_response)
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "axial",
            "brief",
            "run",
            str(FIXTURE_BRIEF_PATH),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _extract_brief_id(result: subprocess.CompletedProcess) -> str:
    combined = result.stdout + result.stderr
    match = _BRIEF_ID_PATTERN.search(combined)
    assert match, f"expected a printed brief_id, got:\nstdout: {result.stdout!r}"
    return match.group(1)


def _grounded_claim(text: str, kind: str, chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "text": text,
        "kind": kind,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids],
        "confidence": "medium",
    }


def test_source_usage_disclosed_with_denominator_via_full_brief_run(fixture_root: Path):
    """Scenario 1 (issue #265): a real `axial brief run` over a fixture
    vault of 100 filter-matching chunks (22 tilly / 78 other), grounds
    citing 10 distinct chunks (6 tilly / 4 other) -- source_usage discloses
    tilly's contribution alongside its real corpus-wide availability."""
    record_path = fixture_root / "record.jsonl"
    stub_interrogate_response = {"premises_found": [], "bounds_applied": [], "refusal": None}
    stub_tool_calls = [
        {
            "tool": "query_by_tag",
            "args": {"field": FIELD_FILTER, "claim_type": CLAIM_TYPE_FILTER},
        },
        None,
    ]
    tilly_grounds = [f"tilly_0_intro_{i:03d}" for i in range(TILLY_GROUNDS_COUNT)]
    other_grounds = [f"other_0_intro_{i:03d}" for i in range(OTHER_GROUNDS_COUNT)]
    stub_synthesize_response = {
        "claims": [
            _grounded_claim("A claim grounded in the tilly chunks.", "a", tilly_grounds),
            _grounded_claim("A cross-source inference over the other chunks.", "b", other_grounds),
        ]
    }

    result = _run_brief_run_cli(
        fixture_root,
        record_path=record_path,
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )

    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    brief_id = _extract_brief_id(result)
    record_file = fixture_root / "data" / "analyses" / f"{brief_id}.json"
    assert record_file.is_file()
    record = json.loads(record_file.read_text(encoding="utf-8"))

    source_usage = record["source_usage"]
    assert source_usage["filters_observed"] == [
        {
            "tool": "query_by_tag",
            "args": {"claim_type": CLAIM_TYPE_FILTER, "field": FIELD_FILTER},
        }
    ]

    by_source = {s["source_id"]: s for s in source_usage["sources"]}
    tilly = by_source["tilly"]
    assert tilly["evidence_chunk_count"] == 6
    assert tilly["evidence_share"] == pytest.approx(0.6)
    assert tilly["available_chunk_count"] == 22
    assert tilly["available_share"] == pytest.approx(0.22)
    assert tilly["usage_ratio"] == pytest.approx(0.6 / 0.22)

    for entry in source_usage["sources"]:
        assert "evidence_share" in entry and "available_share" in entry


def test_source_usage_exits_0_and_writes_the_record_a_second_identical_run(fixture_root: Path):
    """A re-run over the same pinned vault writes to the same path with the
    same source_usage -- determinism carried through the CLI, not just the
    bare function (mirrors test_brief_run_analysis_record.py's own
    identical-path scenario)."""
    stub_interrogate_response = {"premises_found": [], "bounds_applied": [], "refusal": None}
    stub_tool_calls = [
        {"tool": "query_by_tag", "args": {"field": FIELD_FILTER}},
        None,
    ]
    stub_synthesize_response = {"claims": [_grounded_claim("A claim.", "a", ["tilly_0_intro_000"])]}

    first = _run_brief_run_cli(
        fixture_root,
        record_path=fixture_root / "record_1.jsonl",
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )
    assert first.returncode == 0, first.stderr
    first_id = _extract_brief_id(first)
    first_record = json.loads(
        (fixture_root / "data" / "analyses" / f"{first_id}.json").read_text(encoding="utf-8")
    )

    second = _run_brief_run_cli(
        fixture_root,
        record_path=fixture_root / "record_2.jsonl",
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )
    assert second.returncode == 0, second.stderr
    second_id = _extract_brief_id(second)
    second_record = json.loads(
        (fixture_root / "data" / "analyses" / f"{second_id}.json").read_text(encoding="utf-8")
    )

    assert first_id == second_id
    assert first_record["source_usage"] == second_record["source_usage"]


# ---------------------------------------------------------------------------
# Scenarios 2-4: hand-built records, the computation run directly.
# ---------------------------------------------------------------------------


def _persist_hand_built_record(
    analyses_dir: Path,
    brief_id: str,
    *,
    claims: list[dict],
    trajectory: list[dict],
    disposition: str,
) -> dict[str, Any]:
    record = {
        "brief_id": brief_id,
        "brief": {"brief_id": brief_id, "case": "Test", "request": "Test?", "lens": None},
        "corpus_pin": "baseline",
        "schema_version": "0.1",
        "lens": "default",
        "interrogation": {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": None if disposition != "refuse" else {"reason": "no coverage"},
            "disposition": disposition,
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
        "confidence": {"overall_band": "low", "rationale": "placeholder"},
        "trajectory": trajectory,
        "model_by_pass": {"interrogate": "stub"},
    }
    persist_record(brief_id, record, analyses_dir=analyses_dir)
    return record


def test_source_usage_on_a_concentrated_hand_built_record_makes_zero_llm_calls(
    tmp_path: Path, monkeypatch
):
    """Scenario 2 (issue #265, DEV31): grounds all resolve to a single
    source_id "gellner" -- source_usage discloses evidence_share 1.0 and
    the sole entry's real available_share, with zero LLM calls made and no
    failure/non-zero-exit reaction to the concentration."""
    monkeypatch.setenv(PROVIDER_ENV_VAR, "explode")
    from axial.llm import ExplodingLLMClient, get_client

    assert isinstance(get_client(), ExplodingLLMClient)

    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    for i in range(5):
        frontmatter = _chunk_frontmatter(f"gellner_0_intro_{i:03d}")
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")

    analyses_dir = tmp_path / "data" / "analyses"
    claims = [
        _grounded_claim("A claim.", "a", ["gellner_0_intro_000", "gellner_0_intro_001"]),
    ]
    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": FIELD_FILTER},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    record = _persist_hand_built_record(
        analyses_dir, "DEV31", claims=claims, trajectory=trajectory, disposition="proceed"
    )

    # No exception raised, no sentinel failure -- "the record still releases".
    source_usage = compute_source_usage(record, vault_dir=vault_dir)
    record["source_usage"] = source_usage
    persist_record("DEV31", record, analyses_dir=analyses_dir)

    assert (analyses_dir / "DEV31.json").is_file()
    assert len(source_usage["sources"]) == 1
    gellner = source_usage["sources"][0]
    assert gellner["source_id"] == "gellner"
    assert gellner["evidence_share"] == 1.0
    assert gellner["available_chunk_count"] == 5
    assert gellner["available_share"] == pytest.approx(1.0)


def test_source_usage_empty_on_refuse_disposition_with_empty_claims(tmp_path: Path):
    """Scenario 3 (issue #265, DEV32): disposition "refuse" and empty
    claims -- source_usage is present, filters_observed comes from the
    trajectory, sources is empty."""
    analyses_dir = tmp_path / "data" / "analyses"
    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": FIELD_FILTER},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    record = _persist_hand_built_record(
        analyses_dir, "DEV32", claims=[], trajectory=trajectory, disposition="refuse"
    )

    source_usage = compute_source_usage(record, vault_dir=None)
    assert source_usage["sources"] == []
    assert source_usage["filters_observed"] == [
        {"tool": "query_by_tag", "args": {"field": FIELD_FILTER}}
    ]


def test_source_usage_usage_ratio_null_when_filters_match_zero_of_a_cited_sources_chunks(
    tmp_path: Path,
):
    """Scenario 4 (issue #265, DEV33): the trajectory's filters match zero
    chunks of source_id "zaum" while its grounds cite one -- available_
    chunk_count 0, available_share 0, usage_ratio null (never 0, never an
    error)."""
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True)
    # The vault holds real chunks that DO match the observed filter, just
    # none of them belonging to "zaum" -- proving the denominator is a real
    # corpus-wide re-query, not a vacuous empty vault.
    for i in range(3):
        frontmatter = _chunk_frontmatter(f"other_0_intro_{i:03d}")
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")

    analyses_dir = tmp_path / "data" / "analyses"
    claims = [_grounded_claim("A claim.", "a", ["zaum_0_intro_000"])]
    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": FIELD_FILTER},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    record = _persist_hand_built_record(
        analyses_dir, "DEV33", claims=claims, trajectory=trajectory, disposition="proceed"
    )

    source_usage = compute_source_usage(record, vault_dir=vault_dir)
    zaum = source_usage["sources"][0]
    assert zaum["source_id"] == "zaum"
    assert zaum["available_chunk_count"] == 0
    assert zaum["available_share"] == 0
    assert zaum["usage_ratio"] is None
