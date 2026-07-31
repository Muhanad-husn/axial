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

Given a scripted get_name call capped with limit=1 against the fixture's
      3-member Tilly page (issue #505)
When  the retrieval loop runs
Then  the trajectory entry still has exactly the §7.6 fields (seven, since
      issue #493 additively persists `total`/`detail` onto the entry too),
      with result_count 1
  And the recorded prompt for the next step states "1 of 3 total" and invites
      a larger limit
  And the same call with no limit (3 of 3, uncapped) adds no such text at all
  And a call that is both THIN (below thin_result_floor) and capped states
      both notes -- neither may silently swallow the other

Given a scripted find_names call that resolves through the alias tier
      (issue #517: planner blindness -- the loop used to hand back only a
      bare canonical string)
When  the retrieval loop runs
Then  the trajectory entry still has exactly the §7.6 fields (seven, issue
      #493)
  And the recorded prompt for the next step states the hit's kind and tier,
      so the model can tell a solid resolution from a guess
  And the entry's own persisted `detail` field states the same kind/tier,
      answerable offline without replaying the prompt

Given a scripted get_name call, and separately a scripted where_names_meet
      call, each against members drawn from a known number of sources
      (issue #517's own follow-up: a live corpus run showed a model told to
      intersect only a "large" name avoiding the tool by resolving narrow,
      one-book names instead)
When  the retrieval loop runs
Then  each trajectory entry still has exactly the §7.6 fields (seven, issue
      #493)
  And the recorded prompt for the next step states how many distinct
      sources the returned members actually span

See specs/PHASE-B.md §4 (the agentic loop, case-as-anchor P0-3), §7.5 (the
name-layer tools, [FIRM], and D4's Gather-hint rule) and §7.6 (the
trajectory log, [FIRM]; its shape gained `total`/`detail` as of issue #493,
additive over the original five) for the source of truth, and
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


# ---------------------------------------------------------------------------
# Scenario 5 (issue #505): a capped result states its true total in the next
# prompt, and an uncapped one adds no such noise. The trajectory entry stays
# exactly the §7.6 fields either way (seven since issue #493 additively
# persists `total`/`detail` onto the entry itself, not only the next prompt).
# ---------------------------------------------------------------------------


def test_capped_get_name_result_states_the_true_total_in_the_next_prompt(
    fixture: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Tilly's fixture page has 3 members (issue #505's own worst real case
    is `Syria` at 962). `limit=1` returns 1 of 3, and the next turn's prompt
    must say so -- the load-bearing half of the fix: a cap the model cannot
    see is a lie about the corpus."""
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "get_name", "args": {"canonical": TILLY, "limit": 1}},
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

    assert len(trajectory) == 1
    entry = trajectory[0]
    # issue #493: `total`/`detail` are now persisted onto the entry too,
    # additive over the original five -- this assertion is updated with that
    # one-line justification rather than the shape drifting unnoticed.
    assert set(entry) == {"step", "tool", "args", "result_ids", "result_count", "total", "detail"}
    assert entry["result_count"] == 1, "result_count is the honest count of ids returned"
    assert entry["result_ids"] == [EGYPT_CHUNK_ID]
    assert entry["total"] == 3, "the entry itself now carries the true pre-cap total"

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    step_2_prompt = prompts[1]
    assert "1 of 3 total" in step_2_prompt, (
        f"expected the true pre-cap total stated in the next prompt, got {step_2_prompt!r}"
    )
    assert "larger limit" in step_2_prompt


def test_an_uncapped_result_adds_no_total_noise_to_the_next_prompt(
    fixture: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The same page, called with the default `limit` (10): 3 of 3 members
    come back, nothing was capped, and the next prompt must not mention a
    total at all -- a capped-result notice on an uncapped call would be
    exactly the noise a real provider's model has no reason to see."""
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "get_name", "args": {"canonical": TILLY}},
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

    assert trajectory[0]["result_count"] == 3

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    step_2_prompt = prompts[1]
    assert "total" not in step_2_prompt, (
        f"an uncapped result must not mention a total at all, got {step_2_prompt!r}"
    )


def test_a_result_that_is_both_thin_and_capped_states_both_notes(
    fixture: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A small caller-chosen `limit` can be below `thin_result_floor` AND
    capped below `result.total` at once: `limit=1` against Tilly's 3-member
    page, with the default `thin_result_floor` (3), is both. Neither signal
    may silently swallow the other."""
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "get_name", "args": {"canonical": TILLY, "limit": 1}},
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
        thin_result_floor=3,
    )

    assert trajectory[0]["result_count"] == 1

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    step_2_prompt = prompts[1]
    assert "THIN" in step_2_prompt, f"the thin signal must not be dropped, got {step_2_prompt!r}"
    assert "1 of 3 total" in step_2_prompt, (
        f"the capped signal must not be dropped, got {step_2_prompt!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 6 (issue #517): find_names' own resolution detail -- kind,
# member_count, tier -- reaches the next turn's prompt, beside the
# trajectory, AND (issue #493) is now also persisted onto the trajectory
# entry itself, so the record answers the same question offline.
# ---------------------------------------------------------------------------


def test_find_names_detail_reaches_the_next_turns_prompt(
    fixture: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Before this, the loop handed the model only a bare canonical string
    for every `find_names` hit, so an exact/alias resolution and an
    embedding guess at cosine 0.78 were indistinguishable -- the planner-
    blindness signature #505's run 1 showed (ten find_names calls, seven
    returning a single result). `ToolResult.detail` carries the hit's own
    `kind`/`member_count`/`tier`, and the loop appends it to the next
    prompt, the same way `total` already rides beside the trajectory."""
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "find_names", "args": {"query": "Tilly"}},
            None,
        ],
    )
    record_path = tmp_path / "record.jsonl"
    client = RecordLLMClient(record_path)

    trajectory = run_retrieval_loop(
        client, "seed prompt", vault_dir=vault_dir, names_dir=names_dir, step_budget=10
    )

    assert len(trajectory) == 1
    # issue #493: `detail` (and `total`) now ride on the persisted entry too,
    # not only the next prompt -- updated with that one-line justification.
    assert set(trajectory[0]) == {
        "step",
        "tool",
        "args",
        "result_ids",
        "result_count",
        "total",
        "detail",
    }

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    step_2_prompt = prompts[1]
    assert "kind=person" in step_2_prompt, (
        f"expected the hit's kind in the next prompt, got {step_2_prompt!r}"
    )
    assert "member_count=3" in step_2_prompt, (
        f"expected the hit's member_count in the next prompt, got {step_2_prompt!r}"
    )
    assert "tier=alias" in step_2_prompt, (
        f"expected which tier resolved the query in the next prompt, got {step_2_prompt!r}"
    )

    # The record itself (not only the prompt) must answer the same question
    # offline -- the whole point of issue #493.
    detail = trajectory[0]["detail"]
    assert detail is not None and "kind=person" in detail
    assert "member_count=3" in detail
    assert "tier=alias" in detail


def test_get_name_detail_reaches_the_next_turns_prompt(
    fixture: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """issue #517's own follow-up: a live corpus run showed a model cannot
    tell a large page is one book from a bare chunk_id list. All three of
    Tilly's fixture member notes share one `source_id`, so `detail` states
    a one-source span the model can check directly."""
    vault_dir, names_dir = fixture
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "get_name", "args": {"canonical": TILLY}},
            None,
        ],
    )
    record_path = tmp_path / "record.jsonl"
    client = RecordLLMClient(record_path)

    trajectory = run_retrieval_loop(
        client, "seed prompt", vault_dir=vault_dir, names_dir=names_dir, step_budget=10
    )

    assert set(trajectory[0]) == {
        "step",
        "tool",
        "args",
        "result_ids",
        "result_count",
        "total",
        "detail",
    }, "issue #493: detail (and total) now ride on the persisted entry too"

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    step_2_prompt = prompts[1]
    assert "3 notes across 1 sources" in step_2_prompt, (
        f"expected the source-span detail in the next prompt, got {step_2_prompt!r}"
    )
    assert trajectory[0]["detail"] == "3 notes across 1 sources"
    assert trajectory[0]["total"] == 3


