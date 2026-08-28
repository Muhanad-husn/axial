"""Tests for `axial eval layers` (issue #809): the per-arm comparison read
off persisted sweep directories.

Every fixture sweep directory below is built by constructing the sweep's own
dataclasses and calling `axial.brief.sweep.write_sweep_summary` -- never by
hand-rolling a `summary.json` shape. If the sweep's persisted shape moves,
these fixtures move with it and this reader's tests fail loudly rather than
passing against a schema nothing writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.brief.sweep import (
    FAIL_STATUS,
    OK_STATUS,
    BriefSweepResult,
    DrawOutcome,
    SweepSummary,
    aggregate_brief_cost,
    compute_quorum,
    write_sweep_summary,
)
from axial.gates import GROUNDING_GATE_NAME, GateReport, MetricResult

COMMIT = "abc1234def5678"


def _grounding_report(value: float | None, n: int, passed: bool | None) -> GateReport:
    """One brief's own grounding gate report, exactly the shape
    `_score_brief_gates` persists: one `grounding_support_rate` metric with a
    tri-state `passed`."""
    return GateReport(
        gate=GROUNDING_GATE_NAME,
        corpus_pin="sim-corpus-v1",
        trusted=True,
        metrics=[
            MetricResult(
                metric="grounding_support_rate",
                value=value,
                threshold=0.90,
                comparison="gte",
                passed=passed,
                n=n,
            )
        ],
    )


def _brief_result(
    brief_stem: str,
    *,
    arm: str,
    source_counts: list[int | None],
    grounding: GateReport | None,
) -> BriefSweepResult:
    """One brief's sweep result. `source_counts[i]` is draw `i`'s
    `distinct_sources_cited`; `None` means that draw FAILed and produced no
    record at all."""
    draws = [
        DrawOutcome(
            brief_path=f"config/briefs/smoke/{brief_stem}.yaml",
            brief_stem=brief_stem,
            brief_id=f"{brief_stem}-id",
            draw_index=index,
            status=OK_STATUS if count is not None else FAIL_STATUS,
            reason="" if count is not None else "AnswerError: no answer",
            latency_seconds=12.5 if count is not None else None,
            record_path=None,
            report_path=None,
            arm=arm,
            distinct_sources_cited=count,
        )
        for index, count in enumerate(source_counts)
    ]
    return BriefSweepResult(
        brief_path=f"config/briefs/smoke/{brief_stem}.yaml",
        brief_stem=brief_stem,
        brief_id=f"{brief_stem}-id",
        draws=draws,
        gate_reports={} if grounding is None else {GROUNDING_GATE_NAME: grounding},
        quorum=compute_quorum([]),
        cost=aggregate_brief_cost([]),
    )


def _never_loaded_brief_result(brief_stem: str, *, arm: str) -> BriefSweepResult:
    """A brief whose own file never loaded. The sweep records ONE synthetic
    outcome at `draw_index=-1` for it -- not a draw anyone asked for."""
    return BriefSweepResult(
        brief_path=f"config/briefs/smoke/{brief_stem}.yaml",
        brief_stem=brief_stem,
        brief_id=None,
        draws=[
            DrawOutcome(
                brief_path=f"config/briefs/smoke/{brief_stem}.yaml",
                brief_stem=brief_stem,
                brief_id=None,
                draw_index=-1,
                status=FAIL_STATUS,
                reason="BriefError: unreadable brief",
                latency_seconds=None,
                record_path=None,
                report_path=None,
                arm=arm,
            )
        ],
        gate_reports={},
        quorum=compute_quorum([]),
        cost=aggregate_brief_cost([]),
    )


def _write_arm_dir(
    root: Path,
    arm: str,
    briefs: list[BriefSweepResult],
    *,
    commit: str | None = COMMIT,
) -> Path:
    sweep_dir = root / arm.replace("+", "-")
    outcomes = [outcome for result in briefs for outcome in result.draws]
    ok = sum(1 for outcome in outcomes if outcome.status == OK_STATUS)
    summary = SweepSummary(
        briefs=briefs,
        total_draws=len(outcomes),
        ok_count=ok,
        fail_count=len(outcomes) - ok,
        skip_count=0,
        arm=arm,
        commit=commit,
    )
    write_sweep_summary(summary, sweep_dir)
    return sweep_dir


def _three_arms(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Three arms over the same two briefs, three draws each, one commit."""
    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [
            _brief_result(
                "S-01",
                arm="name",
                source_counts=[5, 6, 8],
                grounding=_grounding_report(0.933, 30, True),
            ),
            _brief_result(
                "S-02",
                arm="name",
                source_counts=[4, 4, 4],
                grounding=_grounding_report(0.870, 23, False),
            ),
        ],
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [
            _brief_result(
                "S-01",
                arm="map",
                source_counts=[4, 4, 5],
                grounding=_grounding_report(0.964, 28, True),
            ),
            _brief_result(
                "S-02",
                arm="map",
                source_counts=[3, 4, 4],
                grounding=_grounding_report(0.910, 22, True),
            ),
        ],
    )
    vocab_dir = _write_arm_dir(
        tmp_path,
        "map+vocab",
        [
            _brief_result(
                "S-01",
                arm="map+vocab",
                source_counts=[5, 5, 6],
                grounding=_grounding_report(0.958, 24, True),
            ),
            _brief_result(
                "S-02",
                arm="map+vocab",
                source_counts=[4, 5, 5],
                grounding=_grounding_report(0.880, 25, False),
            ),
        ],
    )
    return name_dir, map_dir, vocab_dir


