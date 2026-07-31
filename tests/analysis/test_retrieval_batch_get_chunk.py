"""Acceptance test for issue #542 fix 1: `get_chunk` reads a batch of notes in
one call (specs/PHASE-B.md §7.5/§7.6).

Measured on seven persisted smoke records (`data/runs/smoke-v2/`,
`data/runs/smoke-v3-stage*/`), replayed with zero model calls: `get_chunk` was
called 44 times and contributed **zero** new ids to the assembled evidence set
-- every id it read had already been surfaced by the `get_name` that listed it
-- while costing a full model round trip each. 24 of those 44 calls sat in a
run of consecutive `get_chunk` calls that a batching tool collapses into one
turn.

What this pins:

- One call, several ids -- and the bare-string single-id shape still works,
  because the model will emit both forms and a hard error on the old one would
  burn a full model turn.
- A batched call is ONE §7.6 trajectory entry carrying every returned id in
  `result_ids`. That is what keeps `assemble_evidence_ids`,
  `evidence_tool_calls` and `turns_without_new_evidence` meaning exactly what
  they mean today -- all three are computed per ENTRY.
- The batch is bounded by the same `limit`/`DEFAULT_LIMIT` mechanism every
  other bounded tool already uses (issue #505). An unbounded list lets one
  call pull the whole index back into the prompt, which is the exact failure
  #505 fixed for the name tools.
- Batching does not change what gets assembled. This is the real regression
  risk: batching changes trajectory shape, and `assemble_evidence_ids` reads
  trajectory shape.

Seam decisions
--------------
Library calls, not a CLI subprocess -- the same seam
`tests/analysis/test_retrieval_planning_requery.py` established:
`AXIAL_STUB_TOOL_CALLS` scripts the model's tool calls through
`axial.llm.RecordLLMClient`, so the model is deterministic while the loop runs
for real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import STUB_TOOL_CALLS_ENV_VAR, RecordLLMClient
from axial.query.names import DEFAULT_LIMIT
from axial.retrieve.dispatcher import dispatch
from axial.retrieve.loop import assemble_evidence_ids, run_retrieval_loop
from axial.retrieve.tools import TOOL_REGISTRY, tool_specs_for_provider

SOURCE_A = "batchfix-alpha"
SOURCE_B = "batchfix-beta"

A_CHUNK_IDS = [f"{SOURCE_A}_1_intro_{index:03d}" for index in range(1, 13)]
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
    """Two synthetic sources: twelve notes in one (more than `DEFAULT_LIMIT`,
    so the default batch bound is observable) and two in the other."""
    vault_dir = tmp_path / "batch-vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for chunk_id in A_CHUNK_IDS + B_CHUNK_IDS:
        _write_note(prose_dir, chunk_id)
    return vault_dir


def _set_scripted_tool_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any] | None]
) -> None:
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps(calls))


def _record_client(tmp_path: Path, name: str) -> RecordLLMClient:
    return RecordLLMClient(tmp_path / f"{name}.jsonl")


def test_get_chunk_returns_every_id_of_a_batch_in_one_call(fixture_vault_dir: Path):
    """The whole point: three notes, one dispatch, three ids back."""
    wanted = A_CHUNK_IDS[:3]
    result = dispatch("get_chunk", {"chunk_id": wanted}, vault_dir=fixture_vault_dir)

    assert result.error is None
    assert result.ids == wanted
    assert result.count == 3


def test_get_chunk_still_accepts_a_bare_string_id(fixture_vault_dir: Path):
    """The old single-id shape keeps working -- the model will emit both, and
    a hard error on the old one would burn a full model turn."""
    result = dispatch("get_chunk", {"chunk_id": A_CHUNK_IDS[0]}, vault_dir=fixture_vault_dir)

    assert result.error is None
    assert result.ids == [A_CHUNK_IDS[0]]
    assert result.count == 1


def test_get_chunk_batch_is_bounded_by_the_tool_sets_own_default_limit(fixture_vault_dir: Path):
    """An unbounded list lets one call pull the whole index back into the
    prompt -- the exact failure #505 fixed for the name tools. `get_chunk`
    reuses that same bound, it does not invent a second one, and the true
    pre-cap count travels with the truncated result so the cap is never
    silent."""
    assert len(A_CHUNK_IDS) > DEFAULT_LIMIT
    result = dispatch("get_chunk", {"chunk_id": A_CHUNK_IDS}, vault_dir=fixture_vault_dir)

    assert result.error is None
    assert result.count == DEFAULT_LIMIT
    assert result.ids == A_CHUNK_IDS[:DEFAULT_LIMIT]
    assert result.total == len(A_CHUNK_IDS)


def test_get_chunk_honours_an_explicit_limit(fixture_vault_dir: Path):
    result = dispatch(
        "get_chunk", {"chunk_id": A_CHUNK_IDS[:5], "limit": 2}, vault_dir=fixture_vault_dir
    )

    assert result.error is None
    assert result.ids == A_CHUNK_IDS[:2]
    assert result.count == 2
    assert result.total == 5


def test_get_chunk_rejects_a_list_holding_a_non_string_without_raising(fixture_vault_dir: Path):
    result = dispatch("get_chunk", {"chunk_id": [A_CHUNK_IDS[0], 7]}, vault_dir=fixture_vault_dir)

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "chunk_id" in result.error


def test_provider_schema_advertises_get_chunk_as_a_list_of_strings():
    """What a real provider's model is shown. The dispatcher additionally
    tolerates a bare string (test above), but the shape the model is asked for
    is the batch."""
    by_name = {entry["function"]["name"]: entry for entry in tool_specs_for_provider()}
    properties = by_name["get_chunk"]["function"]["parameters"]["properties"]

    assert properties["chunk_id"] == {"type": "array", "items": {"type": "string"}}
    assert properties["limit"] == {"type": "integer"}
    assert "one id or a list" in TOOL_REGISTRY["get_chunk"].description.lower()


def test_a_batched_call_is_one_trajectory_entry_carrying_every_id(
    fixture_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """§7.6's shape is unchanged: one entry per CALL, not per id, so
    `result_count` stays the honest count of ids that entry returned and every
    figure computed per entry keeps its meaning."""
    wanted = A_CHUNK_IDS[:3]
    _set_scripted_tool_calls(
        monkeypatch, [{"tool": "get_chunk", "args": {"chunk_id": wanted}}, None]
    )

    trajectory = run_retrieval_loop(
        _record_client(tmp_path, "batched"),
        "PROMPT",
        vault_dir=fixture_vault_dir,
        step_budget=5,
        thin_result_floor=3,
    )

    assert len(trajectory) == 1
    assert trajectory[0]["result_ids"] == wanted
    assert trajectory[0]["result_count"] == 3


def test_batching_reads_assembles_exactly_what_reading_them_one_at_a_time_did(
    fixture_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The regression this fix genuinely risks: batching changes trajectory
    SHAPE, and `assemble_evidence_ids` reads trajectory shape (dedupe
    first-seen, then reorder source round-robin). Three one-at-a-time reads
    and one batched read of the same three ids must assemble the same set in
    the same order."""
    wanted = [A_CHUNK_IDS[0], B_CHUNK_IDS[0], A_CHUNK_IDS[1]]

    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "get_chunk", "args": {"chunk_id": chunk_id}} for chunk_id in wanted] + [None],
    )
    one_at_a_time = run_retrieval_loop(
        _record_client(tmp_path, "single"),
        "PROMPT",
        vault_dir=fixture_vault_dir,
        step_budget=5,
        thin_result_floor=3,
    )

    _set_scripted_tool_calls(
        monkeypatch, [{"tool": "get_chunk", "args": {"chunk_id": wanted}}, None]
    )
    batched = run_retrieval_loop(
        _record_client(tmp_path, "batch"),
        "PROMPT",
        vault_dir=fixture_vault_dir,
        step_budget=5,
        thin_result_floor=3,
    )

    assert len(one_at_a_time) == 3
    assert len(batched) == 1
    assert assemble_evidence_ids(batched) == assemble_evidence_ids(one_at_a_time)
