"""Ingest: drives `axial.vault.run_vault_write` over a worklist of source
paths, one source at a time, recreating the operator-owned
`data/gold/ingest_worker.sh` round-robin loop as a tested, first-class CLI
subcommand (`axial ingest <worklist>`) -- see issue #119 and its parent
postmortem `docs/postmortem/gold-run-2026-07/README.md` ("root cause D. No
failure isolation... the worker loop re-runs finished work").

The core behavior this issue adds, missing from the original script: a skip
guard. At the top of the per-source loop, if that source's own computed
`source_id` (`axial.envelope.compute_source_id`, content-derived, never
guessed) already appears in the persistent results file
(`data/gold/ingest.results.tsv` by default) with `vault_status=OK`, this pass
logs exactly one `skip: <source> already ingested` line naming it and
performs NO pipeline work for it at all -- it is neither re-read, re-chunked,
re-tagged, nor re-written to the vault. Every other source is ingested via
the existing `axial.vault.run_vault_write` (the same internal pipeline
`axial vault write` already drives: chunk -> tag -> artifacts -> xref ->
vault), and one new row is appended to the results file recording the
outcome -- an APPEND, never an overwrite, so a pre-seeded row for an
already-completed source survives byte-for-byte untouched (this is the
locked outer test's own strongest check, tests/test_ingest.py seam decision
6).

A per-source pipeline failure (any `axial.vault.VaultError`) records
`vault_status=FAIL` for that source and the loop continues to the next
source -- one bad source never aborts the whole worklist. The overall
process exits 0 in that case; it only exits non-zero for a FATAL error that
prevents the loop from running at all (the worklist file itself unreadable,
or the results file un-appendable), mirroring PRD-level guidance that a
per-source failure is expected, recoverable operator signal, not a crash.
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axial.envelope import MissingSourceError as _EnvelopeMissingSourceError, compute_source_id
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.tag import DEFAULT_DOMAIN_DIR
from axial.vault import VaultError, run_vault_write

# Persistent results file (issue #119's own contract): appended to, never
# overwritten, across every `axial ingest` invocation -- a plain path
# relative to the process cwd, mirroring every other module-level default in
# this codebase (e.g. `axial.gold.GOLD_DIR`, `axial.vault.VAULT_DIR`).
RESULTS_PATH = Path("data/gold/ingest.results.tsv")

RESULTS_COLUMNS = (
    "source_path",
    "source_id",
    "vault_status",
    "notes_count",
    "duration_sec",
    "exit_code",
    "timestamp",
)

OK_STATUS = "OK"
FAIL_STATUS = "FAIL"


class IngestError(Exception):
    """Base class for fatal ingest errors -- ones that stop the whole
    worklist, as opposed to a single source's `VaultError`, which is caught
    per-source and recorded as a `FAIL` row (see module docstring)."""


class WorklistError(IngestError):
    """Raised when the worklist file itself cannot be read."""

    def __init__(self, path: Path, cause: Exception | None = None):
        self.path = path
        self.cause = cause
        message = f"cannot read worklist {path}"
        if cause is not None:
            message = f"{message}: {cause}"
        super().__init__(message)


class ResultsFileError(IngestError):
    """Raised when the persistent results file cannot be read or appended
    to."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"cannot access results file {path}: {cause}")


def read_worklist(worklist_path: str | Path) -> list[str]:
    """Read a line-delimited worklist of source paths: one non-blank,
    stripped line per source, blank lines skipped. Raises `WorklistError` if
    the file does not exist or cannot be read."""
    path = Path(worklist_path)
    if not path.is_file():
        raise WorklistError(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorklistError(path, exc) from exc
    return [line.strip() for line in text.splitlines() if line.strip()]


def _load_completed_source_ids(results_path: Path) -> set[str]:
    """The set of `source_id`s that already carry a `vault_status=OK` row in
    `results_path` -- the skip guard's own precondition (module docstring).
    An absent results file has no completed sources yet."""
    if not results_path.exists():
        return set()
    try:
        with results_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            return {
                row["source_id"]
                for row in reader
                if row.get("vault_status") == OK_STATUS and row.get("source_id")
            }
    except OSError as exc:
        raise ResultsFileError(results_path, exc) from exc


def _append_result_row(results_path: Path, row: dict[str, Any]) -> None:
    """Append one row to `results_path`, writing a header first if the file
    does not exist yet (module docstring: APPEND, never overwrite)."""
    try:
        results_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = results_path.exists()
        with results_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULTS_COLUMNS, delimiter="\t")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except OSError as exc:
        raise ResultsFileError(results_path, exc) from exc


def run_ingest(
    worklist_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    results_path: Path | None = None,
    chunks_dir: Path | None = None,
    tags_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    xref_dir: Path | None = None,
) -> int:
    """Drive `axial.vault.run_vault_write` over every source path named in
    `worklist_path`, skipping any source whose `source_id` already carries a
    `vault_status=OK` row in the persistent results file (module docstring).
    Appends one results row per NON-skipped source. Returns 0 unless a fatal
    error prevents the loop from running at all (an unreadable worklist or an
    inaccessible results file); a per-source pipeline failure is recorded as
    a `FAIL` row and does not affect the overall exit code."""
    if results_path is None:
        results_path = RESULTS_PATH

    try:
        source_paths = read_worklist(worklist_path)
    except WorklistError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        completed_source_ids = _load_completed_source_ids(results_path)
    except ResultsFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for source_path_str in source_paths:
        source_path = Path(source_path_str)

        try:
            source_id = compute_source_id(source_path)
        except _EnvelopeMissingSourceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue

        if source_id in completed_source_ids:
            print(f"skip: {source_path} already ingested (source_id={source_id})")
            continue

        start = time.monotonic()
        try:
            written = run_vault_write(
                source_path,
                client=client,
                envelopes_dir=envelopes_dir,
                vault_dir=vault_dir,
                config_path=config_path,
                domain_dir=domain_dir,
                chunks_dir=chunks_dir,
                tags_dir=tags_dir,
                artifacts_dir=artifacts_dir,
                xref_dir=xref_dir,
            )
            vault_status = OK_STATUS
            notes_count = len(written)
            exit_code = 0
        except VaultError as exc:
            print(f"error: {exc}", file=sys.stderr)
            vault_status = FAIL_STATUS
            notes_count = 0
            exit_code = 1
        duration_sec = time.monotonic() - start

        row = {
            "source_path": str(source_path),
            "source_id": source_id,
            "vault_status": vault_status,
            "notes_count": str(notes_count),
            "duration_sec": f"{duration_sec:.3f}",
            "exit_code": str(exit_code),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _append_result_row(results_path, row)
        except ResultsFileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        if vault_status == OK_STATUS:
            completed_source_ids.add(source_id)

    return 0