def _row(output: str, brief_stem: str, arm: str) -> list[str]:
    """The one table row for `(brief_stem, arm)`, split into its cells. Every
    cell the report prints is space-free, so a row splits on whitespace."""
    matches = [
        line.split() for line in output.splitlines() if line.split()[:2] == [brief_stem, arm]
    ]
    assert len(matches) == 1, f"expected exactly one {brief_stem}/{arm} row, got {matches}"
    return matches[0]


# ---------------------------------------------------------------------------
# The acceptance criterion (issue #809), driven through the CLI.
# ---------------------------------------------------------------------------


def test_eval_layers_reports_grounding_and_sources_per_brief_and_arm(tmp_path, capsys):
    """Given three sweep directories, one per arm, over the same worklist, the
    same draw count and one commit, the report gives per brief and per arm the
    grounding gate result and the count of distinct sources cited, each
    carrying that brief's spread across its own draws."""
    from axial.cli import main

    name_dir, map_dir, vocab_dir = _three_arms(tmp_path)

    exit_code = main(
        [
            "eval",
            "layers",
            "--arm-dir",
            str(name_dir),
            "--arm-dir",
            str(map_dir),
            "--arm-dir",
            str(vocab_dir),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0

    # brief | arm | grounding | rate | gate_draws | sources | range | src_draws
    assert _row(out, "S-01", "name") == ["S-01", "name", "PASS", "0.933", "3", "6.3", "5-8", "3"]
    assert _row(out, "S-01", "map") == ["S-01", "map", "PASS", "0.964", "3", "4.3", "4-5", "3"]
    assert _row(out, "S-01", "map+vocab") == [
        "S-01",
        "map+vocab",
        "PASS",
        "0.958",
        "3",
        "5.3",
        "5-6",
        "3",
    ]
    assert _row(out, "S-02", "name") == ["S-02", "name", "FAIL", "0.870", "3", "4.0", "4-4", "3"]
    assert _row(out, "S-02", "map") == ["S-02", "map", "PASS", "0.910", "3", "3.7", "3-4", "3"]
    assert _row(out, "S-02", "map+vocab") == [
        "S-02",
        "map+vocab",
        "FAIL",
        "0.880",
        "3",
        "4.7",
        "4-5",
        "3",
    ]


def test_eval_layers_refuses_arms_that_do_not_cover_the_same_briefs(tmp_path, capsys):
    """And it refuses, naming the mismatch, if the directories do not cover
    the same briefs."""
    from axial.cli import main

    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [_brief_result("S-01", arm="name", source_counts=[5, 6, 8], grounding=None)],
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [
            _brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None),
            _brief_result("S-03", arm="map", source_counts=[4, 4, 5], grounding=None),
        ],
    )

    exit_code = main(["eval", "layers", "--arm-dir", str(name_dir), "--arm-dir", str(map_dir)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "brief 'S-03' present in arm 'map' and missing from arm 'name'" in captured.err
    assert "S-01" not in captured.out


def test_eval_layers_reports_a_brief_with_no_usable_draw_as_missing(tmp_path, capsys):
    """And a brief missing from one arm is reported as missing for that arm,
    never averaged over or dropped. The brief IS in every arm's worklist -- it
    simply produced no usable draw in one of them."""
    from axial.cli import main

    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [
            _brief_result(
                "S-01",
                arm="name",
                source_counts=[5, 6, 8],
                grounding=_grounding_report(0.933, 30, True),
            )
        ],
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [_brief_result("S-01", arm="map", source_counts=[None, None, None], grounding=None)],
    )

    exit_code = main(["eval", "layers", "--arm-dir", str(name_dir), "--arm-dir", str(map_dir)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _row(out, "S-01", "name") == ["S-01", "name", "PASS", "0.933", "3", "6.3", "5-8", "3"]
    assert _row(out, "S-01", "map") == ["S-01", "map", "missing", "-", "0", "missing", "-", "0"]


def test_a_brief_that_never_loaded_is_missing_and_does_not_move_the_arms_draw_count(tmp_path):
    """A brief whose file never loaded is recorded as ONE synthetic draw at
    index -1, which is not a draw anyone asked for. Counting it would make an
    otherwise-matching arm look like it ran a different number of draws, and
    the whole comparison would be refused over a brief that never ran."""
    from axial.eval.layers import compare_arms, format_layer_comparison

    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [
            _never_loaded_brief_result("S-02", arm="name"),
            _brief_result("S-01", arm="name", source_counts=[5, 6, 8], grounding=None),
        ],
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [
            _brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None),
            _brief_result("S-02", arm="map", source_counts=[4, 4, 5], grounding=None),
        ],
    )

    comparison = compare_arms([name_dir, map_dir])
    report = format_layer_comparison(comparison)

    assert comparison.draws == 3
    assert _row(report, "S-02", "name") == [
        "S-02",
        "name",
        "missing",
        "-",
        "0",
        "missing",
        "-",
        "0",
    ]


# ---------------------------------------------------------------------------
# Reading one arm's directory.
# ---------------------------------------------------------------------------


def test_read_arm_sweep_yields_per_brief_gate_result_and_source_counts(tmp_path):
    from axial.eval.layers import read_arm_sweep

    sweep_dir = _write_arm_dir(
        tmp_path,
        "map",
        [
            _brief_result(
                "S-01",
                arm="map",
                source_counts=[4, 4, 5],
                grounding=_grounding_report(0.964, 28, True),
            )
        ],
    )

    arm = read_arm_sweep(sweep_dir)

    assert arm.arm == "map"
    assert arm.commit == COMMIT
    assert arm.draws == 3
    assert arm.brief_stems == ("S-01",)
    figures = arm.figures["S-01"]
    assert figures.source_counts == (4, 4, 5)
    assert figures.gate_draws == 3
    assert figures.grounding_scored is True
    assert figures.grounding_passed is True
    assert figures.grounding_rate == 0.964
    assert figures.missing is False


def test_read_arm_sweep_refuses_a_directory_holding_no_sweep_summary(tmp_path):
    from axial.eval.layers import LayerComparisonError, read_arm_sweep

    empty = tmp_path / "not-a-sweep"
    empty.mkdir()

    with pytest.raises(LayerComparisonError) as excinfo:
        read_arm_sweep(empty)

    assert "summary.json" in str(excinfo.value)


def test_a_grounding_report_that_is_not_scoreable_is_not_collapsed(tmp_path):
    """The tri-state `passed` (issues #401/#402) survives the read: a
    not-scoreable gate is neither a pass nor a fail here either."""
    from axial.eval.layers import compare_arms, format_layer_comparison

    sweep_dir = _write_arm_dir(
        tmp_path,
        "map",
        [
            _brief_result(
                "S-01",
                arm="map",
                source_counts=[4, 4, 5],
                grounding=_grounding_report(None, 0, None),
            )
        ],
    )

    report = format_layer_comparison(compare_arms([sweep_dir]))

    assert _row(report, "S-01", "map") == [
        "S-01",
        "map",
        "NOT-SCOREABLE",
        "-",
        "3",
        "4.3",
        "4-5",
        "3",
    ]


def test_a_sweep_that_scored_no_gates_reports_no_grounding_figure(tmp_path):
    """`axial brief smoke` runs the sweep with `score_gates=False`, so its
    directories carry records and no gate reports. That is not the same as a
    brief with no usable draw, and does not print as one."""
    from axial.eval.layers import compare_arms, format_layer_comparison

    sweep_dir = _write_arm_dir(
        tmp_path,
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None)],
    )

    report = format_layer_comparison(compare_arms([sweep_dir]))

    assert _row(report, "S-01", "map") == [
        "S-01",
        "map",
        "not-scored",
        "-",
        "3",
        "4.3",
        "4-5",
        "3",
    ]


