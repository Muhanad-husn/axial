"""Corpus-wide pass runner: drives one registered per-source pass over a
worklist of source paths, one source at a time, with per-source failure
isolation and a single unified resume ledger (issue #277; slice 01
`plans/run/01-runner-core-and-failure-isolation.md`, slice 02
`plans/run/02-unified-resume-ledger.md`).

This is `axial run <pass> --worklist <file>`. It generalizes
`axial.ingest.run_ingest`'s proven loop shape -- read the source set, skip
what is already done, run one source, record an outcome, continue on
failure, exit non-zero only when the loop itself cannot run -- from one
hard-wired pass (`run_vault_write`, caught only for `VaultError`) to any
pass in the **pass registry**: a plain dict mapping a pass name to a small
descriptor carrying that pass's per-source callable, the `*Error` base it
declares, and its **done-predicate**. This is the retirement path for the
bare-`except Exception` loop wrapper the postmortem named as root cause D --
every registered pass's OWN declared error type is now what gets caught,
never a catch-all.

Slice 02 adds the runner's own resume ledger -- one TSV, `data/run/
ledger.tsv` by default, keyed by `(pass, source_id)` -- and a
`done_predicate` field on each pass descriptor: a small function answering
"is this source_id already done for this pass?" Before invoking a pass, the
loop asks the predicate; a source it reports done is skipped doing zero
pipeline work -- no invocation, no LLM call, no output rewrite -- logging
one `skip: <source> already done (<pass>)` line. `extract` and `envelope`
declare a file-exists predicate over their own persisted-output cache (the
README's mechanism 2); every other registered pass declares the ledger
predicate (the README's mechanisms 1 and 3, now unified into one ledger the
runner owns). Every non-skipped source appends exactly one outcome row to
the ledger -- an APPEND, never an overwrite, reusing `axial.ingest`'s TSV
discipline (`_append_result_row`/`_load_completed_source_ids`) verbatim in
shape.

Slice 03 (`plans/run/03-source-sets-and-run-summary.md`) adds the second
**source set**: `--corpus`, every `data/sources/*.pdf`/`*.docx` file in
sorted (deterministic) order, as an alternative to `--worklist`. Exactly one
source set is required per run -- both or neither is a fatal `SourceSetError`
before any source is touched. It also formalizes the end-of-run summary this
module already printed (a tally line of OK/FAIL/SKIP counts) into a
structured in-process value, `RunSummary`, that `run_pass` returns alongside
the exit code -- so a consumer (#270's log emitter, #288's not-applicable/
unlisted rates report) can attach to it without reaching into runner
internals. `RunSummary.rates` is the named attachment point for #288; this
slice leaves it `None` and never computes it.

Out of scope for this slice too (see the plan): the #270 run-log emitter and
the #288 rates report; parallelism; cross-pass chaining; reaching into the
per-chunk `.jsonl` checkpoints inside tag/artifacts/xref -- a pass's
done-predicate may consult its own checkpoints internally, but this module
neither replaces nor reaches into them (source-level resume only); recursive
or configurable corpus roots beyond the single `data/sources/` glob.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from axial.artifacts import ArtifactsError, run_artifacts
from axial.chunk import ChunkError, run_chunk_recursive
from axial.envelope import (
    EnvelopeError,
    MissingSourceError,
    _default_envelopes_dir,
    compute_source_id,
    envelope_path,
    run_envelope,
)
from axial.extract import ExtractError, extract, tree_path
from axial.ingest import WorklistError, read_worklist
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient, get_client
from axial.tag import DEFAULT_DOMAIN_DIR, TagError, run_tag
from axial.vault import VaultError, run_vault_write
from axial.xref import XrefError, run_xref

OK_STATUS = "OK"
FAIL_STATUS = "FAIL"
SKIP_STATUS = "SKIP"

# The runner-owned resume ledger (module docstring): one TSV, appended to,
# never overwritten, across every `axial run` invocation -- mirrors
# `axial.ingest.RESULTS_PATH`'s convention exactly, generalized from one
# hard-wired pass to a `pass` column so every registered pass shares the
# same file, keyed by `(pass, source_id)`.
#
# It lives under `data/run/`, not `data/logs/`, deliberately: `data/logs/`
# holds one directory per run (`<date>-<run-name>/`, the run-logging
# convention), and this is the opposite -- one file that outlives every run
# and is read at the START of the next one. It is runner state, a peer of
# `data/trees/` and `data/envelopes/`, not a log.
LEDGER_PATH = Path("data/run/ledger.tsv")

LEDGER_COLUMNS = ("pass", "source_path", "source_id", "status", "reason", "timestamp")

# The printed per-source outcome table's column order (mirrors
# axial.pipeline_ready.TABLE_COLUMNS's convention: a header row + one row per
# source, columns looked up by name -- never by position). `reason` is empty
# for an OK outcome.
TABLE_COLUMNS = ("source_path", "source_id", "status", "reason")

# The corpus source set's root (slice 03) -- a plain path relative to the
# process cwd, mirroring every other module-level default in this codebase
# (LEDGER_PATH above, axial.reconcile.SOURCES_DIR, axial.ingest.RESULTS_PATH).
CORPUS_SOURCES_DIR = Path("data/sources")

# The two documented extensions the corpus glob matches (plan's out-of-scope
# note: "one corpus root, the two documented extensions" -- no config option
# for this, since nothing today needs a third).
CORPUS_EXTENSIONS = (".pdf", ".docx")


class RunError(Exception):
    """Base class for fatal run errors -- ones that stop the whole worklist
    before any source is attempted, as opposed to one source's own declared
    pass error, which is caught per source and recorded as a FAIL outcome
    (module docstring)."""


class UnknownPassError(RunError):
    """Raised when the requested pass name is absent from `PASS_REGISTRY`."""

    def __init__(self, pass_name: str):
        self.pass_name = pass_name
        known = ", ".join(sorted(PASS_REGISTRY))
        super().__init__(f"unknown pass {pass_name!r}; known passes: {known}")


class LedgerError(RunError):
    """Raised when the runner-owned resume ledger cannot be read or appended
    to -- fatal, mirroring `axial.ingest.ResultsFileError` (module
    docstring: an unappendable ledger stops the loop, exactly like an
    unappendable results file stops `run_ingest`)."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"cannot access ledger {path}: {cause}")


