"""Inner unit tests for the axial.runlog seam (issue #270 slice 01;
plans/run-logging/01-run-logging-seam.md's inner-loop list). Each test
drives `run_context`/`RunHandle.record` directly, independent of any
specific pass -- the pass wiring (axial.cli._extract) is exercised by the
outer acceptance test at tests/test_runlog.py."""

from __future__ import annotations

import json
import logging

import pytest

from axial.runlog import LOGS_ROOT_ENV_VAR, run_context

FIXED_TS = "20260721T000000Z"


def test_run_context_falls_back_to_the_env_var_when_root_is_not_given(tmp_path, monkeypatch):
    """`AXIAL_LOGS_ROOT` is the resolution seam `run_context` reads when a
    caller passes no `root` -- the same explicit-argument -> env var ->
    default order `axial.llm`'s own `AXIAL_SECRETS_PATH`/`_secrets_path()`
    already uses (issue #23, requirement 4). This is what lets both
    conftests redirect a subprocess `axial` invocation's default run-log
    root, not only an in-process one, with a single `monkeypatch.setenv`."""
    monkeypatch.setenv(LOGS_ROOT_ENV_VAR, str(tmp_path))

    with run_context("demo", clock=lambda: FIXED_TS) as run:
        assert run.run_dir == tmp_path / f"demo-{FIXED_TS}"


def test_run_context_explicit_root_wins_over_the_env_var(tmp_path, monkeypatch):
    """The env var is only the fallback for a caller that passes no `root`
    at all -- an explicit `root` argument (the seam every existing test in
    this file uses) must still win, so a caller that deliberately chose a
    directory is never silently redirected."""
    env_root = tmp_path / "env-root"
    explicit_root = tmp_path / "explicit-root"
    monkeypatch.setenv(LOGS_ROOT_ENV_VAR, str(env_root))

    with run_context("demo", root=explicit_root, clock=lambda: FIXED_TS) as run:
        assert run.run_dir == explicit_root / f"demo-{FIXED_TS}"

    assert not env_root.exists()


def test_run_context_creates_run_dir_under_injected_root_with_fixed_clock(tmp_path):
    with run_context("extract", root=tmp_path, clock=lambda: FIXED_TS) as run:
        assert run.run_dir == tmp_path / f"extract-{FIXED_TS}"
        assert run.run_dir.is_dir()


def test_record_appends_one_json_line_per_call_with_the_locked_keys(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.record(
            source_id="src-1",
            pass_name="extract",
            model=None,
            status="ok",
            duration_sec=1.25,
            error=None,
        )

    lines = (tmp_path / f"demo-{FIXED_TS}" / "run.jsonl").read_text(encoding="utf-8").strip()
    record = json.loads(lines)
    assert set(record) == {"source_id", "pass", "model", "status", "duration_sec", "error"}
    assert record["source_id"] == "src-1"
    assert record["pass"] == "extract"
    assert record["duration_sec"] == 1.25


def test_record_with_model_none_serializes_as_json_null(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.record(
            source_id="src-1",
            pass_name="extract",
            model=None,
            status="ok",
            duration_sec=0.5,
            error=None,
        )

    raw = (tmp_path / f"demo-{FIXED_TS}" / "run.jsonl").read_text(encoding="utf-8")
    assert '"model": null' in raw
    assert json.loads(raw.strip())["model"] is None


def test_handler_is_flushed_and_detached_on_context_exit(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        logger = run.logger
        assert logger.handlers, "expected the FileHandler attached inside the context"
        run.logger.info("inside the run")

    assert not logger.handlers, "expected the FileHandler detached once the context exits"

    console_log = (tmp_path / f"demo-{FIXED_TS}" / "console.log").read_text(encoding="utf-8")
    assert "inside the run" in console_log

    # A leaked handler would still accept records after exit and write into
    # a file it no longer owns; logging through the (now handler-less)
    # logger must not raise.
    logger.info("after context exit -- must not raise or leak")


def test_console_log_receives_logger_output_but_leaves_print_untouched(tmp_path, capsys):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.logger.info("logged through the run logger")
        print("printed straight to stdout")

    console_log = (tmp_path / f"demo-{FIXED_TS}" / "console.log").read_text(encoding="utf-8")
    assert "logged through the run logger" in console_log

    captured = capsys.readouterr()
    assert "printed straight to stdout" in captured.out
    assert "logged through the run logger" not in captured.out


def test_summary_md_stub_is_a_header_only_no_narrative_body(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS):
        pass

    summary = (tmp_path / f"demo-{FIXED_TS}" / "summary.md").read_text(encoding="utf-8")
    assert "demo" in summary
    # A stub is short -- a handful of header lines, never a generated report.
    assert len(summary.splitlines()) < 10


def test_record_has_no_parameter_that_can_carry_source_text(tmp_path):
    """DEC-23 guard: record()'s signature is a fixed set of keyword-only
    scalars. There is no `chunk_text`/`text`/`passage` parameter to smuggle
    a source passage through, so passing one is a TypeError, not silently
    accepted."""
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        with pytest.raises(TypeError):
            run.record(
                source_id="src-1",
                pass_name="extract",
                model=None,
                status="ok",
                duration_sec=0.1,
                error=None,
                chunk_text="this is source prose and must never be accepted",
            )


def test_per_source_failure_records_error_status_without_affecting_other_records(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.record(
            source_id="ok-1",
            pass_name="extract",
            model=None,
            status="ok",
            duration_sec=1.0,
            error=None,
        )
        run.record(
            source_id="fail-1",
            pass_name="extract",
            model=None,
            status="error",
            duration_sec=0.2,
            error="boom",
        )

    lines = (tmp_path / f"demo-{FIXED_TS}" / "run.jsonl").read_text(encoding="utf-8").splitlines()
    ok_record, fail_record = (json.loads(line) for line in lines)

    assert ok_record["status"] == "ok"
    assert ok_record["error"] is None
    assert ok_record["source_id"] == "ok-1", "the healthy record must be unaffected by the failure"

    assert fail_record["status"] == "error"
    assert fail_record["error"] == "boom"


def test_run_context_yields_a_named_logger_for_the_run(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        assert isinstance(run.logger, logging.Logger)
