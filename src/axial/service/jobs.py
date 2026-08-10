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
"""

from __future__ import annotations

import uuid
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
"""

_COLUMNS = (
    "id, kind, principal, payload, state, created_at, "
    "claimed_at, heartbeat_at, finished_at, result_ref, error, corpus_pin"
)


class JobStore:
    """A thin wrapper over the `jobs` table. Every method opens its own
    connection and commits (or rolls back, on an exception propagating out
    of a `with` block) before returning -- there is no long-lived shared
    connection or pool here, matching the scale the issue names (hundreds of
    concurrent jobs, not thousands of requests a second)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def create_schema(self) -> None:
        """Create the `jobs` table if it does not already exist. Idempotent,
        so a worker or a test fixture can call it unconditionally on
        startup."""
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

    def complete(self, job_id: str, *, result_ref: str, corpus_pin: str) -> None:
        """Mark a job `done`, recording where its result lives and the
        corpus pin it ran against (the issue's third acceptance
        criterion)."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "UPDATE jobs SET state = %s, finished_at = %s, result_ref = %s, corpus_pin = %s "
                "WHERE id = %s",
                (DONE, datetime.now(timezone.utc), result_ref, corpus_pin, job_id),
            )

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
