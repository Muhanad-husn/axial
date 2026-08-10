"""A content-keyed paper cache (issue #686): a `paper_cache` table keyed
`(brief_id, corpus_pin)` pointing at a finished analysis record, so two
analysts asking the same brief against the same published corpus cost one
generation, not two.

**The cache resolves in the worker, not the API** (DEC-65's own #691 shape,
issue #686's second decision): only the worker process holds the bound
snapshot's pin (`axial.service.snapshot.Snapshot.bind`), and the API stays
pin-free. A cache hit therefore still creates a `queued` job row --
`POST /asks` never calls the engine either way -- and the worker completes
it straight to `done` with no model call (`axial.service.worker.
run_ask_job`).

**Key is `(brief_id, corpus_pin)`, not `(brief_id, corpus_pin, source
weights)`** as the issue's own prose names. `axial.brief.intake.
compute_brief_id` already folds `weights` (and `lens`) into `brief_id`
itself (issue #639) -- a separate weights column would be dead, since two
briefs with different weights already compute different ids and so never
collide in this table.

**A hit crosses the per-principal boundary on purpose.** The paper is
corpus-derived and content-identical for anyone who asks the same brief
against the same pin, not analyst A's private work -- serving it to analyst
B is correct. But it must survive A's own working set changing later, so
`store` below MATERIALISES a private copy of the finished record under a
shared, principal-free directory at generation time, rather than pointing
at the originating analyst's own `analyses_dir` entry. Recording the
original path is one field cheaper to write, but a later hit reading it
would carry an undocumented dependency on analyst A's own directory
surviving -- exactly what the issue rules out ("must not silently break if
the originating analyst's working set is gone"). Only the materialising
copy actually meets that bar, so it is not a cost/robustness trade, and a
persisted §7.3 record is kilobytes: the copy is not a cost worth avoiding.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS paper_cache (
    brief_id TEXT NOT NULL,
    corpus_pin TEXT NOT NULL,
    result_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (brief_id, corpus_pin)
);
"""


class PaperCache:
    """A thin wrapper over the `paper_cache` table plus the one file
    operation a store needs -- no ORM, in `JobStore`'s own
    one-connection-per-call style."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def create_schema(self) -> None:
        """Create the `paper_cache` table if it does not already exist.
        Idempotent, so a test fixture or an app's own startup can call it
        unconditionally."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(_SCHEMA_SQL)

    def lookup(self, brief_id: str, corpus_pin: str) -> str | None:
        """The cached record's path for this exact `(brief_id, corpus_pin)`,
        or `None` on a miss. A different pin is a different paper (module
        docstring) -- there is no cross-pin fallback here or anywhere
        else."""
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT result_ref FROM paper_cache WHERE brief_id = %s AND corpus_pin = %s",
                (brief_id, corpus_pin),
            ).fetchone()
        return row[0] if row else None

    def store(self, brief_id: str, corpus_pin: str, source_path: Path, cache_dir: Path) -> Path:
        """Materialise `source_path` (a just-generated §7.3 record) into
        `cache_dir` under a name keyed on `(brief_id, corpus_pin)`, record
        the entry, and return the materialised path.

        `ON CONFLICT DO NOTHING`: two workers racing the same brief against
        the same pin can both reach here (both saw a miss, both generated).
        The loser's copy sits harmlessly unreferenced in `cache_dir` --
        its own job row still completed correctly against its own copy
        moments earlier; a duplicate generation here is a wasted model
        call, not a correctness bug, and no worse than running with no
        cache at all."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{brief_id}__{corpus_pin}.json"
        shutil.copyfile(source_path, target)
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO paper_cache (brief_id, corpus_pin, result_ref) VALUES (%s, %s, %s) "
                "ON CONFLICT (brief_id, corpus_pin) DO NOTHING",
                (brief_id, corpus_pin, str(target)),
            )
        return target