class SourceSetError(RunError):
    """Raised when the requested source set is invalid: `--worklist` and
    `--corpus` given together, or neither given (module docstring: exactly
    one source set is required per run) -- fatal, before any source is
    touched."""

    def __init__(self, worklist_given: bool, corpus_given: bool):
        self.worklist_given = worklist_given
        self.corpus_given = corpus_given
        if worklist_given and corpus_given:
            message = "--worklist and --corpus are mutually exclusive; supply exactly one"
        else:
            message = "exactly one source set is required: --worklist <file> or --corpus"
        super().__init__(message)


@dataclass(frozen=True)
class Outcome:
    """One source's recorded in-process outcome: OK, FAIL, or SKIP, with a
    short reason (DEC-23: ids, statuses, and short reasons only, never source
    text)."""

    source_path: str
    source_id: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class RunSummary:
    """The end-of-run summary (slice 03): a structured in-process value
    `run_pass` returns and prints, so a consumer (#270's log emitter, #288's
    not-applicable/unlisted rates report) can attach to it without reaching
    into runner internals. `outcomes` carries every attempted source's row
    (DEC-23: ids, statuses, counts, and short reasons only, never source
    text); the OK/FAIL/SKIP counts always sum to `total`.

    `rates` is the named attachment point for #288's not-applicable/unlisted
    rates report -- always `None` here; this slice defines the seam, #288
    computes and fills it. Nothing in this module reads or writes it beyond
    this default."""

    pass_name: str
    outcomes: list[Outcome]
    total: int
    ok_count: int
    fail_count: int
    skip_count: int
    rates: Any | None = None


def _empty_summary(pass_name: str) -> RunSummary:
    """The summary returned alongside a fatal exit (unknown pass, invalid
    source set, unreadable worklist, unappendable ledger) -- no source was
    ever attempted."""
    return RunSummary(pass_name, [], 0, 0, 0, 0)


