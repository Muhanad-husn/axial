"""Outer acceptance test for issue #661: front/back-matter chunks are
retrieved, assembled and cited exactly like an ordinary passage, even
though nothing about an acknowledgments page or an endnotes run is
argument. A live run (`data/logs/2026-08-04-intake-fork-649/live/`)
grounded two of seventeen claims -- one of them a cross-source claim --
on an acknowledgments page and an endnotes page, reached through
`get_name` (the store-backed name page) and `query_by_source` (a direct
vault read).

Given a fixture vault whose store carries, alongside two ordinary body
notes, an acknowledgments note and an endnotes note that both name the
same concept and one of which argues against it
When  `find_notes`, `get_name`, `opposition_pairs` and `query_by_source`
      are asked about that concept or that source
Then  the body notes come back every time, and the acknowledgments/
      endnotes notes never do -- not as a member, not as a note, not as
      either end of an opposition edge, and not as one of a source's own
      chunks -- even though the store still carries a `notes` row for
      each of them (materialize never refuses to write one).

See specs/PHASE-B.md §7.5/§7.16 and `axial.back_matter` for the shared
classifier both `axial.gold`'s sampling frame and this filter apply.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.materialize import build_note_store, materialize_names
from axial.query import reader
from axial.query import store as store_module
from axial.query.names import get_name
from axial.query.relations import find_notes, opposition_pairs

ALPHA = "alpha-2020-aaaaaaaaaaaa"
BETA = "beta-2021-bbbbbbbbbbbb"

A_BODY = f"{ALPHA}_000_introduction_001"
A_ACKNOWLEDGMENTS = f"{ALPHA}_001_acknowledgments_001"
A_NOTES = f"{ALPHA}_002_notes_001"
B_BODY = f"{BETA}_000_introduction_001"

SHABBIHA = "Shabbiha"
OPPOSITION_TARGET = "Shabbiha as merely a spontaneous militia with no prior existence"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _answer(chunk_id: str, source_id: str, section: str, **answers) -> dict:
    body = {"claim": "x", "position": None, "arguing_against": [], "names": [], "citations": []}
    body.update(answers)
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": section,
        "pass": "note_interrogate",
        "model": "stub",
        "frame_version": "0.2",
        "answered_at": "2026-01-01T00:00:00Z",
        "answers": body,
    }


def _build_fixture(root: Path) -> None:
    _write_jsonl(
        root / "data" / "answers" / f"{ALPHA}.jsonl",
        [
            _answer(
                A_BODY,
                ALPHA,
                "Introduction",
                claim="The Shabbiha existed before 2011 as smuggler gangs later armed by the state.",
                names=[{"name": SHABBIHA, "kind": "concept"}],
            ),
            # An acknowledgments page: real interrogation answers were still
            # written for it (nothing here refuses to answer it), but it is
            # not argument -- exactly the shape issue #661 was filed on.
            _answer(
                A_ACKNOWLEDGMENTS,
                ALPHA,
                "Acknowledgments",
                claim="I thank my colleagues and the Shabbiha research group for their comments.",
                names=[{"name": SHABBIHA, "kind": "concept"}],
            ),
            # An endnotes page carrying an `arguing_against` answer -- the
            # opposing end of an opposition edge must be excluded too, not
            # only the "about" end `find_notes`/`get_name` already cover.
            _answer(
                A_NOTES,
                ALPHA,
                "Notes",
                claim="See also the sources cited in chapter one.",
                names=[{"name": SHABBIHA, "kind": "concept"}],
                arguing_against=[OPPOSITION_TARGET],
            ),
        ],
    )
    _write_json(
        root / "data" / "source_meta" / f"{ALPHA}.json",
        {
            "author": {"value": "A. Author", "provenance": "title page"},
            "title": {"value": "A Title", "provenance": "embedded metadata"},
            "date": {"value": 2020, "provenance": "embedded metadata"},
        },
    )
    _write_json(root / "data" / "envelopes" / f"{ALPHA}.json", {})

    _write_jsonl(
        root / "data" / "answers" / f"{BETA}.jsonl",
        [
            _answer(
                B_BODY,
                BETA,
                "Introduction",
                claim="The Shabbiha were a pre-existing, state-linked militia network.",
                names=[{"name": SHABBIHA, "kind": "concept"}],
            ),
        ],
    )
    _write_json(
        root / "data" / "source_meta" / f"{BETA}.json",
        {
            "author": {"value": "B. Author", "provenance": "title page"},
            "title": {"value": "B Title", "provenance": "embedded metadata"},
            "date": {"value": 2021, "provenance": "embedded metadata"},
        },
    )
    _write_json(root / "data" / "envelopes" / f"{BETA}.json", {})

    _write_jsonl(
        root / "data" / "names" / "inventory.jsonl",
        [
            {
                "surface": SHABBIHA,
                "kind": "concept",
                "count": 4,
                "chunk_ids": [A_BODY, A_ACKNOWLEDGMENTS, A_NOTES, B_BODY],
            },
        ],
    )
    _write_json(
        root / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [{"canonical": SHABBIHA, "kind": "concept", "aliases": []}],
        },
    )
    _write_json(root / "data" / "names" / "index.json", {"names": [SHABBIHA]})


def _dirs(root: Path) -> dict:
    return {
        "alias_map_path": root / "data" / "names" / "alias_map.json",
        "inventory_path": root / "data" / "names" / "inventory.jsonl",
        "answers_dir": root / "data" / "answers",
        "source_meta_dir": root / "data" / "source_meta",
        "vault_dir": root / "data" / "vault",
    }


def _write_prose_stub(vault_dir: Path, chunk_id: str, section: str) -> None:
    """The minimal frontmatter `query_by_source` reads: `chunk_id` (its own
    `_require`d field) and `section` (the #661 filter's own input). Every
    other `ChunkNote` field only matters to `get_chunk`'s full parse, which
    this test does not exercise."""
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    (prose_dir / f"{chunk_id}.md").write_text(
        f"---\nchunk_id: {chunk_id}\nsection: {section}\n---\nBody.\n", encoding="utf-8"
    )


@pytest.fixture
def corpus(tmp_path: Path) -> dict:
    _build_fixture(tmp_path)
    dirs = _dirs(tmp_path)
    materialize_names(artifacts_dir=tmp_path / "data" / "artifacts", **dirs)
    build_note_store(envelopes_dir=tmp_path / "data" / "envelopes", **dirs)
    vault_dir = dirs["vault_dir"]
    _write_prose_stub(vault_dir, A_BODY, "Introduction")
    _write_prose_stub(vault_dir, A_ACKNOWLEDGMENTS, "Acknowledgments")
    _write_prose_stub(vault_dir, A_NOTES, "Notes")
    return {**dirs, "names_dir": tmp_path / "data" / "names"}


def test_the_store_still_carries_a_row_for_the_back_matter_notes(corpus):
    """Materialize never refuses to write the note itself -- only the
    evidence-facing reads stop returning it."""
    connection = store_module.connect(corpus["vault_dir"])
    try:
        rows = dict(connection.execute("SELECT chunk_id, back_matter FROM notes ORDER BY chunk_id"))
    finally:
        connection.close()
    assert rows[A_BODY] == 0
    assert rows[A_ACKNOWLEDGMENTS] == 1
    assert rows[A_NOTES] == 1
    assert rows[B_BODY] == 0


def test_find_notes_never_returns_the_back_matter_notes(corpus):
    rows, total, resolution = find_notes(
        SHABBIHA, vault_dir=corpus["vault_dir"], names_dir=corpus["names_dir"]
    )
    ids = {row.chunk_id for row in rows}
    assert ids == {A_BODY, B_BODY}
    assert total == 2
    assert resolution.canonical == SHABBIHA


def test_get_name_never_lists_the_back_matter_notes_as_members(corpus):
    page = get_name(SHABBIHA, vault_dir=corpus["vault_dir"], names_dir=corpus["names_dir"])
    ids = {member.chunk_id for member in page.members}
    assert ids == {A_BODY, B_BODY}
    assert page.member_count == 2


def test_opposition_pairs_excludes_an_edge_whose_opposing_note_is_back_matter(corpus):
    """`A_NOTES` (an endnotes page) is the only note that argues against
    `Shabbiha` at all -- before issue #661, this would have paired it with
    `B_BODY` as a real cross-source opposition edge. With the fix, the
    opposing end is filtered and the edge never exists."""
    pairs, chunk_ids, total, _resolution = opposition_pairs(
        SHABBIHA, vault_dir=corpus["vault_dir"], names_dir=corpus["names_dir"]
    )
    assert pairs == []
    assert chunk_ids == []
    assert total == 0


def test_query_by_source_never_returns_the_back_matter_notes(corpus):
    assert reader.query_by_source(ALPHA, vault_dir=corpus["vault_dir"]) == [A_BODY]
