"""One real worker process for the #744 live validation.

Binds to the published snapshot at process start (`Snapshot.bind` chdirs into
it, for this process's whole life) and drains the queue with the real engine
and a real `LLMClient`. Deliberately NOT a test double: the point of this run
is to find out whether the web client's SSE walk works against the real thing.

    python scratchpad/live744_worker.py <dsn> <snapshot_root> <work_dir>

The client is built BEFORE `bind()`, while cwd is still the repo root, so
`config/pipeline.yaml` and `secrets/secrets.toml` resolve against the repo
rather than against the snapshot. `AXIAL_SECRETS_PATH` is set absolutely as a
second belt.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from axial.llm import get_client
from axial.service.cache import PaperCache
from axial.service.jobs import JobStore
from axial.service.snapshot import Snapshot
from axial.service.worker import Worker, run_ask_job


def main() -> None:
    dsn, snapshot_root, work_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    # Built while cwd is still the repo root.
    client = get_client()
    print(f"client: {type(client).__name__}", flush=True)

    snapshot = Snapshot.open(snapshot_root)
    print(
        f"snapshot {snapshot.version} pin={snapshot.corpus_pin} map={snapshot.map_pin}", flush=True
    )

    store = JobStore(dsn)
    cache = PaperCache(dsn)
    snapshot.bind()
    print(f"bound; cwd={Path.cwd()}", flush=True)

    worker = Worker(
        store,
        run_job=lambda job: run_ask_job(
            job,
            client=client,
            store=store,
            snapshot=snapshot,
            work_dir=work_dir,
            cache=cache,
        ),
    )

    print("draining", flush=True)
    while True:
        if not worker.run_once():
            time.sleep(1.0)


if __name__ == "__main__":
    main()
