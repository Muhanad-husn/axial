"""Vault query: the read layer over the tagged Obsidian vault (Phase-B
stage 3, specs/PHASE-B.md §7.5).

Slice 01 (#249) landed the note reader and three of the §7.5 tool set:
`get_chunk`, `get_artifact`, `query_by_tag`. Slice 02 (#251) adds the
remaining four: `query_by_polity`, `query_by_source`, `get_envelope`,
`follow_backlinks`, `coverage_count`.
"""

from __future__ import annotations

from axial.query.reader import (
    ArtifactNote,
    ArtifactNotFoundError,
    BacklinkTargetNotFoundError,
    ChunkNote,
    ChunkNotFoundError,
    Envelope,
    EnvelopeNotFoundError,
    KNOWN_FILTER_KEYS,
    MalformedChunkIdError,
    MalformedNoteError,
    MissingVaultDirError,
    QueryError,
    UnknownFilterError,
    coverage_count,
    follow_backlinks,
    get_artifact,
    get_chunk,
    get_envelope,
    query_by_polity,
    query_by_source,
    query_by_tag,
)

__all__ = [
    "ArtifactNote",
    "ArtifactNotFoundError",
    "BacklinkTargetNotFoundError",
    "ChunkNote",
    "ChunkNotFoundError",
    "Envelope",
    "EnvelopeNotFoundError",
    "KNOWN_FILTER_KEYS",
    "MalformedChunkIdError",
    "MalformedNoteError",
    "MissingVaultDirError",
    "QueryError",
    "UnknownFilterError",
    "coverage_count",
    "follow_backlinks",
    "get_artifact",
    "get_chunk",
    "get_envelope",
    "query_by_polity",
    "query_by_source",
    "query_by_tag",
]
