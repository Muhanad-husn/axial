"""Inner unit tests for `axial brief smoke` (§9.0, issue #491). The outer
acceptance test lives at tests/analysis/test_brief_smoke.py.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from axial.brief.smoke import (
    CHECK_COST_BUDGET,
    CHECK_COVERAGE_MAP,
    CHECK_DISPOSITION,
    CHECK_RECORD_SHAPE,
    CHECK_TOOL_CALLS,
    Budgets,
    BriefSmokeResult,
    CheckResult,
    SmokeSummary,
    _check_budget,
    _check_coverage_map,
    _check_disposition,
    _check_record_shape,
    _check_tool_calls,
    format_smoke_summary,
    resolve_budgets,
    smoke_brief_paths,
)


def _record(**overrides) -> dict:
    record = {
        "brief_id": "DEV90",
        "brief": {"case": "c", "request": "r"},
        "corpus_pin": "baseline",
        "schema_version": "0.1",
        "lens": "political-economy",
        "interrogation": {"disposition": "proceed"},
        "claims": [],
        "counter_position": {"present": False},
        "coverage_map": {"Charles Tilly": {"coverage_band": "dense"}},
        "confidence": {"overall_band": "low", "rationale": "r"},
        "source_usage": {"names_queried": [], "denominator_by_name": {}, "sources": []},
        "trajectory": [],
        "model_by_pass": {"interrogate": "stub"},
        "cost": {"by_pass": {}, "total_usd": None},
    }
    record.update(overrides)
    return record


# -- budgets: unset means SKIPPED, never a vacuous pass ------------------------


def test_an_unset_budget_skips_its_check_rather_than_passing_vacuously():
    result = _check_budget(CHECK_COST_BUDGET, 1_000_000.0, None, "usd")
    assert result.passed is None
    assert "UNMEASURED" in result.detail


def test_a_set_budget_fails_a_run_over_it():
    assert _check_budget(CHECK_COST_BUDGET, 2.0, 1.0, "usd").passed is False


def test_a_set_budget_passes_a_run_exactly_on_it():
    assert _check_budget(CHECK_COST_BUDGET, 1.0, 1.0, "usd").passed is True


def test_an_unobservable_figure_skips_rather_than_failing():
    """A `null` `total_usd` (an unpriced model, §7.14) is nothing to compare,
    so the check is skipped rather than failed for a number that does not
    exist."""
    assert _check_budget(CHECK_COST_BUDGET, None, 1.0, "usd").passed is None


def test_resolve_budgets_reads_an_explicit_null_as_unset(tmp_path):
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        yaml.safe_dump({"smoke": {"max_usd_per_brief": None, "max_seconds_per_brief": None}}),
        encoding="utf-8",
    )
    budgets = resolve_budgets(config)
    assert budgets == Budgets(None, None)
    assert not budgets.any_measured


def test_resolve_budgets_reads_a_missing_block_as_unset(tmp_path):
    config = tmp_path / "pipeline.yaml"
    config.write_text(yaml.safe_dump({"gates": {}}), encoding="utf-8")
    assert resolve_budgets(config) == Budgets(None, None)


def test_resolve_budgets_reads_set_values(tmp_path):
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        yaml.safe_dump({"smoke": {"max_usd_per_brief": 0.5, "max_seconds_per_brief": 180}}),
        encoding="utf-8",
    )
    budgets = resolve_budgets(config)
    assert budgets == Budgets(0.5, 180.0)
    assert budgets.any_measured


def test_the_committed_config_leaves_both_budgets_unmeasured():
    """They are set from the first five real runs, never guessed in advance
    (§9.0). This pins that they are still unset, so a value landing later is
    a deliberate, reviewed change."""
    assert resolve_budgets(Path("config/pipeline.yaml")) == Budgets(None, None)


# -- the mechanical checks ------------------------------------------------------


def test_record_shape_fails_on_a_missing_non_nullable_field(tmp_path):
    record = _record()
    del record["confidence"]
    result = _check_record_shape(record, vault_dir=tmp_path)
    assert result.passed is False
    assert "confidence" in result.detail


def test_record_shape_fails_when_a_grounds_pointer_does_not_resolve(tmp_path):
    (tmp_path / "prose").mkdir(parents=True)
    record = _record(
        claims=[{"kind": "a", "grounds": [{"ref_type": "chunk", "ref_id": "ghost_0_a_001"}]}]
    )
    result = _check_record_shape(record, vault_dir=tmp_path)
    assert result.passed is False
    assert "ghost_0_a_001" in result.detail


def test_record_shape_passes_a_refusal_with_no_claims(tmp_path):
    assert _check_record_shape(_record(claims=[]), vault_dir=tmp_path).passed is True


def test_disposition_must_be_one_of_the_three():
    assert _check_disposition(_record()).passed is True
    bad = _check_disposition(_record(interrogation={"disposition": "maybe"}))
    assert bad.passed is False
    assert bad.name == CHECK_DISPOSITION


def test_an_empty_coverage_map_on_a_proceeding_run_is_loud():
    result = _check_coverage_map(_record(coverage_map={}))
    assert result.passed is False
    assert "#490" in result.detail


def test_a_refusal_skips_the_coverage_check_rather_than_failing_it():
    """A refusal retrieves nothing and legitimately maps nothing; it is a
    COMPLETE run (§7.2), so failing it would make the alarm cry wolf."""
    result = _check_coverage_map(_record(coverage_map={}, interrogation={"disposition": "refuse"}))
    assert result.passed is None
    assert result.name == CHECK_COVERAGE_MAP


def test_a_refused_tool_call_fails_the_no_unhandled_failure_check():
    record = _record(
        trajectory=[
            {"step": 1, "tool": "query_by_tag", "args": {}, "result_ids": [], "result_count": 0}
        ]
    )
    result = _check_tool_calls(record, draw_failed=False, reason="")
    assert result.passed is False
    assert "query_by_tag" in result.detail


def test_a_valid_tool_returning_nothing_is_not_a_failure():
    """An empty result is a real answer (§7.5) -- an honest resolution
    failure, not a broken call."""
    record = _record(
        trajectory=[
            {
                "step": 1,
                "tool": "find_names",
                "args": {"query": "zzqqx"},
                "result_ids": [],
                "result_count": 0,
            }
        ]
    )
    assert _check_tool_calls(record, draw_failed=False, reason="").passed is True


def test_a_raised_draw_fails_the_no_unhandled_failure_check():
    result = _check_tool_calls(_record(), draw_failed=True, reason="boom")
    assert result.passed is False
    assert "boom" in result.detail


# -- the summary's verdict is a gate, not a loop --------------------------------


def _smoke_result(*checks: CheckResult) -> BriefSmokeResult:
    return BriefSmokeResult(
        brief_stem="P3-01",
        brief_id="abc",
        checks=list(checks),
        names_queried=["get_name:Charles Tilly"],
        total_usd=None,
        total_seconds=None,
    )


def test_a_skipped_check_never_drives_the_exit_code():
    summary = SmokeSummary(
        briefs=[_smoke_result(CheckResult(CHECK_COST_BUDGET, None, "skipped"))],
        budgets=Budgets(None, None),
    )
    assert summary.passed is True


def test_any_failed_check_makes_the_summary_fail():
    summary = SmokeSummary(
        briefs=[_smoke_result(CheckResult(CHECK_RECORD_SHAPE, False, "broken"))],
        budgets=Budgets(None, None),
    )
    assert summary.passed is False
    assert summary.failures[0][0] == "P3-01"


def test_the_rendered_summary_says_plainly_that_the_budgets_are_unmeasured():
    summary = SmokeSummary(
        briefs=[_smoke_result(CheckResult(CHECK_TOOL_CALLS, True, "clean"))],
        budgets=Budgets(None, None),
    )
    text = format_smoke_summary(summary)
    assert "UNMEASURED" in text
    assert "smoke: PASS" in text
    # The names a run queried are printed, so a nearest-neighbour
    # substitution (P4-04) is visible by eye rather than asserted on.
    assert "get_name:Charles Tilly" in text


# -- the set itself --------------------------------------------------------------


def test_smoke_brief_paths_is_sorted_and_ignores_the_readme():
    paths = smoke_brief_paths()
    # The set was rebuilt 2026-07-30 (§9.0): five Syria briefs out, five
    # measured-anchor briefs in, P3-04 retained as the one hub anchor
    # §7.13's denominator inspection needs.
    assert [path.stem for path in paths] == [
        "P3-04",
        "S-01",
        "S-02",
        "S-03",
        "S-04",
        "S-05",
    ]
    assert all(path.suffix == ".yaml" for path in paths)
