"""The §7.5 tool registry the retrieval loop exposes to the model (issue
#253 slice 01, specs/PHASE-B.md §7.5).

Every entry is a thin adapter: it calls exactly one query-API function (zero
LLM calls, per §7.5) and normalizes that function's return value into
`(ids, count)`, the shape the §7.6 trajectory log and the dispatcher's
`ToolResult` both carry.

`query_by_tag`, `query_by_polity` and `follow_backlinks` were de-registered
with the tools themselves (issue #487, D1/D5): each returned 0 or `[]` on
every call against the v1 vault. The name-layer tools that replace them
(`find_names`, `get_name`, `name_neighbors`, `who_cites`,
`who_argues_against`) are registered by issue #488, which owns the loop's
own rewiring; this registry carries only what still resolves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.query import names, reader

# Every §7.5 tool arg is a plain string (a chunk/artifact/source id) -- there
# is no int/bool/list-valued arg in the whole tool set, so the registry
# validates types against `str` alone rather than pulling in a JSON-schema
# library for a single scalar type.
ToolCall = Callable[[dict[str, str], Path | None, Path | None], tuple[list[str], int]]


@dataclass(frozen=True)
class ToolSpec:
    """One registry entry: a model-facing `name`, a `description` (fed to a
    real provider's tool schema), the string-valued args it accepts split
    into `required_args`/`optional_args`, and `call` -- the adapter that
    invokes the underlying `reader` function and returns `(result_ids,
    result_count)`."""

    name: str
    description: str
    required_args: frozenset[str]
    optional_args: frozenset[str]
    call: ToolCall

    @property
    def allowed_args(self) -> frozenset[str]:
        return self.required_args | self.optional_args


def _query_by_source(
    args: dict[str, str], vault_dir: Path | None, _envelopes_dir: Path | None
) -> tuple[list[str], int]:
    ids = reader.query_by_source(args["source_id"], vault_dir=vault_dir)
    return ids, len(ids)


def _get_envelope(
    args: dict[str, str], _vault_dir: Path | None, envelopes_dir: Path | None
) -> tuple[list[str], int]:
    envelope = reader.get_envelope(args["source_id"], envelopes_dir=envelopes_dir)
    return [envelope.source_id], 1


def _get_chunk(
    args: dict[str, str], vault_dir: Path | None, _envelopes_dir: Path | None
) -> tuple[list[str], int]:
    chunk = reader.get_chunk(args["chunk_id"], vault_dir=vault_dir)
    return [chunk.chunk_id], 1


def _get_artifact(
    args: dict[str, str], vault_dir: Path | None, _envelopes_dir: Path | None
) -> tuple[list[str], int]:
    artifact = reader.get_artifact(args["artifact_id"], vault_dir=vault_dir)
    return [artifact.artifact_id], 1


def _coverage_count(
    _args: dict[str, str], vault_dir: Path | None, _envelopes_dir: Path | None
) -> tuple[list[str], int]:
    counts = names.coverage_count(vault_dir=vault_dir)
    canonicals = sorted(counts)
    return canonicals, len(canonicals)


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "query_by_source": ToolSpec(
        name="query_by_source",
        description="Every chunk_id belonging to the given source_id.",
        required_args=frozenset({"source_id"}),
        optional_args=frozenset(),
        call=_query_by_source,
    ),
    "get_envelope": ToolSpec(
        name="get_envelope",
        description=(
            "The per-source envelope for source_id: thesis, nested toc, scope, stated_argument."
        ),
        required_args=frozenset({"source_id"}),
        optional_args=frozenset(),
        call=_get_envelope,
    ),
    "get_chunk": ToolSpec(
        name="get_chunk",
        description="One prose chunk by chunk_id, with its frontmatter and text.",
        required_args=frozenset({"chunk_id"}),
        optional_args=frozenset(),
        call=_get_chunk,
    ),
    "get_artifact": ToolSpec(
        name="get_artifact",
        description="One artifact (figure/table/etc.) by artifact_id.",
        required_args=frozenset({"artifact_id"}),
        optional_args=frozenset(),
        call=_get_artifact,
    ),
    "coverage_count": ToolSpec(
        name="coverage_count",
        description="The member-note count of every name page in the vault, per name.",
        required_args=frozenset(),
        optional_args=frozenset(),
        call=_coverage_count,
    ),
}


def tool_specs_for_provider() -> list[dict[str, Any]]:
    """The registry rendered into the OpenAI/OpenRouter function-calling
    `tools` payload shape (`OpenRouterClient.complete_with_tools` sends this
    list verbatim)."""
    specs: list[dict[str, Any]] = []
    for spec in TOOL_REGISTRY.values():
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": {
                        "type": "object",
                        "properties": {name: {"type": "string"} for name in spec.allowed_args},
                        "required": sorted(spec.required_args),
                        "additionalProperties": False,
                    },
                },
            }
        )
    return specs
