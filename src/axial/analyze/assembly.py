"""Evidence assembly (Phase-B stage 4 pre-pass, specs/PHASE-B.md §7.5/§7.7,
issue #255): the retrieval loop's output (a list of chunk ids) turned into
one inspectable object -- the assembled evidence set the operator can look
at, and the eventual synthesis call will read, before any expensive model
call is made.

`assemble_evidence` fetches each id's full `ChunkNote` (dropping any id the
retrieval loop returned that does not resolve to a prose chunk -- the
loop's own `RetrievalResult.evidence_ids` pools ids from every tool a model
called, including `get_envelope`/`coverage_count`, whose "ids" are
source_ids/polity names rather than chunk ids; the evidence SET this module
assembles is chunks specifically) and rolls the frontmatter's
`polities_touched` up into the §7.7 raw counts: `corpus_chunk_count` (from
`axial.query.reader.coverage_count`, never a recount) and
`evidence_chunk_count` (this run's own evidence set). Coverage BANDS
(`coverage_band`) are explicitly out of this slice's scope -- see
plans/analysis-synthesis/01-evidence-assembly-and-examine.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from axial.query.reader import ChunkNotFoundError, coverage_count, get_chunk


@dataclass(frozen=True)
class EvidenceChunk:
    """One evidence chunk's synthesis-relevant frontmatter (the plan's
    inner-loop bullet 2): the id plus exactly the axes synthesis will need.
    Not the full `ChunkNote` -- `chunk_text`/`source_meta` stay reachable via
    `axial.query.reader.get_chunk` when synthesis (slice 02) actually needs
    them."""

    chunk_id: str
    polities_touched: list[str]
    role_in_argument: str
    theory_school: dict[str, Any]
    claim_type: dict[str, Any]
    empirical_scope: dict[str, Any]


@dataclass(frozen=True)
class PolityCoverage:
    """One polity's §7.7 raw counts. Coverage BANDS (`coverage_band`) are
    out of this slice's scope: `corpus_chunk_count` comes straight from
    `axial.query.reader.coverage_count` (never a recount), and
    `evidence_chunk_count` from this run's own evidence set."""

    corpus_chunk_count: int
    evidence_chunk_count: int


@dataclass(frozen=True)
class EvidenceSet:
    """The assembled evidence set (issue #255): deduplicated `chunk_ids` in
    first-seen retrieval order, each surviving chunk's synthesis-relevant
    frontmatter (`chunks`, index-aligned with `chunk_ids`), and the raw
    per-polity coverage roll-up for every polity the set touches. Empty
    cleanly (`chunk_ids=[]`, `chunks=[]`, `polity_coverage={}`) when the
    evidence set itself is empty -- never raises on that case."""

    chunk_ids: list[str]
    chunks: list[EvidenceChunk]
    polity_coverage: dict[str, PolityCoverage]


def _dedupe_preserving_order(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for chunk_id in ids:
        if chunk_id not in seen:
            seen.add(chunk_id)
            ordered.append(chunk_id)
    return ordered


def _roll_up_polity_coverage(
    chunks: list[EvidenceChunk], corpus_counts: dict[str, int]
) -> dict[str, PolityCoverage]:
    """Count each polity once per chunk that touches it (mirroring
    `axial.query.reader.coverage_count`'s own per-chunk dedup), and report
    only polities at least one evidence chunk touches -- a polity absent
    from the evidence set never gets a fabricated zero-evidence entry."""
    evidence_counts: dict[str, int] = {}
    for chunk in chunks:
        for polity in set(chunk.polities_touched):
            evidence_counts[polity] = evidence_counts.get(polity, 0) + 1
    return {
        polity: PolityCoverage(
            corpus_chunk_count=corpus_counts.get(polity, 0),
            evidence_chunk_count=count,
        )
        for polity, count in sorted(evidence_counts.items())
    }


def assemble_evidence(chunk_ids: Iterable[str], *, vault_dir: Path | None = None) -> EvidenceSet:
    """Assemble the evidence set `chunk_ids` (typically
    `RetrievalResult.evidence_ids`) resolves to (issue #255, §7.5/§7.7):
    dedupe preserving first-seen retrieval order, fetch each id's
    frontmatter via `axial.query.reader.get_chunk`, and roll up raw
    per-polity coverage counts against `coverage_count`'s real corpus-wide
    result.

    An id that does not resolve to a real prose chunk (`ChunkNotFoundError`)
    is dropped rather than raised -- see the module docstring for why.

    Cleanly returns an empty `EvidenceSet` for an empty `chunk_ids`, never
    raising."""
    ordered_ids = _dedupe_preserving_order(chunk_ids)

    chunks: list[EvidenceChunk] = []
    resolved_ids: list[str] = []
    for chunk_id in ordered_ids:
        try:
            note = get_chunk(chunk_id, vault_dir=vault_dir)
        except ChunkNotFoundError:
            continue
        resolved_ids.append(chunk_id)
        chunks.append(
            EvidenceChunk(
                chunk_id=note.chunk_id,
                polities_touched=list(note.polities_touched),
                role_in_argument=note.role_in_argument,
                theory_school=note.theory_school,
                claim_type=note.claim_type,
                empirical_scope=note.empirical_scope,
            )
        )

    corpus_counts = coverage_count(vault_dir=vault_dir)
    polity_coverage = _roll_up_polity_coverage(chunks, corpus_counts)

    return EvidenceSet(chunk_ids=resolved_ids, chunks=chunks, polity_coverage=polity_coverage)
