"""Regression coverage for the theory_school not-applicable/unlisted rates
report (issue #288): the operator's promote-or-reconsider signal for the
axis (specs/PRODUCT.md Appendix E) -- per source, the count and percentage
of chunks tagged `not-applicable` and `unlisted`, plus (for `unlisted` only)
the distinct proposed school names the candidates log recorded for that
source. This report is read-only over already-persisted output (the tag
checkpoint `<tags_dir>/<source_id>.jsonl` and the shared candidates log
`<tags_dir>/theory_school_candidates.jsonl`) -- it never calls the model,
never re-tags anything, and must never raise: a torn checkpoint or a
malformed candidates-log line is a stderr diagnostic, not a crash (the
issue's acceptance bar: "the summary never blocks or fails the run").

Mirrors `test_tag_theory_school_unlisted.py`'s inner-loop style: real
`tag.py` functions exercised directly against small fixtures written under
`tmp_path`, never the CLI-subprocess acceptance style.
"""

from __future__ import annotations

import json

from axial.tag import (
    THEORY_SCHOOL_CANDIDATES_FILENAME,
    TheorySchoolSourceRate,
    tags_checkpoint_path,
    theory_school_rates_for_source,
    theory_school_rates_report,
)


def _write_checkpoint(tags_dir, source_id, records):
    tags_dir.mkdir(parents=True, exist_ok=True)
    path = tags_checkpoint_path(source_id, tags_dir)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def _tagged(chunk_id, primary):
    return {"chunk_id": chunk_id, "theory_school": {"primary": primary}}


def _write_candidates(tags_dir, records):
    tags_dir.mkdir(parents=True, exist_ok=True)
    path = tags_dir / THEORY_SCHOOL_CANDIDATES_FILENAME
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


# --- per-source counts and percentages --------------------------------------


def test_rate_counts_not_applicable_and_unlisted_against_total_tagged_chunks(tmp_path):
    tags_dir = tmp_path / "tags"
    _write_checkpoint(
        tags_dir,
        "src-1",
        [
            _tagged("c1", "bellicist"),
            _tagged("c2", "not-applicable"),
            _tagged("c3", "not-applicable"),
            _tagged("c4", "unlisted"),
        ],
    )

    rate = theory_school_rates_for_source("src-1", tags_dir)

    assert rate == TheorySchoolSourceRate(
        source_id="src-1",
        total=4,
        not_applicable_count=2,
        not_applicable_pct=50.0,
        unlisted_count=1,
        unlisted_pct=25.0,
        unlisted_schools=[],
    )


def test_quarantined_and_axis_less_records_are_excluded_from_the_denominator(tmp_path):
    tags_dir = tmp_path / "tags"
    _write_checkpoint(
        tags_dir,
        "src-1",
        [
            _tagged("c1", "bellicist"),
            {"chunk_id": "c2", "quarantine_reason": "content_filter"},
            {"chunk_id": "c3", "role_in_argument": "role:claim"},  # no theory_school key
        ],
    )

    rate = theory_school_rates_for_source("src-1", tags_dir)

    assert rate.total == 1
    assert rate.not_applicable_count == 0
    assert rate.unlisted_count == 0


def test_source_with_no_checkpoint_file_returns_none(tmp_path):
    tags_dir = tmp_path / "tags"
    tags_dir.mkdir()

    assert theory_school_rates_for_source("never-tagged", tags_dir) is None


def test_source_whose_records_are_all_quarantined_returns_none(tmp_path):
    tags_dir = tmp_path / "tags"
    _write_checkpoint(
        tags_dir,
        "src-1",
        [{"chunk_id": "c1", "quarantine_reason": "malformed_json"}],
    )

    assert theory_school_rates_for_source("src-1", tags_dir) is None


# --- unlisted proposed schools from the candidates log ----------------------


