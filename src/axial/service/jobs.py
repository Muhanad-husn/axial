"""The job store (issue #681): a `jobs` table in Postgres that an ask (and,
later, a chat-mode turn -- the module docstring in
`plans/multiuser-analyst-service/README.md`'s 2026-08-05 amendment) is
queued into, a worker claims out of, and that ends in a terminal `done` or
`failed` record.

Claiming is `SELECT ... FOR UPDATE SKIP LOCKED` (the issue's own
requirement): two workers racing the same queue take a row lock each on
their own transaction, and Postgres skips any row another transaction
already has locked rather than blocking on it, so two workers never claim
the same row and neither ever waits on the other. No broker, no queue
library -- Postgres already does this correctly at the scale this needs.

`kind` exists from day one even though `"ask"` is the only value written
today: the issue is explicit that this is deliberate generality, so that a
second job kind (chat mode) reuses this table later instead of a migration
on live rows.

`job_events` (issue #683) is a second, append-only table beside `jobs`: one
row per `on_event(message, detail)` call the engine makes while a job runs,
keyed by a monotonic per-job `seq`. It lives in Postgres rather than a file
because the API and the worker are separate processes -- under #691,
separate containers -- so nothing but the database is guaranteed shared
between them.

`cached` and `cost_usd` (issue #686) are two more facts a completed row
carries. `cached` defaults `FALSE` and is set `TRUE` only when
`axial.service.worker.run_ask_job` served the row from the content-keyed
paper cache (`axial.service.cache.PaperCache`) instead of calling the
engine -- what `count_since` excludes from a quota window's count, since a
cache hit spends nothing. `cost_usd` is the run's own `record["cost"]
["total_usd"]` (§7.14): `None`-preserving for an unpriced model's pass,
`0.0` (a real, known zero) on a cache hit -- the two must never collapse
into each other, which is why `sum_spend_for_principal` below leans on
SQL's own `NULL`-skipping `SUM` rather than coercing anything itself.

`tokens` (issue #724) is a fourth fact, added for `GET /me/usage`: the
run's own total token count, summed by `axial.service.worker.run_ask_job`
across `record["cost"]["by_pass"]` -- the same dict `cost_usd` is already
read from, never a second read of the record. Same null-preserving rule as
`cost_usd`: `None` when the record carried no `cost` block at all (an
unpriced or uncaptured run), a real `0` on a cache hit (this job made no
model call, so it used none of its own), never coerced into each other.

`paper_ref` (issue #784) is where the Phase-C essay this ask ended in was
written -- the analogue of `result_ref` for the paper, set by
`axial.service.worker.run_ask_job` through `set_paper_ref` while the job is
still running rather than travelling in `JobRunner`'s return tuple. It is
nullable, and a `done` row with no `paper_ref` is a real outcome, not a
missing write: a refused ask drafts no paper and a drafting failure leaves
the analysis standing without one. The path is recorded rather than derived
at serve time, because a follow-up turn's thesis is the question the
analyst typed while its record's own `request` carries the previous turn
folded in -- the two hash to different `paper_brief_id`s, so a recomputed
filename would miss, silently, and look correct.

`count_since` and `sum_spend_for_principal` both grew two optional filters
for issue #724's usage endpoint: `session_id` (`payload->>'session_id'`,
a session is identified by that id alone, never a time window) and, on
`count_since`, `exclude_cached` (default `True`, preserving every existing
caller's behaviour) -- `GET /me/usage` needs the OPPOSITE count too
("asks made" including a cache hit, versus "asks charged against quota"
excluding one, the founder's own naming), which no existing caller of
this method has ever needed before.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

# The staleness bound `reclaim_stale` uses when a caller doesn't supply its
# own: how long a `running` job's heartbeat may go silent before its worker
# is presumed dead and the row goes back to the queue. One constant, not a
# config system -- callers that need a different bound (tests proving the
# reclaim path without a real multi-minute wait) pass their own.
DEFAULT_STALE_AFTER_SECONDS = 120.0

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    principal TEXT NOT NULL,
    payload JSONB NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    result_ref TEXT,
    error TEXT,
    corpus_pin TEXT
);
CREATE TABLE IF NOT EXISTS job_events (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    message TEXT NOT NULL,
    detail JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, seq)
);
-- Added by issue #686, after `jobs` already existed in deployed databases --
-- `ADD COLUMN IF NOT EXISTS` upgrades an existing table the same
-- `CREATE TABLE IF NOT EXISTS` above only handles for a fresh one.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cached BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION;
-- Added by issue #724, after both columns above already existed in
-- deployed databases -- same idiom, same reason.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tokens BIGINT;
-- Added by issue #784: where the Phase-C paper this ask ends in was
-- written. Nullable, because a refused ask drafts none and a drafting
-- failure leaves the analysis standing without one -- same idiom again.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS paper_ref TEXT;
"""

