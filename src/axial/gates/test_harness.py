"""Inner unit tests for the common rung-3 gate harness (issue #262,
specs/PHASE-B.md §10). Co-located under src/axial/gates/ per the repo's
existing test layout (mirrors src/axial/validators/test_attribution.py,
src/axial/eval/test_corpus_pin_unit.py).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from axial.gates.harness import (
    GateError,
    GateReport,
    MetricResult,
    build_metric_result,
    comparison_for,
    compare,
    format_report,
    load_records,
    not_scoreable_metric,
    resolve_corpus_pin,
    resolve_threshold,
    resolve_trusted,
    verdict_text,
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


# -- `reported`: a number disclosed but never gated (issue #550) -------------


def test_reported_is_empty_by_default_and_omitted_from_json():
    metric = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    report = GateReport(gate="g", corpus_pin=None, trusted=False, metrics=[metric])
    assert report.reported == {}
    assert "reported" not in report.to_json()


def test_reported_entries_never_affect_gate_report_passed():
    """A `reported` value can be anything -- even one a hypothetical future
    threshold would call bad -- and `passed` must still ignore it entirely:
    only `metrics` gates release."""
    failing_looking_value = {"value": 0.0, "numerator": 0, "denominator": 10}
    metric = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    report = GateReport(
        gate="g",
        corpus_pin=None,
        trusted=False,
        metrics=[metric],
        reported={"some_metric": failing_looking_value},
    )
    assert report.passed is True
    assert report.to_json()["reported"] == {"some_metric": failing_looking_value}


def test_format_report_renders_reported_entries_distinctly_as_not_gated():
    metric = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    report = GateReport(
        gate="g",
        corpus_pin=None,
        trusted=False,
        metrics=[metric],
        reported={"some_metric": {"value": 0.25, "numerator": 1, "denominator": 4}},
    )
    text = format_report(report)
    assert "not gated" in text
    assert "some_metric" in text
    assert "0.2500" in text


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


# -- compare: float-representation tolerance at an exact boundary (#402) -----


def test_compare_lte_survives_float_representation_error_at_the_boundary():
    """Issue #402: `1.0 - 0.85` is mathematically exactly 0.15 but lands one
    float ULP above it (`0.15000000000000002`, the exact value a real
    calibration report computed) -- a raw `<=` would report this boundary
    value as failing. `0.150..0.600` was the observed range across the
    whole benchmark run, so this boundary is not a rare edge case."""
    value = 1.0 - 0.85
    assert value != 0.15  # the float-representation artifact this guards against
    assert compare(value, 0.15, "lte") is True


def test_compare_gte_survives_float_representation_error_at_the_boundary():
    """The mirror case for a "gte" metric: a value one ULP BELOW its
    threshold, purely from float representation, must still count as
    meeting it."""
    value = math.nextafter(0.9, 0.0)
    assert value != 0.9
    assert compare(value, 0.9, "gte") is True


def test_compare_still_fails_clearly_outside_tolerance():
    """The tolerance absorbs float-representation error only -- it must
    never widen into a real, measurable miss."""
    assert compare(0.20, 0.15, "lte") is False
    assert compare(0.80, 0.90, "gte") is False


# -- not_scoreable_metric / tri-state passed (#401/#402) ----------------------


def test_not_scoreable_metric_has_null_value_and_passed():
    result = not_scoreable_metric(
        "steelman_quality", reason="no present-with-grounds counter-position to judge"
    )
    assert result.value is None
    assert result.passed is None
    assert result.n == 0
    assert result.detail["reason"] == "no present-with-grounds counter-position to judge"


def test_gate_report_passed_is_none_when_any_metric_not_scoreable_and_none_failed():
    """A not-scoreable metric must not collapse into either a pass or a
    fail one level up -- the whole point of issues #401/#402."""
    passing = MetricResult("m1", 1.0, 1.0, "gte", True, 1)
    not_scoreable = not_scoreable_metric("steelman_quality", reason="nothing to judge")
    report = GateReport(gate="g", corpus_pin=None, trusted=False, metrics=[passing, not_scoreable])
    assert report.passed is None


def test_gate_report_passed_is_false_when_a_real_failure_coexists_with_not_scoreable():
    """A genuine failure is never hidden behind a co-occurring not-scoreable
    metric."""
    failing = MetricResult("m1", 0.0, 1.0, "gte", False, 1)
    not_scoreable = not_scoreable_metric("steelman_quality", reason="nothing to judge")
    report = GateReport(gate="g", corpus_pin=None, trusted=False, metrics=[failing, not_scoreable])
    assert report.passed is False


def test_verdict_text_renders_the_three_states_distinctly():
    assert verdict_text(True) == "PASS"
    assert verdict_text(False) == "FAIL"
    assert verdict_text(None) == "NOT-SCOREABLE"


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


def test_resolve_trusted_true_from_the_pin_alone(tmp_path: Path):
    """Issue #380, PHASE-B §9.2: the five rung-3 gates are corpus-anchored,
    so an unambiguous pin is the whole condition. Academic-authored cases
    were removed as a conjunct when #250/#295 closed not-planned -- keeping
    them would leave every gate untrusted forever."""
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "baseline.json").write_text("{}", encoding="utf-8")

    corpus_pin, trusted = resolve_trusted(evals_dir=pin_dir)
    assert corpus_pin == "baseline"
    assert trusted is True


def test_resolve_trusted_ignores_the_cases_directory_entirely(tmp_path: Path, monkeypatch):
    """§9.2's stated observable: with a resolved pin and ZERO files under
    `evals/cases/`, a gate reports `trusted: true`. Guards against the
    conjunct being reintroduced under another name."""
    pin_dir = tmp_path / "corpus_pin"
    pin_dir.mkdir()
    (pin_dir / "baseline.json").write_text("{}", encoding="utf-8")
    empty_cases = tmp_path / "cases"
    empty_cases.mkdir()
    monkeypatch.chdir(tmp_path)

    _, trusted = resolve_trusted(evals_dir=pin_dir)
    assert trusted is True, "an empty evals/cases/ must not make a corpus-anchored gate untrusted"


def test_resolve_trusted_false_when_pin_absent(tmp_path: Path):
    corpus_pin, trusted = resolve_trusted(evals_dir=tmp_path / "no_pin")
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
