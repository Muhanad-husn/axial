"""Inner unit tests for the §7.13 cross-run usage report (issue #266,
plans/source-usage/02-cross-run-usage-report.md's inner-loop list). The
outer acceptance test lives at tests/analysis/test_usage_report.py.
"""

from __future__ import annotations

import json

from axial.answer.usage_report import (
    build_usage_report,
    load_analysis_records,
)


def _record(brief_id: str, *, corpus_pin: str, filters_observed=None, sources=None) -> dict:
    return {
        "brief_id": brief_id,
        "corpus_pin": corpus_pin,
        "source_usage": {
            "filters_observed": filters_observed or [],
            "sources": sources or [],
        },
    }


def _source(source_id: str, usage_ratio) -> dict:
    return {"source_id": source_id, "usage_ratio": usage_ratio}


# -- pin partitioning --------------------------------------------------------


def test_default_pin_is_the_one_the_most_records_share():
    records = [
        _record("a1", corpus_pin="PIN-A"),
        _record("a2", corpus_pin="PIN-A"),
        _record("b1", corpus_pin="PIN-B"),
    ]
    report = build_usage_report(records)
    assert report.pin_id == "PIN-A"
    assert report.included_record_count == 2
    assert report.excluded_pin_counts == {"PIN-B": 1}


def test_explicit_pin_overrides_the_default():
    records = [
        _record("a1", corpus_pin="PIN-A"),
        _record("a2", corpus_pin="PIN-A"),
        _record("b1", corpus_pin="PIN-B"),
    ]
    report = build_usage_report(records, pin="PIN-B")
    assert report.pin_id == "PIN-B"
    assert report.included_record_count == 1
    assert report.excluded_pin_counts == {"PIN-A": 2}


def test_no_records_at_all_yields_a_pinless_empty_report():
    report = build_usage_report([])
    assert report.pin_id is None
    assert report.included_record_count == 0
    assert report.sources == []
    assert report.filters == []


# -- per-source pooling -------------------------------------------------------


def test_per_source_pooling_carries_the_contributing_record_count():
    records = [
        _record("a1", corpus_pin="PIN-A", sources=[_source("tilly", 2.0)]),
        _record("a2", corpus_pin="PIN-A", sources=[_source("tilly", 4.0)]),
    ]
    report = build_usage_report(records)
    assert len(report.sources) == 1
    pooled = report.sources[0]
    assert pooled.source_id == "tilly"
    assert pooled.pooled_usage_ratio == 3.0
    assert pooled.record_count == 2


def test_null_usage_ratio_is_excluded_from_the_pool_not_treated_as_zero():
    records = [
        _record("a1", corpus_pin="PIN-A", sources=[_source("zaum", None)]),
        _record("a2", corpus_pin="PIN-A", sources=[_source("zaum", 2.0)]),
    ]
    report = build_usage_report(records)
    pooled = report.sources[0]
    assert pooled.pooled_usage_ratio == 2.0
    assert pooled.record_count == 1


def test_records_with_empty_sources_contribute_nothing_and_raise_nothing():
    records = [
        _record("r1", corpus_pin="PIN-A", sources=[]),
        _record("r2", corpus_pin="PIN-A", sources=[]),
    ]
    report = build_usage_report(records)
    assert report.sources == []
    assert report.included_record_count == 2


# -- per-(source, filter) pooling --------------------------------------------


def test_per_filter_pooling_only_includes_records_whose_filters_observed_matches():
    world_systems = {"tool": "query_by_tag", "args": {"theory_school": "world-systems"}}
    other = {"tool": "query_by_tag", "args": {"field": "political-science"}}
    records = [
        _record(
            "a1",
            corpus_pin="PIN-A",
            filters_observed=[world_systems],
            sources=[_source("tilly", 3.0)],
        ),
        _record(
            "a2",
            corpus_pin="PIN-A",
            filters_observed=[other],
            sources=[_source("tilly", 1.0)],
        ),
    ]
    report = build_usage_report(records)
    assert len(report.filters) == 2
    by_label = {entry.filter_label: entry for entry in report.filters}
    assert by_label["theory_school:world-systems"].pooled_usage_ratio == 3.0
    assert by_label["theory_school:world-systems"].record_count == 1
    assert by_label["field:political-science"].pooled_usage_ratio == 1.0


def test_query_by_tag_and_query_by_polity_polity_filters_stay_distinct():
    """§7.13: `query_by_tag`'s own `polity` filter key and `query_by_polity`'s
    `polity` arg share a key name but are different queries -- they must not
    collapse into one pooled row."""
    tag_polity = {"tool": "query_by_tag", "args": {"polity": "Freedonia"}}
    query_polity = {"tool": "query_by_polity", "args": {"polity": "Freedonia"}}
    records = [
        _record(
            "a1",
            corpus_pin="PIN-A",
            filters_observed=[tag_polity],
            sources=[_source("tilly", 2.0)],
        ),
        _record(
            "a2",
            corpus_pin="PIN-A",
            filters_observed=[query_polity],
            sources=[_source("tilly", 5.0)],
        ),
    ]
    report = build_usage_report(records)
    assert len(report.filters) == 2
    ratios = sorted(entry.pooled_usage_ratio for entry in report.filters)
    assert ratios == [2.0, 5.0]


# -- ordering / determinism ---------------------------------------------------


def test_sources_are_sorted_heaviest_weighing_first():
    records = [
        _record("a1", corpus_pin="PIN-A", sources=[_source("light", 1.0), _source("heavy", 5.0)]),
    ]
    report = build_usage_report(records)
    assert [entry.source_id for entry in report.sources] == ["heavy", "light"]


def test_build_usage_report_is_deterministic_across_calls():
    records = [
        _record("a1", corpus_pin="PIN-A", sources=[_source("tilly", 2.0), _source("other", 1.0)]),
        _record("a2", corpus_pin="PIN-A", sources=[_source("tilly", 4.0)]),
    ]
    first = build_usage_report(records)
    second = build_usage_report(records)
    assert first == second


# -- loading records off disk -------------------------------------------------


def test_load_analysis_records_missing_dir_yields_no_records_and_no_error(tmp_path):
    records, unreadable = load_analysis_records(tmp_path / "does_not_exist")
    assert records == []
    assert unreadable == 0


def test_load_analysis_records_skips_malformed_json_and_counts_it(tmp_path):
    analyses_dir = tmp_path / "data" / "analyses"
    analyses_dir.mkdir(parents=True)
    (analyses_dir / "good.json").write_text(
        json.dumps(_record("good", corpus_pin="PIN-A")), encoding="utf-8"
    )
    (analyses_dir / "bad.json").write_text("{not valid json", encoding="utf-8")

    records, unreadable = load_analysis_records(analyses_dir)
    assert len(records) == 1
    assert records[0]["brief_id"] == "good"
    assert unreadable == 1


# -- gates nothing -------------------------------------------------------------


def test_the_report_carries_no_threshold_or_flag_field():
    """P0-13/§7.13: the report discloses, it never gates -- there is no
    field anywhere on `UsageReport` that names a threshold or a pass/fail
    verdict."""
    records = [_record("a1", corpus_pin="PIN-A", sources=[_source("tilly", 99.0)])]
    report = build_usage_report(records)
    field_names = set(report.__dataclass_fields__.keys())
    assert not any("threshold" in name or "flag" in name or "pass" in name for name in field_names)
