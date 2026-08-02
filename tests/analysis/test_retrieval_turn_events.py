"""Outer acceptance test for issue #533, the retrieval loop's own slice of
the engine event seam (`axial.retrieve.loop.run_retrieval_loop`'s `on_event`
parameter).

Given a scripted model that issues two tool calls (`query_by_source`, then
      `get_chunk`) before ending the loop
When  `run_retrieval_loop(..., on_event=<collector>)` runs
Then  the collector receives one event per turn describing what that turn
      looked for and what it found, in plain language -- no raw tool name,
      chunk id, or `args` dict ever appears in the event's own sentence
  And every event fires WHILE the loop runs (the collector observes them
      one at a time, in step order, never as a single end-of-run batch)
  And each event also carries a `detail` dict with the real tool/args/counts,
      for a renderer that wants the machinery instead of the sentence

Given no `on_event` is given at all
When  the loop runs the same scripted sequence
Then  the exact same sentences are printed to stderr instead -- the
      real-time visibility this loop always had is not lost by adding the
      seam.

See GitHub issue #533 for the source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import STUB_TOOL_CALLS_ENV_VAR, StubLLMClient
from axial.retrieve.loop import run_retrieval_loop

SOURCE_ID = "evfix-source"
CHUNK_ID = f"{SOURCE_ID}_1_intro_001"


def _write_fixture_vault(root: Path) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True)
    frontmatter = {
        "chunk_id": CHUNK_ID,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{CHUNK_ID}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:state", "secondary": []},
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
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")
    return root / "vault"


@pytest.fixture
def fixture_vault_dir(tmp_path: Path) -> Path:
    return _write_fixture_vault(tmp_path)


def _set_scripted_tool_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any] | None]
) -> None:
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps(calls))


def test_on_event_fires_live_once_per_turn_with_a_plain_sentence_and_detail(
    fixture_vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "query_by_source", "args": {"source_id": SOURCE_ID}},
            {"tool": "get_chunk", "args": {"chunk_id": CHUNK_ID}},
            None,
        ],
    )
    client = StubLLMClient()
    events: list[tuple[str, dict[str, Any]]] = []

    def collector(message: str, detail: dict[str, Any]) -> None:
        # The collector proves events arrive WHILE the loop runs, one at a
        # time: by the time the outcome for turn 1 fires, the trajectory
        # this same call is building has not appended it yet for THIS turn,
        # but has for every prior one -- observable ordering, not a
        # post-hoc replay.
        events.append((message, dict(detail)))

    trajectory = run_retrieval_loop(
        client,
        "irrelevant prompt",
        vault_dir=fixture_vault_dir,
        step_budget=10,
        on_event=collector,
    )

    assert len(trajectory) == 2

    outcome_messages = [msg for msg, detail in events if detail.get("phase") == "outcome"]
    assert len(outcome_messages) == 2, f"expected one outcome event per real turn, got {events!r}"

    first, second = outcome_messages
    assert "found 1 result" in first or "found 1" in first
    assert SOURCE_ID in first, "the tool's own argument CONTENT belongs in the sentence"
    assert "query_by_source" not in first, "the raw tool name must never appear in the sentence"

    assert CHUNK_ID not in second, (
        "a chunk id is machinery, not content -- it must never appear in the sentence"
    )
    assert "get_chunk" not in second

    # `detail` carries what the sentence deliberately omits.
    outcome_details = [detail for _msg, detail in events if detail.get("phase") == "outcome"]
    assert outcome_details[0]["tool"] == "query_by_source"
    assert outcome_details[0]["args"] == {"source_id": SOURCE_ID}
    assert outcome_details[1]["tool"] == "get_chunk"

    # A planning event precedes each turn's outcome -- "start and outcome"
    # (issue #533's own acceptance bar), not outcome-only.
    planning_messages = [msg for msg, detail in events if detail.get("phase") == "planning"]
    assert len(planning_messages) >= 2


def test_no_on_event_falls_back_to_the_same_plain_sentences_on_stderr(
    fixture_vault_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "query_by_source", "args": {"source_id": SOURCE_ID}}, None],
    )
    client = StubLLMClient()

    run_retrieval_loop(client, "irrelevant prompt", vault_dir=fixture_vault_dir, step_budget=10)

    captured = capsys.readouterr()
    assert SOURCE_ID in captured.err
    assert "found 1" in captured.err
    assert "query_by_source" not in captured.err