def test_unlisted_schools_come_from_the_candidates_log_filtered_by_source_deduped_sorted(
    tmp_path,
):
    tags_dir = tmp_path / "tags"
    _write_checkpoint(tags_dir, "src-1", [_tagged("c1", "unlisted")])
    _write_candidates(
        tags_dir,
        [
            {
                "source_id": "src-1",
                "chunk_id": "c1",
                "section": "s",
                "proposed_value": "pluralist",
                "position": "primary",
            },
            {
                "source_id": "src-1",
                "chunk_id": "c2",
                "section": "s",
                "proposed_value": "corporatist",
                "position": "primary",
            },
            {
                "source_id": "src-1",
                "chunk_id": "c3",
                "section": "s",
                "proposed_value": "pluralist",
                "position": "primary",
            },
            # A different source's candidate must never leak into src-1's report.
            {
                "source_id": "src-2",
                "chunk_id": "c9",
                "section": "s",
                "proposed_value": "other",
                "position": "primary",
            },
        ],
    )

    # Read through the whole-corpus report, which loads the candidates log
    # once and groups it by source_id -- the path a real run actually uses.
    report = theory_school_rates_report(["src-1", "src-2"], tags_dir=tags_dir)
    by_source = {rate.source_id: rate for rate in report}

    assert by_source["src-1"].unlisted_schools == ["corporatist", "pluralist"]


def test_a_blank_proposed_value_is_excluded_from_unlisted_schools(tmp_path):
    # Seen in the real corpus candidates log: a record whose proposed_value
    # is an empty string. It names nothing an operator could promote, so it
    # must never show up in the promotable-candidates list.
    tags_dir = tmp_path / "tags"
    _write_checkpoint(tags_dir, "src-1", [_tagged("c1", "unlisted")])
    _write_candidates(
        tags_dir,
        [
            {
                "source_id": "src-1",
                "chunk_id": "c1",
                "section": "s",
                "proposed_value": "",
                "position": "secondary",
            },
            {
                "source_id": "src-1",
                "chunk_id": "c2",
                "section": "s",
                "proposed_value": "pluralist",
                "position": "primary",
            },
        ],
    )

    rate = theory_school_rates_for_source("src-1", tags_dir)

    assert rate.unlisted_schools == ["pluralist"]


# --- the whole-corpus report --------------------------------------------------


def test_report_sorts_by_source_id_and_skips_sources_with_no_data(tmp_path):
    tags_dir = tmp_path / "tags"
    _write_checkpoint(tags_dir, "zzz-last", [_tagged("c1", "bellicist")])
    _write_checkpoint(tags_dir, "aaa-first", [_tagged("c1", "not-applicable")])

    report = theory_school_rates_report(["zzz-last", "aaa-first", "no-data-src"], tags_dir=tags_dir)

    assert [rate.source_id for rate in report] == ["aaa-first", "zzz-last"]


def test_report_deduplicates_repeated_source_ids(tmp_path):
    tags_dir = tmp_path / "tags"
    _write_checkpoint(tags_dir, "src-1", [_tagged("c1", "bellicist")])

    report = theory_school_rates_report(["src-1", "src-1"], tags_dir=tags_dir)

    assert len(report) == 1


# --- never blocks or fails the run --------------------------------------------


def test_torn_checkpoint_line_is_diagnosed_and_excluded_not_raised(tmp_path, capsys):
    tags_dir = tmp_path / "tags"
    tags_dir.mkdir()
    path = tags_checkpoint_path("src-1", tags_dir)
    # A torn NON-last line -- genuine corruption, `load_tag_checkpoint` raises
    # `TagCheckpointCorruptError` for this shape; the rates report must catch
    # it, print a diagnostic, and report no row for this source, not raise.
    path.write_text(
        json.dumps(_tagged("c1", "bellicist"))[:10]
        + "\n"
        + json.dumps(_tagged("c2", "unlisted"))
        + "\n",
        encoding="utf-8",
    )

    rate = theory_school_rates_for_source("src-1", tags_dir)

    assert rate is None
    assert "src-1" in capsys.readouterr().err


def test_malformed_candidates_log_line_is_skipped_not_raised(tmp_path, capsys):
    tags_dir = tmp_path / "tags"
    _write_checkpoint(tags_dir, "src-1", [_tagged("c1", "unlisted")])
    path = tags_dir / THEORY_SCHOOL_CANDIDATES_FILENAME
    path.write_text(
        "not-json-at-all\n"
        + json.dumps(
            {
                "source_id": "src-1",
                "chunk_id": "c1",
                "section": "s",
                "proposed_value": "pluralist",
                "position": "primary",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = theory_school_rates_report(["src-1"], tags_dir=tags_dir)

    assert report[0].unlisted_schools == ["pluralist"]
    assert capsys.readouterr().err  # the malformed line was diagnosed, not silently dropped


def test_report_never_raises_when_tags_dir_does_not_exist(tmp_path):
    missing_dir = tmp_path / "does-not-exist"

    assert theory_school_rates_report(["src-1"], tags_dir=missing_dir) == []
