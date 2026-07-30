"""The §7.13 source-usage disclosure (Phase-B stage 6, specs/PHASE-B.md
§7.13, §8 P0-13, issues #265 and #491): every analysis record's per-source
contribution, disclosed alongside the denominator it should be read
against.

Computed deterministically, with zero model calls, from data the record
already holds plus deterministic re-reads of the pinned vault:

- `names_queried` -- the union of the name queries this run's trajectory
  (§7.6) recorded, each entry `{tool, args}`. It replaces `filters_observed`,
  which drew from `query_by_tag`/`query_by_polity`; both tools are deleted
  with the facets they filtered (D1), so no trajectory can carry one.
- `denominator_by_name` -- per canonical name this run reached, how many
  member notes that name's page holds. Disclosed as data because one hub
  name can be most of the corpus: `Syria` alone carries 962 of the live
  vault's 6,148 prose notes (15.6%), so a denominator inflated by one place
  name is visible here rather than only in the ratios it flattens.
- `sources` -- one entry per distinct `source_id` appearing in the claim
  grounds (never a source that only appears in the denominator query but
  was never actually drawn on): its evidence share, plus its available
  share across the names queried.

**The denominator is the plain union of member notes across the names
queried**, a note that is a member of two queried names counting once,
re-queried over the pinned vault through `get_name`, never derived from
this run's own evidence -- exactly the analogue §7.13 states. No `kind`
exclusion and no per-name cap is applied: both would be constants fitted
before any measurement exists, and §7.13 makes proving the denominator on
the smoke set a separate, evidence-led step. `denominator_by_name` is what
that step reads.

This module never imports `axial.llm` or constructs any LLM client --
mirroring `axial.query.reader`'s own model-free-by-construction discipline
(§7.5), it is pure vault reads plus arithmetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.query.names import NameNotFoundError, NamePage, get_name
from axial.query.reader import get_artifact, source_id_from_chunk_id
from axial.validators.coverage import NAME_ARG_TOOLS, NAME_RESULT_TOOLS, retrieved_names

# The §7.5 tools whose calls ARE name queries -- the four that take a
# canonical name plus `find_names`, which resolves one. Exactly the tools
# §7.7's coverage scope reads, imported rather than restated so the two
# never drift.
NAME_QUERY_TOOLS = NAME_ARG_TOOLS | NAME_RESULT_TOOLS


def derive_names_queried(trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The union of the name queries this run actually made (§7.13),
    deduplicated and deterministically ordered: first-seen order over
    `trajectory`'s own call order, so the same trajectory always yields the
    same list. Each entry is `{tool, args}` -- `tool` is kept alongside
    `args` (the #265 rule, unchanged) because `get_name`, `name_neighbors`,
    `who_cites` and `who_argues_against` all take a canonical name under the
    same arg key and are different queries; collapsing them would re-run the
    wrong tool when the denominator is counted."""
    seen: set[tuple[str, tuple[tuple[str, Any], ...]]] = set()
    names_queried: list[dict[str, Any]] = []
    for entry in trajectory:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        if tool not in NAME_QUERY_TOOLS:
            continue
        args = dict(entry.get("args") or {})
        key = (tool, tuple(sorted((str(k), str(v)) for k, v in args.items())))
        if key in seen:
            continue
        seen.add(key)
        names_queried.append({"tool": tool, "args": dict(sorted(args.items()))})
    return names_queried


def full_name_page(canonical: str, *, vault_dir: Path | None) -> NamePage | None:
    """`canonical`'s page with its member list UNCAPPED, or `None` when the
    vault holds no page for it. `get_name`'s `members` is truncated at its
    own `limit` (issue #505), which a denominator cannot accept -- a member
    past the cap would silently shrink the corpus. A first call at the
    default cap is used only when it already proves uncapped; a page over it
    pays one extra call at its own true `member_count`. Same rule
    `axial.validators.coverage._evidence_note_count` follows, for the same
    reason. Shared with §7.15's name-reach and disagreement-reuse figures,
    which need the same whole page."""
    try:
        page = get_name(canonical, vault_dir=vault_dir)
    except NameNotFoundError:
        return None
    if page.member_count > len(page.members):
        page = get_name(canonical, page.member_count, vault_dir=vault_dir)
    return page