_COLUMNS = (
    "id, kind, principal, payload, state, created_at, "
    "claimed_at, heartbeat_at, finished_at, result_ref, error, corpus_pin, "
    "cached, cost_usd, tokens, paper_ref"
)


class JobStore:
    """A thin wrapper over the `jobs` table. Every method opens its own
    connection and commits (or rolls back, on an exception propagating out
    of a `with` block) before returning -- there is no long-lived shared
    connection or pool here, matching the scale the issue names (hundreds of
    concurrent jobs, not thousands of requests a second)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @property
    def dsn(self) -> str:
        """The Postgres connection string this store was built with -- a
        composition-root convenience (issue #686) so a caller building a
        small sibling store over the same database
        (`axial.service.quotas.QuotaStore`, `axial.service.cache.
        PaperCache`) doesn't need its own copy of the setting."""
        return self._dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """One physical connection to this store's database, for a caller
        that needs to batch more than one call onto it (issue #686:
        `axial.service.api._check_quota` reads a principal's limits and
        both its usage windows before every `POST /asks`, and each fresh
        `psycopg.connect()` measured ~25ms on this stack -- three of those
        alone would burn most of that route's own <100ms budget). Every
        other method on this class still opens and closes its own
        connection; this is only for a caller batching several of them."""
        with psycopg.connect(self._dsn) as conn:
            yield conn

    def create_schema(self) -> None:
        """Create the `jobs` and `job_events` tables if they do not already
        exist. Idempotent, so a worker or a test fixture can call it
        unconditionally on startup."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(_SCHEMA_SQL)

    def enqueue(self, *, kind: str, principal: str, payload: dict[str, Any]) -> str:
        """Insert one `queued` row and return its id."""
        job_id = uuid.uuid4().hex
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO jobs (id, kind, principal, payload, state) "
                "VALUES (%s, %s, %s, %s, %s)",
                (job_id, kind, principal, Jsonb(payload), QUEUED),
            )
        return job_id

    def claim(self) -> dict[str, Any] | None:
        """Claim the oldest `queued` row and mark it `running`, or return
        `None` when the queue is empty. `SELECT ... FOR UPDATE SKIP LOCKED`
        inside one transaction (module docstring) is what makes two
        concurrent callers never claim the same row."""
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM jobs "
                "WHERE state = %s ORDER BY created_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1",
                (QUEUED,),
            ).fetchone()
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            conn.execute(
                "UPDATE jobs SET state = %s, claimed_at = %s, heartbeat_at = %s WHERE id = %s",
                (RUNNING, now, now, row["id"]),
            )
            row["state"] = RUNNING
            row["claimed_at"] = now
            row["heartbeat_at"] = now
            return row

    def heartbeat(self, job_id: str) -> None:
        """Refresh `heartbeat_at` for a `running` job -- a worker still
        alive and working calls this periodically; a dead worker's last
        heartbeat ages past `reclaim_stale`'s threshold."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "UPDATE jobs SET heartbeat_at = %s WHERE id = %s AND state = %s",
                (datetime.now(timezone.utc), job_id, RUNNING),
            )

    def complete(
        self,
        job_id: str,
        *,
        result_ref: str,
        corpus_pin: str,
        cached: bool = False,
        cost_usd: float | None = None,
        tokens: int | None = None,
    ) -> None:
        """Mark a job `done`, recording where its result lives, the corpus
        pin it ran against (the issue's third acceptance criterion), and
        (issue #686) whether it was served from the content-keyed paper
        cache plus its dollar cost -- `0.0` on a cache hit, `None`
        (the default, and every call site before these two parameters
        existed) for a run whose model was unpriced. `tokens` (issue #724)
        follows the identical rule: `0` on a cache hit (this job made no
        model call), `None` for a run whose record carried no `cost` block
        at all, and every call site before this parameter existed keeps
        defaulting to that same `None`."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "UPDATE jobs SET state = %s, finished_at = %s, result_ref = %s, corpus_pin = %s, "
                "cached = %s, cost_usd = %s, tokens = %s WHERE id = %s",
                (
                    DONE,
                    datetime.now(timezone.utc),
                    result_ref,
                    corpus_pin,
                    cached,
                    cost_usd,
                    tokens,
                    job_id,
                ),
            )

    def set_paper_ref(self, job_id: str, paper_ref: str) -> None:
        """Record where this ask's Phase-C paper was written (issue #784).

        Called by the job body itself, mid-run, rather than travelling in
        `JobRunner`'s return tuple: the runner already writes to its own row
        through `append_event`, and widening that tuple would change the
        contract every other job kind and every test stub is written
        against, for a column only the `ask` kind ever fills.
        """
        with psycopg.connect(self._dsn) as conn:
            conn.execute("UPDATE jobs SET paper_ref = %s WHERE id = %s", (paper_ref, job_id))

    def fail(self, job_id: str, *, error: str) -> None:
        """Mark a job `failed`, recording the error it raised."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "UPDATE jobs SET state = %s, finished_at = %s, error = %s WHERE id = %s",
                (FAILED, datetime.now(timezone.utc), error, job_id),
            )

    def reclaim_stale(self, stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS) -> int:
        """Move every `running` job whose `heartbeat_at` is older than
        `stale_after_seconds` back to `queued`, clearing `claimed_at` and
        `heartbeat_at` so the next `claim()` picks it up fresh. Returns how
        many rows were reclaimed. This is the other half of the dead-worker
        story: a worker that stops heartbeating (killed, crashed, network
        partition) leaves its row `running` forever unless something else
        notices -- this is that something else, called periodically by
        whatever process owns the queue (a worker's own loop, or a separate
        reaper)."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        with psycopg.connect(self._dsn) as conn:
            cursor = conn.execute(
                "UPDATE jobs SET state = %s, claimed_at = NULL, heartbeat_at = NULL "
                "WHERE state = %s AND heartbeat_at < %s",
                (QUEUED, RUNNING, cutoff),
            )
            return cursor.rowcount

    def list_for_principal(self, principal: str) -> list[dict[str, Any]]:
        """Every job belonging to `principal`, newest first -- what `GET
        /asks` serves (issue #682)."""
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            return conn.execute(
                f"SELECT {_COLUMNS} FROM jobs WHERE principal = %s ORDER BY created_at DESC",
                (principal,),
            ).fetchall()

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Fetch one job row by id, or `None` if it does not exist."""
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            return conn.execute(f"SELECT {_COLUMNS} FROM jobs WHERE id = %s", (job_id,)).fetchone()

    def count_since(
        self,
        principal: str,
        *,
        kind: str,
        since: datetime | None = None,
        session_id: str | None = None,
        exclude_cached: bool = True,
        conn: psycopg.Connection | None = None,
    ) -> int:
        """How many `kind` jobs `principal` created, filtered by whichever
        of `since`/`session_id` is given.

        The quota check's own call (`axial.service.api._check_quota`) is
        the original shape: `since` a calendar-UTC window start, no
        `session_id`, `exclude_cached` at its default `True` -- a cache
        hit costs nothing and must never count against a budget that
        exists to bound spend, so a `cached` row is excluded; a row still
        `queued` or `running` (`cached` defaults `FALSE`) counts
        conservatively until a hit is proven.

        `session_id` and `exclude_cached=False` (issue #724, `GET
        /me/usage`) are the two additions: a session is identified by that
        id alone, never a time window, and a usage panel's "asks made"
        needs the OPPOSITE count from "asks charged against quota" -- the
        founder's own naming for why one count must never be mislabelled
        as the other.

        `conn`, when given (`self.connection()`), reuses an already-open
        connection instead of opening a new one -- a quota check calls this
        twice (day, month) plus `QuotaStore.limits_for` once, and batching
        all three onto one connection is what keeps `POST /asks` under its
        own latency budget (`connection`'s own docstring)."""
        conditions = ["principal = %s", "kind = %s"]
        params: list[Any] = [principal, kind]
        if since is not None:
            conditions.append("created_at >= %s")
            params.append(since)
        if session_id is not None:
            conditions.append("payload->>'session_id' = %s")
            params.append(session_id)
        if exclude_cached:
            conditions.append("cached = FALSE")
        where = " AND ".join(conditions)
        with self.connection() if conn is None else nullcontext(conn) as active_conn:
            (count,) = active_conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE {where}", params
            ).fetchone()
        return count

    def sum_spend_for_principal(
        self, principal: str, *, since: datetime | None = None, session_id: str | None = None
    ) -> float | None:
        """The sum of `cost_usd` across every `done` job `principal` has
        run (issue #686's fourth "done when": spend per analyst is
        queryable). `None`-preserving: SQL `SUM` already skips individual
        `NULL`s and returns `NULL` only when every row is -- a principal
        with no finished jobs, or whose every finished job's cost is
        unknown (an unpriced model, §7.14), reports `None` rather than a
        misleading `0.0`.

        `since`/`session_id` (issue #724, `GET /me/usage`) narrow the sum
        to a calendar window (month-to-date) or a session
        (`payload->>'session_id'`, no time bound) -- both default `None`,
        the original unbounded "all time" sum every caller before this
        issue relied on."""
        conditions = ["principal = %s", "state = %s"]
        params: list[Any] = [principal, DONE]
        if since is not None:
            conditions.append("created_at >= %s")
            params.append(since)
        if session_id is not None:
            conditions.append("payload->>'session_id' = %s")
            params.append(session_id)
        where = " AND ".join(conditions)
        with psycopg.connect(self._dsn) as conn:
            (total,) = conn.execute(
                f"SELECT SUM(cost_usd) FROM jobs WHERE {where}", params
            ).fetchone()
        return float(total) if total is not None else None

    def sum_tokens_for_principal(
        self, principal: str, *, since: datetime | None = None, session_id: str | None = None
    ) -> int | None:
        """`sum_spend_for_principal`'s exact mirror over `tokens` instead of
        `cost_usd` (issue #724) -- same `None`-preserving `SUM`, same two
        optional filters, because a usage window's cost and token figures
        are read off the same rows the same way and must never disagree on
        which rows counted."""
        conditions = ["principal = %s", "state = %s"]
        params: list[Any] = [principal, DONE]
        if since is not None:
            conditions.append("created_at >= %s")
            params.append(since)
        if session_id is not None:
            conditions.append("payload->>'session_id' = %s")
            params.append(session_id)
        where = " AND ".join(conditions)
        with psycopg.connect(self._dsn) as conn:
            (total,) = conn.execute(
                f"SELECT SUM(tokens) FROM jobs WHERE {where}", params
            ).fetchone()
        return int(total) if total is not None else None

    def append_event(self, job_id: str, message: str, detail: dict[str, Any] | None = None) -> int:
        """Append one `on_event(message, detail)` call as a `job_events` row
        (issue #683) and return its `seq`, monotonic per job starting at 1.
        Locks the parent job row for the duration: a worker only ever runs
        one job at a time so this never contends in production, but it
        keeps a concurrent caller (a test) from racing two rows onto the
        same seq."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute("SELECT id FROM jobs WHERE id = %s FOR UPDATE", (job_id,))
            (next_seq,) = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM job_events WHERE job_id = %s", (job_id,)
            ).fetchone()
            conn.execute(
                "INSERT INTO job_events (job_id, seq, message, detail) VALUES (%s, %s, %s, %s)",
                (job_id, next_seq, message, Jsonb(detail or {})),
            )
            return next_seq

    def events_since(self, job_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        """Every event for `job_id` with `seq > after_seq`, oldest first --
        the replay a newly-connected `GET /asks/{id}/events` client gets
        before it starts tailing live, and what a `Last-Event-ID` reconnect
        resumes from."""
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            return conn.execute(
                "SELECT seq, message, detail, created_at FROM job_events "
                "WHERE job_id = %s AND seq > %s ORDER BY seq",
                (job_id, after_seq),
            ).fetchall()
