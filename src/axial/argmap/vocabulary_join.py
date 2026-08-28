"""Two notes meet at a shared group (issue #807): a deterministic step in
the map arm's own walk -- door -> landing -> corridor -> vocabulary
neighbours -> assembly -- that reaches a passage through a category a
derived vocabulary (`axial.vocabulary`, issue #806) assigned it, the way
`positions_on` (issue #650, `axial.argmap.ask`) reaches one through a
shared name.

Not a tool, not a model call. `run_map_ask_for_brief` (`axial.argmap.ask`)
runs this AFTER the corridor, on the map arm's own deterministic walk, with
no tool loop and nothing to decline: `landed`'s own notes are looked up in
`<vocabulary_dir>/<column>/assignments.jsonl` -- `axial.vocabulary.
build_vocabulary`'s own persisted output -- to find which categories they
were filed under, and every OTHER note filed under the same category, that
is not already reached through landing or the corridor (the same guard
`build_corridor` already applies to its own two-hop reach), is a neighbour.
`VocabularyPosition` carries that neighbour in the same shape `MatchedPosition`
(issue #650) already gives a name-joined position: nothing encoded, nothing
scored, one table lookup.

**Why the join reads each landed NOTE, not each landed POSITION.** A
position's own `size` can be large and span several categories across its
own notes; joining on "the position touched category X" would pull in every
one of the position's OTHER notes too, most of which never answered the
column the same way at all. The join reads each of `landed`'s own notes'
assignment records and only follows the categories THAT note was filed
under.

**A note is not in exactly one position.** The map's positions overlap:
across all three builds on disk, 263-344 chunks of ~5,200-5,600 sit in 2 to
5 positions each (issue #822). The join indexes each chunk to EVERY position
holding it and applies `excluded_position_ids` per position, so an edge is
never lost because the note's first-listed position happened to be landed or
in the corridor. Where several of a note's positions survive, each is its
own edge -- the note really is part of more than one argument, and assembly
walks positions.

**The per-category cap.** A `mechanism` category holds 309-623 notes
(measured, #806's own manifest) against `assemble_map_evidence`'s shared
`ASSEMBLE_CAP = 90` (`axial.argmap.ask`) -- uncapped, a single category
would swamp the landed and corridor positions long before assembly ever
gets to them. `PER_CATEGORY_CAP` keeps what ONE category may hand to
assembly to a fifth or so of that shared budget, with cross-source notes
preferred first (issue #651: only 40.5% of argument-map edges reach another
book) -- capped small enough that a reader can tell a category was more
than one book agreeing with itself, from the record `_map_retrieval_to_dict`
(`axial.answer.record`) writes.

**Four distinguishable reasons a note contributes no edge**
(`category_for_note`): the note was never answered for this column at all
("not-found" -- excluded by `axial.vocabulary.read_column`, or the model
was never asked); the model answered with a string naming no committed
category ("out-of-scheme"); the model genuinely declined ("refused"); or
the note landed in a category that has exactly one member -- itself --
which is not a missing edge at all, but a real category reached with
nobody else in it (`CategoryReach.chunk_ids` empty, still present in
`VocabularyJoinResult.categories`, never conflated with the three reasons
above)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from axial.vocabulary import (
    ASSIGNMENTS_FILENAME,
    MANIFEST_FILENAME,
    ROOT_LEVEL,
    VOCABULARY_DIR,
)

if TYPE_CHECKING:
    # Type-hint only -- `axial.argmap.ask` imports THIS module at runtime to
    # call `vocabulary_neighbours`, so a real, module-level import the other
    # way would be a cycle. `LandedPosition` is duck-typed here regardless
    # (only `.chunk_ids`/`.sources` are ever read); this import exists so a
    # type checker can still see the real shape.
    from axial.argmap.ask import LandedPosition

# The only column slice 02 (#806) has assigned so far -- the parameter this
# module takes so a second cleared column (#809's own call) needs no new
# code path, only a different value passed in here. Not a fallback masking
# a missing argument: `run_map_ask_for_brief` always passes a column
# explicitly, and this is only what it defaults that argument to.
DEFAULT_VOCABULARY_COLUMN = "mechanism"

# See module docstring's "the per-category cap". `axial.argmap.ask.
# ASSEMBLE_CAP` (90) is not imported here to avoid the same import cycle
# `LandedPosition`'s TYPE_CHECKING guard above avoids -- kept in sync by the
# shared reasoning in both docstrings, the same standalone-constant
# precedent `POSITIONS_PER_ASK`/`ASSEMBLE_CAP` themselves already are.
PER_CATEGORY_CAP = 20

# `category_for_note`'s own reason strings (module docstring's "four
# distinguishable reasons").
REASON_ASSIGNED = "assigned"
REASON_REFUSED = "refused"
REASON_OUT_OF_SCHEME = "out-of-scheme"
REASON_NOT_FOUND = "not-found"

# Every reason, in the order a reader wants them: the one that produced an
# edge first, then the three that did not. `VocabularyJoinResult.reasons` and
# `_vocabulary_to_dict`'s own block (`axial.answer.record`) both key on this
# so a reason that did not occur is reported as a zero rather than an absent
# key -- an absent key reads as "not measured", which is the conflation
# issue #822 exists to end.
ALL_REASONS = (REASON_ASSIGNED, REASON_REFUSED, REASON_OUT_OF_SCHEME, REASON_NOT_FOUND)


class VocabularyJoinError(Exception):
    """Base class for every error `axial.argmap.vocabulary_join` raises."""


class NoVocabularyError(VocabularyJoinError):
    """Raised when `<vocabulary_dir>/<column>/manifest.json` does not exist
    -- no `axial vocabulary build` has ever run for this column. Named
    rather than a stack trace, and never an empty success either: a typo in
    a column name or a column nobody has assigned yet must fail loudly, not
    read as "this brief simply reached no categories" (issue #807)."""

    def __init__(self, column: str, column_dir: Path):
        self.column = column
        self.column_dir = column_dir
        super().__init__(
            f"no derived vocabulary built for column {column!r} at {column_dir} -- "
            "run `axial vocabulary build` first"
        )


@dataclass(frozen=True)
class VocabularyPosition:
    """One position reached because one of ITS OWN notes shares a derived-
    vocabulary category with one of `landed`'s notes (issue #807) -- the
    same table-join shape `MatchedPosition` (issue #650, `axial.argmap.ask`)
    already gives a name-joined position, with the category assignment in
    place of the note-name table.

    `categories` names every category that pulled this position in (plural,
    the same "several edges collapse to one position" contract
    `CorridorPosition.labels` already keeps for relations). `chunk_ids` is
    ONLY this position's own notes that a matched category actually
    contains -- never the position's full set -- so a note reached for an
    unrelated reason is never double-counted as a category hit. `size` is
    the position's own full passage count, carried through unchanged, the
    same field `LandedPosition`/`CorridorPosition` already carry."""

    position_id: str
    categories: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    argument: str
    size: int
    sources: tuple[str, ...]
    authors: tuple[str, ...]


@dataclass(frozen=True)
class CategoryReach:
    """One category `landed`'s own notes reached: `chunk_ids` is the
    (possibly capped) set of OTHER notes actually contributed to assembly,
    `source_count` the distinct sources those notes come from, and
    `cap_applied` whether more candidates existed than `cap` let through --
    a fact about this run, recorded in `_map_retrieval_to_dict`
    (`axial.answer.record`) rather than left to be inferred.

    **`chunk_ids` counts notes; the cap counts edges (issue #822).** The
    map's positions do not partition the notes, so one note can be offered
    through two of its own positions. That is two things handed to
    assembly, which is what the cap governs, and one note reached, which is
    what this field reports. The two figures differ only for a note sitting
    in several surviving positions.

    A category with exactly one member -- the landed note itself -- is
    still reported here, with `chunk_ids` empty: reached, but with nobody
    else in it, which is a different fact from a note the scheme refused
    never touching a category at all (module docstring's own reason-string
    contract)."""

    category_id: str
    category_name: str
    chunk_ids: tuple[str, ...]
    source_count: int
    cap_applied: bool


@dataclass(frozen=True)
class VocabularyJoinResult:
    """What `vocabulary_neighbours` hands back: the column and level it
    joined on, the cap it enforced, every category `landed`'s own notes
    reached (`categories`, including one contributing zero neighbours), and
    the neighbour positions themselves (`positions`) -- already ordered
    (cross-source first) and already capped, ready to hand straight to
    `assemble_map_evidence` alongside the landed and corridor positions.

    `reasons` (issue #822) counts `landed`'s own distinct notes by
    `category_for_note`'s own outcome, keyed on `ALL_REASONS` with every
    reason present even at zero. It answers the first question anyone asks
    of an underperforming run: whether the notes reached no category
    because the scheme refused them, because the model answered outside
    the scheme, or because they were never assigned at all. Defaults to an
    empty mapping so a hand-built result (a test fixture) need not restate
    it; `vocabulary_neighbours` always fills all four."""

    column: str
    level: int
    cap: int
    categories: tuple[CategoryReach, ...]
    positions: tuple[VocabularyPosition, ...]
    reasons: Mapping[str, int] = field(default_factory=dict)


def category_for_note(
    chunk_id: str, by_chunk: Mapping[str, Sequence[Mapping[str, Any]]]
) -> tuple[str | None, str]:
    """What category `chunk_id` reached in this column, and why not when it
    didn't (module docstring's "four distinguishable reasons"):
    `(category_id, "assigned")` when any of its own assignment records
    carries one; `(None, "not-found")` when the note has no record at all
    in this column (never answered, or excluded -- `axial.vocabulary.
    read_column`'s own exclusion rule); `(None, "out-of-scheme")` when the
    model answered with a string naming no committed category; `(None,
    "refused")` when it genuinely declined. Only "refused" is a judgment
    about the note itself -- the other two `None` reasons are facts about
    the build, never conflated with it.

    Every one of the note's records at this level is read, not only the
    first (issue #822): one assigned record makes the note assigned, and
    one out-of-scheme record makes it out-of-scheme. That is invisible on
    a scalar column like `mechanism`, where a note has exactly one record,
    and it is the whole difference on a list-valued one."""
    records = by_chunk.get(chunk_id)
    if not records:
        return None, REASON_NOT_FOUND
    for record in records:
        category_id = record.get("category_id")
        if isinstance(category_id, str):
            return category_id, REASON_ASSIGNED
    # Every record, not just the first (issue #822). Moot for `mechanism`,
    # which is scalar and gives a note one record; live the moment a
    # list-valued column arrives, which this module advertises as needing
    # no new code path. A note whose second element answered outside the
    # scheme read as a plain refusal, and "the model declined" and "the
    # model answered something the scheme does not hold" are the two facts
    # a reader separates to decide whether the scheme fits the corpus.
    if any(record.get("out_of_scheme") for record in records):
        return None, REASON_OUT_OF_SCHEME
    return None, REASON_REFUSED


def _load_json_or_none(path: Path) -> dict[str, Any] | None:
    """Local, tolerant JSON read -- the same shape every other module's own
    manifest reader keeps privately (`axial.vocabulary._load_json_or_none`,
    `axial.argmap.build._load_json_or_none`) rather than importing another
    module's private helper, the precedent both of those already set."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_assignment_records(path: Path) -> list[dict[str, Any]]:
    """Every persisted assignment record under `path`, or `[]` when the
    file does not exist. A torn final line is dropped, not raised -- the
    same tolerance `axial.vocabulary._read_assignment_records` gives its
    own reader, kept as this module's own private copy for the same reason
    `_load_json_or_none` above is."""
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def vocabulary_neighbours(
    landed: Sequence["LandedPosition"],
    excluded_position_ids: set[str],
    positions: Sequence[Mapping[str, Any]],
    column: str,
    *,
    level: int | None = None,
    vocabulary_dir: Path | None = None,
    cap: int = PER_CATEGORY_CAP,
) -> VocabularyJoinResult:
    """The vocabulary step (issue #807): every OTHER position reachable
    because one of ITS notes shares a category with one of `landed`'s own
    notes, in `column` at `level` (or the column's finest level, read off
    the persisted manifest's own `max_level`, when `level` is `None`).

    `excluded_position_ids` is `landed`'s own position ids UNION the
    corridor's -- the same guard `build_corridor` applies to its own reach
    -- so a position already reached through landing or the corridor is
    never reported again here.

    `positions` is the map's own full position list (`_load_map`'s own
    `positions.jsonl`, unfiltered), used to resolve which position a
    category's member chunk_id belongs to.

    Raises `NoVocabularyError` when `<vocabulary_dir>/<column>/manifest.json`
    does not exist -- a column with no persisted vocabulary fails naming
    the column, never with a stack trace and never with an empty success."""
    root = Path(vocabulary_dir) if vocabulary_dir is not None else VOCABULARY_DIR
    column_dir = root / column
    manifest = _load_json_or_none(column_dir / MANIFEST_FILENAME)
    if manifest is None:
        raise NoVocabularyError(column, column_dir)
    resolved_level = level if level is not None else int(manifest.get("max_level", ROOT_LEVEL))
    category_names = {
        str(entry.get("category_id")): str(entry.get("name", ""))
        for entry in manifest.get("categories", [])
        if isinstance(entry, dict)
    }

    records = _read_assignment_records(column_dir / ASSIGNMENTS_FILENAME)
    by_chunk: dict[str, list[dict[str, Any]]] = {}
    # category_id -> [(chunk_id, source_id), ...], in file order.
    members_by_category: dict[str, list[tuple[str, str]]] = {}
    for record in records:
        if int(record.get("level", ROOT_LEVEL)) != resolved_level:
            continue
        chunk_id = str(record.get("chunk_id", ""))
        by_chunk.setdefault(chunk_id, []).append(record)
        category_id = record.get("category_id")
        if isinstance(category_id, str):
            source_id = str(record.get("source_id", ""))
            members_by_category.setdefault(category_id, []).append((chunk_id, source_id))

    # **A note can sit in more than one position (issue #822).** The first
    # cut kept only the first position holding each chunk, which assumes the
    # map's positions partition the notes. They do not: measured against
    # every built map on disk, `data/map/9b796b3a6312b329/positions.jsonl`
    # holds 1,937 positions over 5,596 distinct chunks and 344 of those
    # chunks appear in 2 to 5 positions; the two older builds show 278/5,177
    # and 263/5,509, with the same maximum multiplicity of 5. Under the old
    # rule a candidate whose FIRST position happened to be landed or in the
    # corridor was dropped even though another, unexcluded position also
    # held it, and which position a category hit was attributed to depended
    # on file order.
    positions_by_chunk: dict[str, list[Mapping[str, Any]]] = {}
    for position in positions:
        for chunk_id in position["chunk_ids"]:
            positions_by_chunk.setdefault(chunk_id, []).append(position)

    landed_chunk_ids = {chunk_id for position in landed for chunk_id in position.chunk_ids}
    landed_sources = {source for position in landed for source in position.sources}

    # **Cross-source is judged per category, not against every landed source
    # (issue #807, second cut).** The first cut ranked a candidate against
    # the union of every landed position's sources. On the live run that was
    # 22 landed positions over a 35-source corpus: the union covered most of
    # the corpus, so almost no candidate could enter the preferred tier, and
    # the cap filled by `position_id` ascending -- an arbitrary order with no
    # book-diversity property at all, which is the opposite of what #651
    # asks for. What the finding actually asks is that a category's
    # neighbours lead with books other than the one the ASKING note came
    # from, so the comparison set is the sources of the landed notes that
    # touched THIS category.
    # **The reason is counted, not discarded (issue #822).** `category_for_
    # note` distinguishes four outcomes and the join's first cut dropped
    # three of them on the floor, so nothing in the recorded block said how
    # many landed notes produced no edge or why. The counts are over
    # `landed`'s own DISTINCT notes -- one vote each, the same set the join
    # itself walks -- and every reason keeps a key even at zero, so
    # "the scheme does not fit this corpus" (refused, out-of-scheme) reads
    # differently from "these notes were never assigned" (not-found).
    reasons: dict[str, int] = {reason: 0 for reason in ALL_REASONS}
    touched_category_ids: set[str] = set()
    landed_sources_by_category: dict[str, set[str]] = {}
    for chunk_id in landed_chunk_ids:
        category_id, reason = category_for_note(chunk_id, by_chunk)
        reasons[reason] = reasons.get(reason, 0) + 1
        if category_id is None:
            continue
        touched_category_ids.add(category_id)
        records = by_chunk.get(chunk_id) or []
        for record in records:
            source_id = record.get("source_id")
            if isinstance(source_id, str) and source_id:
                landed_sources_by_category.setdefault(category_id, set()).add(source_id)

    categories: list[CategoryReach] = []
    # position_id -> {"categories": set[str], "chunk_ids": list[str], "position": dict}
    hits: dict[str, dict[str, Any]] = {}

    for category_id in sorted(touched_category_ids):
        candidates: list[tuple[str, str, Mapping[str, Any]]] = []
        seen_chunk_ids: set[str] = set()
        for chunk_id, source_id in members_by_category.get(category_id, []):
            if chunk_id in landed_chunk_ids or chunk_id in seen_chunk_ids:
                continue
            # Exclusion is applied per position, not to the chunk. When
            # several of a note's positions survive, EACH is its own edge:
            # the note is genuinely part of more than one argument, and
            # assembly walks positions, so collapsing them would silently
            # pick one argument for the reader. The per-category cap goes
            # on counting what a category hands to assembly -- one count per
            # surviving position -- so the budget contract is unchanged;
            # `CategoryReach.chunk_ids` below stays a count of distinct
            # NOTES offered, which is the different question it answers.
            surviving = [
                position
                for position in positions_by_chunk.get(chunk_id, ())
                if position["position_id"] not in excluded_position_ids
            ]
            if not surviving:
                continue
            seen_chunk_ids.add(chunk_id)
            candidates.extend((chunk_id, source_id, position) for position in surviving)

        # Cross-source first (issue #651: only 40.5% of argument-map edges
        # reach another book), then a deterministic total order. The
        # comparison set is this category's own landed sources (see above),
        # falling back to every landed source when no assignment record
        # named one -- a fallback that only ever makes the tier stricter, so
        # it can never silently promote a same-book neighbour.
        category_sources = landed_sources_by_category.get(category_id) or landed_sources
        candidates.sort(
            key=lambda item: (
                0 if item[1] not in category_sources else 1,
                item[2]["position_id"],
                item[0],
            )
        )
        cap_applied = len(candidates) > cap
        contributed = candidates[:cap]

        for chunk_id, source_id, position in contributed:
            position_id = position["position_id"]
            hit = hits.setdefault(
                position_id,
                {
                    "categories": set(),
                    "chunk_ids": [],
                    "position": position,
                    "cross_source": False,
                },
            )
            hit["categories"].add(category_id)
            hit["chunk_ids"].append(chunk_id)
            # Cross-source is a property of the EDGE, judged against the
            # category that made it (issue #807). A position pulled in by two
            # categories counts as cross-source if it is a different book
            # from the asking note under either of them -- the same "several
            # edges collapse to one position" reading `categories` itself
            # keeps, rather than re-deciding the question against a union
            # that no single edge was judged on.
            if source_id not in category_sources:
                hit["cross_source"] = True

        categories.append(
            CategoryReach(
                category_id=category_id,
                category_name=category_names.get(category_id, ""),
                # Distinct notes, in contribution order -- a note reached
                # through two of its own positions is one note offered, two
                # edges spent (issue #822).
                chunk_ids=tuple(
                    dict.fromkeys(chunk_id for chunk_id, _source_id, _position in contributed)
                ),
                source_count=len({source_id for _c, source_id, _p in contributed}),
                cap_applied=cap_applied,
            )
        )

    cross_source = {position_id: bool(hit["cross_source"]) for position_id, hit in hits.items()}
    vocabulary_positions = [
        VocabularyPosition(
            position_id=position_id,
            categories=tuple(sorted(hit["categories"])),
            chunk_ids=tuple(hit["chunk_ids"]),
            argument=hit["position"]["argument"],
            size=hit["position"]["size"],
            sources=tuple(hit["position"]["sources"]),
            authors=tuple(hit["position"]["authors"]),
        )
        for position_id, hit in hits.items()
    ]
    # Ordered by the same per-category judgment the cap already selected on
    # (issue #807), not re-derived here against the union of every landed
    # source -- two different answers to the same question in one function
    # is how the cap and the order came to disagree in the first cut.
    vocabulary_positions.sort(key=lambda vp: (0 if cross_source[vp.position_id] else 1, vp.position_id))

    return VocabularyJoinResult(
        column=column,
        level=resolved_level,
        cap=cap,
        categories=tuple(categories),
        positions=tuple(vocabulary_positions),
        reasons=reasons,
    )