def test_where_names_meet_detail_reaches_the_next_turns_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Same fix, for the intersection itself: two notes from two different
    sources report as spanning two sources, not just as two notes."""
    vault_dir = tmp_path / "vault"
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)

    def _write_page(name: str, filename: str, chunk_ids: list[str]) -> None:
        member_lines = "\n".join(
            f"- [[{chunk_id}]] — Author (2020): A claim." for chunk_id in chunk_ids
        )
        body = f"# {name}\n\n**Member notes:**\n{member_lines}\n"
        (names_dir / filename).write_text(
            "---\n"
            + yaml.safe_dump(
                {"name": name, "kind": "concept", "aliases": [], "member_count": len(chunk_ids)},
                sort_keys=False,
            )
            + "---\n"
            + body,
            encoding="utf-8",
        )

    shared = ["srcA_1_a_001", "srcB_1_a_001"]
    _write_page("A", "a.md", shared)
    _write_page("B", "b.md", shared)

    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "where_names_meet", "args": {"canonical": "A", "other": "B"}},
            None,
        ],
    )
    record_path = tmp_path / "record.jsonl"
    client = RecordLLMClient(record_path)

    trajectory = run_retrieval_loop(
        client, "seed prompt", vault_dir=vault_dir, names_dir=names_dir, step_budget=10
    )

    assert set(trajectory[0]) == {
        "step",
        "tool",
        "args",
        "result_ids",
        "result_count",
        "total",
        "detail",
    }

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    step_2_prompt = prompts[1]
    assert "2 notes across 2 sources" in step_2_prompt, (
        f"expected the source-span detail in the next prompt, got {step_2_prompt!r}"
    )
    assert trajectory[0]["detail"] == "2 notes across 2 sources"
    assert trajectory[0]["total"] == 2