def _all_member_chunk_ids(canonical: str, *, vault_dir: Path | None) -> set[str]:
    page = full_name_page(canonical, vault_dir=vault_dir)
    if page is None:
        return set()
    return {member.chunk_id for member in page.members}


def compute_available_notes(
    trajectory: list[dict[str, Any]], *, vault_dir: Path | None = None
) -> tuple[dict[str, int], dict[str, int]]:
    """The §7.13 denominator: `(per-name member counts, per-source counts of
    the union)`.

    The names are the canonicals this run reached -- the `canonical`
    argument of every name-layer traversal plus every canonical `find_names`
    resolved (`axial.validators.coverage.retrieved_names`, the same read
    §7.7's coverage scope uses). The union counts a note once however many
    queried names it is a member of; the per-name map is NOT that union
    de-duplicated, it is each name's own page size, so a hub name's
    contribution to the denominator is legible on its own."""
    per_name: dict[str, int] = {}
    union: set[str] = set()
    for canonical in sorted(retrieved_names(trajectory)):
        member_ids = _all_member_chunk_ids(canonical, vault_dir=vault_dir)
        per_name[canonical] = len(member_ids)
        union |= member_ids

    by_source: dict[str, int] = {}
    for chunk_id in union:
        source_id = source_id_from_chunk_id(chunk_id)
        by_source[source_id] = by_source.get(source_id, 0) + 1
    return per_name, by_source


def source_ids_for_grounds(claim: dict[str, Any], *, vault_dir: Path | None) -> set[str]:
    """The distinct `source_id`s one claim's grounds pointers resolve to. A
    `chunk` pointer's source_id is a parse of its id
    (`source_id_from_chunk_id`); an `artifact` pointer's is read off the
    artifact's own frontmatter (`get_artifact`), since an artifact_id
    carries no such seam. Shared with §7.15's cross-source rate, which asks
    the same question of one claim at a time."""
    source_ids: set[str] = set()
    for ground in claim.get("grounds") or []:
        if not isinstance(ground, dict):
            continue
        ref_type = ground.get("ref_type")
        ref_id = ground.get("ref_id")
        if ref_type == "chunk":
            source_ids.add(source_id_from_chunk_id(ref_id))
        elif ref_type == "artifact":
            source_ids.add(get_artifact(ref_id, vault_dir=vault_dir).source_id)
    return source_ids


def _fold_evidence_grounds(
    claims: list[dict[str, Any]], *, vault_dir: Path | None
) -> dict[str, int]:
    """Distinct grounds pointers (chunk or artifact ids), resolved to their
    `source_id` and counted once each even when two claims cite the same
    pointer (§7.13's own evidence fold)."""
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
    carry no grounds (§7.13), `names_queried` and `denominator_by_name`
    still populated in both -- what the run looked at is a fact about the
    run whether or not it then cited anything. `usage_ratio` is
    `evidence_share / available_share`, and is `None` (never 0, never an
    error) when `available_share` is 0: the run drew on a source whose notes
    are members of none of the names it queried, so there is no
    availability to divide by."""
    trajectory = record.get("trajectory") or []
    names_queried = derive_names_queried(trajectory)
    denominator_by_name, available_counts = compute_available_notes(trajectory, vault_dir=vault_dir)
    available_total = sum(available_counts.values())

    disposition = (record.get("interrogation") or {}).get("disposition")
    claims = record.get("claims") or []
    evidence_counts = (
        {} if disposition == "refuse" else _fold_evidence_grounds(claims, vault_dir=vault_dir)
    )

    base = {"names_queried": names_queried, "denominator_by_name": denominator_by_name}
    if not evidence_counts:
        return {**base, "sources": []}

    total_evidence = sum(evidence_counts.values())
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

    return {**base, "sources": sources}
