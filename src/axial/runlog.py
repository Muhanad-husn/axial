"""Structured run-logging seam (issue #270 slice 01): the one place a
long-running pass opens a run directory, tees a logger to a file, and
appends one JSON record per unit of work.

`run_context(name, *, root=None, clock=None)` is the whole mechanism --
stdlib `logging` + a `FileHandler` + a thin context manager, deliberately
not a logging framework (plans/run-logging/README.md's "out of scope": no
structlog, no loguru, no config DSL). It creates `data/logs/<name>-<ts>/`
containing:

- `run.jsonl` -- one JSON record per `RunHandle.record(...)` call:
  `source_id`, `pass`, `model` (nullable), `status`, `duration_sec`,
  `error`. Ids and values only -- DEC-23 is why `record`'s signature is a
  fixed set of keyword-only scalars with no field that could carry a chunk
  or source passage.
- `console.log` -- whatever the yielded handle's `logger` emits, via a
  `FileHandler` attached for the context's lifetime and flushed + detached
  on exit, so no handler leaks into a later run or test.
- `summary.md` -- a header stub only. The narrative (command, counts,
  outliers, next action) is operator-authored at run end, not generated
  here.

This slice wires only the `extract` pass (see `axial.cli._extract`); the
corpus runner (#277, `axial.run`) and the remaining passes (`envelope`,
`tag`, `eval` -- slice 02) deliberately are not touched here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Repo-root/cwd-relative constant, mirroring axial.extract.TREES_DIR /
# axial.paths.VAULT_DIR's convention.
LOGS_ROOT = Path("data/logs")


def _default_clock() -> str:
    """Production clock: a sortable, filesystem-safe UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class RunHandle:
    """What `run_context` yields: the run directory and a logger callers
    can write through to tee into `console.log`."""

    run_dir: Path
    logger: logging.Logger

    def record(
        self,
        *,
        source_id: str,
        pass_name: str,
        model: str | None,
        status: str,
        duration_sec: float,
        error: str | None = None,
    ) -> None:
        """Append one JSON line to `run.jsonl`. The keyword-only, fixed
        signature is the DEC-23 guard: there is no parameter this shape
        could carry a chunk or source passage through -- only ids, values,
        and status."""
        row = {
            "source_id": source_id,
            "pass": pass_name,
            "model": model,
            "status": status,
            "duration_sec": duration_sec,
            "error": error,
        }
        with (self.run_dir / "run.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


def _write_summary_stub(run_dir: Path, name: str) -> None:
    """Write the summary.md header stub. The seam creates the file's home;
    the narrative body is operator-authored at run end, never generated
    here (plans/run-logging/README.md's 'summary.md content' out-of-scope
    note)."""
    header = (
        f"# Run: {name}\n\n"
        f"Run directory: {run_dir.name}\n\n"
        "<!-- operator-authored: command, counts, outliers, next action -->\n"
    )
    (run_dir / "summary.md").write_text(header, encoding="utf-8")


@contextmanager
def run_context(
    name: str,
    *,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> Iterator[RunHandle]:
    """Open `<root>/<name>-<clock()>/`, attach a `FileHandler` teeing a
    per-run logger to its `console.log`, write the `summary.md` stub, and
    yield a `RunHandle`. On exit the handler is flushed, closed, and
    detached, whether the body raised or not.

    `root`/`clock` are the determinism seam (plans/run-logging/
    01-run-logging-seam.md): a test injects both to get a known, fixed-name
    run directory; production passes neither and gets
    `data/logs/<name>-<real-timestamp>/`.
    """
    if root is None:
        root = LOGS_ROOT
    if clock is None:
        clock = _default_clock

    run_dir = Path(root) / f"{name}-{clock()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Keyed by the full run_dir path, not just its <name>-<ts> tail: two
    # runs sharing that tail (e.g. two tests injecting the same fixed
    # clock under different tmp roots, or two real invocations landing in
    # the same clock second) must still get distinct `logging.getLogger()`
    # objects -- Python's logger registry is process-global and keyed by
    # name alone, so a shared tail would otherwise alias unrelated runs
    # onto the same logger.
    logger = logging.getLogger(f"axial.run.{run_dir.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    file_handler = logging.FileHandler(run_dir / "console.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    _write_summary_stub(run_dir, name)

    try:
        yield RunHandle(run_dir=run_dir, logger=logger)
    finally:
        file_handler.flush()
        file_handler.close()
        logger.removeHandler(file_handler)
