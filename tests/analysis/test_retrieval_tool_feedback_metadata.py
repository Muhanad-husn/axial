"""Acceptance test for issue #545: the retrieval loop's tool feedback
carries per-id metadata, not bare ids (specs/PHASE-B.md §7.5, §7.6).

`axial.retrieve.loop.tool_feedback` used to hand the model a bare id list
(`result.ids`) for a successful chunk-valued call -- a ~200-char id string
per note, with no author, year or claim attached. The model was choosing
what to retrieve next, and later which twenty notes matter most, by string
alone.

Design pick (measured in the PR body): a single, uniform helper
(`chunk_feedback_metadata`) reads each returned id's own prose note
(`axial.query.reader.get_chunk`) and renders `"<chunk_id> — <author>
(<year>): <claim>"` -- the exact shape a name page's own member line already
carries (`axial.materialize.render_name_page_body`). Applied at the feedback
site to every chunk-valued tool's own result, so `get_name` (whose members
already carry author/year/claim for free) and `who_cites`/`who_argues_
against` (whose own edge types carry neither) hand back the SAME shape of
feedback -- never rich for one call and bare for the next.

Three constraints this file also pins:

- An abstention is never coerced into an answer's shape (§7.15, issue #489):
  `is_abstention` is applied before a claim reaches the model.
- `author`/`year` are rendered exactly as the note holds them, `None`
  included -- never guessed at or backfilled.
- Never a §7.6 trajectory field and never a cap, budget or count of what
  more would fit -- states only what a returned id's own note holds.

Seam decisions
--------------
Direct unit tests over the pure function (`chunk_feedback_metadata`) for the
rendering rules, plus the same library-call seam every other retrieval-loop
acceptance test in this directory uses (`AXIAL_STUB_TOOL_CALLS` +
`axial.llm.RecordLLMClient`) for the end-to-end, uniform-across-tools claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.llm import STUB_TOOL_CALLS_ENV_VAR, RecordLLMClient
from axial.retrieve.loop import chunk_feedback_metadata, run_retrieval_loop

SOURCE_A = "feedbackfix-alpha"
SOURCE_B = "feedbackfix-beta"


def _note(
    chunk_id: str,
    *,
    author: Any = "A. Synthetic Author",
    date: Any = 2021,
    claim: Any = "some-key-holds-a-value",
    include_claim_key: bool = True,
) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    if include_claim_key:
        answers["claim"] = claim
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {"author": author, "date": date, "title": "A Fixture"},
        "answers": answers,
    }


def _write_note(prose_dir: Path, frontmatter: dict[str, Any]) -> None:
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def unit_vault_dir(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "feedback-vault"
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    _write_note(
        prose_dir,
        _note(
            f"{SOURCE_A}_1_intro_001",
            author="Ada Researcher",
            date=1990,
            claim="Ada's own claim about method.",
        ),
    )
    _write_note(
        prose_dir,
        _note(f"{SOURCE_A}_1_intro_002", claim="not-in-passage"),
    )
    _write_note(
        prose_dir,
        _note(f"{SOURCE_A}_1_intro_003", include_claim_key=False),
    )
    _write_note(
        prose_dir,
        _note(f"{SOURCE_B}_1_intro_001", author=None, date=None, claim="No metadata here."),
    )
    return vault_dir


# ---------------------------------------------------------------------------
# chunk_feedback_metadata: the pure rendering rules
# ---------------------------------------------------------------------------


def test_renders_author_year_and_claim_per_id(unit_vault_dir: Path):
    rendered = chunk_feedback_metadata([f"{SOURCE_A}_1_intro_001"], unit_vault_dir)

    assert rendered is not None
    assert f"{SOURCE_A}_1_intro_001" in rendered
    assert "Ada Researcher" in rendered
    assert "1990" in rendered
    assert "Ada's own claim about method." in rendered


def test_joins_several_ids_and_keeps_each_ones_claim_distinguishable(unit_vault_dir: Path):
    rendered = chunk_feedback_metadata(
        [f"{SOURCE_A}_1_intro_001", f"{SOURCE_B}_1_intro_001"], unit_vault_dir
    )

    assert rendered is not None
    assert "Ada's own claim about method." in rendered
    assert "No metadata here." in rendered


def test_an_abstention_is_marked_not_coerced_into_an_answer(unit_vault_dir: Path):
    """Issue #489's rule applied here: `is_abstention` runs before a claim
    reaches the model, so the raw D7 marker never reads like a real
    (terse) claim."""
    rendered = chunk_feedback_metadata([f"{SOURCE_A}_1_intro_002"], unit_vault_dir)

    assert rendered is not None
    assert "not-in-passage" not in rendered
    assert "(not stated in the passage)" in rendered


def test_a_note_with_no_claim_key_at_all_is_marked_not_guessed(unit_vault_dir: Path):
    rendered = chunk_feedback_metadata([f"{SOURCE_A}_1_intro_003"], unit_vault_dir)

    assert rendered is not None
    assert "(no claim recorded)" in rendered


def test_missing_author_and_year_render_honestly_never_backfilled(unit_vault_dir: Path):
    """`author`/`year` are legitimately `None` on the real corpus (issue
    #545). Rendered exactly as held -- never guessed at, never replaced with
    a friendlier placeholder that would misrepresent what the note says."""
    rendered = chunk_feedback_metadata([f"{SOURCE_B}_1_intro_001"], unit_vault_dir)

    assert rendered is not None
    assert "None (None)" in rendered


def test_an_id_that_does_not_resolve_to_a_note_is_skipped_not_raised(unit_vault_dir: Path):
    """Covers an artifact id from `get_artifact` reaching this function
    through the same uniform call site: it is not a prose note, so it
    contributes no metadata line, and the call never raises."""
    rendered = chunk_feedback_metadata(["no-such-chunk-id-at-all"], unit_vault_dir)

    assert rendered is None


def test_a_mixed_list_skips_the_unresolvable_id_and_keeps_the_rest(unit_vault_dir: Path):
    rendered = chunk_feedback_metadata(
        ["no-such-chunk-id-at-all", f"{SOURCE_A}_1_intro_001"], unit_vault_dir
    )

    assert rendered is not None
    assert "Ada's own claim about method." in rendered


def test_an_empty_id_list_renders_nothing(unit_vault_dir: Path):
    assert chunk_feedback_metadata([], unit_vault_dir) is None


# ---------------------------------------------------------------------------
# End to end: applied uniformly at the feedback site, never a leaked cap
# ---------------------------------------------------------------------------


def _set_scripted_tool_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any] | None]
) -> None:
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps(calls))


def test_get_chunk_feedback_carries_the_notes_own_metadata(
    unit_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "get_chunk", "args": {"chunk_id": [f"{SOURCE_A}_1_intro_001"]}}, None],
    )
    record_path = tmp_path / "record.jsonl"

    run_retrieval_loop(
        RecordLLMClient(record_path),
        "PROMPT",
        vault_dir=unit_vault_dir,
        step_budget=5,
        thin_result_floor=3,
    )

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert "notes:" in prompts[1]
    assert "Ada Researcher" in prompts[1]
    assert "Ada's own claim about method." in prompts[1]
    # The bare id is still there too -- metadata is additive, not a
    # replacement of the id the model needs to cite.
    assert f"{SOURCE_A}_1_intro_001" in prompts[1]


def test_query_by_source_gets_the_same_shape_as_get_chunk_not_ragged(
    unit_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`query_by_source` carries no author/year/claim of its own -- proving
    this is a uniform per-id read, not a per-tool thread of whatever shape
    each tool happens to already have (the design pick this issue chose
    over threading `NameMember` et al. through `ToolResult`)."""
    _set_scripted_tool_calls(
        monkeypatch, [{"tool": "query_by_source", "args": {"source_id": SOURCE_A}}, None]
    )
    record_path = tmp_path / "record.jsonl"

    run_retrieval_loop(
        RecordLLMClient(record_path),
        "PROMPT",
        vault_dir=unit_vault_dir,
        step_budget=5,
        thin_result_floor=3,
    )

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert "notes:" in prompts[1]
    assert "Ada Researcher" in prompts[1]


def test_a_name_valued_result_never_gets_note_metadata_even_if_it_looks_like_a_chunk_id(
    unit_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`find_names` returns canonical NAMES, never chunk ids
    (`returns_chunk_ids=False`) -- a regression guard, not just an absence:
    the resolved "canonical" here is deliberately the exact chunk_id of a
    REAL note, so if the feedback site ever stopped gating on
    `ToolSpec.returns_chunk_ids` this would silently start passing too."""
    lookalike = f"{SOURCE_A}_1_intro_001"
    names_dir = tmp_path / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "index.json").write_text(
        json.dumps({"version": 1, "generated_at": "2026-07-30T00:00:00Z", "names": [lookalike]}),
        encoding="utf-8",
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": "2026-07-30T00:00:00Z",
                "nodes": [{"canonical": lookalike, "kind": "person", "aliases": []}],
            }
        ),
        encoding="utf-8",
    )
    _set_scripted_tool_calls(
        monkeypatch, [{"tool": "find_names", "args": {"query": lookalike}}, None]
    )
    record_path = tmp_path / "record.jsonl"

    run_retrieval_loop(
        RecordLLMClient(record_path),
        "PROMPT",
        vault_dir=unit_vault_dir,
        names_dir=names_dir,
        step_budget=5,
        thin_result_floor=3,
    )

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert "notes:" not in prompts[1]
