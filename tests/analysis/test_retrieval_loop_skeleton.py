"""Outer acceptance test for issue #253, slice 01 of the retrieval-loop
subproject (Phase B, sub:analysis-v0): the walking skeleton -- a tool-use
seam, a validating dispatcher, a bounded step budget, and the §7.6
trajectory log.

Locked behavioral contract -- do not edit once committed red/green without a
one-line justification in the PR body.

Given a fixture vault with known chunk ids
  And a scripted model that issues exactly three tool calls in order:
      query_by_tag{field: "state-formation"}, then
      query_by_polity{polity: "Syria"}, then
      get_chunk{chunk_id: <a known id>}
When  the retrieval loop runs against that vault
Then  the trajectory log has exactly 3 entries in that order
  And entry 1 is {step: 1, tool: "query_by_tag", args: {field: "state-formation"},
      result_ids: [<the ids that query returns>], result_count: <their count>}
  And every entry's `result_count` equals the length of its `result_ids`
  And `step` increments 1, 2, 3 with no gaps

Given a scripted model that requests tool "query_by_vibes" with args {q: "x"}
When  the retrieval loop runs
Then  the vault query API is never called for that step
  And the model receives a validation-error result naming the unknown tool
  And the loop continues to the next step rather than crashing

Given a scripted model that requests query_by_polity with a missing required arg
When  the retrieval loop runs
Then  the dispatcher rejects it before calling, with a named arg error

Given a step budget of 5 and a scripted model that issues an unbounded stream
      of valid query_by_tag calls
When  the retrieval loop runs
Then  the loop halts after exactly 5 tool calls
  And the trajectory log has exactly 5 entries
  And the halt is a clean bounded return, not an exception

See specs/PHASE-B.md §7.5 (the vault query API, [FIRM]) and §7.6 (the
retrieval trajectory log, [FIRM]) for the source of truth, and
plans/retrieval-loop/01-tool-loop-skeleton.md for this slice's own
acceptance criterion (identical Gherkin).

Seam decisions
--------------
Library calls, not a CLI subprocess (no `axial retrieve`/`axial analyze`
subcommand is in scope -- this slice's own boundary is
`src/axial/retrieve/` driven with an injected scripted model client, per
the plan). `axial.llm.StubLLMClient` is constructed directly in-process and
driven through the new `complete_with_tools` tool-use seam via
`AXIAL_STUB_TOOL_CALLS` (a JSON array of `{"tool", "args"}` entries, or
`null` for "no tool call, end the loop" -- see that env var's own comment
in `src/axial/llm.py`), consumed by a per-INSTANCE counter (not a
module-global one, unlike the older `.complete()` stub seams) so tests in
this module never leak state into each other. The fixture vault is written
fresh per test under `tmp_path` (mirroring
`tests/analysis/test_brief_interrogation.py`'s `_write_fixture_vault`),
never the real, shared `data/vault/`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import STUB_TOOL_CALLS_ENV_VAR, StubLLMClient
from axial.query import reader
from axial.retrieve.loop import run_retrieval_loop

STATE_FORMATION_CHUNK_ID = "rlfix_001_intro"
SYRIA_CHUNK_ID = "rlfix_002_syria"


def _chunk_frontmatter(
    *,
    chunk_id: str,
    field_primary: str,
    polities_touched: list[str],
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
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": polities_touched[0]},
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


def _write_fixture_vault(root: Path) -> Path:
    """Two synthetic prose notes: one carries `field.primary ==
    "state-formation"` (chunk A), the other's `polities_touched` names
    "Syria" (chunk B) -- exactly the two facts the outer scenario's first
    three scripted calls each need one real, distinct answer for."""
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    chunk_a = _chunk_frontmatter(
        chunk_id=STATE_FORMATION_CHUNK_ID,
        field_primary="state-formation",
        polities_touched=["Freedonia"],
    )
    chunk_b = _chunk_frontmatter(
        chunk_id=SYRIA_CHUNK_ID,
        field_primary="ideology",
        polities_touched=["Syria"],
    )
    for frontmatter in (chunk_a, chunk_b):
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")

    return prose_dir.parent


@pytest.fixture
def fixture_vault_dir(tmp_path: Path) -> Path:
    return _write_fixture_vault(tmp_path)


def _set_scripted_tool_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any] | None]
) -> None:
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps(calls))


def test_scripted_three_call_sequence_produces_exact_ordered_trajectory(
    fixture_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 1: a scripted query_by_tag -> query_by_polity -> get_chunk
    sequence produces exactly 3 trajectory entries, in order, entry 1 exact,
    every result_count == len(result_ids), step 1..3 with no gaps."""
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "query_by_tag", "args": {"field": "state-formation"}},
            {"tool": "query_by_polity", "args": {"polity": "Syria"}},
            {"tool": "get_chunk", "args": {"chunk_id": STATE_FORMATION_CHUNK_ID}},
            None,
        ],
    )
    client = StubLLMClient()

    trajectory = run_retrieval_loop(
        client, "irrelevant prompt", vault_dir=fixture_vault_dir, step_budget=10
    )

    assert len(trajectory) == 3, f"expected exactly 3 trajectory entries, got {trajectory!r}"
    assert [entry["step"] for entry in trajectory] == [1, 2, 3], (
        f"expected step to increment 1, 2, 3 with no gaps, got {trajectory!r}"
    )
    assert [entry["tool"] for entry in trajectory] == [
        "query_by_tag",
        "query_by_polity",
        "get_chunk",
    ]

    entry_1 = trajectory[0]
    assert entry_1["tool"] == "query_by_tag"
    assert entry_1["args"] == {"field": "state-formation"}
    assert entry_1["result_ids"] == [STATE_FORMATION_CHUNK_ID]
    assert entry_1["result_count"] == 1

    for entry in trajectory:
        assert entry["result_count"] == len(entry["result_ids"]), (
            f"result_count must equal len(result_ids), got {entry!r}"
        )

    entry_2 = trajectory[1]
    assert entry_2["result_ids"] == [SYRIA_CHUNK_ID]
    assert entry_2["result_count"] == 1

    entry_3 = trajectory[2]
    assert entry_3["result_ids"] == [STATE_FORMATION_CHUNK_ID]
    assert entry_3["result_count"] == 1


