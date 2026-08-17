"""A content-keyed paper cache (issue #686): a `paper_cache` table keyed
`(brief_id, corpus_pin)` pointing at a finished analysis record -- and,
since issue #784, at the Phase-C essay drafted from it -- so two analysts
asking the same brief against the same published corpus cost one
generation, not two.

**The essay travels with the record it was drawn from.** A repeat question
is free by design, and a free answer that silently lost its essay would be
a worse answer rather than a cheaper one. `paper_ref` is nullable because
three real cases have no essay: an entry stored before that column existed,
a refused ask, and a run whose drafting failed.

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
-- Added by issue #784, after `paper_cache` already existed in deployed
-- databases: the Phase-C essay drafted from that same record, materialised
-- beside it. Nullable -- an entry stored before this column existed, a
-- refused ask, and a run whose drafting failed all have none.
ALTER TABLE paper_cache ADD COLUMN IF NOT EXISTS paper_ref TEXT;
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

    def lookup_paper(self, brief_id: str, corpus_pin: str) -> str | None:
        """The cached §7.3 **paper** record's path for this exact
        `(brief_id, corpus_pin)`, or `None` when this entry has none (issue
        #784).

        A second query rather than a second column on `lookup`'s return:
        `lookup`'s single-value signature is what four call sites and every
        existing test are written against, and a hit is already the path
        that makes no model call, so one more round trip on it costs
        nothing worth the churn.
        """
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT paper_ref FROM paper_cache WHERE brief_id = %s AND corpus_pin = %s",
                (brief_id, corpus_pin),
            ).fetchone()
        return row[0] if row else None

    def store(
        self,
        brief_id: str,
        corpus_pin: str,
        source_path: Path,
        cache_dir: Path,
        paper_path: Path | None = None,
    ) -> Path:
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

        # The essay is materialised on the same terms and for the same
        # reason as the record (module docstring): a later hit must not
        # depend on the originating analyst's own directory surviving.
        paper_target = None
        if paper_path is not None:
            paper_target = cache_dir / f"{brief_id}__{corpus_pin}.paper.json"
            shutil.copyfile(paper_path, paper_target)

        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO paper_cache (brief_id, corpus_pin, result_ref, paper_ref) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (brief_id, corpus_pin) DO NOTHING",
                (brief_id, corpus_pin, str(target), None if paper_target is None else str(paper_target)),
            )
        return target
