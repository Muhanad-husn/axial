"""Subprocess harness for test_worker_reclaim.py (issue #681's second "done
when": a worker killed mid-job leaves its row reclaimable). This is a real,
separate OS process launched by the test and killed by it -- not a stub
standing in for a dead worker.

Run as `python _subprocess_worker.py <dsn>`: claims exactly one job (setting
`state='running'`/`claimed_at`/`heartbeat_at` for real, in Postgres) and then
sleeps well past any reasonable test timeout, so the test can kill this
process at its leisure once it has observed the claim.
"""

from __future__ import annotations

import sys
import time

from axial.service.jobs import JobStore
from axial.service.worker import Worker


def _never_finishes(job: dict) -> tuple[str, str]:
    time.sleep(3600)
    return "unused", "unused"  # pragma: no cover - never reached, the test kills this process first


def main() -> None:
    dsn = sys.argv[1]
    store = JobStore(dsn)
    worker = Worker(store, run_job=_never_finishes, heartbeat_interval=0.2)
    worker.run_once()


if __name__ == "__main__":
    main()
