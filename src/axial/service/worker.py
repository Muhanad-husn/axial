"""The worker process that drains the `jobs` table (issue #681): claim one
job via `JobStore.claim` (never two workers on the same row -- see
`axial.service.jobs`'s module docstring), heartbeat while it runs, and leave
a terminal `done`/`failed` record.

**The worker calls the existing ask path in-process** (the issue's own
requirement) -- `run_ask_job` below calls `axial.ask.engine.ask` directly,
never the `axial` CLI as a subprocess. `Worker.run_job` is a seam over that
call (mirrors `axial.ask.engine.ask`'s own `run_brief_fn` seam) so a test can
stand in a fast, free stub instead of a real, paid engine run; production
code always wires the real `run_ask_job`.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable

from axial.ask.engine import ask as run_ask
from axial.llm import LLMClient
from axial.service.jobs import JobStore

# How often a claimed job's heartbeat is refreshed while `run_job` is still
# running. One constant, not a config system -- no caller has needed a
# different cadence; `JobStore.reclaim_stale`'s own staleness bound is set
# well above this so a live worker's heartbeat never races a reaper pass.
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0

JobRunner = Callable[[dict[str, Any]], tuple[str, str]]


def run_ask_job(job: dict[str, Any], *, client: LLMClient) -> tuple[str, str]:
    """The `"ask"`-kind job body: run the full ask engine in-process over
    `job["payload"]` and return `(result_ref, corpus_pin)` for
    `JobStore.complete`. `payload` carries the same arguments `axial ask`
    itself collects (`question`, `case`, and the optional `session_id`,
    `lens`, `weights` a follow-up or a weighted query supplies)."""
    payload = job["payload"]
    turn = run_ask(
        payload["question"],
        payload["case"],
        client=client,
        session_id=payload.get("session_id"),
        lens=payload.get("lens"),
        weights=payload.get("weights"),
    )
    return str(turn.result.path), turn.result.record["corpus_pin"]


class Worker:
    """Claims and runs jobs one at a time. `run_job` decides what a claimed
    job actually does (`run_ask_job`, bound to a real `LLMClient`, in
    production; a fast stub in tests) -- the worker itself only owns the
    claim/heartbeat/terminal-record lifecycle, identical for every `kind`."""

    def __init__(
        self,
        store: JobStore,
        run_job: JobRunner,
        *,
        worker_id: str | None = None,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.store = store
        self.run_job = run_job
        self.worker_id = worker_id or uuid.uuid4().hex
        self.heartbeat_interval = heartbeat_interval

    def run_once(self) -> bool:
        """Claim one job and run it to a terminal state. Returns `False`
        with nothing claimed when the queue is empty, `True` otherwise
        (regardless of whether the job ended `done` or `failed`) --
        `run_job` raising is caught here and recorded as `failed` rather
        than propagating, so one bad job never kills the worker loop."""
        job = self.store.claim()
        if job is None:
            return False

        stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, args=(job["id"], stop), daemon=True
        )
        heartbeat_thread.start()
        try:
            result_ref, corpus_pin = self.run_job(job)
        except Exception as exc:  # noqa: BLE001 - any job failure is recorded, not swallowed
            stop.set()
            heartbeat_thread.join()
            self.store.fail(job["id"], error=str(exc))
        else:
            stop.set()
            heartbeat_thread.join()
            self.store.complete(job["id"], result_ref=result_ref, corpus_pin=corpus_pin)
        return True

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval):
            self.store.heartbeat(job_id)
