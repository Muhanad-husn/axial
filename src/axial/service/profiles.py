"""Per-analyst profile (issue #763): a `profiles` table beside `jobs` and
`quotas`, keyed by principal, carrying the light/dark/system theme choice.
From the founder's own comment on #688: the theme persists per analyst, not
per device, so it lives here rather than in browser storage.

`theme` is constrained to `light`/`dark`/`system` by a `CHECK` constraint on
the column itself, defaulting to `system` -- the issue's own shape, enforced
where the data lives rather than by a second, hand-written guard in Python
that would have to agree with it. `GET /me/profile` (`axial.service.api`)
serves that same default for a principal with no row yet, rather than a
`404`: the issue's own line is "the first sign-in should not need a write
before a read works."

`JobStore`'s own `CREATE TABLE IF NOT EXISTS` idiom, same store, same
one-connection-per-call style as `QuotaStore`."""

from __future__ import annotations

import psycopg

DEFAULT_THEME = "system"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS profiles (
    principal TEXT PRIMARY KEY,
    theme TEXT NOT NULL DEFAULT 'system' CHECK (theme IN ('light', 'dark', 'system')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class ProfileStore:
    """A thin wrapper over the `profiles` table."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def create_schema(self) -> None:
        """Create the `profiles` table if it does not already exist.
        Idempotent, so a test fixture or an app's own startup can call it
        unconditionally."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(_SCHEMA_SQL)

    def theme_for(self, principal: str) -> str:
        """`principal`'s own theme, or `DEFAULT_THEME` when they have never
        written one (module docstring: a principal with no row reads the
        default rather than a 404)."""
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT theme FROM profiles WHERE principal = %s", (principal,)
            ).fetchone()
        return row[0] if row is not None else DEFAULT_THEME

    def set_theme(self, principal: str, theme: str) -> None:
        """Write `principal`'s own theme, creating their row on first write
        or updating it otherwise. `theme`'s own shape is validated by the
        API's Pydantic model before this is ever called, and again by the
        table's own `CHECK` constraint (module docstring) -- this method
        trusts neither on faith, since a bad value from either seam surfaces
        here as `psycopg.errors.CheckViolation`, not a silently accepted
        row."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO profiles (principal, theme, updated_at) VALUES (%s, %s, now()) "
                "ON CONFLICT (principal) DO UPDATE SET theme = EXCLUDED.theme, updated_at = now()",
                (principal, theme),
            )
