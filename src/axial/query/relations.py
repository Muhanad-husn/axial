"""Retrieval over the notes and their relations (DEC-62, issue #650,
specs/PHASE-B.md §7.5).

The name layer answers one relation at a time: `get_name` walks
`note -> name`, `who_argues_against` walks `note -> opposition target`,
`name_neighbors` walks `name -> name`. A historian's question chains two.
Measured (`data/logs/2026-08-04-relational-join-ceiling/`), 43,101
high-confidence cross-source opposition pairs across 343 named scholars and
works sit in the notes and no tool on that surface reaches them, because
each of the three queries §7.5 names needs a second join the door layer
cannot express:

- positions on X held by authors who disagree with Y (`find_notes`, with
  `opposing`);
- claims about X made only by sources published after or before Z
  (`find_notes`, with `published_after`/`published_before`);
- names co-occurring in the notes that argue against the same target
  (`names_arguing_against`).

`opposition_pairs` returns the measured edge itself: the cross-source
`(A, B)` note pairs where A argues against something B's own passage is
about.

**The note is the destination; a name, a year and a source are filters on
it.** Every function here starts from `notes` and narrows, which is why a
name argument is resolved through the alias/fold layer
(`canonical_name_for_surface`) before it is matched -- a caller writes
`Tilly` and reaches `Charles Tilly` without spending a turn on `find_names`
first. A surface the layer does not carry is used verbatim, the same
fallback `axial.query.names.where_names_meet` already applies, so a vault
whose `data/names/` is absent still queries its own store.

**The opposition join is the conservative one and nothing here loosens
it.** `note_arguing_against.resolved_canonical` is written by
`axial.materialize._resolve_target`, which matches only surface forms of two
or more tokens. The permissive single-token join reaches 93.4% of targets
against 44.0%, and the measurement showed that gap to be NER noise
(`the notion of Free French rule` resolving to the canonical `Rule`), not
signal.

**A vault with no store answers nothing here, honestly.** `connect` returns
`None` for a vault materialized before the store existed, and every function
returns an empty result with a zero total rather than raising -- the same
"empty is a real answer" rule §7.5 states for `find_names`. The name-page
tools are unaffected and keep answering from the pages.

**Determinism (§7.5, binding).** Every query orders explicitly in SQL, then
spreads the ordered rows across their sources one per source in rotation
(`_spread_by_source`) before truncating at `limit`. Plain `chunk_id`
ascending is not used, for the reason `where_names_meet` already states: a
`chunk_id` begins with its own `source_id`, so ascending order IS
alphabetical-by-source and a truncated window collapses onto whichever book
sorts first. The rotation preserves the SQL order inside each source, so the
whole order is total and the same query over the same pinned vault returns
the same ids in the same order.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.paths import default_vault_dir
from axial.query import store as note_store
from axial.query.names import DEFAULT_LIMIT, canonical_name_for_surface


@dataclass(frozen=True)
class NoteRow:
    """One note `find_notes` reached, with the fields a retrieval model
    judges relevance on: its own one-sentence `claim`, its stated `position`
    (the `position` answer where the note carries one, `position_of`
    otherwise -- the mixed frame is resolved once, at store-build time), and
    its source's author and publication year."""

    chunk_id: str
    source_id: str | None
    author: str | None
    year: int | None
    claim: str | None
    position: str | None


@dataclass(frozen=True)
class CoName:
    """One name that co-occurs, in some note's own `names` answer, with an
    opposition to a given target: `note_count` is how many such notes carry
    it, `source_count` how many books those notes span."""

    canonical: str
    kind: str | None
    note_count: int
    source_count: int


@dataclass(frozen=True)
class OppositionPair:
    """One cross-source opposition edge: the note `opposing_chunk_id` argues
    against `target` (its own free text), that target resolves to the
    canonical asked for, and `about_chunk_id` is a note from a DIFFERENT
    source whose own `names` answer carries the same canonical -- A opposes
    something B's passage is about."""

    opposing_chunk_id: str
    opposing_source_id: str
    target: str
    about_chunk_id: str
    about_source_id: str


def _connect(vault_dir: Path | None) -> sqlite3.Connection | None:
    """A read-only connection to the vault's store, or `None` when the vault
    has none -- `vault_dir` resolved the same way every other `axial.query`
    default is (`axial.paths.default_vault_dir`) when the caller passed
    none."""
    return note_store.connect(vault_dir if vault_dir is not None else default_vault_dir())


