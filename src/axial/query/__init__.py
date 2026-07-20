"""Vault query: the read layer over the tagged Obsidian vault (Phase-B
stage 3, specs/PHASE-B.md §7.5).

This slice (#249) lands the note reader and three of the §7.5 tool set:
`get_chunk`, `get_artifact`, `query_by_tag`. `query_by_polity`,
`query_by_source`/`get_envelope`, `follow_backlinks`, and `coverage_count`
are a later slice.
"""

from __future__ import annotations

from axial.query.reader import (
    ArtifactNote,
    ArtifactNotFoundError,
    ChunkNote,
    ChunkNotFoundError,
    KNOWN_FILTER_KEYS,
    MalformedNoteError,
    MissingVaultDirError,
    QueryError,
    UnknownFilterError,
    get_artifact,
    get_chunk,
    query_by_tag,
)

__all__ = [
    "ArtifactNote",
    "ArtifactNotFoundError",
    "ChunkNote",
    "ChunkNotFoundError",
    "KNOWN_FILTER_KEYS",
    "MalformedNoteError",
    "MissingVaultDirError",
    "QueryError",
    "UnknownFilterError",
    "get_artifact",
    "get_chunk",
    "query_by_tag",
]
