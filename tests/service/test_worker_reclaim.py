"""Acceptance test for issue #681's second "done when": a worker killed
mid-job leaves its row reclaimable, and a second worker picks it up. A real
subprocess (`_subprocess_worker.py`) claims the job and is killed by this
test with SIGKILL/`Process.kill()` -- not a mock of a dead worker."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from axial.service.jobs import RUNNING, JobStore
from axial.service.worker import Worker

_HARNESS = Path(__file__).parent / "_subprocess_worker.py"


def _wait_until_running(store: JobStore, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = store.get(job_id)
        if row is not None and row["state"] == RUNNING:
            return row
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} never reached 'running'")


def test_a_worker_killed_mid_job_leaves_its_row_reclaimable(job_store: JobStore, postgres_dsn: str):
    job_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"question": "Q", "case": "Syria"}
    )

    proc = subprocess.Popen([sys.executable, str(_HARNESS), postgres_dsn])
    try:
        claimed = _wait_until_running(job_store, job_id)
        assert claimed["heartbeat_at"] is not None
    finally:
        proc.kill()
        proc.wait(timeout=10)

    # The dead process leaves the row 'running' with a heartbeat that never
    # advances again -- a small stale threshold ages it out quickly, without
    # the test waiting on a real multi-minute production timeout. The sleep
    # guarantees the elapsed time actually exceeds that threshold.
    time.sleep(0.6)
    reclaimed = job_store.reclaim_stale(stale_after_seconds=0.5)
    assert reclaimed == 1
    row = job_store.get(job_id)
    assert row["state"] == "queued"

    second_worker_calls = []

    def fake_run_job(job):
        second_worker_calls.append(job["id"])
        return "data/analyses/recovered.json", "sim-2026-08-10"

    second_worker = Worker(job_store, run_job=fake_run_job)
    picked_up = second_worker.run_once()

    assert picked_up is True
    assert second_worker_calls == [job_id]
    row = job_store.get(job_id)
    assert row["state"] == "done"
    assert row["corpus_pin"] == "sim-2026-08-10"
