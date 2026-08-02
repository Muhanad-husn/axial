"""Paper claims: carried, new, and the confidence ceiling (specs/PHASE-C.md
§7.4, §8 P0-3/P0-4).

Three kinds of entry, distinguished by `origin` and, among the new ones, by
`kind`, and the whole of Phase C's honesty rests on the distinction holding.

**A carried claim** is copied from the inventory with its kind, grounds and
band intact and `origin` naming where it came from. Its text may be re-worded
for the paper's prose; a re-worded carried (a) claim is still kind `a` and
still carries its origin. Phase C never restates an (a) claim as its own
inference -- that is the laundering failure §1 names, and no new kind-`a`
claim is ever built by this module (§3 non-goal 4, unchanged by #574/#577).

**A new (b) claim** is Phase C's own cross-source inference: `kind: b`,
`origin: null`, and a `derived_from` list spanning at least two distinct
source `brief_id`s. Its grounds are the union of the grounds of the claims it
derives from, so it points at real vault ids without the drafter ever
touching the vault.

**A new (c) claim is Phase C's own verdict** (issue #577, following #574's
redefinition of `(c)` as the analyst's own judgment, not "speculation").
Built the same mechanical way as a new (b) claim -- `kind: c`, `origin: null`,
grounds the union of a non-empty `derived_from` -- except a verdict is not
cross-source synthesis, so the two-distinct-records rule does not bind it: a
paper built from a single analysis record must still be able to reach one.
`derived_from` empty is still an error: a verdict that does not name what it
judges over is not a verdict, the same class of failure as a `weak` band
naming no defect.

**The band a carried claim carries is its origin's CLAMPED band**, not the
band the analysis record persisted (§7.4, issue #550). Phase B persists the
model's own emitted band and clamps only what it renders; 93 of 121 claims
across the six smoke-v5 records differ between the two. Copying the persisted
field would lift an unclamped band into a paper and render it beside the
paper's own coverage counts, which is confidence inflation across a layer
boundary wearing the costume of fidelity. **A new (c) claim's band is capped
identically to a new (b) claim's** -- the minimum over `derived_from` -- so a
verdict reached over thin evidence renders as a thin verdict, never a
confident one beside weak coverage counts.

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
MIN_DISTINCT_RECORDS = 2


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
            f"{MIN_DISTINCT_RECORDS}. A claim drawn from one record is a restatement, "
            f"not cross-source synthesis"
        )


class UngroundedVerdictError(PaperClaimError):
    """Raised when a new (c) claim's `derived_from` is empty (issue #577).

    A verdict is exempt from the two-distinct-records rule, but not from
    naming what it judges over: `derived_from` is how a (c) claim points at
    real vault ids without the drafter ever touching the vault, exactly like
    a (b) claim. An empty list is the same class of error as a `weak` band
    naming no defect -- a verdict that does not say what it judges over is
    not a verdict."""

    def __init__(self, paper_claim_id: str):
        self.paper_claim_id = paper_claim_id
        super().__init__(
            f"new (c) claim {paper_claim_id!r} carries an empty derived_from -- a "
            f"verdict must name the claims it judges over (§7.4, issue #577)"
        )


class NewAssertionError(PaperClaimError):
    """Raised when a new claim (no `origin`) is kind 'a' (§3 non-goal 4).

    This is the one new-claim kind Phase C never builds, before or after
    issue #577: restating a source's own assertion as the tool's contribution
    is the laundering failure §1 names. Renamed from `SpeculationError`
    (issue #577) -- that class blocked every new (c) claim under the
    pre-#574 reading of `(c)` as speculation; #574 redefined `(c)` as the
    analyst's own judgment and exempted it from the traceability ban, so the
    prohibition that survives is on kind `a`, not kind `c`."""

    def __init__(self, paper_claim_id: str):
        self.paper_claim_id = paper_claim_id
        super().__init__(
            f"new claim {paper_claim_id!r} is kind 'a'; Phase C never builds a new "
            f"kind-'a' claim (§3 non-goal 4) -- restating a source's assertion as "
            f"the paper's own contribution is the laundering failure §1 names. A "
            f"carried (a) claim keeps its origin"
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


def names_touched_of(claim: dict[str, Any]) -> list[str]:
    """The names a Phase-B claim touches, under either vocabulary (issue #599).

    Records written before the names rename carry the same values under
    `polities_touched`. Four of the six analysis records on disk still do, and
    the sim corpus is not regenerated wholesale (DEC-29), so a mixed corpus is
    the permanent condition rather than a migration window. This branches on
    KEY PRESENCE rather than a version field, which is the rule #496 settled
    one layer down."""
    for key in ("names_touched", "polities_touched"):
        values = claim.get(key)
        if values:
            return [name for name in values if isinstance(name, str) and name]
    return []


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
        "names_touched": names_touched_of(origin),
        "derived_from": [],
    }


def _brief_ids_of(
    parent_id: str, by_paper_claim_id: dict[str, dict[str, Any]], visited: set[str]
) -> set[str]:
    """The distinct source records reachable from one claim, resolved
    TRANSITIVELY (issue #616).

    `grounds` and `names_touched` already inherit transitively for free: a
    new claim's own fields are the union over ITS ancestors, computed when it
    was built, so a later claim that derives from it inherits the union just
    by copying that field. Source records have no such persisted field, so a
    parent that is itself a new (b)/(c) claim (`origin` is `None`) is resolved
    by walking ITS `derived_from` in turn, not counted as contributing zero
    records -- one hop is not the whole chain."""
    if parent_id in visited:
        return set()
    visited.add(parent_id)
    parent = by_paper_claim_id.get(parent_id)
    if parent is None:
        raise UnknownInventoryClaimError((parent_id, ""))
    origin = parent.get("origin")
    if isinstance(origin, dict) and origin.get("brief_id"):
        return {str(origin["brief_id"])}
    brief_ids: set[str] = set()
    for grandparent_id in parent.get("derived_from") or []:
        brief_ids |= _brief_ids_of(grandparent_id, by_paper_claim_id, visited)
    return brief_ids


def _union_over_derivation(
    derived_from: list[str], by_paper_claim_id: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """Grounds and `names_touched`, both the UNION over `derived_from`,
    deduplicated with order preserved, plus the distinct source `brief_id`s
    reached -- shared by `new_b_claim` and `new_c_claim` (issue #577) so the
    mechanism for "what a synthesis claim points at" cannot drift between the
    two. Neither grounds nor names are asked of the drafter: the drafter
    chooses what the claim reasons from, and the pointers follow mechanically,
    which is what makes a new claim grounded by construction rather than by
    the model's care."""
    grounds: list[dict[str, Any]] = []
    seen_grounds: set[tuple[Any, Any]] = set()
    names: list[str] = []
    seen_names: set[str] = set()
    brief_ids: set[str] = set()

    for parent_id in derived_from:
        parent = by_paper_claim_id.get(parent_id)
        if parent is None:
            raise UnknownInventoryClaimError((parent_id, ""))
        brief_ids |= _brief_ids_of(parent_id, by_paper_claim_id, set())
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

    return grounds, names, brief_ids


def new_b_claim(
    paper_claim_id: str,
    text: str,
    derived_from: list[str],
    by_paper_claim_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one new (b) claim from claims already in the paper (§7.4): a
    cross-source inference, which is what the two-distinct-records rule
    checks for."""
    grounds, names, brief_ids = _union_over_derivation(derived_from, by_paper_claim_id)

    if len(brief_ids) < MIN_DISTINCT_RECORDS:
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


def new_c_claim(
    paper_claim_id: str,
    text: str,
    derived_from: list[str],
    by_paper_claim_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one new (c) claim from claims already in the paper: the paper's
    own verdict (§7.4, issue #577), not cross-source synthesis, so unlike
    `new_b_claim` it does not require two distinct source records -- a paper
    built from a single analysis record must still be able to reach one. It
    does require a non-empty `derived_from`: a verdict that names nothing it
    judges over is not a verdict."""
    if not derived_from:
        raise UngroundedVerdictError(paper_claim_id)

    grounds, names, _brief_ids = _union_over_derivation(derived_from, by_paper_claim_id)

    return {
        "paper_claim_id": paper_claim_id,
        "text": text,
        "kind": "c",
        "origin": None,
        "grounds": grounds,
        "confidence": _min_band(derived_from, by_paper_claim_id),
        "names_touched": names,
        "derived_from": list(derived_from),
    }


def _min_band(derived_from: list[str], by_paper_claim_id: dict[str, dict[str, Any]]) -> Any:
    """The lowest band among the claims a new (b) or (c) claim stands on.

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

    `carried_claim`, `new_b_claim` and `new_c_claim` construct claims that
    satisfy this by construction, so this exists for the claims they did not
    build: a record loaded from disk, or a hand-edited one. A gate that only
    ever checks its own output checks nothing."""
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

        # A new claim (no origin). §3 non-goal 4: Phase C never builds a new
        # kind-'a' claim -- that is the one prohibition #574/#577 leave
        # standing. New (b) and (c) claims share the same ceiling below.
        if claim.get("kind") == "a":
            raise NewAssertionError(paper_claim_id)

        ceiling = _min_band(list(claim.get("derived_from") or []), by_id)
        if band in _BAND_RANK and ceiling in _BAND_RANK:
            if _BAND_RANK[band] > _BAND_RANK[ceiling]:
                raise ConfidenceCeilingError(
                    paper_claim_id,
                    band,
                    ceiling,
                    "a synthesis is no stronger than the weakest claim holding it up",
                )
