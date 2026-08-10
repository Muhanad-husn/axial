"""Acceptance test for issue #681's first "done when": two workers against
one queue never claim the same row. Real threads, each opening its own
Postgres connection through `JobStore.claim`'s `SELECT ... FOR UPDATE SKIP
LOCKED` -- no mock of the locking behavior, per the issue's own instruction.
"""

from __future__ import annotations

import threading

from axial.service.jobs import JobStore

_JOB_COUNT = 40
_WORKER_COUNT = 8


def test_concurrent_workers_never_claim_the_same_row(job_store: JobStore):
    job_ids = {
        job_store.enqueue(kind="ask", principal="analyst-1", payload={"n": i})
        for i in range(_JOB_COUNT)
    }

    claimed: list[str] = []
    claimed_lock = threading.Lock()
    start = threading.Barrier(_WORKER_COUNT)

    def drain_queue() -> None:
        start.wait()
        while True:
            job = job_store.claim()
            if job is None:
                return
            with claimed_lock:
                claimed.append(job["id"])

    workers = [threading.Thread(target=drain_queue) for _ in range(_WORKER_COUNT)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert len(claimed) == _JOB_COUNT, "every job should be claimed exactly once"
    assert len(claimed) == len(set(claimed)), "no job id was claimed twice"
    assert set(claimed) == job_ids