def test_unknown_tool_never_reaches_query_api_and_loop_continues(
    fixture_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 2: an unknown tool name is rejected by the dispatcher before
    ever calling a real reader.py function, and the loop continues to the
    next scripted step instead of crashing."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the vault query API must never be called for an unknown-tool step")

    for name in (
        "query_by_tag",
        "query_by_polity",
        "query_by_source",
        "get_envelope",
        "get_chunk",
        "get_artifact",
        "follow_backlinks",
        "coverage_count",
    ):
        monkeypatch.setattr(reader, name, _explode)

    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "query_by_vibes", "args": {"q": "x"}}, None],
    )
    client = StubLLMClient()

    trajectory = run_retrieval_loop(
        client, "irrelevant prompt", vault_dir=fixture_vault_dir, step_budget=10
    )

    assert len(trajectory) == 1, f"expected exactly 1 trajectory entry, got {trajectory!r}"
    entry = trajectory[0]
    assert entry["step"] == 1
    assert entry["tool"] == "query_by_vibes"
    assert entry["result_ids"] == []
    assert entry["result_count"] == 0


def test_unknown_tool_error_names_the_unknown_tool(
    fixture_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 2's second clause, at the dispatcher level directly: the
    structured error result the model receives names the unknown tool."""
    from axial.retrieve.dispatcher import dispatch

    result = dispatch("query_by_vibes", {"q": "x"}, vault_dir=fixture_vault_dir)

    assert result.ids == []
    assert result.count == 0
    assert result.error is not None
    assert "query_by_vibes" in result.error


def test_missing_required_arg_is_rejected_before_calling(
    fixture_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 3: query_by_polity with a missing required `polity` arg is
    rejected by the dispatcher before it ever reaches reader.query_by_polity,
    with a named arg error, and the loop continues rather than crashing."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("query_by_polity must never be called with a missing required arg")

    monkeypatch.setattr(reader, "query_by_polity", _explode)

    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "query_by_polity", "args": {}}, None],
    )
    client = StubLLMClient()

    trajectory = run_retrieval_loop(
        client, "irrelevant prompt", vault_dir=fixture_vault_dir, step_budget=10
    )

    assert len(trajectory) == 1
    entry = trajectory[0]
    assert entry["step"] == 1
    assert entry["tool"] == "query_by_polity"
    assert entry["args"] == {}
    assert entry["result_ids"] == []
    assert entry["result_count"] == 0

    from axial.retrieve.dispatcher import dispatch

    result = dispatch("query_by_polity", {}, vault_dir=fixture_vault_dir)
    assert result.error is not None
    assert "polity" in result.error


def test_step_budget_halts_an_unbounded_valid_call_stream_cleanly(
    fixture_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 4: a step budget of 5 halts an unbounded stream of valid
    query_by_tag calls at exactly 5 trajectory entries, with a clean
    bounded return -- no exception."""
    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "query_by_tag", "args": {"field": "state-formation"}}],
    )
    client = StubLLMClient()

    trajectory = run_retrieval_loop(
        client, "irrelevant prompt", vault_dir=fixture_vault_dir, step_budget=5
    )

    assert len(trajectory) == 5, (
        f"expected the loop to halt at exactly 5 entries, got {trajectory!r}"
    )
    assert [entry["step"] for entry in trajectory] == [1, 2, 3, 4, 5]
    for entry in trajectory:
        assert entry["tool"] == "query_by_tag"
        assert entry["result_ids"] == [STATE_FORMATION_CHUNK_ID]
        assert entry["result_count"] == 1
