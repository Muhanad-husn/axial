"""The paper's coverage map and confidence, unioned from the source records
(specs/PHASE-C.md §7.11, §7.3, §7.4).

**Unioned, never recomputed, and this is the one place Phase B v1 changed the
mechanism rather than a name.** Phase B keys its own map on
`coverage_scope(claims, trajectory)`: the names this run's retrieval queried
that its claims also touch. That intersection needs a trajectory, and a paper
record has none and never will (§7.3) -- Phase C retrieves nothing. Calling
`compute_coverage_map` on a paper record does not approximate the right
answer, it returns `{}`.

So the denominator is carried across from the maps that already exist, and
only the numerator is the paper's own:

- `corpus_note_count` -- from the source records' maps. Two records at one pin
  cannot legitimately disagree, so a disagreement is a hard error naming both,
  never a value to average. `null` survives as `null`, never a fabricated `0`.
- `cited_claim_count` -- the paper's own numerator. An analysis counts evidence
  notes it assembled; a paper's unit is the cited claim, and reusing a source
  record's `evidence_note_count` would report evidence the analysis gathered
  as though the paper had used it.
- `coverage_band` -- carried with its count, since band and count were derived
  together at one pin under one threshold.

**Zero vault reads and zero model calls**, which is what §7.4's `names_touched`
on every paper claim buys.
"""

from __future__ import annotations

from typing import Any

from axial.validators.coverage import (
    NOT_MEASURED_BAND,
    compute_confidence,
    confidence_ceiling_for_claim,
)


class PaperCoverageError(Exception):
    """Base class for paper coverage-map failures."""


class CoverageDisagreementError(PaperCoverageError):
    """Raised when two source records disagree on a name's `corpus_note_count`.

    Records sharing a `corpus_pin` were produced against a byte-identical
    vault (§7.1), so they cannot legitimately disagree about how many notes a
    name page holds. Averaging would manufacture a denominator neither record
    reported; this names both records instead (§7.11)."""

    def __init__(self, canonical: str, counts_by_brief_id: dict[str, Any]):
        self.canonical = canonical
        self.counts_by_brief_id = dict(counts_by_brief_id)
        rendered = ", ".join(
            f"{brief_id}={count!r}" for brief_id, count in sorted(counts_by_brief_id.items())
        )
        super().__init__(
            f"source records disagree on the corpus note count for {canonical!r}: {rendered}. "
            f"Records at one corpus pin cannot legitimately disagree -- one of them is stale"
        )