def _resolve(surface: str, names_dir: Path | None) -> str:
    """`surface` as a canonical name, through the alias map's three exact
    tiers, or `surface` itself when the layer carries no such name -- the
    same `or canonical` fallback `where_names_meet` already applies, so a
    store whose vault has no `data/names/` beside it still matches its own
    `note_names` rows."""
    return canonical_name_for_surface(surface, names_dir=names_dir) or surface


def _spread_by_source(keyed: list[tuple[str, Any]]) -> list[Any]:
    """`keyed`, a list of `(source_id, row)` in the query's own explicit
    order, regrouped by source and emitted one row per source in rotation --
    so truncating at `limit` yields a window spread across books rather than
    a prefix of whichever book sorts first (§7.5's own reason for
    `where_names_meet`'s rotation). Groups are ordered by `source_id`
    ascending, each group keeps its incoming order, and a row with no source
    groups under `""`, which sorts first -- reachable, never dropped.

    A third small rotation rather than a shared one: `axial.query.names.
    _round_robin_by_source` rotates `NameMember` objects and `axial.retrieve.
    loop._round_robin_by_source` rotates bare ids under weighted fair
    queuing, and both are pinned by measurement (#562/#566, #639). This one
    rotates whatever its two callers here hold."""
    groups: dict[str, list[Any]] = {}
    for source_id, row in keyed:
        groups.setdefault(source_id or "", []).append(row)
    keys = sorted(groups)
    ordered: list[Any] = []
    index = 0
    while len(ordered) < len(keyed):
        for key in keys:
            bucket = groups[key]
            if index < len(bucket):
                ordered.append(bucket[index])
        index += 1
    return ordered


