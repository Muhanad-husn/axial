"""Structured run-logging seam (issue #270 slice 01; extended by issue #526
into the run-state seam every domain writes and every reader reads): the
one place a long-running pass opens a run directory, tees a logger to a
file, keeps a live heartbeat, and appends per-unit and finer-grained
records.

`run_context(name, *, root=None, clock=None, command=None, corpus_pin=None)`
is the whole mechanism -- stdlib `logging` + a `FileHandler` + a background
heartbeat thread + a thin context manager, deliberately not a logging
framework (plans/run-logging/README.md's "out of scope": no structlog, no
loguru, no config DSL). It creates `data/logs/<name>-<ts>/` containing:

- `meta.json` -- what the run is (`run_id`, `name`, `command`,
  `corpus_pin`), when it started/finished, and its `status` lifecycle:
  `"running"` while the `with` block is open, then `"ok"` (clean exit),
  `"failed"` (an exception propagated, or a caller explicitly called
  `RunHandle.set_status("failed")` before returning), or `"aborted"` (a
  `KeyboardInterrupt` reached this context). Written at open and rewritten
  once at close -- never mid-run.
- `heartbeat.json` -- `{"updated_at": <iso>}`, written once at open and then
  by a daemon thread every `HEARTBEAT_INTERVAL_SEC` for as long as the
  context is open, independent of whatever the calling thread is doing
  (this is what makes a single opaque call -- e.g. docling extraction, which
  has no progress hook -- still read as "started, still alive" rather than
  silence). A process killed outright never runs `run_context`'s own
  `finally`, so its `meta.json` stays stuck at `status: "running"` forever;
  the heartbeat going stale (`HEARTBEAT_STALE_AFTER_SEC`) is the only signal
  that distinguishes that from a run genuinely still working -- see
  `list_runs`/`load_run`'s `alive` computation.
- `run.jsonl` -- one JSON record per `RunHandle.record(...)` call, the
  existing one-per-unit-of-work granularity: `source_id`, `pass`, `model`
  (nullable), `status`, `duration_sec`, `error`. Ids and values only --
  DEC-23 is why `record`'s signature is a fixed set of keyword-only scalars
  with no field that could carry a chunk or source passage. Unchanged by
  #526 (its schema is a locked contract, `src/axial/test_runlog.py`).
- `events.jsonl` -- one JSON record per `RunHandle.event(...)` call, finer
  than `record()`: a source's own start, finish, or failure, or any other
  named `kind`, each carrying its own timestamp. This is what lets a
  caller (`axial.run.run_pass`) report progress **while** a source is
  running, not only once it finishes.
- `console.log` -- whatever the yielded handle's `logger` emits, via a
  `FileHandler` attached for the context's lifetime and flushed + detached
  on exit, so no handler leaks into a later run or test.
- `summary.md` -- a header stub only. The narrative (command, counts,
  outliers, next action) is operator-authored at run end, not generated
  here.

Every write above (`record`, `event`, the heartbeat tick, `meta.json`) opens
the file, writes, and closes (or otherwise flushes) in the same call --
never buffered until the run ends. That is what makes liveness independent
of the launching terminal: a `console.log`/`meta.json`/`heartbeat.json` read
from a second process sees exactly what a live run has done so far, whether
its own stdout is a console, piped, or fully detached.

The reader half -- `list_runs`, `load_run`, `follow_run` -- is a small,
read-only API over the same three JSON artifacts; it invents no fourth file
and no query language.

This module wires only the seam itself; `axial.run.run_pass` (issue #526)
is its first multi-source caller, and the single-source CLI passes
(`extract`, `envelope`, `tag`, `eval`, ...) keep using `record()` exactly as
before.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Repo-root/cwd-relative constant, mirroring axial.extract.TREES_DIR /
# axial.paths.VAULT_DIR's convention.
LOGS_ROOT = Path("data/logs")

# Env-var override for LOGS_ROOT, read by `run_context` only when a caller
# passes no `root` -- the same explicit-argument -> env var -> default
# resolution order `axial.llm`'s `AXIAL_SECRETS_PATH`/`_secrets_path()`
# already uses (issue #23, requirement 4). A house pattern, not a one-off:
# it is what lets both `conftest.py`s redirect every test's default run-log
# root, in-process AND in a subprocess `axial` invocation, with one
# `monkeypatch.setenv` rather than patching this module's global directly
# (which a subprocess never inherits).
LOGS_ROOT_ENV_VAR = "AXIAL_LOGS_ROOT"


def _resolve_logs_root() -> Path:
    """`AXIAL_LOGS_ROOT` when set/non-empty, else `LOGS_ROOT`. Read fresh on
    every call, never cached, so a test's `monkeypatch.setenv`/`setattr`
    takes effect for that test alone."""
    override = os.environ.get(LOGS_ROOT_ENV_VAR, "")
    return Path(override) if override else LOGS_ROOT


def _default_clock() -> str:
    """Production clock: a sortable, filesystem-safe UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# How often the background heartbeat thread touches `heartbeat.json` while a
