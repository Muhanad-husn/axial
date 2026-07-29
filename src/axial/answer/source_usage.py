"""The §7.13 source-usage disclosure (Phase-B stage 6, specs/PHASE-B.md
§7.13, §8 P0-13, issue #265): every analysis record's per-source
contribution, disclosed alongside the denominator it should be read
against.

Computed deterministically, with zero model calls, from data the record
already holds:

- `filters_observed` -- the union of the tag-filter arguments the run's
  trajectory (§7.6) actually recorded. **Empty on every run since issue
  #487**: the two tools it drew from (`query_by_tag`, `query_by_polity`) are
  deleted with the facets they filtered (D1), so no trajectory can carry one.
- `sources` -- one entry per distinct `source_id` appearing in the claim
  grounds (never a source that only appears in the denominator query but was
  never actually drawn on): its evidence share, plus its available share
  under `filters_observed`.

**`available_chunk_count` is therefore 0 by construction, and
`usage_ratio` is `None`, until issue #491 re-bases the denominator onto the
name layer** (`plans/phase-b-v1/README.md`: "under names the natural
analogue is the union of member notes across the names queried", to be proven
on the smoke set first). Disclosed here rather than papered over: the
evidence half of §7.13 is unaffected and still real.

This module never imports `axial.llm` or constructs any LLM client --
mirroring `axial.query.reader`'s own model-free-by-construction discipline
(§7.5), it is pure vault reads plus arithmetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.query.reader import get_artifact, source_id_from_chunk_id

# The tools whose `args` were tag-axis filters (§7.6's trajectory `args`
# field) -- the only tools `filters_observed` ever drew from. Both are
# deleted (issue #487, D1), so this set now matches nothing any real
# trajectory carries; #491 owns what replaces it.
_FILTER_TOOLS = frozenset({"query_by_tag", "query_by_polity"})


def derive_filters_observed(trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The union of tag filters this run actually queried (§7.13),
    deduplicated and deterministically ordered: first-seen order over
    `trajectory`'s own call order, so the same trajectory always yields the
    same list. Each entry is `{tool, args}` -- `tool` is kept alongside
    `args` because `query_by_tag`'s own `polity` filter key (matching the
    single-valued `empirical_scope.polity`) and `query_by_polity`'s `polity`
    arg (matching the many-valued `polities_touched` facet) are different
    queries that happen to share a key name; collapsing them would re-run
    the wrong tool when the denominator is counted."""
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    filters_observed: list[dict[str, Any]] = []
    for entry in trajectory:
        tool = entry.get("tool")
        if tool not in _FILTER_TOOLS:
            continue
        args = dict(entry.get("args") or {})
        key = (tool, tuple(sorted(args.items())))
        if key in seen:
            continue
        seen.add(key)
        filters_observed.append({"tool": tool, "args": dict(sorted(args.items()))})
    return filters_observed


def _fold_evidence_grounds(
    claims: list[dict[str, Any]], *, vault_dir: Path | None
) -> dict[str, int]:
    """Distinct grounds pointers (chunk or artifact ids), resolved to their
    `source_id` and counted once each even when two claims cite the same
    pointer (§7.13's own evidence fold). A `chunk` pointer's source_id is a
    parse of its id (`source_id_from_chunk_id`); an `artifact` pointer's
    source_id is read off the artifact's own frontmatter (`get_artifact`),
    since an artifact_id carries no such seam of its own."""
    chunks_by_source: dict[str, set[str]] = {}
    for claim in claims:
        for ground in claim.get("grounds") or []:
            ref_type = ground.get("ref_type")
            ref_id = ground.get("ref_id")
            if ref_type == "chunk":
                source_id = source_id_from_chunk_id(ref_id)
            elif ref_type == "artifact":
                source_id = get_artifact(ref_id, vault_dir=vault_dir).source_id
            else:
                continue
            chunks_by_source.setdefault(source_id, set()).add(ref_id)
    return {source_id: len(ids) for source_id, ids in chunks_by_source.items()}


def compute_source_usage(
    record: dict[str, Any], *, vault_dir: Path | None = None
) -> dict[str, Any]:
    """Compute the §7.13 `source_usage` field for an analysis record
    (§7.3's shape: `claims`, `trajectory`, `interrogation.disposition`).
    Zero model calls -- pure vault reads plus arithmetic.

    `sources` is empty on disposition `refuse` and on any run whose claims
    carry no grounds (§7.13), `filters_observed` still populated in both.
    `usage_ratio` is `evidence_share / available_share`, and is `None`
    (never 0, never an error) when `available_share` is 0 -- which is every
    run until #491 re-bases the denominator (see the module docstring)."""
    trajectory = record.get("trajectory") or []
    filters_observed = derive_filters_observed(trajectory)

    disposition = (record.get("interrogation") or {}).get("disposition")
    claims = record.get("claims") or []
    evidence_counts = (
        {} if disposition == "refuse" else _fold_evidence_grounds(claims, vault_dir=vault_dir)
    )

    if not evidence_counts:
        return {"filters_observed": filters_observed, "sources": []}

    total_evidence = sum(evidence_counts.values())
    # The denominator's two filter tools are deleted with the facets they
    # filtered (issue #487, D1), so there is nothing left to re-query and
    # every `available_chunk_count` below is 0 by construction. #491 re-bases
    # it onto the union of member notes across the names a run queried; the
    # dead re-query path is removed rather than left looking like it still
    # measures something (the same rule that deleted the tools).
    available_counts: dict[str, int] = {}
    available_total = 0

    sources: list[dict[str, Any]] = []
    for source_id in sorted(evidence_counts):
        evidence_chunk_count = evidence_counts[source_id]
        evidence_share = evidence_chunk_count / total_evidence
        available_chunk_count = available_counts.get(source_id, 0)
        available_share = (available_chunk_count / available_total) if available_total else 0.0
        usage_ratio = (evidence_share / available_share) if available_share else None
        sources.append(
            {
                "source_id": source_id,
                "evidence_chunk_count": evidence_chunk_count,
                "evidence_share": evidence_share,
                "available_chunk_count": available_chunk_count,
                "available_share": available_share,
                "usage_ratio": usage_ratio,
            }
        )

    return {"filters_observed": filters_observed, "sources": sources}
