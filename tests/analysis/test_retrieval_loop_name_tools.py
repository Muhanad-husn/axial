"""Outer acceptance test for issue #488, Phase B v1 slice 03: the retrieval
loop rewired onto the name tool set slice 02 (#487) shipped.

Locked behavioral contract -- do not edit once committed red/green without a
one-line justification in the PR body.

Given a fixture name layer holding "Charles Tilly" (alias "Tilly") and a
      fixture vault whose "Charles Tilly" name page has three member notes
      -- two about other polities, one about the case anchor -- plus a
      fourth note (not a page member) that cites "Charles Tilly"
  And a scripted model that resolves the name (find_names), reads who meets
      there (get_name), then follows a citation edge (who_cites)
When  the retrieval loop runs
Then  the trajectory shows name resolution, then member reads, then a
      traversal, in that order
  And every id in the assembled evidence set resolves through get_chunk
  And no canonical name string lands in the assembled evidence set

Given the same fixture and a brief anchored on case "Syria"
When  the same trajectory runs
Then  the assembled evidence set contains the two member notes about OTHER
      polities, uncensored by any case-scope rule -- case anchors retrieval,
      it does not fence it (charter §3, P0-3)

Given a scripted model that requests a retired tool ("query_by_polity") and
      then a real one with an undeclared arg ("find_names" with an extra
      "polity" arg)
When  the retrieval loop runs
Then  neither call ever reaches the name layer or the vault
  And each is rejected as a structured, non-raising ToolResult error
  And the loop continues to the next scripted step rather than crashing

Given a scripted model whose first find_names call resolves to nothing
When  the retrieval loop runs with a thin-result floor of 1
Then  the first trajectory entry is thin (result_count 0)
  And the second entry is a DIFFERENT find_names call, not the loop giving up
  And the recorded prompt for step 2 carries the step-1 result_count, so the
      re-query happened on the thin signal, not by luck

See specs/PHASE-B.md §4 (the agentic loop, case-as-anchor P0-3), §7.5 (the
name-layer tools, [FIRM], and D4's Gather-hint rule) and §7.6 (the
trajectory log, [FIRM], unchanged) for the source of truth, and
plans/phase-b-v1/README.md slice 03.

Seam decisions
--------------
Library calls, not a CLI subprocess -- the same seam every other retrieval-
loop acceptance test in this directory uses. The scripted tool-call channel
(`AXIAL_STUB_TOOL_CALLS`) and `RecordLLMClient` (to observe the assembled
prompt) are the exact mechanisms `tests/analysis/test_retrieval_planning_
requery.py` already established; this file is LLM-free (no real model call
is made anywhere in it).

The fixture -- a name layer plus a handful of prose notes -- is built fresh
under `tmp_path` per test, following the fixture-building approach
`tests/analysis/test_name_query.py` (slice 02's own acceptance test)
established, trimmed to only what this slice's tools need: no artifact
notes, no embedding tier (tiers 1-3 alone resolve everything this file
needs, so no vector store or encoder is built at all).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, PremiseAssessment, disposition_for
from axial.llm import STUB_TOOL_CALLS_ENV_VAR, RecordLLMClient, StubLLMClient
from axial.query import get_chunk
from axial.retrieve.loop import run_planned_retrieval, run_retrieval_loop

TILLY = "Charles Tilly"

EGYPT_CHUNK_ID = "tillyfix-1978-aaaaaaaaaaaa_1_egypt_001"
LEBANON_CHUNK_ID = "tillyfix-1978-aaaaaaaaaaaa_2_lebanon_001"
SYRIA_CHUNK_ID = "tillyfix-1978-aaaaaaaaaaaa_3_syria_001"
BATATU_CHUNK_ID = "batatufix-1978-bbbbbbbbbbbb_1_iraq_001"


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


def _render(frontmatter: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n" + body


def _prose_note(
    *,
    chunk_id: str,
    author: str,
    year: int,
    claim: str,
    names: list[dict[str, str]],
    citations: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": author,
            "title": "A Synthetic Fixture Source",
            "date": year,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "answers": {
            "claim": claim,
            "position_of": "the author",
            "arguing_against": [],
            "names": names,
            "citations": citations or [],
        },
    }


def _write_vault(vault_dir: Path) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    notes = [
        _prose_note(
            chunk_id=EGYPT_CHUNK_ID,
            author="Charles Tilly",
            year=1978,
            claim="Synthetic claim: Egyptian state formation under coercive extraction.",
            names=[{"name": TILLY, "kind": "person"}],
        ),
        _prose_note(
            chunk_id=LEBANON_CHUNK_ID,
            author="Charles Tilly",
            year=1978,
            claim="Synthetic claim: Lebanese state formation under coercive extraction.",
            names=[{"name": TILLY, "kind": "person"}],
        ),
        _prose_note(
            chunk_id=SYRIA_CHUNK_ID,
            author="Charles Tilly",
            year=1978,
            claim="Synthetic claim: Syrian state formation under coercive extraction.",
            names=[{"name": TILLY, "kind": "person"}],
        ),
        # Not a member of Tilly's own name page (its own `names` answer never
        # names Tilly) -- it reaches Tilly only through `who_cites`, which is
        # exactly the traversal this fixture exists to exercise.
        _prose_note(
            chunk_id=BATATU_CHUNK_ID,
            author="Hanna Batatu",
            year=1978,
            claim="Synthetic claim: Iraqi class formation under Ottoman-then-British rule.",
            names=[{"name": "Iraqi state formation", "kind": "concept"}],
            citations=[{"cited": TILLY, "stance": "support", "about": "coercive extraction"}],
        ),
    ]
    for frontmatter in notes:
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(
            _render(frontmatter, "Body.\n"), encoding="utf-8"
        )

    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    member_lines = "\n".join(
        f"- [[{chunk_id}]] — Charles Tilly (1978): {claim}"
        for chunk_id, claim in [
            (
                EGYPT_CHUNK_ID,
                "Synthetic claim: Egyptian state formation under coercive extraction.",
            ),
            (
                LEBANON_CHUNK_ID,
                "Synthetic claim: Lebanese state formation under coercive extraction.",
            ),
            (SYRIA_CHUNK_ID, "Synthetic claim: Syrian state formation under coercive extraction."),
        ]
    )
    page_body = f"# {TILLY}\n\n**Aliases:** Tilly\n\n**Member notes:**\n{member_lines}\n"
    (names_dir / "charles-tilly.md").write_text(
        _render(
            {"name": TILLY, "kind": "person", "aliases": ["Tilly"], "member_count": 3},
            page_body,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[Path, Path]:
    """`(vault_dir, names_dir)`."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_vault(vault_dir)
    _write_name_layer(names_dir)
    return vault_dir, names_dir


