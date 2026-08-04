"""Inner unit tests for `axial.query.store`'s `concept_sources` (issue #649:
the intake fork-check's own per-source breakdown, over the note store
`materialize.build_note_store` already writes -- see that module's own
acceptance test, `tests/analysis/test_relational_store.py`, for the store's
whole-pipeline contract)."""

from __future__ import annotations

from pathlib import Path

from axial.query import store as note_store

SOURCE_A = "alpha-2005-aaaaaaaaaaaa"
SOURCE_B = "beta-2019-bbbbbbbbbbbb"


def _write_fixture_store(path: Path) -> None:
    note_store.write_store(
        path,
        sources=[
            (SOURCE_A, "A. Author", "A Title", "2005", 2005),
            (SOURCE_B, "B. Author", "B Title", "2019", 2019),
        ],
        notes=[
            (f"{SOURCE_A}_000_intro_001", SOURCE_A, "Introduction", None, "claim one", None),
            (f"{SOURCE_A}_001_intro_002", SOURCE_A, "Introduction", None, "claim two", None),
            (f"{SOURCE_B}_000_intro_001", SOURCE_B, "Introduction", None, "claim three", None),
        ],
        names=[("Syria", "place", "syria")],
        note_names=[
            (f"{SOURCE_A}_000_intro_001", SOURCE_A, "Syria", "place"),
            (f"{SOURCE_A}_001_intro_002", SOURCE_A, "Syria", "place"),
            (f"{SOURCE_B}_000_intro_001", SOURCE_B, "Syria", "place"),
        ],
        note_arguing_against=[],
        note_citations=[],
    )


def test_concept_sources_ranks_by_note_count_descending(tmp_path: Path):
    path = tmp_path / "notes.db"
    _write_fixture_store(path)
    connection = note_store.connect(tmp_path)
    try:
        shares = note_store.concept_sources(connection, "Syria")
    finally:
        connection.close()

    assert [s.source_id for s in shares] == [SOURCE_A, SOURCE_B]
    assert shares[0].note_count == 2
    assert shares[0].author == "A. Author"
    assert shares[0].year == 2005
    assert shares[1].note_count == 1
    assert shares[1].year == 2019


def test_concept_sources_empty_for_a_canonical_with_no_member(tmp_path: Path):
    path = tmp_path / "notes.db"
    _write_fixture_store(path)
    connection = note_store.connect(tmp_path)
    try:
        shares = note_store.concept_sources(connection, "Nobody Home")
    finally:
        connection.close()

    assert shares == []
