"""Inner unit tests for the axial.runlog seam (issue #270 slice 01, extended
by issue #526's run-state seam: meta.json, heartbeat, event(), the status
lifecycle, and the list_runs/load_run/follow_run reader API;
plans/run-logging/01-run-logging-seam.md's inner-loop list). Each test
drives `run_context`/`RunHandle` directly, independent of any specific pass
-- the pass wiring (axial.cli._extract, axial.run.run_pass) is exercised by
the outer acceptance tests at tests/test_runlog.py and tests/test_run*.py."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from axial.runlog import (
    HEARTBEAT_STALE_AFTER_SEC,
    LOGS_ROOT_ENV_VAR,
    RunNotFoundError,
    follow_run,
    list_runs,
    load_run,
    run_context,
)

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


# ---------------------------------------------------------------------------
# meta.json + the status lifecycle (issue #526)
# ---------------------------------------------------------------------------


def _read_meta(run_dir):
    return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))


def test_meta_json_is_running_while_open_then_ok_on_clean_exit(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        meta = _read_meta(run.run_dir)
        assert meta["status"] == "running"
        assert meta["run_id"] == run.run_id == f"demo-{FIXED_TS}"
        assert meta["finished_at"] is None
        assert meta["corpus_pin"] is None
        assert meta["command"], "expected a non-empty command line by default"

    meta = _read_meta(tmp_path / f"demo-{FIXED_TS}")
    assert meta["status"] == "ok"
    assert meta["finished_at"] is not None


def test_corpus_pin_and_explicit_command_are_recorded_when_supplied(tmp_path):
    with run_context(
        "demo",
        root=tmp_path,
        clock=lambda: FIXED_TS,
        command="axial run extract --corpus",
        corpus_pin="corpus:data/sources (3 sources)",
    ):
        pass

    meta = _read_meta(tmp_path / f"demo-{FIXED_TS}")
    assert meta["corpus_pin"] == "corpus:data/sources (3 sources)"
    assert meta["command"] == "axial run extract --corpus"


def test_set_status_is_honored_when_the_with_block_exits_cleanly(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.set_status("failed")

    assert _read_meta(tmp_path / f"demo-{FIXED_TS}")["status"] == "failed"


def test_set_status_rejects_an_unknown_value(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        with pytest.raises(ValueError):
            run.set_status("done")


def test_an_uncaught_exception_marks_status_failed_and_still_propagates(tmp_path):
    with pytest.raises(RuntimeError):
        with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS):
            raise RuntimeError("boom")

    assert _read_meta(tmp_path / f"demo-{FIXED_TS}")["status"] == "failed"


def test_a_keyboard_interrupt_marks_status_aborted_and_still_propagates(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS):
            raise KeyboardInterrupt()

    assert _read_meta(tmp_path / f"demo-{FIXED_TS}")["status"] == "aborted"


def test_exception_status_overrides_an_earlier_set_status_call(tmp_path):
    """A real exception is more authoritative than the caller's own guess
    (run_context's own docstring): set_status("ok") followed by an
    exception must still land as "failed", never "ok"."""
    with pytest.raises(RuntimeError):
        with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
            run.set_status("ok")
            raise RuntimeError("boom")

    assert _read_meta(tmp_path / f"demo-{FIXED_TS}")["status"] == "failed"


# ---------------------------------------------------------------------------
# The heartbeat (issue #526)
# ---------------------------------------------------------------------------


def test_run_context_writes_a_fresh_heartbeat_immediately_on_open(tmp_path):
    """Liveness must not depend on waiting for the background thread's
    first periodic tick -- the very first heartbeat write happens
    synchronously before `run_context` ever yields."""
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        heartbeat = json.loads((run.run_dir / "heartbeat.json").read_text(encoding="utf-8"))
        assert "updated_at" in heartbeat

        view = load_run(run.run_dir, now=datetime.fromisoformat(heartbeat["updated_at"]))
        assert view.alive is True


def test_load_run_reads_a_stale_heartbeat_as_dead_even_though_status_is_running(tmp_path):
    """A process a hard kill ends never runs `run_context`'s own `finally`,
    so its `meta.json` is stuck at `status: "running"` forever -- heartbeat
    age is the only thing that tells that apart from a run genuinely still
    working (built directly on disk here, not through `run_context`, since
    a real kill cannot be simulated in-process)."""
    run_dir = tmp_path / "demo-killed"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "name": "demo",
                "command": "axial run interrogate --corpus",
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": None,
                "corpus_pin": None,
                "status": "running",
            }
        ),
        encoding="utf-8",
    )
    stale_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    (run_dir / "heartbeat.json").write_text(
        json.dumps({"updated_at": stale_at.isoformat()}), encoding="utf-8"
    )

    now = stale_at + timedelta(seconds=HEARTBEAT_STALE_AFTER_SEC + 1)
    view = load_run(run_dir, now=now)

    assert view.meta["status"] == "running"
    assert view.alive is False, "a stale heartbeat must read as dead, by heartbeat age alone"
    assert view.heartbeat_age_sec > HEARTBEAT_STALE_AFTER_SEC

    # list_runs must agree with load_run for the exact same run directory.
    listing = next(entry for entry in list_runs(tmp_path, now=now) if entry.run_dir == run_dir)
    assert listing.alive is False


def test_load_run_reads_a_fresh_heartbeat_as_alive_while_status_is_running(tmp_path):
    run_dir = tmp_path / "demo-live"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "name": "demo",
                "command": "axial run interrogate --corpus",
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": None,
                "corpus_pin": None,
                "status": "running",
            }
        ),
        encoding="utf-8",
    )
    fresh_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    (run_dir / "heartbeat.json").write_text(
        json.dumps({"updated_at": fresh_at.isoformat()}), encoding="utf-8"
    )

    now = fresh_at + timedelta(seconds=HEARTBEAT_STALE_AFTER_SEC - 1)
    view = load_run(run_dir, now=now)

    assert view.meta["status"] == "running"
    assert view.alive is True


# ---------------------------------------------------------------------------
# event() -- finer-grained than record() (issue #526)
# ---------------------------------------------------------------------------


def test_event_appends_finer_grained_records_to_its_own_file(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.event(kind="source_start", source_id="s1", pass_name="extract", detail="1/2")
        run.event(kind="source_finish", source_id="s1", pass_name="extract")

    run_dir = tmp_path / f"demo-{FIXED_TS}"
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["kind"] == "source_start"
    assert first["source_id"] == "s1"
    assert first["pass"] == "extract"
    assert first["detail"] == "1/2"
    assert "ts" in first

    # A separate stream from record()'s own run.jsonl -- never folded into
    # its locked, one-per-unit-of-work schema.
    assert not (run_dir / "run.jsonl").exists()


def test_event_has_no_parameter_that_can_carry_source_text(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        with pytest.raises(TypeError):
            run.event(kind="source_start", chunk_text="this must never be accepted")


# ---------------------------------------------------------------------------
# Reader API: list_runs, load_run, follow_run (issue #526)
# ---------------------------------------------------------------------------


def test_list_runs_returns_newest_first_and_skips_dirs_without_meta_json(tmp_path):
    (tmp_path / "not-a-run").mkdir()  # no meta.json -- must be skipped, not crashed on

    with run_context("alpha", root=tmp_path, clock=lambda: "20260101T000000Z"):
        pass
    with run_context("beta", root=tmp_path, clock=lambda: "20260102T000000Z"):
        pass

    listings = list_runs(tmp_path)

    assert [listing.name for listing in listings] == ["beta", "alpha"]
    assert all(listing.run_dir.name != "not-a-run" for listing in listings)
    assert all(listing.status == "ok" for listing in listings)


def test_list_runs_over_a_missing_root_returns_an_empty_list(tmp_path):
    assert list_runs(tmp_path / "does-not-exist") == []


def test_load_run_reads_records_and_events_together(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.record(
            source_id="s1",
            pass_name="extract",
            model=None,
            status="ok",
            duration_sec=1.0,
            error=None,
        )
        run.event(kind="source_start", source_id="s1", pass_name="extract")

    view = load_run(tmp_path / f"demo-{FIXED_TS}")

    assert view.meta["status"] == "ok"
    assert len(view.records) == 1 and view.records[0]["source_id"] == "s1"
    assert len(view.events) == 1 and view.events[0]["kind"] == "source_start"
    assert view.alive is False, "a finished run is never 'alive', whatever its heartbeat age"


def test_load_run_raises_for_a_directory_with_no_meta_json(tmp_path):
    with pytest.raises(RunNotFoundError):
        load_run(tmp_path / "does-not-exist")


def test_follow_run_yields_existing_lines_then_stops_for_an_already_finished_run(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: FIXED_TS) as run:
        run.record(
            source_id="s1",
            pass_name="extract",
            model=None,
            status="ok",
            duration_sec=1.0,
            error=None,
        )
        run.event(kind="source_start", source_id="s1", pass_name="extract")

    rows = list(
        follow_run(
            tmp_path / f"demo-{FIXED_TS}",
            sleep=lambda seconds: pytest.fail("must never sleep for an already-finished run"),
        )
    )

    assert {row["stream"] for row in rows} == {"record", "event"}
    assert len(rows) == 2


def test_follow_run_polls_and_stops_once_status_leaves_running(tmp_path):
    """A minimal stand-in for a still-running writer: `meta.json` starts at
    `"running"`, and the injected `sleep` flips it to `"ok"` the moment it
    is called -- proving `follow_run` polls (rather than returning
    immediately) and stops as soon as the writer finishes, without ever
    blocking on a real timer."""
    run_dir = tmp_path / "demo-live"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        json.dumps({"kind": "source_start"}) + "\n", encoding="utf-8"
    )

    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        (run_dir / "meta.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

    rows = list(follow_run(run_dir, poll_interval=0.01, sleep=fake_sleep))

    assert sleep_calls == [0.01], "expected exactly one poll before status left 'running'"
    assert [row["kind"] for row in rows] == ["source_start"]


def test_follow_run_stop_when_stale_reports_death_instead_of_hanging(tmp_path):
    """issue #530: a hard-killed run leaves `meta.json` stuck at
    `"running"` forever (module docstring) -- `stop_when_stale=True` must
    break the loop the moment the heartbeat itself goes stale, yielding a
    death marker, rather than polling that run forever."""
    run_dir = tmp_path / "demo-dead"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    stale_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_STALE_AFTER_SEC + 5)
    (run_dir / "heartbeat.json").write_text(
        json.dumps({"updated_at": stale_heartbeat.isoformat()}), encoding="utf-8"
    )

    rows = list(
        follow_run(
            run_dir,
            stop_when_stale=True,
            sleep=lambda seconds: pytest.fail("must stop on the first stale check, never sleep"),
        )
    )

    assert rows == [{"stream": "status", "status": "stale"}]


def test_follow_run_without_stop_when_stale_keeps_polling_a_stale_heartbeat(tmp_path):
    """`stop_when_stale` defaults to `False` -- the exact prior behaviour
    for every existing caller is unchanged: a stale heartbeat with status
    still `"running"` keeps polling rather than stopping early."""
    run_dir = tmp_path / "demo-live"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    stale_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_STALE_AFTER_SEC + 5)
    (run_dir / "heartbeat.json").write_text(
        json.dumps({"updated_at": stale_heartbeat.isoformat()}), encoding="utf-8"
    )

    def fake_sleep(seconds):
        (run_dir / "meta.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

    rows = list(follow_run(run_dir, poll_interval=0.01, sleep=fake_sleep))

    assert rows == []