# run is open, and how old a heartbeat is allowed to get before a reader
# calls the run dead (`_heartbeat_alive`). The stale threshold is a plain
# multiple of the write interval -- one tunable, not two independently
# hand-picked numbers -- generous enough (4x) that a single slow disk write
# or GC pause is never mistaken for a dead process.
HEARTBEAT_INTERVAL_SEC = 5.0
HEARTBEAT_STALE_AFTER_SEC = HEARTBEAT_INTERVAL_SEC * 4

# The only three terminal values `RunHandle.set_status`/`run_context` ever
# write to `meta.json`'s `status` field, past the open-time `"running"`.
_TERMINAL_STATUSES = {"ok", "failed", "aborted"}


def format_duration(seconds: float) -> str:
    """Render a duration compactly for a progress/status line: under a
    minute as `"12s"`, under an hour as `"3m12s"`, else `"1h05m"`. Shared by
    every reader/renderer of run-log timing (`axial.run.run_pass`'s live
    progress line today; a later `axial status`/`axial watch` is the named
    next caller) so the format never drifts between them."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _write_heartbeat(path: Path) -> None:
    path.write_text(json.dumps({"updated_at": _now_iso()}), encoding="utf-8")


def _write_meta(run_dir: Path, meta: dict[str, Any]) -> None:
    (run_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@dataclass
class RunHandle:
    """What `run_context` yields: the run directory, a logger callers can
    write through to tee into `console.log`, the run's own stable id, and
    the `record()`/`event()` writers.

    The trailing fields are internal bookkeeping the heartbeat thread and
    `run_context`'s own close logic use -- `init=False` so `RunHandle`'s
    public constructor shape (`run_dir`, `logger`, `run_id`) is unchanged
    for the one call site that builds one, `run_context` itself."""

    run_dir: Path
    logger: logging.Logger
    run_id: str
    _final_status: str = field(default="ok", init=False, repr=False)
    _heartbeat_stop: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _heartbeat_thread: threading.Thread | None = field(default=None, init=False, repr=False)

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

    def event(
        self,
        *,
        kind: str,
        source_id: str | None = None,
        pass_name: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Append one JSON line to `events.jsonl` -- finer-grained than
        `record()`'s one-per-unit-of-work (issue #526): a source's own
        start, finish, or failure, or any other short-labeled `kind`, each
        carrying its own timestamp. Written and flushed the instant it
        happens, same discipline as `record()`. Same DEC-23 guard: no
        parameter here can carry source text, only short ids/labels."""
        row = {
            "ts": _now_iso(),
            "kind": kind,
            "source_id": source_id,
            "pass": pass_name,
            "detail": detail,
        }
        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def set_status(self, status: str) -> None:
        """Declare the status `run_context` writes to `meta.json` at close,
        used when the `with` block returns normally but the caller itself
        knows the run did not actually succeed (e.g. `axial.run.run_pass`'s
        own fatal, pre-loop error paths, which return an exit code without
        raising). An exception propagating out of the `with` block always
        overrides this with `"failed"`/`"aborted"` -- see `run_context`."""
        if status not in _TERMINAL_STATUSES:
            raise ValueError(
                f"unknown run status {status!r}; expected one of {sorted(_TERMINAL_STATUSES)}"
            )
        self._final_status = status

    def _heartbeat_path(self) -> Path:
        return self.run_dir / "heartbeat.json"

    def _start_heartbeat(self) -> None:
        _write_heartbeat(self._heartbeat_path())
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(HEARTBEAT_INTERVAL_SEC):
            _write_heartbeat(self._heartbeat_path())

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2.0)


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
    command: str | None = None,
    corpus_pin: str | None = None,
) -> Iterator[RunHandle]:
    """Open `<root>/<name>-<clock()>/`, attach a `FileHandler` teeing a
    per-run logger to its `console.log`, write the `summary.md` stub and the
    opening `meta.json`, start the heartbeat thread, and yield a
    `RunHandle`. On exit the heartbeat stops, `meta.json` is rewritten with
    its final `status`/`finished_at`, and the log handler is flushed,
    closed, and detached -- whether the body raised or not.

    `root`/`clock` are the determinism seam (plans/run-logging/
    01-run-logging-seam.md): a test injects both to get a known, fixed-name
    run directory; production passes neither and gets
    `data/logs/<name>-<real-timestamp>/`.

    Resolution order when `root` is not given: the `AXIAL_LOGS_ROOT` env var
    (`_resolve_logs_root`), then the module-level `LOGS_ROOT` default. An
    explicit `root` argument always wins over both.

    `command` defaults to `" ".join(sys.argv)` -- the process's own real
    invocation -- when not given; `corpus_pin` defaults to `None` (only a
    caller with an actual notion of "which corpus" this run touches, e.g.
    `axial.run.run_pass`'s resolved worklist/corpus source set, supplies
    one; a single-source CLI pass has no corpus to pin and leaves it null).

    Status lifecycle written to `meta.json`'s `status` field: `"running"`
    at open; at close, `"ok"` unless the caller called
    `RunHandle.set_status(...)` (honored) or an exception propagated out of
    the `with` block (`"aborted"` for `KeyboardInterrupt`, `"failed"` for
    anything else -- always overriding an explicit `set_status`, since a
    real exception is more authoritative than a caller's own guess).
    """
    if root is None:
        root = _resolve_logs_root()
    if clock is None:
        clock = _default_clock

    run_dir = Path(root) / f"{name}-{clock()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name

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

    meta: dict[str, Any] = {
        "run_id": run_id,
        "name": name,
        "command": command if command is not None else " ".join(sys.argv),
        "started_at": _now_iso(),
        "finished_at": None,
        "corpus_pin": corpus_pin,
        "status": "running",
    }
    _write_meta(run_dir, meta)

    handle = RunHandle(run_dir=run_dir, logger=logger, run_id=run_id)
    handle._start_heartbeat()

    try:
        yield handle
    except BaseException as exc:
        meta["status"] = "aborted" if isinstance(exc, KeyboardInterrupt) else "failed"
        raise
    else:
        meta["status"] = handle._final_status
    finally:
        handle._stop_heartbeat()
        meta["finished_at"] = _now_iso()
        _write_meta(run_dir, meta)
        file_handler.flush()
        file_handler.close()
        logger.removeHandler(file_handler)


