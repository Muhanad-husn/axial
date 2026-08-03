"""The §7.5 tool registry the retrieval loop exposes to the model (issue
#253 slice 01, extended to the name layer by issue #488, specs/PHASE-B.md
§7.5).

Every entry is a thin adapter: it calls exactly one query-API function (zero
LLM calls, per §7.5) and normalizes that function's return value into
`(ids, count, total, detail)`, the shape the dispatcher's `ToolResult`
carries -- `ids`/`count` are exactly the §7.6 trajectory log's `result_ids`/
`result_count`; `total` (issue #505) and `detail` (issue #517) both ride
beside it, never inside it.

`query_by_tag`, `query_by_polity` and `follow_backlinks` were de-registered
with the tools themselves (issue #487, D1/D5): each returned 0 or `[]` on
every call against the v1 vault. The name-layer tools that replace them --
`find_names`, `get_name`, `name_neighbors`, `who_cites`,
`who_argues_against` -- are registered here (issue #488), joined by
`where_names_meet` (issue #517), the intersection of two name pages'
members.

**`coverage_count` is NOT registered here (issue #505's own follow-up).**
It is the mirror case of D1/D5: not de-registered for returning nothing
useful, but for returning far too much. On a paid corpus run a real
provider's model chose to call it unprompted -- nothing scripted the call --
and got all 49,674 canonical names back in one result,
jumping the prompt from 3,862 to 1,204,509 characters (350,923 prompt
tokens) and holding it there for 14 turns -- 4,947,176 prompt tokens for
that run alone, thirteen times the flood #505 itself fixed. §7.2 already
ruled out this exact shape for the interrogation pre-pass ("rendering the
whole index instead is out of the question: measured 2026-07-30 at 62,821
rows, 2.08 MB, ~500k tokens"); the retrieval tool carried the identical
hazard, unguarded. A `limit` would bound the tokens without making the
tool useful -- the alphabetical head of 49,674 names answers no retrieval
question -- and the model already gets `member_count` per name, the count
it can actually act on, from `find_names` and `get_name`. The function
itself (`axial.query.names.coverage_count`) is untouched: §7.7's coverage
map is its real, deterministic, model-free consumer
(`axial.validators.coverage`).

Two mechanical facts this registry states explicitly, because the model and
the dispatcher both need them and neither is free to assume the answer:

- **Arg types.** Every arg in the §7.5 tool set is a plain string EXCEPT
  `limit`, which is an int wherever it appears -- `find_names`,
  `name_neighbors`, and, as of issue #505, `get_name`, `who_cites` and
  `who_argues_against` too (all five were unbounded or capless before; the
  last three used to return every matching row, and one `get_name` on a
  hub name page returned 962 ids into a retrieval loop's prompt) -- and
  `get_chunk`'s `chunk_id`, which is a list of strings (issue #542). Three
  arg types total -- `int_args` and `str_list_args` name the subsets of a
  tool's `allowed_args` that are int- and list-typed, every other allowed
  arg is str, and no JSON-schema library is pulled in for that.
- **What kind of id a tool yields.** `find_names` and `name_neighbors`
  return CANONICAL NAMES. `get_name`, `who_cites`, `who_argues_against`,
  `where_names_meet`, `query_by_source`, `get_chunk` and `get_artifact`
  return CHUNK/ARTIFACT ids -- real vault ids a claim's grounds may cite.
  `get_envelope` returns a `source_id`, neither. `returns_chunk_ids` marks
  the second group; `axial.retrieve.loop.assemble_evidence_ids` reads it so
  a name string can never land in the evidence set stage 4 treats as
  citable passages.

Every adapter now returns `(result_ids, result_count, total, detail)`
(issues #505, #517 and #493): `total` is the true pre-cap count for
`get_name`/`who_cites`/`who_argues_against`/`where_names_meet`, and, since
issue #542, the count of ids asked for on `get_chunk` -- **but only when
`get_chunk`'s own batch was actually truncated by `limit` (issue #629's
follow-up); `None` otherwise, even when some requested id failed to
resolve, exactly like every other non-truncating tool below** (see
`_get_chunk`'s own docstring for the misleading-nudge bug an unconditional
`total` re-created). `None` for every other tool. `detail` is set by five
tools. Four are a planner-blindness fix
(§4, issues #517/#493, extended by #632's door slate) -- `find_names`
carries each hit's `kind`, `member_count`, `source_count` and `tier` so a
model can tell an exact resolution from a guess, and a big same-family door
from a small one; `get_name` and `where_names_meet` carry `_source_span_detail`'s
`"<N> notes across <M> sources"` over the members actually returned, so a
model can tell a large page (or intersection) is one book from many without
re-reading it; `name_neighbors` carries `_shared_note_count_distribution`'s
compact min/median/max/floor-count summary over the neighbours actually
returned (issue #493 -- see that function's own docstring for why a summary,
never one line per neighbour). The fifth, `get_chunk` (issue #629), names
whichever ids in its batch failed to resolve, so a typo reads as a typo
rather than a silent drop in `result_count` -- see `_get_chunk`'s own
docstring. Every other adapter passes `None`. Both `total` and `detail`
ride straight through to `axial.retrieve.dispatcher.ToolResult`, and are
now ALSO persisted onto the §7.6 trajectory entry itself
(`axial.retrieve.loop.run_retrieval_loop`, issue #493) -- see that module
for why the record needed them, not only the next turn's prompt.

**A live corpus run measured why `get_name`/`where_names_meet` need this
too, not just `find_names` (issue #517's own follow-up).** A model told to
call `where_names_meet` only on a "large" resolved name avoided it entirely
by resolving narrow names instead -- `Syrian nationalism` (24 members) is
83.3% one source because only the one book about Syrian nationalism uses
that phrase. Narrowing felt like precision and produced a one-book answer;
`_source_span_detail` makes the number of sources a result actually spans
checkable in the next prompt rather than something the model has to infer
from how specific a name sounds.

**`get_chunk` reads a BATCH (issue #542).** `chunk_id` takes a list of ids
and the tool returns them together, because a read per model round trip is
what the tail of a real brief run is made of: replayed over seven persisted
smoke records, `get_chunk` was called 44 times, contributed zero new ids to
the evidence set every single time (the id was always already surfaced by
the `get_name` that listed it), and 24 of those 44 calls sat in a run of
consecutive `get_chunk` calls one batched call collapses. A bare string is
still accepted -- the model will emit both forms, and a hard error on the
old one costs a full turn -- and the batch is bounded by the SAME
`limit`/`names.DEFAULT_LIMIT` mechanism every other bounded tool uses
(issue #505), never a second cap invented here: an unbounded id list is the
same "one call pulls the index into the prompt" hazard #505 fixed. `total`
carries the pre-cap count of ids ASKED FOR when the batch was actually
truncated by `limit`, so a truncated batch is never silent -- and `None`
otherwise, even when some requested id failed to resolve (issue #629's own
follow-up; see `_get_chunk`'s own docstring for the misleading-nudge bug an
unconditional `total` re-created). One call is still one §7.6 trajectory
entry, with every returned id in that entry's `result_ids`. **An id that
fails to resolve no longer fails the whole call (issue #629's own
follow-up):** it is skipped and named in `detail` instead -- see
`_get_chunk`'s own docstring for the live run that found this the hard way.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.query import names, reader

# `(args, vault_dir, envelopes_dir, names_dir) ->
# (result_ids, result_count, total, detail)`. Every adapter takes all four
# positional slots, even the four that ignore `names_dir` (`query_by_source`,
# `get_envelope`, `get_chunk`, `get_artifact` -- the pre-name-layer tools) or
# `envelopes_dir` (everything but `get_envelope`) -- one uniform shape the
# dispatcher calls without branching on which tool it is calling. `get_name`
# now resolves its own `canonical` through `names_dir` too, the same alias
# resolution `find_names`/`name_neighbors`/`who_cites`/`who_argues_against`/
# `where_names_meet` already apply. `total` is `None` for every tool but
# `get_name`/`who_cites`/`who_argues_against`/`where_names_meet` (issues
# #505, #517); `detail` is `None` for every tool but `find_names` (#517).
ToolCall = Callable[
    [dict[str, Any], Path | None, Path | None, Path | None],
    tuple[list[str], int, int | None, str | None],
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


def _source_span_detail(members: list[names.NameMember]) -> str | None:
    """`"<N> notes across <M> sources"` over the members a tool actually
    returned (never the pre-cap total) -- `get_name`/`where_names_meet`'s own
    `detail`, counting DISTINCT `source_id` values so a model can tell a
    large page or intersection is one book from several without re-reading
    it. `None` only when there is nothing to describe (an empty result)."""
    if not members:
        return None
    source_count = len({member.source_id for member in members})
    return f"{len(members)} notes across {source_count} sources"


def _shared_note_count_distribution(neighbors: list[names.NameNeighbor]) -> str | None:
    """`name_neighbors`' own `detail` (issue #493): a compact summary of the
    `shared_note_count` spread over the neighbours actually returned, never
    one line per neighbour. Measured on the real index, `name_neighbors('state
    formation')` returns 30 neighbours of which 26 sit at `shared_note_count`
    1, ordered alphabetically from there -- a ranked list whose ranking
    carries no signal past the head, and a run's record could not previously
    say so: the returned ids are bare canonical strings with no count
    attached anywhere in the persisted trajectory. A model can (and does) ask
    for a large `limit`, so this states four numbers regardless of how many
    neighbours came back -- min, median, max, and how many sit at that
    floor -- rather than growing linearly with the result the way
    `result_ids` already does. `None` only when there is nothing to
    describe (an empty result)."""
    if not neighbors:
        return None
    counts = sorted(neighbor.shared_note_count for neighbor in neighbors)
    count = len(counts)
    middle = count // 2
    median = counts[middle] if count % 2 else (counts[middle - 1] + counts[middle]) / 2
    # An even-count average of two equal counts (e.g. two neighbours tied at
    # 1) is a whole number that Python's `/` still renders as `1.0` -- shown
    # as a bare int instead, so "the middle of the ranking" reads the same
    # whether it landed on one neighbour's count or split two of them.
    if isinstance(median, float) and median.is_integer():
        median = int(median)
    floor = counts[0]
    at_floor = sum(1 for value in counts if value == floor)
    return (
        f"{count} neighbors, shared_note_count min={floor} median={median} max={counts[-1]} "
        f"({at_floor} of {count} at the floor of {floor})"
    )


def _query_by_source(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    ids = reader.query_by_source(args["source_id"], vault_dir=vault_dir)
    return ids, len(ids), None, None


def _get_envelope(
    args: dict[str, Any],
    _vault_dir: Path | None,
    envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    envelope = reader.get_envelope(args["source_id"], envelopes_dir=envelopes_dir)
    return [envelope.source_id], 1, None, None


def _get_chunk(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
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
    return ids, len(ids), total, detail


def _get_artifact(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    artifact = reader.get_artifact(args["artifact_id"], vault_dir=vault_dir)
    return [artifact.artifact_id], 1, None, None


def _find_names(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    hits = names.find_names(args["query"], limit, names_dir=names_dir, vault_dir=vault_dir)
    canonicals = [hit.canonical for hit in hits]
    # Issue #517's planner-blindness fix, extended by #632's door slate:
    # `detail` carries what `find_names` already computed per hit -- no new
    # lookup, no LLM call -- so the next turn's prompt can show a 55-note/
    # 8-source door next to a 3-note/3-source one and let the model pick.
    detail = (
        "; ".join(
            f"{hit.canonical} (kind={hit.kind}, member_count={hit.member_count}, "
            f"source_count={hit.source_count}, tier={hit.tier})"
            for hit in hits
        )
        or None
    )
    return canonicals, len(canonicals), None, detail


def _get_name(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    page = names.get_name(args["canonical"], limit, vault_dir=vault_dir, names_dir=names_dir)
    ids = [member.chunk_id for member in page.members]
    return ids, len(ids), page.member_count, _source_span_detail(page.members)


def _name_neighbors(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    neighbors = names.name_neighbors(
        args["canonical"], limit, vault_dir=vault_dir, names_dir=names_dir
    )
    canonicals = [neighbor.canonical for neighbor in neighbors]
    return canonicals, len(canonicals), None, _shared_note_count_distribution(neighbors)


def _who_cites(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    edges, total = names.who_cites(
        args["canonical"], limit, vault_dir=vault_dir, names_dir=names_dir
    )
    ids = [edge.chunk_id for edge in edges]
    return ids, len(ids), total, None


def _who_argues_against(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    edges, total = names.who_argues_against(
        args["canonical"], limit, vault_dir=vault_dir, names_dir=names_dir
    )
    ids = [edge.chunk_id for edge in edges]
    return ids, len(ids), total, None


def _where_names_meet(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int, int | None, str | None]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    members, total = names.where_names_meet(
        args["canonical"], args["other"], limit, vault_dir=vault_dir, names_dir=names_dir
    )
    ids = [member.chunk_id for member in members]
    return ids, len(ids), total, _source_span_detail(members)


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "find_names": ToolSpec(
        name="find_names",
        description=(
            "Resolve a phrase (a scholar, concept or polity) to a slate of doors the "
            "corpus actually carries -- every page whose name matches or contains the "
            "phrase, ranked by how many notes and sources it spans, topped up with "
            "embedding matches only if that literal set is short of limit. A bigger "
            "same-family page (e.g. 'French Mandate', 55 notes/8 sources) is offered "
            "alongside a narrower exact hit (e.g. 'Mandate', 3 notes/3 sources), never "
            "suppressed by it. If the phrase matches no page at all, its individual "
            "words are each resolved instead and marked tier=word. Returns each hit's "
            "canonical, kind, member_count, source_count and which surface form and "
            "tier matched. An empty result is a real, honest resolution failure, not an "
            "error."
        ),
        required_args=frozenset({"query"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        returns_chunk_ids=False,
        call=_find_names,
    ),
    "get_name": ToolSpec(
        name="get_name",
        description=(
            "One name page by its canonical name: its member notes (chunk_id, author, "
            "year, one-sentence claim), up to limit, and any Gather disagreement "
            "section. When limit covers every member they come back in the page's own "
            "order; when it truncates, the window is spread across sources (one member "
            "per source in rotation) rather than a prefix, so a small limit still "
            "reaches a source that sorts late alphabetically. A disagreement is a "
            "retrieval hint, never a citation (D4) -- follow its member chunk_ids to "
            "the real notes and cite only those."
        ),
        required_args=frozenset({"canonical"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        returns_chunk_ids=True,
        call=_get_name,
    ),
    "name_neighbors": ToolSpec(
        name="name_neighbors",
        description=(
            "The names that co-occur with this one in some note's own `names` answers, "
            "ranked by how many notes they share -- the cheapest real edge the "
            "interrogation produced."
        ),
        required_args=frozenset({"canonical"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        returns_chunk_ids=False,
        call=_name_neighbors,
    ),
    "who_cites": ToolSpec(
        name="who_cites",
        description=(
            "Every prose note whose citations[].cited resolves to this name, carrying "
            "the author's own stance (support/foil/authority) and what the citation is "
            "about -- an author-stated cross-book edge, up to limit."
        ),
        required_args=frozenset({"canonical"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        returns_chunk_ids=True,
        call=_who_cites,
    ),
    "who_argues_against": ToolSpec(
        name="who_argues_against",
        description=(
            "Every prose note whose arguing_against answers name this name, carrying "
            "that note's own stated position and one-sentence claim -- an author-stated "
            "opposition edge, up to limit."
        ),
        required_args=frozenset({"canonical"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        returns_chunk_ids=True,
        call=_who_argues_against,
    ),
    "where_names_meet": ToolSpec(
        name="where_names_meet",
        description=(
            "The notes that are members of BOTH of two name pages -- e.g. a polity "
            "intersected with a concept, scholar or event -- so the anchor filters and "
            "the intellectual name carries the query, up to limit. An empty intersection "
            "is a real, honest answer, not an error. Reach for this instead of reading a "
            "large name's page whole."
        ),
        required_args=frozenset({"canonical", "other"}),
        optional_args=frozenset({"limit"}),
        int_args=frozenset({"limit"}),
        returns_chunk_ids=True,
        call=_where_names_meet,
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
