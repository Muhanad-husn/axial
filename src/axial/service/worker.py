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

**Every ask ends in an essay (issue #784).** Once the analysis record is
written, `run_ask_job` runs the Phase-C composition over that one record
(`axial.ask.paper.draft_paper_for_turn`, the same call `axial ask` has made
since #668) and records where the paper landed on the job row. Four
consequences, three in `_draft_the_essay` and one in
`_hit_without_an_essay`: a drafting failure never fails the ask, because
the analysis is already persisted and already paid for; the drafting passes
are counted into the `cost_usd`/`tokens` this job reports, so the spend an
analyst is shown is the spend they incurred; the paper is drafted BEFORE
`cache.store`, so a later hit serves the essay along with the answer; and a
hit whose entry has no essay -- a failed earlier draft, or an entry written
by a worker predating this issue -- drafts one and repairs the entry rather
than serving an essay-less answer forever.

**`main()` is the worker container's own entry point** (issue #691,
`python -m axial.service.worker`, this module's own `if __name__` guard):
bind the process to the published snapshot mounted at `AXIAL_SNAPSHOT_DIR`
(`Snapshot.bind`), create the `jobs`/`job_events`/`paper_cache` schema
(idempotent, so it races safely with `axial.service.api.create_app` doing
the same for `jobs`), build the real `LLMClient`, and run
`AXIAL_WORKER_COUNT` claim/run loops concurrently over the same queue --
`ThreadPoolExecutor`, the same bounded-concurrency idiom every other
`--workers` pass in this codebase already uses (`axial.interrogate`,
`axial.gather`, ...), safe here for the identical reason it is safe there:
`JobStore.claim`'s `SELECT ... FOR UPDATE SKIP LOCKED` is exactly what
makes two loops racing the same table never claim the same row
(`axial.service.jobs` module docstring). A slot that finds the queue
empty sleeps `AXIAL_WORKER_POLL_SECONDS` before asking again. A second
background thread calls `JobStore.reclaim_stale` every
`AXIAL_WORKER_RECLAIM_AFTER_SECONDS` -- issue #681 built that method for
exactly this ("a worker killed mid-job leaves its row reclaimable") but
shipped with no production caller; this is the first one. SIGTERM/SIGINT
(`docker compose down`/`stop`) set a shared stop event so every slot
finishes its current job and exits cleanly rather than being SIGKILLed
mid-run once the container's grace period expires.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.ask.engine import ask as run_ask
from axial.ask.paper import draft_paper, draft_paper_for_turn
from axial.brief.intake import BriefContent, compute_brief_id
from axial.llm import LLMClient, get_client
from axial.paths import scoped_for_principal
from axial.service.cache import PaperCache
from axial.service.jobs import DEFAULT_STALE_AFTER_SECONDS, JobStore
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


def _combined(analysis: float | int | None, paper: float | int | None):
    """The ask's total across both halves of the work it did (issue #784):
    the Phase-B answer and the Phase-C essay drafted from it.

    `None` means unknown, never zero, and it survives one side at a time the
    way `axial.llm.usage_and_cost_by_pass` already treats a single record --
    a total is `None` only when NOTHING priced. Dropping a known half
    because the other is unpriced would report a smaller number than the ask
    actually cost, which is worse than either honest answer.
    """
    known = [value for value in (analysis, paper) if value is not None]
    if not known:
        return None
    return sum(known)


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
            # The essay comes with it (issue #784). A repeat question is free
            # by design; a free answer that silently lost its essay would be
            # a worse answer, not a cheaper one.
            cached_paper = cache.lookup_paper(brief_id, snapshot.corpus_pin)
            if cached_paper is not None:
                store.set_paper_ref(job["id"], cached_paper)
                return cached_ref, snapshot.corpus_pin, True, 0.0, 0
            return _hit_without_an_essay(
                job,
                brief_id,
                Path(cached_ref),
                client=client,
                store=store,
                cache=cache,
                snapshot=snapshot,
                work_dir=Path(work_dir),
            )

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

    # Drafted BEFORE the cache is written, so the entry a later hit reads
    # carries the essay as well as the answer -- one insert, never a record
    # cached now and an essay attached to it later.
    essay = _draft_the_essay(
        job, turn, client=client, store=store, work_dir=work_dir, on_event=on_event
    )

    if cache is not None:
        cache.store(
            brief_id,
            snapshot.corpus_pin,
            turn.result.path,
            Path(work_dir) / "cache",
            paper_path=essay.path,
        )

    cost_usd = _combined(
        (turn.result.record.get("cost") or {}).get("total_usd"),
        None if essay.record is None else (essay.record.get("cost") or {}).get("total_usd"),
    )
    tokens = _combined(
        _tokens_used(turn.result.record),
        None if essay.record is None else _tokens_used(essay.record),
    )
    return str(turn.result.path), snapshot.corpus_pin, False, cost_usd, tokens


@dataclass(frozen=True)
class _EssayOutcome:
    """What `_draft_the_essay` found. `failed` distinguishes the two ways
    `record` can be `None` -- a refusal, which never has an essay, from a
    drafting run that died, which should have had one."""

    record: dict[str, Any] | None
    path: Path | None
    failed: bool


def _hit_without_an_essay(
    job: dict[str, Any],
    brief_id: str,
    cached_ref: Path,
    *,
    client: LLMClient,
    store: JobStore,
    cache: PaperCache,
    snapshot: Snapshot,
    work_dir: Path,
) -> tuple[str, str, bool, float | None, int | None]:
    """A cache hit whose entry carries no essay: draft one from the cached
    answer and repair the entry, rather than serving an essay-less answer
    forever (issue #784).

    **Why this exists.** A cache hit short-circuits before any drafting, so
    without this an entry stored after a failed drafting run -- or stored by
    a worker that predates this issue -- would deny every later ask of that
    question its essay permanently, with nothing recorded to say why. Not
    caching such a run instead would be worse: it would cost a full Phase B
    re-run to recover a $0.013 essay, and it would break issue #686's own
    guarantee that an identical brief generates once.

    The answer is still free; only the essay is paid for. The row stays
    `cached=True`, because the ask WAS served from the cache -- what it
    reports is the drafting cost it actually incurred, not `0.0`.
    """
    record = json.loads(cached_ref.read_text(encoding="utf-8"))
    # The record's OWN id, not the cache key: intake keys its claim
    # inventory on the id it is asked for, and the plan the drafter writes
    # names claims by the id the record carries. On a first turn the two are
    # the same string; taking it off the record is what keeps them the same
    # here without relying on that.
    record_id = record.get("brief_id") or brief_id

    analyses_dir = scoped_for_principal(Path(work_dir) / "analyses", job["principal"])
    analyses_dir.mkdir(parents=True, exist_ok=True)
    record_path = analyses_dir / f"{record_id}.json"
    # Intake resolves `<analyses_dir>/<brief_id>.json`; the cached copy is
    # filed under a cache-keyed name, so it has to land here first. The
    # analyst asked this question, so the record belongs in their own
    # working set either way.
    shutil.copyfile(cached_ref, record_path)

    papers_dir = scoped_for_principal(Path(work_dir) / "papers", job["principal"])
    try:
        paper_record = draft_paper(
            client,
            job["payload"]["question"],
            record_id,
            record,
            analyses_dir=analyses_dir,
            papers_dir=papers_dir,
        )
    except Exception as exc:  # noqa: BLE001 - see `_draft_the_essay`: the answer outlives the essay
        store.append_event(
            job["id"],
            f"the cached answer stands, but writing the essay from it failed: {exc}",
            {"stage": "draft", "error": str(exc)},
        )
        return str(record_path), snapshot.corpus_pin, True, 0.0, 0

    if paper_record is None:  # a cached refusal: no essay, and never one
        return str(record_path), snapshot.corpus_pin, True, 0.0, 0

    paper_path = papers_dir / f"{paper_record['paper_brief_id']}.json"
    store.set_paper_ref(job["id"], str(paper_path))
    cache.attach_paper(brief_id, snapshot.corpus_pin, paper_path, Path(work_dir) / "cache")
    return (
        str(record_path),
        snapshot.corpus_pin,
        True,
        (paper_record.get("cost") or {}).get("total_usd"),
        _tokens_used(paper_record),
    )


def _draft_the_essay(
    job: dict[str, Any],
    turn: Any,
    *,
    client: LLMClient,
    store: JobStore,
    work_dir: Path,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> _EssayOutcome:
    """Draft the paper this ask ends in (issue #784) and record where it
    landed.

    `on_event` (issue #784 slice 03) is the same closure `run_ask_job` wires
    the analysis stages through, threaded straight to `draft_paper_for_turn`
    -> `run_paper`: the arc it planned and each section as it finishes land
    in `job_events` under this job's own id, continuing the same monotonic
    `seq` the analysis events already used, so `GET /asks/{id}/events` stays
    live through the last minute of a run rather than going quiet at `check`.

    **A drafting failure does not fail the ask.** The analysis is already
    persisted and already paid for, and losing it because the essay drawn
    from it could not be written would charge the analyst for an answer they
    never receive. The failure is appended as an event instead, so it reads
    as a failure of the drafting run rather than as a corpus with nothing to
    say -- the distinction PHASE-C §7.3 draws for a failed counter-position,
    one level up.

    **The catch is deliberately broad**, not the enumerated
    `PAPER_PIPELINE_ERRORS` alone. The rule is that the answer outlives the
    essay, and a rule that holds only for the failures somebody thought to
    list is not that rule: an `AttributeError` in the drafting layer would
    otherwise throw away an analysis the analyst has already been charged
    for. `Worker.run_once` catches broadly one level up for the same
    reason, and the failure is recorded rather than swallowed.
    """
    papers_dir = scoped_for_principal(Path(work_dir) / "papers", job["principal"])
    try:
        paper_record = draft_paper_for_turn(
            client,
            turn,
            on_event=on_event,
            analyses_dir=turn.result.path.parent,
            papers_dir=papers_dir,
        )
    except Exception as exc:  # noqa: BLE001 - deliberate, see the docstring above
        store.append_event(
            job["id"],
            f"the answer stands, but writing the essay from it failed: {exc}",
            {"stage": "draft", "error": str(exc)},
        )
        return _EssayOutcome(None, None, failed=True)

    if paper_record is None:
        return _EssayOutcome(None, None, failed=False)

    paper_path = papers_dir / f"{paper_record['paper_brief_id']}.json"
    store.set_paper_ref(job["id"], str(paper_path))
    return _EssayOutcome(paper_record, paper_path, failed=False)


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


# --------------------------------------------------------------------------
# Container entry point (issue #691)
# --------------------------------------------------------------------------

# Where the compose file mounts the published snapshot, in both the worker
# and the API container -- an in-container path, never a founder path, and
# the same default `axial.service.api`'s own cwd convention (module
# docstring there) resolves against when the API's `working_dir` is set to
# it too.
SNAPSHOT_DIR_ENV_VAR = "AXIAL_SNAPSHOT_DIR"
DEFAULT_SNAPSHOT_DIR = "/snapshot"

# Where a generated record's cache copy, and an analyst's `analyses`/`runs`
# output, are written -- writable, and deliberately NOT the read-only
# snapshot mount (`run_ask_job`'s own docstring; the review comment on issue
# #691 that named this gap).
WORK_DIR_ENV_VAR = "AXIAL_WORK_DIR"
DEFAULT_WORK_DIR = "/work"

# How many claim/run loops run concurrently in this one process (module
# docstring). One knob, matching the `--workers` convention every other
# bounded-concurrency pass in this codebase already exposes as a flag;
# here it is an env var because nothing else about a container's startup
# is a CLI flag.
WORKER_COUNT_ENV_VAR = "AXIAL_WORKER_COUNT"
DEFAULT_WORKER_COUNT = 1

# How long an empty queue is slept before the next claim attempt.
POLL_SECONDS_ENV_VAR = "AXIAL_WORKER_POLL_SECONDS"
DEFAULT_POLL_SECONDS = 2.0

# How long a claimed job may go without a heartbeat before
# `JobStore.reclaim_stale` returns it to the queue -- the same bound
# `DEFAULT_STALE_AFTER_SECONDS` already names, exposed here because #691 is
# what gives `reclaim_stale` its first production caller.
RECLAIM_AFTER_SECONDS_ENV_VAR = "AXIAL_WORKER_RECLAIM_AFTER_SECONDS"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _poll_loop(worker: Worker, *, poll_interval: float, stop: threading.Event) -> None:
    """One concurrency slot's own claim/run/sleep loop, until `stop` is
    set. `Worker.run_once` (this module's own docstring) claims and runs
    exactly one job and returns `False` when the queue was empty -- this
    is the first caller that runs it in a loop rather than once."""
    while not stop.is_set():
        claimed = worker.run_once()
        if not claimed:
            stop.wait(poll_interval)


def main() -> None:
    """The worker container's entry point (module docstring). Reads every
    setting from the environment, with the documented defaults above;
    `DATABASE_URL` and `OPENROUTER_API_KEY`/`AXIAL_SECRETS_PATH` (read by
    `axial.llm.get_client`, unchanged by this issue) are the only ones with
    no in-code default, since a worker with no database or no model access
    cannot do anything a default could paper over."""
    dsn = os.environ["DATABASE_URL"]
    snapshot_dir = os.environ.get(SNAPSHOT_DIR_ENV_VAR, DEFAULT_SNAPSHOT_DIR)
    work_dir = Path(os.environ.get(WORK_DIR_ENV_VAR, DEFAULT_WORK_DIR))
    worker_count = max(1, _env_int(WORKER_COUNT_ENV_VAR, DEFAULT_WORKER_COUNT))
    poll_interval = _env_float(POLL_SECONDS_ENV_VAR, DEFAULT_POLL_SECONDS)
    reclaim_after = _env_float(RECLAIM_AFTER_SECONDS_ENV_VAR, DEFAULT_STALE_AFTER_SECONDS)

    snapshot = Snapshot.open(snapshot_dir).bind()
    store = JobStore(dsn)
    store.create_schema()
    cache = PaperCache(dsn)
    cache.create_schema()
    client = get_client()
    work_dir.mkdir(parents=True, exist_ok=True)

    def run_job(job: dict[str, Any]) -> tuple[str, str, bool, float | None, int | None]:
        return run_ask_job(
            job, client=client, store=store, snapshot=snapshot, work_dir=work_dir, cache=cache
        )

    worker = Worker(store, run_job)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    signal.signal(signal.SIGINT, lambda *_args: stop.set())

    def reclaim_loop() -> None:
        while not stop.wait(reclaim_after):
            store.reclaim_stale(stale_after_seconds=reclaim_after)

    threading.Thread(target=reclaim_loop, daemon=True).start()

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(_poll_loop, worker, poll_interval=poll_interval, stop=stop)
            for _ in range(worker_count)
        ]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
