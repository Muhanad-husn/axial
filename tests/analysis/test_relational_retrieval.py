"""Outer acceptance test for issue #650 (DEC-62): retrieval walks the notes,
their opposition edges and the argument map's positions, and names, years and
sources are filters on those rather than the way in.

The fixture is a three-source corpus with a real note store and a real name
layer, queried with real SQL -- nothing about the query layer is mocked:

- `mann-2012` (2012) -- two notes, one naming `Michael Mann`, one naming both
  `Michael Mann` and `the state`;
- `hall-2006` (2006) -- one note naming `the state`, one note that names the
  `IEMP model` and argues against `Michael Mann`;
- `smith-1999` (1999) -- one note naming `the state` and arguing against
  nobody.

Given that fixture
When  the retrieval loop calls find_notes(about="the state",
      opposing="Michael Mann")
Then  only Hall's note on the state comes back -- the notes of the two
      sources that do not argue with Mann are filtered out
  And get_name("the state"), the old surface, returns all three regardless,
      because a name page cannot see who its members' authors argue with

Given the same fixture
When  the loop calls find_notes(about="the state", published_after=2000)
Then  only the 2012 and 2006 sources come back
  And the name page for `the state` carries no publication year at all, so
      the same question has no answer on that surface

Given the same fixture
When  the loop calls names_arguing_against(target="Michael Mann")
Then  it returns the names that co-occur INSIDE the notes that argue against
      Mann (the IEMP model), not the corpus-wide co-occurrence
      name_neighbors returns (which includes `the state`)

Given the same fixture
When  the loop calls opposition_pairs(canonical="Michael Mann")
Then  both ends of each cross-source edge come back as citable chunk ids
  And each pair names the free-text target the opposing note actually wrote
  And Mann's own notes are never paired with each other

Given a brief whose walk uses only the new tools
When  run_planned_retrieval assembles the evidence set
Then  the loop keeps its shape: chunk-valued results land in the evidence
      set, name-valued ones never do, the set is ordered source round-robin,
      and an intake fork's ForkConstraint still drops and caps sources

Given the same fixture and a model that writes a phrase, not a canonical
When  the loop calls find_notes(about="the state as a cage of social
      relations")
Then  the notes about the state come back -- the phrase resolves through the
      same tiers find_names uses, not the exact ones alone
  And the result says what the phrase resolved to
  And a phrase nothing resolves says that, instead of a bare zero

Given a vault with NO note store (materialized before it existed)
When  the same loop runs
Then  find_names/get_name still answer from the name pages
  And the new tools report an honest empty result rather than raising

Given a fixture argument map pinned beside the vault
When  the loop calls positions_on(name="the state")
Then  the positions whose passages carry that name come back, ranked by how
      many of their passages do, with each position's own argument sentence
  And the passages behind them land in the evidence set as citable ids

Given a walk that calls ONLY the relational tools
When  the §7.7 coverage map and the §7.13 source-usage disclosure are
      computed off its trajectory
Then  the map carries an entry per name the walk resolved, the confidence
      band is a measured one rather than `not_measured`, and the denominator
      names those canonicals -- the phrase the model wrote never appears as
      if it were a name the corpus carries

See specs/PHASE-B.md §7.5 (the query API, [FIRM]) and
`data/logs/2026-08-04-relational-join-ceiling/summary.md` for the
measurement this slice is built on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.answer.source_usage import compute_source_usage
from axial.brief.fork import ForkConstraint
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, PremiseAssessment, disposition_for
from axial.llm import STUB_TOOL_CALLS_ENV_VAR, StubLLMClient
from axial.paths import name_page_path
from axial.query import store as note_store
from axial.retrieve.loop import run_planned_retrieval
from axial.validators.coverage import (
    NOT_MEASURED_BAND,
    compute_confidence,
    compute_coverage_map,
)

MANN = "mann-2012-aaaaaaaaaaaa"
HALL = "hall-2006-bbbbbbbbbbbb"
SMITH = "smith-1999-cccccccccccc"

MANN_NOTE = f"{MANN}_000_intro_001"
MANN_STATE_NOTE = f"{MANN}_001_two_002"
HALL_STATE_NOTE = f"{HALL}_000_one_001"
HALL_OPPOSING_NOTE = f"{HALL}_001_two_002"
SMITH_STATE_NOTE = f"{SMITH}_000_one_001"

MICHAEL_MANN = "Michael Mann"
THE_STATE = "the state"
IEMP = "IEMP model"

OPPOSITION_TARGET = "Mann's conclusion that ideological power declined after the Reformation"

_NOTES: list[dict[str, Any]] = [
    {
        "chunk_id": MANN_NOTE,
        "source_id": MANN,
        "author": "Mann",
        "year": 2012,
        "claim": "Ideological power declined after the Reformation.",
        "position": "Mann's own account of social power",
        "names": [MICHAEL_MANN],
        "arguing_against": [],
    },
    {
        "chunk_id": MANN_STATE_NOTE,
        "source_id": MANN,
        "author": "Mann",
        "year": 2012,
        "claim": "The state is a cage of caged social relations.",
        "position": "Mann's own account of social power",
        "names": [MICHAEL_MANN, THE_STATE],
        "arguing_against": [],
    },
    {
        "chunk_id": HALL_STATE_NOTE,
        "source_id": HALL,
        "author": "Hall",
        "year": 2006,
        "claim": "The state is a bargain between rulers and ruled.",
        "position": "a historical-sociological account of state power",
        "names": [THE_STATE],
        "arguing_against": [],
    },
    {
        "chunk_id": HALL_OPPOSING_NOTE,
        "source_id": HALL,
        "author": "Hall",
        "year": 2006,
        "claim": "The decline of ideological power does not follow.",
        "position": "a historical-sociological account of state power",
        "names": [IEMP],
        "arguing_against": [OPPOSITION_TARGET],
    },
    {
        "chunk_id": SMITH_STATE_NOTE,
        "source_id": SMITH,
        "author": "Smith",
        "year": 1999,
        "claim": "The state rests on pre-modern ethnic ties.",
        "position": "an ethno-symbolic account",
        "names": [THE_STATE],
        "arguing_against": [],
    },
]

_SOURCE_TITLES = {
    MANN: "The Sources of Social Power",
    HALL: "An Anatomy of Power",
    SMITH: "Nations",
}


def _render(frontmatter: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n" + body


def _write_prose(vault_dir: Path) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for note in _NOTES:
        frontmatter = {
            "chunk_id": note["chunk_id"],
            "section": "Synthetic Section",
            "chunk_text": f"SENTINEL_{note['chunk_id']}: synthetic prose.",
            "source_meta": {
                "author": note["author"],
                "title": _SOURCE_TITLES[note["source_id"]],
                "date": note["year"],
                "thesis": "Synthetic thesis.",
                "scope": "Synthetic scope.",
            },
            "answers": {
                "claim": note["claim"],
                "position": note["position"],
                "position_of": "the author",
                "arguing_against": note["arguing_against"],
                "names": [{"name": name, "kind": "concept"} for name in note["names"]],
                "citations": [],
            },
        }
        (prose_dir / f"{note['chunk_id']}.md").write_text(
            _render(frontmatter, "Body.\n"), encoding="utf-8"
        )


def _write_name_pages(vault_dir: Path) -> None:
    """The rendered pages `find_names`/`get_name` fall back to when a vault
    has no store, and which `get_name` reads its Gather section from even
    when it does."""
    for canonical in (MICHAEL_MANN, THE_STATE, IEMP):
        members = [note for note in _NOTES if canonical in note["names"]]
        member_lines = "\n".join(
            f"- [[{note['chunk_id']}]] — {note['author']} ({note['year']}): {note['claim']}"
            for note in members
        )
        page = f"# {canonical}\n\n**Member notes:**\n{member_lines}\n"
        name_page_path(vault_dir, canonical).parent.mkdir(parents=True, exist_ok=True)
        name_page_path(vault_dir, canonical).write_text(
            _render(
                {"name": canonical, "kind": "concept", "member_count": len(members)},
                page,
            ),
            encoding="utf-8",
        )


def _write_store(vault_dir: Path) -> None:
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[
            (source_id, author, _SOURCE_TITLES[source_id], str(year), year)
            for source_id, author, year in (
                (MANN, "Mann", 2012),
                (HALL, "Hall", 2006),
                (SMITH, "Smith", 1999),
            )
        ],
        notes=[
            (
                note["chunk_id"],
                note["source_id"],
                "Synthetic Section",
                None,
                note["claim"],
                note["position"],
            )
            for note in _NOTES
        ],
        names=[
            (MICHAEL_MANN, "person", "michael mann"),
            (THE_STATE, "concept", "the state"),
            (IEMP, "concept", "iemp model"),
        ],
        note_names=[
            (note["chunk_id"], note["source_id"], name, "concept")
            for note in _NOTES
            for name in note["names"]
        ],
        # The conservative join `axial.materialize._resolve_target` writes:
        # the target's own free text alongside the canonical it resolves to.
        note_arguing_against=[
            (HALL_OPPOSING_NOTE, HALL, OPPOSITION_TARGET, MICHAEL_MANN),
        ],
        note_citations=[],
    )


def _write_name_layer(names_dir: Path) -> None:
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "index.json").write_text(
        json.dumps({"version": 1, "names": [MICHAEL_MANN, THE_STATE, IEMP]}), encoding="utf-8"
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps(
            {
                "version": 1,
                "nodes": [
                    {"canonical": MICHAEL_MANN, "kind": "person", "aliases": ["Mann"]},
                    {"canonical": THE_STATE, "kind": "concept", "aliases": []},
                    {"canonical": IEMP, "kind": "concept", "aliases": []},
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_map(map_dir: Path) -> Path:
    """A fixture argument map, in the shape `axial map build` writes: one
    position per contestable argument, each carrying the passages that make
    it."""
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "map.json").write_text(json.dumps({"encoder": "fixture"}), encoding="utf-8")
    positions = [
        {
            "position_id": "p-0001",
            "argument": "The state is a container of social relations, not a bargain.",
            "size": 3,
            "sources": [HALL, MANN, SMITH],
            "authors": ["Mann", "Hall", "Smith"],
            "chunk_ids": [MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE],
        },
        {
            "position_id": "p-0002",
            "argument": "Ideological power did not decline after the Reformation.",
            "size": 2,
            "sources": [HALL, MANN],
            "authors": ["Mann", "Hall"],
            "chunk_ids": [MANN_NOTE, HALL_OPPOSING_NOTE],
        },
    ]
    (map_dir / "positions.jsonl").write_text(
        "\n".join(json.dumps(position) for position in positions), encoding="utf-8"
    )
    return map_dir


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[Path, Path]:
    """`(vault_dir, names_dir)` -- prose notes, rendered name pages, a real
    note store and a real name layer."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_prose(vault_dir)
    _write_name_pages(vault_dir)
    _write_store(vault_dir)
    _write_name_layer(names_dir)
    return vault_dir, names_dir


