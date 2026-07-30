"""Vault query: the read layer over the Obsidian vault and the name layer
(Phase-B stage 3, specs/PHASE-B.md §7.5).

`axial.query.reader` is the note layer -- `get_chunk`, `get_artifact`,
`query_by_source` / `get_envelope`. Every one of them needs an id the caller
already holds.

`axial.query.names` is how a caller FINDS something (Phase B v1 slice 02,
issue #487): `find_names`, `get_name`, `name_neighbors`, `who_cites`,
`who_argues_against`, `where_names_meet` (issue #517) and the per-name
`coverage_count`. It replaces
`query_by_tag`, `query_by_polity` and `follow_backlinks`, deleted with the
facets they filtered (D1/D5): each returned 0 or `[]` on every call against
the v1 vault, and a tool that silently returns nothing is worse than one that
is absent.
"""

from __future__ import annotations

from axial.query.names import (
    CitationEdge,
    Disagreement,
    NameHit,
    NameMember,
    NameNeighbor,
    NameNotFoundError,
    NamePage,
    OppositionEdge,
    coverage_count,
    find_names,
    get_name,
    name_neighbors,
    where_names_meet,
    who_argues_against,
    who_cites,
)
from axial.query.reader import (
    ArtifactNote,
    ArtifactNotFoundError,
    ChunkNote,
    ChunkNotFoundError,
    Envelope,
    EnvelopeNotFoundError,
    MalformedChunkIdError,
    MalformedNoteError,
    MissingVaultDirError,
    QueryError,
    get_artifact,
    get_chunk,
    get_envelope,
    query_by_source,
)

__all__ = [
    "ArtifactNote",
    "ArtifactNotFoundError",
    "ChunkNote",
    "ChunkNotFoundError",
    "CitationEdge",
    "Disagreement",
    "Envelope",
    "EnvelopeNotFoundError",
    "MalformedChunkIdError",
    "MalformedNoteError",
    "MissingVaultDirError",
    "NameHit",
    "NameMember",
    "NameNeighbor",
    "NameNotFoundError",
    "NamePage",
    "OppositionEdge",
    "QueryError",
    "coverage_count",
    "find_names",
    "get_artifact",
    "get_chunk",
    "get_envelope",
    "get_name",
    "name_neighbors",
    "query_by_source",
    "where_names_meet",
    "who_argues_against",
    "who_cites",
]