# ---------------------------------------------------------------------------
# Refusals: the directories have to be comparable.
# ---------------------------------------------------------------------------


def test_compare_arms_refuses_zero_directories():
    from axial.eval.layers import LayerComparisonError, compare_arms

    with pytest.raises(LayerComparisonError) as excinfo:
        compare_arms([])

    assert "--arm-dir" in str(excinfo.value)


def test_compare_arms_refuses_two_directories_recording_the_same_arm(tmp_path):
    """An operator mistake, not a comparison."""
    from axial.eval.layers import LayerComparisonError, compare_arms

    first = _write_arm_dir(
        tmp_path / "first",
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None)],
    )
    second = _write_arm_dir(
        tmp_path / "second",
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None)],
    )

    with pytest.raises(LayerComparisonError) as excinfo:
        compare_arms([first, second])

    message = str(excinfo.value)
    assert "arm 'map' is recorded by two directories" in message
    assert str(first) in message and str(second) in message


def test_compare_arms_names_a_brief_missing_from_the_second_arm(tmp_path):
    """The mirror of the CLI-level refusal above: the brief is in the FIRST
    arm's worklist and absent from the second."""
    from axial.eval.layers import LayerComparisonError, compare_arms

    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [
            _brief_result("S-01", arm="name", source_counts=[4, 4, 5], grounding=None),
            _brief_result("S-04", arm="name", source_counts=[4, 4, 5], grounding=None),
        ],
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None)],
    )

    with pytest.raises(LayerComparisonError) as excinfo:
        compare_arms([name_dir, map_dir])

    assert str(excinfo.value) == "brief 'S-04' present in arm 'name' and missing from arm 'map'"


