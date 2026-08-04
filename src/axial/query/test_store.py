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


# ---------------------------------------------------------------------------
# `back_matter` (issue #661): `doors`, `concept_sources` and `name_members`
# each filter a back-matter member out, and `doors` must still report a
# canonical whose ONLY members are back matter as a real, empty door rather
# than dropping it as if the store never carried it at all.
# ---------------------------------------------------------------------------


def _write_back_matter_fixture(path: Path) -> None:
    note_store.write_store(
        path,
        sources=[(SOURCE_A, "A. Author", "A Title", "2005", 2005)],
        notes=[
            (f"{SOURCE_A}_000_intro_001", SOURCE_A, "Introduction", None, "real claim", None, 0),
            (
                f"{SOURCE_A}_001_ack_001",
                SOURCE_A,
                "Acknowledgments",
                None,
                "thanks",
                None,
                1,
            ),
            (
                f"{SOURCE_A}_002_ack_002",
                SOURCE_A,
                "Acknowledgments",
                None,
                "more thanks",
                None,
                1,
            ),
        ],
        names=[("Mixed", "concept", "mixed"), ("Only Back Matter", "concept", "only back matter")],
        note_names=[
            (f"{SOURCE_A}_000_intro_001", SOURCE_A, "Mixed", "concept"),
            (f"{SOURCE_A}_001_ack_001", SOURCE_A, "Mixed", "concept"),
            (f"{SOURCE_A}_002_ack_002", SOURCE_A, "Only Back Matter", "concept"),
        ],
        note_arguing_against=[],
        note_citations=[],
    )


def test_name_members_excludes_a_back_matter_note(tmp_path: Path):
    path = tmp_path / "notes.db"
    _write_back_matter_fixture(path)
    connection = note_store.connect(tmp_path)
    try:
        members = note_store.name_members(connection, "Mixed")
    finally:
        connection.close()

    assert [row[0] for row in members] == [f"{SOURCE_A}_000_intro_001"]


def test_doors_counts_only_non_back_matter_members(tmp_path: Path):
    path = tmp_path / "notes.db"
    _write_back_matter_fixture(path)
    connection = note_store.connect(tmp_path)
    try:
        found = note_store.doors(connection, ["Mixed"])
    finally:
        connection.close()

    assert found["Mixed"].member_count == 1
    assert found["Mixed"].source_count == 1


def test_doors_reports_a_canonical_whose_only_members_are_back_matter_as_empty_not_absent(
    tmp_path: Path,
):
    """A `WHERE`-filtered join would drop this canonical from the result
    entirely (every one of its `note_names` rows excluded), indistinguishable
    from a canonical the store never carried. The conditional-aggregate join
    must instead report it: a real door, sitting at zero."""
    path = tmp_path / "notes.db"
    _write_back_matter_fixture(path)
    connection = note_store.connect(tmp_path)
    try:
        found = note_store.doors(connection, ["Only Back Matter"])
    finally:
        connection.close()

    assert "Only Back Matter" in found
    assert found["Only Back Matter"].member_count == 0
    assert found["Only Back Matter"].source_count == 0
    assert found["Only Back Matter"].kind == "concept"


def test_concept_sources_excludes_a_source_whose_only_notes_are_back_matter(tmp_path: Path):
    path = tmp_path / "notes.db"
    _write_back_matter_fixture(path)
    connection = note_store.connect(tmp_path)
    try:
        shares = note_store.concept_sources(connection, "Only Back Matter")
    finally:
        connection.close()

    assert shares == []


# ---------------------------------------------------------------------------
# `note_opposed_position` (issue #651): the semantic residue resolver's
# matched edges, folded in by `axial.materialize.build_note_store`. These
# tests exercise the table and `opposing_notes` directly, at the store
# level -- `axial.test_materialize` covers the fold from a decision log.
# ---------------------------------------------------------------------------


def test_write_store_defaults_note_opposed_position_to_empty(tmp_path: Path):
    """A caller that omits `note_opposed_position` entirely (every existing
    call site before issue #651) still gets a store with the table present
    and empty -- not a missing table, not an error."""
    path = tmp_path / "notes.db"
    _write_fixture_store(path)
    connection = note_store.connect(tmp_path)
    try:
        assert note_store.opposing_notes(connection, "pos-0001") == []
    finally:
        connection.close()


def test_opposing_notes_returns_mode_and_self_referential_unfiltered(tmp_path: Path):
    path = tmp_path / "notes.db"
    note_store.write_store(
        path,
        sources=[(SOURCE_A, "A. Author", "A Title", "2005", 2005)],
        notes=[
            (f"{SOURCE_A}_000_intro_001", SOURCE_A, "Introduction", None, "claim one", None),
            (f"{SOURCE_A}_001_intro_002", SOURCE_A, "Introduction", None, "claim two", None),
        ],
        names=[],
        note_names=[],
        note_arguing_against=[],
        note_citations=[],
        note_opposed_position=[
            (
                f"{SOURCE_A}_000_intro_001",
                SOURCE_A,
                "a paraphrased opposing claim",
                "pos-0001",
                "unblocked",
                0,
            ),
            (
                f"{SOURCE_A}_001_intro_002",
                SOURCE_A,
                "a same-book opposing claim",
                "pos-0001",
                "blocked",
                1,
            ),
        ],
    )
    connection = note_store.connect(tmp_path)
    try:
        rows = note_store.opposing_notes(connection, "pos-0001")
        absent = note_store.opposing_notes(connection, "pos-9999")
    finally:
        connection.close()

    assert rows == [
        (f"{SOURCE_A}_000_intro_001", SOURCE_A, "a paraphrased opposing claim", "unblocked", 0),
        (f"{SOURCE_A}_001_intro_002", SOURCE_A, "a same-book opposing claim", "blocked", 1),
    ]
    assert absent == []
