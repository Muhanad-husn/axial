"""Acceptance: a paper reads coverage from records written under either
vocabulary (issue #599, specs/PHASE-C.md §7.11).

Phase C read each claim's `names_touched` and each source map entry's
`corpus_note_count`. Four of the six analysis records on disk predate those
renames and carry `polities_touched` and `corpus_chunk_count` instead, so every
paper built on them produced an empty coverage map and reported
`not_measured` -- while the record beneath it had measured `high` across seven
polities. That is a false disclosure, not a missing one: #587 added
`not_measured` precisely so an unmeasured band could not be read as a measured
low, and here it said nothing was measured when something was.

The corpus stays mixed permanently (DEC-29), so these branch on KEY PRESENCE
rather than a version field, per #496.
"""

from __future__ import annotations

from axial.paper.claims import carried_claim, names_touched_of
from axial.paper.coverage import build_coverage_map, overall_confidence
from axial.paper.intake import InventoryClaim

OLD_ENTRY = {"corpus_chunk_count": 927, "evidence_chunk_count": 1, "coverage_band": "dense"}
NEW_ENTRY = {"corpus_note_count": 927, "evidence_note_count": 1, "coverage_band": "dense"}


def _record(entry, brief_id="b1"):
    return {
        "brief_id": brief_id,
        "confidence": {"overall_band": "high", "rationale": "..."},
        "coverage_map": {"France": dict(entry)},
    }


def _claim(names_key, brief_id="b1", claim_id="c1"):
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": "French colonial rule fragmented the territory.",
        "grounds": [],
        "confidence": "high",
        names_key: ["France"],
    }


def test_names_touched_reads_either_key():
    assert names_touched_of({"names_touched": ["France"]}) == ["France"]
    assert names_touched_of({"polities_touched": ["France"]}) == ["France"]
    assert names_touched_of({}) == []


def test_the_new_key_wins_when_a_record_somehow_carries_both():
    claim = {"names_touched": ["Syria"], "polities_touched": ["France"]}

    assert names_touched_of(claim) == ["Syria"]


def test_a_claim_carried_from_an_old_record_keeps_its_names():
    entry = InventoryClaim(brief_id="b1", claim_id="c1", claim=_claim("polities_touched"))

    carried = carried_claim("pc-001", "text", entry, {"France": dict(OLD_ENTRY)})

    assert carried["names_touched"] == ["France"]


def test_an_old_vocabulary_paper_reports_a_measured_band():
    """The regression. Before the fix this produced an empty map and
    `not_measured` on a record whose own band was `high`."""
    records = {"b1": _record(OLD_ENTRY)}
    entry = InventoryClaim(brief_id="b1", claim_id="c1", claim=_claim("polities_touched"))
    claims = [carried_claim("pc-001", "text", entry, records["b1"]["coverage_map"])]

    coverage_map = build_coverage_map(claims, records)
    confidence = overall_confidence(coverage_map, records)

    assert set(coverage_map) == {"France"}
    assert coverage_map["France"]["corpus_note_count"] == 927
    assert confidence["overall_band"] == "high"


def test_both_vocabularies_produce_the_same_map():
    """A record's vocabulary must not change the number a paper reports."""
    maps = []
    for names_key, map_entry in (
        ("polities_touched", OLD_ENTRY),
        ("names_touched", NEW_ENTRY),
    ):
        records = {"b1": _record(map_entry)}
        entry = InventoryClaim(brief_id="b1", claim_id="c1", claim=_claim(names_key))
        claims = [carried_claim("pc-001", "text", entry, records["b1"]["coverage_map"])]
        maps.append(build_coverage_map(claims, records))

    assert maps[0] == maps[1]
