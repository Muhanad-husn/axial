"""Paper claims: carried, new, and the confidence ceiling (specs/PHASE-C.md
§7.4, §8 P0-3/P0-4).

Two kinds of entry, distinguished by `origin`, and the whole of Phase C's
honesty rests on the distinction holding.

**A carried claim** is copied from the inventory with its kind, grounds and
band intact and `origin` naming where it came from. Its text may be re-worded
for the paper's prose; a re-worded carried (a) claim is still kind `a` and
still carries its origin. Phase C never restates an (a) claim as its own
inference -- that is the laundering failure §1 names.

**A new (b) claim** is Phase C's own contribution: `kind: b`, `origin: null`,
and a `derived_from` list spanning at least two distinct source `brief_id`s.
Its grounds are the union of the grounds of the claims it derives from, so it
points at real vault ids without the drafter ever touching the vault.

**The band a carried claim carries is its origin's CLAMPED band**, not the
band the analysis record persisted (§7.4, issue #550). Phase B persists the
model's own emitted band and clamps only what it renders; 93 of 121 claims
across the six smoke-v5 records differ between the two. Copying the persisted
field would lift an unclamped band into a paper and render it beside the
paper's own coverage counts, which is confidence inflation across a layer
boundary wearing the costume of fidelity.

Model-free: this module assembles and validates what the drafter returned. It
never calls anything.
"""

from __future__ import annotations

from typing import Any

from axial.paper.coverage import clamped_band_for
from axial.paper.intake import InventoryClaim

# Bands ordered `low < medium < high` (§7.4).
_BAND_RANK = {"low": 0, "medium": 1, "high": 2}

# A new (b) claim must reason across at least this many DISTINCT source
# records. Not a tunable: two is what "cross-source" means, and one is a
# restatement (§7.4).
_MIN_DISTINCT_RECORDS = 2


class PaperClaimError(Exception):
    """Base class for paper-claim assembly failures."""


class UnknownInventoryClaimError(PaperClaimError):
    """Raised when a carried claim names an inventory entry that is not there."""

    def __init__(self, key: tuple[str, str]):
        self.key = key
        super().__init__(
            f"carried claim names inventory entry {key!r}, which the claim inventory "
            f"does not hold; a carried claim must name a real (brief_id, claim_id)"
        )


class SingleRecordInferenceError(PaperClaimError):
    """Raised when a new (b) claim does not span two distinct source records.

    This is the mechanical half of "cross-source rather than a restatement"
    (§7.4). A (b) claim resting on one record's claims is a summary of that
    record, and Phase C's entire contribution is the part that is not."""

    def __init__(self, paper_claim_id: str, brief_ids: set[str]):
        self.paper_claim_id = paper_claim_id
        self.brief_ids = set(brief_ids)
        super().__init__(
            f"new (b) claim {paper_claim_id!r} derives from {sorted(brief_ids)!r} -- "
            f"{len(brief_ids)} distinct source record(s), and §7.4 requires at least "
            f"{_MIN_DISTINCT_RECORDS}. A claim drawn from one record is a restatement, "
            f"not cross-source synthesis"
        )


class SpeculationError(PaperClaimError):
    """Raised when the drafter emits a NEW kind-(c) claim (§3 non-goal 4).

    A (c) claim already present in a source record may be carried, marked and
    cited. v0 does not invent them."""

    def __init__(self, paper_claim_id: str):
        self.paper_claim_id = paper_claim_id
        super().__init__(
            f"new claim {paper_claim_id!r} is kind 'c'; Phase C v0 emits no new "
            f"speculation (§3 non-goal 4). A carried (c) claim keeps its origin"
        )


class ConfidenceCeilingError(PaperClaimError):
    """Raised when a claim's band exceeds what §7.4 permits it.

    Both limbs are hard and both fail the provenance-integrity gate: a carried
    claim's band must equal its origin's clamped band, and a new (b) claim's
    band may not exceed the minimum among the claims it derives from."""

    def __init__(self, paper_claim_id: str, band: Any, ceiling: Any, reason: str):
        self.paper_claim_id = paper_claim_id
        self.band = band
        self.ceiling = ceiling
        super().__init__(
            f"claim {paper_claim_id!r} discloses band {band!r} against a ceiling of "
            f"{ceiling!r}: {reason}"
        )


