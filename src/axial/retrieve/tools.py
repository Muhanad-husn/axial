"""The §7.5 tool registry the retrieval loop exposes to the model (issue
#253 slice 01, extended to the name layer by issue #488, specs/PHASE-B.md
§7.5).

Every entry is a thin adapter: it calls exactly one query-API function (zero
LLM calls, per §7.5) and normalizes that function's return value into
`(ids, count)`, the shape the §7.6 trajectory log and the dispatcher's
`ToolResult` both carry.

`query_by_tag`, `query_by_polity` and `follow_backlinks` were de-registered
with the tools themselves (issue #487, D1/D5): each returned 0 or `[]` on
every call against the v1 vault. The name-layer tools that replace them --
`find_names`, `get_name`, `name_neighbors`, `who_cites`,
`who_argues_against` -- are registered here (issue #488), alongside the
per-name `coverage_count` slice 02 already re-pointed.

Two mechanical facts this registry states explicitly, because the model and
the dispatcher both need them and neither is free to assume the answer:

- **Arg types.** Every arg in the §7.5 tool set is a plain string EXCEPT
  `find_names`'/`name_neighbors`' `limit`, which is an int. `int_args`
  names the subset of a tool's `allowed_args` that are int-typed; every
  other allowed arg is str. Two types total -- no JSON-schema library is
  pulled in for that.
- **What kind of id a tool yields.** `find_names`, `name_neighbors` and
  `coverage_count` return CANONICAL NAMES. `get_name`, `who_cites`,
  `who_argues_against`, `query_by_source`, `get_chunk` and `get_artifact`
  return CHUNK/ARTIFACT ids -- real vault ids a claim's grounds may cite.
  `get_envelope` returns a `source_id`, neither. `returns_chunk_ids` marks
  the second group; `axial.retrieve.loop.assemble_evidence_ids` reads it so
  a name string can never land in the evidence set stage 4 treats as
  citable passages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.query import names, reader

# `(args, vault_dir, envelopes_dir, names_dir) -> (result_ids, result_count)`.
# Every adapter takes all four positional slots, even the three that ignore
# `names_dir` (the pre-name-layer tools) or `envelopes_dir` (everything but
# `get_envelope`) -- one uniform shape the dispatcher calls without
# branching on which tool it is calling.
ToolCall = Callable[[dict[str, Any], Path | None, Path | None, Path | None], tuple[list[str], int]]


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
) -> tuple[list[str], int]:
    ids = reader.query_by_source(args["source_id"], vault_dir=vault_dir)
    return ids, len(ids)


def _get_envelope(
    args: dict[str, Any],
    _vault_dir: Path | None,
    envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int]:
    envelope = reader.get_envelope(args["source_id"], envelopes_dir=envelopes_dir)
    return [envelope.source_id], 1


def _get_chunk(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int]:
    chunk = reader.get_chunk(args["chunk_id"], vault_dir=vault_dir)
    return [chunk.chunk_id], 1


def _get_artifact(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int]:
    artifact = reader.get_artifact(args["artifact_id"], vault_dir=vault_dir)
    return [artifact.artifact_id], 1


def _coverage_count(
    _args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int]:
    counts = names.coverage_count(vault_dir=vault_dir)
    canonicals = sorted(counts)
    return canonicals, len(canonicals)


def _find_names(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    hits = names.find_names(args["query"], limit, names_dir=names_dir, vault_dir=vault_dir)
    canonicals = [hit.canonical for hit in hits]
    return canonicals, len(canonicals)


def _get_name(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    _names_dir: Path | None,
) -> tuple[list[str], int]:
    page = names.get_name(args["canonical"], vault_dir=vault_dir)
    ids = [member.chunk_id for member in page.members]
    return ids, len(ids)


def _name_neighbors(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int]:
    limit = args.get("limit", names.DEFAULT_LIMIT)
    neighbors = names.name_neighbors(
        args["canonical"], limit, vault_dir=vault_dir, names_dir=names_dir
    )
    canonicals = [neighbor.canonical for neighbor in neighbors]
    return canonicals, len(canonicals)


def _who_cites(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int]:
    edges = names.who_cites(args["canonical"], vault_dir=vault_dir, names_dir=names_dir)
    ids = [edge.chunk_id for edge in edges]
    return ids, len(ids)


def _who_argues_against(
    args: dict[str, Any],
    vault_dir: Path | None,
    _envelopes_dir: Path | None,
    names_dir: Path | None,
) -> tuple[list[str], int]:
    edges = names.who_argues_against(args["canonical"], vault_dir=vault_dir, names_dir=names_dir)
    ids = [edge.chunk_id for edge in edges]
    return ids, len(ids)


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
            "year, one-sentence claim) in the page's own order, and any Gather "
            "disagreement section. A disagreement is a retrieval hint, never a citation "
            "(D4) -- follow its member chunk_ids to the real notes and cite only those."
        ),
        required_args=frozenset({"canonical"}),
        optional_args=frozenset(),
        int_args=frozenset(),
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
            "about -- an author-stated cross-book edge."
        ),
        required_args=frozenset({"canonical"}),
        optional_args=frozenset(),
        int_args=frozenset(),
        returns_chunk_ids=True,
        call=_who_cites,
    ),
    "who_argues_against": ToolSpec(
        name="who_argues_against",
        description=(
            "Every prose note whose arguing_against answers name this name, carrying "
            "that note's own stated position and one-sentence claim -- an author-stated "
            "opposition edge."
        ),
        required_args=frozenset({"canonical"}),
        optional_args=frozenset(),
        int_args=frozenset(),
        returns_chunk_ids=True,
        call=_who_argues_against,
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
    "coverage_count": ToolSpec(
        name="coverage_count",
        description="The member-note count of every name page in the vault, per name.",
        required_args=frozenset(),
        optional_args=frozenset(),
        int_args=frozenset(),
        returns_chunk_ids=False,
        call=_coverage_count,
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
