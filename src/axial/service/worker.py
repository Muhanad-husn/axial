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

**The content-keyed paper cache (issue #686) is checked here, before the
engine ever runs** -- `axial.service.cache.PaperCache`'s own module
docstring covers the key and the cross-principal materialisation; this
module only wires it into `run_ask_job`'s own flow, a lookup on entry, a
`store` call on a fresh generation's way out. A `run_job` callable now
reports a fourth thing back to `Worker.run_once`: whether the row it
completed was a cache hit and what it cost, so those two land on the job
row (`JobStore.complete`) the same way `result_ref`/`corpus_pin` always
have.

**`run_job` reports a fifth thing, `tokens` (issue #724)**: the run's own
total token count, read off the exact same `record["cost"]["by_pass"]`
dict `cost_usd` already comes from -- never a second read of the record,
and never a re-derivation from anything `GET /me/usage` reads later. Same
rule as `cost_usd`: `0` on a cache hit (this job made no model call), and
`None` when the record carried no `cost` block to sum at all.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from axial.ask.engine import ask as run_ask
from axial.brief.intake import BriefContent, compute_brief_id
from axial.llm import LLMClient
from axial.paths import scoped_for_principal
from axial.service.cache import PaperCache
from axial.service.jobs import JobStore
from axial.service.snapshot import Snapshot, SnapshotPinMismatchError

# How often a claimed job's heartbeat is refreshed while `run_job` is still
# running. One constant, not a config system -- no caller has needed a
# different cadence; `JobStore.reclaim_stale`'s own staleness bound is set
# well above this so a live worker's heartbeat never races a reaper pass.
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0

# result_ref, corpus_pin, cached, cost_usd, tokens -- exactly what
# `JobStore.complete` needs to record (issue #686 added `cached`/`cost_usd`,
# issue #724 added `tokens`).
JobRunner = Callable[[dict[str, Any]], tuple[str, str, bool, float | None, int | None]]


def _tokens_used(record: dict[str, Any]) -> int | None:
    """The run's total token count, summed across `record["cost"]["by_pass"]`
    (issue #724) -- the same `cost` dict `cost_usd` is already read from
    below, never a second read of the record. `None` when the record
    carries no `cost` block at all (an unpriced or uncaptured run, §7.14's
    own rule for `cost_usd` applied identically here); a real `0` when
    `by_pass` exists but every pass's own `total_tokens` is genuinely `0`
    (`axial.llm.usage_and_cost_by_pass` never reports a negative or missing
    count once a pass is named in it)."""
    by_pass = ((record.get("cost") or {}).get("by_pass")) or None
    if by_pass is None:
        return None
    return sum(entry.get("total_tokens", 0) for entry in by_pass.values())


def run_ask_job(
    job: dict[str, Any],
    *,
    client: LLMClient,
    store: JobStore,
    snapshot: Snapshot,
    work_dir: Path,
    cache: PaperCache | None = None,
) -> tuple[str, str, bool, float | None, int | None]:
    """The `"ask"`-kind job body: run the full ask engine in-process over
    `job["payload"]` and return `(result_ref, corpus_pin, cached, cost_usd,
    tokens)` for `JobStore.complete`. `payload` carries the same arguments
    `axial ask` itself collects (`question`, `case`, and the optional
    `session_id`, `lens`, `weights` a follow-up or a weighted query
    supplies).

    `cache` (issue #686), when given, is checked BEFORE the engine runs at
    all: this payload's own `(brief_id, snapshot.corpus_pin)` -- the exact
    key `axial.ask.engine.ask` would compute for a first turn, via the same
    `compute_brief_id` -- is looked up, and a hit short-circuits straight to
    `(cached_result_ref, snapshot.corpus_pin, True, 0.0, 0)`: no model call,
    no `run_ask`, and one appended event so `GET /asks/{id}/events` still
    ends with something rather than jumping straight to `done`
    (`axial.service.cache`'s own module docstring covers the cross-principal
    materialisation a hit relies on). `None` (the default, and every call
    site before this parameter existed) skips the cache entirely -- always a
    miss, always generates, byte-identical to before this issue. On a fresh
    generation, the just-written record is handed to `cache.store` so the
    NEXT identical brief against this same pin is a hit.

    The returned `cost_usd` (issue #686, §7.14) is the run's own
    `record["cost"]["total_usd"]` -- `None`-preserving for an unpriced
    model's pass, never coerced to `0.0` (a cache hit's own, genuinely known
    zero, returned above instead). `tokens` (issue #724) is
    `_tokens_used(record)`, the same `record["cost"]["by_pass"]` dict summed
    instead of read for its `total_usd` -- identical null-preserving rule,
    and `0` (not `None`) on the cache-hit branch above for the same reason
    `cost_usd` is `0.0` there: this job itself made no model call.

    `snapshot` (issue #684) is the published corpus this worker process was
    started on and stays on for its whole life. The process is already bound
    to it (`Snapshot.bind`), so the engine reads it without being told; what
    the snapshot is passed for here is the two things binding cannot supply:
    `map_pin`, which otherwise would be derived by hashing raw source files
    a hosted worker must not hold, and the pin the row is stamped with.

    **The pin has one source of truth, the snapshot.** `resolve_pin_id`
    reads `evals/corpus_pin/` from inside the bound snapshot, so the run's
    own recorded pin and `snapshot.corpus_pin` are the same string by
    construction. When they are not, the binding leaked and the answer was
    computed against a corpus this row would misname:
    `SnapshotPinMismatchError` fails the job rather than record it.

    `work_dir` is where the analyst's own records land (`analyses/`,
    `runs/`). Passed explicitly because it is not corpus -- the snapshot is
    read-only, and nothing a query produces belongs inside it. Each is
    further scoped to the job's own `principal` (issue #685,
    `axial.paths.scoped_for_principal`), so two principals asking against
    the same worker never see each other's saved work -- the default
    principal (today's single pre-login analyst) keeps landing directly
    under `work_dir`, unchanged.

    `on_event` (issue #683) is the same seam `axial ask` wires to its live
    printer -- here it appends each call to `store` instead, under this
    job's own id, so `GET /asks/{id}/events` has something to stream. No new
    emitter: the engine already narrates every stage in analyst-readable
    prose (`axial.llm.emit_event`'s callers), this only persists it."""
    payload = job["payload"]
    weights = payload.get("weights") or {}
    brief_id = compute_brief_id(
        BriefContent(
            case=payload["case"],
            request=payload["question"],
            lens=payload.get("lens"),
            weights=weights,
        )
    )

    if cache is not None:
        cached_ref = cache.lookup(brief_id, snapshot.corpus_pin)
        if cached_ref is not None:
            store.append_event(
                job["id"],
                "this exact brief has already been answered against this corpus -- "
                "served from cache, no model call made",
                {"stage": "cache", "brief_id": brief_id, "corpus_pin": snapshot.corpus_pin},
            )
            return cached_ref, snapshot.corpus_pin, True, 0.0, 0

    def on_event(message: str, detail: dict[str, Any]) -> None:
        store.append_event(job["id"], message, detail)

    turn = run_ask(
        payload["question"],
        payload["case"],
        client=client,
        session_id=payload.get("session_id"),
        lens=payload.get("lens"),
        weights=payload.get("weights"),
        on_event=on_event,
        analyses_dir=scoped_for_principal(Path(work_dir) / "analyses", job["principal"]),
        runs_dir=scoped_for_principal(Path(work_dir) / "runs", job["principal"]),
        map_pin=snapshot.map_pin,
    )
    recorded = turn.result.record["corpus_pin"]
    if recorded != snapshot.corpus_pin:
        raise SnapshotPinMismatchError(snapshot.version, snapshot.corpus_pin, recorded)

    if cache is not None:
        cache.store(brief_id, snapshot.corpus_pin, turn.result.path, Path(work_dir) / "cache")

    cost_usd = (turn.result.record.get("cost") or {}).get("total_usd")
    tokens = _tokens_used(turn.result.record)
    return str(turn.result.path), snapshot.corpus_pin, False, cost_usd, tokens


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
            result_ref, corpus_pin, cached, cost_usd, tokens = self.run_job(job)
        except Exception as exc:  # noqa: BLE001 - any job failure is recorded, not swallowed
            stop.set()
            heartbeat_thread.join()
            self.store.fail(job["id"], error=str(exc))
        else:
            stop.set()
            heartbeat_thread.join()
            self.store.complete(
                job["id"],
                result_ref=result_ref,
                corpus_pin=corpus_pin,
                cached=cached,
                cost_usd=cost_usd,
                tokens=tokens,
            )
        return True

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval):
            self.store.heartbeat(job_id)
