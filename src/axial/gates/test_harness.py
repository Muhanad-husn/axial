"""Inner unit tests for the common rung-3 gate harness (issue #262,
specs/PHASE-B.md §10). Co-located under src/axial/gates/ per the repo's
existing test layout (mirrors src/axial/validators/test_attribution.py,
src/axial/eval/test_corpus_pin_unit.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.gates.harness import (
    GateError,
    GateReport,
    MetricResult,
    academic_cases_present,
    build_metric_result,
    comparison_for,
    format_report,
    load_records,
    resolve_corpus_pin,
    resolve_threshold,
    resolve_trusted,
    write_report,
)


# -- MetricResult / GateReport shape -----------------------------------------


def test_metric_result_to_json_carries_the_common_shape():
    metric = MetricResult(
        metric="attribution_completeness",
        value=1.0,
        threshold=1.0,
        comparison="gte",
        passed=True,
        n=20,
    )
    payload = metric.to_json()
    assert payload == {
        "metric": "attribution_completeness",
        "value": 1.0,
        "threshold": 1.0,
        "comparison": "gte",
        "passed": True,
        "n": 20,
    }


def test_metric_result_detail_merges_into_json():
    metric = MetricResult(
        metric="attribution_completeness",
        value=0.5,
        threshold=1.0,
        comparison="gte",
        passed=False,
        n=2,
        detail={"failing_claim_ids": ["c-1"]},
    )
    assert metric.to_json()["failing_claim_ids"] == ["c-1"]


def test_gate_report_passed_is_conjunction_of_metrics():
    passing = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    failing = MetricResult("m2", 0.0, 1.0, "gte", False, 1)
    report = GateReport(gate="g", corpus_pin=None, trusted=False, metrics=[passing, failing])
    assert report.passed is False

    report_all_pass = GateReport(gate="g", corpus_pin=None, trusted=False, metrics=[passing])
    assert report_all_pass.passed is True


def test_gate_report_to_json_carries_gate_corpus_pin_trusted():
    metric = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    report = GateReport(
        gate="attribution-fidelity", corpus_pin="baseline", trusted=True, metrics=[metric]
    )
    payload = report.to_json()
    assert payload["gate"] == "attribution-fidelity"
    assert payload["corpus_pin"] == "baseline"
    assert payload["trusted"] is True
    assert payload["passed"] is True
    assert payload["metrics"][0]["metric"] == "m1"


# -- threshold resolution: config, never a literal ---------------------------


def test_resolve_threshold_falls_back_to_default_when_config_absent(tmp_path: Path):
    missing_config = tmp_path / "nonexistent.yaml"
    assert resolve_threshold("attribution_completeness", missing_config) == 1.00
    assert resolve_threshold("b_seam_mislabel_rate", missing_config) == 0.05
    assert resolve_threshold("grounding_support_rate", missing_config) == 0.90


def test_resolve_threshold_reads_config_override(tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("gates:\n  attribution_completeness: 0.95\n", encoding="utf-8")
    assert resolve_threshold("attribution_completeness", config_path) == 0.95
    # An un-overridden metric in the same file still falls back to default.
    assert resolve_threshold("grounding_support_rate", config_path) == 0.90


def test_resolve_threshold_unknown_metric_raises(tmp_path: Path):
    with pytest.raises(GateError):
        resolve_threshold("not_a_real_metric", tmp_path / "nonexistent.yaml")


def test_comparison_for_known_metrics():
    assert comparison_for("attribution_completeness") == "gte"
    assert comparison_for("b_seam_mislabel_rate") == "lte"
    assert comparison_for("grounding_support_rate") == "gte"


# -- build_metric_result: direction, boundary, empty-denominator rules ------


def test_gte_metric_passes_at_exactly_the_threshold(tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("gates:\n  attribution_completeness: 1.0\n", encoding="utf-8")
    result = build_metric_result(
        "attribution_completeness",
        numerator=10,
        denominator=10,
        config_path=config_path,
        empty_denominator_fails=True,
    )
    assert result.value == 1.0
    assert result.passed is True


def test_lte_metric_passes_at_exactly_the_threshold(tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("gates:\n  b_seam_mislabel_rate: 0.05\n", encoding="utf-8")
    result = build_metric_result(
        "b_seam_mislabel_rate",
        numerator=1,
        denominator=20,
        config_path=config_path,
        empty_denominator_fails=False,
    )
    assert result.value == 0.05
    assert result.passed is True


def test_lte_metric_fails_just_above_the_threshold(tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("gates:\n  b_seam_mislabel_rate: 0.05\n", encoding="utf-8")
    result = build_metric_result(
        "b_seam_mislabel_rate",
        numerator=2,
        denominator=20,
        config_path=config_path,
        empty_denominator_fails=False,
    )
    assert result.value == 0.10
    assert result.passed is False


def test_empty_denominator_fails_true_reports_failed_with_reason(tmp_path: Path):
    result = build_metric_result(
        "attribution_completeness",
        numerator=0,
        denominator=0,
        config_path=tmp_path / "nonexistent.yaml",
        empty_denominator_fails=True,
    )
    assert result.value is None
    assert result.passed is False
    assert result.n == 0
    assert "reason" in result.detail


def test_empty_denominator_fails_false_reports_a_vacuous_pass(tmp_path: Path):
    result = build_metric_result(
        "b_seam_mislabel_rate",
        numerator=0,
        denominator=0,
        config_path=tmp_path / "nonexistent.yaml",
        empty_denominator_fails=False,
    )
    assert result.value == 0.0
    assert result.passed is True
    assert result.n == 0


# -- load_records -------------------------------------------------------------


def test_load_records_reads_every_json_file_sorted(tmp_path: Path):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    (records_dir / "b.json").write_text(json.dumps({"claims": [{"id": "b"}]}), encoding="utf-8")
    (records_dir / "a.json").write_text(json.dumps({"claims": [{"id": "a"}]}), encoding="utf-8")

    records = load_records(records_dir)
    assert [r["claims"][0]["id"] for r in records] == ["a", "b"]


def test_load_records_missing_directory_raises(tmp_path: Path):
    with pytest.raises(GateError):
        load_records(tmp_path / "nonexistent")


# -- corpus pin / academic cases / trusted -----------------------------------


def test_resolve_corpus_pin_none_when_evals_dir_absent(tmp_path: Path):
    assert resolve_corpus_pin(tmp_path / "no_such_dir") is None


def test_resolve_corpus_pin_resolves_the_sole_manifest(tmp_path: Path):
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "baseline.json").write_text("{}", encoding="utf-8")
    assert resolve_corpus_pin(pin_dir) == "baseline"


def test_resolve_corpus_pin_none_when_ambiguous(tmp_path: Path):
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "a.json").write_text("{}", encoding="utf-8")
    (pin_dir / "b.json").write_text("{}", encoding="utf-8")
    assert resolve_corpus_pin(pin_dir) is None


def test_academic_cases_present_false_when_dir_absent(tmp_path: Path):
    assert academic_cases_present(tmp_path / "no_such_dir") is False


def test_academic_cases_present_false_when_only_sim_subdir_has_cases(tmp_path: Path):
    cases_dir = tmp_path / "cases"
    sim_dir = cases_dir / "sim"
    sim_dir.mkdir(parents=True)
    (sim_dir / "case-001.json").write_text("{}", encoding="utf-8")
    assert academic_cases_present(cases_dir) is False, (
        "simulated stand-in cases under cases/sim/ must never count as real academic hard cases"
    )


def test_academic_cases_present_true_for_a_direct_case_file(tmp_path: Path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "case-001.json").write_text("{}", encoding="utf-8")
    assert academic_cases_present(cases_dir) is True


def test_resolve_trusted_requires_both_pin_and_cases(tmp_path: Path):
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "baseline.json").write_text("{}", encoding="utf-8")
    cases_dir = tmp_path / "cases"

    # Pin exists, cases do not -> untrusted.
    corpus_pin, trusted = resolve_trusted(evals_dir=pin_dir, cases_dir=cases_dir)
    assert corpus_pin == "baseline"
    assert trusted is False

    # Both exist -> trusted.
    cases_dir.mkdir()
    (cases_dir / "case-001.json").write_text("{}", encoding="utf-8")
    corpus_pin, trusted = resolve_trusted(evals_dir=pin_dir, cases_dir=cases_dir)
    assert trusted is True


def test_resolve_trusted_false_when_pin_absent_even_with_cases(tmp_path: Path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "case-001.json").write_text("{}", encoding="utf-8")
    corpus_pin, trusted = resolve_trusted(evals_dir=tmp_path / "no_pin", cases_dir=cases_dir)
    assert corpus_pin is None
    assert trusted is False


# -- write_report / format_report --------------------------------------------


def test_write_report_writes_to_reports_dir_named_after_the_gate(tmp_path: Path):
    metric = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    report = GateReport(
        gate="attribution-fidelity", corpus_pin=None, trusted=False, metrics=[metric]
    )
    reports_dir = tmp_path / "reports"

    out_path = write_report(report, reports_dir=reports_dir)

    assert out_path == reports_dir / "attribution-fidelity.json"
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["gate"] == "attribution-fidelity"


def test_write_report_is_deterministic_for_a_fixed_report(tmp_path: Path):
    metric = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    report = GateReport(gate="g", corpus_pin=None, trusted=False, metrics=[metric])
    path1 = write_report(report, reports_dir=tmp_path / "run1")
    path2 = write_report(report, reports_dir=tmp_path / "run2")
    assert path1.read_text(encoding="utf-8") == path2.read_text(encoding="utf-8")


def test_format_report_names_metric_and_overall_verdict():
    metric = MetricResult(
        "attribution_completeness",
        0.95,
        1.0,
        "gte",
        False,
        20,
        detail={"failing_claim_ids": ["c-3"]},
    )
    report = GateReport(
        gate="attribution-fidelity", corpus_pin=None, trusted=False, metrics=[metric]
    )
    text = format_report(report)
    assert "attribution_completeness" in text
    assert "FAIL" in text
    assert "c-3" in text
    assert "trusted: False" in text
