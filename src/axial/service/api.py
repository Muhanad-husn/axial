"""The HTTP surface both UIs call (issue #682): submit an ask, poll it,
fetch the paper, list your own asks. FastAPI over the `JobStore` issue #681
landed -- stateless, and small enough that nothing about retrieval,
composition or evidence lives here.

**The endpoints are jobs, not request/response** (DEC-65). An ask is ~3
minutes, so `POST /asks` writes a `queued` row and returns its id; a worker
process runs it. Nothing in this module ever calls the engine.

**`GET /asks/{id}/paper` serves the §7.3 analysis record** an ask produces
(`axial.answer.record.BriefRunResult.record`, persisted at the job's
`result_ref`), as JSON, for the client to render. That is what an ask
produces; the Phase-C paper is a separate pipeline that runs off an
analysis record. The route path is the issue's own and #687's client is
written against it.

**The record is rendered through this deployment's citation mode before it
is served** (issue #690, `axial.service.citation`): `locator` (the
default) serves the record exactly as persisted -- its `grounds` already
carry no passage text -- and `passage` additionally resolves each `chunk`
ground into a quoted `citation.quote`. The mode is `AXIAL_CITATION_MODE`,
resolved once at `create_app`, never a request field a client could set.

**`GET /asks/{id}/events` streams progress as Server-Sent Events** (issue
#683), replacing a client-side spinner with the same `on_event` narration
`axial ask` already prints (`axial.llm.emit_event`'s callers) -- the worker
persists each call via `JobStore.append_event`, this endpoint replays and
tails it, and `Last-Event-ID` makes a reconnect resume exactly rather than
missing or repeating an event.

**Pydantic lives here and nowhere else.** `src/axial` core is dataclasses
and dicts; the models below are the wire contract at this boundary, not a
record shape.

Auth is not in this issue (#685 built the request-path shape and the access
policy; #688 is where a token turns into a real, distinct principal).
`current_principal` is the identity seam: one FastAPI dependency, still
returning the single local `DEFAULT_PRINCIPAL` (`axial.context`) until #688
lands. `GET /asks` filters on it, and every by-id route below (`GET /asks/
{id}`, its `/events`, its `/paper`) now goes through `can_access`
(`axial.access`) rather than trusting that a query naturally excluded rows
that are not the caller's: a job id is guessable, so the refusal has to come
from the policy, not from an accident of how `JobStore.get` happens to be
called.

**`POST /asks` checks the caller's quota BEFORE `store.enqueue`** (issue
#686, `axial.service.quotas.QuotaStore`): an over-quota ask returns `429`
naming the window, the limit, and the exact UTC instant it resets, and
creates no job row at all -- the issue's own criterion. The content-keyed
paper cache that makes a duplicate ask free is NOT checked here: only the
worker holds the bound snapshot's pin (`axial.service.snapshot`), so a
cache hit still enqueues a `queued` row exactly like a miss and is resolved
in `axial.service.worker.run_ask_job` instead (that module's own docstring).
`AskStatus.cached` is `True` once the worker records a hit, so a client can
say the paper it is showing cost nothing to produce.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints

from axial.access import ANALYST, READ, WORK, Resource, can_access
from axial.context import DEFAULT_PRINCIPAL
from axial.paths import default_vault_dir
from axial.service.citation import render_record_for_serving, resolve_citation_mode
from axial.service.jobs import DONE, FAILED, JobStore
from axial.service.quotas import (
    QuotaStore,
    next_daily_reset,
    next_monthly_reset,
    start_of_day_utc,
    start_of_month_utc,
)

ASK_KIND = "ask"

# How often `GET /asks/{id}/events` polls the job row for a terminal state
# while it has no new event to send -- an ask can go quiet between events
# (retrieval's own walk narrates as it goes, but a stage boundary can still
# be silent for seconds), so the stream needs its own clock to notice `done`
# or `failed` rather than waiting on the next `on_event` call that may never
# come. One constant, in the style of `DEFAULT_HEARTBEAT_INTERVAL_SECONDS` --
# no caller has needed a different cadence.
EVENTS_POLL_INTERVAL_SECONDS = 0.5

# Blank-or-whitespace is rejected at the boundary rather than enqueued and
# left to fail in a worker three minutes later -- the same precondition
# `axial.ask.engine.ask` enforces (`BlankCaseError`/`BlankQuestionError`).
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def current_principal() -> str:
    """Who is asking. Still the single local analyst (`DEFAULT_PRINCIPAL`)
    until #688 lands a real identity provider behind this same dependency --
    #685's own scope is the request-path shape (`RequestContext`), the
    per-principal working set (`axial.paths`), and the access policy
    (`axial.access.can_access`) that consult it, not login itself."""
    return DEFAULT_PRINCIPAL


Principal = Annotated[str, Depends(current_principal)]


def _require_own_job(store: JobStore, ask_id: str, principal: str) -> dict[str, Any]:
    """The job at `ask_id`, only when `principal` may read it. `can_access`
    (`axial.access`, table-driven, in `disposition_for`'s own style) makes
    the call -- every request into this service is the `ANALYST` role, so a
    job owned by someone else is refused exactly as if it did not exist:
    guessing another analyst's id correctly proves nothing, because the
    refusal comes from the policy, never from `JobStore.get` merely never
    having been asked to filter."""
    job = _require_job(store, ask_id)
    if not can_access(principal, ANALYST, READ, Resource(WORK, owner=job["principal"])):
        raise HTTPException(status_code=404, detail=f"no ask with id {ask_id!r}")
    return job


class AskRequest(BaseModel):
    """A brief (§7.1) as it arrives over HTTP: the case and the request,
    plus the optional source weights, lens and session the analyst may
    supply. `weights` is the analyst's own instruction and is never
    inferred (DEC-61)."""

    case: NonBlank
    request: NonBlank
    weights: dict[str, float] | None = None
    lens: str | None = None
    session_id: str | None = None


class AskAccepted(BaseModel):
    id: str
    state: str


class AskStatus(BaseModel):
    """One job row as the client sees it: state, corpus pin, timings, and
    the result reference once it is done. `cached` (issue #686) is `True`
    once the worker has served this row from the content-keyed paper cache
    instead of calling the engine -- "marked as such" is the issue's own
    acceptance line, and this field is that mark."""

    id: str
    state: str
    corpus_pin: str | None = None
    cached: bool = False
    created_at: datetime
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    result_ref: str | None = None
    error: str | None = None


def _require_job(store: JobStore, ask_id: str) -> dict[str, Any]:
    job = store.get(ask_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no ask with id {ask_id!r}")
    return job


_WINDOW_LABEL = {"day": "daily", "month": "monthly"}


def _reject_quota_exceeded(window: str, limit: int, reset_at: datetime) -> None:
    """Raise the `429` the issue's third "done when" describes: a clear
    refusal naming the limit that was hit and the exact UTC instant it
    resets, worded so a UI can show it to an academic verbatim -- never a
    bare status code with no explanation."""
    raise HTTPException(
        status_code=429,
        detail={
            "message": (
                f"You've reached your {_WINDOW_LABEL[window]} limit of {limit} ask(s). "
                f"It resets at {reset_at.isoformat()} (UTC)."
            ),
            "window": window,
            "limit": limit,
            "reset_at": reset_at.isoformat(),
        },
    )


def _check_quota(store: JobStore, quotas: QuotaStore, principal: str) -> None:
    """Refuse `principal` before a job row is ever created (issue #686's
    own criterion) when either the daily or the monthly calendar-UTC window
    (`axial.service.quotas` module docstring) is already at its limit. The
    count comes from `JobStore.count_since`, which excludes a `cached` row
    -- a cache hit spends nothing, so it must never count against the
    budget that exists to bound spend.

    All three reads (limits, daily count, monthly count) share ONE physical
    connection (`store.connection()`) -- `POST /asks` has its own <100ms
    budget (`test_api_under_load.py`), and three separate `psycopg.connect()`
    calls measured ~25ms each on this stack; batched onto one, this check
    costs roughly what one of them used to.

    **Not atomic.** This reads the count, then returns; nothing locks the
    window between the read here and the `store.enqueue` call after it, so
    two simultaneous requests from the same principal can both read
    `limit - 1` and both pass, landing the window one-or-a-few over its
    stated limit -- bounded by how many requests are genuinely concurrent
    at that instant, never unbounded. Acceptable as shipped: a quota here
    is an economic guardrail, not a security boundary. A `SELECT ... FOR
    UPDATE` scoped to `principal`, or folding the count and the enqueue
    into one serializable transaction, would close this if it ever
    mattered."""
    now = datetime.now(timezone.utc)
    with store.connection() as conn:
        limits = quotas.limits_for(principal, conn=conn)
        daily_count = store.count_since(
            principal, kind=ASK_KIND, since=start_of_day_utc(now), conn=conn
        )
        monthly_count = store.count_since(
            principal, kind=ASK_KIND, since=start_of_month_utc(now), conn=conn
        )
    if daily_count >= limits.daily:
        _reject_quota_exceeded("day", limits.daily, next_daily_reset(now))
    if monthly_count >= limits.monthly:
        _reject_quota_exceeded("month", limits.monthly, next_monthly_reset(now))


def _sse_frame(*, seq: int | None, data: dict[str, Any]) -> str:
    """One SSE frame. `seq`, when given, is the `id:` line a reconnecting
    client's `Last-Event-ID` header names to resume after -- omitted for the
    synthetic final frame a failed job emits, which is not a stored,
    replayable event."""
    lines = [] if seq is None else [f"id: {seq}"]
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


def _drain(store: JobStore, ask_id: str, last_seq: int) -> tuple[list[str], int]:
    """Every event past `last_seq`, as SSE frames, plus the new `last_seq`
    past them. A plain function rather than inline in `_event_stream` so the
    terminal branch below can call it a second time without repeating the
    loop body."""
    frames = []
    for event in store.events_since(ask_id, last_seq):
        last_seq = event["seq"]
        frames.append(
            _sse_frame(seq=last_seq, data={"message": event["message"], "detail": event["detail"]})
        )
    return frames, last_seq


def _event_stream(store: JobStore, ask_id: str, after_seq: int) -> Iterator[str]:
    """Replay every event past `after_seq`, then keep polling and tailing
    until the job reaches a terminal state (module docstring on the poll
    constant).

    The worker's last `on_event` call and its `store.complete`/`store.fail`
    land back-to-back, so the state read below can observe `done`/`failed`
    before this generator has re-read the event that call just wrote --
    `_drain` runs once more after the state read to close exactly that
    window, rather than trusting the read that raced it. `done` then closes
    with no extra frame; `failed` sends the job's error as one final,
    unstored frame after that drain, so the error stays the last thing the
    stream sends."""
    last_seq = after_seq
    while True:
        frames, last_seq = _drain(store, ask_id, last_seq)
        yield from frames

        job = store.get(ask_id)
        if job is not None and job["state"] not in (DONE, FAILED):
            time.sleep(EVENTS_POLL_INTERVAL_SECONDS)
            continue

        if job is not None:
            frames, last_seq = _drain(store, ask_id, last_seq)
            yield from frames
            if job["state"] == FAILED:
                yield _sse_frame(
                    seq=None, data={"message": job["error"], "detail": {"error": job["error"]}}
                )
        return


def create_app(
    store: JobStore,
    quotas: QuotaStore | None = None,
    *,
    citation_mode: str | None = None,
    vault_dir: Path | None = None,
) -> FastAPI:
    """Build the app over `store`. The store is an argument rather than a
    module global so a test drives the same app the deployment does.

    `quotas` (issue #686) defaults to a `QuotaStore` over `store`'s own DSN
    (`JobStore.dsn`) -- a caller that only ever passed a `JobStore` before
    this parameter existed still gets quota enforcement for free, with the
    environment's default limits (`axial.service.quotas` module docstring).
    Its schema is created here, unconditionally: unlike `jobs`/`job_events`
    (left to a fixture or an ops migration, matching the pre-existing
    convention), a `quotas` table is new enough, and this check runs on
    EVERY `POST /asks`, that not creating it here would break every existing
    caller of `create_app(store)` the moment this issue landed.

    `citation_mode` (issue #690) defaults to `AXIAL_CITATION_MODE`
    (`axial.service.citation.resolve_citation_mode`), resolved and
    validated HERE, at app construction -- an unrecognised value is a
    startup error naming the two valid modes, never a silent fallback to
    `locator`. `vault_dir` is where `GET /asks/{id}/paper` reads
    `notes.db`/prose from to resolve a citation (`axial.service.citation`);
    `None` (the default here, always the case in a test that does not pass
    one) means no resolution happens and every ground is served exactly as
    the record already had it -- `locator` mode's own "no book text" bar is
    already met by the untouched record (that module's docstring), so this
    is a silent no-op, not a startup error. `app()` below supplies the real
    default."""
    citation_mode = resolve_citation_mode(citation_mode)
    if quotas is None:
        quotas = QuotaStore(store.dsn)
    quotas.create_schema()

    app = FastAPI(title="Axial analyst service")

    @app.post("/asks", status_code=202, response_model=AskAccepted)
    def submit_ask(ask: AskRequest, principal: Principal) -> AskAccepted:
        """Queue an ask and return its id. Does not run it. Refuses with
        `429` before enqueuing anything when `principal` is over quota
        (module docstring, `_check_quota`)."""
        _check_quota(store, quotas, principal)
        job_id = store.enqueue(
            kind=ASK_KIND,
            principal=principal,
            payload={
                "case": ask.case,
                "question": ask.request,
                "weights": ask.weights,
                "lens": ask.lens,
                "session_id": ask.session_id,
            },
        )
        return AskAccepted(id=job_id, state="queued")

    @app.get("/asks", response_model=list[AskStatus])
    def list_asks(principal: Principal) -> list[AskStatus]:
        return [AskStatus(**job) for job in store.list_for_principal(principal)]

    @app.get("/asks/{ask_id}", response_model=AskStatus)
    def get_ask(ask_id: str, principal: Principal) -> AskStatus:
        return AskStatus(**_require_own_job(store, ask_id, principal))

    @app.get("/asks/{ask_id}/events")
    def stream_events(ask_id: str, request: Request, principal: Principal) -> StreamingResponse:
        """Server-Sent Events over the job's `on_event` history (issue
        #683): every missed event first, on connect or reconnect, then live
        ones on the same response, until the job reaches a terminal state.
        `Last-Event-ID` (SSE's own reconnect header) is where a client
        resumes from -- absent, or unparseable, is treated as `0`, a fresh
        connection starting from the beginning."""
        _require_own_job(store, ask_id, principal)
        try:
            after_seq = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            after_seq = 0
        return StreamingResponse(
            _event_stream(store, ask_id, after_seq), media_type="text/event-stream"
        )

    @app.get("/asks/{ask_id}/paper")
    def get_paper(ask_id: str, principal: Principal) -> dict[str, Any]:
        """The finished ask's §7.3 analysis record, as JSON (module
        docstring), rendered through this deployment's own citation mode
        (issue #690, `axial.service.citation.render_record_for_serving`) --
        the record on disk never carries a quote either way, so `locator`
        mode returns it untouched and `passage` mode adds one."""
        job = _require_own_job(store, ask_id, principal)
        if job["state"] != DONE:
            raise HTTPException(
                status_code=409, detail=f"ask {ask_id!r} is {job['state']}, not finished"
            )
        record = json.loads(Path(job["result_ref"]).read_text(encoding="utf-8"))
        return render_record_for_serving(record, citation_mode=citation_mode, vault_dir=vault_dir)

    return app


def app() -> FastAPI:
    """The deployment entry point: `uvicorn axial.service.api:app
    --factory`. `DATABASE_URL` is the one setting, the same variable
    `tests/service/conftest.py` already honours; the quota env vars are
    `axial.service.quotas`'s own (`AXIAL_QUOTA_ASKS_PER_DAY`/`_MONTH`); the
    citation mode is `AXIAL_CITATION_MODE` (`axial.service.citation`).

    `vault_dir` (issue #690) is `axial.paths.default_vault_dir()` -- the
    same `config/pipeline.yaml`-relative-to-cwd convention every other read
    in this codebase already resolves through, so a deployment that mounts
    a published snapshot at this process's cwd (matching how a worker binds
    to one, `axial.service.snapshot.Snapshot.bind`) resolves citations with
    no second path to configure. Flipping `AXIAL_CITATION_MODE=passage`
    genuinely needs no code change here -- it needs that mount, a
    deployment detail #691 wires, not a setting this factory adds."""
    dsn = os.environ["DATABASE_URL"]
    return create_app(JobStore(dsn), QuotaStore(dsn), vault_dir=default_vault_dir())
