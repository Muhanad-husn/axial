"""The console's read model over one run directory: everything the run
monitor screen shows, computed from what `axial.runlog.run_context` already
writes and nothing else. Pure functions over a path, so the numbers are
testable without a browser.

Three of them are behaviour rather than decoration, and each is derived from
the run's own record -- never from a hand-picked constant:

- **Effective concurrency** = sum of every record's `duration_sec` divided by
  the run's wall clock. This is the number that caught interrogation running
  strictly serial (a 12-worker pass measuring 1.0x), so it is a headline stat
  shown against the worker count, which is parsed out of the run's own
  recorded `command` (`--workers N`) rather than read from any config.

- **The quiet band.** `run.jsonl` records carry no timestamp, only
  `duration_sec`, so there is no single field to diff. The one progress
  clock both streams share is the mtime of the files themselves: every
  `record()`/`event()` call opens, writes and closes in the same call (see
  `axial.runlog`'s module docstring), so `max(mtime(run.jsonl),
  mtime(events.jsonl))` is exactly when this run last made progress,
  whichever stream it wrote to.

  The interval to compare that silence against is the run's own observed
  cadence: elapsed wall clock divided by the number of lines it has logged.
  On the real corpus that reads a chunk pass at ~11s a line and an
  interrogate pass at ~11 minutes, which is the whole point -- four quiet
  minutes is alarming in one and unremarkable in the other. There is no
  threshold constant anywhere in this, and the band is shown for EVERY live
  run: a run's own silence is never rendered as health.

  Cadence alone does not separate a stalled run from a working one, and
  replaying 77 real run directories says so plainly: a live band that fired
  on "quiet longer than the cadence" would have been lit for 81-97% of a
  perfectly healthy chunk/extract/interrogate/artifacts pass, because those
  passes are silent while a unit runs. What does separate them is a fact the
  run already records -- whether any unit is in flight (a `source_start`
  with no matching finish). Over those same 77 runs the longest stretch of
  silence with nothing in flight was 0.54s, and not one of them ever went
  idle-and-empty for longer than its own cadence. So `overdue` is the
  conjunction: quiet past the run's own cadence AND nothing in flight.

- **Spend** (issue #734, precedence revised by #738). `run.jsonl`'s own
  per-record `usd` field (`axial.runlog.RunHandle.record`'s issue #734
  addition) wins whenever at least one record has priced -- summed straight
  off the log, the same number a live run's own progress line already
  prints, now readable from a second process too, and (issue #738 defect 2)
  the PROVIDER'S OWN charge per source when it reported one, not
  `estimate_cost`'s price-table figure. A record whose `usd` is `null` (a
  model-bearing call whose response carried no `usage` object, or an
  unpriced model) is excluded from the sum, never coerced to zero.
  `spend_partial` is `True` exactly when the sum is real but incomplete --
  at least one model-bearing record's own `usd` is unknown -- so the
  aggregate itself reads as qualified rather than a confident total.

  `report.json`'s `tokens_and_cost.total_usd` (`axial.llm
  .usage_and_cost_by_pass`, still `estimate_cost`-only -- issue #738 did not
  touch it) is the fallback, used only when no record has priced at all --
  a run directory from before issue #734 added the per-record fields, most
  concretely. Records win over the report whenever they can, because they
  are now the more accurate number, not merely the live one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axial.runlog import RunListing, list_runs, load_run

# `axial.run`/`axial.map`'s own worker flag, as recorded in `meta.json`'s
# `command`. The run says how many workers it was given; nothing else does.
_WORKERS_FLAG = re.compile(r"--workers[= ](\d+)")

# `axial.run`'s `source_start` event detail: "<index>/<total>", the only
# place a pass's planned source count is written down.
_PROGRESS_DETAIL = re.compile(r"^(\d+)/(\d+)$")

_FINISHED_EVENT_KINDS = {"source_finish", "source_fail"}


@dataclass(frozen=True)
class PassRow:
    """One pass's progress row: what it settled, what is still in flight, and
    how many sources it set out to touch (`total`, `None` when the run
    recorded no `source_start` detail to read it from)."""

    name: str
    done: int
    skipped: int
    failed: int
    running: int
    total: int | None

    @property
    def settled(self) -> int:
        return self.done + self.skipped + self.failed

    @property
    def fraction(self) -> float | None:
        """How full the progress bar is, or `None` when the run never
        recorded a total to measure against."""
        if not self.total:
            return None
        return min(1.0, self.settled / self.total)


@dataclass(frozen=True)
class Quiet:
    """How long since this run last wrote anything, what it wrote, and the
    cadence it has been keeping -- see the module docstring."""

    quiet_sec: float
    expected_interval_sec: float | None
    last_mark: str
    in_flight: int
    overdue: bool


@dataclass(frozen=True)
class RunSnapshot:
    """One run, as the monitor screen shows it."""

    run_id: str
    status: str
    alive: bool
    command: str
    corpus_pin: str | None
    elapsed_sec: float | None
    units: int
    model_calls: int
    failures: int
    workers: int | None
    effective_concurrency: float | None
    spend_usd: float | None
    spend_partial: bool
    passes: list[PassRow]
    quiet: Quiet | None
    report: dict[str, Any] | None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _last_write(run_dir: Path) -> datetime | None:
    """When this run last appended to either log stream -- the one progress
    clock both `run.jsonl` and `events.jsonl` share (module docstring)."""
    stamps = [
        path.stat().st_mtime
        for path in (run_dir / "run.jsonl", run_dir / "events.jsonl")
        if path.is_file()
    ]
    if not stamps:
        return None
    return datetime.fromtimestamp(max(stamps), tz=timezone.utc)


def _pass_rows(records: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[PassRow]:
    """One row per pass named by either stream, in the order each pass is
    first seen -- which is the order the run drove them."""
    order: list[str] = []
    tallies: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}

    def bucket(name: str) -> dict[str, int]:
        if name not in tallies:
            order.append(name)
            tallies[name] = {"done": 0, "skipped": 0, "failed": 0, "started": 0, "finished": 0}
        return tallies[name]

    for record in records:
        counts = bucket(record.get("pass") or "(unnamed)")
        counts["done" if record.get("status") == "ok" else "failed"] += 1

    for event in events:
        name = event.get("pass") or "(unnamed)"
        counts = bucket(name)
        kind = event.get("kind")
        if kind == "source_skip":
            counts["skipped"] += 1
        elif kind == "source_start":
            counts["started"] += 1
            match = _PROGRESS_DETAIL.match(str(event.get("detail") or ""))
            if match:
                totals[name] = max(totals.get(name, 0), int(match.group(2)))
        elif kind in _FINISHED_EVENT_KINDS:
            counts["finished"] += 1

    rows = []
    for name in order:
        counts = tallies[name]
        settled = counts["done"] + counts["skipped"] + counts["failed"]
        running = max(0, counts["started"] - counts["finished"])
        total = totals.get(name)
        # A real run has landed here: three concurrent worklists of one
        # source each, writing into one run directory, so every
        # `source_start` said "1/1" while three sources settled. Whatever
        # the run planned, it cannot be less than what it has already done.
        if total is not None:
            total = max(total, settled + running)
        rows.append(
            PassRow(
                name=name,
                done=counts["done"],
                skipped=counts["skipped"],
                failed=counts["failed"],
                running=running,
                total=total,
            )
        )
    return rows


def _spend_from_report(report: dict[str, Any] | None) -> float | None:
    if not report:
        return None
    tokens_and_cost = report.get("tokens_and_cost") or {}
    total = tokens_and_cost.get("total_usd")
    return float(total) if isinstance(total, (int, float)) else None


def _spend_from_records(records: list[dict[str, Any]]) -> tuple[float | None, bool]:
    """This run's own spend, summed straight from `run.jsonl`'s per-record
    `usd` field (issue #734) -- the live-run path (module docstring). Every
    record whose `usd` is not a real number is excluded from the sum rather
    than treated as zero; the sum itself is `None` when no record has
    priced. `partial` is `True` when a model-bearing record's `usd` is
    unknown alongside at least one that IS known -- a real but incomplete
    total, distinguished from "no spend data at all". A record's `model`
    is populated whenever `axial.run` observed a real call for it
    (`calls_for_pass` moved, `_source_usage_and_cost`), so this also catches
    the case the issue is about: a call whose response carried no `usage`
    object reads as `model` set, `usd: null` -- exactly what fires
    `partial` here, never a silent `$0.00`."""
    known = [record["usd"] for record in records if isinstance(record.get("usd"), (int, float))]
    partial = any(
        record.get("model") is not None and not isinstance(record.get("usd"), (int, float))
        for record in records
    )
    total = sum(known) if known else None
    return total, (partial and total is not None)


def _read_report(run_dir: Path) -> dict[str, Any] | None:
    """`axial.run`'s end-of-run `report.json` -- what the run left behind.
    Absent while a run is still going, and absent entirely for passes that
    do not go through `axial.run.run_pass`."""
    path = run_dir / "report.json"
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _quiet(
    run_dir: Path,
    *,
    started_at: datetime | None,
    records: list[dict[str, Any]],
    events: list[dict[str, Any]],
    in_flight: int,
    now: datetime,
) -> Quiet | None:
    """The quiet band for a live run (module docstring). `None` when the run
    never opened a log stream at all, which is a run that has not started
    working rather than one that has gone silent."""
    last_write = _last_write(run_dir)
    if last_write is None or started_at is None:
        return None

    marks = len(records) + len(events)
    worked_sec = (last_write - started_at).total_seconds()
    expected = worked_sec / marks if marks else None

    if events:
        tail = events[-1]
        last_mark = " ".join(
            str(part) for part in (tail.get("kind"), tail.get("source_id")) if part
        )
    elif records:
        tail = records[-1]
        last_mark = " ".join(
            str(part) for part in (tail.get("pass"), tail.get("source_id")) if part
        )
    else:
        last_mark = "nothing yet"

    quiet_sec = max(0.0, (now - last_write).total_seconds())
    return Quiet(
        quiet_sec=quiet_sec,
        expected_interval_sec=expected,
        last_mark=last_mark or "nothing yet",
        in_flight=in_flight,
        overdue=in_flight == 0 and expected is not None and quiet_sec > expected,
    )


def snapshot(run_dir: Path, *, now: datetime | None = None) -> RunSnapshot:
    """Read one run directory into everything the monitor screen shows.
    Raises `axial.runlog.RunNotFoundError` when `run_dir` is not a run
    directory, same as `load_run`."""
    run_dir = Path(run_dir)
    resolved_now = now if now is not None else datetime.now(timezone.utc)
    view = load_run(run_dir, now=resolved_now)
    meta = view.meta

    started_at = _parse_iso(meta.get("started_at"))
    finished_at = _parse_iso(meta.get("finished_at"))
    elapsed_sec = None
    if started_at is not None:
        elapsed_sec = max(0.0, ((finished_at or resolved_now) - started_at).total_seconds())

    busy_sec = sum(
        record.get("duration_sec") or 0.0
        for record in view.records
        if isinstance(record.get("duration_sec"), (int, float))
    )
    command = str(meta.get("command") or "")
    workers_match = _WORKERS_FLAG.search(command)
    report = _read_report(run_dir)
    passes = _pass_rows(view.records, view.events)

    # Issue #738: records win whenever they can price at all -- they now
    # carry the provider's own real cost, more accurate than
    # `report.json`'s `estimate_cost`-only total (module docstring). The
    # report is the fallback, for a run directory old enough to predate
    # #734's per-record fields.
    records_total, spend_partial = _spend_from_records(view.records)
    if records_total is not None:
        spend_usd = records_total
    else:
        spend_usd = _spend_from_report(report)
        spend_partial = False

    return RunSnapshot(
        run_id=str(meta.get("run_id") or run_dir.name),
        status=str(meta.get("status") or "unknown"),
        alive=view.alive,
        command=command,
        corpus_pin=meta.get("corpus_pin"),
        elapsed_sec=elapsed_sec,
        units=len(view.records),
        model_calls=sum(1 for record in view.records if record.get("model")),
        failures=sum(1 for record in view.records if record.get("status") != "ok"),
        workers=int(workers_match.group(1)) if workers_match else None,
        effective_concurrency=(busy_sec / elapsed_sec) if elapsed_sec else None,
        spend_usd=spend_usd,
        spend_partial=spend_partial,
        passes=passes,
        quiet=(
            _quiet(
                run_dir,
                started_at=started_at,
                records=view.records,
                events=view.events,
                in_flight=sum(row.running for row in passes),
                now=resolved_now,
            )
            if view.alive
            else None
        ),
        report=report,
    )


def recent_runs(*, limit: int = 25, now: datetime | None = None) -> list[RunListing]:
    """The newest `limit` runs under the configured logs root, live ones
    first -- `axial.runlog.list_runs`' own newest-first order, with anything
    still alive pulled to the top so the console opens on the run the
    operator is actually watching."""
    runs = list_runs(now=now)
    runs.sort(key=lambda run: not run.alive)  # stable: newest-first survives within each group
    return runs[:limit]
