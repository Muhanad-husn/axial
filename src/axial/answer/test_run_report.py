"""Inner unit tests for the §7.15 run report (issue #491). The outer
acceptance test lives at tests/analysis/test_run_report.py.
"""

from __future__ import annotations

import time

import pytest
import yaml

from axial.answer.run_report import (
    PassClock,
    _claim_mix,
    _concentration,
    _cost_figures,
    _cross_source_rate,
    _evidence_figures,
    _grounds_per_claim,
    _latency,
    _retrieval_precision,
    _trajectory_figures,
    build_run_report,
    format_run_report,
    persist_run_report,
)

TILLY = "Charles Tilly"


def _claim(kind: str, chunk_ids: list[str], names: list[str] | None = None) -> dict:
    return {
        "claim_id": f"c-{kind}-{'-'.join(chunk_ids)}",
        "text": "Some claim.",
        "kind": kind,
        "grounds": [{"ref_type": "chunk", "ref_id": cid} for cid in chunk_ids],
        "confidence": "medium",
        "names_touched": names or [],
    }


def _write_chunk(prose_dir, chunk_id):
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "A Section",
        "chunk_text": f"{chunk_id} text.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "frame_version": "0.1",
        "answers": {"claim": "A claim.", "position_of": "the author"},
    }
    (prose_dir / f"{chunk_id}.md").write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n", encoding="utf-8"
    )


# -- PassClock -----------------------------------------------------------------


def test_pass_clock_accumulates_rather_than_overwriting_a_repeated_pass():
    clock = PassClock()
    with clock.time("retrieve"):
        time.sleep(0.01)
    with clock.time("retrieve"):
        time.sleep(0.01)
    assert clock.seconds_by_pass()["retrieve"] >= 0.02


def test_pass_clock_records_a_pass_whose_body_raised():
    clock = PassClock()
    with pytest.raises(ValueError):
        with clock.time("synthesize"):
            raise ValueError("boom")
    assert "synthesize" in clock.seconds_by_pass()


# -- latency ---------------------------------------------------------------------


def test_latency_names_every_pass_model_by_pass_names_and_totals_their_sum():
    latency = _latency({"interrogate": 1.0, "retrieve": 2.0}, {"interrogate": "m", "retrieve": "m"})
    assert set(latency["by_pass"]) == {"interrogate", "retrieve"}
    assert latency["total"] == pytest.approx(3.0)


def test_a_named_pass_that_was_never_timed_reports_zero_rather_than_being_dropped():
    latency = _latency({}, {"interrogate": "m"})
    assert latency["by_pass"] == {"interrogate": 0.0}


def test_a_timed_pass_the_run_did_not_name_is_left_out():
    """`counter_position_generate` is timed unconditionally but only NAMED
    when the contested path actually fired -- an uncontested run must not
    report a pass it never made."""
    latency = _latency({"interrogate": 1.0, "counter_position_generate": 0.5}, {"interrogate": "m"})
    assert latency["by_pass"] == {"interrogate": 1.0}
    assert latency["total"] == pytest.approx(1.0)


# -- trajectory figures ----------------------------------------------------------


def _entry(step, tool, ids):
    return {"step": step, "tool": tool, "args": {}, "result_ids": ids, "result_count": len(ids)}


def test_a_turn_re_fetching_a_seen_id_counts_as_adding_no_new_evidence():
    figures = _trajectory_figures(
        [
            _entry(1, "get_chunk", ["a"]),
            _entry(2, "get_chunk", ["a"]),
            _entry(3, "get_chunk", ["b"]),
        ]
    )
    assert figures["evidence_tool_calls"] == 3
    assert figures["turns_without_new_evidence"] == 1


def test_a_resolution_call_is_not_counted_as_a_wasted_turn():
    """`find_names` returns canonical names, never evidence, so it can never
    add an id -- counting it as a wasted turn would misread the signal."""
    figures = _trajectory_figures([_entry(1, "find_names", ["Charles Tilly"])])
    assert figures["evidence_tool_calls"] == 0
    assert figures["turns_without_new_evidence"] == 0


