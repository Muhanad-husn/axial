"""Inner unit tests for issue #493: `total`/`detail` (`axial.retrieve.
dispatcher.ToolResult`) are now persisted onto the §7.6 trajectory entry
itself, not only rendered into the next turn's prompt feedback
(specs/PHASE-B.md §7.6). Before this, a persisted run record could not say
what `member_count` a resolved name carried, which tier `find_names` used,
or what a `name_neighbors` call's own ranking looked like, without replaying
the prompt text a real provider's model saw at run time.

The outer, scripted-scenario acceptance contract for the tool loop itself
lives in `tests/analysis/test_retrieval_loop_name_tools.py`; these two tests
pin the narrower seam this issue actually changed -- the trajectory dict
`run_retrieval_loop` appends -- directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from axial.llm import STUB_TOOL_CALLS_ENV_VAR, StubLLMClient
from axial.retrieve.loop import run_retrieval_loop

TILLY = "Charles Tilly"


def _write_name_layer(names_dir: Path) -> None:
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "index.json").write_text(
        json.dumps({"version": 1, "generated_at": "2026-07-30T00:00:00Z", "names": [TILLY]}),
        encoding="utf-8",
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": "2026-07-30T00:00:00Z",
                "nodes": [{"canonical": TILLY, "kind": "person", "aliases": ["Tilly"]}],
            }
        ),
        encoding="utf-8",
    )


def _write_tilly_page(vault_dir: Path, member_ids: list[str]) -> None:
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    member_lines = "\n".join(
        f"- [[{chunk_id}]] — Charles Tilly (1978): Claim of {chunk_id}." for chunk_id in member_ids
    )
    page_body = f"# {TILLY}\n\n**Aliases:** Tilly\n\n**Member notes:**\n{member_lines}\n"
    (names_dir / "charles-tilly.md").write_text(
        "---\n"
        + yaml.safe_dump(
            {
                "name": TILLY,
                "kind": "person",
                "aliases": ["Tilly"],
                "member_count": len(member_ids),
            },
            sort_keys=False,
        )
        + "---\n"
        + page_body,
        encoding="utf-8",
    )


def _set_scripted_tool_calls(monkeypatch, calls: list[dict[str, Any] | None]) -> None:
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps(calls))


def test_find_names_hit_carries_member_count_and_tier_on_the_persisted_entry(
    tmp_path: Path, monkeypatch
):
    """A stubbed `find_names` call that resolves through the alias tier: the
    persisted trajectory entry's `detail` -- not only the next turn's prompt
    -- must state the hit's `member_count` and `tier`, so a completed run's
    record answers "how many notes back this name, and how confident was the
    resolution" offline."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_name_layer(names_dir)
    _write_tilly_page(vault_dir, ["tillyfix-1978_1_intro_001", "tillyfix-1978_2_intro_001"])

    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "find_names", "args": {"query": "Tilly"}}, None],
    )
    trajectory = run_retrieval_loop(
        StubLLMClient(), "seed prompt", vault_dir=vault_dir, names_dir=names_dir, step_budget=10
    )

    assert len(trajectory) == 1
    entry = trajectory[0]
    assert entry["result_ids"] == [TILLY]
    assert entry["total"] is None, "find_names carries no pre-cap total"
    assert entry["detail"] is not None
    assert "member_count=2" in entry["detail"]
    assert "tier=alias" in entry["detail"]


def test_name_neighbors_distribution_on_the_persisted_entry_matches_the_neighbours_given(
    tmp_path: Path, monkeypatch
):
    """A stubbed `name_neighbors` call over three prose notes with a known
    co-occurrence shape (one neighbour shared by two notes, one shared by
    one) -- the persisted entry's `detail` must state exactly that
    distribution, not just the next turn's prompt."""
    vault_dir = tmp_path / "vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    def _note(chunk_id: str, names: list[str]) -> None:
        frontmatter = {
            "chunk_id": chunk_id,
            "section": "Synthetic Section",
            "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
            "source_meta": {"author": "Someone", "title": "T", "date": 2000},
            "answers": {
                "claim": "A claim.",
                "position_of": "the author",
                "names": [{"name": name} for name in names],
            },
        }
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")

    _note("src-1_1_a_001", ["Anchor", "Common"])
    _note("src-1_2_a_001", ["Anchor", "Common"])
    _note("src-2_1_a_001", ["Anchor", "Rare"])

    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "name_neighbors", "args": {"canonical": "Anchor"}}, None],
    )
    trajectory = run_retrieval_loop(
        StubLLMClient(), "seed prompt", vault_dir=vault_dir, step_budget=10
    )

    assert len(trajectory) == 1
    entry = trajectory[0]
    assert set(entry["result_ids"]) == {"Common", "Rare"}
    assert entry["total"] is None
    assert entry["detail"] == (
        "2 neighbors, shared_note_count min=1 median=1.5 max=2 (1 of 2 at the floor of 1)"
    )
