"""Inner unit tests for `axial.query.relations` (issue #650): the three
chained queries the door layer cannot express, plus the cross-source
opposition edge itself, over a real fixture store with real SQL.

The fixture is the smallest corpus that makes each join falsifiable:

- `mann-2012` names `the state` on two notes and is the source everyone
  argues with;
- `hall-2006` (2006) names `the state` AND argues against `Michael Mann`;
- `smith-1999` (1999) names `the state`, argues against nobody, and exists
  only so a year filter and an `opposing` filter each have something to
  exclude.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.query import relations
from axial.query import store as note_store

MANN = "mann-2012-aaaaaaaaaaaa"
HALL = "hall-2006-bbbbbbbbbbbb"
SMITH = "smith-1999-cccccccccccc"

MANN_NOTE = f"{MANN}_000_intro_001"
MANN_STATE_NOTE = f"{MANN}_001_intro_002"
HALL_STATE_NOTE = f"{HALL}_000_intro_001"
HALL_OPPOSING_NOTE = f"{HALL}_001_intro_002"
SMITH_STATE_NOTE = f"{SMITH}_000_intro_001"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "vault"
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[
            (MANN, "Mann", "The Sources of Social Power", "2012", 2012),
            (HALL, "Hall", "An Anatomy of Power", "2006", 2006),
            (SMITH, "Smith", "Nations and Nationalism", "1999", 1999),
        ],
        notes=[
            (MANN_NOTE, MANN, "Introduction", None, "Ideological power declined.", "Mann's own"),
            (MANN_STATE_NOTE, MANN, "Two", None, "The state is a cage.", "Mann's own"),
            (HALL_STATE_NOTE, HALL, "One", None, "The state is a bargain.", "historical-soc"),
            (HALL_OPPOSING_NOTE, HALL, "Two", None, "The decline does not follow.", "Hall's own"),
            (SMITH_STATE_NOTE, SMITH, "One", None, "The state is ethnic.", "ethno-symbolic"),
        ],
        names=[
            ("Michael Mann", "person", "michael mann"),
            ("the state", "concept", "the state"),
            ("IEMP model", "concept", "iemp model"),
        ],
        note_names=[
            (MANN_NOTE, MANN, "Michael Mann", "person"),
            (MANN_STATE_NOTE, MANN, "the state", "concept"),
            (MANN_STATE_NOTE, MANN, "Michael Mann", "person"),
            (HALL_STATE_NOTE, HALL, "the state", "concept"),
            (HALL_OPPOSING_NOTE, HALL, "IEMP model", "concept"),
            (SMITH_STATE_NOTE, SMITH, "the state", "concept"),
        ],
        note_arguing_against=[
            (HALL_OPPOSING_NOTE, HALL, "Mann's conclusion about ideological power", "Michael Mann"),
            (HALL_OPPOSING_NOTE, HALL, "a prose target naming nobody", None),
        ],
        note_citations=[],
    )
    return vault_dir


def test_find_notes_filters_a_concept_by_who_its_authors_argue_against(vault: Path):
    """Q1, the join the door layer cannot make: `the state` alone reaches
    three sources; only Hall argues against Mann, so only Hall's own note on
    the state survives the filter."""
    unfiltered, unfiltered_total, _ = relations.find_notes("the state", vault_dir=vault)
    assert unfiltered_total == 3

    rows, total, _ = relations.find_notes("the state", opposing="Michael Mann", vault_dir=vault)

    assert [row.chunk_id for row in rows] == [HALL_STATE_NOTE]
    assert total == 1
    assert rows[0].position == "historical-soc"
    assert rows[0].year == 2006


def test_find_notes_answers_a_descriptive_phrase_the_exact_tiers_miss(vault: Path):
    """The defect the live paired run measured (issue #650's follow-up): a
    model writes a phrase, not a canonical. `the modern state and war`
    matches no canonical, no alias and no fold, so the exact-only resolver
    fell through to the raw surface and matched no `note_names` row at all
    -- a bare `0/0`, 25 times in 42 steps. The same tiers `find_names` uses
    reach the door the phrase is actually about."""
    rows, total, resolution = relations.find_notes("the modern state and war", vault_dir=vault)

    assert resolution.canonical == "the state"
    assert resolution.tier == "word", "resolved by the compound-word route, not an exact tier"
    assert total == 3
    assert {row.chunk_id for row in rows} == {MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE}


def test_a_phrase_nothing_resolves_says_so_rather_than_answering_silently(vault: Path):
    """The honest other half: a phrase no route reaches is still queried
    verbatim (so a store with no name layer beside it keeps working) and the
    resolution says it never became a name, which is what an empty result
    has left to report."""
    rows, total, resolution = relations.find_notes("zzqqx quorf", vault_dir=vault)

    assert (rows, total) == ([], 0)
    assert resolution.resolved is False
    assert resolution.tier is None
    assert resolution.canonical == "zzqqx quorf"
    assert resolution.slate == ()


def test_positions_and_pairs_resolve_a_phrase_the_same_way(vault: Path):
    """One resolver, not one per tool: the same phrase reaches the same
    canonical through the co-occurrence and join-key entry points."""
    _rows, _total, co_occurrence = relations.names_arguing_against(
        "what Mann concluded", vault_dir=vault
    )
    ids, join_key = relations.chunk_ids_for_name("the modern state and war", vault_dir=vault)

    assert co_occurrence.canonical == "Michael Mann"
    assert join_key.canonical == "the state"
    assert ids == {MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE}


def test_find_notes_filters_a_concept_by_publication_year(vault: Path):
    """Q2: a name page carries no publication date at all, so "claims about
    X made only by sources published after Z" had no answer on that
    surface."""
    after, after_total, _ = relations.find_notes("the state", published_after=2000, vault_dir=vault)
    assert {row.source_id for row in after} == {MANN, HALL}
    assert after_total == 2

    before, before_total, _ = relations.find_notes(
        "the state", published_before=2000, vault_dir=vault
    )
    assert [row.chunk_id for row in before] == [SMITH_STATE_NOTE]
    assert before_total == 1

    window, _total, _resolution = relations.find_notes(
        "the state", published_after=2000, published_before=2010, vault_dir=vault
    )
    assert [row.chunk_id for row in window] == [HALL_STATE_NOTE]


def test_find_notes_spreads_a_truncated_window_across_sources(vault: Path):
    """The §7.5 rotation rule: `chunk_id` ascending IS alphabetical by
    source, so a `limit` of 2 over three sources must reach two different
    books, never two notes of whichever book sorts first."""
    rows, total, _ = relations.find_notes("the state", 2, vault_dir=vault)
    assert total == 3
    assert len({row.source_id for row in rows}) == 2
    # Deterministic: same query, same pinned store, same ids in the same order.
    again, _total, _resolution = relations.find_notes("the state", 2, vault_dir=vault)
    assert [row.chunk_id for row in rows] == [row.chunk_id for row in again]


def test_names_arguing_against_conditions_co_occurrence_on_the_opposition(vault: Path):
    """Q3: `name_neighbors` computes co-occurrence over the whole corpus and
    cannot condition it on a third relation. Here the only note arguing
    against Mann also names the `IEMP model`, and nothing else does."""
    rows, total, _ = relations.names_arguing_against("Michael Mann", vault_dir=vault)

    assert [row.canonical for row in rows] == ["IEMP model"]
    assert rows[0].note_count == 1
    assert rows[0].source_count == 1
    assert total == 1
    # `the state` co-occurs with Mann corpus-wide but not inside the
    # opposition set, so conditioning is doing real work.
    assert "the state" not in {row.canonical for row in rows}


def test_opposition_pairs_returns_both_ends_of_a_cross_source_edge(vault: Path):
    pairs, ids, total, _ = relations.opposition_pairs("Michael Mann", vault_dir=vault)

    assert [(p.opposing_chunk_id, p.about_chunk_id) for p in pairs] == [
        (HALL_OPPOSING_NOTE, MANN_NOTE),
        (HALL_OPPOSING_NOTE, MANN_STATE_NOTE),
    ]
    assert pairs[0].target == "Mann's conclusion about ideological power"
    assert ids == [HALL_OPPOSING_NOTE, MANN_NOTE, MANN_STATE_NOTE]
    assert total == 3


def test_opposition_pairs_never_pairs_a_source_with_itself(vault: Path):
    """`Michael Mann` is named by Mann's own notes, and Mann's own book does
    not argue against itself -- the cross-source rule is what makes a pair a
    disagreement rather than a self-reference."""
    pairs, _ids, _total, _ = relations.opposition_pairs("Michael Mann", vault_dir=vault)
    assert all(pair.opposing_source_id != pair.about_source_id for pair in pairs)


def test_opposition_pairs_bounds_returned_ids_by_limit_and_states_the_true_total(vault: Path):
    _pairs, ids, total, _ = relations.opposition_pairs("Michael Mann", 2, vault_dir=vault)
    assert len(ids) == 2
    assert total == 3


def test_a_vault_with_no_store_answers_empty_rather_than_raising(tmp_path: Path):
    """A vault materialized before the store existed: the name-page tools
    keep answering from the pages, and these report honest emptiness."""
    bare = tmp_path / "bare-vault"
    bare.mkdir()
    assert relations.find_notes("the state", vault_dir=bare) == ([], 0, None)
    assert relations.names_arguing_against("Michael Mann", vault_dir=bare) == ([], 0, None)
    assert relations.opposition_pairs("Michael Mann", vault_dir=bare) == ([], [], 0, None)
    assert relations.chunk_ids_for_name("the state", vault_dir=bare) == (set(), None)


def test_a_name_the_store_does_not_carry_is_an_empty_answer_not_an_error(vault: Path):
    rows, total, resolution = relations.find_notes("zzqqx nonexistent", vault_dir=vault)
    assert (rows, total) == ([], 0)
    assert not resolution.resolved
    assert relations.names_arguing_against("zzqqx nonexistent", vault_dir=vault)[:2] == ([], 0)


def test_chunk_ids_for_name_is_the_join_key_the_argument_map_intersects(vault: Path):
    ids, resolution = relations.chunk_ids_for_name("the state", vault_dir=vault)
    assert ids == {MANN_STATE_NOTE, HALL_STATE_NOTE, SMITH_STATE_NOTE}
    assert resolution.canonical == "the state"