def _brief(case: str = "Syria") -> Brief:
    return Brief(
        brief_id="test-brief-488",
        case=case,
        request="What does Tilly's coercive-extraction account explain about the region?",
        lens=None,
    )


def _proceed_bounded_interrogation_result() -> InterrogationResult:
    premises_found = [
        PremiseAssessment(
            premise="The corpus covers comparative state formation.", assessment="silent"
        )
    ]
    bounds_applied = ["Covers coercive-extraction theory, not economic policy."]
    disposition = disposition_for(premises_found, bounds_applied, refusal=None)
    return InterrogationResult(
        premises_found=premises_found,
        bounds_applied=bounds_applied,
        refusal=None,
        disposition=disposition,
    )


def _set_scripted_tool_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any] | None]
) -> None:
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps(calls))


# ---------------------------------------------------------------------------
# Scenario 1: name resolution -> member reads -> traversal; evidence
# resolves through get_chunk; no name string lands in the evidence set.
# ---------------------------------------------------------------------------


def test_trajectory_resolves_name_reads_members_then_traverses_and_evidence_resolves(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "find_names", "args": {"query": "Tilly"}},
            {"tool": "get_name", "args": {"canonical": TILLY}},
            {"tool": "who_cites", "args": {"canonical": TILLY}},
            None,
        ],
    )
    client = StubLLMClient()
    brief = _brief(case="Syria")
    interrogation_result = _proceed_bounded_interrogation_result()

    result = run_planned_retrieval(
        client,
        brief,
        interrogation_result,
        vault_dir=vault_dir,
        names_dir=names_dir,
        step_budget=10,
        thin_result_floor=1,
    )

    assert [entry["tool"] for entry in result.trajectory] == [
        "find_names",
        "get_name",
        "who_cites",
    ], f"expected name resolution -> member reads -> traversal, got {result.trajectory!r}"

    resolution, member_read, traversal = result.trajectory
    assert resolution["result_ids"] == [TILLY]
    assert member_read["result_ids"] == [EGYPT_CHUNK_ID, LEBANON_CHUNK_ID, SYRIA_CHUNK_ID], (
        "get_name returns the page's own member order"
    )
    assert traversal["result_ids"] == [BATATU_CHUNK_ID], (
        "who_cites reaches a note that is not itself a page member -- a real traversal"
    )

    assert TILLY not in result.evidence_ids, (
        "a canonical name string must never land in the chunk-valued evidence set"
    )
    assert set(result.evidence_ids) == {
        EGYPT_CHUNK_ID,
        LEBANON_CHUNK_ID,
        SYRIA_CHUNK_ID,
        BATATU_CHUNK_ID,
    }
    for chunk_id in result.evidence_ids:
        assert get_chunk(chunk_id, vault_dir=vault_dir).chunk_id == chunk_id, (
            f"every assembled evidence id must resolve through get_chunk, {chunk_id!r} did not"
        )