# ---------------------------------------------------------------------------
# Reader API (issue #526): list runs, load one, follow a live one. Read-only,
# over the same `meta.json`/`heartbeat.json`/`run.jsonl`/`events.jsonl`
# artifacts `run_context` writes -- no fourth file, no query language.
# ---------------------------------------------------------------------------


class RunNotFoundError(Exception):
    """Raised by `load_run` when `run_dir` carries no `meta.json` -- either
    the path is not a run directory at all, or it predates issue #526."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        super().__init__(f"no run found at {run_dir} (missing meta.json)")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _heartbeat_alive(run_dir: Path, status: str, now: datetime) -> bool:
    """A run is alive iff its own `meta.json` still says `"running"` AND its
    heartbeat is fresher than `HEARTBEAT_STALE_AFTER_SEC` -- the one check
    that tells a genuinely still-working run apart from one a hard kill left
    stuck at `status: "running"` forever (module docstring)."""
    if status != "running":
        return False
    heartbeat = _read_json(run_dir / "heartbeat.json")
    if heartbeat is None or "updated_at" not in heartbeat:
        return False
    try:
        updated_at = datetime.fromisoformat(heartbeat["updated_at"])
    except ValueError:
        return False
    return (now - updated_at).total_seconds() < HEARTBEAT_STALE_AFTER_SEC


@dataclass(frozen=True)
class RunListing:
    """One `list_runs()` row: `meta.json`'s own fields plus the computed
    `alive` liveness bit -- never a second copy of anything `meta.json`
    itself carries."""

    run_id: str
    name: str
    status: str
    started_at: str
    finished_at: str | None
    corpus_pin: str | None
    command: str
    run_dir: Path
    alive: bool


def list_runs(root: Path | None = None, *, now: datetime | None = None) -> list[RunListing]:
    """Every run directory under `root` (default: `_resolve_logs_root()`)
    that carries a `meta.json`, newest `started_at` first. A directory with
    no `meta.json` -- a run that predates issue #526, or anything else that
    is not a run directory -- is silently skipped, never a crash."""
    resolved_root = Path(root) if root is not None else _resolve_logs_root()
    resolved_now = now if now is not None else datetime.now(timezone.utc)
    if not resolved_root.is_dir():
        return []

    listings = []
    for run_dir in sorted(resolved_root.iterdir()):
        if not run_dir.is_dir():
            continue
        meta = _read_json(run_dir / "meta.json")
        if meta is None:
            continue
        status = meta.get("status", "unknown")
        listings.append(
            RunListing(
                run_id=meta.get("run_id", run_dir.name),
                name=meta.get("name", ""),
                status=status,
                started_at=meta.get("started_at", ""),
                finished_at=meta.get("finished_at"),
                corpus_pin=meta.get("corpus_pin"),
                command=meta.get("command", ""),
                run_dir=run_dir,
                alive=_heartbeat_alive(run_dir, status, resolved_now),
            )
        )
    listings.sort(key=lambda listing: listing.started_at, reverse=True)
    return listings


@dataclass(frozen=True)
class RunView:
    """`load_run()`'s full read of one run: its `meta.json`, every
    `run.jsonl`/`events.jsonl` record, and the same computed liveness
    `list_runs` reports for it."""

    meta: dict[str, Any]
    records: list[dict[str, Any]]
    events: list[dict[str, Any]]
    alive: bool
    heartbeat_age_sec: float | None


def load_run(run_dir: Path, *, now: datetime | None = None) -> RunView:
    """Read one run directory fully -- `meta.json`, `run.jsonl`,
    `events.jsonl`, and the heartbeat's current age -- re-readable at any
    point during or after the run (issue #526: "a run in progress is fully
    readable from a separate process", and the end-of-run report stays
    re-readable long after the run finished). Raises `RunNotFoundError` when
    `run_dir` carries no `meta.json`."""
    run_dir = Path(run_dir)
    meta = _read_json(run_dir / "meta.json")
    if meta is None:
        raise RunNotFoundError(run_dir)
    resolved_now = now if now is not None else datetime.now(timezone.utc)

    heartbeat = _read_json(run_dir / "heartbeat.json")
    heartbeat_age_sec: float | None = None
    if heartbeat is not None and "updated_at" in heartbeat:
        try:
            updated_at = datetime.fromisoformat(heartbeat["updated_at"])
            heartbeat_age_sec = (resolved_now - updated_at).total_seconds()
        except ValueError:
            heartbeat_age_sec = None

    return RunView(
        meta=meta,
        records=_read_jsonl(run_dir / "run.jsonl"),
        events=_read_jsonl(run_dir / "events.jsonl"),
        alive=_heartbeat_alive(run_dir, meta.get("status", "unknown"), resolved_now),
        heartbeat_age_sec=heartbeat_age_sec,
    )


def _read_new_lines(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Every complete JSON line appended to `path` since byte `offset`, and
    the new offset to resume from -- the tailing primitive `follow_run`
    polls with. A `path` that does not exist yet (e.g. `events.jsonl` before
    the first `event()` call) yields nothing, offset unchanged."""
    if not path.is_file():
        return [], offset
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        new_text = handle.read()
        new_offset = handle.tell()
    rows = [json.loads(line) for line in new_text.splitlines() if line.strip()]
    return rows, new_offset