def test_a_call_naming_no_registered_tool_is_counted_as_refused():
    figures = _trajectory_figures([_entry(1, "query_by_tag", []), _entry(2, "get_chunk", ["a"])])
    assert figures["rejected_tool_calls"] == 1
    assert figures["empty_result_calls"] == 1
    assert figures["tool_calls"] == 2


# -- the headline: cross-source rate ---------------------------------------------


def test_cross_source_rate_is_zero_when_every_b_claim_sits_in_one_book():
    claims = [_claim("b", ["tilly_0_a_001", "tilly_0_a_002"]), _claim("a", ["tilly_0_a_001"])]
    result = _cross_source_rate(claims, vault_dir=None)
    assert result["value"] == 0.0
    assert result["denominator"] == 1


def test_cross_source_rate_is_one_when_a_b_claim_spans_two_books():
    claims = [_claim("b", ["tilly_0_a_001", "bayat_0_a_001"])]
    assert _cross_source_rate(claims, vault_dir=None)["value"] == 1.0


def test_cross_source_rate_is_not_scored_when_there_is_no_b_claim():
    result = _cross_source_rate([_claim("a", ["tilly_0_a_001"])], vault_dir=None)
    assert result["value"] is None
    assert result["reason"]


# -- concentration / mix / grounds -------------------------------------------------


def test_concentration_reads_one_for_a_single_source_run():
    assert _concentration([1.0]) == {"top_1_share": 1.0, "hhi": 1.0}


def test_concentration_hhi_falls_as_sources_spread():
    spread = _concentration([0.25, 0.25, 0.25, 0.25])
    assert spread["top_1_share"] == 0.25
    assert spread["hhi"] == pytest.approx(0.25)


def test_concentration_is_null_with_no_sources_rather_than_zero():
    assert _concentration([]) == {"top_1_share": None, "hhi": None}


def test_claim_mix_counts_and_shares_every_kind():
    mix = _claim_mix([_claim("a", ["x_0_a_001"]), _claim("b", ["x_0_a_001"])])
    assert mix["counts"] == {"a": 1, "b": 1, "c": 0}
    assert mix["shares"]["a"] == pytest.approx(0.5)


def test_grounds_per_claim_reports_mean_median_and_the_two_or_more_share():
    claims = [_claim("a", ["x_0_a_001"]), _claim("b", ["x_0_a_001", "y_0_a_001"])]
    result = _grounds_per_claim(claims)
    assert result["mean"] == pytest.approx(1.5)
    assert result["median"] == pytest.approx(1.5)
    assert result["share_with_two_or_more"] == pytest.approx(0.5)


def test_retrieval_precision_divides_cited_by_retrieved():
    trajectory = [_entry(1, "get_chunk", ["a"]), _entry(2, "get_chunk", ["b"])]
    result = _retrieval_precision({"a"}, trajectory)
    assert result["value"] == pytest.approx(0.5)
    assert result["retrieved_note_count"] == 2


def test_retrieval_precision_is_not_scored_when_nothing_was_retrieved():
    result = _retrieval_precision(set(), [])
    assert result["value"] is None
    assert result["reason"]


def test_cost_figures_carry_a_null_total_usd_through_rather_than_zeroing_it():
    figures = _cost_figures(
        {"by_pass": {"interrogate": {"total_tokens": 12, "usd": None}}, "total_usd": None}
    )
    assert figures["total_tokens"] == 12
    assert figures["total_usd"] is None


# -- evidence: assembled vs composed (§7.3, issue #545) ------------------------


def test_evidence_figures_report_the_drop_and_its_share():
    figures = _evidence_figures({"assembled_count": 506, "composed_count": 146})

    assert figures["assembled_count"] == 506
    assert figures["composed_count"] == 146
    assert figures["dropped_count"] == 360
    assert figures["composed_share"] == pytest.approx(146 / 506)


def test_evidence_figures_report_no_share_rather_than_dividing_by_zero():
    """Nothing was assembled -- a `refuse` disposition, or a run whose
    retrieval reached no note -- so `composed_share` is `None`, not a
    ZeroDivisionError and not a fabricated 0 or 1."""
    figures = _evidence_figures({"assembled_count": 0, "composed_count": 0})

    assert figures["dropped_count"] == 0
    assert figures["composed_share"] is None


