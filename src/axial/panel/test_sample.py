"""Inner unit tests for the coherence sample spec (specs/PHASE-C.md §7.13,
issue #611 P0-12)."""

from __future__ import annotations

import json

import pytest

from axial.panel.sample import (
    SampleSpecParseError,
    UnstratifiedAxisError,
    load_sample_spec,
)


def _spec(**overrides):
    spec = {
        "sample_id": "coherence-2026-08-02",
        "corpus_pin": "sim-2026-07-30",
        "control_paper_id": "pb-control",
        "strata": [
            {
                "stratum_id": "s-medium-baseline",
                "tier": "medium",
                "model_combination": "baseline",
                "paper_brief_ids": ["pb-001", "pb-002"],
            },
            {
                "stratum_id": "s-high-open",
                "tier": "high",
                "model_combination": "open",
                "paper_brief_ids": ["pb-003"],
            },
        ],
    }
    spec.update(overrides)
    return spec


def _write(tmp_path, data):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_well_stratified_sample_loads(tmp_path):
    spec = load_sample_spec(_write(tmp_path, _spec()))
    assert spec.sample_id == "coherence-2026-08-02"
    assert spec.control_paper_id == "pb-control"
    assert len(spec.strata) == 2


def test_paper_brief_ids_are_deduplicated_across_strata(tmp_path):
    data = _spec()
    data["strata"][1]["paper_brief_ids"] = ["pb-001", "pb-003"]
    spec = load_sample_spec(_write(tmp_path, data))
    assert spec.paper_brief_ids() == ["pb-001", "pb-002", "pb-003"]


def test_a_single_tier_sample_is_rejected_naming_the_tier_axis(tmp_path):
    data = _spec()
    data["strata"][1]["tier"] = "medium"
    with pytest.raises(UnstratifiedAxisError) as excinfo:
        load_sample_spec(_write(tmp_path, data))
    assert excinfo.value.axis == "performance tier"


def test_a_single_model_combination_sample_is_rejected_naming_that_axis(tmp_path):
    data = _spec()
    data["strata"][1]["model_combination"] = "baseline"
    with pytest.raises(UnstratifiedAxisError) as excinfo:
        load_sample_spec(_write(tmp_path, data))
    assert excinfo.value.axis == "model combination"


def test_a_missing_field_is_a_parse_error(tmp_path):
    data = _spec()
    del data["control_paper_id"]
    with pytest.raises(SampleSpecParseError):
        load_sample_spec(_write(tmp_path, data))


def test_a_nonexistent_file_is_a_parse_error_not_an_uncaught_oserror(tmp_path):
    with pytest.raises(SampleSpecParseError):
        load_sample_spec(tmp_path / "does-not-exist.json")