@pytest.fixture
def storeless(tmp_path: Path) -> tuple[Path, Path]:
    """The same corpus rendered as name pages ONLY -- a vault materialized
    before the store existed."""
    vault_dir = tmp_path / "storeless-vault"
    names_dir = tmp_path / "storeless-names"
    _write_prose(vault_dir)
    _write_name_pages(vault_dir)
    _write_name_layer(names_dir)
    return vault_dir, names_dir


def _brief() -> Brief:
    return Brief(
        brief_id="test-brief-650",
        case="the state",
        request="What do these authors disagree about when they write about the state?",
        lens=None,
    )


def _interrogation_result() -> InterrogationResult:
    premises_found = [
        PremiseAssessment(premise="The corpus covers theories of state power.", assessment="silent")
    ]
    bounds_applied = ["Covers social-power theory, not policy."]
    return InterrogationResult(
        premises_found=premises_found,
        bounds_applied=bounds_applied,
        refusal=None,
        disposition=disposition_for(premises_found, bounds_applied, refusal=None),
    )


def _walk(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict[str, Any] | None],
    vault_dir: Path,
    names_dir: Path,
    *,
    map_dir: Path | None = None,
    fork_constraint: ForkConstraint | None = None,
):
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps([*calls, None]))
    return run_planned_retrieval(
        StubLLMClient(),
        _brief(),
        _interrogation_result(),
        vault_dir=vault_dir,
        names_dir=names_dir,
        map_dir=map_dir,
        step_budget=10,
        thin_result_floor=1,
        fork_constraint=fork_constraint,
    )


