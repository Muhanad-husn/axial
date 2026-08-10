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

**`GET /asks/{id}/events` streams progress as Server-Sent Events** (issue
#683), replacing a client-side spinner with the same `on_event` narration
`axial ask` already prints (`axial.llm.emit_event`'s callers) -- the worker
persists each call via `JobStore.append_event`, this endpoint replays and
tails it, and `Last-Event-ID` makes a reconnect resume exactly rather than
missing or repeating an event.

**Pydantic lives here and nowhere else.** `src/axial` core is dataclasses
and dicts; the models below are the wire contract at this boundary, not a
record shape.

Auth is not in this issue. `current_principal` is the whole identity seam:
one FastAPI dependency returning a single local user, which issue #685
replaces with real identity. `GET /asks` filters on it today -- with one
principal that is every row, but the filter is where it will be when there
is more than one.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints

from axial.service.jobs import DONE, FAILED, JobStore

ASK_KIND = "ask"

# How often `GET /asks/{id}/events` polls the job row for a terminal state
# while it has no new event to send -- an ask can go quiet between events
# (retrieval's own walk narrates as it goes, but a stage boundary can still
# be silent for seconds), so the stream needs its own clock to notice `done`
# or `failed` rather than waiting on the next `on_event` call that may never
# come. One constant, in the style of `DEFAULT_HEARTBEAT_INTERVAL_SECONDS` --
# no caller has needed a different cadence.
EVENTS_POLL_INTERVAL_SECONDS = 0.5

# The single local user every request is until issue #685 lands real
# identity.
DEFAULT_PRINCIPAL = "local-analyst"

# Blank-or-whitespace is rejected at the boundary rather than enqueued and
# left to fail in a worker three minutes later -- the same precondition
# `axial.ask.engine.ask` enforces (`BlankCaseError`/`BlankQuestionError`).
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def current_principal() -> str:
    """Who is asking. Issue #685 replaces this dependency with real
    identity; until then every request is the same local analyst."""
    return DEFAULT_PRINCIPAL


Principal = Annotated[str, Depends(current_principal)]


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
    the result reference once it is done."""

    id: str
    state: str
    corpus_pin: str | None = None
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


def _sse_frame(*, seq: int | None, data: dict[str, Any]) -> str:
    """One SSE frame. `seq`, when given, is the `id:` line a reconnecting
    client's `Last-Event-ID` header names to resume after -- omitted for the
    synthetic final frame a failed job emits, which is not a stored,
    replayable event."""
    lines = [] if seq is None else [f"id: {seq}"]
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


def _event_stream(store: JobStore, ask_id: str, after_seq: int) -> Iterator[str]:
    """Replay every event past `after_seq`, then keep polling and tailing
    until the job reaches a terminal state (module docstring on the poll
    constant). `done` closes with no extra frame; `failed` sends the job's
    error as one final, unstored frame so the stream ends with the failure
    rather than hanging on an event that will never arrive."""
    last_seq = after_seq
    while True:
        for event in store.events_since(ask_id, last_seq):
            last_seq = event["seq"]
            yield _sse_frame(
                seq=last_seq, data={"message": event["message"], "detail": event["detail"]}
            )

        job = store.get(ask_id)
        if job is None or job["state"] == DONE:
            return
        if job["state"] == FAILED:
            yield _sse_frame(
                seq=None, data={"message": job["error"], "detail": {"error": job["error"]}}
            )
            return

        time.sleep(EVENTS_POLL_INTERVAL_SECONDS)


def create_app(store: JobStore) -> FastAPI:
    """Build the app over `store`. The store is an argument rather than a
    module global so a test drives the same app the deployment does."""
    app = FastAPI(title="Axial analyst service")

    @app.post("/asks", status_code=202, response_model=AskAccepted)
    def submit_ask(ask: AskRequest, principal: Principal) -> AskAccepted:
        """Queue an ask and return its id. Does not run it."""
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
    def get_ask(ask_id: str) -> AskStatus:
        return AskStatus(**_require_job(store, ask_id))

    @app.get("/asks/{ask_id}/events")
    def stream_events(ask_id: str, request: Request) -> StreamingResponse:
        """Server-Sent Events over the job's `on_event` history (issue
        #683): every missed event first, on connect or reconnect, then live
        ones on the same response, until the job reaches a terminal state.
        `Last-Event-ID` (SSE's own reconnect header) is where a client
        resumes from -- absent, or unparseable, is treated as `0`, a fresh
        connection starting from the beginning."""
        _require_job(store, ask_id)
        try:
            after_seq = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            after_seq = 0
        return StreamingResponse(
            _event_stream(store, ask_id, after_seq), media_type="text/event-stream"
        )

    @app.get("/asks/{ask_id}/paper")
    def get_paper(ask_id: str) -> dict[str, Any]:
        """The finished ask's §7.3 analysis record, as JSON (module
        docstring). A job that has not reached `done` has no record to
        serve, so it is a 409 naming the state it is actually in rather
        than an empty 200."""
        job = _require_job(store, ask_id)
        if job["state"] != DONE:
            raise HTTPException(
                status_code=409, detail=f"ask {ask_id!r} is {job['state']}, not finished"
            )
        return json.loads(Path(job["result_ref"]).read_text(encoding="utf-8"))

    return app


def app() -> FastAPI:
    """The deployment entry point: `uvicorn axial.service.api:app
    --factory`. `DATABASE_URL` is the one setting, the same variable
    `tests/service/conftest.py` already honours."""
    return create_app(JobStore(os.environ["DATABASE_URL"]))
