"""`axial sources`: one command, two backends, the same "what is new"
answer (issue #528).

`axial.drive` already keeps an incremental fetch-state manifest for the
Google Drive backend (`id -> {modifiedTime, md5Checksum, fetched_at}`), so a
re-run only downloads and ingests what is new or changed, and a rejected
candidate gets no manifest entry so it is re-examined -- never silently
skipped -- next time (see that module's docstring). That is exactly the
"recognise what was added" behaviour the local folder never had.

This module gives the LOCAL folder backend the same view, computed from the
runner's own resume ledger (`axial.run.LEDGER_PATH`) rather than a second,
parallel manifest: a source's `source_id` is content-derived
(`axial.envelope.compute_source_id`, filename stem + a hash of the bytes),
so the ledger a corpus-wide `axial run <pass>` already writes answers
"have I seen these exact bytes under this path before, and did the pipeline
finish" without any new bookkeeping.

Both backends report the same four-way status for every listed item:

- **new** -- never seen before.
- **changed** -- seen under this name/path (local) or Drive file id before,
  different content.
- **done** -- already fully processed; ingesting it again is a no-op.
- **rejected** -- named, with a reason: wrong file type (both backends), or
  Drive's English-only language gate (`axial.drive`'s P0-11c).

Ingesting means running the alive per-source pass chain
(`DEFAULT_INGEST_PASSES`) over whatever scan reports NEW or CHANGED. A plain
re-run does no pipeline work and says so, because each pass's own
done-predicate (`axial.run.PASS_REGISTRY`) already skips whatever the ledger
shows as finished -- `sync_local` never reimplements that skip logic, it
just calls `axial.run.run_pass` once per pass.

`DEFAULT_DONE_PASS = "interrogate"`, not `"vault-write"`: `axial.vault.
run_vault_write` is currently retired (`VaultWriteRetiredError`, issue
#411) and unconditionally fails, so treating it as the local backend's
completion signal would mark every source `rejected` forever -- obviously
wrong, not a real gate rejection. `interrogate` is the last pass in the
registry that still does real per-source work end to end today; when
vault-write is un-retired, moving this one constant is the whole fix.

`axial sources --check` (issue #528, CLI: `src/axial/cli.py`'s `_sources_
local`/`_sources_drive`) asks the question without committing to the
action: it prints the same report and stops. On this backend, `scan_local`
already IS that report -- it never writes anything and never calls
`sync_local`, so a checked run costs one ledger read, full stop. The Drive
backend cannot make the same promise (a Drive `--check` still downloads a
new/changed candidate's bytes to run the language gate -- see
`axial.drive.run_drive_sources`'s own docstring); this module's own
report/ingest split is what makes the local side free.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from axial.envelope import MissingSourceError, compute_source_id
from axial.llm import LLMClient
from axial.paths import DEFAULT_DOMAIN_DIR, DEFAULT_PIPELINE_CONFIG_PATH
from axial.run import (
    CORPUS_EXTENSIONS,
    CORPUS_SOURCES_DIR,
    LEDGER_PATH,
    OK_STATUS,
    RunSummary,
    run_pass,
)
from axial.yaml_loader import SAFE_LOADER

NEW = "new"
CHANGED = "changed"
DONE = "done"
REJECTED = "rejected"

# The last pass in axial.run.PASS_REGISTRY that still runs end to end (see
# module docstring for why this is not "vault-write").
DEFAULT_DONE_PASS = "interrogate"

# The alive per-source chain `sync_local` drives, in order -- every
# registered pass up to and including DEFAULT_DONE_PASS, excluding the
# retired "vault-write" (module docstring).
DEFAULT_INGEST_PASSES = ("extract", "envelope", "chunk", "interrogate")

# The operator's one-time backend choice (config/pipeline.yaml's `sources:`
# block), falling back to "local" when the file or key is absent --
# mirrors axial.drive._language_gate_config's config-with-fallback pattern.
DEFAULT_BACKEND = "local"

REPORT_COLUMNS = ("name", "status", "reason")


@dataclass(frozen=True)
class SourceRecord:
    """One listed item's status, in the vocabulary every backend shares
    (module docstring). `reason` is empty except for REJECTED."""

    name: str
    status: str
    reason: str = ""


def render_report(records: Iterable[SourceRecord]) -> str:
    """The report table both backends print: a header row plus one row per
    listed item, tab-separated -- mirrors axial.run's own TABLE_COLUMNS
    convention (header + one row per source, columns looked up by name)."""
    lines = ["\t".join(REPORT_COLUMNS)]
    for record in records:
        lines.append("\t".join((record.name, record.status, record.reason)))
    return "\n".join(lines)


def resolve_backend(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> str:
    """The configured backend name ("local" or "drive") from `config_path`'s
    `sources:` block, falling back to DEFAULT_BACKEND when the file, the
    block, or the key is absent."""
    if not config_path.is_file():
        return DEFAULT_BACKEND
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
    section = document.get("sources", {}) or {}
    return section.get("backend", DEFAULT_BACKEND)


def _read_ledger_rows(ledger_path: Path, pass_name: str) -> list[dict[str, str]]:
    """Every ledger row recorded for `pass_name`, in file order. An absent
    ledger yields no rows -- nothing has ever run (mirrors axial.run.
    _load_done_source_ids's own "absent ledger = empty" convention)."""
    if not ledger_path.exists():
        return []
    with ledger_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [row for row in reader if row.get("pass") == pass_name]


def scan_local(
    sources_dir: Path = CORPUS_SOURCES_DIR,
    ledger_path: Path = LEDGER_PATH,
    *,
    done_pass: str = DEFAULT_DONE_PASS,
) -> list[SourceRecord]:
    """The local folder backend's report (module docstring): one
    `SourceRecord` per file directly under `sources_dir`, sorted by name.

    A file whose extension isn't one of `axial.run.CORPUS_EXTENSIONS` is
    `rejected` ("unsupported file type") without ever computing a
    `source_id` -- the same candidate filter Drive applies before download,
    made visible here instead of silently excluding the file from the
    corpus glob. Otherwise the file's current content-derived `source_id` is
    looked up against `done_pass`'s own ledger rows for this exact path:
    an OK row for the current `source_id` is `done`; any row at all for this
    path under a *different* `source_id` is `changed` (the path was seen
    before, the bytes were not); anything else -- never seen, or seen only
    as a prior FAIL under this same `source_id` -- is `new`, eligible for
    (re)ingest. A FAIL row is deliberately not its own `rejected` status:
    like Drive's own chain-error handling, a pipeline failure leaves the
    file retryable, not gated out (module docstring's `rejected` is reserved
    for a type check or a gate, mirroring Drive's own vocabulary of
    `reject:` vs. `error:`).

    An absent `sources_dir` yields an empty list -- nothing to report.
    """
    if not sources_dir.is_dir():
        return []

    rows_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_ledger_rows(ledger_path, done_pass):
        rows_by_path[row.get("source_path", "")].append(row)

    records: list[SourceRecord] = []
    files = sorted((path for path in sources_dir.iterdir() if path.is_file()), key=lambda p: p.name)
    for path in files:
        if path.suffix.lower() not in CORPUS_EXTENSIONS:
            records.append(
                SourceRecord(path.name, REJECTED, f"unsupported file type {path.suffix!r}")
            )
            continue

        try:
            source_id = compute_source_id(path)
        except MissingSourceError as exc:
            records.append(SourceRecord(path.name, REJECTED, str(exc)))
            continue

        path_rows = rows_by_path.get(str(path), [])
        matching = [row for row in path_rows if row.get("source_id") == source_id]
        if any(row.get("status") == OK_STATUS for row in matching):
            records.append(SourceRecord(path.name, DONE))
        elif path_rows and not matching:
            records.append(SourceRecord(path.name, CHANGED))
        else:
            records.append(SourceRecord(path.name, NEW))

    return records


def sync_local(
    sources_dir: Path = CORPUS_SOURCES_DIR,
    ledger_path: Path = LEDGER_PATH,
    *,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    passes: tuple[str, ...] = DEFAULT_INGEST_PASSES,
) -> list[RunSummary]:
    """Ingest whatever `scan_local` reports NEW or CHANGED: run each of
    `passes` in order, corpus-wide, via `axial.run.run_pass` -- never a
    second ingestion mechanism. `run_pass` already resumes from its own
    ledger/file-exists done-predicates, so a source already finished for a
    given pass does zero work for it (no invocation, no LLM call); calling
    this with nothing new or changed prints each pass's own "nothing to do"
    or all-skip summary and performs no pipeline work.

    The shared `client` is threaded into every pass's `run_pass` call so it
    is built once for the whole sync, not once per pass."""
    summaries: list[RunSummary] = []
    for pass_name in passes:
        summary, _exit_code = run_pass(
            pass_name,
            client=client,
            config_path=config_path,
            domain_dir=domain_dir,
            ledger_path=ledger_path,
            corpus=True,
            sources_dir=sources_dir,
        )
        summaries.append(summary)
    return summaries