# ---------------------------------------------------------------------------
# Q1 -- positions on X held by authors who disagree with Y
# ---------------------------------------------------------------------------


def test_a_concept_filtered_by_who_its_authors_argue_against(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [
            {"tool": "get_name", "args": {"canonical": THE_STATE}},
            {"tool": "find_notes", "args": {"about": THE_STATE, "opposing": "Mann"}},
        ],
        vault_dir,
        names_dir,
    )
    page_read, filtered = result.trajectory

    # The old surface: every note that mentions the state, from all three
    # sources, with nothing about who their authors argue with.
    assert sorted(page_read["result_ids"]) == sorted(
        [MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE]
    )
    # The chained query: only the source that argues against Mann survives.
    assert filtered["result_ids"] == [HALL_STATE_NOTE]
    assert filtered["total"] == 1
    # The note's own stated position is what the question asked for, and it
    # reaches the model in the tool's detail.
    assert "a historical-sociological account of state power" in filtered["detail"]
    # `opposing` resolved "Mann" through the alias map with no find_names
    # call in front of it -- a name is a filter argument, not a destination.
    assert not any(entry["tool"] == "find_names" for entry in result.trajectory)


# ---------------------------------------------------------------------------
# Q2 -- claims about X made only by sources published after (or before) Z
# ---------------------------------------------------------------------------


