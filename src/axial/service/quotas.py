"""Per-analyst quotas (issue #686): a `quotas` table holding an optional
per-principal override of the daily/monthly ask limit, plus a default read
from the environment for every principal with no row (DEC-65/#691 style:
one env var, one documented default, read at the edge -- no config
system, the same `AXIAL_*` seam `axial.ask.role.ROLE_ENV_VAR` already
uses).

**Quota windows are calendar UTC day and month, not rolling** (issue #686's
own call). A rolling window's reset time is fuzzy ("24 hours from your last
ask"); a calendar window's is an exact, statable instant a UI can print
verbatim -- `next_daily_reset`/`next_monthly_reset` below, which
`axial.service.api`'s 429 body carries.

**The count a window checks lives in `axial.service.jobs.JobStore.
count_since`, not here** -- it is the `jobs` table's own data (how many
`kind="ask"` rows a principal created in the window), and this store only
ever answers "what is this principal's limit." `count_since` excludes a
`cached` row (issue #686's third decision): a cache hit costs nothing, so
it must never count against a budget that exists to bound spend. Every row
starts `cached = FALSE` and the worker flips it only once a hit is proven,
so a job still `queued` or `running` counts conservatively until then.

The operator raises one analyst's limit by hand with `set_limits` -- a
plain store method, deliberately no admin HTTP surface or CLI command (the
issue's own scope line): a python one-liner against this store is the
whole mechanism.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

# One documented default per window, read once at the edge. Generous
# relative to the issue's own arithmetic ("a thousand academics at two
# papers a week"), since a quota here exists to bound a RUNAWAY (a bug, a
# script, abuse), not to throttle ordinary use -- an operator raises a
# specific analyst's limit by hand (`set_limits`) for anything past that.
DAILY_LIMIT_ENV_VAR = "AXIAL_QUOTA_ASKS_PER_DAY"
MONTHLY_LIMIT_ENV_VAR = "AXIAL_QUOTA_ASKS_PER_MONTH"
DEFAULT_DAILY_LIMIT = 20
DEFAULT_MONTHLY_LIMIT = 300

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS quotas (
    principal TEXT PRIMARY KEY,
    daily_limit INTEGER NOT NULL,
    monthly_limit INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _env_int(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var, "").strip()
    return int(raw) if raw else default


def _default_daily_limit() -> int:
    return _env_int(DAILY_LIMIT_ENV_VAR, DEFAULT_DAILY_LIMIT)


def _default_monthly_limit() -> int:
    return _env_int(MONTHLY_LIMIT_ENV_VAR, DEFAULT_MONTHLY_LIMIT)


@dataclass(frozen=True)
class QuotaLimits:
    """One principal's own limits, whether from their own `quotas` row or
    the environment default (`QuotaStore.limits_for`)."""

    daily: int
    monthly: int


def start_of_day_utc(now: datetime | None = None) -> datetime:
    """The start of `now`'s calendar UTC day. `now` defaults to the actual
    current instant; a caller passes its own for a deterministic test."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def next_daily_reset(now: datetime | None = None) -> datetime:
    """The next UTC midnight after `now` -- the exact instant a daily quota
    resets."""
    return start_of_day_utc(now) + timedelta(days=1)


def start_of_month_utc(now: datetime | None = None) -> datetime:
    """The start of `now`'s calendar UTC month."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_monthly_reset(now: datetime | None = None) -> datetime:
    """The start of the UTC month after `now`'s -- the exact instant a
    monthly quota resets, rolling the year over at December."""
    start = start_of_month_utc(now)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


class QuotaStore:
    """A thin wrapper over the `quotas` table, in `JobStore`'s own
    one-connection-per-call style: every method opens its own connection
    and commits before returning."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def create_schema(self) -> None:
        """Create the `quotas` table if it does not already exist.
        Idempotent, so a test fixture or an app's own startup can call it
        unconditionally."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(_SCHEMA_SQL)

    def limits_for(self, principal: str, *, conn: psycopg.Connection | None = None) -> QuotaLimits:
        """`principal`'s own limits, or the environment default (module
        docstring) when they have no row -- the overwhelming default, since
        an operator only ever writes a row to raise one person's limit.

        `conn`, when given, reuses an already-open connection instead of
        opening a new one (`axial.service.jobs.JobStore.connection`'s own
        docstring: batching a quota check's three reads onto one physical
        connection is what keeps `POST /asks` under its latency budget) --
        the same DSN in every real deployment, `quotas` and `jobs` living in
        one rented Postgres (DEC-65). `row_factory=dict_row` is requested at
        the CURSOR, not the connection, so a reused connection (opened with
        whatever default row shape its own owner wants) still gets a dict
        back here."""
        query = "SELECT daily_limit, monthly_limit FROM quotas WHERE principal = %s"
        if conn is not None:
            row = conn.cursor(row_factory=dict_row).execute(query, (principal,)).fetchone()
        else:
            with psycopg.connect(self._dsn, row_factory=dict_row) as new_conn:
                row = new_conn.execute(query, (principal,)).fetchone()
        if row is None:
            return QuotaLimits(daily=_default_daily_limit(), monthly=_default_monthly_limit())
        return QuotaLimits(daily=row["daily_limit"], monthly=row["monthly_limit"])

    def set_limits(self, principal: str, *, daily: int, monthly: int) -> None:
        """Raise (or lower) one principal's own limit by hand -- the
        issue's own "the operator can raise an individual's limit"
        mechanism, deliberately just this one store method (module
        docstring)."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO quotas (principal, daily_limit, monthly_limit, updated_at) "
                "VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (principal) DO UPDATE SET "
                "daily_limit = EXCLUDED.daily_limit, monthly_limit = EXCLUDED.monthly_limit, "
                "updated_at = now()",
                (principal, daily, monthly),
            )
