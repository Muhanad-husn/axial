"""Outer acceptance test for issue #257, slice 01 of the analysis-record
subproject (Phase B, sub:analysis-v0): the analysis record and
`axial brief run`.

Given a fixture vault, a written corpus pin under evals/corpus_pin/, and a
      brief file config/briefs/dev/fixture-syria-displacement.yaml
  And AXIAL_LLM_PROVIDER=record so interrogation, retrieval, and synthesis
      are all scripted, the interrogation yielding disposition "proceed"
When  `axial brief run config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And data/analyses/<brief_id>.json exists, where <brief_id> is the id the
      brief loader computes for that brief
  And the record carries every §7.3 key: brief_id, brief, corpus_pin,
      schema_version, lens, interrogation, claims, counter_position,
      coverage_map, confidence, trajectory, model_by_pass
  And record["brief"] equals the loaded brief verbatim
  And record["corpus_pin"] equals the pin id under evals/corpus_pin/
  And record["claims"] equals the claim graph the synthesis pass emitted
  And record["trajectory"] is a list of {step, tool, args, result_ids,
      result_count} entries in tool-call order
  And record["model_by_pass"] names each pass that ran

Given the same brief run a second time over the same pinned vault
When  `axial brief run` runs again
Then  the record is written to the identical path data/analyses/<brief_id>.json

Given a brief whose scripted interrogation yields disposition "refuse" with
      a reason
  And no synthesis-response/tool-call seam is armed (nothing would answer a
      retrieval or synthesis call if one were attempted)
When  `axial brief run` runs on it
Then  the command exits 0
  And data/analyses/<brief_id>.json is still written
  And record["claims"] is the empty list
  And record["interrogation"]["disposition"] is "refuse" with the reason present
  And exactly one LLM call was made (the interrogation call itself), proving
      the synthesis call count is 0

See specs/PHASE-B.md §7.3 (the analysis record), §7.2 (the interrogation
result), §7.12 (the corpus-pin manifest), and §8 P0-8/P0-9 for the source of
truth, and issue #257 for this slice's own acceptance criterion (identical
Gherkin).

Seam decisions
--------------
Mirrors tests/analysis/test_brief_examine.py exactly: an isolated `tmp_path`
staging root as the subprocess `cwd` (never the real, shared `data/` tree),
`AXIAL_LLM_PROVIDER=record` with `AXIAL_LLM_RECORD_PATH` so every prompt is
observable, and the scripted-response env vars issues #252/#254/#256 already
established (`AXIAL_STUB_INTERROGATE_RESPONSE`, `AXIAL_STUB_TOOL_CALLS`,
`AXIAL_STUB_SYNTHESIZE_RESPONSE`). The brief file itself is still the real
repo fixture `config/briefs/dev/fixture-syria-displacement.yaml`, passed by
its absolute path so it resolves regardless of the isolated cwd.

`config/lenses/` is copied into the isolated root (mirroring
`isolated_vault_root`'s own `config/domains/syria/` copy in tests/conftest.py):
the brief under test omits `lens`, so stage 4's `resolve_lens` auto-selects
from `config/lenses/`, which -- being a plain cwd-relative path with no env
override (`axial.analyze.synthesis.DEFAULT_LENSES_DIR`) -- must physically
exist under the isolated cwd to resolve at all.

The refusal scenario proves "zero synthesis calls" the same way
`test_brief_examine.py`'s own refusal scenario does: by counting recorded
prompts (`AXIAL_LLM_RECORD_PATH` lines) rather than a poisoned client,
since `AXIAL_LLM_PROVIDER=explode` would also poison the interrogation call
this scenario legitimately needs to succeed.
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

_BRIEF_ID_PATTERN = re.compile(r"brief_id:\s*(\S+)")

SYRIA_A = "brfix_001_syria_a"
IRAQ_A = "brfix_002_iraq_a"


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
    """A corpus-pin manifest under evals/corpus_pin/<name>.json (§7.12). Its
    CONTENT is never read by `axial brief run` in this slice (issue #257
    scopes out pin-content/mismatch checks) -- only its filename stem is,
    as the record's `corpus_pin` id -- so any well-formed placeholder JSON
    suffices."""
    evals_dir = root / "evals" / "corpus_pin"
    evals_dir.mkdir(parents=True, exist_ok=True)
    (evals_dir / f"{name}.json").write_text(
        json.dumps({"sources": [], "ingest_code_sha": "deadbeef", "vault_snapshot_hash": "abc"}),
        encoding="utf-8",
    )


def _write_fixture_lenses(root: Path) -> None:
    """Copy the real `config/lenses/` into the isolated root so stage 4's
    `resolve_lens` auto-selection has something real to select from --
    mirrors `tests/conftest.py`'s `isolated_vault_root` copying
    `config/domains/syria/` for the same reason."""
    dest = root / "config" / "lenses"
    shutil.copytree(REPO_LENSES_DIR, dest)


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    _write_fixture_vault(tmp_path)
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


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ("invalid choice", "unrecognized arguments"):
        assert marker not in combined, (
            "expected a real `brief run` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `brief run` "
            f"subcommand does not exist yet:\nstdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


def _extract_brief_id(result: subprocess.CompletedProcess) -> str:
    combined = result.stdout + result.stderr
    match = _BRIEF_ID_PATTERN.search(combined)
    assert match, f"expected a printed brief_id, got:\nstdout: {result.stdout!r}"
    return match.group(1)


def _read_recorded_prompts(record_path: Path) -> list[str]:
    if not record_path.exists():
        return []
    return [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]


def _three_kind_synthesize_response() -> dict[str, Any]:
    return {
        "claims": [
            {
                "text": "The corpus states that displacement reshaped local authority in Syria.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": SYRIA_A}],
                "confidence": "medium",
            },
            {
                "text": "A cross-source inference linking Syrian and Iraqi displacement dynamics.",
                "kind": "b",
                "grounds": [
                    {"ref_type": "chunk", "ref_id": SYRIA_A},
                    {"ref_type": "chunk", "ref_id": IRAQ_A},
                ],
                "confidence": "low",
            },
        ]
    }


def test_brief_run_writes_the_full_analysis_record_on_proceed(fixture_root: Path):
    """Scenario 1 (issue #257): every §7.3 key is present, `brief`/
    `corpus_pin`/`claims`/`trajectory`/`model_by_pass` round-trip the
    scripted stages' real output."""
    record_path = fixture_root / "record.jsonl"
    stub_interrogate_response = {"premises_found": [], "bounds_applied": [], "refusal": None}
    stub_tool_calls = [
        {"tool": "get_chunk", "args": {"chunk_id": SYRIA_A}},
        {"tool": "get_chunk", "args": {"chunk_id": IRAQ_A}},
        None,
    ]
    stub_synthesize_response = _three_kind_synthesize_response()

    result = _run_brief_run_cli(
        fixture_root,
        record_path=record_path,
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    brief_id = _extract_brief_id(result)
    record_file = fixture_root / "data" / "analyses" / f"{brief_id}.json"
    assert record_file.is_file(), f"expected {record_file} to exist"

    record = json.loads(record_file.read_text(encoding="utf-8"))

    expected_keys = {
        "brief_id",
        "brief",
        "corpus_pin",
        "schema_version",
        "lens",
        "interrogation",
        "claims",
        "counter_position",
        "coverage_map",
        "confidence",
        "trajectory",
        "model_by_pass",
    }
    assert expected_keys <= set(record), f"missing §7.3 key(s): {expected_keys - set(record)}"

    assert record["brief_id"] == brief_id
    assert record["brief"] == {
        "brief_id": brief_id,
        "case": "Syria",
        "request": "How did displacement reshape local authority?",
        "lens": None,
    }
    assert record["corpus_pin"] == "baseline"
    assert record["schema_version"] == "0.1"
    assert record["interrogation"]["disposition"] == "proceed"

    claim_texts = {claim["text"] for claim in record["claims"]}
    assert claim_texts == {
        "The corpus states that displacement reshaped local authority in Syria.",
        "A cross-source inference linking Syrian and Iraqi displacement dynamics.",
    }
    by_kind = {claim["kind"]: claim for claim in record["claims"]}
    assert by_kind["a"]["grounds"] == [{"ref_type": "chunk", "ref_id": SYRIA_A}]
    assert by_kind["b"]["polities_touched"] == ["Syria", "Iraq"]

    assert isinstance(record["trajectory"], list) and record["trajectory"]
    for entry in record["trajectory"]:
        assert set(entry) == {"step", "tool", "args", "result_ids", "result_count"}
    assert [entry["tool"] for entry in record["trajectory"]] == ["get_chunk", "get_chunk"]

    assert record["model_by_pass"] == {
        "interrogate": "stub",
        "retrieve": "stub",
        "synthesize": "stub",
    }

    # Issue #363: `cost` carries the same three passes, token usage
    # captured, dollar cost null -- "stub" is never in the real price
    # table, so this proves the unpriced path end-to-end rather than
    # crashing or reporting a fabricated zero.
    assert set(record["cost"]["by_pass"]) == {"interrogate", "retrieve", "synthesize"}
    for pass_name, entry in record["cost"]["by_pass"].items():
        assert entry["prompt_tokens"] > 0, pass_name
        assert entry["total_tokens"] > 0, pass_name
        assert entry["usd"] is None, f"{pass_name}: 'stub' is not in the real price table"
    assert record["cost"]["total_usd"] is None

    # 1 interrogate call + 3 retrieval-loop turns (2 tool calls, then a
    # final turn with no tool call to end the loop cleanly) + 1 synthesize
    # call -- every one of the three passes actually ran and is observable.
    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) == 5, f"expected interrogate+retrieve+synthesize calls, got {prompts!r}"


def test_brief_run_writes_the_identical_path_on_a_second_run(fixture_root: Path):
    """Scenario 2 (issue #257): re-running the same brief over the same
    pinned vault writes to the identical path."""
    stub_interrogate_response = {"premises_found": [], "bounds_applied": [], "refusal": None}
    stub_tool_calls = [{"tool": "get_chunk", "args": {"chunk_id": SYRIA_A}}, None]
    stub_synthesize_response = {"claims": []}

    first = _run_brief_run_cli(
        fixture_root,
        record_path=fixture_root / "record_1.jsonl",
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )
    assert first.returncode == 0, first.stderr
    first_id = _extract_brief_id(first)

    second = _run_brief_run_cli(
        fixture_root,
        record_path=fixture_root / "record_2.jsonl",
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )
    assert second.returncode == 0, second.stderr
    second_id = _extract_brief_id(second)

    assert first_id == second_id
    record_file = fixture_root / "data" / "analyses" / f"{first_id}.json"
    assert record_file.is_file()


def test_brief_run_on_refuse_disposition_writes_empty_claims_and_makes_no_synthesis_call(
    fixture_root: Path,
):
    """Scenario 3 (issue #257): a `refuse` disposition still exits 0, still
    writes the record, `claims` is empty, and exactly one LLM call (the
    interrogation call itself) is made in the whole run -- proving no
    retrieval and no synthesis call ever followed the refusal."""
    record_path = fixture_root / "record.jsonl"
    stub_interrogate_response = {
        "premises_found": [],
        "bounds_applied": [],
        "refusal": {"reason": "the corpus holds no coverage for the polity this brief depends on"},
    }

    result = _run_brief_run_cli(
        fixture_root,
        record_path=record_path,
        stub_interrogate_response=stub_interrogate_response,
    )

    _assert_not_argparse_fallback(result)
    assert result.returncode == 0, (
        f"expected exit 0 on a refuse disposition, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    brief_id = _extract_brief_id(result)
    record_file = fixture_root / "data" / "analyses" / f"{brief_id}.json"
    assert record_file.is_file()

    record = json.loads(record_file.read_text(encoding="utf-8"))
    assert record["claims"] == []
    assert record["interrogation"]["disposition"] == "refuse"
    assert (
        record["interrogation"]["refusal"]["reason"]
        == "the corpus holds no coverage for the polity this brief depends on"
    )
    assert record["trajectory"] == []
    assert record["model_by_pass"] == {"interrogate": "stub"}
    # Issue #363: on refuse, `cost` names only the interrogate pass, mirroring
    # `model_by_pass` -- no retrieve/synthesize entries for stages that never ran.
    assert set(record["cost"]["by_pass"]) == {"interrogate"}

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) == 1, (
        f"expected exactly one recorded LLM call (interrogation only -- no "
        f"retrieval, no synthesis call), got {len(prompts)}: {prompts!r}"
    )