def test_a_concept_filtered_by_publication_year(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [
            {"tool": "find_notes", "args": {"about": THE_STATE, "published_after": 2000}},
            {"tool": "find_notes", "args": {"about": THE_STATE, "published_before": 2000}},
        ],
        vault_dir,
        names_dir,
    )
    after, before = result.trajectory

    assert sorted(after["result_ids"]) == sorted([MANN_STATE_NOTE, HALL_STATE_NOTE])
    assert before["result_ids"] == [SMITH_STATE_NOTE]
    # A window spread across the two sources it spans, not a prefix of one.
    assert "2 notes across 2 sources" in after["detail"]


# ---------------------------------------------------------------------------
# Q3 -- names co-occurring in the notes that argue against the same target
# ---------------------------------------------------------------------------


def test_co_occurrence_conditioned_on_an_opposition(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [
            {"tool": "name_neighbors", "args": {"canonical": MICHAEL_MANN}},
            {"tool": "names_arguing_against", "args": {"target": MICHAEL_MANN}},
        ],
        vault_dir,
        names_dir,
    )
    corpus_wide, conditioned = result.trajectory

    # The old surface: co-occurrence over the whole corpus, which for Mann is
    # whatever Mann's own book happens to discuss alongside him.
    assert corpus_wide["result_ids"] == [THE_STATE]
    # The chained query: what the notes that argue AGAINST Mann talk about.
    assert conditioned["result_ids"] == [IEMP]
    assert "note_count=1" in conditioned["detail"]
    # Names are not passages: nothing here reaches the evidence set.
    assert IEMP not in result.evidence_ids


# ---------------------------------------------------------------------------
# The opposition edge itself
# ---------------------------------------------------------------------------


def test_the_cross_source_opposition_edge_is_directly_retrievable(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [{"tool": "opposition_pairs", "args": {"canonical": MICHAEL_MANN}}],
        vault_dir,
        names_dir,
    )
    (pairs,) = result.trajectory

    # Both ends of the edge, and both are real citable notes.
    assert pairs["result_ids"] == [HALL_OPPOSING_NOTE, MANN_NOTE, MANN_STATE_NOTE]
    assert set(pairs["result_ids"]) <= set(result.evidence_ids)
    # The opposing author's own words for what he is arguing against.
    assert OPPOSITION_TARGET in pairs["detail"]
    # Cross-source only: Mann's own two notes are never paired with each
    # other, only with Hall's.
    assert f"{MANN_NOTE} argues against" not in pairs["detail"]


# ---------------------------------------------------------------------------
# A descriptive phrase is what a model actually writes
# ---------------------------------------------------------------------------


def test_a_descriptive_phrase_reaches_the_notes_and_the_result_says_how(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    """The live paired run's defect (issue #650's follow-up): `about`
    resolved through the exact tiers alone, so 25 of 42 steps returned a
    bare `0/0` and one phrase was re-asked six times in a row. The phrase
    now resolves the way `find_names` resolves it, and the result says what
    it looked for -- which is the half an empty result has left."""
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [
            {"tool": "find_notes", "args": {"about": "the state as a cage of social relations"}},
            {"tool": "find_notes", "args": {"about": "zzqqx quorf"}},
        ],
        vault_dir,
        names_dir,
    )
    phrase, unresolvable = result.trajectory

    assert sorted(phrase["result_ids"]) == sorted(
        [MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE]
    )
    assert "'the state as a cage of social relations' resolved to 'the state'" in phrase["detail"]
    # And the honest other half: nothing matched, said as much.
    assert unresolvable["result_ids"] == []
    assert "matched no name this corpus carries" in unresolvable["detail"]
    # Never a find_names turn in front of either -- the phrase IS the query.
    assert not any(entry["tool"] == "find_names" for entry in result.trajectory)


