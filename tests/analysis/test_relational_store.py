"""The relational store over the notes and their typed relations (DEC-62,
issue #648).

Two contracts, both acceptance-level:

1. **The store holds the graph the interrogation produced** -- notes, the
   names each note carries, the free-text `arguing_against` target with the
   canonical it resolves to (conservative, >=2-token phrase containment),
   citations, and the sources with their publication year -- so a caller can
   chain two relations in one query, which no tool over the flat name-page
   layer can do.
2. **`find_names` and `get_name` answered from the store are byte-identical
   to the same calls answered from the name pages.** The store subsumes the
   door layer; it does not change what it says.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from axial.materialize import build_note_store, materialize_names
from axial.query import store as store_module
from axial.query.names import find_names, get_name

# ---------------------------------------------------------------------------
# Fixture corpus: three author-year sources that meet at `Ernest Gellner`
# ---------------------------------------------------------------------------

ALPHA = "alpha-1999-aaaaaaaaaaaa"
BETA = "beta-2005-bbbbbbbbbbbb"
MANN = "mann-v1-2012-cccccccccccc"

A_NOTE = f"{ALPHA}_000_intro_001"
A_NOTE_2 = f"{ALPHA}_001_intro_002"
B_NOTE = f"{BETA}_000_intro_001"
M_NOTE = f"{MANN}_000_intro_001"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _answer(chunk_id: str, source_id: str, **answers) -> dict:
    body = {
        "claim": "x",
        "position": None,
        "arguing_against": [],
        "names": [],
        "citations": [],
    }
    body.update(answers)
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": "Introduction",
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
                A_NOTE,
                ALPHA,
                claim="Nationalism is a modern industrial artefact.",
                position="the modernist school",
                arguing_against=[
                    "the modernist account Ernest Gellner gives of nationalism",
                    "the notion that every rule of thumb settles the matter",
                ],
                names=[
                    {"name": "Ernest Gellner", "kind": "person"},
                    {"name": "the state", "kind": "concept"},
                ],
                citations=[
                    {"cited": "Nations and Nationalism", "stance": "foil", "about": "modernism"}
                ],
            ),
            _answer(
                A_NOTE_2,
                ALPHA,
                # Trailing whitespace on purpose: the name page's reader
                # strips the whole member line, so the store has to say the
                # same thing (10 real claims carry it).
                claim="A second passage from the same book. ",
                names=[{"name": "Ernest Gellner", "kind": "person"}],
            ),
        ],
    )
    _write_json(
        root / "data" / "source_meta" / f"{ALPHA}.json",
        {
            "author": {"value": "Anthony D. Smith", "provenance": "title page"},
            "title": {"value": "Ethno-symbolism", "provenance": "embedded metadata"},
            "date": {"value": 1999, "provenance": "embedded metadata"},
        },
    )

    _write_jsonl(
        root / "data" / "answers" / f"{BETA}.jsonl",
        [
            _answer(
                B_NOTE,
                BETA,
                claim="Nations rest on pre-modern ethnic cores.",
                position="not-in-passage",
                names=[
                    {"name": "Ernest Gellner", "kind": "person"},
                    {"name": "French Mandate", "kind": "period"},
                ],
            )
        ],
    )
    _write_json(
        root / "data" / "source_meta" / f"{BETA}.json",
        {
            "author": {"value": "John Hall", "provenance": "title page"},
            "title": {"value": "Powers", "provenance": "embedded metadata"},
            "date": {"value": 2005, "provenance": "embedded metadata"},
        },
    )

    _write_jsonl(
        root / "data" / "answers" / f"{MANN}.jsonl",
        [
            _answer(
                M_NOTE,
                MANN,
                claim="not-in-passage",
                names=[
                    {"name": "Rule", "kind": "concept"},
                    {"name": "French Mandate", "kind": "period"},
                ],
            )
        ],
    )
    _write_json(
        root / "data" / "source_meta" / f"{MANN}.json",
        {
            "author": {"value": "Michael Mann", "provenance": "title page"},
            "title": {"value": "The Sources of Social Power", "provenance": "title page"},
            "date": {"value": 2012, "provenance": "embedded metadata"},
        },
    )

    _write_jsonl(
        root / "data" / "names" / "inventory.jsonl",
        [
            {
                "surface": "Ernest Gellner",
                "kind": "person",
                "count": 3,
                "chunk_ids": [A_NOTE, A_NOTE_2, B_NOTE],
            },
            {"surface": "the state", "kind": "concept", "count": 1, "chunk_ids": [A_NOTE]},
            {
                "surface": "French Mandate",
                "kind": "period",
                "count": 2,
                "chunk_ids": [B_NOTE, M_NOTE],
            },
            {"surface": "Rule", "kind": "concept", "count": 1, "chunk_ids": [M_NOTE]},
        ],
    )
    _write_json(
        root / "data" / "names" / "alias_map.json",
        {
            "version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [
                {"canonical": "Ernest Gellner", "kind": "person", "aliases": ["Gellner"]},
                {"canonical": "the state", "kind": "concept", "aliases": []},
                {"canonical": "French Mandate", "kind": "period", "aliases": []},
                {"canonical": "Rule", "kind": "concept", "aliases": []},
            ],
        },
    )
    _write_json(
        root / "data" / "names" / "index.json",
        {"names": ["Ernest Gellner", "the state", "French Mandate", "Rule"]},
    )


def _dirs(root: Path) -> dict:
    return {
        "alias_map_path": root / "data" / "names" / "alias_map.json",
        "inventory_path": root / "data" / "names" / "inventory.jsonl",
        "answers_dir": root / "data" / "answers",
        "source_meta_dir": root / "data" / "source_meta",
        "vault_dir": root / "data" / "vault",
    }


@pytest.fixture
def corpus(tmp_path: Path) -> dict:
    """A materialized fixture vault -- name pages, the door index, and the
    store -- plus its own name layer."""
    _build_fixture(tmp_path)
    dirs = _dirs(tmp_path)
    materialize_names(artifacts_dir=tmp_path / "data" / "artifacts", **dirs)
    build_note_store(**dirs)
    return {
        **dirs,
        "root": tmp_path,
        "names_dir": tmp_path / "data" / "names",
    }


def _query(corpus: dict, sql: str, *parameters):
    connection = store_module.connect(corpus["vault_dir"])
    assert connection is not None
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 1. The store holds the graph
# ---------------------------------------------------------------------------


def test_a_source_carries_its_publication_year_parsed_from_its_id(corpus):
    rows = {
        row[0]: (row[1], row[2])
        for row in _query(corpus, "SELECT source_id, author, year FROM sources")
    }
    assert rows[ALPHA] == ("Anthony D. Smith", 1999)
    assert rows[BETA] == ("John Hall", 2005)
    # A volume token between the author and the year does not hide the year.
    assert rows[MANN] == ("Michael Mann", 2012)


def test_a_note_carries_its_claim_its_position_and_the_names_it_names(corpus):
    (row,) = _query(
        corpus, "SELECT source_id, claim, position FROM notes WHERE chunk_id = ?", A_NOTE
    )
    assert row[0] == ALPHA
    assert row[1] == "Nationalism is a modern industrial artefact."
    assert row[2] == "the modernist school"

    names = _query(
        corpus,
        "SELECT canonical, kind FROM note_names WHERE chunk_id = ? ORDER BY canonical",
        A_NOTE,
    )
    assert [tuple(row) for row in names] == [("Ernest Gellner", "person"), ("the state", "concept")]


def test_a_citation_keeps_the_stance_and_the_about_clause(corpus):
    rows = _query(
        corpus, "SELECT cited, stance, about FROM note_citations WHERE chunk_id = ?", A_NOTE
    )
    assert [tuple(row) for row in rows] == [("Nations and Nationalism", "foil", "modernism")]


def test_a_target_resolves_on_a_two_token_phrase_and_never_on_a_single_word(corpus):
    """The conservative join measured in
    `data/logs/2026-08-04-relational-join-ceiling/`: a name of two or more
    tokens found as a whole-word phrase inside the target text resolves; a
    single-token canonical (`Rule`) inside "every rule of thumb" does not,
    because that match is NER noise, not an opposition."""
    rows = _query(
        corpus,
        "SELECT target, resolved_canonical FROM note_arguing_against "
        "WHERE chunk_id = ? ORDER BY target, resolved_canonical",
        A_NOTE,
    )
    assert [tuple(row) for row in rows] == [
        ("the modernist account Ernest Gellner gives of nationalism", "Ernest Gellner"),
        ("the notion that every rule of thumb settles the matter", None),
    ]


def test_an_opposition_pair_joins_two_notes_across_sources(corpus):
    """The query the flat layer cannot answer: every note in another source
    whose own names carry what this note argues against."""
    rows = _query(
        corpus,
        """
        SELECT DISTINCT aa.chunk_id, nn.chunk_id, nn.canonical
        FROM note_arguing_against aa
        JOIN note_names nn ON nn.canonical = aa.resolved_canonical
        JOIN notes a ON a.chunk_id = aa.chunk_id
        JOIN notes b ON b.chunk_id = nn.chunk_id
        WHERE a.source_id != b.source_id
        ORDER BY aa.chunk_id, nn.chunk_id
        """,
    )
    assert [tuple(row) for row in rows] == [(A_NOTE, B_NOTE, "Ernest Gellner")]


def test_claims_about_a_name_can_be_filtered_by_publication_year(corpus):
    """Measurement §3 Q2 -- `get_name` carries no publication date at all, so
    this question has no answer over the name pages."""
    rows = _query(
        corpus,
        """
        SELECT n.chunk_id
        FROM notes n
        JOIN note_names nn ON nn.chunk_id = n.chunk_id AND nn.canonical = 'French Mandate'
        JOIN sources s ON s.source_id = n.source_id
        WHERE s.year > 2010
        """,
    )
    assert [row[0] for row in rows] == [M_NOTE]


def test_rebuilding_the_store_replaces_it_and_leaves_no_partial_file(corpus):
    path = store_module.store_path(corpus["vault_dir"])
    before = path.stat().st_mtime_ns
    build_note_store(**{key: corpus[key] for key in _dirs(corpus["root"])})
    assert path.is_file()
    assert not [item for item in path.parent.iterdir() if item.name.endswith(".tmp")]
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 4
    finally:
        connection.close()
    assert path.stat().st_mtime_ns >= before


# ---------------------------------------------------------------------------
# 2. The store subsumes the door layer without changing what it says
# ---------------------------------------------------------------------------


@pytest.fixture
def pages_only(corpus, tmp_path_factory) -> Path:
    """The same vault with the store removed, so the same call is answered
    from the name pages and their door index instead."""
    destination = tmp_path_factory.mktemp("pages-only") / "vault"
    shutil.copytree(corpus["vault_dir"], destination)
    store_module.store_path(destination).unlink()
    return destination


@pytest.mark.parametrize(
    "query",
    [
        "Ernest Gellner",  # exact
        "Gellner",  # alias
        "ernest  gellner",  # folded
        "Mandate",  # contains: reaches `French Mandate`
        "mandate-era institutions Gellner",  # the compound-query fallback
        "nothing in this corpus at all",  # a real empty answer
    ],
)
def test_find_names_says_the_same_thing_from_the_store_as_from_the_pages(corpus, pages_only, query):
    from_store = find_names(query, names_dir=corpus["names_dir"], vault_dir=corpus["vault_dir"])
    from_pages = find_names(query, names_dir=corpus["names_dir"], vault_dir=pages_only)
    assert from_store == from_pages


def test_find_names_ranks_the_bigger_door_first_from_the_store(corpus):
    hits = find_names("Mandate", names_dir=corpus["names_dir"], vault_dir=corpus["vault_dir"])
    assert [(hit.canonical, hit.member_count, hit.source_count) for hit in hits] == [
        ("French Mandate", 2, 2)
    ]


@pytest.mark.parametrize("limit", [10, 2])
def test_get_name_says_the_same_thing_from_the_store_as_from_the_pages(corpus, pages_only, limit):
    from_store = get_name(
        "Ernest Gellner", limit, names_dir=corpus["names_dir"], vault_dir=corpus["vault_dir"]
    )
    from_pages = get_name(
        "Ernest Gellner", limit, names_dir=corpus["names_dir"], vault_dir=pages_only
    )
    assert from_store == from_pages
    assert from_store.member_count == 3
    assert [member.chunk_id for member in from_store.members] == [
        member.chunk_id for member in from_pages.members
    ]
    claims = {member.chunk_id: member.claim for member in from_store.members}
    if A_NOTE_2 in claims:
        assert claims[A_NOTE_2] == "A second passage from the same book."


def test_get_name_still_carries_the_gather_section_the_page_holds(corpus, pages_only):
    """Gather appends its finding to the name page after Materialize has
    already written the store, so the rendered page stays the one place that
    finding lives."""
    page = corpus["vault_dir"] / "names" / "Ernest Gellner.md"
    page.write_text(
        page.read_text(encoding="utf-8")
        + "\n## What the authors here disagree about\n\nWhether nations are modern.\n"
        + "\n**Runs between:** [[Ernest Gellner]]\n",
        encoding="utf-8",
    )
    shutil.copy(page, pages_only / "names" / "Ernest Gellner.md")

    from_store = get_name(
        "Ernest Gellner", names_dir=corpus["names_dir"], vault_dir=corpus["vault_dir"]
    )
    from_pages = get_name("Ernest Gellner", names_dir=corpus["names_dir"], vault_dir=pages_only)
    assert from_store.disagreement is not None
    assert from_store.disagreement.text == "Whether nations are modern."
    assert from_store == from_pages
