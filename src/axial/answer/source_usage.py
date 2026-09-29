"""The §7.13 source-usage disclosure (Phase-B stage 6, specs/PHASE-B.md
§7.13, §8 P0-13, issues #265 and #491): every analysis record's per-source
contribution, disclosed alongside the denominator it should be read
against.

**Re-pointed at the store (DEC-75, issue #853).** The map arm -- the only
retrieval path left -- makes no name-layer tool call, so it writes no §7.6
trajectory this disclosure used to read `names_queried`/the denominator off
of. What a run's answer is ABOUT is still knowable: every claim already
carries `names_touched` (§7.3), the canonicals its own grounds resolved to.
This module reads that instead, and answers the denominator from
`axial.query.store` (`doors`/`concept_sources`) rather than from a name
page or a `where_names_meet` pair -- there is no page left to re-query.

Computed deterministically, with zero model calls, from data the record
already holds plus deterministic re-reads of the pinned vault's store:

- `names_queried` -- the union of every claim's `names_touched` (§7.3),
  each entry `{tool: "names_touched", args: {canonical}}` -- the same
  `{tool, args}` shape §7.13 always used, so `axial.answer.usage_report`'s
  cross-run join and `axial.brief.smoke`'s console rendering need no second
  convention, with a tool label that says plainly this is read off the
  claims, not off a retrieval call.
- `denominator_by_name` -- per touched canonical, its door's own
  `member_count` (`axial.query.store.doors`) -- the whole corpus's count,
  not a union. Disclosed as data because one hub name can be most of the
  corpus: `Syria` alone carries 962 of the live vault's 6,148 prose notes
  (15.6%), so a denominator inflated by one place name is visible here
  rather than only in the ratios it flattens.
- `sources` -- one entry per distinct `source_id` appearing in the claim
  grounds (never a source that only appears in the denominator query but
  was never actually drawn on): its evidence share, plus its available
  share across the names touched.
- `weights` -- the analyst's own `Brief.weights` (issue #639), `{}` when
  none were supplied, read straight off `record["brief"]["weights"]`
  (§7.1's verbatim brief). Recorded here, beside the contribution figures
  it was meant to move, so a reader sees the instruction and its effect in
  one place rather than having to cross-reference `record["brief"]`
  separately -- disclosed on every run, including a `refuse` disposition
  or one with no grounds, exactly like `names_queried`/`denominator_by_
  name` below.

**The per-source availability is now a SUM across touched names, not a
chunk-level union (a real, disclosed change from the retired mechanism).**
`axial.query.store.concept_sources` gives each touched name's own per-source
note count directly; getting the true cross-name union would need each
name's member `chunk_id`s, which `where_names_meet`/a name page were the
only way to read without a per-name join this module has no reason to grow.
A note naming two touched names is counted once per name here, not once
overall -- inflating the denominator for a source contributing to several
touched names, in the same direction the union always erred anyway (a
larger, more forgiving denominator, never a smaller one that would overstate
a `usage_ratio`).

This module never imports `axial.llm` or constructs any LLM client --
mirroring `axial.query.reader`'s own model-free-by-construction discipline
(§7.5), it is pure vault reads plus arithmetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.paths import default_vault_dir
from axial.query import store as note_store
from axial.query.reader import get_artifact, source_id_from_chunk_id

# The synthetic `tool` label `names_queried` entries carry (DEC-75, issue
# #853): there is no retrieval tool to name any more, only the claims'
# own `names_touched`, so this says plainly where the entry came from
# rather than naming a tool that was never called.
NAMES_TOUCHED_LABEL = "names_touched"


def _touched_names(claims: list[dict[str, Any]]) -> list[str]:
    """Every canonical this run's claims name (`Claim.names_touched`, §7.3),
    deduplicated, ascending -- the query-agnostic replacement for the
    retired name-layer trajectory (DEC-75, issue #853)."""
    touched: set[str] = set()
    for claim in claims:
        for name in claim.get("names_touched") or []:
            if isinstance(name, str) and name:
                touched.add(name)
    return sorted(touched)


def derive_names_queried(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The union of the names this run's claims are about (§7.13), as the
    `{tool, args}` shape this field always carried -- `tool` is always
    `NAMES_TOUCHED_LABEL` now (DEC-75, issue #853: there is no retrieval
    tool left to distinguish; every touched name is one query)."""
    return [{"tool": NAMES_TOUCHED_LABEL, "args": {"canonical": name}} for name in _touched_names(claims)]


def compute_available_notes(
    names_touched: list[str], *, vault_dir: Path | None = None
) -> tuple[dict[str, int], dict[str, int]]:
    """The §7.13 denominator: `(per-name member counts, per-source counts)`,
    read off the store (DEC-75, issue #853).

    `per_name` is each touched name's own door `member_count`
    (`axial.query.store.doors`) -- the corpus-wide total. `by_source` sums
    `axial.query.store.concept_sources`' own per-source `note_count` across
    every touched name (see module docstring for why this is a sum, not a
    chunk-level union). A vault with no store answers `({}, {})`."""
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    connection = note_store.connect(vault)
    if connection is None:
        return {}, {}
    try:
        doors = note_store.doors(connection, names_touched)
        per_name = {name: doors[name].member_count for name in names_touched if name in doors}
        by_source: dict[str, int] = {}
        for name in names_touched:
            for share in note_store.concept_sources(connection, name):
                by_source[share.source_id] = by_source.get(share.source_id, 0) + share.note_count
        return per_name, by_source
    finally:
        connection.close()


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
    (§7.3's shape: `claims`, `interrogation.disposition`, `brief.weights`).
    Zero model calls -- pure vault reads plus arithmetic.

    `weights` (issue #639) is read straight off `record["brief"]["weights"]`
    -- `{}` for a record with none, never absent -- so the analyst's own
    instruction rides alongside the contribution figures it was meant to
    move, always, on every disposition.

    `sources` is empty on disposition `refuse` and on any run whose claims
    carry no grounds (§7.13), `names_queried` and `denominator_by_name`
    still populated in both -- what the run's answer is about is a fact
    about the run whether or not it then cited anything. `usage_ratio` is
    `evidence_share / available_share`, and is `None` (never 0, never an
    error) when `available_share` is 0: the run drew on a source whose notes
    are members of none of the names its claims touch, so there is no
    availability to divide by.

    **`available_chunk_count`/`available_share` are `None`, not `0`, when
    this run's claims touched no name at all (issue #584)** --
    `denominator_by_name` empty is that signal. A genuine measured zero -- a
    source drawn on that is a member of none of the names THIS run's claims
    touch -- still reads `0`: the distinction is whether a denominator was
    ever computed at all, not whether one source's own share of it happens
    to be empty."""
    claims = record.get("claims") or []
    names_touched = _touched_names(claims)
    names_queried = derive_names_queried(claims)
    denominator_by_name, available_counts = compute_available_notes(
        names_touched, vault_dir=vault_dir
    )
    available_total = sum(available_counts.values())
    names_were_queried = bool(denominator_by_name)

    disposition = (record.get("interrogation") or {}).get("disposition")
    evidence_counts = (
        {} if disposition == "refuse" else _fold_evidence_grounds(claims, vault_dir=vault_dir)
    )

    weights = dict((record.get("brief") or {}).get("weights") or {})
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    base = {
        "names_queried": names_queried,
        "denominator_by_name": denominator_by_name,
        # Issue #856: each touched name's Wikidata QID, an identifier only.
        "qid_by_name": note_store.vault_qids(vault, names_touched),
        "weights": weights,
    }
    if not evidence_counts:
        return {**base, "sources": []}

    total_evidence = sum(evidence_counts.values())
    sources: list[dict[str, Any]] = []
    for source_id in sorted(evidence_counts):
        evidence_chunk_count = evidence_counts[source_id]
        evidence_share = evidence_chunk_count / total_evidence
        if names_were_queried:
            available_chunk_count = available_counts.get(source_id, 0)
            available_share = (available_chunk_count / available_total) if available_total else 0.0
        else:
            available_chunk_count = None
            available_share = None
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
