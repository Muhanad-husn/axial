"""Fixture runs for the operator-console suite: real `axial.runlog` run
directories, written with `run_context`'s own file shapes so the console is
tested against the artifacts the pipeline actually produces."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from axial.runlog import HEARTBEAT_STALE_AFTER_SEC, LOGS_ROOT_ENV_VAR


def write_run(
    root: Path,
    run_id: str,
    *,
    status: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    records: list[dict] | None = None,
    events: list[dict] | None = None,
    heartbeat_at: datetime | None = None,
    last_write_at: datetime | None = None,
    command: str = "axial run chunk --corpus",
    report: dict | None = None,
) -> Path:
    """One run directory, exactly as `axial.runlog.run_context` leaves it."""
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "name": run_id.rsplit("-", 1)[0],
                "command": command,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat() if finished_at else None,
                "corpus_pin": None,
                "status": status,
            }
        ),
        encoding="utf-8",
    )
    if heartbeat_at is not None:
        (run_dir / "heartbeat.json").write_text(
            json.dumps({"updated_at": heartbeat_at.isoformat()}), encoding="utf-8"
        )
    for name, rows in (("run.jsonl", records), ("events.jsonl", events)):
        if rows is None:
            continue
        path = run_dir / name
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        if last_write_at is not None:
            stamp = last_write_at.timestamp()
            os.utime(path, (stamp, stamp))
    if report is not None:
        (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return run_dir


@pytest.fixture
def write_run_dir():
    """`write_run`, as a fixture -- `tests/` has no packages, so a test
    module cannot import it directly."""
    return write_run


@pytest.fixture
def logs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated `data/logs` the console reads through its normal path
    resolution (`AXIAL_LOGS_ROOT`), never a patched module global."""
    root = tmp_path / "logs"
    root.mkdir()
    monkeypatch.setenv(LOGS_ROOT_ENV_VAR, str(root))
    return root


@pytest.fixture
def now() -> datetime:
    """Real wall clock: the console reads the same clock, and a heartbeat is
    only fresh relative to it."""
    return datetime.now(timezone.utc)


@pytest.fixture
def stalled_run(logs_root: Path, now: datetime) -> Path:
    """A run that is alive -- its heartbeat thread is still ticking -- that
    finished its tenth source and never started an eleventh: nothing in
    flight, silent for twenty minutes against a cadence of twenty seconds.
    The exact shape the quiet band exists to make visible."""
    started = now - timedelta(minutes=30)
    events = []
    for i in range(10):
        at = started + timedelta(seconds=60 * i)
        events.append(
            {
                "ts": at.isoformat(),
                "kind": "source_start",
                "source_id": f"src-{i}",
                "pass": "chunk",
                "detail": f"{i + 1}/12",
            }
        )
        events.append(
            {
                "ts": (at + timedelta(seconds=59)).isoformat(),
                "kind": "source_finish",
                "source_id": f"src-{i}",
                "pass": "chunk",
                "detail": None,
            }
        )
    return write_run(
        logs_root,
        "run-chunk-20260810T113000Z",
        status="running",
        started_at=started,
        heartbeat_at=now - timedelta(seconds=HEARTBEAT_STALE_AFTER_SEC / 4),
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
        events=events,
        last_write_at=now - timedelta(minutes=20),
    )


@pytest.fixture
def finished_run(logs_root: Path, now: datetime) -> Path:
    """A clean, finished run -- no heartbeat left ticking, `report.json`
    written."""
    started = now - timedelta(minutes=10)
    return write_run(
        logs_root,
        "run-interrogate-20260810T115000Z",
        status="ok",
        started_at=started,
        finished_at=now - timedelta(minutes=1),
        command="axial run interrogate --corpus --workers 12",
        records=[
            {
                "source_id": "src-a",
                "pass": "interrogate",
                "model": "z-ai/glm-5.2",
                "status": "ok",
                "duration_sec": 540.0,
                "error": None,
            },
            {
                "source_id": "src-b",
                "pass": "interrogate",
                "model": "z-ai/glm-5.2",
                "status": "ok",
                "duration_sec": 540.0,
                "error": None,
            },
        ],
        events=[
            {
                "ts": started.isoformat(),
                "kind": "source_start",
                "source_id": "src-a",
                "pass": "interrogate",
                "detail": "1/2",
            },
            {
                "ts": (now - timedelta(minutes=1)).isoformat(),
                "kind": "source_finish",
                "source_id": "src-a",
                "pass": "interrogate",
                "detail": None,
            },
        ],
        report={
            "ok_count": 2,
            "fail_count": 0,
            "skip_count": 0,
            "outstanding": [],
            "tokens_and_cost": {"total_usd": 1.25},
        },
    )
