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


def test_get_chunk_skips_an_unresolved_id_and_returns_the_rest(fixture_vault_dir: Path):
    """One bad id must not zero the whole batch -- #630's shape one layer
    down (issue #629). A real run typo'd a single hyphen out of one
    ~100-character id, asked for 10, and got 0 back; here the two good ids
    still come back and the bad one is named in `detail`. The batch here is
    NOT truncated by `limit` (3 ids, default limit 10), so `total` stays
    `None` -- see the dedicated `total`-narrowing tests below for why."""
    bogus_id = f"{SOURCE_A}_1_intro_does-not-exist_999"
    wanted = [A_CHUNK_IDS[0], bogus_id, A_CHUNK_IDS[1]]

    result = dispatch("get_chunk", {"chunk_id": wanted}, vault_dir=fixture_vault_dir)

    assert result.error is None
    assert result.ids == [A_CHUNK_IDS[0], A_CHUNK_IDS[1]]
    assert result.count == 2
    assert result.total is None, "the batch was not truncated by limit, so total is unset"
    assert result.detail is not None
    assert bogus_id in result.detail


def test_get_chunk_all_ids_unresolved_is_an_empty_result_not_an_error(fixture_vault_dir: Path):
    result = dispatch("get_chunk", {"chunk_id": ["nope-1", "nope-2"]}, vault_dir=fixture_vault_dir)

    assert result.error is None
    assert result.ids == []
    assert result.count == 0
    assert result.total is None, "not truncated by limit either, even though nothing resolved"
    assert result.detail is not None
    assert "nope-1" in result.detail
    assert "nope-2" in result.detail


def test_get_chunk_total_still_reports_a_genuine_truncation_alongside_an_unresolved_id(
    fixture_vault_dir: Path,
):
    """The narrowed meaning of `total` (issue #629's own follow-up, caught in
    review before merge): the first cut of this fix kept `total =
    len(chunk_ids)` unconditionally, which re-created the bug through a new
    door -- an unresolved id alone made a batch read as CAPPED even when
    nothing sat past `limit`. `total` must still fire correctly, though, when
    a real truncation and an unresolved id occur in the SAME call: one bad id
    within the attempted window, plus real ids genuinely left unasked past
    `limit`. `get_chunk` now means exactly what `get_name`/`who_cites`/
    `who_argues_against`/`where_names_meet` already mean by `total`: set only
    on a genuine truncation, whatever else happened in that same call."""
    bogus_id = f"{SOURCE_A}_1_intro_does-not-exist_999"
    wanted = [bogus_id, *A_CHUNK_IDS]
    assert len(wanted) > DEFAULT_LIMIT

    result = dispatch("get_chunk", {"chunk_id": wanted}, vault_dir=fixture_vault_dir)

    assert result.error is None
    assert result.count == DEFAULT_LIMIT - 1, "one of the first `limit` ids was the bad one"
    assert result.total == len(wanted), (
        "the tail past `limit` is genuinely unasked -- CAPPED is right"
    )
    assert bogus_id in (result.detail or "")


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


def test_untruncated_batch_with_an_unresolved_id_gets_no_capped_note_from_the_loop(
    fixture_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The regression this branch would otherwise ship (issue #629's own
    follow-up, caught in review before merge): a batch NOT truncated by
    `limit` must not tell the model a larger `limit` would return more just
    because one of its own ids failed to resolve. That is the exact
    misleading nudge measured on a live run that cycled `where_names_meet`'s
    `limit` 20/15/10/15/20 on an already-exhausted call -- reachable through
    `get_chunk` too if `total` stayed unconditional on "fewer came back than
    asked for" rather than on genuine truncation."""
    bogus_id = f"{SOURCE_A}_1_intro_does-not-exist_999"
    wanted = [A_CHUNK_IDS[0], bogus_id]
    assert len(wanted) < DEFAULT_LIMIT, "the batch itself must not be limit-truncated"
    _set_scripted_tool_calls(
        monkeypatch, [{"tool": "get_chunk", "args": {"chunk_id": wanted}}, None]
    )
    record_path = tmp_path / "unresolved-untruncated.jsonl"

    run_retrieval_loop(
        RecordLLMClient(record_path),
        "PROMPT",
        vault_dir=fixture_vault_dir,
        step_budget=5,
        thin_result_floor=1,
    )

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    feedback = prompts[1]
    assert "re-ask with a larger limit for more" not in feedback
    # Not EXHAUSTED either (see `_get_chunk`'s own docstring): "exhausted"
    # describes a query whose corpus-side size the model could not see in
    # advance, and a get_chunk batch is a list the model wrote itself --
    # `total` narrowed to "truncated only" makes this the natural, not a
    # special-cased, consequence.
    assert "EXHAUSTED" not in feedback
    assert bogus_id in feedback
