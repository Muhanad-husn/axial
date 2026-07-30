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
  hub name page returned 962 ids into a retrieval loop's prompt). `int_args`
  names the subset of a tool's `allowed_args` that are int-typed; every
  other allowed arg is str. Two types total -- no JSON-schema library is
  pulled in for that.
- **What kind of id a tool yields.** `find_names` and `name_neighbors`
  return CANONICAL NAMES. `get_name`, `who_cites`, `who_argues_against`,
  `where_names_meet`, `query_by_source`, `get_chunk` and `get_artifact`
  return CHUNK/ARTIFACT ids -- real vault ids a claim's grounds may cite.
  `get_envelope` returns a `source_id`, neither. `returns_chunk_ids` marks
  the second group; `axial.retrieve.loop.assemble_evidence_ids` reads it so
  a name string can never land in the evidence set stage 4 treats as
  citable passages.

Every adapter now returns `(result_ids, result_count, total, detail)`
(issues #505 and #517): `total` is the true pre-cap count for `get_name`/
`who_cites`/`who_argues_against`/`where_names_meet`, `None` for every other
tool. `detail` is set only by `find_names`, carrying each hit's `kind`,
`member_count` and `tier` so a model can tell an exact resolution from a
guess (§4's planner-blindness fix, issue #517) -- every other adapter passes
`None`. Both ride straight through to `axial.retrieve.dispatcher.ToolResult`,
never part of the §7.6 trajectory entry (which stays exactly `{step, tool,
args, result_ids, result_count}`).
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
    are int rather than str -- `returns_chunk_ids` (see the module
    docstring), and `call` -- the adapter that invokes the underlying
    `axial.query` function and returns `(result_ids, result_count)`."""

    name: str
    description: str
    required_args: frozenset[str]
    optional_args: frozenset[str]
    call: ToolCall
    int_args: frozenset[str]
    returns_chunk_ids: bool

    @property
    def allowed_args(self) -> frozenset[str]:
        return self.required_args | self.optional_args


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
    chunk = reader.get_chunk(args["chunk_id"], vault_dir=vault_dir)
    return [chunk.chunk_id], 1, None, None


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
    # Issue #517's planner-blindness fix: a bare canonical string cannot tell
    # the model an exact hit apart from an embedding guess. `detail` carries
    # what `find_names` already computed per hit -- no new lookup, no LLM
    # call -- so the next turn's prompt can show it.
    detail = (
        "; ".join(
            f"{hit.canonical} (kind={hit.kind}, member_count={hit.member_count}, tier={hit.tier})"
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
    return ids, len(ids), page.member_count, None


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
    return canonicals, len(canonicals), None, None


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
    return ids, len(ids), total, None


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "find_names": ToolSpec(
        name="find_names",
        description=(
            "Resolve a phrase (a scholar, concept or polity) to the canonical names the "
            "corpus actually carries -- tiered exact/alias/folded/embedding resolution, "
            "never string equality. Returns each hit's canonical, kind, member_count and "
            "which surface form and tier matched. An empty result is a real, honest "
            "resolution failure, not an error."
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
            "year, one-sentence claim) in the page's own order, up to limit, and any "
            "Gather disagreement section. A disagreement is a retrieval hint, never a "
            "citation (D4) -- follow its member chunk_ids to the real notes and cite "
            "only those."
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
        description="One prose chunk by chunk_id, with its frontmatter and text.",
        required_args=frozenset({"chunk_id"}),
        optional_args=frozenset(),
        int_args=frozenset(),
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
    type `"integer"`; every other allowed arg is `"string"` -- the honest
    reflection of `ToolSpec`'s own declared types."""
    specs: list[dict[str, Any]] = []
    for spec in TOOL_REGISTRY.values():
        properties = {
            arg_name: {"type": "integer" if arg_name in spec.int_args else "string"}
            for arg_name in spec.allowed_args
        }
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