def follow_run(
    run_dir: Path,
    *,
    poll_interval: float = 1.0,
    sleep: Callable[[float], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every `run.jsonl`/`events.jsonl` line as it is written, oldest
    first within each stream, tagged `{"stream": "record"|"event", ...row}`.
    Polls every `poll_interval` seconds and stops once `meta.json`'s own
    `status` is no longer `"running"` -- by which point every line the run
    will ever write is already on disk (`run_context`'s own close order:
    every `record()`/`event()` call the pass makes happens before `status`
    leaves `"running"`), so nothing is missed by checking status only after
    a full read.

    `sleep` is the same explicit-injection determinism seam `run_context`'s
    own `clock` uses (default `time.sleep`, imported lazily so this module
    carries no top-level `import time` for its one use) -- a test drives
    this with a fake to prove the polling loop without ever blocking on a
    real timer."""
    if sleep is None:
        import time

        sleep = time.sleep

    run_dir = Path(run_dir)
    records_path = run_dir / "run.jsonl"
    events_path = run_dir / "events.jsonl"
    records_offset = 0
    events_offset = 0

    while True:
        new_records, records_offset = _read_new_lines(records_path, records_offset)
        for row in new_records:
            yield {"stream": "record", **row}
        new_events, events_offset = _read_new_lines(events_path, events_offset)
        for row in new_events:
            yield {"stream": "event", **row}

        meta = _read_json(run_dir / "meta.json") or {}
        if meta.get("status") != "running":
            return
        sleep(poll_interval)