@dataclass(frozen=True)
class PassDescriptor:
    """One registered pass: its per-source invoker, the `*Error` base it
    raises, and its done-predicate. `invoke` normalizes every pass's own
    differently-shaped entrypoint (some take no client, some no domain_dir --
    see each pass module) behind one uniform `(source_path, client,
    config_path, domain_dir)` call shape, so the runner loop never
    special-cases a pass by name. `done_predicate` is likewise uniform --
    `(source_id, ledger_done_ids, config_path) -> bool` -- whether a pass's
    own natural done-signal is a persisted-output file (extract, envelope)
    or the runner's own ledger (every other pass): the loop calls it the same
    way regardless (module docstring)."""

    name: str
    invoke: Callable[[str, LLMClient | None, Path, str | Path], Any]
    error: type[Exception]
    done_predicate: Callable[[str, set[str], Path], bool]


def _invoke_extract(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    return extract(source_path)


def _invoke_envelope(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    return run_envelope(source_path, client=client, config_path=config_path)


def _invoke_chunk(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    return run_chunk_recursive(source_path, config_path=config_path, client=client)


def _invoke_tag(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    return run_tag(source_path, client=client, config_path=config_path, domain_dir=domain_dir)


def _invoke_artifacts(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    return run_artifacts(source_path, client=client, domain_dir=domain_dir, config_path=config_path)


def _invoke_xref(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    return run_xref(source_path, client=client, domain_dir=domain_dir, config_path=config_path)


def _invoke_vault_write(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    return run_vault_write(
        source_path, client=client, config_path=config_path, domain_dir=domain_dir
    )


def _tree_done_predicate(source_id: str, ledger_done_ids: set[str], config_path: Path) -> bool:
    """extract's own done-signal: its persisted tree already exists at
    `data/trees/<source_id>.json` (module docstring's mechanism 2)."""
    return tree_path(source_id).exists()


def _envelope_done_predicate(source_id: str, ledger_done_ids: set[str], config_path: Path) -> bool:
    """envelope's own done-signal: its persisted envelope already exists at
    `data/envelopes/<source_id>.json` (module docstring's mechanism 2)."""
    envelopes_dir = _default_envelopes_dir(config_path)
    return envelope_path(source_id, envelopes_dir).exists()


def _ledger_done_predicate(source_id: str, ledger_done_ids: set[str], config_path: Path) -> bool:
    """The runner-owned ledger's own done-signal (module docstring's
    mechanisms 1 and 3, now unified): an OK row already recorded for this
    `(pass, source_id)`. `ledger_done_ids` is loaded once per `run_pass`
    call, not re-read per source."""
    return source_id in ledger_done_ids


# The pass registry (module docstring): a plain dict, not a plugin system --
# seven known passes, all in this repo, each with a `(source_path, client,
# config_path, domain_dir)`-shaped invoker (via the `_invoke_*` adapters
# above), the `*Error` base it declares, and its done-predicate. extract and
# envelope declare their own persisted-output file as the done-signal; every
# other pass -- lacking a single atomic per-source output file, since
# chunk/tag/artifacts/xref checkpoint per-chunk, a finer granularity this
# runner does not reach into (module docstring) -- declares the runner's own
# ledger.
PASS_REGISTRY: dict[str, PassDescriptor] = {
    "extract": PassDescriptor("extract", _invoke_extract, ExtractError, _tree_done_predicate),
    "envelope": PassDescriptor(
        "envelope", _invoke_envelope, EnvelopeError, _envelope_done_predicate
    ),
    "chunk": PassDescriptor("chunk", _invoke_chunk, ChunkError, _ledger_done_predicate),
    "tag": PassDescriptor("tag", _invoke_tag, TagError, _ledger_done_predicate),
    "artifacts": PassDescriptor(
        "artifacts", _invoke_artifacts, ArtifactsError, _ledger_done_predicate
    ),
    "xref": PassDescriptor("xref", _invoke_xref, XrefError, _ledger_done_predicate),
    "vault-write": PassDescriptor(
        "vault-write", _invoke_vault_write, VaultError, _ledger_done_predicate
    ),
}


def _render_row(outcome: Outcome) -> str:
    row = {
        "source_path": outcome.source_path,
        "source_id": outcome.source_id,
        "status": outcome.status,
        "reason": outcome.reason,
    }
    return "\t".join(row[column] for column in TABLE_COLUMNS)


def _load_done_source_ids(ledger_path: Path, pass_name: str) -> set[str]:
    """The set of `source_id`s that already carry an OK row for `pass_name`
    in the ledger (module docstring's done-predicate precondition; mirrors
    `axial.ingest._load_completed_source_ids`, generalized with a `pass`
    filter since one ledger now serves every pass). An absent ledger yields
    an empty done-set -- nothing skipped."""
    if not ledger_path.exists():
        return set()
    try:
        with ledger_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            return {
                row["source_id"]
                for row in reader
                if row.get("pass") == pass_name
                and row.get("status") == OK_STATUS
                and row.get("source_id")
            }
    except OSError as exc:
        raise LedgerError(ledger_path, exc) from exc


def _append_ledger_row(ledger_path: Path, row: dict[str, str]) -> None:
    """Append one row to the ledger, writing a header first if it does not
    exist yet -- an APPEND, never an overwrite (module docstring; mirrors
    `axial.ingest._append_result_row`)."""
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = ledger_path.exists()
        with ledger_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS, delimiter="\t")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except OSError as exc:
        raise LedgerError(ledger_path, exc) from exc


def _ledger_row(pass_name: str, outcome: Outcome) -> dict[str, str]:
    return {
        "pass": pass_name,
        "source_path": outcome.source_path,
        "source_id": outcome.source_id,
        "status": outcome.status,
        "reason": outcome.reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def resolve_corpus_source_paths(sources_dir: Path) -> list[str]:
    """The corpus source set (slice 03): every `sources_dir` file matching
    `CORPUS_EXTENSIONS` (`.pdf`, `.docx`), sorted for a deterministic order
    -- never raw filesystem iteration order, which is not guaranteed across
    platforms. Mirrors `axial.reconcile.live_source_ids`'s own single-level
    (non-recursive) scan. An absent or empty `sources_dir` yields an empty
    list -- an empty source set, not an error (a run over it reports
    total=0, see `run_pass`)."""
    if not sources_dir.is_dir():
        return []
    matches = [
        path
        for extension in CORPUS_EXTENSIONS
        for path in sources_dir.glob(f"*{extension}")
        if path.is_file()
    ]
    return sorted(str(path) for path in matches)


def _resolve_source_paths(
    worklist_path: str | Path | None, corpus: bool, sources_dir: Path | None
) -> list[str]:
    """Resolve the one required source set (module docstring): `worklist_path`
    (slice 01) or `corpus` (slice 03), never both, never neither. Raises
    `SourceSetError` for the both/neither cases and `WorklistError` if a
    given worklist path cannot be read -- both fatal, checked before any
    source is touched."""
    worklist_given = worklist_path is not None
    if worklist_given == corpus:
        raise SourceSetError(worklist_given, corpus)
    if worklist_given:
        return read_worklist(worklist_path)
    return resolve_corpus_source_paths(
        sources_dir if sources_dir is not None else CORPUS_SOURCES_DIR
    )


def _summarize(pass_name: str, outcomes: list[Outcome]) -> RunSummary:
    ok_count = sum(1 for outcome in outcomes if outcome.status == OK_STATUS)
    skip_count = sum(1 for outcome in outcomes if outcome.status == SKIP_STATUS)
    fail_count = len(outcomes) - ok_count - skip_count
    return RunSummary(pass_name, outcomes, len(outcomes), ok_count, fail_count, skip_count)


def run_pass(
    pass_name: str,
    worklist_path: str | Path | None = None,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    ledger_path: Path | None = None,
    *,
    corpus: bool = False,
    sources_dir: Path | None = None,
) -> tuple[RunSummary, int]:
    """Drive the registered pass named `pass_name` over its resolved source
    set, one source at a time (module docstring). The source set is either a
    line-delimited worklist (`worklist_path`) or the corpus glob (`corpus=
    True`, every `sources_dir` `.pdf`/`.docx` file in sorted order) --
    exactly one of the two is required; supplying both, or neither, is a
    fatal `SourceSetError`. Prints a tab-separated outcome table (header +
    one row per attempted source, including skipped ones) to stdout, plus
    one `error:`/`skip:` diagnostic line to stderr/stdout per FAIL/SKIP, an
    end-of-run tally line, and returns `(summary, exit_code)`.

    `summary` is a `RunSummary` -- the same structured value printed as the
    tally line, returned so a consumer (#270's log emitter, #288's rates
    report) can attach to it without reaching into runner internals (slice
    03). Its `outcomes` is empty and every count is 0 for every fatal
    condition below.

    Exit code is 0 even when some sources FAIL -- a per-source failure is
    expected, recoverable operator signal, not a crash (mirroring
    `axial.ingest.run_ingest`). It is non-zero ONLY when the loop itself
    cannot run: an unknown pass name, an invalid source set, an unreadable
    worklist, or an unappendable ledger. All fatal conditions are checked
    before any source is touched (except the ledger append itself, which can
    only fail once a source has actually run).

    `ledger_path` defaults to `LEDGER_PATH`; `sources_dir` defaults to
    `CORPUS_SOURCES_DIR`; both overridable for tests, mirroring
    `axial.ingest.run_ingest`'s own `results_path` seam. Before the loop, the
    ledger is read once for this pass's own already-done `source_id`s
    (`_load_done_source_ids`); each source then asks `descriptor
    .done_predicate` -- file-exists for extract/envelope, ledger-membership
    for every other pass (module docstring) -- and a source it reports done
    is skipped doing zero pipeline work: no `descriptor.invoke` call, hence
    no LLM call and no output rewrite, since that call is exactly what would
    do either. Every non-skipped source appends exactly one row to the
    ledger; a re-run therefore never appends a duplicate OK row and never
    rewrites a prior run's rows (`_append_ledger_row` only ever opens the
    file in append mode).

    The shared `client` is constructed once for the whole run (if not passed
    explicitly) and threaded, along with `config_path`/`domain_dir`, into
    every source's pass invocation -- never rebuilt per source.
    """
    descriptor = PASS_REGISTRY.get(pass_name)
    if descriptor is None:
        print(f"error: {UnknownPassError(pass_name)}", file=sys.stderr)
        return _empty_summary(pass_name), 1

    try:
        source_paths = _resolve_source_paths(worklist_path, corpus, sources_dir)
    except (SourceSetError, WorklistError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _empty_summary(pass_name), 1

    if ledger_path is None:
        ledger_path = LEDGER_PATH

    try:
        ledger_done_ids = _load_done_source_ids(ledger_path, pass_name)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _empty_summary(pass_name), 1

    if client is None:
        client = get_client(config_path=config_path)

    outcomes: list[Outcome] = []
    print("\t".join(TABLE_COLUMNS))

    if not source_paths:
        print(f"run: pass={pass_name} nothing to do (0 sources in source set)")
        return _summarize(pass_name, outcomes), 0

    for source_path_str in source_paths:
        source_path = Path(source_path_str)

        try:
            source_id = compute_source_id(source_path)
        except MissingSourceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            outcome = Outcome(str(source_path), "", FAIL_STATUS, str(exc))
            outcomes.append(outcome)
            print(_render_row(outcome))
            try:
                _append_ledger_row(ledger_path, _ledger_row(pass_name, outcome))
            except LedgerError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return _summarize(pass_name, outcomes), 1
            continue

        if descriptor.done_predicate(source_id, ledger_done_ids, config_path):
            print(f"skip: {source_path} already done ({pass_name})")
            outcome = Outcome(str(source_path), source_id, SKIP_STATUS)
            outcomes.append(outcome)
            print(_render_row(outcome))
            continue

        try:
            descriptor.invoke(str(source_path), client, config_path, domain_dir)
        except descriptor.error as exc:
            print(f"error: {source_path}: {exc}", file=sys.stderr)
            outcome = Outcome(str(source_path), source_id, FAIL_STATUS, str(exc))
        else:
            outcome = Outcome(str(source_path), source_id, OK_STATUS)

        outcomes.append(outcome)
        print(_render_row(outcome))

        try:
            _append_ledger_row(ledger_path, _ledger_row(pass_name, outcome))
        except LedgerError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _summarize(pass_name, outcomes), 1
        if outcome.status == OK_STATUS:
            ledger_done_ids.add(source_id)

    summary = _summarize(pass_name, outcomes)
    print(
        f"run: pass={pass_name} total={summary.total} ok={summary.ok_count} "
        f"skipped={summary.skip_count} failed={summary.fail_count}"
    )

    return summary, 0