def test_evidence_figures_default_cleanly_on_an_absent_field():
    """A record from before issue #545 (or a caller's minimal test double)
    carries no `evidence` key at all -- reads as 0/0, never a crash."""
    figures = _evidence_figures({})

    assert figures == {
        "assembled_count": 0,
        "composed_count": 0,
        "dropped_count": 0,
        "composed_share": None,
    }


# -- accuracy: the four are separate ---------------------------------------------


def _minimal_record(claims, trajectory=None) -> dict:
    return {
        "brief_id": "DEV90",
        "corpus_pin": "baseline",
        "interrogation": {"disposition": "proceed"},
        "claims": claims,
        "counter_position": {"present": False},
        "coverage_map": {},
        "confidence": {"overall_band": "low", "rationale": "r"},
        "trajectory": trajectory or [],
        "model_by_pass": {"interrogate": "stub"},
        "cost": {"by_pass": {}, "total_usd": None},
        "source_usage": {"names_queried": [], "denominator_by_name": {}, "sources": []},
    }


def test_the_report_never_carries_a_single_accuracy_number(tmp_path):
    """§10.0/D8: accuracy decomposes into four, each reported on its own and
    never summed, averaged or headlined as one figure."""
    _write_chunk(tmp_path / "prose", "tilly_0_a_001")
    report = build_run_report(_minimal_record([_claim("a", ["tilly_0_a_001"])]), vault_dir=tmp_path)
    accuracy = report["accuracy"]
    assert set(accuracy) == {
        "attribution_completeness",
        "retrieval_hit",
        "grounding_support_rate",
        "instant_dismissal_violations",
    }
    assert "accuracy_score" not in report
    assert not any(key == "accuracy" for key in report["response_quality"])


def test_attribution_completeness_is_not_scored_on_a_run_with_no_claim(tmp_path):
    report = build_run_report(_minimal_record([]), vault_dir=tmp_path)
    entry = report["accuracy"]["attribution_completeness"]
    assert entry["value"] is None
    assert entry["reason"]


def test_a_claim_whose_grounds_do_not_resolve_fails_attribution_completeness(tmp_path):
    (tmp_path / "prose").mkdir(parents=True)
    report = build_run_report(_minimal_record([_claim("a", ["ghost_0_a_001"])]), vault_dir=tmp_path)
    entry = report["accuracy"]["attribution_completeness"]
    assert entry["value"] == 0.0
    assert entry["failing_claim_ids"]


# -- persistence + rendering -------------------------------------------------------


def test_persist_run_report_is_keyed_on_brief_id_and_overwrites(tmp_path):
    runs_dir = tmp_path / "runs"
    first = persist_run_report("DEV90", {"brief_id": "DEV90", "n": 1}, runs_dir=runs_dir)
    second = persist_run_report("DEV90", {"brief_id": "DEV90", "n": 2}, runs_dir=runs_dir)
    assert first == second
    assert '"n": 2' in second.read_text(encoding="utf-8")


def test_format_run_report_names_the_headline_and_the_unscored_reasons(tmp_path):
    _write_chunk(tmp_path / "prose", "tilly_0_a_001")
    report = build_run_report(
        _minimal_record([_claim("b", ["tilly_0_a_001"])]),
        latency_by_pass={"interrogate": 1.0},
        vault_dir=tmp_path,
    )
    text = format_run_report(report)
    assert "cross-source rate (headline, D9)" in text
    assert "grounding_support_rate: n/a" in text
    assert "not scored" in text


def test_the_report_surfaces_the_records_own_assembled_and_composed_counts(tmp_path):
    """Issue #545: the record's `evidence` field reaches the report
    unchanged, with the derived drop/share alongside it, and a rendered
    line so the next run is comparable to these seven at a glance."""
    record = {**_minimal_record([]), "evidence": {"assembled_count": 21, "composed_count": 19}}

    report = build_run_report(record, vault_dir=tmp_path)

    assert report["operational"]["evidence"] == {
        "assembled_count": 21,
        "composed_count": 19,
        "dropped_count": 2,
        "composed_share": pytest.approx(19 / 21),
    }
    assert "evidence: assembled=21 composed=19" in format_run_report(report)