def carried_claim(
    paper_claim_id: str,
    text: str,
    entry: InventoryClaim,
    source_coverage_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one carried claim (§7.4).

    `source_coverage_map` is the ORIGIN RECORD's own map, not the paper's:
    the clamp that produced the band Phase B renders was computed against that
    record's coverage, and re-deriving it against the paper's map would answer
    a different question with the same arithmetic."""
    origin = entry.claim
    return {
        "paper_claim_id": paper_claim_id,
        "text": text,
        "kind": origin.get("kind"),
        "origin": {"brief_id": entry.brief_id, "claim_id": entry.claim_id},
        "grounds": list(origin.get("grounds") or []),
        "confidence": clamped_band_for(origin, source_coverage_map),
        "names_touched": list(origin.get("names_touched") or []),
        "derived_from": [],
    }


def new_b_claim(
    paper_claim_id: str,
    text: str,
    derived_from: list[str],
    by_paper_claim_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one new (b) claim from claims already in the paper (§7.4).

    Grounds and `names_touched` are both the UNION over `derived_from`,
    deduplicated with order preserved. Neither is asked of the drafter: the
    drafter chooses what the claim reasons from, and the pointers follow
    mechanically, which is what makes a new claim grounded by construction
    rather than by the model's care."""
    grounds: list[dict[str, Any]] = []
    seen_grounds: set[tuple[Any, Any]] = set()
    names: list[str] = []
    seen_names: set[str] = set()
    brief_ids: set[str] = set()

    for parent_id in derived_from:
        parent = by_paper_claim_id.get(parent_id)
        if parent is None:
            raise UnknownInventoryClaimError((parent_id, ""))
        origin = parent.get("origin")
        if isinstance(origin, dict) and origin.get("brief_id"):
            brief_ids.add(str(origin["brief_id"]))
        for ground in parent.get("grounds") or []:
            if not isinstance(ground, dict):
                continue
            key = (ground.get("ref_type"), ground.get("ref_id"))
            if key not in seen_grounds:
                seen_grounds.add(key)
                grounds.append(dict(ground))
        for name in parent.get("names_touched") or []:
            if name not in seen_names:
                seen_names.add(name)
                names.append(name)

    if len(brief_ids) < _MIN_DISTINCT_RECORDS:
        raise SingleRecordInferenceError(paper_claim_id, brief_ids)

    return {
        "paper_claim_id": paper_claim_id,
        "text": text,
        "kind": "b",
        "origin": None,
        "grounds": grounds,
        "confidence": _min_band(derived_from, by_paper_claim_id),
        "names_touched": names,
        "derived_from": list(derived_from),
    }


def _min_band(derived_from: list[str], by_paper_claim_id: dict[str, dict[str, Any]]) -> Any:
    """The lowest band among the claims a new (b) claim stands on.

    A band outside the vocabulary is ignored rather than ranked, exactly as
    `confidence_ceiling_for_claim` refuses to rank one: an out-of-vocabulary
    value has no position in an ordering, and inventing one would silently
    decide the ceiling. With nothing rankable at all the band is `low`, the
    most conservative answer, never a pass-through of whatever was there."""
    bands = [
        band
        for parent_id in derived_from
        if (band := (by_paper_claim_id.get(parent_id) or {}).get("confidence")) in _BAND_RANK
    ]
    if not bands:
        return "low"
    return min(bands, key=lambda band: _BAND_RANK[band])


def assert_ceilings(
    claims: list[dict[str, Any]],
    inventory_by_key: dict[tuple[str, str], InventoryClaim],
    source_coverage_maps: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """The §7.4 ceiling over a finished claim list, checked rather than
    assumed (P0-4, and the provenance-integrity gate's second metric).

    `carried_claim` and `new_b_claim` construct claims that satisfy this by
    construction, so this exists for the claims they did not build: a record
    loaded from disk, or a hand-edited one. A gate that only ever checks its
    own output checks nothing."""
    by_id = {claim.get("paper_claim_id"): claim for claim in claims}

    for claim in claims:
        paper_claim_id = str(claim.get("paper_claim_id"))
        band = claim.get("confidence")
        origin = claim.get("origin")

        if isinstance(origin, dict):
            key = (origin.get("brief_id"), origin.get("claim_id"))
            entry = inventory_by_key.get(key)  # type: ignore[arg-type]
            if entry is None:
                raise UnknownInventoryClaimError(key)  # type: ignore[arg-type]
            expected = clamped_band_for(entry.claim, source_coverage_maps.get(entry.brief_id, {}))
            if band != expected:
                raise ConfidenceCeilingError(
                    paper_claim_id,
                    band,
                    expected,
                    "a carried claim's band equals its origin's clamped band exactly -- "
                    "raising it inflates, lowering it is its own dishonesty",
                )
            continue

        if claim.get("kind") == "c":
            raise SpeculationError(paper_claim_id)

        ceiling = _min_band(list(claim.get("derived_from") or []), by_id)
        if band in _BAND_RANK and ceiling in _BAND_RANK:
            if _BAND_RANK[band] > _BAND_RANK[ceiling]:
                raise ConfidenceCeilingError(
                    paper_claim_id,
                    band,
                    ceiling,
                    "a synthesis is no stronger than the weakest claim holding it up",
                )