def _source_maps(records: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    maps: dict[str, dict[str, dict[str, Any]]] = {}
    for brief_id, record in records.items():
        coverage_map = record.get("coverage_map")
        maps[brief_id] = coverage_map if isinstance(coverage_map, dict) else {}
    return maps


def _cited_names(claims: list[dict[str, Any]]) -> dict[str, int]:
    """Every canonical name the paper's cited claims touch, with how many of
    them touch it. Read off each claim's own `names_touched` (§7.4), which is
    carried from its origin and never re-resolved here."""
    counts: dict[str, int] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for name in claim.get("names_touched") or []:
            if isinstance(name, str) and name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def _corpus_note_count(entry: dict[str, Any]) -> Any:
    """A source map entry's corpus count, under either vocabulary (issue #599).

    Records predating the notes rename carry it as `corpus_chunk_count`, the
    same four records that carry `polities_touched`. Keyed on presence rather
    than truthiness: `None` and `0` are both meaningful counts, and `None` is
    what a map-fed record's entry legitimately holds."""
    if "corpus_note_count" in entry:
        return entry.get("corpus_note_count")
    return entry.get("corpus_chunk_count")


def build_coverage_map(
    claims: list[dict[str, Any]], records: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """The paper's §7.11 coverage map.

    Restricted to names that are BOTH in some source record's map AND touched
    by a claim this paper cited. A name outside every source map is out of
    scope by construction -- the map never grows at paper scale, and this is
    the direction an honest disclosure moves when material is dropped on the
    way into a paper."""
    maps = _source_maps(records)
    cited = _cited_names(claims)

    coverage_map: dict[str, dict[str, Any]] = {}
    for canonical in sorted(cited):
        counts_by_brief_id: dict[str, Any] = {}
        band: Any = None
        for brief_id, source_map in maps.items():
            entry = source_map.get(canonical)
            if not isinstance(entry, dict):
                continue
            counts_by_brief_id[brief_id] = _corpus_note_count(entry)
            if band is None:
                band = entry.get("coverage_band")

        if not counts_by_brief_id:
            continue

        distinct = {repr(count) for count in counts_by_brief_id.values()}
        if len(distinct) > 1:
            raise CoverageDisagreementError(canonical, counts_by_brief_id)

        coverage_map[canonical] = {
            "corpus_note_count": next(iter(counts_by_brief_id.values())),
            "cited_claim_count": cited[canonical],
            "coverage_band": band,
        }

    return coverage_map


def clamped_band_for(claim: dict[str, Any], coverage_map: dict[str, dict[str, Any]]) -> Any:
    """The band Phase B would RENDER for `claim`, which is what Phase C
    carries (§7.4, issue #550).

    A Phase-B record persists the model's own emitted band and clamps only
    what it renders, and the two disagree often rather than rarely: 93 of 121
    claims across the six smoke-v5 records were clamped. Copying the persisted
    field would lift an unclamped band into a paper and render it beside the
    paper's own coverage counts, which is the confidence-inflation failure
    §1 names.

    `confidence_ceiling_for_claim` is reused rather than re-derived: it is
    pure, model-free and vault-free, and a second implementation of the clamp
    would let the carrier and the gate that checks it disagree."""
    return confidence_ceiling_for_claim(claim, coverage_map).effective_band


def _paper_rationale(band: Any, coverage_map: dict[str, dict[str, Any]]) -> str:
    """The paper's own coverage rationale (§7.3: "states the coverage counts
    behind it, drawn from `coverage_map`").

    Phase B's `compute_confidence` writes its own rationale naming
    `evidence_note_count`, which a paper map deliberately does not carry
    (§7.11) -- reusing it verbatim would render "None evidence notes" beside
    every band, which is the manufactured-precision failure §7.10 forbids in a
    smaller costume. The BAND derivation is still Phase B's, so the
    coverage-to-band mapping stays shared; only the sentence is the paper's.

    An empty `coverage_map` here is the same fourth meaning `compute_confidence`
    guards against (issue #584/#587): not a measured `low`, but the absence of
    any name that is both covered by a source record and touched by a cited
    claim. The rationale says plainly that nothing was measured rather than
    implying a band was derived and found wanting -- see
    `overall_confidence`'s `NOT_MEASURED_BAND` handling for the sibling case
    where a SOURCE record itself measured nothing."""
    if not coverage_map:
        return (
            "nothing was measured: no name is both covered by a source analysis record "
            "and touched by a cited claim, so there is no coverage_map entry to derive a "
            "band from -- this is not a measured low band"
        )
    worst = min(
        coverage_map,
        key=lambda name: (_BAND_ORDER.get(coverage_map[name].get("coverage_band"), 0), name),
    )
    per_name = "; ".join(
        f"{name} ({entry.get('coverage_band')}: {entry.get('corpus_note_count')} "
        f"corpus notes, {entry.get('cited_claim_count')} cited claims)"
        for name, entry in sorted(coverage_map.items())
    )
    return (
        f"overall confidence is {band!r}, bounded by the least-covered name the paper "
        f"cites ({worst!r}, band {coverage_map[worst].get('coverage_band')!r}); "
        f"coverage by name: {per_name}"
    )


def _unmeasured_source_rationale(
    unmeasured_brief_ids: list[str], coverage_map: dict[str, dict[str, Any]]
) -> str:
    """The rationale when at least one source record's own `confidence.
    overall_band` is `NOT_MEASURED_BAND` (issue #584/#587): its own
    `coverage_map` was empty, so it measured nothing, and a paper standing on
    it cannot disclose a measured band either -- not `low`, which would read
    as "measured and found thin" when nothing was measured at all.

    This overrides the derived/held bands entirely rather than folding the
    unmeasured record into the floor comparison: `not_measured` is not a rung
    on the `low`/`medium`/`high` ordinal (§584's own rule, kept out of every
    rank map in this module and `axial.validators.coverage`), so there is no
    ceiling arithmetic to run it through.

    Disclosed, not averaged (mixed case): when the paper's OWN coverage map is
    non-empty -- some other, measured source record does cover a cited name --
    that coverage is still named here, so a reader sees both facts rather than
    a single number that quietly drops the unmeasured leg."""
    detail = (
        f"source record(s) {unmeasured_brief_ids!r} measured nothing of their own "
        "(their own coverage_map is empty), and a paper cannot claim a measured band "
        "while standing on an unmeasured analysis (§7.3) -- this is not a measured low band"
    )
    if not coverage_map:
        return f"paper confidence is not measured: {detail}"
    per_name = "; ".join(
        f"{name} ({entry.get('coverage_band')}: {entry.get('corpus_note_count')} "
        f"corpus notes, {entry.get('cited_claim_count')} cited claims)"
        for name, entry in sorted(coverage_map.items())
    )
    return (
        f"paper confidence is not measured: {detail}; the other source record(s) do "
        f"disclose coverage by name: {per_name}"
    )


def overall_confidence(
    coverage_map: dict[str, dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """The paper's `confidence` (§7.3): derived from its own coverage map, then
    held to the lowest overall band among the named source records.

    Two ceilings, and the tighter one wins. The map-derived band comes from
    Phase B's own `compute_confidence`, so the coverage-to-band mapping is
    shared rather than restated. The source-record ceiling is §7.3's own rule:
    a paper may not be more confident than the weakest analysis it stands on,
    however well-covered the names it happened to cite are.

    A THIRD state pre-empts both (issue #584/#587): if any source record's own
    `overall_band` is `NOT_MEASURED_BAND`, that record contributed no
    measurement at all, and `_BAND_RANK`-filtering it out of the ceiling
    comparison (as a plain "unrecognised band" would be) would silently drop
    it from consideration -- the exact defect #587's own docstring predicted
    for this module by name. The paper's band becomes `NOT_MEASURED_BAND`
    unconditionally in that case, never `high`, never the measured floor of
    whatever other records it also stands on."""
    derived_band = compute_confidence(coverage_map).get("overall_band")

    source_bands: list[str] = []
    unmeasured_brief_ids: list[str] = []
    for brief_id, record in records.items():
        confidence = record.get("confidence")
        if not isinstance(confidence, dict):
            continue
        band = confidence.get("overall_band")
        if band == NOT_MEASURED_BAND:
            unmeasured_brief_ids.append(brief_id)
        elif band in _BAND_RANK:
            source_bands.append(band)

    if unmeasured_brief_ids:
        return {
            "overall_band": NOT_MEASURED_BAND,
            "rationale": _unmeasured_source_rationale(sorted(unmeasured_brief_ids), coverage_map),
        }

    band = derived_band
    held = False
    if source_bands and derived_band in _BAND_RANK:
        floor = min(source_bands, key=lambda entry: _BAND_RANK[entry])
        if _BAND_RANK[derived_band] > _BAND_RANK[floor]:
            band, held = floor, True

    rationale = _paper_rationale(band, coverage_map)
    if held:
        rationale = (
            f"{rationale}. Held to {band!r}, the lowest overall band among "
            f"the source analysis records (§7.3): a paper is no more confident than "
            f"the weakest evidence it stands on"
        )
    return {"overall_band": band, "rationale": rationale}


# Confidence bands ordered `low < medium < high` (§7.4), and coverage bands
# ordered `thin < moderate < dense` (PHASE-B §7.7). Local rather than imported
# because `axial.validators.coverage` keeps its own rank maps private; two
# short ordinal vocabularies restated once is cheaper than widening that
# module's surface, and neither is a tunable.
_BAND_RANK = {"low": 0, "medium": 1, "high": 2}
_BAND_ORDER = {"thin": 0, "moderate": 1, "dense": 2}