def test_compare_arms_refuses_different_draw_counts_naming_both(tmp_path):
    from axial.eval.layers import LayerComparisonError, compare_arms

    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [_brief_result("S-01", arm="name", source_counts=[4, 4, 5], grounding=None)],
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4], grounding=None)],
    )

    with pytest.raises(LayerComparisonError) as excinfo:
        compare_arms([name_dir, map_dir])

    assert str(excinfo.value) == "arm 'name' ran 3 draws, arm 'map' ran 2"


def test_compare_arms_refuses_different_commits_naming_both(tmp_path):
    from axial.eval.layers import LayerComparisonError, compare_arms

    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [_brief_result("S-01", arm="name", source_counts=[4, 4, 5], grounding=None)],
        commit="abc1234",
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None)],
        commit="def5678",
    )

    with pytest.raises(LayerComparisonError) as excinfo:
        compare_arms([name_dir, map_dir])

    assert str(excinfo.value) == "arm 'name' built at abc1234, arm 'map' at def5678"


def test_compare_arms_refuses_an_unrecorded_commit_rather_than_matching_two_nones(tmp_path):
    """A `commit` of `None` means git was unavailable when that sweep ran. It
    is not a value two arms can agree on, so two `None`s are never read as a
    match."""
    from axial.eval.layers import LayerComparisonError, compare_arms

    name_dir = _write_arm_dir(
        tmp_path,
        "name",
        [_brief_result("S-01", arm="name", source_counts=[4, 4, 5], grounding=None)],
        commit=None,
    )
    map_dir = _write_arm_dir(
        tmp_path,
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4, 5], grounding=None)],
        commit=None,
    )

    with pytest.raises(LayerComparisonError) as excinfo:
        compare_arms([name_dir, map_dir])

    assert "arm 'name' recorded no commit" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The spread, the plain count, and the arm count.
# ---------------------------------------------------------------------------


