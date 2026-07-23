"""Outer acceptance test for issue #261, slice 02 of the analysis-record
subproject (Phase B, sub:analysis-v0): the deterministic markdown answer
rendered from the analysis record.

Given a fixture analysis record carrying one (a) claim, one (b) claim, one
      (c) claim, a counter-position section with non-empty grounds, a
      coverage_map with one dense polity and one thin polity, and a
      confidence disclosure with a rationale
When  the answer is rendered from that record
Then  each claim's text appears in the markdown
  And each claim's kind is legible on the page as (a), (b), or (c)
  And the counter-position section appears with its stance and grounds
  And every polity in the coverage_map appears with its corpus and evidence
      chunk counts and its coverage band
  And the confidence disclosure and its rationale appear

Given the same fixture record
When  the answer is rendered twice
Then  the two rendered strings are byte-identical

Given a record whose interrogation disposition is "refuse" with a reason and
      whose claims list is empty
When  the answer is rendered
Then  the markdown states the refusal and its reason
  And no claims section is rendered

Given a fixture vault, a corpus pin, and a brief file
  And AXIAL_LLM_PROVIDER=record so every pass is scripted
When  `axial brief run config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0
  And both data/analyses/<brief_id>.json and the rendered markdown answer are
      written
  And re-running the same brief rewrites byte-identical markdown

See specs/PHASE-B.md §7.10 (the rendered markdown answer), §7.7 (the
coverage map), §7.8 (the counter-position section), §7.4 (the claim
kind vocabulary), and issue #261 for this slice's own acceptance criterion
(identical Gherkin). plans/analysis-record/02-markdown-answer-rendering.md
is the slice plan.

Seam decisions
--------------
Scenarios 1-3 exercise `axial.answer.render.render_markdown` directly as a
pure function -- no subprocess, no LLM, no vault -- since the renderer's own
contract is "reads the record and nothing else". Scenario 4 mirrors
tests/analysis/test_brief_run_analysis_record.py's own subprocess harness
(isolated tmp_path staging root, AXIAL_LLM_PROVIDER=record with scripted
responses) to prove the markdown answer is actually wired into
`axial brief run`.
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

from axial.answer.render import render_markdown

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


# --- Scenarios 1-3: the renderer as a pure function over a fixture record --


def _fixture_record() -> dict[str, Any]:
    """The acceptance criterion's own fixture: one (a), one (b), one (c)
    claim; a counter-position section with non-empty grounds; a
    coverage_map with one dense and one thin polity; a confidence
    disclosure with a rationale."""
    return {
        "brief_id": "brf_answer_001",
        "brief": {
            "brief_id": "brf_answer_001",
            "case": "Syria",
            "request": "How did displacement reshape local authority?",
            "lens": None,
        },
        "corpus_pin": "baseline",
        "schema_version": "0.1",
        "lens": "lens:default",
        "interrogation": {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": None,
            "disposition": "proceed",
        },
        "claims": [
            {
                "claim_id": "clm_a",
                "text": "The corpus states that displacement reshaped local authority in Syria.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "syr_001_intro_001"}],
                "confidence": "medium",
                "polities_touched": ["Syria"],
            },
            {
                "claim_id": "clm_b",
                "text": "A cross-source inference linking Syrian and Iraqi displacement dynamics.",
                "kind": "b",
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "syr_001_intro_001"},
                    {"ref_type": "chunk", "ref_id": "irq_001_intro_001"},
                ],
                "confidence": "low",
                "polities_touched": ["Syria", "Iraq"],
            },
            {
                "claim_id": "clm_c",
                "text": "A speculative extension of the pattern beyond the corpus's own cases.",
                "kind": "c",
                "grounds": [],
                "confidence": "low",
                "polities_touched": [],
            },
        ],
        "counter_position": {
            "present": True,
            "stance": "Displacement entrenched, rather than reshaped, existing authority structures.",
            "grounds": [{"ref_type": "chunk", "ref_id": "irq_002_counter_001"}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "coverage_map": {
            "Syria": {
                "corpus_chunk_count": 150,
                "evidence_chunk_count": 2,
                "coverage_band": "dense",
            },
            "Iraq": {
                "corpus_chunk_count": 4,
                "evidence_chunk_count": 1,
                "coverage_band": "thin",
            },
        },
        "confidence": {
            "overall_band": "medium",
            "rationale": (
                "medium confidence, grounded in 2 evidence chunks against a corpus of 150 "
                "chunks on the dense polity and 4 on the thin one"
            ),
        },
        "source_usage": {"filters_observed": [], "sources": []},
        "trajectory": [],
        "model_by_pass": {"interrogate": "stub", "retrieve": "stub", "synthesize": "stub"},
    }


def test_claims_counter_position_coverage_and_confidence_all_render():
    record = _fixture_record()
    markdown = render_markdown(record)

    # Each claim's text and kind are legible on the page.
    assert "The corpus states that displacement reshaped local authority in Syria." in markdown
    assert "A cross-source inference linking Syrian and Iraqi displacement dynamics." in markdown
    assert "A speculative extension of the pattern beyond the corpus's own cases." in markdown
    assert "(a)" in markdown
    assert "(b)" in markdown
    assert "(c)" in markdown

    # The counter-position section appears with its stance and grounds.
    assert "Displacement entrenched, rather than reshaped" in markdown
    assert "irq_002_counter_001" in markdown

    # Every polity in the coverage_map appears with its counts and band.
    assert "Syria" in markdown and "corpus=150" in markdown and "evidence=2" in markdown
    assert "band=dense" in markdown
    assert "Iraq" in markdown and "corpus=4" in markdown and "evidence=1" in markdown
    assert "band=thin" in markdown

    # The confidence disclosure and its rationale appear.
    assert "medium" in markdown
    assert "grounded in 2 evidence chunks against a corpus of 150" in markdown


def test_rendering_the_same_record_twice_is_byte_identical():
    record = _fixture_record()
    first = render_markdown(record)
    second = render_markdown(record)
    assert first == second


def test_refuse_disposition_states_refusal_and_omits_claims_section():
    record = _fixture_record()
    record["interrogation"] = {
        "premises_found": [],
        "bounds_applied": [],
        "refusal": {"reason": "the corpus holds no coverage for the polity this brief depends on"},
        "disposition": "refuse",
    }
    record["claims"] = []

    markdown = render_markdown(record)

    assert "the corpus holds no coverage for the polity this brief depends on" in markdown
    assert "## Claims" not in markdown
    # Nothing from the (now-absent) claims leaks in either.
    assert "displacement reshaped local authority" not in markdown


# --- Scenario 4: `axial brief run` writes both the JSON record and the
# markdown answer, and re-running rewrites byte-identical markdown --------


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


def _extract_brief_id(result: subprocess.CompletedProcess) -> str:
    combined = result.stdout + result.stderr
    match = _BRIEF_ID_PATTERN.search(combined)
    assert match, f"expected a printed brief_id, got:\nstdout: {result.stdout!r}"
    return match.group(1)


def test_brief_run_writes_both_json_and_markdown_and_rerun_is_byte_identical(
    fixture_root: Path,
):
    stub_interrogate_response = {"premises_found": [], "bounds_applied": [], "refusal": None}
    stub_tool_calls = [
        {"tool": "get_chunk", "args": {"chunk_id": SYRIA_A}},
        {"tool": "get_chunk", "args": {"chunk_id": IRAQ_A}},
        None,
    ]
    stub_synthesize_response = {
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

    first = _run_brief_run_cli(
        fixture_root,
        record_path=fixture_root / "record_1.jsonl",
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )
    assert first.returncode == 0, (
        f"expected exit 0, got {first.returncode}\nstdout: {first.stdout!r}\nstderr: {first.stderr!r}"
    )
    brief_id = _extract_brief_id(first)

    json_path = fixture_root / "data" / "analyses" / f"{brief_id}.json"
    markdown_path = fixture_root / "data" / "analyses" / f"{brief_id}.md"
    assert json_path.is_file(), f"expected {json_path} to exist"
    assert markdown_path.is_file(), f"expected {markdown_path} to exist"

    first_markdown = markdown_path.read_text(encoding="utf-8")
    assert "(a)" in first_markdown and "(b)" in first_markdown

    second = _run_brief_run_cli(
        fixture_root,
        record_path=fixture_root / "record_2.jsonl",
        stub_interrogate_response=stub_interrogate_response,
        stub_tool_calls=stub_tool_calls,
        stub_synthesize_response=stub_synthesize_response,
    )
    assert second.returncode == 0, second.stderr
    second_id = _extract_brief_id(second)
    assert second_id == brief_id

    second_markdown = markdown_path.read_text(encoding="utf-8")
    assert first_markdown == second_markdown
