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

**The response carries the record and a `metrics` block beside it, never
merged into one** (issue #724): `{"record": ..., "metrics": {...}}`. The
metrics block is exactly the four fields the §7.3 record already carries
-- `cost`, `model_by_pass`, `coverage_map`, `confidence` -- pulled out
into their own sibling key so #687's client reads them without hunting
through `record` for which top-level keys are "the answer" and which are
"the bill." `retries` and a shape band are Phase-C-only
(`src/axial/paper/record.py`) and are never served here: an ask is not a
paper run, and chaining a paper draft onto every ask to manufacture them
would turn a ~$0.13 ask into a paper run nobody asked for. `GET
/asks/{id}/export` (below) reuses this same pair.

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

**`current_principal` verifies a Supabase-issued JWT** (issue #763): the
identity seam #685 built this dependency to be, now reading the
`Authorization: Bearer` header, verifying it (`axial.service.auth.
verify_bearer_token` -- JWKS, asymmetric, `AXIAL_SUPABASE_JWKS_URL` the one
setting, no shared-secret path), and returning the token's own verified
subject. A missing, malformed, expired or wrongly-signed token, or one
whose subject fails the identity edge's own shape check, is `401` from this
dependency -- refused before any route body runs, before the job store is
opened. With `AXIAL_SUPABASE_JWKS_URL` unset, every request is `401`:
unconfigured means closed here, the opposite default direction from
`AXIAL_CITATION_MODE` below. There is no dev-principal environment
escape hatch; `tests/service` instead overrides this dependency with
`app.dependency_overrides[current_principal]`, the FastAPI-native seam,
adding no production surface. `GET /asks` filters on the resolved
principal, and every by-id route below (`GET /asks/{id}`, its `/events`,
its `/paper`) goes through `can_access` (`axial.access`) rather than
trusting that a query naturally excluded rows that are not the caller's: a
job id is guessable, so the refusal has to come from the policy, not from
an accident of how `JobStore.get` happens to be called.

**Invitation-only is Supabase's own switch, not a second list here**: public
sign-up is disabled in the Supabase project and the operator invites an
email by hand. The service carries no parallel email allowlist -- two gates
that must agree is exactly the config nobody sets. A deployment that leaves
public sign-up on is an open door; that is a deployment-time decision, not
one this module can see or close.

**`GET`/`PUT /me/profile` carry the caller's own theme** (issue #763, the
founder's own comment on #688): a `profiles` table beside `jobs` and
`quotas` (`axial.service.profiles.ProfileStore`), keyed by principal, with
`theme` constrained to `light`/`dark`/`system` (default `system`) by the
table's own `CHECK` constraint. A principal with no row yet reads the
default rather than a `404` -- the first sign-in should not need a write
before a read works.

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

**`GET /me/usage` reports cost, tokens and quota state for the caller**
(issue #724, semantics from #686): a `month_to_date` block always present,
and an optional `session` block when `session_id` is given as a query
parameter -- the server holds no notion of a "current" session, so a
client that wants one names it itself. Both blocks carry the same four
figures: `cost_usd` (`JobStore.sum_spend_for_principal`, `None`-preserving
-- unknown is never rendered or summed as `$0.00`), `tokens`
(`JobStore.sum_tokens_for_principal`, the same rule), `asks_made` (every
ask, `JobStore.count_since(..., exclude_cached=False)`) and
`asks_charged` (the same count with a cache hit excluded -- what a quota
window actually counts). The founder's own naming: "asks made" and "asks
charged against quota" are two different counts, and a client that reads
one while it is labelled the other would misreport an analyst's own cache
hits as consuming their budget. `quota` reuses exactly what the `429`
path already assembles (`QuotaStore.limits_for`, `count_since` over the
calendar-UTC day window, `next_daily_reset`/`next_monthly_reset`) -- no
new query for the numbers `_check_quota` already knows how to read, and
`quota["month"].used` is `month_to_date.asks_charged` itself, not a second
count of the same window.

**`GET /asks/{id}/export?format=md|docx|odt` serves the brief, the
rendered answer and the metrics block as one file** (issue #724,
`axial.service.export`): markdown is the one rendering path, and `docx`/
`odt` are converted from that same markdown string, never re-derived from
the record. Exporting is free -- no model call, no job row touched, no
quota consulted -- and goes through `_require_own_job` exactly like every
other by-id route, so an export is exactly as private as the paper it
comes from. The citation mode applies here too, for the same reason it
applies to `GET /asks/{id}/paper`: the record this route renders is the
SAME already-mode-rendered record that route serves, so a `locator`
deployment's export carries no book text either.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, StringConstraints

from axial.access import ANALYST, READ, WORK, Resource, can_access
from axial.context import (
    DEFAULT_PRINCIPAL,  # noqa: F401 -- re-exported; tests/service imports it from here
)
from axial.paths import default_vault_dir
from axial.service.auth import verify_bearer_token
from axial.service.citation import render_record_for_serving, resolve_citation_mode
from axial.service.export import (
    EXPORT_FORMATS,
    metrics_block,
    render_docx,
    render_export_markdown,
    render_odt,
)
from axial.service.jobs import DONE, FAILED, JobStore
from axial.service.profiles import ProfileStore
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


# `auto_error=False`: a missing header is handled below as the same `401`
# every other verification failure gets, rather than `HTTPBearer`'s own
# generic "not authenticated" body -- one refusal shape for this whole
# dependency, not two.
_bearer_scheme = HTTPBearer(auto_error=False)


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> str:
    """Who is asking (issue #763): the verified `sub` of a Supabase-issued
    JWT presented as `Authorization: Bearer <token>` (module docstring,
    `axial.service.auth.verify_bearer_token`). A missing, malformed,
    expired or wrongly-signed token, or a subject that fails the identity
    edge's own shape check, is `401` -- this is the seam #685 built and
    #688/#763 fill in, not a second place `RequestContext`, `axial.paths`
    or `axial.access.can_access` need to change for."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    return verify_bearer_token(credentials.credentials)


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
    acceptance line, and this field is that mark.

    `case`/`question` (issue #759) are the brief that produced this row,
    read off the job's own payload (`POST /asks` writes it at `enqueue`
    time) rather than the finished analysis record -- a `queued`, `running`
    or `failed` row has no record yet, but it always has the payload it was
    enqueued with. This is additive: every existing consumer of this shape
    (`web/src/lib/api.ts`, `tests/service/`) reads a strict superset of what
    it already read."""

    id: str
    state: str
    case: str | None = None
    question: str | None = None
    corpus_pin: str | None = None
    cached: bool = False
    created_at: datetime
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    result_ref: str | None = None
    error: str | None = None


def _ask_status(job: dict[str, Any]) -> AskStatus:
    """Build the served `AskStatus` for one job row, pulling `case`/
    `question` out of `job["payload"]` (issue #759) -- the brief this
    principal's own request enqueued, present on every row regardless of
    state, unlike the analysis record `GET /asks/{id}/paper` only has once
    a job is `done`."""
    payload = job.get("payload") or {}
    return AskStatus(**job, case=payload.get("case"), question=payload.get("question"))


def _require_job(store: JobStore, ask_id: str) -> dict[str, Any]:
    job = store.get(ask_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no ask with id {ask_id!r}")
    return job


class UsageWindow(BaseModel):
    """One usage window's own four figures (issue #724, `GET /me/usage`):
    `cost_usd`/`tokens` are `None`-preserving sums (`JobStore.
    sum_spend_for_principal`/`sum_tokens_for_principal`) -- unknown, never
    rendered as a zero. `asks_made` counts every ask in the window,
    `asks_charged` excludes a cache hit -- two different counts, named so
    neither can be mislabelled as the other (the founder's own line)."""

    cost_usd: float | None
    tokens: int | None
    asks_made: int
    asks_charged: int


class QuotaWindowStatus(BaseModel):
    """One quota window's limit, how much of it this UTC window has used
    (`JobStore.count_since`, cache hits excluded -- the same count a
    quota check itself makes), and the exact instant it resets."""

    limit: int
    used: int
    reset_at: datetime


class UsageResponse(BaseModel):
    """`GET /me/usage`'s whole body: the caller's own principal, an
    optional `session` window (present only when the caller supplied a
    `session_id`, since the server holds no notion of a "current"
    session), the `month_to_date` window that is always present, and
    `quota` -- the same limits and calendar-UTC usage the `429` path on
    `POST /asks` already assembles."""

    principal: str
    session: UsageWindow | None
    month_to_date: UsageWindow
    quota: dict[str, QuotaWindowStatus]


class ProfileResponse(BaseModel):
    """`GET`/`PUT /me/profile`'s own body (issue #763): the caller's own
    theme, `system` by default (`axial.service.profiles.DEFAULT_THEME`) for
    a principal that has never written one."""

    theme: str


class ProfileUpdate(BaseModel):
    """`PUT /me/profile`'s request body. `Literal` rejects anything but the
    three allowed values with a `422` at the boundary, ahead of the
    `profiles` table's own `CHECK` constraint (`axial.service.profiles`
    module docstring) -- the same value is validated at both, deliberately,
    since a bad value from either seam should never reach the other
    silently."""

    theme: Literal["light", "dark", "system"]


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
            # A stage can stay quiet for 40-55s on a real ask (issue #751) --
            # long enough that a browser, a proxy, or Vercel's edge reaps a
            # connection with no bytes on it well before the job has anything
            # new to say. An SSE comment frame is the wire convention for
            # exactly this: the client's own parser drops any line with no
            # `data:`, so this is invisible to `parseFrames`/`EventSource`
            # and carries no `id:`, so it can never collide with a real seq.
            yield ": keepalive\n\n"
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
    profiles: ProfileStore | None = None,
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
    default.

    `profiles` (issue #763) defaults to a `ProfileStore` over `store`'s own
    DSN, the same "a caller that only ever passed a `JobStore` still gets
    it for free" rule `quotas` above already follows; its schema is created
    here, unconditionally, for the same reason `quotas`'s is."""
    citation_mode = resolve_citation_mode(citation_mode)
    if quotas is None:
        quotas = QuotaStore(store.dsn)
    quotas.create_schema()
    if profiles is None:
        profiles = ProfileStore(store.dsn)
    profiles.create_schema()

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
        return [_ask_status(job) for job in store.list_for_principal(principal)]

    @app.get("/asks/{ask_id}", response_model=AskStatus)
    def get_ask(ask_id: str, principal: Principal) -> AskStatus:
        return _ask_status(_require_own_job(store, ask_id, principal))

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

    def _paper_payload(ask_id: str, principal: str) -> dict[str, Any]:
        """The finished ask's §7.3 analysis record, rendered through this
        deployment's own citation mode (issue #690,
        `axial.service.citation.render_record_for_serving` -- the record on
        disk never carries a quote either way, so `locator` mode returns it
        untouched and `passage` mode adds one), plus the metrics block
        pulled out beside it (issue #724, `axial.service.export.
        metrics_block`). Shared by `GET /asks/{id}/paper` and `GET
        /asks/{id}/export` so the two routes can never disagree on what
        "the record" or "the metrics" are."""
        job = _require_own_job(store, ask_id, principal)
        if job["state"] != DONE:
            raise HTTPException(
                status_code=409, detail=f"ask {ask_id!r} is {job['state']}, not finished"
            )
        record = json.loads(Path(job["result_ref"]).read_text(encoding="utf-8"))
        record = render_record_for_serving(record, citation_mode=citation_mode, vault_dir=vault_dir)
        return {"record": record, "metrics": metrics_block(record)}

    @app.get("/asks/{ask_id}/paper")
    def get_paper(ask_id: str, principal: Principal) -> dict[str, Any]:
        """The finished ask's §7.3 analysis record and its metrics block,
        as `{"record": ..., "metrics": ...}` (module docstring, issue
        #724) -- the metrics block sits beside the record, never merged
        into it, so a client reads the two without ambiguity."""
        return _paper_payload(ask_id, principal)

    def _usage_window(
        principal: str, *, since: datetime | None, session_id: str | None
    ) -> UsageWindow:
        return UsageWindow(
            cost_usd=store.sum_spend_for_principal(principal, since=since, session_id=session_id),
            tokens=store.sum_tokens_for_principal(principal, since=since, session_id=session_id),
            asks_made=store.count_since(
                principal,
                kind=ASK_KIND,
                since=since,
                session_id=session_id,
                exclude_cached=False,
            ),
            asks_charged=store.count_since(
                principal, kind=ASK_KIND, since=since, session_id=session_id
            ),
        )

    @app.get("/me/usage", response_model=UsageResponse)
    def get_usage(principal: Principal, session_id: str | None = None) -> UsageResponse:
        """Cost, tokens and quota state for the caller (module docstring,
        issue #724). `session_id`, when given as a query parameter, adds a
        `session` window scoped to that id alone (no time bound) -- this
        server has no notion of a "current" session, so a client that
        wants one names it. `month_to_date` is always present."""
        now = datetime.now(timezone.utc)
        session = (
            _usage_window(principal, since=None, session_id=session_id)
            if session_id is not None
            else None
        )
        month_to_date = _usage_window(principal, since=start_of_month_utc(now), session_id=None)
        with store.connection() as conn:
            limits = quotas.limits_for(principal, conn=conn)
            daily_used = store.count_since(
                principal, kind=ASK_KIND, since=start_of_day_utc(now), conn=conn
            )
        return UsageResponse(
            principal=principal,
            session=session,
            month_to_date=month_to_date,
            quota={
                "day": QuotaWindowStatus(
                    limit=limits.daily, used=daily_used, reset_at=next_daily_reset(now)
                ),
                "month": QuotaWindowStatus(
                    limit=limits.monthly,
                    # The same count as `month_to_date.asks_charged` above --
                    # both are "asks charged against quota this calendar
                    # month" -- reused rather than a second `count_since`
                    # call for the identical window.
                    used=month_to_date.asks_charged,
                    reset_at=next_monthly_reset(now),
                ),
            },
        )

    @app.get("/me/profile", response_model=ProfileResponse)
    def get_profile(principal: Principal) -> ProfileResponse:
        """The caller's own theme (issue #763), `system` when they have
        never written one (`ProfileStore.theme_for`'s own default) --
        never a `404`, so a first sign-in can read before it ever writes."""
        return ProfileResponse(theme=profiles.theme_for(principal))

    @app.put("/me/profile", response_model=ProfileResponse)
    def put_profile(update: ProfileUpdate, principal: Principal) -> ProfileResponse:
        """Write the caller's own theme and echo it back. Scoped to the
        caller by construction -- `principal` is this dependency's own
        verified subject, never a field on the request body, so one
        analyst can never write another's row."""
        profiles.set_theme(principal, update.theme)
        return ProfileResponse(theme=update.theme)

    @app.get("/asks/{ask_id}/export")
    def export_paper(ask_id: str, principal: Principal, format: str = "md") -> Response:
        """The brief, the rendered answer and the metrics block as one
        downloadable file (module docstring, issue #724,
        `axial.service.export`). Free: no model call, no job row touched,
        no quota consulted -- `_paper_payload` above is a read of an
        already-persisted record, the same one `GET /asks/{id}/paper`
        reads."""
        if format not in EXPORT_FORMATS:
            raise HTTPException(
                status_code=422, detail=f"format must be one of {EXPORT_FORMATS!r}, got {format!r}"
            )
        payload = _paper_payload(ask_id, principal)
        markdown_text = render_export_markdown(payload["record"], payload["metrics"])
        if format == "md":
            content: bytes = markdown_text.encode("utf-8")
            media_type = "text/markdown; charset=utf-8"
        elif format == "docx":
            content = render_docx(markdown_text)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            content = render_odt(markdown_text)
            media_type = "application/vnd.oasis.opendocument.text"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{ask_id}.{format}"'},
        )

    return app


def app() -> FastAPI:
    """The deployment entry point: `uvicorn axial.service.api:app
    --factory`. `DATABASE_URL` is the one setting, the same variable
    `tests/service/conftest.py` already honours; the quota env vars are
    `axial.service.quotas`'s own (`AXIAL_QUOTA_ASKS_PER_DAY`/`_MONTH`); the
    citation mode is `AXIAL_CITATION_MODE` (`axial.service.citation`); token
    verification is `AXIAL_SUPABASE_JWKS_URL` (issue #763,
    `axial.service.auth`) -- unset means every request is `401`, so a
    deployment that forgets it fails closed rather than serving one shared
    account.

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
