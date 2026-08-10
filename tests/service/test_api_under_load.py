"""Issue #682's first two "done when"s, against the real API, the real
`JobStore` and the real Postgres fixture:

1. `POST /asks` returns in under 100ms while an ask is running -- with a
   real `Worker` actually holding a claimed row and heartbeating, not a
   mock. The occupying job's body sleeps instead of running the paid engine
   (a real three-minute ask costs real model calls); the property under
   test is that the POST does not wait for it, and a job that has not
   returned after seconds proves that exactly as well as one that has not
   returned after three minutes.
2. Killing every worker leaves the API answering normally, with jobs
   stacking up as `queued` -- the worker here is a real OS process, killed
   with `Process.kill()`, reusing `_subprocess_worker.py`.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from axial.service.api import create_app
from axial.service.jobs import QUEUED, RUNNING, JobStore
from axial.service.worker import Worker

_HARNESS = Path(__file__).parent / "_subprocess_worker.py"

# The issue's own bar for `POST /asks`.
_POST_BUDGET_SECONDS = 0.1


@pytest.fixture
def client(job_store: JobStore):
    with TestClient(create_app(job_store)) as test_client:
        yield test_client


def _wait_until_running(store: JobStore, job_id: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = store.get(job_id)
        if row is not None and row["state"] == RUNNING:
            return
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached 'running'")


def test_post_asks_returns_under_100ms_while_an_ask_is_running(client, job_store: JobStore):
    occupied = threading.Event()
    release = threading.Event()

    def long_running_ask(job):
        occupied.set()
        release.wait(60)
        return "data/analyses/long.json", "sim-2026-08-10", False, None, None

    running_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"case": "Syria", "question": "A long one"}
    )
    worker = Worker(job_store, run_job=long_running_ask, heartbeat_interval=0.1)
    worker_thread = threading.Thread(target=worker.run_once, daemon=True)
    worker_thread.start()

    try:
        assert occupied.wait(15)
        # One read first, so the measurement below is of a POST against a
        # warm app rather than of first-request import cost.
        client.get("/asks")

        started = time.perf_counter()
        response = client.post("/asks", json={"case": "Syria", "request": "Who led it?"})
        elapsed = time.perf_counter() - started

        assert response.status_code == 202
        assert elapsed < _POST_BUDGET_SECONDS, f"POST /asks took {elapsed * 1000:.0f}ms"
        # The ask the POST did not wait for is still running.
        assert job_store.get(running_id)["state"] == RUNNING
        assert job_store.get(response.json()["id"])["state"] == QUEUED
    finally:
        release.set()
        worker_thread.join(30)


def test_killing_every_worker_leaves_the_api_answering_with_jobs_stacking_up(
    client, job_store: JobStore, postgres_dsn: str
):
    claimed_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"case": "Syria", "question": "Q"}
    )
    proc = subprocess.Popen([sys.executable, str(_HARNESS), postgres_dsn])
    try:
        _wait_until_running(job_store, claimed_id)
    finally:
        proc.kill()
        proc.wait(timeout=15)

    # No worker process is alive now. The API must not care.
    submitted = []
    for index in range(3):
        response = client.post("/asks", json={"case": "Syria", "request": f"Question {index}"})
        assert response.status_code == 202
        submitted.append(response.json()["id"])

    for job_id in submitted:
        status = client.get(f"/asks/{job_id}")
        assert status.status_code == 200
        assert status.json()["state"] == QUEUED

    listed = client.get("/asks")
    assert listed.status_code == 200
    assert [ask["id"] for ask in listed.json()] == list(reversed(submitted))
