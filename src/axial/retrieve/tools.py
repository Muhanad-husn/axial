"""The §7.5 tool registry the retrieval loop exposes to the model (issue
#253 slice 01, specs/PHASE-B.md §7.5). This is `axial.analyze.examine`'s
tool palette (`axial brief examine`'s debug loop, and any future consumer of
`axial.retrieve.loop`'s tool-calling machinery) -- the name retrieval arm
that was `run_planned_retrieval`'s own production caller is retired (DEC-75,
issue #853).

Every entry is a thin adapter: it calls exactly one query-API function (zero
LLM calls, per §7.5) and normalizes that function's return value into
`(ids, count, total, detail)`, the shape the dispatcher's `ToolResult`
carries -- `ids`/`count` are exactly the §7.6 trajectory log's `result_ids`/
`result_count`; `total` (issue #505) and `detail` (issue #517) both ride
beside it, never inside it.

**`find_notes` is the entry point (DEC-62, issue #650).** It, `positions_on`
(`axial.argmap.ask`), `query_by_source`, `get_envelope`, `get_chunk` and
`get_artifact` are what remains of this registry: `find_notes` retrieves
notes filtered by a resolved name, publication years and sources, chaining
relations a single name's own page never could. The eight name-layer walk
tools this registry used to also carry -- `find_names`, `get_name`,
`name_neighbors`, `who_cites`, `who_argues_against`, `where_names_meet`,
`names_arguing_against`, `opposition_pairs` -- are retired (DEC-75, issue
#853) along with the name pages `find_names`/`get_name` used to walk to;
`find_names`/`get_name` themselves survive as plain functions
(`axial.query.names`), answered from the store, but are no longer
registered here as LLM-callable tools.

`query_by_tag`, `query_by_polity` and `follow_backlinks` were de-registered
earlier (issue #487, D1/D5) for the same reason: each returned 0 or `[]` on
every call against the v1 vault.

**`coverage_count` is NOT registered here (issue #505's own follow-up).**
On a paid corpus run a real provider's model chose to call it unprompted --
nothing scripted the call -- and got all 49,674 canonical names back in one
result, jumping the prompt from 3,862 to 1,204,509 characters (350,923
prompt tokens) and holding it there for 14 turns. §7.2 already ruled out
this exact shape for the interrogation pre-pass; the retrieval tool carried
the identical hazard, unguarded. The function itself
(`axial.query.names.coverage_count`) is untouched: §7.7's coverage map is
its real, deterministic, model-free consumer (`axial.validators.coverage`).

Two mechanical facts this registry states explicitly, because the model and
the dispatcher both need them and neither is free to assume the answer:

- **Arg types.** Every arg in the §7.5 tool set is a plain string EXCEPT
  `limit`, which is an int wherever it appears, and `get_chunk`'s
  `chunk_id`, which is a list of strings (issue #542). Three arg types
  total -- `int_args` and `str_list_args` name the subsets of a tool's
  `allowed_args` that are int- and list-typed, every other allowed arg is
  str, and no JSON-schema library is pulled in for that.
- **What kind of id a tool yields.** `find_notes`, `positions_on`,
  `query_by_source`, `get_chunk` and `get_artifact` return CHUNK/ARTIFACT
  ids -- real vault ids a claim's grounds may cite. `get_envelope` returns a
  `source_id`, neither. `returns_chunk_ids` marks the first group;
  `axial.retrieve.loop.assemble_evidence_ids` reads it so a name string can
  never land in the evidence set stage 4 treats as citable passages.

Every adapter returns `(result_ids, result_count, total, detail,
resolved_name)` (issues #505, #517, #493 and #650): `total` is `None` for
every tool except, since issue #542, the count of ids asked for on
`get_chunk` -- **but only when `get_chunk`'s own batch was actually
truncated by `limit` (issue #629's follow-up); `None` otherwise, even when
some requested id failed to resolve** (see `_get_chunk`'s own docstring for
the misleading-nudge bug an unconditional `total` re-created). `detail` is
set by `find_notes`/`positions_on` (their own resolution and span detail)
and by `get_chunk` (issue #629, which ids in its batch failed to resolve, so
a typo reads as a typo rather than a silent drop in `result_count`). Every
other adapter passes `None`. Both `total` and `detail` ride straight through
to `axial.retrieve.dispatcher.ToolResult`, and are now ALSO persisted onto
the §7.6 trajectory entry itself (`axial.retrieve.loop.run_retrieval_loop`,
issue #493) -- see that module for why the record needed them, not only the
next turn's prompt.

**`find_notes`/`positions_on` also say what their name argument RESOLVED
TO** (`_resolution_detail`), which is the half of a result `_note_span_detail`
and the rest cannot describe: they say what came back, and an empty result's
only remaining fact is what was looked for. A live paired run measured a
model asking `find_notes(about="violence against civilians Syria")` six
times in a row against a bare `0/0` -- 25 of 42 steps returned zero because
a descriptive phrase never became a name -- and the run had no way to see
that from the result. Loop-side memory of "you already asked this" is NOT
the fix and is not built here: #633 measured it and repeats rose (14% ->
20%).

**They also report the canonical they landed on as `resolved_name`, the
fifth element of `ToolOutcome`** (`_resolved_name`, issue #650's second
follow-up): `detail` says it in prose for the model, `resolved_name` says it
as data for the record, because §7.7's coverage scope and §7.13's
denominator both read the trajectory. A call that resolved nothing reports
`None`: an unresolved phrase is not a queried name.

**`get_chunk` reads a BATCH (issue #542).** `chunk_id` takes a list of ids
and the tool returns them together, because a read per model round trip is
what the tail of a real brief run is made of. A bare string is still
accepted -- the model will emit both forms, and a hard error on the old one
costs a full turn -- and the batch is bounded by the SAME
`limit`/`names.DEFAULT_LIMIT` mechanism every other bounded tool uses
(issue #505), never a second cap invented here. `total` carries the pre-cap
count of ids ASKED FOR when the batch was actually truncated by `limit`, so
a truncated batch is never silent -- and `None` otherwise, even when some
requested id failed to resolve (issue #629's own follow-up; see
`_get_chunk`'s own docstring for the misleading-nudge bug an unconditional
`total` re-created). One call is still one §7.6 trajectory entry, with every
returned id in that entry's `result_ids`. **An id that fails to resolve no
longer fails the whole call (issue #629's own follow-up):** it is skipped
and named in `detail` instead -- see `_get_chunk`'s own docstring for the
live run that found this the hard way.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.query import names, reader, relations

# What every adapter returns: `(result_ids, result_count, total, detail,
# resolved_name)`. `total` is `None` for every tool but `get_chunk` (issues
# #505, #517); `detail` is `None` for every tool but `find_notes`/
# `positions_on` (#650) and `get_chunk` (#629); `resolved_name` is set by
# `find_notes`/`positions_on` alone.
ToolOutcome = tuple[list[str], int, int | None, str | None, str | None]

# `(args, vault_dir, envelopes_dir, names_dir, map_dir) -> ToolOutcome`.
# Every adapter takes all five positional slots, even the ones that ignore
# `names_dir` (`query_by_source`, `get_envelope`, `get_chunk`,
# `get_artifact`) or `envelopes_dir` (everything but `get_envelope`) or
# `map_dir` (everything but `positions_on`, issue #650) -- one uniform shape
# the dispatcher calls without branching on which tool it is calling.
ToolCall = Callable[
    [dict[str, Any], Path | None, Path | None, Path | None, Path | None],
    ToolOutcome,
]


@dataclass(frozen=True)
class ToolSpec:
    """One registry entry: a model-facing `name`, a `description` (fed to a
    real provider's tool schema), the args it accepts split into
    `required_args`/`optional_args`, `int_args` -- the subset of those that
    are int rather than str -- `str_list_args` -- the subset that take a
    list of strings (`get_chunk`'s `chunk_id`, issue #542; a bare string is
    tolerated there too, see the module docstring) -- `returns_chunk_ids`
    (see the module docstring), and `call` -- the adapter that invokes the
    underlying `axial.query` function and returns
    `(result_ids, result_count)`."""

    name: str
    description: str
    required_args: frozenset[str]
    optional_args: frozenset[str]
    call: ToolCall
    int_args: frozenset[str]
    returns_chunk_ids: bool
    str_list_args: frozenset[str] = frozenset()

    @property
    def allowed_args(self) -> frozenset[str]:
        return self.required_args | self.optional_args


def _query_by_source(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
    _map_dir: Path | None,
) -> ToolOutcome:
    ids = reader.query_by_source(args["source_id"], vault_dir=vault_dir)
    return ids, len(ids), None, None, None


def _get_envelope(
    args: dict[str, Any],
    _vault_dir: Path | None,
    envelopes_dir: Path | None,
    _names_dir: Path | None,
    _map_dir: Path | None,
) -> ToolOutcome:
    envelope = reader.get_envelope(args["source_id"], envelopes_dir=envelopes_dir)
    return [envelope.source_id], 1, None, None, None


def _get_chunk(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
    _map_dir: Path | None,
) -> ToolOutcome:
    """One or many prose notes (issue #542). `chunk_id` is a list of ids, or
    a single id as a bare string; the batch is truncated at `limit`, and
    `total` is the pre-cap count of ids ASKED FOR -- but, unlike the
    original #542 version of this function, **only when the batch actually
    WAS truncated** (`len(chunk_ids) > limit`), `None` otherwise, the same
    convention every other non-truncating tool already uses.

    An id that resolves to no note is SKIPPED, not fatal to the whole call
    (issue #629 -- #630's "a dangling record fails its own metric, not the
    whole batch" one layer down). The #542 measurement across the seven
    smoke records (44 calls, none hit a bad id) is why the original version
    of this function let one bad id raise for the whole call; a later live
    run did hit one -- asked for 10 ids, got 0 back, because a single hyphen
    was missing from one ~100-character transcribed id, then spent its next
    turn re-asking 8 of the same 9 good ids to get 8 back. Every id that
    resolves still comes back in `result_ids`; every id that does not is
    named in `detail`, so a typo reads as a typo rather than a silent zero.

    **Why `total` narrows to "truncated only" (issue #629's own follow-up,
    caught in review before merge).** The first version of this fix kept
    `total = len(chunk_ids)` unconditionally, exactly as #542 had it. That
    re-created the bug #629 exists to fix through a new door: 10 ids asked
    for, 1 unresolved, 9 resolved -- `total(10) > count(9)` reads as CAPPED
    in the loop's own feedback ("9 of 10 total -- re-ask with a larger limit
    for more"), which is false; the missing one isn't sitting past `limit`,
    it just does not exist. That is the exact misleading nudge that made a
    live run cycle `limit` 20/15/10/15/20 on an already-exhausted
    `where_names_meet` call, now reachable through `get_chunk` too. Setting
    `total` only on genuine truncation makes all three shapes read correctly
    in the loop: truncated, all resolve -> CAPPED (more really is unasked);
    truncated, some also unresolved -> CAPPED, plus `detail` names the bad
    ones; not truncated, some unresolved -> no CAPPED note, only `detail`.
    **Not truncated never reads as EXHAUSTED either**, and correctly so: a
    truncated batch's `count` is always strictly below its `total` (only the
    first `limit` ids are ever attempted), so EXHAUSTED (`total == count`)
    can never fire here regardless -- which is the right absence, since
    "exhausted" describes a query whose corpus-side size the model could not
    see in advance, and a `get_chunk` batch is a list the model wrote itself."""
    requested = args["chunk_id"]
    chunk_ids = [requested] if isinstance(requested, str) else list(requested)
    limit = args.get("limit", names.DEFAULT_LIMIT)
    ids: list[str] = []
    unresolved: list[str] = []
    for chunk_id in chunk_ids[:limit]:
        try:
            ids.append(reader.get_chunk(chunk_id, vault_dir=vault_dir).chunk_id)
        except reader.QueryError:
            unresolved.append(chunk_id)
    detail = f"{len(unresolved)} id(s) did not resolve: {unresolved}" if unresolved else None
    total = len(chunk_ids) if len(chunk_ids) > limit else None
    return ids, len(ids), total, detail, None


def _get_artifact(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
    _map_dir: Path | None,
) -> ToolOutcome:
    artifact = reader.get_artifact(args["artifact_id"], vault_dir=vault_dir)
    return [artifact.artifact_id], 1, None, None, None


def _resolution_detail(resolution: relations.Resolution | None) -> str | None:
    """What a store-backed tool's name argument resolved to, for the four
    tools of issue #650, and the other names that phrase also reaches.

    **A zero result must say what it tried (issue #650's own follow-up).**
    The live paired run measured a model asking
    `find_notes(about="violence against civilians Syria")` six times in a
    row against a bare `0/0`: the phrase never became a name, and nothing in
    the result said so, so re-asking the same words was the only move it
    had. `_note_span_detail` and the position/pair details below describe
    what came BACK; this describes what was LOOKED FOR, which is the half
    an empty result has left.

    **The alternatives are stated on a NON-empty result too, and that is
    the case that needs them most.** Re-measured against the live store
    after the resolver was widened: `violence against civilians Syria` now
    reaches `Filipino civilians` -- one note -- because `find_names` orders
    a compound query's words rarest-first (#632), which is right for a
    slate a model picks from and wrong for a head taken automatically. One
    note is not a zero, so it does not look like a failure; `Syria` and
    `violence` sat third and second in the same slate, unshown. A thin
    answer to the wrong door is worse than an honest zero, and the fix is
    to show the slate, not to re-rank it -- size-ranking a
    relevance-filtered set was measured to drift to hubs (#632, PR #522).

    Silent in the two cases where it would only add noise: `resolution`
    `None` (no store, or no argument map -- no resolution was attempted and
    saying "nothing matched" would be a lie), and a phrase that resolved
    exactly to itself, where naming the resolution repeats the caller's own
    argument back at it."""
    if resolution is None:
        return None
    parts: list[str] = []
    if not resolution.resolved:
        parts.append(
            f"{resolution.surface!r} matched no name this corpus carries -- "
            "the phrase itself and each of its words were tried"
        )
    elif resolution.canonical != resolution.surface:
        hit = resolution.slate[0] if resolution.slate else None
        tier = hit.tier if hit is not None else resolution.tier
        counts = (
            f", member_count={hit.member_count}, source_count={hit.source_count}"
            if hit is not None
            else ""
        )
        parts.append(
            f"{resolution.surface!r} resolved to {resolution.canonical!r} (tier={tier}{counts})"
        )
    if len(resolution.slate) > 1:
        parts.append(
            "other names this phrase reaches: "
            + ", ".join(
                f"{hit.canonical} (member_count={hit.member_count}, "
                f"source_count={hit.source_count})"
                for hit in resolution.slate[1:]
            )
        )
    return "; ".join(parts) or None


def _resolved_name(resolution: relations.Resolution | None) -> str | None:
    """The canonical a store-backed tool's name argument actually landed on,
    for the four tools of issue #650 -- the fifth element of `ToolOutcome`,
    carried through `ToolResult.resolved_name` onto the §7.6 trajectory entry
    so §7.7's coverage scope and §7.13's denominator can read what the run
    leaned on (issue #650's own second follow-up).

    Before this, neither could: both read the name-layer tools' `canonical`
    argument, and a relational tool's argument is a phrase the caller wrote
    (`about="violence against civilians Syria"`), not a canonical. Measured
    over three hard briefs, moving the walk onto these tools took the
    coverage map from 11/5/8 entries to 2/0/1, and brief B -- 23 composed
    notes, 18 claims -- reported `not_measured`. A confident band computed
    from a near-empty map is worse than an honest `not_measured`, and a
    coverage map with nothing in it is the "computation over nothing" #490
    exists to prevent.

    **A call that resolved nothing records nothing.** `None` both when no
    resolution was attempted (no store, no argument map) and when every tier
    missed -- `resolve_name` falls back to querying the surface verbatim, but
    an unresolved phrase is not a name the corpus carries and must not enter
    a per-name map or a denominator as if it were."""
    if resolution is None or not resolution.resolved:
        return None
    return resolution.canonical


def _joined(*parts: str | None) -> str | None:
    """The non-`None` `detail` parts of one tool result, joined -- a tool
    that both resolved a phrase and found something says both."""
    return "; ".join(part for part in parts if part) or None


def _note_span_detail(rows: list[relations.NoteRow]) -> str | None:
    """`find_notes`' own `detail`: the same `"<N> notes across <M> sources"`
    span `_source_span_detail` gives a name page, plus the DISTINCT stated
    positions the returned notes carry. The positions are the answer to
    "positions on X held by authors who disagree with Y" -- the question
    this tool exists for -- and they are a note field no other tool's
    feedback surfaces (§7.5's own per-id metadata carries author, year and
    claim, never `position`). Deduplicated in return order, so a window of
    ten notes from one school states that school once."""
    if not rows:
        return None
    source_count = len({row.source_id for row in rows})
    detail = f"{len(rows)} notes across {source_count} sources"
    positions = list(dict.fromkeys(row.position for row in rows if row.position))
    if positions:
        detail += "; positions: " + "; ".join(positions)
    return detail


def _find_notes(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
    _map_dir: Path | None,
) -> ToolOutcome:
    rows, total, resolution = relations.find_notes(
        args["about"],
        args.get("limit", names.DEFAULT_LIMIT),
        opposing=args.get("opposing"),
        published_after=args.get("published_after"),
        published_before=args.get("published_before"),
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    ids = [row.chunk_id for row in rows]
    detail = _joined(
        _resolution_detail(resolution),
        _note_span_detail(rows),
    )
    # `about` alone, never `opposing`: the filter narrows which notes come
    # back, it does not change which name the run leaned on, and the rows
    # returned are members of `about`'s page and of no other.
    return ids, len(ids), total, detail, _resolved_name(resolution)


def _positions_on(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
    map_dir: Path | None,
) -> ToolOutcome:
    """The argument map's positions a name reaches (issue #650). `detail`
    carries each position's own argument SENTENCE, which is the point of the
    layer: a position states an argument several passages make, in words a
    model can judge, where a bare chunk id cannot.

    **`axial.argmap.ask` is imported here, not at module scope**: it pulls
    `axial.argmap.build`, which pulls the whole ingestion stack
    (`axial.extract`, `axial.intake`), taking this module's own warm import
    from ~0.27s to ~1.1s for a build-side dependency no tool here uses. The
    map's positions are plain JSON."""
    from axial.argmap.ask import positions_on

    positions, ids, total, resolution = positions_on(
        args["name"],
        args.get("limit", names.DEFAULT_LIMIT),
        map_dir=map_dir,
        vault_dir=vault_dir,
        names_dir=names_dir,
    )
    detail = _joined(
        _resolution_detail(resolution),
        "; ".join(
            f"{position.position_id} ({position.size} passages across "
            f"{len(position.sources)} sources, {position.matched_note_count} naming it): "
            f"{position.argument}"
            for position in positions
        ),
    )
    return ids, len(ids), total, detail, _resolved_name(resolution)


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "find_notes": ToolSpec(
        name="find_notes",
        description=(
            "The notes themselves, filtered. Every prose note whose own names answer "
            "carries `about` (a concept, scholar, work, place or period -- written "
            "however you like, a phrase or a name; it is resolved against the names the "
            "corpus carries first, so 'Tilly' reaches 'Charles Tilly' and a descriptive "
            "phrase reaches the closest name it contains, which the result names), "
            "narrowed by "
            "any of: `opposing`, keeping only notes from sources that argue against "
            "that name somewhere -- 'positions on X held by authors who disagree with "
            "Y'; `published_after` / `published_before`, keeping only sources published "
            "strictly after / before that year. Returns the notes, spread across the "
            "sources they come from, with how many sources they span and the distinct "
            "positions they state. This is the first tool to reach for: it chains "
            "relations a single name page cannot."
        ),
        required_args=frozenset({"about"}),
        optional_args=frozenset({"opposing", "published_after", "published_before", "limit"}),
        int_args=frozenset({"limit", "published_after", "published_before"}),
        returns_chunk_ids=True,
        call=_find_notes,
    ),
    "positions_on": ToolSpec(
        name="positions_on",
        description=(
            "The arguments the corpus makes about this name, as positions from the "
            "argument map: each one is a single contestable sentence with the passages "
            "from every book that make it standing behind it. A position says what is "
            "argued, where a name page only says who mentioned what. Returns those "
            "passages as citable notes, spread across books, with each position's own "
            "argument sentence in the detail. Empty when this corpus has no argument "
            "map built."
        ),
        required_args=frozenset({"name"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        returns_chunk_ids=True,
        call=_positions_on,
    ),
    "query_by_source": ToolSpec(
        name="query_by_source",
        description="Every chunk_id belonging to the given source_id.",
        required_args=frozenset({"source_id"}),
        optional_args=frozenset(),
        int_args=frozenset(),
        returns_chunk_ids=True,
        call=_query_by_source,
    ),
    "get_envelope": ToolSpec(
        name="get_envelope",
        description=(
            "The per-source envelope for source_id: thesis, nested toc, scope, stated_argument."
        ),
        required_args=frozenset({"source_id"}),
        optional_args=frozenset(),
        int_args=frozenset(),
        returns_chunk_ids=False,
        call=_get_envelope,
    ),
    "get_chunk": ToolSpec(
        name="get_chunk",
        description=(
            "Prose chunks by chunk_id, with their frontmatter and text. Takes one id or "
            "a list of ids, so several notes are read in a single call rather than one "
            "call per note, up to limit."
        ),
        required_args=frozenset({"chunk_id"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        str_list_args=frozenset({"chunk_id"}),
        returns_chunk_ids=True,
        call=_get_chunk,
    ),
    "get_artifact": ToolSpec(
        name="get_artifact",
        description="One artifact (figure/table/etc.) by artifact_id.",
        required_args=frozenset({"artifact_id"}),
        optional_args=frozenset(),
        int_args=frozenset(),
        returns_chunk_ids=True,
        call=_get_artifact,
    ),
}


def tool_specs_for_provider() -> list[dict[str, Any]]:
    """The registry rendered into the OpenAI/OpenRouter function-calling
    `tools` payload shape (`OpenRouterClient.complete_with_tools` sends this
    list verbatim). An arg named in a spec's `int_args` is emitted as JSON
    type `"integer"`, one named in `str_list_args` as an array of strings,
    every other allowed arg as `"string"` -- the honest reflection of
    `ToolSpec`'s own declared types. A `str_list_args` arg is advertised as
    the array alone rather than as a string/array union: the batch is the
    shape the model is asked for, a union type is the shape strict function-
    calling modes reject, and the dispatcher separately TOLERATES a bare
    string there (issue #542) so a model that emits the old single-id form
    does not burn a turn on a schema error."""
    specs: list[dict[str, Any]] = []
    for spec in TOOL_REGISTRY.values():
        properties: dict[str, dict[str, Any]] = {}
        for arg_name in spec.allowed_args:
            if arg_name in spec.int_args:
                properties[arg_name] = {"type": "integer"}
            elif arg_name in spec.str_list_args:
                properties[arg_name] = {"type": "array", "items": {"type": "string"}}
            else:
                properties[arg_name] = {"type": "string"}
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": sorted(spec.required_args),
                        "additionalProperties": False,
                    },
                },
            }
        )
    return specs
