"""Outer acceptance test for issue #649: Axial measures the question against
the corpus it actually has, and asks the analyst only at a genuine fork.

Given a fixture vault whose store holds "Syria" with 4 member notes across
      two sources -- three from a 2021 monograph, one from an older, 1999
      source -- and a scripted fork-check response naming that imbalance
When  `run_brief` runs with the analyst's answer pre-supplied on the brief
      (`fork_answer={"option": "background only"}`, the batch-mode seam)
Then  the persisted record's `intake_fork` block discloses the question
      asked, the answer given, and what it did
  And the assembled evidence set is smaller and drops the dominant source --
      the analyst's answer demonstrably changed the evidence set

Given the identical fixture and fork-check script, but NO answer supplied
      (no `brief.fork_answer`, no `on_fork` callback -- `axial brief run`'s
      own batch shape)
When  `run_brief` runs
Then  the fork is still recorded, `answer` is `null`, and the assembled
      evidence set is UNCONSTRAINED (identical to a brief with no fork
      answered at all) -- never guessed at, never blocked on

Given the identical fixture, but a scripted fork-check response of
      `is_fork: false`
When  `run_brief` runs
Then  `intake_fork.is_fork` is `false` and the evidence set is unaffected --
      a question with no fork asks nothing

See specs/PHASE-B.md §7 (DEC-62) and `axial.brief.fork`'s own module
docstring for the source of truth.
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
from axial.llm import (
    STUB_FORK_CHECK_RESPONSE_ENV_VAR,
    STUB_SYNTHESIZE_RESPONSE_ENV_VAR,
    STUB_TOOL_CALLS_ENV_VAR,
    StubLLMClient,
)
from axial.paths import name_page_path
from axial.query import store as note_store

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_LENSES_DIR = REPO_ROOT / "config" / "lenses"

SOURCE_DOMINANT = "vignalfix-2021-aaaaaaaaaaaa"
SOURCE_OLDER = "oldfix-1999-bbbbbbbbbbbb"

DOMINANT_IDS = [
    f"{SOURCE_DOMINANT}_000_intro_001",
    f"{SOURCE_DOMINANT}_001_intro_002",
    f"{SOURCE_DOMINANT}_002_intro_003",
]
OLDER_ID = f"{SOURCE_OLDER}_000_intro_001"

_FORK_FOUND_RESPONSE = json.dumps(
    {
        "is_fork": True,
        "concept": "Syria",
        "kind": "source_imbalance",
        "question": (
            "75% of the material on Syria is Vignal's 2021 monograph and the rest "
            "predates it -- background only, or full voices?"
        ),
        "options": [
            {
                "label": "background only",
                # `SOURCE_DOMINANT` has 3 notes, `SOURCE_OLDER` has 1 --
                # `concept_sources` ranks by note count descending, so
                # `SOURCE_DOMINANT` is index 1 (issue #649: an option names
                # a source by this rendered index, never the raw id text).
                "drop_source_indices": [1],
                "per_source_cap": None,
                "guidance": "treat the 2021 monograph as background, not a full voice",
            },
            {
                "label": "full voices",
                "drop_source_indices": [],
                "per_source_cap": None,
                "guidance": "read every source as an equal voice",
            },
        ],
    }
)

_NO_FORK_RESPONSE = json.dumps({"is_fork": False})

# A well-formed JSON response whose `drop_source_indices` names an index the
# concept's own measurement does not carry -- the well-formed-but-wrong-
# content case `parse_fork_response` rejects with `ForkCheckParseError`
# (never a mistyped `source_id` string post-issue #649's index-based wire
# shape, but an out-of-range index is still possible and must fail the same
# deterministic way).
_BAD_INDEX_FORK_RESPONSE = json.dumps(
    {
        "is_fork": True,
        "concept": "Syria",
        "kind": "source_imbalance",
        "question": "background only, or full voices?",
        "options": [
            {
                "label": "background only",
                "drop_source_indices": [99],
                "per_source_cap": None,
                "guidance": "treat the 2021 monograph as background",
            }
        ],
    }
)


def _note_frontmatter(*, chunk_id: str, source_id: str, author: str, year: int) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Introduction",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose about Syria.",
        "source_meta": {
            "author": author,
            "title": f"{author}'s Book",
            "date": year,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "frame_version": "0.2",
        "answers": {
            "claim": f"Synthetic claim from {chunk_id}.",
            "move": "stating a mechanism",
            "position_of": "the author",
            "position": "a synthetic position",
            "names": [{"name": "Syria", "kind": "place"}],
        },
    }


def _render(frontmatter: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n" + body


def _write_fixture_root(root: Path) -> None:
    prose_dir = root / "data" / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    notes = [(chunk_id, SOURCE_DOMINANT, "Vignal", 2021) for chunk_id in DOMINANT_IDS] + [
        (OLDER_ID, SOURCE_OLDER, "Old Author", 1999)
    ]
    for chunk_id, source_id, author, year in notes:
        frontmatter = _note_frontmatter(
            chunk_id=chunk_id, source_id=source_id, author=author, year=year
        )
        (prose_dir / f"{chunk_id}.md").write_text(_render(frontmatter, "Body.\n"), encoding="utf-8")

    vault_dir = root / "data" / "vault"
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[
            (SOURCE_DOMINANT, "Vignal", "Vignal's Book", "2021", 2021),
            (SOURCE_OLDER, "Old Author", "Old Author's Book", "1999", 1999),
        ],
        notes=[
            (chunk_id, source_id, "Introduction", None, f"Synthetic claim from {chunk_id}.", None)
            for chunk_id, source_id, _author, _year in notes
        ],
        names=[("Syria", "place", "syria")],
        note_names=[
            (chunk_id, source_id, "Syria", "place") for chunk_id, source_id, _author, _year in notes
        ],
        note_arguing_against=[],
        note_citations=[],
    )

    # `get_name` still resolves the rendered page for its Gather section and
    # its own `NameNotFoundError` meaning (`axial.query.names.
    # _name_page_from_store`'s own docstring) even though its MEMBER data
    # comes from the store above -- so a real page must exist too.
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    member_lines = "\n".join(
        f"- [[{chunk_id}]] — {author} ({year}): Synthetic claim from {chunk_id}."
        for chunk_id, _source_id, author, year in notes
    )
    page_body = f"# Syria\n\n**Member notes:**\n{member_lines}\n"
    page_path = name_page_path(vault_dir, "Syria")
    page_path.write_text(
        _render({"name": "Syria", "kind": "place", "member_count": 4}, page_body),
        encoding="utf-8",
    )

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


def _script_retrieval_and_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        STUB_TOOL_CALLS_ENV_VAR,
        json.dumps(
            [
                {"tool": "find_names", "args": {"query": "Syria"}},
                {"tool": "get_name", "args": {"canonical": "Syria"}},
                None,
            ]
        ),
    )
    monkeypatch.setenv(
        STUB_SYNTHESIZE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                "claims": [
                    {
                        "text": "A synthetic claim about Syria.",
                        "kind": "a",
                        "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                        "confidence": "medium",
                    }
                ]
            }
        ),
    )


def _brief(*, fork_answer: dict[str, str | None] | None = None) -> Brief:
    return Brief(
        brief_id="fork-fix-brief" if fork_answer is None else "fork-fix-brief-answered",
        case="Syria",
        request="What does the corpus say about Syria?",
        fork_answer=fork_answer,
    )


def test_a_pre_supplied_answer_drops_the_named_source_from_the_evidence_set(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(STUB_FORK_CHECK_RESPONSE_ENV_VAR, _FORK_FOUND_RESPONSE)
    _script_retrieval_and_synthesis(monkeypatch)

    brief = _brief(fork_answer={"option": "background only", "free_text": None})
    result = run_brief(brief, client=StubLLMClient(), vault_dir=fixture_root / "data" / "vault")
    record = result.record

    assert record["intake_fork"]["is_fork"] is True
    assert record["intake_fork"]["concept"] == "Syria"
    assert record["intake_fork"]["answer"] == {"option": "background only", "free_text": None}
    assert record["intake_fork"]["effect"]["sources_before"] == 2
    assert record["intake_fork"]["effect"]["sources_after"] == 1
    assert record["intake_fork"]["effect"]["notes_before"] == 4
    assert record["intake_fork"]["effect"]["notes_after"] == 1

    # The named source is gone from the assembled evidence set entirely.
    grounds_ids = {ground["ref_id"] for claim in record["claims"] for ground in claim["grounds"]}
    assert not any(chunk_id in grounds_ids for chunk_id in DOMINANT_IDS)
    assert OLDER_ID in grounds_ids
    assert record["evidence"]["assembled_count"] == 1


def test_a_genuine_fork_with_no_answer_is_disclosed_and_proceeds_unconstrained(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(STUB_FORK_CHECK_RESPONSE_ENV_VAR, _FORK_FOUND_RESPONSE)
    _script_retrieval_and_synthesis(monkeypatch)

    brief = _brief(fork_answer=None)
    result = run_brief(brief, client=StubLLMClient(), vault_dir=fixture_root / "data" / "vault")
    record = result.record

    assert record["intake_fork"]["is_fork"] is True
    assert record["intake_fork"]["answer"] is None
    assert record["intake_fork"]["effect"] is None
    # Unconstrained: every one of the four members is still reachable.
    assert record["evidence"]["assembled_count"] == 4


def test_no_fork_found_asks_nothing_and_measures_it(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(STUB_FORK_CHECK_RESPONSE_ENV_VAR, _NO_FORK_RESPONSE)
    _script_retrieval_and_synthesis(monkeypatch)

    result = run_brief(
        _brief(), client=StubLLMClient(), vault_dir=fixture_root / "data" / "vault"
    )
    record = result.record

    assert record["intake_fork"]["measured"] is True
    assert record["intake_fork"]["is_fork"] is False
    assert record["intake_fork"]["question"] is None
    assert record["intake_fork"]["effect"] is None
    assert record["evidence"]["assembled_count"] == 4


def test_a_response_naming_an_unknown_index_fails_the_check_but_the_run_completes(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """A well-formed JSON fork-check response whose `drop_source_indices`
    names an index the concept's own measurement does not carry --
    `parse_fork_response` still rejects it (`ForkCheckParseError`), but
    `run_brief`'s own call site is where that failure has to land now
    (issue #649): the check is advisory, so a malformed answer degrades to
    "unconstrained", with `intake_fork.failed` saying plainly that the
    check itself failed -- never that no fork existed, and never a raise
    that discards the interrogation call already paid for."""
    monkeypatch.setenv(STUB_FORK_CHECK_RESPONSE_ENV_VAR, _BAD_INDEX_FORK_RESPONSE)
    _script_retrieval_and_synthesis(monkeypatch)

    result = run_brief(
        _brief(), client=StubLLMClient(), vault_dir=fixture_root / "data" / "vault"
    )
    record = result.record

    assert record["intake_fork"]["measured"] is False
    assert record["intake_fork"]["is_fork"] is False
    assert record["intake_fork"]["failed"] is not None
    assert "drop_source_indices" in record["intake_fork"]["failed"]
    assert record["intake_fork"]["answer"] is None
    assert record["intake_fork"]["effect"] is None
    # Unconstrained, exactly like a genuine "no fork" verdict -- every
    # member is still reachable, and the run completed all the way through
    # synthesis rather than dying on the fork-check.
    assert record["evidence"]["assembled_count"] == 4
    assert record["claims"]


def test_a_fork_check_that_raises_still_completes_the_run_with_an_honest_disclosure(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """`assess_fork` itself still raises on a transport failure
    (`ForkCheckFailedError`) -- that discipline stays available to its own
    callers/tests. It is `run_brief`'s own call site that must degrade: a
    real paid run once lost an entire interrogation call to exactly this
    exception propagating unhandled through an optional pre-pass."""
    import axial.answer.record as record_module
    from axial.brief.fork import ForkCheckFailedError

    def _raise(*_args, **_kwargs):
        raise ForkCheckFailedError("simulated transport failure")

    monkeypatch.setattr(record_module, "assess_fork", _raise)
    _script_retrieval_and_synthesis(monkeypatch)

    result = run_brief(
        _brief(), client=StubLLMClient(), vault_dir=fixture_root / "data" / "vault"
    )
    record = result.record

    assert record["intake_fork"]["measured"] is False
    assert record["intake_fork"]["is_fork"] is False
    assert record["intake_fork"]["failed"] == "simulated transport failure"
    assert record["evidence"]["assembled_count"] == 4
    # The interrogation call already paid for was not thrown away: the run
    # completed all the way through synthesis.
    assert record["claims"]
