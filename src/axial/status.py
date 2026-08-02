"""`axial status`: one screen, zero model calls, answering "can I ask
questions yet, and if not what is missing" (issue #530). Reads what
`axial.run`, `axial.runlog`, `axial.eval.corpus_pin` and each pass module
already persist; writes nothing.

**The central rule, forced by a real bug** (issue #530): `axial sources`
reported all 31 fully-ingested books as "new" because it asked
`data/run/ledger.tsv` -- a bookkeeping file that did not exist, over a
corpus whose envelope/chunks/tree/answers artifacts all plainly sat on
disk. So here: a stage's completion is read from the artifact the pass
itself persists -- `axial.extract.tree_path`, `axial.envelope.
envelope_path`, `axial.chunk.chunks_checkpoint_path`, `axial.interrogate.
answers_checkpoint_path`, `axial.artifacts.artifacts_checkpoint_path` --
the exact same paths `axial.run`'s own done-predicates already check for
extract/envelope, generalized to every stage that has one. A file existing
is enough; its contents are never opened or parsed. The runner-owned
resume ledger (`axial.run.LEDGER_PATH`) is consulted only to explain a
stage that is NOT done -- distinguishing "attempted and failed" (a FAIL
row, with its reason) from "never attempted" (pending) -- never to decide
what IS done. An absent or stale ledger therefore degrades this command to
"can't say why it's pending," never to a false "not done" for something
that plainly is.

`vault-write` has no single per-source artifact (materialize writes many
note files per source), so its done-signal is instead: does at least one
note filename under `<vault_dir>/prose|artifacts` carry this source's own
12-hex-char content-hash suffix? That suffix is the one part of a note's
filename `axial.paths.budgeted_chunk_filename`'s own docstring guarantees
is NEVER shortened -- so the check is a plain filename scan (no file
reads), not a heuristic.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axial.artifacts import _default_artifacts_dir, artifacts_checkpoint_path
from axial.chunk import _default_chunks_dir, chunks_checkpoint_path
from axial.envelope import _default_envelopes_dir, compute_source_id, envelope_path
from axial.eval.corpus_pin import (
    EVALS_DIR,
    AmbiguousCorpusPinError,
    MissingCorpusPinError,
    resolve_pin_id,
)
from axial.extract import TREES_DIR, tree_path
from axial.intake import SUPPORTED_EXTENSIONS
from axial.interrogate import _default_answers_dir, answers_checkpoint_path
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_sources_dir, default_vault_dir
from axial.runlog import RunListing, RunNotFoundError, RunView, format_duration, list_runs

# Repeated, not imported, deliberately: `axial.run` is the ledger's owner
# and imports the whole pipeline (extract/envelope/chunk/interrogate/
# artifacts/vault/llm) to do its writing job. This module only ever READS
# the ledger, and already imports every pass module it needs directly for
# their own artifact paths above -- pulling in `axial.run` just for three
# literals would add `axial.vault`/`axial.llm` to a command whose whole
# point is to cost nothing. Same precedent `axial.paths`'s own module
# docstring documents for `axial.reconcile`/`axial.run` repeating
# `SOURCES_DIR`'s literal rather than importing it.
LEDGER_PATH = Path("data/run/ledger.tsv")
_OK_STATUS = "OK"
_FAIL_STATUS = "FAIL"

# The six passes `axial.run.PASS_REGISTRY` registers, in pipeline order --
# the same names the ledger's own `pass` column carries, reused verbatim so
# a ledger row and a status row are never independently spelled.
STAGES = ("extract", "envelope", "chunk", "interrogate", "artifacts", "vault-write")

_VAULT_HASH12 = re.compile(r"-([0-9a-f]{12})_")


@dataclass(frozen=True)
class StageStatus:
    """One stage's tally across every source in the corpus: how many carry
    the stage's own persisted artifact (`done`), how many don't and the
    ledger names no attempt (`pending`), and how many don't and the ledger's
    own last row for `(stage, source_id)` was a FAIL (`failed`, with the
    reason -- `failures`)."""

    stage: str
    done: int
    pending: int
    failed: int
    failures: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class StatusReport:
    """The whole `axial status` screen as data -- `render_status` turns it
    into text."""

    sources_total: int
    stages: dict[str, StageStatus]
    corpus_pin_status: str  # "ok" | "missing" | "ambiguous"
    corpus_pin_name: str | None
    corpus_pin_detail: str | None
    prose_notes: int
    artifact_notes: int
    name_pages: int
    ready: bool
    live_run: RunListing | None
    live_run_heartbeat_age_sec: float | None
    most_recent_run: RunListing | None


def _load_ledger_failures(ledger_path: Path) -> dict[tuple[str, str], str]:
    """The last FAIL reason recorded per `(pass, source_id)` -- an OK row
    for the same pair, wherever it lands in the (append-only,
    chronologically-ordered) file, clears an earlier FAIL, since a later
    successful retry is the freshest truth. An absent, unreadable or
    malformed ledger yields `{}` -- corroboration only, never fatal to a
    read-only status command (unlike `axial.run`'s own `LedgerError`, which
    IS fatal there because the ledger is that module's write-side state)."""
    if not ledger_path.is_file():
        return {}
    failures: dict[tuple[str, str], str] = {}
    try:
        with ledger_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                pass_name = row.get("pass")
                source_id = row.get("source_id")
                if not pass_name or not source_id:
                    continue
                key = (pass_name, source_id)
                status = row.get("status")
                if status == _FAIL_STATUS:
                    failures[key] = row.get("reason") or ""
                elif status == _OK_STATUS:
                    failures.pop(key, None)
    except (OSError, csv.Error):
        return {}
    return failures


def _vault_hash12_set(vault_dir: Path) -> set[str]:
    """Every 12-hex-char source content-hash found in a note FILENAME under
    `<vault_dir>/prose` and `<vault_dir>/artifacts` -- one directory listing
    per call, no file ever opened. See the module docstring for why this
    suffix is a safe, unshortened signal."""
    hashes: set[str] = set()
    for sub in ("prose", "artifacts"):
        directory = vault_dir / sub
        if not directory.is_dir():
            continue
        for note_path in directory.glob("*.md"):
            match = _VAULT_HASH12.search(note_path.name)
            if match:
                hashes.add(match.group(1))
    return hashes


def _count_md(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.glob("*.md"))


def _read_heartbeat_age_sec(run_dir: Path, now: datetime) -> float | None:
    """The live run's own heartbeat age, read directly (a two-field JSON
    file) -- deliberately NOT `axial.runlog.load_run`, which also parses
    every `run.jsonl`/`events.jsonl` record, the "thousands of records" cost
    a status question must never pay."""
    path = run_dir / "heartbeat.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (now - updated_at).total_seconds()


def compute_status(
    *,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    sources_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    trees_dir: Path = TREES_DIR,
    chunks_dir: Path | None = None,
    answers_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    vault_dir: Path | None = None,
    evals_dir: Path | None = None,
    ledger_path: Path = LEDGER_PATH,
    logs_root: Path | None = None,
    now: datetime | None = None,
) -> StatusReport:
    """Build one `StatusReport` from whatever is on disk. Every directory
    parameter defaults through the same config-then-fallback resolution the
    rest of the pipeline uses (`axial.paths`, each pass module's own
    `_default_*_dir`), so production callers (`axial status`) need supply
    nothing, and tests inject isolated temp directories the same way
    `axial.eval.corpus_pin.write_pin`'s tests already do."""
    resolved_now = now if now is not None else datetime.now(timezone.utc)
    sources_dir = sources_dir if sources_dir is not None else default_sources_dir(config_path)
    envelopes_dir = (
        envelopes_dir if envelopes_dir is not None else _default_envelopes_dir(config_path)
    )
    chunks_dir = chunks_dir if chunks_dir is not None else _default_chunks_dir(config_path)
    answers_dir = answers_dir if answers_dir is not None else _default_answers_dir(config_path)
    artifacts_dir = (
        artifacts_dir if artifacts_dir is not None else _default_artifacts_dir(config_path)
    )
    vault_dir = vault_dir if vault_dir is not None else default_vault_dir(config_path)
    evals_dir = evals_dir if evals_dir is not None else EVALS_DIR

    source_files = (
        sorted(
            p
            for p in sources_dir.glob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        if sources_dir.is_dir()
        else []
    )
    source_ids = [compute_source_id(p) for p in source_files]

    ledger_failures = _load_ledger_failures(ledger_path)
    vault_hash12s = _vault_hash12_set(vault_dir)

    def _is_done(stage: str, source_id: str) -> bool:
        if stage == "extract":
            return tree_path(source_id, trees_dir).exists()
        if stage == "envelope":
            return envelope_path(source_id, envelopes_dir).exists()
        if stage == "chunk":
            return chunks_checkpoint_path(source_id, chunks_dir).exists()
        if stage == "interrogate":
            return answers_checkpoint_path(source_id, answers_dir).exists()
        if stage == "artifacts":
            return artifacts_checkpoint_path(source_id, artifacts_dir).exists()
        return source_id[-12:] in vault_hash12s  # "vault-write"

    stages: dict[str, StageStatus] = {}
    for stage in STAGES:
        done = 0
        failures: list[tuple[str, str]] = []
        pending = 0
        for source_id in source_ids:
            if _is_done(stage, source_id):
                done += 1
                continue
            reason = ledger_failures.get((stage, source_id))
            if reason is not None:
                failures.append((source_id, reason))
            else:
                pending += 1
        stages[stage] = StageStatus(
            stage=stage, done=done, pending=pending, failed=len(failures), failures=failures
        )

    corpus_pin_status = "ok"
    corpus_pin_name: str | None = None
    corpus_pin_detail: str | None = None
    try:
        corpus_pin_name = resolve_pin_id(evals_dir)
    except MissingCorpusPinError:
        corpus_pin_status = "missing"
    except AmbiguousCorpusPinError as exc:
        corpus_pin_status = "ambiguous"
        corpus_pin_detail = ", ".join(sorted(p.stem for p in exc.candidates))

    prose_notes = _count_md(vault_dir / "prose")
    artifact_notes = _count_md(vault_dir / "artifacts")
    name_pages = _count_md(vault_dir / "names")

    vault_write = stages["vault-write"]
    ready = len(source_ids) > 0 and vault_write.pending == 0 and vault_write.failed == 0

    runs = list_runs(root=logs_root, now=resolved_now)
    live_run = next((run for run in runs if run.alive), None)
    live_run_heartbeat_age_sec = (
        _read_heartbeat_age_sec(live_run.run_dir, resolved_now) if live_run is not None else None
    )
    most_recent_run = runs[0] if runs else None

    return StatusReport(
        sources_total=len(source_ids),
        stages=stages,
        corpus_pin_status=corpus_pin_status,
        corpus_pin_name=corpus_pin_name,
        corpus_pin_detail=corpus_pin_detail,
        prose_notes=prose_notes,
        artifact_notes=artifact_notes,
        name_pages=name_pages,
        ready=ready,
        live_run=live_run,
        live_run_heartbeat_age_sec=live_run_heartbeat_age_sec,
        most_recent_run=most_recent_run,
    )


def render_status(report: StatusReport) -> str:
    """Render a `StatusReport` as the plain-text `axial status` screen."""
    lines: list[str] = []

    if report.ready:
        lines.append(f"ready to query: yes -- all {report.sources_total} source(s) in the vault")
    elif report.sources_total == 0:
        lines.append("ready to query: no -- no sources found")
    else:
        vw = report.stages["vault-write"]
        lines.append(
            f"ready to query: no -- {vw.pending} pending, {vw.failed} failed "
            f"reaching the vault (of {report.sources_total} source(s))"
        )
    lines.append("")

    lines.append(f"sources: {report.sources_total}")
    lines.append(f"{'stage':<13}{'done':>6}{'pending':>9}{'failed':>8}")
    for stage in STAGES:
        s = report.stages[stage]
        lines.append(f"{stage:<13}{s.done:>6}{s.pending:>9}{s.failed:>8}")
    lines.append("")

    if report.corpus_pin_status == "ok":
        lines.append(f"corpus pin: {report.corpus_pin_name}")
    elif report.corpus_pin_status == "missing":
        lines.append("corpus pin: none written (run `axial pin write <name>`)")
    else:
        lines.append(f"corpus pin: ambiguous -- {report.corpus_pin_detail}")

    lines.append(
        f"vault: {report.prose_notes} prose note(s), {report.artifact_notes} artifact "
        f"note(s), {report.name_pages} name page(s)"
    )
    lines.append("")

    all_failures = [
        (stage, source_id, reason)
        for stage in STAGES
        for source_id, reason in report.stages[stage].failures
    ]
    if all_failures:
        lines.append("failed:")
        for stage, source_id, reason in all_failures:
            lines.append(f"  {stage:<13} {source_id}: {reason or '(no reason recorded)'}")
    else:
        lines.append("failed: none")
    lines.append("")

    if report.live_run is not None:
        age = format_duration(report.live_run_heartbeat_age_sec or 0.0)
        lines.append(f"run: {report.live_run.name} is alive (heartbeat {age} ago)")
    elif report.most_recent_run is not None:
        run = report.most_recent_run
        stale_note = " -- STALE, appears to have died mid-run" if run.status == "running" else ""
        finished = run.finished_at or "not finished"
        lines.append(
            f"run: none alive; last was {run.name} ({run.status}{stale_note}), finished {finished}"
        )
    else:
        lines.append("run: none recorded")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Watching a run (issue #530): thin rendering over axial.runlog's own reader
# API (list_runs/load_run/follow_run) -- no second reader, no new persisted
# file. `axial runs list|show|follow` in cli.py calls these directly.
# ---------------------------------------------------------------------------


def resolve_run_dir(identifier: str, *, root: Path | None = None) -> Path:
    """What `axial runs show <x>`/`axial runs follow <x>` accepts for `<x>`:
    either a path that is itself a run directory (carries `meta.json`),
    taken verbatim, or a bare `run_id` matched against `list_runs(root)`.
    Raises `axial.runlog.RunNotFoundError` when neither resolves -- the same
    error `load_run` itself raises for a bad path, so callers need only one
    except clause."""
    candidate = Path(identifier)
    if candidate.is_dir() and (candidate / "meta.json").is_file():
        return candidate
    for run in list_runs(root=root):
        if run.run_id == identifier:
            return run.run_dir
    raise RunNotFoundError(candidate)


def render_run_list(runs: list[RunListing]) -> str:
    """`axial runs list`'s table: what each run was, when it started, how
    it ended, and whether it is alive right now -- `list_runs`'s own newest-
    first order, unchanged."""
    if not runs:
        return "no runs recorded"
    header = f"{'run_id':<42}{'status':<10}{'alive':<7}{'started_at':<34}finished_at"
    lines = [header]
    for run in runs:
        lines.append(
            f"{run.run_id:<42}{run.status:<10}{str(run.alive):<7}"
            f"{run.started_at:<34}{run.finished_at or ''}"
        )
    return "\n".join(lines)


def render_run_view(view: RunView) -> str:
    """`axial runs show <run>`'s report: `meta.json` plus a tally of
    `run.jsonl`'s outcomes and every failure's own reason -- re-readable at
    any point during or after the run, same as `load_run` itself."""
    meta = view.meta
    lines = [
        f"run_id: {meta.get('run_id')}",
        f"name: {meta.get('name')}",
        f"command: {meta.get('command')}",
        f"corpus_pin: {meta.get('corpus_pin')}",
        f"status: {meta.get('status')}{' (alive)' if view.alive else ''}",
        f"started_at: {meta.get('started_at')}",
        f"finished_at: {meta.get('finished_at') or 'not finished'}",
    ]
    if view.heartbeat_age_sec is not None:
        lines.append(f"heartbeat age: {format_duration(view.heartbeat_age_sec)}")

    tallies: dict[str, int] = {}
    for record in view.records:
        tallies[record.get("status", "?")] = tallies.get(record.get("status", "?"), 0) + 1
    summary = ", ".join(f"{status}: {count}" for status, count in sorted(tallies.items()))
    lines.append(f"records: {len(view.records)} ({summary})" if summary else "records: none yet")
    lines.append(f"events: {len(view.events)}")

    failures = [r for r in view.records if r.get("status") == "FAIL"]
    if failures:
        lines.append("failed:")
        for r in failures:
            reason = r.get("error") or "(no reason recorded)"
            lines.append(f"  {r.get('pass')}  {r.get('source_id')}: {reason}")

    return "\n".join(lines)


def render_follow_line(item: dict[str, Any]) -> str:
    """One `follow_run` item, rendered for a terminal tailing a live run."""
    stream = item.get("stream")
    if stream == "status":
        return f"[status] {item.get('status')}"
    if stream == "event":
        parts = [
            item.get("ts") or "",
            item.get("kind") or "",
            item.get("source_id") or "",
            item.get("pass") or "",
            item.get("detail") or "",
        ]
        return "[event]  " + "  ".join(p for p in parts if p)
    parts = [
        item.get("pass") or "",
        item.get("source_id") or "",
        item.get("status") or "",
        item.get("error") or "",
    ]
    return "[record] " + "  ".join(p for p in parts if p)
