"""Inner unit tests for the sim case reader (§9.3, issue #491)."""

from __future__ import annotations

import json

from axial.eval.cases import load_case

_CASE = {
    "case_id": "DEVCASE",
    "question": "Q",
    "answer_kind": "rubric",
    "expected_answer": "a pre-written answer that must never leave this file",
    "required_citation_source_ids": ["tilly-1978", "bayat-2017"],
    "rubric": [],
    "instant_dismissal_criteria": ["Anything that ignores organization."],
}


def _write_case(cases_dir, payload):
    cases_dir.mkdir(parents=True, exist_ok=True)
    (cases_dir / f"{payload.get('case_id', 'DEVCASE')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_load_case_reads_both_oracle_fields(tmp_path):
    _write_case(tmp_path, _CASE)
    case = load_case("DEVCASE", cases_dir=tmp_path)
    assert case is not None
    assert case.required_citation_source_ids == ["tilly-1978", "bayat-2017"]
    assert case.instant_dismissal_criteria == ["Anything that ignores organization."]


def test_expected_answer_is_not_exposed(tmp_path):
    """§9.3 retires `expected_answer` as the referee and forbids putting it
    in a reviewer packet. A reader that handed it back would invite exactly
    that, so the field is not on the returned shape at all."""
    _write_case(tmp_path, _CASE)
    case = load_case("DEVCASE", cases_dir=tmp_path)
    assert not hasattr(case, "expected_answer")


def test_a_missing_case_is_none_not_an_error(tmp_path):
    """Most briefs have no case file by construction -- every dev fixture,
    every adversarial seed. An absent oracle costs the accuracy figure and
    nothing else."""
    assert load_case("NOPE", cases_dir=tmp_path) is None


def test_a_malformed_case_is_none_not_a_crash(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "BAD.json").write_text("{not json", encoding="utf-8")
    assert load_case("BAD", cases_dir=tmp_path) is None


def test_non_string_entries_are_dropped_rather_than_carried(tmp_path):
    _write_case(
        tmp_path,
        {**_CASE, "required_citation_source_ids": ["tilly-1978", None, 7, "  "]},
    )
    case = load_case("DEVCASE", cases_dir=tmp_path)
    assert case is not None
    assert case.required_citation_source_ids == ["tilly-1978"]


def test_every_committed_sim_case_still_states_both_oracles():
    """§9.3 says `instant_dismissal_criteria` is non-empty on every committed
    case and `required_citation_source_ids` survived the Phase A v1 rebuild.
    This pins both, since the whole point of this slice is that they are now
    read. 21 original cases plus the five S-0N cases authored with the
    2026-07-30 smoke-set rebuild (§9.0)."""
    from pathlib import Path

    cases_dir = Path("evals/cases/sim")
    case_ids = sorted(path.stem for path in cases_dir.glob("*.json"))
    assert len(case_ids) == 26
    for case_id in case_ids:
        case = load_case(case_id, cases_dir=cases_dir)
        assert case is not None
        assert case.required_citation_source_ids, case_id
        assert case.instant_dismissal_criteria, case_id
