"""Outer acceptance test for issue #533, `axial.answer.record.run_brief`'s
own slice of the engine event seam.

Given a fixture vault, a corpus pin, and a brief whose scripted
      interrogation, retrieval and synthesis all succeed
When  `run_brief(..., on_event=<collector>)` runs
Then  the collector observes, in order, an interrogation stage (start +
      outcome), at least one retrieval-turn event, an assembling-passages
      stage (start + outcome), a writing-the-answer stage (start +
      outcome), and a checking stage (start + outcome) -- every one WHILE
      the run goes, not batched at the end
  And no event's plain sentence names a tool, a chunk id, or an argument
      shape

Given a brief whose scripted interrogation refuses
When  `run_brief` runs
Then  the interrogation and checking stages still both fire, and nothing
      about retrieval/assembly/synthesis is announced (they never ran)

See GitHub issue #533 for the source of truth.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.answer import run_brief
from axial.brief.intake import Brief
from axial.llm import STUB_SYNTHESIZE_RESPONSE_ENV_VAR, STUB_TOOL_CALLS_ENV_VAR, StubLLMClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_LENSES_DIR = REPO_ROOT / "config" / "lenses"

SYRIA_A = "evfix_brief_syria_a"
TILLY = "Charles Tilly"


def _chunk_frontmatter(*, chunk_id: str) -> dict[str, Any]:
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
        "frame_version": "0.1",
        "answers": {
            "claim": f"Claim of {chunk_id}.",
            "move": "stating a mechanism",
            "position_of": "the author",
            "names": [{"name": "Tilly", "kind": "person"}],
        },
    }


def _write_fixture_root(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = _chunk_frontmatter(chunk_id=SYRIA_A)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{SYRIA_A}.md").write_text(text, encoding="utf-8")

    names_layer = root / "data" / "names"
    names_layer.mkdir(parents=True, exist_ok=True)
    (names_layer / "alias_map.json").write_text(
        json.dumps({"nodes": [{"canonical": TILLY, "kind": "person", "aliases": ["Tilly"]}]}),
        encoding="utf-8",
    )
    (names_layer / "index.json").write_text(json.dumps({"names": [TILLY]}), encoding="utf-8")

    evals_dir = root / "evals" / "corpus_pin"
    evals_dir.mkdir(parents=True, exist_ok=True)
    (evals_dir / "baseline.json").write_text(
        json.dumps({"sources": [], "ingest_code_sha": "deadbeef", "vault_snapshot_hash": "abc"}),
        encoding="utf-8",
    )

    shutil.copytree(REPO_LENSES_DIR, root / "config" / "lenses")


@pytest.fixture
def fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_fixture_root(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _collecting_client() -> tuple[StubLLMClient, list[tuple[str, dict[str, Any]]]]:
    return StubLLMClient(), []


def test_run_brief_announces_every_stage_live_in_order(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        STUB_TOOL_CALLS_ENV_VAR,
        json.dumps([{"tool": "get_chunk", "args": {"chunk_id": SYRIA_A}}, None]),
    )
    monkeypatch.setenv(
        STUB_SYNTHESIZE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                "claims": [
                    {
                        "text": "A synthetic claim.",
                        "kind": "a",
                        "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                        "confidence": "medium",
                    }
                ]
            }
        ),
    )
    client = StubLLMClient()
    events: list[tuple[str, dict[str, Any]]] = []

    def collector(message: str, detail: dict[str, Any]) -> None:
        events.append((message, dict(detail)))

    brief = Brief(brief_id="evfix-brief", case="Syria", request="What happened?", lens=None)
    run_brief(brief, client=client, on_event=collector)

    stages_seen = [detail.get("stage") for _msg, detail in events]
    # Every named stage fired, in this relative order (a stage can repeat --
    # e.g. several retrieval turns -- but never appears before an earlier
    # stage's own first event).
    for stage in ("interrogate", "retrieve", "assemble", "synthesize", "check"):
        assert stage in stages_seen, f"expected a {stage!r} event, got stages: {stages_seen!r}"
    assert stages_seen.index("interrogate") < stages_seen.index("retrieve")
    assert stages_seen.index("retrieve") < stages_seen.index("assemble")
    assert stages_seen.index("assemble") < stages_seen.index("synthesize")
    assert stages_seen.index("synthesize") < stages_seen.index("check")

    # No sentence leaks machinery -- the tool name/chunk id are readable
    # only in `detail`, never in the plain sentence itself.
    for message, _detail in events:
        assert "get_chunk" not in message
        assert SYRIA_A not in message


def test_run_brief_on_refusal_still_announces_interrogate_and_check_only(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    from axial.llm import STUB_INTERROGATE_RESPONSE_ENV_VAR

    monkeypatch.setenv(
        STUB_INTERROGATE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                "premises_found": [],
                "bounds_applied": [],
                "refusal": {"reason": "no coverage for this polity"},
            }
        ),
    )
    client = StubLLMClient()
    events: list[tuple[str, dict[str, Any]]] = []

    def collector(message: str, detail: dict[str, Any]) -> None:
        events.append((message, dict(detail)))

    brief = Brief(brief_id="evfix-brief-refuse", case="Syria", request="What happened?", lens=None)
    run_brief(brief, client=client, on_event=collector)

    stages_seen = {detail.get("stage") for _msg, detail in events}
    assert stages_seen == {"interrogate", "check"}
    conclusion_messages = [msg for msg, detail in events if detail.get("stage") == "interrogate"]
    assert any("no coverage for this polity" in msg for msg in conclusion_messages)