# ---------------------------------------------------------------------------
# The loop keeps its shape
# ---------------------------------------------------------------------------


def test_the_evidence_set_is_still_round_robin_and_a_fork_constraint_still_bites(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    calls = [
        {"tool": "find_notes", "args": {"about": THE_STATE}},
        {"tool": "names_arguing_against", "args": {"target": MICHAEL_MANN}},
    ]

    unconstrained = _walk(monkeypatch, calls, vault_dir, names_dir)
    # One id per source in rotation, sources ascending -- unchanged by #650.
    assert unconstrained.evidence_ids == [HALL_STATE_NOTE, MANN_STATE_NOTE, SMITH_STATE_NOTE]

    constrained = _walk(
        monkeypatch,
        calls,
        vault_dir,
        names_dir,
        fork_constraint=ForkConstraint(
            drop_source_ids=frozenset({MANN}), per_source_cap=None, guidance="background only"
        ),
    )
    assert constrained.evidence_ids == [HALL_STATE_NOTE, SMITH_STATE_NOTE]


def test_the_same_query_over_the_same_vault_returns_the_same_ids_in_the_same_order(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    calls = [
        {"tool": "find_notes", "args": {"about": THE_STATE, "limit": 2}},
        {"tool": "opposition_pairs", "args": {"canonical": MICHAEL_MANN, "limit": 2}},
    ]
    first = _walk(monkeypatch, calls, vault_dir, names_dir)
    second = _walk(monkeypatch, calls, vault_dir, names_dir)

    assert [entry["result_ids"] for entry in first.trajectory] == [
        entry["result_ids"] for entry in second.trajectory
    ]
    # A capped window spans every source rather than collapsing onto
    # whichever source_id sorts first. Since issue #802 that means all three
    # books here, not two: `limit=2` over three sources used to drop the
    # alphabetically last one silently, which is how `tilly-1978` reached
    # zero of 19 analysis records on the live corpus.
    assert len({chunk_id.split("_")[0] for chunk_id in first.trajectory[0]["result_ids"]}) == 3


# ---------------------------------------------------------------------------
# A vault with no store still answers
# ---------------------------------------------------------------------------


def test_a_vault_with_no_store_still_answers_from_its_name_pages(
    storeless: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = storeless
    result = _walk(
        monkeypatch,
        [
            {"tool": "find_names", "args": {"query": "Mann"}},
            {"tool": "get_name", "args": {"canonical": THE_STATE}},
            {"tool": "find_notes", "args": {"about": THE_STATE}},
            {"tool": "opposition_pairs", "args": {"canonical": MICHAEL_MANN}},
        ],
        vault_dir,
        names_dir,
    )
    resolution, page_read, notes, pairs = result.trajectory

    assert resolution["result_ids"] == [MICHAEL_MANN]
    assert sorted(page_read["result_ids"]) == sorted(
        [MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE]
    )
    # The store-backed tools report honest emptiness -- no raise, no error.
    assert notes["result_ids"] == [] and notes["total"] == 0
    assert pairs["result_ids"] == []
    assert page_read["result_ids"], "the page-fallback path still assembles evidence"


# ---------------------------------------------------------------------------
# The argument map's positions as a retrieval target
# ---------------------------------------------------------------------------


def test_argument_map_positions_are_retrievable_by_name(
    fixture: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    map_dir = _write_map(tmp_path / "map" / "fixture-pin")

    result = _walk(
        monkeypatch,
        [{"tool": "positions_on", "args": {"name": THE_STATE}}],
        vault_dir,
        names_dir,
        map_dir=map_dir,
    )
    (positions,) = result.trajectory

    # Only the position whose passages carry the name; its own argument
    # sentence is what the model reads, which no name page carries.
    assert "The state is a container of social relations" in positions["detail"]
    assert "Ideological power did not decline" not in positions["detail"]
    assert sorted(positions["result_ids"]) == sorted(
        [MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE]
    )
    assert set(positions["result_ids"]) <= set(result.evidence_ids)


def test_a_corpus_with_no_argument_map_runs_the_same_loop(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [
            {"tool": "positions_on", "args": {"name": THE_STATE}},
            {"tool": "find_notes", "args": {"about": THE_STATE}},
        ],
        vault_dir,
        names_dir,
        map_dir=None,
    )
    positions, notes = result.trajectory

    assert positions["result_ids"] == [] and positions["total"] == 0
    assert notes["result_ids"], "the rest of the walk is unaffected"


# ---------------------------------------------------------------------------
# What the run leaned on is still measurable when nothing it called was a
# name-layer tool (issue #650's second follow-up)
# ---------------------------------------------------------------------------


def _claims_grounded_in(*chunk_ids: str, names_touched: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": "c-1",
            "text": "These authors disagree about what a state is.",
            "kind": "b",
            "grounds": [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids],
            "confidence": "medium",
            "names_touched": names_touched,
        }
    ]


def test_a_relational_only_walk_is_still_measured_for_coverage_and_usage(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    """The defect the first re-run exposed: the relational tools resolve
    their own name argument, so nothing on the trajectory carried a
    canonical, and §7.7's map -- which reads the trajectory for the names a
    run retrieved on -- collapsed. Across three hard briefs it fell from
    11/5/8 entries to 2/0/1: one brief composed 23 notes and made 18 claims
    and its record said `not_measured`; another reported `high` off a single
    name. A confident band computed from a near-empty map is worse than an
    honest `not_measured`, and both are worse than measuring what the run
    actually leaned on."""
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [
            # A phrase, not a canonical -- what a model actually writes.
            {"tool": "find_notes", "args": {"about": "the state as a cage of social relations"}},
            {"tool": "opposition_pairs", "args": {"canonical": "Mann"}},
        ],
        vault_dir,
        names_dir,
    )
    assert not any(
        entry["tool"] in {"find_names", "get_name", "where_names_meet"}
        for entry in result.trajectory
    ), "this walk touches no name-layer tool at all"

    claims = _claims_grounded_in(
        HALL_STATE_NOTE, MANN_NOTE, names_touched=[THE_STATE, MICHAEL_MANN]
    )
    coverage_map = compute_coverage_map(claims, trajectory=result.trajectory, vault_dir=vault_dir)

    # The map measures both names the walk resolved, at their real corpus
    # counts and this run's own evidence -- not the phrases that reached them.
    assert set(coverage_map) == {THE_STATE, MICHAEL_MANN}
    assert coverage_map[THE_STATE]["corpus_note_count"] == 3
    assert coverage_map[THE_STATE]["evidence_note_count"] == 1
    assert compute_confidence(coverage_map)["overall_band"] != NOT_MEASURED_BAND

    # And §7.13 reads the same canonicals: the disclosure says what the run
    # leaned on, and the denominator is each name's own whole page.
    usage = compute_source_usage(
        {
            "trajectory": result.trajectory,
            "claims": claims,
            "interrogation": {"disposition": "answer"},
            "brief": {},
        },
        vault_dir=vault_dir,
    )
    assert usage["names_queried"] == [
        {"tool": "find_notes", "args": {"canonical": THE_STATE}},
        {"tool": "opposition_pairs", "args": {"canonical": MICHAEL_MANN}},
    ]
    assert usage["denominator_by_name"] == {THE_STATE: 3, MICHAEL_MANN: 2}
    assert all(source["available_chunk_count"] is not None for source in usage["sources"])


def test_a_phrase_that_reaches_no_name_is_not_measured_as_one(
    fixture: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    """The other half: an unresolved phrase is not a queried name. A walk
    that only ever wrote words the corpus does not carry has nothing to
    disclose, and `not_measured` is then the honest answer."""
    vault_dir, names_dir = fixture
    result = _walk(
        monkeypatch,
        [{"tool": "find_notes", "args": {"about": "zzqqx quorf"}}],
        vault_dir,
        names_dir,
    )
    claims = _claims_grounded_in(HALL_STATE_NOTE, names_touched=[THE_STATE])

    coverage_map = compute_coverage_map(claims, trajectory=result.trajectory, vault_dir=vault_dir)
    assert coverage_map == {}
    assert compute_confidence(coverage_map)["overall_band"] == NOT_MEASURED_BAND
