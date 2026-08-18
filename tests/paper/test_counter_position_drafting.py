"""Acceptance test for issue #787 slice 01: `compose_draft_prompt` tells the
drafter what a `counter-position` section obliges.

Same seam and fixture shapes as `test_paper_cli.py` (a child process, so the
CLI's wide import surface -- and the stub client's own call log -- stays
confined to a process this test throws away). What this file adds is capturing
the actual PROMPT text sent for `paper_draft`, per section, so the acceptance
criterion can be checked at the CLI boundary rather than only at
`compose_draft_prompt` directly:

Given a paper brief whose planned arc contains a section with role
"counter-position"
When  an operator runs `axial paper draft <brief>`
Then  the prompt sent for that section instructs the drafter to state the
      opposing position at its strongest before the paper answers it
And   the prompt sent for every other section carries no such instruction
And   the persisted record under data/papers/ still validates unchanged in
      every other respect
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PIN = "sim-2026-08-18"

INSTRUCTION_PHRASE = "at its strongest"


def _claim(claim_id, kind, text, band, chunk_id, names):
    return {
        "claim_id": claim_id,
        "kind": kind,
        "text": text,
        "confidence": band,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "names_touched": names,
    }


def _record(brief_id, claims, coverage_map):
    return {
        "brief_id": brief_id,
        "corpus_pin": PIN,
        "lens": "state-formation",
        "interrogation": {"disposition": "proceed"},
        "claims": claims,
        "coverage_map": coverage_map,
        "counter_position": {
            "present": True,
            "stance": "the opposing account",
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "confidence": {"overall_band": "high", "rationale": "..."},
    }


def _write_analyses(root: Path) -> None:
    directory = root / "data" / "analyses"
    directory.mkdir(parents=True)
    a = _record(
        "brief-a",
        [
            _claim("a1", "a", "War made the state.", "high", "tilly-1978-aaa_1_war_001", ["Tilly"]),
            _claim("a2", "a", "Extraction follows coercion.", "high", "tilly-1978-aaa_2_x_001", ["Tilly"]),
            _claim("a3", "a", "Rulers borrow against future revenue.", "high", "tilly-1978-aaa_3_x_001", ["Tilly"]),
        ],
        {"Tilly": {"corpus_note_count": 30, "evidence_note_count": 3, "coverage_band": "dense"}},
    )
    b = _record(
        "brief-b",
        [
            _claim("b1", "a", "Mobilization did not convert into durable institutions.", "high", "bayat-2017-bbb_1_x_001", ["Bayat"]),
            _claim("b2", "a", "Revolution without revolutionaries still shifts capacity.", "high", "bayat-2017-bbb_2_x_001", ["Bayat"]),
        ],
        {"Bayat": {"corpus_note_count": 10, "evidence_note_count": 2, "coverage_band": "thin"}},
    )
    (directory / "brief-a.json").write_text(json.dumps(a), encoding="utf-8")
    (directory / "brief-b.json").write_text(json.dumps(b), encoding="utf-8")


def _write_lenses(root: Path) -> None:
    directory = root / "config" / "lenses"
    directory.mkdir(parents=True)
    (directory / "state-formation.yaml").write_text(
        "name: state-formation\ndescription: Reads for how state capacity was built.\n",
        encoding="utf-8",
    )


def _write_paper_brief(root: Path) -> Path:
    path = root / "paper_brief.yaml"
    content = {
        "thesis": "Organized challengers explain the outcome better than mass mobilization alone.",
        "analysis_ids": ["brief-a", "brief-b"],
        "lens": "state-formation",
    }
    path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return path


# One section per role in `axial.paper.plan.ROLES`, so every role's prompt is
# exercised in the same run, not only the counter-position one.
PLAN = {
    "thesis_statement": "Organized challengers explain the outcome better than mass mobilization alone.",
    "sections": [
        {"section_id": "s1", "heading": "The puzzle", "role": "setup", "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}]},
        {"section_id": "s2", "heading": "The bellicist account", "role": "claim", "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a2"}]},
        {"section_id": "s3", "heading": "What the record shows", "role": "evidence", "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a3"}]},
        {"section_id": "s4", "heading": "The case against", "role": "counter-position", "assigned_claims": [{"brief_id": "brief-b", "claim_id": "b1"}]},
        {"section_id": "s5", "heading": "Where this lands", "role": "synthesis", "assigned_claims": [{"brief_id": "brief-b", "claim_id": "b2"}]},
    ],
}

DRAFTS = [
    {"prose": "The puzzle is framed here [pc-001].", "new_claims": []},
    {"prose": "The bellicist account holds [pc-002].", "new_claims": []},
    {"prose": "The record shows it [pc-003].", "new_claims": []},
    {"prose": "The opposing account holds that mobilization alone sufficed [pc-004].", "new_claims": []},
    {"prose": "Synthesis follows [pc-005].", "new_claims": []},
]

SHAPE_RESPONSE = {"band": "strong", "defects": []}


def _run_paper_draft(root: Path, brief_path: Path) -> tuple[int, str, str, list[dict]]:
    """Run `axial paper draft` in a throwaway child process with a stubbed
    client that logs every call's `(pass_name, prompt)` pair, read back over
    a small file -- same seam as `test_paper_cli.py`'s `_run_paper_cli`."""
    calls_log = root / "_stub_calls.json"
    script = f"""
import json, sys
import axial.cli as cli
from axial.llm import StubLLMClient

PLAN = {json.dumps(PLAN)}
DRAFTS = {json.dumps(DRAFTS)}
SHAPE = {json.dumps(SHAPE_RESPONSE)}


class StubClient(StubLLMClient):
    model_by_pass = {{
        "paper_plan": "stub/plan",
        "paper_draft": "stub/draft",
        "paper_shape": "stub/shape",
    }}

    def __init__(self):
        super().__init__()
        self._drafts = list(DRAFTS)
        self.calls = []

    def complete(self, prompt, pass_name=None, **_):
        self.calls.append({{"pass_name": pass_name, "prompt": prompt}})
        if pass_name == "paper_plan":
            return json.dumps(PLAN)
        if pass_name == "paper_draft":
            return json.dumps(self._drafts.pop(0))
        if pass_name == "paper_shape":
            return json.dumps(SHAPE)
        raise AssertionError("unexpected pass_name: " + str(pass_name))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)


client = StubClient()
cli.get_client = lambda: client
exit_code = cli.main(["paper", "draft", {str(brief_path)!r}])
with open({str(calls_log)!r}, "w", encoding="utf-8") as f:
    json.dump(client.calls, f)
sys.exit(exit_code)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root, capture_output=True, text=True
    )
    calls = json.loads(calls_log.read_text(encoding="utf-8")) if calls_log.exists() else []
    return result.returncode, result.stdout, result.stderr, calls


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _write_analyses(tmp_path)
    _write_lenses(tmp_path)
    return tmp_path


def test_only_the_counter_position_section_prompt_carries_the_instruction(root):
    brief_path = _write_paper_brief(root)

    exit_code, out, err, calls = _run_paper_draft(root, brief_path)

    assert exit_code == 0, f"stdout: {out!r}\nstderr: {err!r}"
    draft_calls = [call for call in calls if call["pass_name"] == "paper_draft"]
    assert len(draft_calls) == 5, "one drafting call per planned section"

    # Sections are drafted in plan order (s1..s5), so the fourth call is the
    # counter-position section's own prompt.
    counter_position_prompt = draft_calls[3]["prompt"]
    assert INSTRUCTION_PHRASE in counter_position_prompt
    assert 'its role in the argument is "counter-position"' in counter_position_prompt

    other_prompts = [draft_calls[i]["prompt"] for i in (0, 1, 2, 4)]
    for prompt in other_prompts:
        assert INSTRUCTION_PHRASE not in prompt


def test_the_persisted_record_still_validates_unchanged_otherwise(root):
    """The prompt change is additive text only -- the record's shape, claim
    count and shape band are exactly what they would be without it."""
    brief_path = _write_paper_brief(root)

    exit_code, out, err, calls = _run_paper_draft(root, brief_path)

    assert exit_code == 0, f"stdout: {out!r}\nstderr: {err!r}"
    json_files = list((root / "data" / "papers").glob("*.json"))
    assert len(json_files) == 1
    record = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert record["corpus_pin"] == PIN
    assert record["shape"]["band"] == "strong"
    assert len(record["claims"]) == 5
    section_roles = {section["role"] for section in record["plan"]["sections"]}
    assert "counter-position" in section_roles
