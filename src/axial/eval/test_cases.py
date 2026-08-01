"""Inner unit tests for the sim case reader (§9.3, issue #491, #560)."""

from __future__ import annotations

import json

from axial.eval.cases import RequiredLeg, load_case

_CASE = {
    "case_id": "DEVCASE",
    "question": "Q",
    "answer_kind": "rubric",
    "expected_answer": "a pre-written answer that must never leave this file",
    "required_citation_legs": [
        {"leg": "the tilly leg", "any_of": ["tilly-1978"]},
        {"leg": "the bayat leg", "any_of": ["bayat-2017"]},
    ],
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
    assert case.required_citation_legs == (
        RequiredLeg(leg="the tilly leg", any_of=("tilly-1978",)),
        RequiredLeg(leg="the bayat leg", any_of=("bayat-2017",)),
    )
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
    """Applies to both forms: a non-string/empty entry inside a leg's
    `any_of`, and a non-string/empty entry in the older flat list."""
    _write_case(
        tmp_path,
        {
            **_CASE,
            "required_citation_legs": [
                {"leg": "the tilly leg", "any_of": ["tilly-1978", None, 7, "  "]},
            ],
        },
    )
    case = load_case("DEVCASE", cases_dir=tmp_path)
    assert case is not None
    assert case.required_citation_legs == (
        RequiredLeg(leg="the tilly leg", any_of=("tilly-1978",)),
    )


def test_a_leg_with_an_empty_any_of_after_filtering_is_dropped(tmp_path):
    """A leg can never be reached once every candidate in its `any_of` turns
    out non-string/empty, so it is dropped rather than kept as a phantom
    demand no run could ever satisfy."""
    _write_case(
        tmp_path,
        {
            **_CASE,
            "required_citation_legs": [
                {"leg": "the tilly leg", "any_of": ["tilly-1978"]},
                {"leg": "the empty leg", "any_of": [None, "  ", 7]},
            ],
        },
    )
    case = load_case("DEVCASE", cases_dir=tmp_path)
    assert case is not None
    assert case.required_citation_legs == (
        RequiredLeg(leg="the tilly leg", any_of=("tilly-1978",)),
    )


def test_old_flat_source_id_list_is_normalised_into_one_leg_per_id(tmp_path):
    """Back-compat (issue #560): a case stating only the older flat
    `required_citation_source_ids` is read as one leg per id, exactly
    preserving the score that shape has always produced for the cases not
    being re-authored in this slice."""
    _write_case(
        tmp_path,
        {
            **{k: v for k, v in _CASE.items() if k != "required_citation_legs"},
            "required_citation_source_ids": ["tilly-1978", "bayat-2017"],
        },
    )
    case = load_case("DEVCASE", cases_dir=tmp_path)
    assert case is not None
    assert case.required_citation_legs == (
        RequiredLeg(leg="tilly-1978", any_of=("tilly-1978",)),
        RequiredLeg(leg="bayat-2017", any_of=("bayat-2017",)),
    )


def test_when_both_forms_are_present_the_leg_form_wins(tmp_path):
    """A case in transition may carry both fields; `required_citation_legs`
    wins and the flat field is ignored entirely, so a case is never scored
    against two lists of truth at once."""
    _write_case(
        tmp_path,
        {
            **_CASE,
            "required_citation_source_ids": ["ignored-2000"],
        },
    )
    case = load_case("DEVCASE", cases_dir=tmp_path)
    assert case is not None
    assert case.required_citation_legs == (
        RequiredLeg(leg="the tilly leg", any_of=("tilly-1978",)),
        RequiredLeg(leg="the bayat leg", any_of=("bayat-2017",)),
    )


def test_every_committed_sim_case_still_states_both_oracles():
    """§9.3 says `instant_dismissal_criteria` is non-empty on every committed
    case and the citation oracle survived the Phase A v1 rebuild. This pins
    both, since the whole point of this slice is that they are now read. The
    set grows -- 21 original cases, the five S-0N cases authored with the
    2026-07-30 smoke-set rebuild (§9.0), the three eval questions authored
    2026-07-31 -- so the membership assertion names the families that must be
    present rather than a count that breaks every time one is added. A case
    may state either the flat `required_citation_source_ids` form or the
    `required_citation_legs` form (issue #560); both normalise to a non-empty
    `required_citation_legs` on the loaded case."""
    from pathlib import Path

    cases_dir = Path("evals/cases/sim")
    case_ids = sorted(path.stem for path in cases_dir.glob("*.json"))
    assert {"A", "B", "C"} <= set(case_ids), "the three eval questions (§9.0)"
    assert {f"S-0{n}" for n in range(1, 6)} <= set(case_ids), "the smoke cases (§9.0)"
    assert len(case_ids) >= 26
    for case_id in case_ids:
        case = load_case(case_id, cases_dir=cases_dir)
        assert case is not None
        assert case.required_citation_legs, case_id
        assert case.instant_dismissal_criteria, case_id