def find_notes(
    about: str,
    limit: int = DEFAULT_LIMIT,
    *,
    opposing: str | None = None,
    published_after: int | None = None,
    published_before: int | None = None,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> tuple[list[NoteRow], int]:
    """The notes whose own `names` answer carries `about`, narrowed by any
    of three filters, plus `total` -- the true pre-cap count.

    - `opposing`: keep only notes from sources that argue against this name
      somewhere in their own interrogation answers. "Positions on X held by
      authors who disagree with Y" -- the filter is the SOURCE's opposition,
      not the note's, because that is the question: what an author who
      rejects Y thinks about X, which the note stating the opposition and
      the note stating the position are almost never the same note.
      (`who_argues_against` already answers the note-level form.)
    - `published_after` / `published_before`: keep only notes whose source's
      publication year is strictly after / strictly before the given year,
      read off `sources.year` -- a column a name page does not carry at all,
      which is why "claims about X made only by sources published after Z"
      had no answer on the door layer.

    Both name arguments are resolved through the alias/fold layer first.
    Empty is a real answer; a vault with no store returns `([], 0)`."""
    connection = _connect(vault_dir)
    if connection is None:
        return [], 0
    try:
        sql = [
            "SELECT DISTINCT n.chunk_id, n.source_id, s.author, s.year, n.claim, n.position",
            "FROM note_names nn",
            "JOIN notes n ON n.chunk_id = nn.chunk_id",
            "LEFT JOIN sources s ON s.source_id = n.source_id",
            "WHERE nn.canonical = ?",
        ]
        params: list[Any] = [_resolve(about, names_dir)]
        if opposing is not None:
            sql.append(
                "AND n.source_id IN (SELECT source_id FROM note_arguing_against "
                "WHERE resolved_canonical = ?)"
            )
            params.append(_resolve(opposing, names_dir))
        if published_after is not None:
            sql.append("AND s.year > ?")
            params.append(published_after)
        if published_before is not None:
            sql.append("AND s.year < ?")
            params.append(published_before)
        sql.append("ORDER BY n.source_id, n.chunk_id")
        rows = [NoteRow(*row) for row in connection.execute("\n".join(sql), params)]
    finally:
        connection.close()
    spread = _spread_by_source([(row.source_id or "", row) for row in rows])
    return spread[:limit], len(rows)


def names_arguing_against(
    target: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> tuple[list[CoName], int]:
    """The names that co-occur, in the notes that argue against `target`,
    with that opposition -- plus `total`, the true pre-cap count of distinct
    such names.

    This is the third relation `name_neighbors` cannot condition on.
    `name_neighbors` computes co-occurrence for one name over the WHOLE
    corpus; this computes it only inside the set of notes that oppose a
    given target, which is what "what else do the people who disagree with
    Mann talk about" means. Measured against `Michael Mann` on the live
    corpus: `IEMP model` (8 notes), `Europe` (8), `The Sources of Social
    Power` (7), `Joseph Bryant` (5), `Ernest Gellner` (5).

    **Determinism:** `note_count` descending, canonical ascending -- a total
    order, and the count is the plain measured one, with no weighting. (IDF
    weighting was measured to do nothing for a hub anchor, PR #522, and is
    not reintroduced here; conditioning on the opposition set is itself the
    narrowing.) `target` resolves through the alias/fold layer; the target's
    own canonical is excluded from its own co-occurrence list."""
    connection = _connect(vault_dir)
    if connection is None:
        return [], 0
    canonical = _resolve(target, names_dir)
    try:
        rows = [
            CoName(*row)
            for row in connection.execute(
                """
                SELECT nn.canonical, MIN(nn.kind),
                       COUNT(DISTINCT nn.chunk_id)  AS note_count,
                       COUNT(DISTINCT nn.source_id) AS source_count
                FROM note_arguing_against aa
                JOIN note_names nn ON nn.chunk_id = aa.chunk_id
                WHERE aa.resolved_canonical = ? AND nn.canonical <> ?
                GROUP BY nn.canonical
                ORDER BY note_count DESC, nn.canonical ASC
                """,
                (canonical, canonical),
            )
        ]
    finally:
        connection.close()
    return rows[:limit], len(rows)


def opposition_pairs(
    canonical: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> tuple[list[OppositionPair], list[str], int]:
    """The cross-source opposition edge itself: `(pairs, chunk_ids, total)`,
    where each pair is a note that argues against something resolving to
    `canonical` alongside a note from a DIFFERENT source whose own passage is
    about that same canonical.

    `chunk_ids` is both ends of every returned pair, deduplicated in pair
    order (the opposing note first), truncated at `limit` -- so `limit`
    bounds returned IDS, the same unit every other tool bounds, and `total`
    is the true pre-cap count of distinct ids across every pair. Pairs are
    accumulated until that id budget is spent, and the pairs actually
    represented in `chunk_ids` are what comes back.

    Measured on the live corpus: 43,101 such pairs across 343 person/work
    canonicals, of which the door layer surfaces effectively none. The
    hub-inflated raw count (127,776) comes from place and period canonicals
    -- `Both notes mention the United States` is not disagreement -- and
    nothing here filters that, because the caller names the canonical: this
    tool answers about the name it was asked about.

    **Determinism:** pairs are ordered by `(opposing_chunk_id, target,
    about_chunk_id)` in SQL -- a total order, since one note can argue
    against the same canonical under two different free-text targets -- then
    spread across the opposing notes' sources in rotation."""
    connection = _connect(vault_dir)
    if connection is None:
        return [], [], 0
    try:
        rows = [
            OppositionPair(*row)
            for row in connection.execute(
                """
                SELECT DISTINCT aa.chunk_id, aa.source_id, aa.target, n.chunk_id, n.source_id
                FROM note_arguing_against aa
                JOIN note_names nn ON nn.canonical = aa.resolved_canonical
                JOIN notes n ON n.chunk_id = nn.chunk_id
                WHERE aa.resolved_canonical = ?
                  AND aa.source_id IS NOT NULL
                  AND nn.source_id <> aa.source_id
                ORDER BY aa.chunk_id, aa.target, n.chunk_id
                """,
                (_resolve(canonical, names_dir),),
            )
        ]
    finally:
        connection.close()

    ordered = _spread_by_source([(pair.opposing_source_id, pair) for pair in rows])
    total = len({end for pair in rows for end in (pair.opposing_chunk_id, pair.about_chunk_id)})
    chunk_ids: list[str] = []
    seen: set[str] = set()
    pairs: list[OppositionPair] = []
    for pair in ordered:
        if len(chunk_ids) >= limit:
            break
        pairs.append(pair)
        for end in (pair.opposing_chunk_id, pair.about_chunk_id):
            if end not in seen:
                seen.add(end)
                chunk_ids.append(end)
    # A pair's second end can fall past `limit` when the budget ran out
    # mid-pair; the pairs reported are then only those still represented in
    # what came back, so `detail` never names an id `result_ids` does not
    # carry.
    chunk_ids = chunk_ids[:limit]
    kept = set(chunk_ids)
    pairs = [pair for pair in pairs if kept & {pair.opposing_chunk_id, pair.about_chunk_id}]
    return pairs, chunk_ids, total


def chunk_ids_for_name(
    canonical: str, *, vault_dir: Path | None = None, names_dir: Path | None = None
) -> set[str]:
    """Every note whose own `names` answer carries `canonical`, as a bare id
    set -- the join key `axial.argmap.ask.positions_on` intersects the
    argument map's positions against. An empty set for a vault with no
    store, or a name it does not carry."""
    connection = _connect(vault_dir)
    if connection is None:
        return set()
    try:
        return {
            row[0] for row in note_store.name_members(connection, _resolve(canonical, names_dir))
        }
    finally:
        connection.close()
