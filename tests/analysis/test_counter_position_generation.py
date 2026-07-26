"""Outer acceptance test for issue #399: the counter-position section is
GENERATED for real by `axial brief run`, not left at the pre-#399
placeholder (`present: false, corpus_one_sided: false` regardless of
whether the brief is contested).

Given a fixture vault whose two chunks carry two distinct substantive
      theory_school values (a contested brief, `_detect_contested`'s
      theory_school_spread signal)
  And a scripted synthesis response citing both chunks across its claims
  And a scripted counter-position-generation response naming the
      minority-school chunk as PRESENT grounds
When  `axial brief run` runs
Then  the persisted record's `counter_position` is `present: true` with
      `grounds` resolving to the minority-school chunk id
  And `model_by_pass`/`cost` both name the counter_position_generate pass,
      alongside interrogate/retrieve/synthesize

Given the same fixture vault and synthesis response, but a scripted
      counter-position-generation response disclosing the corpus as
      one-sided instead
When  `axial brief run` runs
Then  the persisted record's `counter_position` is `corpus_one_sided: true`
      with a non-blank `one_sided_reason`, `present: false`

Given a fixture vault whose evidence carries only ONE substantive
      theory_school (uncontested) and a scripted synthesis response citing
      only it
When  `axial brief run` runs
Then  the persisted record's `counter_position` is the empty §7.8 shape
  And `model_by_pass`/`cost` name only interrogate/retrieve/synthesize --
      no counter-position-generation call was ever made

See specs/PHASE-B.md §7.8 (the counter-position section) and issue #399 for
this slice's own acceptance criterion.

Seam decisions
--------------
Mirrors tests/analysis/test_brief_run_analysis_record.py exactly: an
isolated `tmp_path` staging root, `AXIAL_LLM_PROVIDER=record` with
`AXIAL_LLM_RECORD_PATH`, and the scripted-response env vars issues
#252/#254/#256/#399 established, including the new
`AXIAL_STUB_COUNTER_POSITION_GENERATE_RESPONSE`.
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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_BRIEF_PATH = REPO_ROOT / "config" / "briefs" / "dev" / "fixture-syria-displacement.yaml"
REPO_LENSES_DIR = REPO_ROOT / "config" / "lenses"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"
STUB_TOOL_CALLS_ENV_VAR = "AXIAL_STUB_TOOL_CALLS"
STUB_SYNTHESIZE_RESPONSE_ENV_VAR = "AXIAL_STUB_SYNTHESIZE_RESPONSE"
STUB_COUNTER_POSITION_GENERATE_RESPONSE_ENV_VAR = "AXIAL_STUB_COUNTER_POSITION_GENERATE_RESPONSE"

_BRIEF_ID_PATTERN = re.compile(r"brief_id:\s*(\S+)")

MAIN_CHUNK = "cpgenacc_001_bellicist_a"
COUNTER_CHUNK = "cpgenacc_002_marxist_a"


def _chunk_frontmatter(
    *, chunk_id: str, theory_school_primary: str, polities_touched: list[str]
) -> dict[str, Any]:
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
        "empirical_scope": {
            "value": "scope:country-case",
            "polity": polities_touched[0] if polities_touched else None,
        },
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


def _write_fixture_vault(root: Path, *, contested: bool) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    notes = [
        _chunk_frontmatter(
            chunk_id=MAIN_CHUNK,
            theory_school_primary="school:bellicist",
            polities_touched=["Syria"],
        )
    ]
    if contested:
        notes.append(
            _chunk_frontmatter(
                chunk_id=COUNTER_CHUNK,
                theory_school_primary="school:marxist-political-economy",
                polities_touched=["Syria"],
            )
        )
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
def contested_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path, contested=True)
    _write_fixture_pin(tmp_path)
    _write_fixture_lenses(tmp_path)
    return tmp_path


@pytest.fixture
def uncontested_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path, contested=False)
    _write_fixture_pin(tmp_path)
    _write_fixture_lenses(tmp_path)
    return tmp_path


def _run_brief_run_cli(
    root: Path,
    *,
    record_path: Path,
    stub_tool_calls: list[dict[str, Any] | None],
    stub_synthesize_response: dict[str, Any],
    stub_counter_position_generate_response: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "record"
    env[RECORD_PATH_ENV_VAR] = str(record_path)
    env[STUB_INTERROGATE_RESPONSE_ENV_VAR] = json.dumps(
        {"premises_found": [], "bounds_applied": [], "refusal": None}
    )
    env[STUB_TOOL_CALLS_ENV_VAR] = json.dumps(stub_tool_calls)
    env[STUB_SYNTHESIZE_RESPONSE_ENV_VAR] = json.dumps(stub_synthesize_response)
    if stub_counter_position_generate_response is not None:
        env[STUB_COUNTER_POSITION_GENERATE_RESPONSE_ENV_VAR] = json.dumps(
            stub_counter_position_generate_response
        )
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


def _synthesize_response(*, chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "claims": [
            {
                "text": f"A claim grounded across the evidence chunk(s): {', '.join(chunk_ids)}.",
                "kind": "b" if len(chunk_ids) > 1 else "a",
                "grounds": [{"ref_type": "chunk", "ref_id": cid} for cid in chunk_ids],
                "confidence": "medium",
            }
        ]
    }


def test_contested_brief_with_scripted_present_response_yields_present_counter_position(
    contested_root: Path,
):
    record_path = contested_root / "record.jsonl"
    stub_tool_calls = [
        {"tool": "get_chunk", "args": {"chunk_id": MAIN_CHUNK}},
        {"tool": "get_chunk", "args": {"chunk_id": COUNTER_CHUNK}},
        None,
    ]
    stub_counter_position_generate_response = {
        "present": True,
        "stance": "The marxist-political-economy material argues war eroded state capacity.",
        "grounds": [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }

    result = _run_brief_run_cli(
        contested_root,
        record_path=record_path,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=_synthesize_response(chunk_ids=[MAIN_CHUNK, COUNTER_CHUNK]),
        stub_counter_position_generate_response=stub_counter_position_generate_response,
    )
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    brief_id = _extract_brief_id(result)
    record = json.loads(
        (contested_root / "data" / "analyses" / f"{brief_id}.json").read_text(encoding="utf-8")
    )

    counter_position = record["counter_position"]
    assert counter_position["present"] is True
    assert counter_position["corpus_one_sided"] is False
    assert counter_position["stance"]
    assert counter_position["grounds"] == [{"ref_type": "chunk", "ref_id": COUNTER_CHUNK}]

    # The generation call is folded into model_by_pass/cost alongside the
    # three engine-stage passes -- a real, priced (here: unpriced-stub) call
    # was made, and the record's own accounting must not drop it.
    assert record["model_by_pass"]["counter_position_generate"] == "stub"
    assert set(record["cost"]["by_pass"]) == {
        "interrogate",
        "retrieve",
        "synthesize",
        "counter_position_generate",
    }
    assert record["cost"]["by_pass"]["counter_position_generate"]["prompt_tokens"] > 0


def test_contested_brief_with_scripted_one_sided_response_yields_disclosure(
    contested_root: Path,
):
    record_path = contested_root / "record.jsonl"
    stub_tool_calls = [
        {"tool": "get_chunk", "args": {"chunk_id": MAIN_CHUNK}},
        {"tool": "get_chunk", "args": {"chunk_id": COUNTER_CHUNK}},
        None,
    ]
    stub_counter_position_generate_response = {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": "the marxist-tagged chunk is a passing aside, not a developed "
        "opposing argument",
    }

    result = _run_brief_run_cli(
        contested_root,
        record_path=record_path,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=_synthesize_response(chunk_ids=[MAIN_CHUNK, COUNTER_CHUNK]),
        stub_counter_position_generate_response=stub_counter_position_generate_response,
    )
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    brief_id = _extract_brief_id(result)
    record = json.loads(
        (contested_root / "data" / "analyses" / f"{brief_id}.json").read_text(encoding="utf-8")
    )

    counter_position = record["counter_position"]
    assert counter_position["present"] is False
    assert counter_position["corpus_one_sided"] is True
    assert counter_position["one_sided_reason"]
    assert counter_position["grounds"] == []


def test_uncontested_brief_never_calls_counter_position_generation(uncontested_root: Path):
    record_path = uncontested_root / "record.jsonl"
    stub_tool_calls = [{"tool": "get_chunk", "args": {"chunk_id": MAIN_CHUNK}}, None]

    result = _run_brief_run_cli(
        uncontested_root,
        record_path=record_path,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=_synthesize_response(chunk_ids=[MAIN_CHUNK]),
        # Deliberately no stub_counter_position_generate_response: if the
        # pipeline called that pass here, it would get the conservative
        # default canned response, not a crash -- so this scenario proves
        # its point by asserting the pass never appears in model_by_pass at
        # all, not merely that a call happened to succeed.
    )
    assert result.returncode == 0, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    brief_id = _extract_brief_id(result)
    record = json.loads(
        (uncontested_root / "data" / "analyses" / f"{brief_id}.json").read_text(encoding="utf-8")
    )

    assert record["counter_position"] == {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": False,
        "one_sided_reason": None,
    }
    assert set(record["model_by_pass"]) == {"interrogate", "retrieve", "synthesize"}
    assert set(record["cost"]["by_pass"]) == {"interrogate", "retrieve", "synthesize"}
