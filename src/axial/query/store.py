"""The relational store over the notes and their typed relations (DEC-62,
issue #648).

Interrogation produced a graph: notes with typed relations -- what each
passage claims, whose position it is, what it argues against, whom it cites,
what it names. Materialize used to keep only the node labels, grouping notes
into one flat page per name; measured
(`data/logs/2026-08-04-relational-join-ceiling/`), 4.7% of the corpus's
`arguing_against` targets joined to anything queryable that way. The same
notes loaded into these tables reach 44%, expose 43,101 high-confidence
cross-source opposition pairs the flat layer surfaces effectively none of,
and answer questions that chain two relations -- "positions on X held by
authors who disagree with Y" -- which a tool that walks one relation cannot.

This module is the store itself: its schema, its atomic write, and the reads
`axial.query.names` answers `find_names`/`get_name` from. **It builds
nothing** -- `axial.materialize.build_note_store` assembles the rows, from
the same already-persisted artifacts the name pages are written from, and
calls `write_store` here. That split is what keeps this module importable
from `axial.query.names` without an import cycle: nothing here reaches back
into the interrogation or materialize stack.

**The name pages are unchanged.** They stay the rendered Obsidian view; the
store is the queryable substrate under them, and `find_names`/`get_name`
answered from it say exactly what they said when they read the pages.

Two `kind` columns, deliberately, because the corpus carries two:
`names.kind` is the merged node's own kind -- what a name page and a door
slate report -- and `note_names.kind` is the label THIS note's own `names[]`
answer gave that name, which varies note to note over the same canonical
(the corpus calls `French Mandate` a period on 40 notes and something else
on the rest). The measured person/work filter on opposition pairs reads the
second.

**`note_opposed_position` (issue #651).** `note_arguing_against` above is the
CONSERVATIVE relational join -- a target resolves only when a >=2-token
phrase in it names a merged name-page node exactly. Measured
(`data/logs/2026-08-04-relational-join-ceiling/`), that join alone leaves
5,846 targets (45.9% of the corpus's `arguing_against` answers) resolved to
nothing, because most targets are a paraphrase of an argument, not a name
("the single right-left continuum of regime typologies"). `axial.argmap.
residue` closes part of that gap with a semantic match against the argument
map's own positions (`data/map/<pin>/positions.jsonl`, issue #572) instead of
the name layer -- one model call per target, logged to a content-keyed
decision log the pass itself writes and never mutates the store from.
`axial.materialize.build_note_store` is what folds that log into this table,
at materialize time, the same split `note_arguing_against` already keeps
between an upstream decision (Reconcile's alias map) and this module's own
assembly.

A target can carry more than one row here -- the union of positions either
blocking arm matched it to, per the founder's own #651 decision to run both
arms and keep everything either one finds rather than picking one. Two
columns exist because of what the sample run measured about that union,
neither derivable from the row alone without them:

- `mode` -- `"blocked"`, `"unblocked"`, or `"both"` when the two arms
  independently landed on the same `(chunk_id, target, position_id)` triple.
  Section blocking (`build_section_index`) is a recovery net that finds
  mostly DIFFERENT targets from the unblocked arm, not a subset of them (3 of
  27 hits overlapped in the 100-target sample) -- if a later pass drops one
  arm, this column is how a query can tell what that specific arm was
  carrying, rather than reading a flat, unattributed edge count.
- `self_referential` -- 1 when the note's own `source_id` is one of the
  matched position's own `sources` (a plain membership check at assembly, no
  new mechanism): the target and the position it names came from the SAME
  book, occasionally the very same passage the target itself is one sentence
  of. A real match, but not the cross-source opposition #651 exists to
  surface, so a reader must be able to exclude it rather than have it mixed
  silently into a "resolved" count.

A query over this table answers the question #651 exists for -- given a
position, which notes argue against it, and from which OTHER sources:

    SELECT o.source_id, COUNT(DISTINCT o.chunk_id)
    FROM note_opposed_position o
    WHERE o.position_id = ? AND o.self_referential = 0
    GROUP BY o.source_id

`opposing_notes` below is that join, unfiltered (every row, `mode` and
`self_referential` both exposed) so a caller decides how to read them rather
than this module deciding for it.

**`notes.back_matter` (issue #661).** Set once, at materialize time
(`axial.materialize.build_note_store`), from a note's own `section` heading
via `axial.back_matter.is_evidence_back_matter` -- the same broader rule
`axial.gold` already applied to its own sampling frame, reused rather than
re-derived. A live run grounded two of seventeen claims on an acknowledgments
page and an endnotes page: both chunks exist, both carry interrogation
answers, and nothing before this column stopped either from being retrieved
and cited as evidence. Every read here that returns a note as citable
evidence (`name_members`, `doors`, `concept_sources`) filters it out at the
join, once, rather than leaving each caller to re-derive the same check --
the note ROW still exists in `notes` (nothing here refuses to write one),
it is simply never counted as evidence again downstream.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from axial.paths import replace_with_retry

# The store's own filename, a sibling of `vault_dir/names/` (the same
# placement `axial.materialize.NAME_PAGE_INDEX_FILENAME` uses, and for the
# same reason: a `*.md` glob over `names/` must never pick it up).
STORE_FILENAME = "notes.db"

SCHEMA = """
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    author    TEXT,
    title     TEXT,
    date      TEXT,
    year      INTEGER
);
CREATE TABLE notes (
    chunk_id    TEXT PRIMARY KEY,
    source_id   TEXT,
    section     TEXT,
    chapter     TEXT,
    claim       TEXT,
    position    TEXT,
    back_matter INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE names (
    canonical TEXT PRIMARY KEY,
    kind      TEXT,
    folded    TEXT NOT NULL
);
CREATE TABLE note_names (
    chunk_id  TEXT NOT NULL,
    source_id TEXT NOT NULL,
    canonical TEXT NOT NULL,
    kind      TEXT
);
CREATE TABLE note_arguing_against (
    chunk_id           TEXT NOT NULL,
    source_id          TEXT,
    target             TEXT NOT NULL,
    resolved_canonical TEXT
);
CREATE TABLE note_citations (
    chunk_id  TEXT NOT NULL,
    source_id TEXT,
    cited     TEXT NOT NULL,
    stance    TEXT,
    about     TEXT
);
CREATE TABLE note_opposed_position (
    chunk_id         TEXT NOT NULL,
    source_id        TEXT,
    target           TEXT NOT NULL,
    position_id      TEXT NOT NULL,
    mode             TEXT NOT NULL,
    self_referential INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX note_names_canonical ON note_names (canonical);
CREATE INDEX note_names_chunk_id ON note_names (chunk_id);
CREATE INDEX note_arguing_against_resolved ON note_arguing_against (resolved_canonical);
CREATE INDEX note_arguing_against_chunk_id ON note_arguing_against (chunk_id);
CREATE INDEX note_citations_chunk_id ON note_citations (chunk_id);
CREATE INDEX note_opposed_position_position_id ON note_opposed_position (position_id);
CREATE INDEX note_opposed_position_chunk_id ON note_opposed_position (chunk_id);
"""

_TABLES = (
    ("sources", 5),
    ("notes", 7),
    ("names", 3),
    ("note_names", 4),
    ("note_arguing_against", 4),
    ("note_citations", 5),
    ("note_opposed_position", 6),
)

# `notes`' own width before `back_matter` was added (issue #661) -- a row of
# exactly this length is a pre-#661 fixture that never states the column,
# padded with the correct default (`0`, not back matter) by `write_store`.
_NOTE_COLUMNS_BEFORE_BACK_MATTER = 6

# SQLite's own limit on host parameters in one statement is 999 on the
# oldest builds still in the wild; a door query over a broad `contains` scan
# can carry thousands of canonicals, so `doors` asks in batches under it.
_PARAMETER_BATCH = 500


@dataclass(frozen=True)
class SourceShare:
    """One source's own contribution to a concept's membership: how many of
    its notes carry the concept, alongside the source's own publication
    year -- the per-source breakdown `Door`'s single aggregated
    `member_count`/`source_count` cannot answer, and the raw material the
    intake fork-check (issue #649, specs/PHASE-B.md §7, DEC-62) measures a
    question's own concepts against: how lopsided the coverage is, and
    whether the sources span the period the question asks about."""

    source_id: str
    author: str | None
    year: int | None
    note_count: int


@dataclass(frozen=True)
class Door:
    """One name as the door layer sees it: the merged node's own `kind`, how
    many notes carry it, and how many distinct sources those notes span. A
    name with no member note at all is still a door, with both counts 0 --
    the same thing the name page for it says."""

    canonical: str
    kind: str | None
    member_count: int
    source_count: int | None


def store_path(vault_dir: Path) -> Path:
    return Path(vault_dir) / STORE_FILENAME


def connect(vault_dir: Path) -> sqlite3.Connection | None:
    """A read-only connection to the vault's store, or `None` when the vault
    has none -- a vault materialized before the store existed, or a fixture
    that only ever wrote name pages. Every caller here treats `None` as "ask
    the pages instead", never as an error.

    A fresh connection per call rather than a cached one: `find_names` is
    called from a threaded retrieval loop, a `sqlite3.Connection` is not
    shared across threads by default, and opening one costs microseconds
    because SQLite reads pages on demand rather than loading the file.

    **`vault_dir` is resolved to an absolute path first (issue #649's own
    acceptance test caught this).** `Path.as_uri()` raises `ValueError` on
    any relative path regardless of the process's own working directory,
    and both `axial.paths.default_vault_dir`'s fallback and
    `config/pipeline.yaml`'s own `paths.vault_dir` are the relative literal
    `data/vault` -- so every real call site that never overrides
    `vault_dir` (`axial brief run`, `axial ask`, with no explicit
    `--vault-dir`) was one relative path away from this crashing the moment
    a vault actually had a store to open."""
    path = store_path(vault_dir).resolve()
    if not path.is_file():
        return None
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def write_store(
    path: Path,
    *,
    sources: Iterable[Sequence],
    notes: Iterable[Sequence],
    names: Iterable[Sequence],
    note_names: Iterable[Sequence],
    note_arguing_against: Iterable[Sequence],
    note_citations: Iterable[Sequence],
    note_opposed_position: Iterable[Sequence] = (),
) -> dict[str, int]:
    """Write the whole store to `path` atomically: a fresh database is built
    beside it and replaced over it in one filesystem rename
    (`axial.paths.replace_with_retry`, issue #705), so a concurrent reader
    always observes either the complete prior store or the complete new one
    and never a half-written one, and a transient Windows `PermissionError`
    on that rename (#653) is retried rather than aborting the write. Same
    shape, and the same reason, as `axial.paths.atomic_write_text` -- which
    cannot be reused directly because SQLite writes the file itself; this
    shares its retry helper instead of re-deriving the loop.

    Returns one row count per table, for the materialize summary."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(handle)
    rows = {
        "sources": sources,
        # `back_matter` (issue #661) is appended when a row omits it, rather
        # than requiring every caller to state it: a fixture written before
        # the column existed and never means to exercise back-matter
        # behavior gets the correct default (not back matter, `0`) without
        # editing every such fixture across the codebase; `axial.materialize.
        # build_note_store` states it explicitly on every row it writes.
        "notes": (
            tuple(row) if len(row) != _NOTE_COLUMNS_BEFORE_BACK_MATTER else (*row, 0)
            for row in notes
        ),
        "names": names,
        "note_names": note_names,
        "note_arguing_against": note_arguing_against,
        "note_citations": note_citations,
        "note_opposed_position": note_opposed_position,
    }
    counts: dict[str, int] = {}
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(SCHEMA)
            for table, width in _TABLES:
                placeholders = ",".join("?" * width)
                cursor = connection.executemany(
                    f"INSERT INTO {table} VALUES ({placeholders})", rows[table]
                )
                counts[f"store_{table}"] = cursor.rowcount
            # Free off the table just written above (issue #661): how many
            # notes the evidence filter withholds corpus-wide, for
            # `axial materialize`'s own operator-facing summary -- one
            # `COUNT` over a table already in memory, not a second pass.
            (back_matter_count,) = connection.execute(
                "SELECT COUNT(*) FROM notes WHERE back_matter = 1"
            ).fetchone()
            counts["store_notes_back_matter"] = back_matter_count
            connection.commit()
        finally:
            connection.close()
        replace_with_retry(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    return counts


# ---------------------------------------------------------------------------
# The reads `axial.query.names` answers from
# ---------------------------------------------------------------------------


def contains_matches(connection: sqlite3.Connection, folded_query: str) -> list[str]:
    """Every name whose folded form carries `folded_query` as a whole-word
    phrase, canonical ascending -- issue #632's `contains` route, as SQL over
    the store's own folded column. `instr` against a space-padded haystack
    and needle, never `LIKE`, so nothing in a query string is read as a
    wildcard."""
    if not folded_query:
        return []
    rows = connection.execute(
        "SELECT canonical FROM names WHERE instr(' ' || folded || ' ', ?) > 0 ORDER BY canonical",
        (f" {folded_query} ",),
    )
    return [row[0] for row in rows]


def doors(connection: sqlite3.Connection, canonicals: Iterable[str]) -> dict[str, Door]:
    """`canonical -> Door` for the names the store carries, as the one GROUP
    BY over `note_names` the measurement verified against production's own
    door index. A canonical the store does not carry is simply absent from
    the result -- the caller reports it as an unknown count rather than a 0
    that would read like real, thin coverage.

    **A back-matter member never counts (issue #661).** The exclusion is a
    conditional aggregate (`CASE WHEN ... back_matter = 0`), not a `WHERE`
    filter on the join -- a `WHERE` would drop a canonical whose members are
    ALL back-matter out of the result entirely (indistinguishable from one
    the store does not carry), where a conditional aggregate correctly
    reports it as a real door sitting at `member_count=0`, the same "carried,
    but empty" reading `name_members` gives it below."""
    ordered = list(dict.fromkeys(canonicals))
    found: dict[str, Door] = {}
    for start in range(0, len(ordered), _PARAMETER_BATCH):
        batch = ordered[start : start + _PARAMETER_BATCH]
        placeholders = ",".join("?" * len(batch))
        for row in connection.execute(
            f"""
            SELECT n.canonical, n.kind,
                   COUNT(DISTINCT CASE WHEN nt.back_matter = 0 THEN nn.chunk_id END)
                       AS member_count,
                   COUNT(DISTINCT CASE WHEN nt.back_matter = 0 THEN nn.source_id END)
                       AS source_count
            FROM names n
            LEFT JOIN note_names nn ON nn.canonical = n.canonical
            LEFT JOIN notes nt ON nt.chunk_id = nn.chunk_id
            WHERE n.canonical IN ({placeholders})
            GROUP BY n.canonical, n.kind
            """,
            batch,
        ):
            found[row[0]] = Door(row[0], row[1], row[2], row[3])
    return found


def concept_sources(connection: sqlite3.Connection, canonical: str) -> list[SourceShare]:
    """Every source contributing to `canonical`'s membership, each with its
    own note count and publication year, ranked by note count descending
    (ties broken by `source_id` ascending) -- one `GROUP BY` over
    `note_names` joined to `sources`, the per-source breakdown `doors()`'s
    single aggregated counts do not carry. `[]` when the store holds no
    member note for `canonical` at all, the same "absent, not zero" reading
    `doors()` gives a canonical it does not carry.

    **A back-matter member is not a real contribution (issue #661)**: a
    source whose only notes carrying `canonical` sit on an acknowledgments
    or endnotes page is not covering the concept, so it is filtered out of
    the join here rather than counted -- unlike `doors()`, a source with
    zero real contribution is supposed to be absent from this per-source
    breakdown, exactly like one that never carried the concept at all."""
    return [
        SourceShare(row[0], row[1], row[2], row[3])
        for row in connection.execute(
            """
            SELECT nn.source_id, s.author, s.year, COUNT(DISTINCT nn.chunk_id) AS note_count
            FROM note_names nn
            JOIN notes nt ON nt.chunk_id = nn.chunk_id AND nt.back_matter = 0
            LEFT JOIN sources s ON s.source_id = nn.source_id
            WHERE nn.canonical = ?
            GROUP BY nn.source_id
            ORDER BY note_count DESC, nn.source_id ASC
            """,
            (canonical,),
        )
    ]


def name_members(connection: sqlite3.Connection, canonical: str) -> list[tuple]:
    """`(chunk_id, source_id, author, date, claim)` for every note that
    carries `canonical`, in `chunk_id` order -- `get_name`'s member list as a
    plain join, in the same order the name page writes its own member lines
    (`axial.materialize.member_chunk_ids_for_node` sorts them).

    **A back-matter note is never a member here (issue #661)**: the join to
    `notes` already carries `nt.back_matter`, so excluding it is one added
    condition on a join this function already makes, not a second query --
    an acknowledgments or endnotes page must never come back as a citable
    passage `get_name`/`chunk_ids_for_name` hand a retrieval loop."""
    return [
        tuple(row)
        for row in connection.execute(
            """
            SELECT nn.chunk_id, nn.source_id, s.author, s.date, n.claim
            FROM note_names nn
            JOIN notes n ON n.chunk_id = nn.chunk_id AND n.back_matter = 0
            LEFT JOIN sources s ON s.source_id = n.source_id
            WHERE nn.canonical = ?
            ORDER BY nn.chunk_id
            """,
            (canonical,),
        )
    ]


def note_locator(connection: sqlite3.Connection, chunk_id: str) -> dict[str, Any] | None:
    """The locator for one note (issue #690): its own `section`/`chapter`
    (`notes`) and its source's own `author`/`title`/`date` (`sources`),
    joined by `source_id` -- everything a citation needs to name WHERE a
    claim rests, deliberately never `chunk_text` (that lives only in the
    vault prose file, `axial.query.reader.get_chunk`; passage-mode
    citation rendering reads it separately, `axial.service.citation`).

    There is no page number anywhere in this system -- `chapter` (derived
    at materialize time from a source's own table of contents,
    `axial.materialize.chapter_for_section`) is the finest location this
    store carries below the source itself, so it is what a locator states.

    `None` when `chunk_id` has no row -- a fixture record, a note from a
    vault with no store yet, or a ref that does not resolve."""
    row = connection.execute(
        """
        SELECT n.section, n.chapter, n.source_id, s.author, s.title, s.date
        FROM notes n
        LEFT JOIN sources s ON s.source_id = n.source_id
        WHERE n.chunk_id = ?
        """,
        (chunk_id,),
    ).fetchone()
    if row is None:
        return None
    section, chapter, source_id, author, title, date = row
    return {
        "source_id": source_id,
        "author": author,
        "title": title,
        "date": date,
        "chapter": chapter,
        "section": section,
    }


def opposing_notes(connection: sqlite3.Connection, position_id: str) -> list[tuple]:
    """`(chunk_id, source_id, target, mode, self_referential)` for every note
    whose `arguing_against` target the semantic residue resolver
    (`axial.argmap.residue`, issue #651) matched to `position_id` -- the join
    a caller makes once it already holds a position and wants to know who
    argues against it, and from which sources. `mode` and `self_referential`
    are both returned unfiltered (module docstring): `WHERE self_referential
    = 0` on the caller's own side is what turns this into the cross-source
    opposition question #651 exists to answer, but nothing here decides that
    for it. `[]` when `position_id` has no matched note -- the honest
    majority for now, since a residue full pass has to be run and folded in
    before this table carries any row at all."""
    return [
        tuple(row)
        for row in connection.execute(
            """
            SELECT chunk_id, source_id, target, mode, self_referential
            FROM note_opposed_position
            WHERE position_id = ?
            ORDER BY chunk_id
            """,
            (position_id,),
        )
    ]
