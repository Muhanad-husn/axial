"""The console's read model and its one write action.

The numbers here are the ones an operator acts on -- effective concurrency
caught interrogation running strictly serial, and the quiet band is the only
thing that tells a wedged worker from a slow one -- so they are pinned
against run directories in `axial.runlog`'s own on-disk shapes rather than
through the UI.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from axial.operator import cli_bridge, monitor


def test_effective_concurrency_is_busy_time_over_wall_clock(finished_run: Path) -> None:
    snap = monitor.snapshot(finished_run)

    # Two sources, 540s of work each, inside a 540s run: 2.0x, against the
    # 12 workers the run's own recorded command asked for.
    assert snap.effective_concurrency == pytest.approx(2.0, abs=0.05)
    assert snap.workers == 12


def test_a_serial_run_reports_one_times(logs_root: Path, now: datetime, write_run_dir) -> None:
    run_dir = write_run_dir(
        logs_root,
        "run-interrogate-serial",
        status="ok",
        started_at=now - timedelta(seconds=600),
        finished_at=now,
        command="axial run interrogate --corpus --workers 12",
        records=[
            {
                "source_id": f"src-{i}",
                "pass": "interrogate",
                "model": "z-ai/glm-5.2",
                "status": "ok",
                "duration_sec": 200.0,
                "error": None,
            }
            for i in range(3)
        ],
    )

    snap = monitor.snapshot(run_dir)

    assert snap.effective_concurrency == pytest.approx(1.0, abs=0.05)
    assert snap.model_calls == 3


def test_a_stalled_run_reads_as_stalled(stalled_run: Path) -> None:
    snap = monitor.snapshot(stalled_run)

    assert snap.alive is True
    quiet = snap.quiet
    assert quiet is not None
    # 30 log lines over the 10 minutes it worked: a line every ~20s. It has
    # now been silent for 20 minutes with nothing in flight.
    assert quiet.expected_interval_sec == pytest.approx(20.0, abs=1.0)
    assert quiet.quiet_sec == pytest.approx(1200.0, abs=5.0)
    assert quiet.in_flight == 0
    assert quiet.overdue is True
    assert "src-9" in quiet.last_mark


def test_a_pass_silent_while_a_unit_runs_is_not_flagged(
    logs_root: Path, now: datetime, write_run_dir
) -> None:
    """The shape every real chunk/extract/interrogate pass spends most of
    its wall clock in: nothing logged for minutes because a source is being
    worked on. Replaying 77 real runs, cadence alone would have flagged
    81-97% of a healthy pass; nothing-in-flight is what tells them apart."""
    started = now - timedelta(seconds=300)
    run_dir = write_run_dir(
        logs_root,
        "run-chunk-working",
        status="running",
        started_at=started,
        heartbeat_at=now - timedelta(seconds=2),
        records=[
            {
                "source_id": "src-0",
                "pass": "chunk",
                "model": None,
                "status": "ok",
                "duration_sec": 30.0,
                "error": None,
            }
        ],
        events=[
            {
                "ts": started.isoformat(),
                "kind": "source_start",
                "source_id": "src-0",
                "pass": "chunk",
                "detail": "1/3",
            },
            {
                "ts": (started + timedelta(seconds=30)).isoformat(),
                "kind": "source_finish",
                "source_id": "src-0",
                "pass": "chunk",
                "detail": None,
            },
            {
                "ts": (started + timedelta(seconds=31)).isoformat(),
                "kind": "source_start",
                "source_id": "src-1",
                "pass": "chunk",
                "detail": "2/3",
            },
        ],
        last_write_at=now - timedelta(seconds=269),
    )

    quiet = monitor.snapshot(run_dir).quiet

    assert quiet is not None
    assert quiet.quiet_sec > (quiet.expected_interval_sec or 0) * 20
    assert quiet.in_flight == 1
    assert quiet.overdue is False


def test_a_live_run_keeping_its_own_cadence_is_not_overdue(
    logs_root: Path, now: datetime, write_run_dir
) -> None:
    started = now - timedelta(seconds=600)
    run_dir = write_run_dir(
        logs_root,
        "run-chunk-keeping-up",
        status="running",
        started_at=started,
        heartbeat_at=now - timedelta(seconds=2),
        records=[
            {
                "source_id": f"src-{i}",
                "pass": "chunk",
                "model": None,
                "status": "ok",
                "duration_sec": 60.0,
                "error": None,
            }
            for i in range(10)
        ],
        last_write_at=now - timedelta(seconds=5),
    )

    quiet = monitor.snapshot(run_dir).quiet

    assert quiet is not None
    assert quiet.expected_interval_sec == pytest.approx(59.5, abs=1.0)
    assert quiet.overdue is False


def test_a_finished_run_has_no_quiet_band(finished_run: Path) -> None:
    snap = monitor.snapshot(finished_run)

    assert snap.alive is False
    assert snap.quiet is None
    assert snap.spend_usd == pytest.approx(1.25)


def test_pass_rows_read_their_total_from_the_run_s_own_progress_detail(
    stalled_run: Path,
) -> None:
    (row,) = monitor.snapshot(stalled_run).passes

    assert row.name == "chunk"
    assert row.done == 10
    assert row.total == 12
    assert row.fraction == pytest.approx(10 / 12)


def test_ingest_launches_detached_from_the_console(
    logs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the console, or the browser tab, must not kill a running
    pass -- so the launch never produces a child of this process."""
    seen: dict[str, object] = {}

    class FakePopen:
        pid = 4242

        def __init__(self, argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    pid, console_log = cli_bridge.launch_detached(["sources"])

    assert pid == 4242
    assert seen["argv"] == [sys.executable, "-m", "axial.cli", "sources"]
    kwargs = seen["kwargs"]
    if sys.platform == "win32":
        assert (
            kwargs["creationflags"]
            == subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        assert kwargs["start_new_session"] is True
    # Detached means no console to inherit, so its output has to land in a
    # file rather than a pipe nobody is reading.
    assert console_log.parent == logs_root
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_sources_report_parses_the_cli_s_own_table() -> None:
    rows = cli_bridge.parse_sources_report(
        "name\tstatus\treason\nbatatu-1999.pdf\tdone\t\nnew-book.pdf\tnew\t\n"
    )

    assert rows == [
        {"name": "batatu-1999.pdf", "status": "done", "reason": ""},
        {"name": "new-book.pdf", "status": "new", "reason": ""},
    ]