# ---------------------------------------------------------------------------
# Scenario 2: case-as-anchor, not case-as-fence.
# ---------------------------------------------------------------------------


def test_case_anchored_brief_reaches_a_name_whose_members_are_mostly_other_polities(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    """The brief's case is "Syria", but two of Tilly's three member notes are
    about Egypt and Lebanon -- other polities -- and the third traversal hop
    reaches an Iraq-focused note. Nothing filters any of them out."""
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "find_names", "args": {"query": "Tilly"}},
            {"tool": "get_name", "args": {"canonical": TILLY}},
            {"tool": "who_cites", "args": {"canonical": TILLY}},
            None,
        ],
    )
    client = StubLLMClient()
    brief = _brief(case="Syria")
    interrogation_result = _proceed_bounded_interrogation_result()

    result = run_planned_retrieval(
        client,
        brief,
        interrogation_result,
        vault_dir=vault_dir,
        names_dir=names_dir,
        step_budget=10,
        thin_result_floor=1,
    )

    other_polity_ids = {EGYPT_CHUNK_ID, LEBANON_CHUNK_ID, BATATU_CHUNK_ID}
    assert other_polity_ids <= set(result.evidence_ids), (
        f"case-as-anchor, not case-as-fence: material about other polities must survive "
        f"assembly uncensored, got {result.evidence_ids!r}"
    )
    assert SYRIA_CHUNK_ID in result.evidence_ids, "the case-scoped note is retrieved too"


# ---------------------------------------------------------------------------
# Scenario 3: the dispatcher rejects a retired tool and an undeclared arg,
# both before reaching the vault, and the loop continues past each.
# ---------------------------------------------------------------------------


def test_dispatcher_rejects_retired_tool_and_undeclared_arg_before_reaching_vault(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture

    from axial.query import names as names_module

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the name layer must never be reached for a rejected call")

    monkeypatch.setattr(names_module, "find_names", _explode)

    _set_scripted_tool_calls(
        monkeypatch,
        [
            # a tool that no longer exists (D1/D5)
            {"tool": "query_by_polity", "args": {"polity": "Syria"}},
            # a well-named tool with an arg its schema does not declare
            {"tool": "find_names", "args": {"query": "Tilly", "polity": "Syria"}},
            None,
        ],
    )
    client = StubLLMClient()

    trajectory = run_retrieval_loop(
        client, "irrelevant prompt", vault_dir=vault_dir, names_dir=names_dir, step_budget=10
    )

    assert len(trajectory) == 2, f"the loop must continue past each rejection, got {trajectory!r}"
    retired_call, undeclared_arg_call = trajectory

    assert retired_call["tool"] == "query_by_polity"
    assert retired_call["result_ids"] == []
    assert retired_call["result_count"] == 0

    assert undeclared_arg_call["tool"] == "find_names"
    assert undeclared_arg_call["result_ids"] == []
    assert undeclared_arg_call["result_count"] == 0


# ---------------------------------------------------------------------------
# Scenario 4: re-query on thin results is observable over the new surface.
# ---------------------------------------------------------------------------


def test_thin_first_find_names_call_triggers_a_different_broadened_call(
    fixture: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            # matches no tier -- an honest empty resolution, THIN
            {"tool": "find_names", "args": {"query": "zzqqx nonexistent scholar"}},
            # a DIFFERENT call: broadened to a query that actually resolves
            {"tool": "find_names", "args": {"query": "Tilly"}},
            None,
        ],
    )
    record_path = tmp_path / "record.jsonl"
    client = RecordLLMClient(record_path)

    trajectory = run_retrieval_loop(
        client,
        "seed prompt",
        vault_dir=vault_dir,
        names_dir=names_dir,
        step_budget=10,
        thin_result_floor=1,
    )

    assert len(trajectory) >= 2
    first, second = trajectory[0], trajectory[1]
    assert first["tool"] == "find_names"
    assert first["result_count"] == 0
    assert first["result_ids"] == []
    assert second["tool"] == "find_names"
    assert second["args"] != first["args"], "the re-query must be a DIFFERENT call, not a retry"
    assert second["result_ids"] == [TILLY]

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) >= 2
    step_2_prompt = prompts[1]
    assert "result_count=0" in step_2_prompt, (
        f"the re-query must be recorded as happening ON the thin signal, got {step_2_prompt!r}"
    )
