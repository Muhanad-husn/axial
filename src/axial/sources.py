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

Both backends report the same status vocabulary for every listed item:

- **new** -- never seen before.
- **changed** -- seen under this name/path (local) or Drive file id before,
  different content.
- **done** -- already fully processed; ingesting it again is a no-op.
- **partial** -- SOME but not all per-source artifacts exist; names what is
  missing, since that is what tells the operator a run died halfway
  (local backend only -- Drive's fetch-state manifest has no equivalent
  partial state, a candidate either has a recorded successful fetch+ingest
  or it does not).
- **rejected** -- named, with a reason: wrong file type (both backends), or
  Drive's English-only language gate (`axial.drive`'s P0-11c).

**The artifacts are the truth, the ledger is a fast path (issue #528,
measured live 2026-08-02).** A first cut of `scan_local` trusted the ledger
alone and, run against the real 31-source corpus, reported every one of
them `new` -- proposing to re-ingest a corpus that is fully processed, at
the ~$35 cost the founder is explicitly holding off. Two real conditions
caused it: the unified ledger this module reads (`data/run/ledger.tsv`)
had never actually been written on that corpus (only an unrelated
`ledger-extract.tsv` from an earlier run existed), and even where a ledger
row exists, it can be keyed by a RETIRED `source_id` format (the old
long-filename form, before the author-year rename) that will never match
what `compute_source_id` returns today. Per this project's own first
principle, a rule that produces an obviously wrong answer loses to the
obvious one: every one of those 31 sources has an envelope, a chunk
checkpoint, a structural tree, interrogation answers and an artifact
record on disk, so `scan_local` now checks for those files directly and
trusts the ledger's OK row only as a shortcut when it is present and
agrees -- never as the sole signal. Checking is five `Path.exists()` calls
per source, not a parse of any artifact's contents, so this stays cheap at
corpus scale.

Ingesting means running the alive per-source pass chain
(`DEFAULT_INGEST_PASSES`) over whatever scan reports NEW or CHANGED. A plain
re-run does no pipeline work and says so, because each pass's own
done-predicate (`axial.run.PASS_REGISTRY`) already skips whatever the ledger
shows as finished -- `sync_local` never reimplements that skip logic, it
just calls `axial.run.run_pass` once per pass.

