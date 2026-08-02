"""Unit tests for `axial.paper.claims`'s new (c) claim: a paper's own verdict
(specs/PHASE-C.md §7.4, issue #577).

#574 redefined kind `(c)` as the analyst's own judgment, exempt from the
traceability ban, but the persisted vocabulary value stayed `"c"`. Before this
change `assert_ceilings` raised on ANY new kind-(c) claim under the pre-#574
reading of `(c)` as speculation -- so a paper could carry someone else's
verdict and never reach one of its own. These tests pin the settled fix: a
new (c) claim carries `derived_from` and grounds exactly like a new (b) claim,
is exempt from the two-distinct-records rule, and is capped by the same
confidence ceiling. New kind-(a) claims stay forbidden.
"""

from __future__ import annotations

import pytest

from axial.paper.claims import (
    ConfidenceCeilingError,
    NewAssertionError,
    SingleRecordInferenceError,
    UngroundedVerdictError,
    assert_ceilings,
    new_b_claim,
    new_c_claim,
)
from axial.paper.intake import InventoryClaim


def _by_id(*claims):
    return {claim["paper_claim_id"]: claim for claim in claims}


def _carried(paper_claim_id, brief_id, claim_id, band, chunk_id, names):
    return {
        "paper_claim_id": paper_claim_id,
        "text": "text",
        "kind": "a",
        "origin": {"brief_id": brief_id, "claim_id": claim_id},
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "confidence": band,
        "names_touched": names,
        "derived_from": [],
    }


def _inventory_entry(brief_id, claim_id, band, chunk_id):
    """An inventory entry whose own `confidence` passes through
    `clamped_band_for` unclamped against an empty coverage map (no
    `names_touched`, so there is nothing to derive a ceiling from) -- which
    is what lets `assert_ceilings`' carried-claim check see exactly `band`
    as the expected value."""
    return InventoryClaim(
        brief_id=brief_id,
        claim_id=claim_id,
        claim={
            "kind": "a",
            "confidence": band,
            "names_touched": [],
            "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        },
    )


def test_a_new_c_claim_carries_derived_from_and_the_union_of_grounds():
    parents = _by_id(
        _carried("pc-001", "brief-a", "a1", "high", "chunk-a1", ["Alice"]),
        _carried("pc-002", "brief-a", "a2", "medium", "chunk-a2", ["Bob"]),
    )
    verdict = new_c_claim(
        "pc-003", "On balance, the first account holds.", ["pc-001", "pc-002"], parents
    )

    assert verdict["kind"] == "c"
    assert verdict["origin"] is None
    assert verdict["derived_from"] == ["pc-001", "pc-002"]
    assert {g["ref_id"] for g in verdict["grounds"]} == {"chunk-a1", "chunk-a2"}
    assert verdict["names_touched"] == ["Alice", "Bob"]


def test_a_new_c_claim_with_empty_derived_from_raises():
    with pytest.raises(UngroundedVerdictError):
        new_c_claim("pc-003", "A verdict from nowhere.", [], {})


def test_a_new_c_claim_may_rest_on_a_single_record_where_b_may_not():
    parents = _by_id(
        _carried("pc-001", "brief-a", "a1", "high", "chunk-a1", ["Alice"]),
        _carried("pc-002", "brief-a", "a2", "medium", "chunk-a2", ["Alice"]),
    )
    # Both parents come from the SAME record ("brief-a").
    verdict = new_c_claim(
        "pc-003", "This record's account is the stronger one.", ["pc-001", "pc-002"], parents
    )
    assert verdict["kind"] == "c"

    with pytest.raises(SingleRecordInferenceError):
        new_b_claim("pc-003", "A restatement.", ["pc-001", "pc-002"], parents)


def test_a_new_c_claims_confidence_is_capped_at_its_weakest_input():
    parents = _by_id(
        _carried("pc-001", "brief-a", "a1", "high", "chunk-a1", ["Alice"]),
        _carried("pc-002", "brief-b", "b1", "low", "chunk-b1", ["Bob"]),
    )
    verdict = new_c_claim(
        "pc-003", "The weaker account still wins on its own terms.", ["pc-001", "pc-002"], parents
    )
    assert verdict["confidence"] == "low"


def test_a_new_b_claim_resolves_record_span_transitively_through_a_prior_new_claim():
    """A new claim's parent can itself be a new (b)/(c) claim, and the span
    check must resolve through it to the real source records rather than
    stopping at one hop (issue #616) -- otherwise a legitimate second-order
    inference over an already-cross-source claim reads as single-record
    (zero DIRECT carried parents) and is rejected regardless of what its
    parent actually spans."""
    parents = _by_id(
        _carried("pc-001", "brief-a", "a1", "high", "chunk-a1", ["Alice"]),
        _carried("pc-002", "brief-b", "b1", "medium", "chunk-b1", ["Bob"]),
    )
    first = new_b_claim(
        "pc-003", "The two accounts diverge on organization.", ["pc-001", "pc-002"], parents
    )
    parents["pc-003"] = first

    # Derives from ONLY the prior (b) claim -- no direct carried parent, so a
    # one-hop-only check would see zero source records here.
    second = new_b_claim(
        "pc-004", "That divergence tracks a deeper disagreement.", ["pc-003"], parents
    )
    assert second["kind"] == "b"
    assert second["derived_from"] == ["pc-003"]


_INVENTORY = {
    ("brief-a", "a1"): _inventory_entry("brief-a", "a1", "high", "chunk-a1"),
    ("brief-b", "b1"): _inventory_entry("brief-b", "b1", "low", "chunk-b1"),
}


def test_assert_ceilings_clamps_a_new_c_claim_to_its_weakest_input():
    claims = [
        _carried("pc-001", "brief-a", "a1", "high", "chunk-a1", []),
        _carried("pc-002", "brief-b", "b1", "low", "chunk-b1", []),
        {
            "paper_claim_id": "pc-003",
            "text": "A verdict claiming too much.",
            "kind": "c",
            "origin": None,
            "grounds": [{"ref_type": "chunk", "ref_id": "chunk-a1"}],
            "confidence": "high",  # exceeds the ceiling (min of high, low = low)
            "names_touched": [],
            "derived_from": ["pc-001", "pc-002"],
        },
    ]
    with pytest.raises(ConfidenceCeilingError):
        assert_ceilings(claims, _INVENTORY, {})


def test_assert_ceilings_accepts_a_new_c_claim_within_its_ceiling():
    claims = [
        _carried("pc-001", "brief-a", "a1", "high", "chunk-a1", []),
        _carried("pc-002", "brief-b", "b1", "low", "chunk-b1", []),
        {
            "paper_claim_id": "pc-003",
            "text": "A verdict honest about its own limits.",
            "kind": "c",
            "origin": None,
            "grounds": [{"ref_type": "chunk", "ref_id": "chunk-a1"}],
            "confidence": "low",
            "names_touched": [],
            "derived_from": ["pc-001", "pc-002"],
        },
    ]
    assert_ceilings(claims, _INVENTORY, {})  # no error


def test_a_new_kind_a_claim_still_raises():
    claims = [
        {
            "paper_claim_id": "pc-001",
            "text": "A source's own assertion, restated as the paper's.",
            "kind": "a",
            "origin": None,
            "grounds": [{"ref_type": "chunk", "ref_id": "chunk-a1"}],
            "confidence": "high",
            "names_touched": [],
            "derived_from": [],
        },
    ]
    with pytest.raises(NewAssertionError):
        assert_ceilings(claims, {}, {})
