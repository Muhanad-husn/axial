"""Acceptance for issue #802: a name query's window never cuts the first
rotation, so every source on the page contributes at least one note.

The defect, measured in `data/logs/2026-08-19-802-tilly-retrieval/`: the
`Charles Tilly` name page draws on 20 sources, `find_notes` truncates at
`limit` (default 10) after spreading one member per source, and groups are
visited in `source_id` ascending order. `tilly-1978` sorts 16th, so the
book the paper argues against never entered any evidence set -- zero
appearances in `source_usage.sources` across all 19 analysis records.

`_round_robin_by_source` (issue #562) fixed the ordering inside a window.
It did not fix selection when the source count exceeds the limit, and there
the rotation degenerates to "the alphabetically first `limit` books".

The fixture is a real note store and real name pages over twelve sources
named `aaa-2001` .. `lll-2012`, all members of one page, queried at the
default limit of ten. `lll-2012` -- the source that sorts last -- stands in
for `tilly-1978`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from axial.paths import name_page_path
from axial.query import store as note_store
from axial.query.names import DEFAULT_LIMIT, get_name
from axial.query.relations import find_notes

# Twelve sources, two more than DEFAULT_LIMIT, so the first rotation cannot
# fit in the window as it stands.
_LETTERS = "abcdefghijkl"
SOURCES = [f"{letter * 3}-{2001 + index}-{letter * 12}" for index, letter in enumerate(_LETTERS)]
LAST_SOURCE = SOURCES[-1]

CROWDED = "a crowded name"
QUIET = "a quiet name"
# Three sources only, comfortably inside the limit: the control that must not
# move at all.
QUIET_SOURCES = SOURCES[:3]


def _notes() -> list[dict[str, Any]]:
    notes = []
    for index, source_id in enumerate(SOURCES):
        names = [CROWDED] + ([QUIET] if source_id in QUIET_SOURCES else [])
        # Two notes per source, so a window that took two from one book
        # before reaching another would be visible as a missing source.
        for ordinal in (1, 2):
            notes.append(
                {
                    "chunk_id": f"{source_id}_{index:03d}_section_{ordinal:03d}",
                    "source_id": source_id,
                    "author": source_id[:3].upper(),
                    "year": 2001 + index,
                    "claim": f"{source_id} says something, note {ordinal}.",
                    "position": "the author's own account",
                    "names": names,
                }
            )
    return notes


NOTES = _notes()


def _render(frontmatter: dict[str, Any], body: str) -> str:
    lines = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    return f"---\n{lines}\n---\n\n{body}"


def _write_name_pages(vault_dir: Path) -> None:
    for canonical in (CROWDED, QUIET):
        members = [note for note in NOTES if canonical in note["names"]]
        member_lines = "\n".join(
            f"- [[{note['chunk_id']}]] — {note['author']} ({note['year']}): {note['claim']}"
            for note in members
        )
        page = f"# {canonical}\n\n**Member notes:**\n{member_lines}\n"
        path = name_page_path(vault_dir, canonical)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _render({"name": canonical, "kind": "concept", "member_count": len(members)}, page),
            encoding="utf-8",
        )


def _write_store(vault_dir: Path) -> None:
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[
            (source_id, source_id[:3].upper(), f"Title {source_id}", str(2001 + index), 2001 + index)
            for index, source_id in enumerate(SOURCES)
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
            for note in NOTES
        ],
        names=[(CROWDED, "concept", CROWDED), (QUIET, "concept", QUIET)],
        note_names=[
            (note["chunk_id"], note["source_id"], name, "concept")
            for note in NOTES
            for name in note["names"]
        ],
        note_arguing_against=[],
        note_citations=[],
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    _write_name_pages(vault_dir)
    _write_store(vault_dir)
    return vault_dir


@pytest.fixture
def vault_without_store(tmp_path: Path) -> Path:
    """A vault materialized before the note store existed. `get_name` falls
    back to parsing the rendered page, which truncates by the same rule."""
    vault_dir = tmp_path / "pages-only"
    vault_dir.mkdir()
    _write_name_pages(vault_dir)
    return vault_dir


def test_find_notes_reaches_the_source_that_sorts_last(vault: Path):
    """The `tilly-1978` case: twelve sources, a limit of ten, and the book
    the argument is against sorting past the cut."""
    rows, total, _ = find_notes(CROWDED, vault_dir=vault, names_dir=vault)

    assert total == len(NOTES)
    returned = {row.source_id for row in rows}
    assert LAST_SOURCE in returned
    assert returned == set(SOURCES)


def test_every_source_contributes_exactly_once_at_the_default_limit(vault: Path):
    """One rotation, not two: the window is raised to cover every source and
    no further, so no book gets a second note while another has none."""
    rows, _, _ = find_notes(CROWDED, vault_dir=vault, names_dir=vault)

    assert len(rows) == len(SOURCES)
    assert sorted(row.source_id for row in rows) == sorted(SOURCES)


def test_a_page_inside_the_limit_is_untouched(vault: Path):
    """The control. Three sources, six notes, a limit of ten — the window
    already covered every source, so nothing about this result may move.

    `find_notes` rotates whatever it returns, so the order is one note per
    source per round (`aaa`, `bbb`, `ccc`, then each source's second), and
    that is what must be unchanged."""
    rows, total, _ = find_notes(QUIET, vault_dir=vault, names_dir=vault)

    quiet_notes = [note for note in NOTES if QUIET in note["names"]]
    rotated = [
        note["chunk_id"]
        for ordinal in (1, 2)
        for source_id in QUIET_SOURCES
        for note in quiet_notes
        if note["source_id"] == source_id and note["chunk_id"].endswith(f"_{ordinal:03d}")
    ]
    assert total == 6
    assert [row.chunk_id for row in rows] == rotated


def test_an_explicit_limit_below_the_source_count_still_covers_every_source(vault: Path):
    """A caller asking for fewer notes than there are books is asking for
    something the rotation cannot honestly give: a spread across books that
    omits books. Coverage wins, and `total` still reports the truth."""
    rows, total, _ = find_notes(CROWDED, limit=3, vault_dir=vault, names_dir=vault)

    assert total == len(NOTES)
    assert {row.source_id for row in rows} == set(SOURCES)


def test_get_name_covers_every_source_from_the_store(vault: Path):
    page = get_name(CROWDED, vault_dir=vault, names_dir=vault)

    assert {member.source_id for member in page.members} == set(SOURCES)
    assert page.member_count == len(NOTES)


def test_get_name_covers_every_source_from_the_rendered_page(vault_without_store: Path):
    """The fallback path, for a vault materialized before the store existed.
    It truncates by the same rule and must gain the same floor."""
    page = get_name(CROWDED, vault_dir=vault_without_store, names_dir=vault_without_store)

    assert {member.source_id for member in page.members} == set(SOURCES)


def test_get_name_leaves_a_page_inside_the_limit_alone(vault: Path):
    page = get_name(QUIET, vault_dir=vault, names_dir=vault)

    assert [member.chunk_id for member in page.members] == [
        note["chunk_id"] for note in NOTES if QUIET in note["names"]
    ]
    assert len(page.members) == 6 <= DEFAULT_LIMIT


def test_the_window_is_still_bounded(vault: Path):
    """The floor is a floor, not the removal of the limit (issue #505).

    Twelve sources with two notes each is 24 members. A `limit` of 10 raises
    the window to 12 -- one per source -- and stops there. The 962-member
    page that made `limit` necessary still does not come back whole."""
    page = get_name(CROWDED, DEFAULT_LIMIT, vault_dir=vault, names_dir=vault)

    assert len(page.members) == len(SOURCES) == 12
    assert page.member_count == len(NOTES) == 24

    rows, total, _ = find_notes(CROWDED, DEFAULT_LIMIT, vault_dir=vault, names_dir=vault)
    assert len(rows) == 12
    assert total == 24


def test_a_limit_of_zero_still_covers_every_source(vault: Path):
    """`limit=0` is the boundary the floor changes most: it used to return
    nothing, and now returns one note per source. Pinned rather than left to
    be discovered -- a caller using `limit=0` as a cheap way to read `total`
    alone now materialises rows."""
    rows, total, _ = find_notes(CROWDED, 0, vault_dir=vault, names_dir=vault)

    assert total == len(NOTES)
    assert len(rows) == len(SOURCES)


def test_a_page_of_one_book_is_still_cut_at_the_limit(vault: Path):
    """The floor is per SOURCE, never per note. One book's notes are still
    truncated normally -- otherwise `limit` would mean nothing on the pages
    that most need it."""
    single = [note for note in NOTES if note["source_id"] == SOURCES[0]]
    assert len(single) == 2
    rows, _, _ = find_notes(QUIET, 1, vault_dir=vault, names_dir=vault)

    # Three sources on the quiet page, so the floor is 3 -- not 6.
    assert len(rows) == 3
    assert len({row.source_id for row in rows}) == 3
