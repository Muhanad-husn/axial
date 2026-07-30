"""Inner unit tests for the positive control (issue #385, §9.4 property 6,
DEC-23)."""

from __future__ import annotations

import pytest

from axial.panel.control import (
    MIS_GROUNDED,
    OVERCONFIDENT,
    STRAWMAN,
    Plant,
    PlantNotApplicableError,
    format_control_report,
    plant_all,
    plant_mis_grounded,
    plant_overconfident,
    plant_strawman_counter_position,
    score_control,
)
from axial.panel.review import Defect, PanelReport, ReviewerVerdict


def _record():
    return {
        "brief_id": "b-001",
        "claims": [
            {
                "claim_id": "c-1",
                "kind": "a",
                "text": "Bureaucratic capacity fell.",
                "names_touched": ["syria"],
                "confidence": "medium",
                "grounds": [{"ref_type": "chunk", "ref_id": "chunk_a"}],
            },
            {
                "claim_id": "c-2",
                "kind": "a",
                "text": "Militia payrolls grew.",
                "names_touched": ["lebanon"],
                "confidence": "high",
                "grounds": [{"ref_type": "chunk", "ref_id": "chunk_b"}],
            },
        ],
        "counter_position": {
            "present": True,
            "stance": "War strengthened the state.",
            "grounds": [{"ref_type": "chunk", "ref_id": "chunk_c"}],
        },
        "coverage_map": {
            "syria": {"coverage_band": "thin", "corpus_chunk_count": 3},
            "lebanon": {"coverage_band": "rich", "corpus_chunk_count": 400},
        },
    }


def _verdict(defects, model="anthropic/claude-opus-4"):
    return ReviewerVerdict(
        model=model,
        vendor="anthropic",
        bands={"factual_correctness": "weak", "citation_grounding": "weak", "completeness": "weak"},
        defects=defects,
    )


def _report(verdicts):
    return PanelReport(
        brief_id="b-001", corpus_pin="pin-1", reviewers=verdicts, dimensions=[], trusted=False
    )


# -- the plants are content-free record mutations ----------------------------


def test_mis_grounded_repoints_a_claim_at_another_claims_evidence():
    mutated, plant = plant_mis_grounded(_record())
    assert plant == Plant(kind=MIS_GROUNDED, claim_id="c-1")
    assert mutated["claims"][0]["grounds"] == [{"ref_type": "chunk", "ref_id": "chunk_b"}]


def test_strawman_repoints_the_counter_position_at_the_claim_it_opposes():
    mutated, plant = plant_strawman_counter_position(_record())
    assert plant.kind == STRAWMAN
    assert mutated["counter_position"]["grounds"] == [{"ref_type": "chunk", "ref_id": "chunk_a"}]


def test_overconfident_raises_a_thin_coverage_claim_to_high():
    mutated, plant = plant_overconfident(_record())
    assert plant == Plant(kind=OVERCONFIDENT, claim_id="c-1")
    assert mutated["claims"][0]["confidence"] == "high"


def test_overconfident_matches_on_any_of_a_multi_name_claims_names_touched():
    """§7.4: `names_touched` is a list -- a claim that touches a
    thin-coverage polity ALONGSIDE a dense one must still be caught, not
    missed because the thin polity is not the only one it touches."""
    record = _record()
    record["claims"][0]["names_touched"] = ["lebanon", "syria"]
    mutated, plant = plant_overconfident(record)
    assert plant == Plant(kind=OVERCONFIDENT, claim_id="c-1")
    assert mutated["claims"][0]["confidence"] == "high"


def test_no_plant_invents_prose_or_embeds_text():
    """DEC-23: plants are deterministic selector-driven mutations. Every
    string in a mutated record must already exist in the original."""
    original = _record()

    def strings(node):
        if isinstance(node, str):
            return {node}
        if isinstance(node, dict):
            return set().union(*(strings(v) for v in node.values())) if node else set()
        if isinstance(node, list):
            return set().union(*(strings(v) for v in node)) if node else set()
        return set()

    before = strings(original)
    for mutated, _ in plant_all(original):
        assert strings(mutated) <= before


def test_plants_do_not_mutate_the_original_record():
    original = _record()
    plant_all(original)
    assert original["claims"][0]["grounds"] == [{"ref_type": "chunk", "ref_id": "chunk_a"}]
    assert original["claims"][0]["confidence"] == "medium"


def test_plants_are_deterministic():
    first = [mutated for mutated, _ in plant_all(_record())]
    second = [mutated for mutated, _ in plant_all(_record())]
    assert first == second


# -- an inapplicable plant is an error, never a silent skip ------------------


def test_mis_grounded_on_a_single_claim_record_raises():
    record = _record()
    record["claims"] = record["claims"][:1]
    with pytest.raises(PlantNotApplicableError):
        plant_mis_grounded(record)


def test_strawman_without_a_counter_position_raises():
    record = _record()
    record["counter_position"] = {"present": False}
    with pytest.raises(PlantNotApplicableError):
        plant_strawman_counter_position(record)


def test_overconfident_without_a_thin_polity_raises():
    record = _record()
    record["coverage_map"]["syria"]["coverage_band"] = "rich"
    with pytest.raises(PlantNotApplicableError):
        plant_overconfident(record)


# -- scoring: a generous panel must fail the control -------------------------


def _plants():
    return [plant for _, plant in plant_all(_record())]


def test_control_passes_when_every_plant_is_caught_by_a_majority():
    results = []
    for plant in _plants():
        caught = Defect(claim_id=plant.claim_id, kind=plant.kind)
        results.append((plant, _report([_verdict([caught])] * 3)))
    report = score_control(results)
    assert report.passed is True
    assert all(outcome.caught for outcome in report.outcomes)


def test_a_single_catcher_among_three_is_not_a_catch():
    """The control tests for systematic generosity: one reviewer catching a
    planted defect is consistent with a panel that mostly waves them past."""
    results = []
    for plant in _plants():
        caught = Defect(claim_id=plant.claim_id, kind=plant.kind)
        results.append((plant, _report([_verdict([caught]), _verdict([]), _verdict([])])))
    assert score_control(results).passed is False


def test_the_right_defect_on_the_wrong_claim_is_not_a_catch():
    results = []
    for plant in _plants():
        wrong = Defect(claim_id="c-99", kind=plant.kind)
        results.append((plant, _report([_verdict([wrong])] * 3)))
    assert score_control(results).passed is False


def test_catching_two_of_three_plants_fails_the_whole_control():
    """A panel with a known blind spot is not trustworthy past it."""
    results = []
    for index, plant in enumerate(_plants()):
        defects = [] if index == 2 else [Defect(claim_id=plant.claim_id, kind=plant.kind)]
        results.append((plant, _report([_verdict(defects)] * 3)))
    report = score_control(results)
    assert report.passed is False
    assert [outcome.caught for outcome in report.outcomes] == [True, True, False]


def test_an_empty_control_never_passes():
    assert score_control([]).passed is False


def test_a_failed_control_says_no_number_is_reportable():
    results = [(plant, _report([_verdict([])] * 3)) for plant in _plants()]
    rendered = format_control_report(score_control(results))
    assert "MISSED" in rendered
    assert "no panel number is reportable" in rendered