def test_the_source_figure_is_computed_only_over_the_draws_that_produced_one(tmp_path):
    """A brief with one FAILed draw is not missing -- it has two usable draws,
    and its figure says so rather than silently averaging over three."""
    from axial.eval.layers import compare_arms, format_layer_comparison

    sweep_dir = _write_arm_dir(
        tmp_path,
        "map",
        [
            _brief_result(
                "S-01",
                arm="map",
                source_counts=[4, None, 7],
                grounding=_grounding_report(0.910, 18, True),
            )
        ],
    )

    report = format_layer_comparison(compare_arms([sweep_dir]))

    assert _row(report, "S-01", "map") == ["S-01", "map", "PASS", "0.910", "2", "5.5", "4-7", "2"]


def test_a_brief_whose_draws_all_agree_still_carries_its_spread(tmp_path):
    """A zero-width spread is a measured spread and prints as one -- omitting
    it would read as "no spread was checked"."""
    from axial.eval.layers import compare_arms, format_layer_comparison

    sweep_dir = _write_arm_dir(
        tmp_path,
        "map",
        [_brief_result("S-01", arm="map", source_counts=[4, 4, 4], grounding=None)],
    )

    report = format_layer_comparison(compare_arms([sweep_dir]))

    assert _row(report, "S-01", "map")[5:] == ["4.0", "4-4", "3"]


def test_the_source_count_carries_no_better_or_worse_marking(tmp_path):
    """The count is a plain count. Nothing in the report calls an arm better,
    worse, a win or a regression -- the interpretation lives in the run log."""
    from axial.eval.layers import compare_arms, format_layer_comparison

    name_dir, map_dir, vocab_dir = _three_arms(tmp_path)

    report = format_layer_comparison(compare_arms([name_dir, map_dir, vocab_dir])).lower()

    for word in ("better", "worse", "best", "wins", "winner", "regression", "improve"):
        assert word not in report


def test_no_row_pools_briefs_together(tmp_path):
    """`eval coherence` refuses a pooled system-wide mean and this holds the
    same line: every row is one (brief, arm) pair, and no row totals or
    averages the briefs."""
    from axial.eval.layers import compare_arms, format_layer_comparison

    name_dir, map_dir, vocab_dir = _three_arms(tmp_path)
    comparison = compare_arms([name_dir, map_dir, vocab_dir])

    rows = comparison.rows()

    assert len(rows) == 6
    assert {figures.brief_stem for figures in rows} == {"S-01", "S-02"}
    report = format_layer_comparison(comparison).lower()
    for word in ("overall", "pooled figure", "all briefs", "total:"):
        assert word not in report


def test_two_arms_are_accepted_as_well_as_three(tmp_path):
    """So the command is usable before the third arm exists."""
    from axial.eval.layers import compare_arms

    name_dir, map_dir, _ = _three_arms(tmp_path)

    comparison = compare_arms([name_dir, map_dir])

    assert [arm.arm for arm in comparison.arms] == ["name", "map"]
    assert len(comparison.rows()) == 4


def test_more_than_three_arms_are_accepted(tmp_path):
    """The arm count is whatever --arm-dir was given, not a fixed three."""
    from axial.eval.layers import compare_arms

    name_dir, map_dir, vocab_dir = _three_arms(tmp_path)
    fourth = _write_arm_dir(
        tmp_path,
        "map+vocab+residue",
        [
            _brief_result("S-01", arm="map+vocab+residue", source_counts=[5, 5, 5], grounding=None),
            _brief_result("S-02", arm="map+vocab+residue", source_counts=[4, 4, 4], grounding=None),
        ],
    )

    comparison = compare_arms([name_dir, map_dir, vocab_dir, fourth])

    assert [arm.arm for arm in comparison.arms] == [
        "name",
        "map",
        "map+vocab",
        "map+vocab+residue",
    ]
    assert len(comparison.rows()) == 8


def test_eval_layers_makes_no_model_call(tmp_path, capsys, monkeypatch):
    """It computes nothing new: no client is ever built, so neither a model
    call nor a second gate-scoring path can hide in here."""
    import axial.cli as cli_mod
    from axial.cli import main

    def _refuse_client(*args, **kwargs):
        raise AssertionError("axial eval layers must never build an LLM client")

    monkeypatch.setattr(cli_mod, "get_client", _refuse_client)
    name_dir, map_dir, vocab_dir = _three_arms(tmp_path)

    exit_code = main(
        [
            "eval",
            "layers",
            "--arm-dir",
            str(name_dir),
            "--arm-dir",
            str(map_dir),
            "--arm-dir",
            str(vocab_dir),
        ]
    )
    capsys.readouterr()

    assert exit_code == 0
