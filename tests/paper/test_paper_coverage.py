"""Acceptance: the paper's coverage roll-up treats `not_measured` (issue
#584/#587) as a real fourth value, never an unrecognised string to filter out
(specs/PHASE-C.md §7.3, §7.11, issue #584 Phase C follow-up).

`overall_confidence`'s source-record ceiling built its floor from
`source_bands`, a list comprehension filtered `in _BAND_RANK` -- exactly the
shape that silently drops a `not_measured` source record from consideration,
which is the defect #587's own docstring named this module as the consumer
that must not repeat. These three cases pin the fix: mixed (one measured, one
not_measured) must not read as the measured record's band; all-unmeasured
must report `not_measured` with a rationale that says nothing was measured;
all-measured is unchanged, because this must not move the number on any paper
built from name-layer records alone."""

from __future__ import annotations

from axial.paper.coverage import build_coverage_map, overall_confidence
from axial.validators.coverage import NOT_MEASURED_BAND

TILLY_ENTRY = {
    "corpus_note_count": 154,
    "evidence_note_count": 8,
    "coverage_band": "dense",
}


def _namelayer_record(brief_id="b1"):
    return {
        "brief_id": brief_id,
        "confidence": {"overall_band": "high", "rationale": "..."},
        "coverage_map": {"Charles Tilly": dict(TILLY_ENTRY)},
    }


def _mapfed_record(brief_id="b2"):
    """An argument-map-fed record (§7.17): queries no name, so its own
    coverage_map is empty and its confidence is #587's `not_measured`."""
    return {
        "brief_id": brief_id,
        "confidence": {"overall_band": NOT_MEASURED_BAND, "rationale": "nothing was measured..."},
        "coverage_map": {},
    }


def _claim_touching_tilly(claim_id="c1"):
    return {
        "claim_id": claim_id,
        "grounds": [{"ref_type": "chunk", "ref_id": "tilly-1978-aaa_1_war_001"}],
        "names_touched": ["Charles Tilly"],
    }


def test_all_measured_is_unchanged():
    """The pre-existing case: every source record measured something, and the
    paper's own band is the derived band held to the source floor. This must
    not move -- the regression this fix is not allowed to cause."""
    records = {"b1": _namelayer_record()}
    claims = [_claim_touching_tilly()]
    coverage_map = build_coverage_map(claims, records)

    result = overall_confidence(coverage_map, records)

    assert result["overall_band"] == "high"
    assert "not measured" not in result["rationale"]
    assert "Charles Tilly" in result["rationale"]


def test_mixed_measured_and_unmeasured_does_not_read_as_the_measured_band():
    """One dense, measured record and one not_measured (map-fed) record. The
    paper must not report the measured record's `high` band -- that would make
    the unmeasured leg invisible, exactly #584's defect one layer up."""
    namelayer = _namelayer_record("b1")
    mapfed = _mapfed_record("b2")
    records = {"b1": namelayer, "b2": mapfed}
    claims = [_claim_touching_tilly()]
    coverage_map = build_coverage_map(claims, records)

    # The map itself still carries what b1 covers -- only the confidence
    # roll-up is at stake here.
    assert coverage_map == {
        "Charles Tilly": {
            "corpus_note_count": TILLY_ENTRY["corpus_note_count"],
            "cited_claim_count": 1,
            "coverage_band": TILLY_ENTRY["coverage_band"],
        }
    }

    result = overall_confidence(coverage_map, records)

    assert result["overall_band"] == NOT_MEASURED_BAND
    assert result["overall_band"] != "high"
    rationale = result["rationale"]
    assert "not measured" in rationale
    assert "b2" in rationale
    # Disclosed, not averaged: the mixed case still names what WAS covered.
    assert "Charles Tilly" in rationale


def test_all_unmeasured_reports_not_measured_with_a_nothing_was_measured_rationale():
    """Both source records are map-fed: the paper's own coverage_map is empty
    too, and the rationale must say nothing was measured rather than implying
    a band was derived and found wanting (the pre-#587 language this replaces)."""
    records = {"b1": _mapfed_record("b1"), "b2": _mapfed_record("b2")}
    claims: list = []
    coverage_map = build_coverage_map(claims, records)
    assert coverage_map == {}

    result = overall_confidence(coverage_map, records)

    assert result["overall_band"] == NOT_MEASURED_BAND
    rationale = result["rationale"]
    assert "not measured" in rationale
    assert "to justify a higher band" not in rationale
    assert "b1" in rationale and "b2" in rationale


def test_not_measured_is_never_ranked_against_a_measured_band():
    """`not_measured` never wins a `min()` comparison against a real band --
    it must not silently become the "floor" the way a plain string would if it
    were added to a rank map with some numeric value."""
    from axial.paper.coverage import _BAND_RANK

    assert NOT_MEASURED_BAND not in _BAND_RANK
