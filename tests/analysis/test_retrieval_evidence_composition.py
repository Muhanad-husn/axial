"""Acceptance test for issue #542 fix 2: the retrieval loop's tool feedback
states its own evidence set's source composition (specs/PHASE-B.md §7.6).

Replaying seven persisted brief runs step by step (`data/runs/smoke-v2/`,
`data/runs/smoke-v3-stage*/`, zero model calls): the assembled evidence prefix
synthesis actually reads changes **exactly when a new SOURCE arrives** --
identical step for step in 6 of the 7 runs. Reaching another book is the
loop's productive act; reaching another note in a book it already has is not.
The loop could see none of that. It spent a model round trip per turn adding
ids to a set it had no view of at all.

So after every call the loop states, mechanically computed off the trajectory
it already holds: how many notes the evidence set holds, how many distinct
sources they span, and which sources. Appended to the tool feedback exactly
the way `ToolResult.total` and `ToolResult.detail` already ride beside it --
one channel, not a second one.

**The trap this test exists to hold shut (#505): a cap the model can SEE gets
widened on purpose.** The feedback reports COMPOSITION -- what the set holds
-- and never a budget, a limit, a maximum, a quota or how much room is left.
`synthesis.evidence_char_budget` and the prefix boundary it produces are
disclosed in no form.

Seam decisions
--------------
Library calls, not a CLI subprocess -- the same seam
`tests/analysis/test_retrieval_planning_requery.py` established:
`axial.llm.RecordLLMClient` observes the assembled prompt while
`AXIAL_STUB_TOOL_CALLS` scripts the model's tool calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import STUB_TOOL_CALLS_ENV_VAR, RecordLLMClient
from axial.retrieve.loop import (
    chunk_feedback_metadata,
    evidence_set_composition,
    run_retrieval_loop,
)

SOURCE_A = "compfix-alpha"
SOURCE_B = "compfix-beta"

A_CHUNK_IDS = [f"{SOURCE_A}_1_intro_{index:03d}" for index in range(1, 4)]
B_CHUNK_IDS = [f"{SOURCE_B}_1_intro_{index:03d}" for index in range(1, 3)]


def _write_note(prose_dir: Path, chunk_id: str) -> None:
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {"author": "A. Synthetic Author", "title": "A Fixture", "date": 2021},
        "answers": {"claim": f"Claim of {chunk_id}."},
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def fixture_vault_dir(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "composition-vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for chunk_id in A_CHUNK_IDS + B_CHUNK_IDS:
        _write_note(prose_dir, chunk_id)
    return vault_dir


def _entry(tool: str, result_ids: list[str]) -> dict[str, Any]:
    return {
        "step": 1,
        "tool": tool,
        "args": {},
        "result_ids": result_ids,
        "result_count": len(result_ids),
    }


def test_composition_states_note_count_source_count_and_the_sources():
    composition = evidence_set_composition(
        [_entry("get_chunk", [A_CHUNK_IDS[0], A_CHUNK_IDS[1], B_CHUNK_IDS[0]])]
    )

    assert "3 notes across 2 sources" in composition
    assert SOURCE_A in composition
    assert SOURCE_B in composition


def test_composition_counts_the_assembled_set_not_the_last_result():
    """It describes the set the run has built, so an id already seen does not
    count twice and a name-valued result contributes nothing to it."""
    trajectory = [
        _entry("find_names", ["Charles Tilly"]),
        _entry("get_chunk", [A_CHUNK_IDS[0], A_CHUNK_IDS[1]]),
        _entry("get_chunk", [A_CHUNK_IDS[1]]),
    ]

    composition = evidence_set_composition(trajectory)

    assert "2 notes across 1 sources" in composition
    assert "Charles Tilly" not in composition


def test_composition_reports_an_empty_set_before_any_chunk_valued_call():
    assert "empty" in evidence_set_composition([_entry("find_names", ["Charles Tilly"])])
    assert "empty" in evidence_set_composition([])


@pytest.mark.parametrize(
    "forbidden",
    ["budget", "limit", "cap", "maximum", "remaining", "room", "char", "quota", "allowance"],
)
def test_composition_never_names_a_budget_a_cap_or_a_remaining_allowance(
    forbidden: str, fixture_vault_dir: Path
):
    """The whole risk of this change (#505): a cap the model can SEE gets
    widened on purpose. Composition is what the set HOLDS; nothing here names
    a budget, a limit, a maximum or how much room is left, and
    `synthesis.evidence_char_budget` and the prefix boundary are disclosed in
    no form.

    Extended by issue #545's own per-id metadata feedback
    (`chunk_feedback_metadata`): it rides the identical channel, right beside
    `evidence_set_composition`, so the same trap applies to it too -- it
    states what a note HOLDS, never how many more would fit."""
    stated = (
        evidence_set_composition([_entry("get_chunk", [A_CHUNK_IDS[0], B_CHUNK_IDS[0]])]),
        evidence_set_composition([]),
        chunk_feedback_metadata([A_CHUNK_IDS[0], B_CHUNK_IDS[0]], fixture_vault_dir) or "",
        chunk_feedback_metadata([], fixture_vault_dir) or "",
    )

    for composition in stated:
        assert forbidden not in composition.lower(), composition


def test_the_next_turns_prompt_carries_the_evidence_sets_composition(
    fixture_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """End to end through the loop: after a call that reaches two sources, the
    prompt the model sees on its next turn states what its evidence set now
    holds -- the signal the loop was blind to -- and it keeps up to date as
    the set grows."""
    monkeypatch.setenv(
        STUB_TOOL_CALLS_ENV_VAR,
        json.dumps(
            [
                {"tool": "get_chunk", "args": {"chunk_id": [A_CHUNK_IDS[0], B_CHUNK_IDS[0]]}},
                {"tool": "get_chunk", "args": {"chunk_id": A_CHUNK_IDS[1]}},
                None,
            ]
        ),
    )
    record_path = tmp_path / "record.jsonl"

    run_retrieval_loop(
        RecordLLMClient(record_path),
        "PROMPT",
        vault_dir=fixture_vault_dir,
        step_budget=5,
        thin_result_floor=3,
    )

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) >= 3

    assert "evidence set" not in prompts[0], "nothing has been retrieved on the first turn"

    assert "2 notes across 2 sources" in prompts[1]
    assert SOURCE_A in prompts[1]
    assert SOURCE_B in prompts[1]

    assert "3 notes across 2 sources" in prompts[2]