`DEFAULT_DONE_PASS = "artifacts"`, not `"vault-write"`: `axial.vault.
run_vault_write` is currently retired (`VaultWriteRetiredError`, issue
#411) and unconditionally fails, so treating it as the local backend's
completion signal would mark every source `rejected` forever -- obviously
wrong, not a real gate rejection. `artifacts` is the last pass in the
registry that still does real per-source work end to end today; when
vault-write is un-retired, moving this one constant is the whole fix.

It was `"interrogate"` until issue #623, which is the same edit as adding
`artifacts` to `DEFAULT_INGEST_PASSES` below: the done-pass and the chain
have to name the same finish line, or the ledger fast path below reports a
source `done` on a pass that is no longer the last one.

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
from typing import Callable, Iterable

import yaml

import axial.artifacts as _artifacts_mod
import axial.chunk as _chunk_mod
import axial.envelope as _envelope_mod
import axial.extract as _extract_mod
import axial.interrogate as _interrogate_mod
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
PARTIAL = "partial"
REJECTED = "rejected"

# The last pass in axial.run.PASS_REGISTRY that still runs end to end (see
# module docstring for why this is not "vault-write").
DEFAULT_DONE_PASS = "artifacts"

# The alive per-source chain `sync_local` drives, in order -- every
# registered pass up to and including DEFAULT_DONE_PASS, excluding the
# retired "vault-write" (module docstring).
#
# `artifacts` joined this chain in issue #623, after the first real "add books
# to a finished corpus" run left three new sources with no table/figure notes
# while the other 31 had theirs: materialize reported `artifact_sources: 31`
# against 34 sources. The pass was registered and alive the whole time, it was
# simply never in the chain, so `axial sources` called a source `done` that had
# no artifact record at all. It is deterministic and makes no model call
# (issue #429 removed the classification call), so it costs nothing to include.
DEFAULT_INGEST_PASSES = ("extract", "envelope", "chunk", "interrogate", "artifacts")

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


# The five per-source artifacts a fully-processed source has on disk, in the
# order §5's pipeline produces them (module docstring's "the artifacts are
# the truth"). Each entry is a `(name, path_fn)` pair; `path_fn(source_id,
# config_path)` returns that artifact's path -- never its parsed contents,
# so `_artifact_status` below stays a handful of `Path.exists()` calls per
# source, cheap at corpus scale (the two constraints issue #528 was built
# against: instant on 31 sources, and no read past a stat).
#
# Every lambda reaches its constant/resolver through the MODULE (`_extract_
# mod.TREES_DIR`, not a bare `TREES_DIR` name or a function's own default
# parameter value) so a test that isolates its data dirs by monkeypatching
# that module -- `axial.chunk.CHUNKS_DIR` etc., the established pattern in
# `src/axial/conftest.py`'s `_isolate_checkpoint_dirs` fixture -- is honored
# here too. A default parameter value is bound once at import time and would
# not be.
_ARTIFACT_PATH_FNS: tuple[tuple[str, Callable[[str, Path], Path]], ...] = (
    (
        "tree",
        lambda source_id, config_path: _extract_mod.tree_path(source_id, _extract_mod.TREES_DIR),
    ),
    (
        "envelope",
        lambda source_id, config_path: _envelope_mod.envelope_path(
            source_id, _envelope_mod._default_envelopes_dir(config_path)
        ),
    ),
    (
        "chunks",
        lambda source_id, config_path: _chunk_mod.chunks_checkpoint_path(
            source_id, _chunk_mod._default_chunks_dir(config_path)
        ),
    ),
    (
        "answers",
        lambda source_id, config_path: _interrogate_mod.answers_checkpoint_path(
            source_id, _interrogate_mod._default_answers_dir(config_path)
        ),
    ),
    (
        "artifacts",
        lambda source_id, config_path: _artifacts_mod.artifacts_checkpoint_path(
            source_id, _artifacts_mod._default_artifacts_dir(config_path)
        ),
    ),
)


def _artifact_status(source_id: str, config_path: Path) -> tuple[str, str]:
    """Whether `source_id` is DONE, PARTIAL, or NEW by what is actually on
    disk (module docstring): every one of the four `_ARTIFACT_PATH_FNS`
    present is DONE; none present is NEW (the caller still has the ledger's
    own CHANGED-vs-NEW history to consult in that case); some but not all is
    PARTIAL, its reason naming exactly which are missing -- "a run died
    halfway" is diagnostic information, not something to flatten away."""
    missing = [
        name for name, path_fn in _ARTIFACT_PATH_FNS if not path_fn(source_id, config_path).exists()
    ]
    if not missing:
        return DONE, ""
    if len(missing) == len(_ARTIFACT_PATH_FNS):
        return NEW, ""
    return PARTIAL, f"missing: {', '.join(missing)}"


def scan_local(
    sources_dir: Path = CORPUS_SOURCES_DIR,
    ledger_path: Path = LEDGER_PATH,
    *,
    done_pass: str = DEFAULT_DONE_PASS,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[SourceRecord]:
    """The local folder backend's report (module docstring): one
    `SourceRecord` per file directly under `sources_dir`, sorted by name.

    A file whose extension isn't one of `axial.run.CORPUS_EXTENSIONS` is
    `rejected` ("unsupported file type") without ever computing a
    `source_id` -- the same candidate filter Drive applies before download,
    made visible here instead of silently excluding the file from the
    corpus glob.

    Otherwise: the ledger is consulted FIRST, as a fast path -- an OK row
    for the current `source_id` under `done_pass` is trusted as `done`
    without touching disk again. When the ledger does not agree (no such
    row -- absent ledger, stale id format, or a genuine first run), the
    file's four per-source artifacts (`_ARTIFACT_PATH_FNS`) are the actual
    source of truth: all four present is `done` regardless of what the
    ledger said or failed to say; some but not all is `partial`, naming
    what is missing; none present falls back to the ledger's own path
    history to tell `new` from `changed` -- any row at all for this path
    under a *different* `source_id` is `changed` (the path was seen before,
    the bytes were not), anything else is `new`.

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

        # Fast path: the ledger already agrees this exact content is done --
        # skip the artifact stats entirely.
        if any(row.get("status") == OK_STATUS for row in matching):
            records.append(SourceRecord(path.name, DONE))
            continue

        # The ledger is silent or disagrees (issue #528: it can be entirely
        # absent while the corpus is fully processed) -- the artifacts on
        # disk are what actually answer the question.
        status, reason = _artifact_status(source_id, config_path)
        if status == DONE:
            records.append(SourceRecord(path.name, DONE))
        elif status == PARTIAL:
            records.append(SourceRecord(path.name, PARTIAL, reason))
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
