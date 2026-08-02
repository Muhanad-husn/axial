"""Unit tests for `axial.ask.history` (issue #536): finding and reopening a
past `axial ask` turn by what it asked, never by its `brief_id`."""

from __future__ import annotations

import json
import time
from pathlib import Path

from axial.ask.history import list_past_turns, load_turn


def _write_record(
    analyses_dir: Path, brief_id: str, *, case: str, question: str, disposition: str
) -> None:
    analyses_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "brief_id": brief_id,
        "brief": {"case": case, "request": question, "lens": None},
        "interrogation": {"disposition": disposition},
        "claims": [],
    }
    (analyses_dir / f"{brief_id}.json").write_text(json.dumps(record), encoding="utf-8")


def _write_report(runs_dir: Path, brief_id: str, *, cross_source_value) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "response_quality": {
            "cross_source_rate": {"value": cross_source_value, "numerator": 1, "denominator": 1}
        }
    }
    (runs_dir / f"{brief_id}.json").write_text(json.dumps(report), encoding="utf-8")


def test_an_empty_analyses_dir_lists_no_turns(tmp_path):
    turns = list_past_turns(analyses_dir=tmp_path / "analyses", runs_dir=tmp_path / "runs")
    assert turns == []


def test_a_question_asked_last_week_is_findable_by_case_and_question_text(tmp_path):
    analyses_dir = tmp_path / "analyses"
    runs_dir = tmp_path / "runs"
    _write_record(
        analyses_dir, "brf_1", case="Syria", question="Who led the uprising?", disposition="proceed"
    )
    _write_report(runs_dir, "brf_1", cross_source_value=0.5)

    turns = list_past_turns(analyses_dir=analyses_dir, runs_dir=runs_dir)

    assert len(turns) == 1
    assert turns[0].case == "Syria"
    assert turns[0].question == "Who led the uprising?"
    assert turns[0].disposition == "proceeded"
    assert turns[0].cross_source_rate == 0.5


def test_disposition_words_are_plain_not_the_raw_vocabulary(tmp_path):
    analyses_dir = tmp_path / "analyses"
    runs_dir = tmp_path / "runs"
    _write_record(
        analyses_dir, "brf_bounded", case="Iraq", question="Q1", disposition="proceed_bounded"
    )
    _write_record(analyses_dir, "brf_refused", case="Iraq", question="Q2", disposition="refuse")

    turns = {
        turn.brief_id: turn
        for turn in list_past_turns(analyses_dir=analyses_dir, runs_dir=runs_dir)
    }

    assert turns["brf_bounded"].disposition == "proceeded, bounded"
    assert turns["brf_refused"].disposition == "refused"


def test_most_recently_written_record_lists_first(tmp_path):
    analyses_dir = tmp_path / "analyses"
    runs_dir = tmp_path / "runs"
    _write_record(analyses_dir, "brf_old", case="Syria", question="older", disposition="proceed")
    time.sleep(0.02)
    _write_record(analyses_dir, "brf_new", case="Syria", question="newer", disposition="proceed")

    turns = list_past_turns(analyses_dir=analyses_dir, runs_dir=runs_dir)

    assert [turn.brief_id for turn in turns] == ["brf_new", "brf_old"]


def test_a_record_with_no_run_report_still_lists_with_the_headline_unmeasured(tmp_path):
    analyses_dir = tmp_path / "analyses"
    runs_dir = tmp_path / "runs"
    _write_record(analyses_dir, "brf_1", case="Syria", question="Q", disposition="proceed")
    # No matching runs_dir/brf_1.json written at all.

    turns = list_past_turns(analyses_dir=analyses_dir, runs_dir=runs_dir)

    assert len(turns) == 1
    assert turns[0].cross_source_rate is None


def test_reopening_needs_only_the_brief_id_list_past_turns_gave_it(tmp_path):
    analyses_dir = tmp_path / "analyses"
    runs_dir = tmp_path / "runs"
    _write_record(
        analyses_dir, "brf_1", case="Syria", question="Who led the uprising?", disposition="proceed"
    )
    _write_report(runs_dir, "brf_1", cross_source_value=1.0)

    turns = list_past_turns(analyses_dir=analyses_dir, runs_dir=runs_dir)
    loaded = load_turn(turns[0].brief_id, analyses_dir=analyses_dir, runs_dir=runs_dir)

    assert loaded is not None
    record, report = loaded
    assert record["brief"]["request"] == "Who led the uprising?"
    assert record["brief"]["case"] == "Syria"
    assert report["response_quality"]["cross_source_rate"]["value"] == 1.0


def test_reopening_an_unknown_brief_id_returns_none(tmp_path):
    loaded = load_turn(
        "no-such-brief", analyses_dir=tmp_path / "analyses", runs_dir=tmp_path / "runs"
    )
    assert loaded is None


def test_a_malformed_record_file_is_skipped_not_a_crash(tmp_path):
    analyses_dir = tmp_path / "analyses"
    analyses_dir.mkdir(parents=True)
    (analyses_dir / "broken.json").write_text("not json", encoding="utf-8")

    turns = list_past_turns(analyses_dir=analyses_dir, runs_dir=tmp_path / "runs")

    assert turns == []
