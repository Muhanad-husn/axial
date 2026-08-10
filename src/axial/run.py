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
one `skip: <source> already done (<pass>)` line. `extract`, `envelope` and
`chunk` declare a file-exists predicate over their own persisted-output
cache (the README's mechanism 2); every other registered pass declares the
ledger predicate (the README's mechanisms 1 and 3, now unified into one
ledger the runner owns). Every non-skipped source appends exactly one outcome row to
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

Issue #288 (not-applicable/unlisted `theory_school` rates) built a CONSUMER
of `RunSummary` at the bottom of this module, `attach_theory_school_rates`/
`render_theory_school_rates`, called explicitly after `run_pass` returns.
Retired along with the tag pass and its `theory_school` axis (issue #414,
`plans/phase-a-v1/README.md` D4/D9) -- `RunSummary.rates` remains as an
attachment point for a future consumer, unenriched by this module itself.

**Issue #526 wires this loop into `axial.runlog.run_context`** -- the first
multi-source caller of that seam. The whole `run_pass` body runs inside one
`run_context(f"run-{pass_name}", ...)`: every source's start, finish, and
failure becomes an `event()` (durable, cross-process-readable progress);
every attempted source still gets exactly one `record()` (unchanged
one-per-source granularity); a live line prints at each source's start --
position, elapsed, spend so far (read from the shared client's own
`usage_for_pass`, never a second accounting), failures so far, and a rough
ETA from the median duration of what has already completed; and an
end-of-run `report.json` is written into the run directory before
returning, on every exit path (fatal or clean) -- per-source timings with
slow outliers named, total tokens/cost, failures grouped by their own
(exact-match) reason string, and whatever sources were never reached.
`summary.md` is untouched: still an operator-authored stub, never
generated. None of this changes the printed TSV table, the tally line, the
resume ledger, or the exit-code contract -- see the outer acceptance tests
under `tests/test_run*.py`, all pinned before #526 and unedited by it.

**Issue #734 wires a before/after `usage_for_pass`/`calls_for_pass`
comparison into `record()` itself** (`_source_usage_and_cost`): each
attempted source's own token usage and dollar cost, so `run.jsonl` -- not
only the end-of-run `report.json` -- carries spend, readable while the run
is still in flight and attributable to a pass and a source. Two
accumulators, not one, because a response with no `usage` object is a
silent no-op for `usage_for_pass` alone -- indistinguishable from "no call
happened" without `calls_for_pass` (issue #734, `axial.llm
._accumulate_usage`) moving alongside it. `None` in the new fields means
"visibly unmeasured" -- either nothing has been captured for this pass yet,
or a call happened whose response carried no usage -- never a fabricated
zero; a real zero means a call genuinely did not happen for this source.
See `_source_usage_and_cost`'s own docstring for the three cases.

**Issue #738 fixed two defects a real-corpus validation of #734 found before
merge, both inside `_source_usage_and_cost`.** Defect 1: `usage_for_pass`
used to return the live dict `_accumulate_usage` mutates in place, so the
"before" snapshot silently aliased "after" the moment the SAME pass
accumulated again -- every source past a pass's first read as "no call
happened" and recorded `null`. Fixed in `axial.llm` (`usage_for_pass` now
returns a copy); this predates #734 entirely -- the `model = ... if
usage_after != usage_before else None` line it replaced had the identical
bug, so every shipped run log has recorded `model: null` for every source
past a pass's first. Defect 2: `usd` priced through `estimate_cost`'s
price-table estimate, measured 3% high to 100% low per call against the
real charge OpenRouter reports on every response (`usage["cost"]`). `usd`
now prefers that real, accumulated cost (`client.cost_for_pass`, threaded
through `_source_usage_and_cost` the same way `usage_for_pass` already
was), falling back to `estimate_cost` only when the provider genuinely
never reported one.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from axial.artifacts import ArtifactsError, _default_artifacts_dir, run_artifacts
from axial.chunk import (
    ChunkError,
    _default_chunks_dir,
    chunks_checkpoint_path,
    run_chunk_recursive,
)
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
from axial.interrogate import (
    InterrogateError,
    _default_answers_dir,
    answers_checkpoint_path,
    load_answer_checkpoint,
    run_interrogate,
)
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    LLMClient,
    estimate_cost,
    get_client,
    usage_and_cost_by_pass,
)
from axial.paths import DEFAULT_DOMAIN_DIR
from axial.position_backfill import notes_missing_position, run_position_backfill
from axial.runlog import format_duration, run_context
from axial.vault import VaultError, run_vault_write

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

# End-of-run report (issue #526): a completed source is a "slow outlier"
# when its own duration is more than this many times the run's median --
# one clear, unconfigurable multiplier, not a hand-tuned table. Needs at
# least two completed durations to make a median meaningful at all.
SLOW_OUTLIER_FACTOR = 2


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
    rates report: `None` from `run_pass` itself (the runner loop never
    computes it -- a `RunSummary` it returns is unenriched, exactly as slice
    03 left it), filled by calling `attach_theory_school_rates` on the
    returned summary as a separate step afterward. That function is a
    CONSUMER of this value, same as #270's log emitter -- it never reaches
    into `run_pass`'s own loop, and calling it is always optional and always
    safe (it never raises; see its own docstring)."""

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


def _invoke_artifacts(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    # Threads a real `artifacts_dir` (issue #424, the same defect #325 fixed
    # for `_invoke_tag` above): `run_artifacts`'s own checkpoint is OPT-IN,
    # active only when `artifacts_dir` is supplied. Without one, every
    # artifact record is produced and then dropped on the floor -- nothing
    # ever lands on disk, and the ledger still records OK, so a resumed run
    # skips a source whose output was never written. `_default_artifacts_dir`
    # is the same default `axial artifacts`'s own standalone CLI path
    # resolves, which is why `data/artifacts/*.jsonl` exists at all today.
    # `client`/`domain_dir` are accepted (every registered pass shares this
    # call signature, see `PassSpec`) but unused: the pass makes no LLM call
    # and needs no domain frame (issue #429).
    del client, domain_dir
    return run_artifacts(source_path, artifacts_dir=_default_artifacts_dir(config_path))


def _invoke_interrogate(source_path: str, client: LLMClient | None, config_path: Path, domain_dir):
    """The Phase A v1 interrogation pass (§7.15, P1-4: "`interrogate`
    registers as a pass like any other, so the corpus re-run resumes rather
    than restarting"). No `data_dir` override here: through this path every
    directory resolves from config, exactly like every other registered
    pass. Its own per-source answer artifact is the finer-grained resume;
    the ledger is the runner's coarse one, as for every checkpointing
    pass."""
    return run_interrogate(
        source_path, client=client, config_path=config_path, domain_dir=domain_dir
    )


def _invoke_position_backfill(
    source_path: str, client: LLMClient | None, config_path: Path, domain_dir
):
    """The `position` backfill pass (issue #697): one question over the
    notes of `source_path` that lack the key. Resumable the same way
    interrogate is -- `run_position_backfill` reads its own per-source
    answer artifact and asks only what is missing -- so re-invoking an
    already-complete source through this registry costs nothing beyond the
    done-predicate's own cheap read below."""
    return run_position_backfill(
        source_path, client=client, config_path=config_path, domain_dir=domain_dir
    )


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


def _chunks_done_predicate(source_id: str, ledger_done_ids: set[str], config_path: Path) -> bool:
    """chunk's own done-signal: its persisted chunk artifact already exists
    at `data/chunks/<source_id>.jsonl` (module docstring's mechanism 2, the
    same one extract and envelope declare).

    chunk used to declare the ledger predicate, on the reasoning that it
    checkpoints per note and so has no single atomic per-source output. It
    does have one -- `run_chunk_recursive` writes the whole artifact in one
    go -- and the ledger is the wrong signal for it in practice (issue
    #623): `data/run/ledger.tsv` has never been written on the real corpus,
    so every one of the 31 already-chunked sources came back not-done, and
    `axial sources` would re-chunk all of them right after reporting them
    `done`. `run_chunk_recursive` has no internal skip -- unlike
    `run_interrogate`, which resumes from its own checkpoint and so costs
    nothing to re-invoke -- so that re-chunk rewrites every artifact and
    pays the router's content-apparatus classification calls again.

    Measured on `agamben-2005` before this predicate existed: the rewrite
    was byte-identical (53 chunks, same ids, same text) but cost seven
    model calls. Identical output is not guaranteed in general, though --
    those calls are what decide which lines get routed out of a section,
    and a classification that lands differently would renumber that
    source's notes and orphan every analysis pinned to them.
    """
    chunks_dir = _default_chunks_dir(config_path)
    return chunks_checkpoint_path(source_id, chunks_dir).exists()


def _ledger_done_predicate(source_id: str, ledger_done_ids: set[str], config_path: Path) -> bool:
    """The runner-owned ledger's own done-signal (module docstring's
    mechanisms 1 and 3, now unified): an OK row already recorded for this
    `(pass, source_id)`. `ledger_done_ids` is loaded once per `run_pass`
    call, not re-read per source."""
    return source_id in ledger_done_ids


def _position_backfill_done_predicate(
    source_id: str, ledger_done_ids: set[str], config_path: Path
) -> bool:
    """The position-backfill pass's own done-signal (issue #697), read off
    its persisted output rather than the ledger (mechanism 2, the same one
    extract/envelope/chunk use): a source is done when its own
    `data/answers/<source_id>.jsonl` carries no record missing `position`.
    This is a cheap file read, never a model call, so a corpus-wide rerun
    after the backfill lands skips every already-backfilled source doing
    zero work -- the ledger predicate above would need its own `--ledger`
    file kept in lockstep instead, which this pass's own resumability
    (`run_position_backfill`'s docstring) makes unnecessary."""
    answers_dir = _default_answers_dir(config_path)
    records = load_answer_checkpoint(answers_checkpoint_path(source_id, answers_dir))
    return not notes_missing_position(records)


# The pass registry (module docstring): a plain dict, not a plugin system --
# seven known passes, all in this repo, each with a `(source_path, client,
# config_path, domain_dir)`-shaped invoker (via the `_invoke_*` adapters
# above), the `*Error` base it declares, and its done-predicate. extract,
# envelope and chunk declare their own persisted-output file as the
# done-signal; interrogate and artifacts -- which checkpoint per note, a
# finer granularity this runner does not reach into (module docstring), and
# which resume from that checkpoint so re-invoking one costs nothing --
# declare the runner's own ledger. `tag` and `xref` were retired (issue
# #414, plans/phase-a-v1/README.md D4/D5): the interrogation pass above
# replaces both. `position-backfill` (issue #697) declares its own
# persisted-output predicate rather than the ledger, for the reason its own
# `_position_backfill_done_predicate` docstring gives.
PASS_REGISTRY: dict[str, PassDescriptor] = {
    "extract": PassDescriptor("extract", _invoke_extract, ExtractError, _tree_done_predicate),
    "envelope": PassDescriptor(
        "envelope", _invoke_envelope, EnvelopeError, _envelope_done_predicate
    ),
    "chunk": PassDescriptor("chunk", _invoke_chunk, ChunkError, _chunks_done_predicate),
    "interrogate": PassDescriptor(
        "interrogate", _invoke_interrogate, InterrogateError, _ledger_done_predicate
    ),
    "position-backfill": PassDescriptor(
        "position-backfill",
        _invoke_position_backfill,
        InterrogateError,
        _position_backfill_done_predicate,
    ),
    "artifacts": PassDescriptor(
        "artifacts", _invoke_artifacts, ArtifactsError, _ledger_done_predicate
    ),
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


def _print_encoding_safe(text: str, *, stream: Any = None) -> None:
    """Print `text` to `stream` (default `sys.stdout`) without crashing when
    the stream's codec can't represent one of its characters -- the real
    failure mode every `axial run <pass>` invocation hits once its stdout is
    piped rather than a real console: Windows then falls back to the
    process's legacy codepage (e.g. `cp1252`) instead of UTF-8, and a source
    path/id/reason carrying a character outside it (a diacritic such as the
    combining caron in "Siniša", decomposed form) raises `UnicodeEncodeError`
    and kills the whole pass. Every row `run_pass` prints is source-derived,
    so every one of them goes through this.

    Mirrors `axial.cli._print_encoding_safe` verbatim (duplicated, not
    imported: `cli` imports from this module, so importing the other
    direction would be circular) -- reconfigure the stream to UTF-8 where
    supported; else fall back to writing backslash-escaped UTF-8 bytes
    through the raw buffer so the line is still emitted, never silently
    dropped. Content/wording is untouched; only the emission path changes.
    """
    stream = sys.stdout if stream is None else stream
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
            print(text, file=stream)
            return
        except (ValueError, OSError):
            pass

    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8", errors="backslashreplace"))
        buffer.write(b"\n")
        buffer.flush()
    else:
        print(text.encode("ascii", errors="backslashreplace").decode("ascii"), file=stream)


def _render_progress_line(
    *,
    index: int,
    total: int,
    source_path: str,
    elapsed_sec: float,
    spent_usd: float | None,
    fail_count: int,
    eta_sec: float | None,
) -> str:
    """One live-progress line, printed the moment a source starts -- not
    only once it finishes (issue #526's "progress appears while a source
    runs" bar; this is also the honest answer for the one opaque step,
    docling extraction, which has no finer progress hook: this line is all
    it ever gets beyond the existing start/finish outcome row). `eta_sec` is
    `None` until at least one source in this run has completed, since a
    median of zero durations is not an estimate."""
    spent = f"${spent_usd:.4f}" if spent_usd is not None else "n/a"
    eta = f"~{format_duration(eta_sec)}" if eta_sec is not None else "unknown"
    return (
        f"progress: {index}/{total} starting {source_path} "
        f"(elapsed={format_duration(elapsed_sec)} spent={spent} "
        f"failed={fail_count} eta={eta})"
    )


def _spent_so_far(client: LLMClient, pass_name: str) -> float | None:
    """This pass's dollar spend so far in this process, read straight from
    the shared client's own per-pass accumulation (`usage_for_pass` via
    `axial.llm.usage_and_cost_by_pass`) -- never a second accounting."""
    model = client.model_for_pass(pass_name)
    report = usage_and_cost_by_pass(client, {pass_name: model})
    return report["by_pass"][pass_name]["usd"]


def _source_usage_and_cost(
    model: str | None,
    usage_before: dict[str, int] | None,
    usage_after: dict[str, int] | None,
    calls_before: int,
    calls_after: int,
    cost_before: float | None = None,
    cost_after: float | None = None,
) -> tuple[int | None, int | None, int | None, float | None]:
    """This one source's own token usage and dollar cost (issue #734): the
    delta between `client.usage_for_pass(pass_name)`/`client.calls_for_pass
    (pass_name)`/`client.cost_for_pass(pass_name)`, each taken right before
    and right after this source's own `descriptor.invoke` call -- all three
    already computed by the loop below, never a second accounting.

    `usage_for_pass`/`cost_for_pass` (issue #738 defect 1) return a COPY of
    their accumulator, never the live dict/float `axial.llm._accumulate_usage`
    updates -- a caller here relies on that: comparing an aliased "before"
    against the "after" it silently became would read every source past a
    pass's first as having made no call at all.

    Two token/call accumulators, not one, because `usage_for_pass` alone
    cannot tell "no call happened for this source" apart from "a call
    happened but its response carried no `usage` object" -- both leave
    `usage_after == usage_before`. `calls_for_pass` (issue #734) moves on
    EVERY call regardless of whether its response carried usage, so the two
    together resolve three cases:

    1. `calls_after == calls_before` -- no call happened for this source.
       `usage_after is None` (the pass has captured no usage at all yet,
       across every source attempted so far) means fully unknown -- every
       field `None`, the same "not on disk yet" case `_render_progress_line`
       already renders as `spent=n/a`. Otherwise a real, honest zero: this
       source spent nothing.
    2. `calls_after != calls_before` and usage moved with it -- a real
       (possibly multi-call) token delta. Priced from `cost_for_pass`'s own
       delta (issue #738 defect 2) when the provider has reported a real
       cost for this pass at all -- the provider's own exact charge, not an
       estimate (`axial.llm.estimate_cost`'s price-table figure measured
       3% high to 100% low per call against it). Falls back to
       `estimate_cost` only when the provider never reported one; `None`
       there too when the model has no `PRICE_TABLE_USD_PER_1K` entry
       either -- real tokens, an honestly unpriced cost.
    3. `calls_after != calls_before` but usage did NOT move -- a call
       happened and its response carried no `usage` object. This is the
       "visibly missing" case the issue is about: tokens and `usd` come back
       `None`, never a fabricated zero standing in for "nothing was spent"."""
    if calls_after == calls_before:
        if usage_after is None:
            return None, None, None, None
        return 0, 0, 0, 0.0
    if usage_after == usage_before:
        return None, None, None, None
    before = usage_before or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    prompt_tokens = usage_after["prompt_tokens"] - before["prompt_tokens"]
    completion_tokens = usage_after["completion_tokens"] - before["completion_tokens"]
    total_tokens = usage_after["total_tokens"] - before["total_tokens"]
    if cost_after is not None:
        usd = cost_after - (cost_before or 0.0)
    else:
        usd = estimate_cost(model, prompt_tokens, completion_tokens) if model is not None else None
    return prompt_tokens, completion_tokens, total_tokens, usd


def _label_corpus_pin(
    worklist_path: str | Path | None, corpus: bool, sources_dir: Path | None
) -> str | None:
    """A short, human-readable `meta.json.corpus_pin` label: which source
    set this run resolved against. Computed from the raw arguments, before
    `_resolve_source_paths` can even fail, so a fatal `SourceSetError`/
    `WorklistError` run still carries a meaningful label."""
    if worklist_path is not None:
        return f"worklist:{worklist_path}"
    if corpus:
        return f"corpus:{sources_dir if sources_dir is not None else CORPUS_SOURCES_DIR}"
    return None


def _build_report(
    pass_name: str,
    outcomes: list[Outcome],
    durations: dict[str, float],
    source_paths: list[str],
    client: LLMClient | None,
    total_elapsed_sec: float,
) -> dict[str, Any]:
    """The end-of-run report (issue #526), written into the run directory
    and re-readable long after the run finished: per-source timings with
    slow outliers named, total tokens/cost, failures grouped by their own
    (exact-match) reason string rather than listed one by one, and whatever
    sources this run never reached. Built on every exit path -- fatal or
    clean -- so even a crashed run's own report answers "how far did it
    get" without reading `console.log` by hand."""
    attempted_paths = {outcome.source_path for outcome in outcomes}
    outstanding = [path for path in source_paths if path not in attempted_paths]

    per_source = [
        {
            "source_path": outcome.source_path,
            "source_id": outcome.source_id,
            "status": outcome.status,
            "duration_sec": durations.get(outcome.source_path),
        }
        for outcome in outcomes
    ]

    # A completed source is a "slow outlier" when its own duration is more
    # than SLOW_OUTLIER_FACTOR times the run's own median -- needs at least
    # two completed durations for a median to mean anything.
    slow_outliers: list[str] = []
    if len(durations) >= 2:
        median = statistics.median(durations.values())
        if median > 0:
            slow_outliers = sorted(
                (
                    path
                    for path, seconds in durations.items()
                    if seconds > median * SLOW_OUTLIER_FACTOR
                ),
                key=lambda path: durations[path],
                reverse=True,
            )

    failures_by_cause: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        if outcome.status != FAIL_STATUS:
            continue
        cause = outcome.reason or "(no reason recorded)"
        bucket = failures_by_cause.setdefault(cause, {"count": 0, "source_ids": []})
        bucket["count"] += 1
        bucket["source_ids"].append(outcome.source_id)

    tokens_and_cost = None
    if client is not None:
        model = client.model_for_pass(pass_name)
        tokens_and_cost = usage_and_cost_by_pass(client, {pass_name: model})

    return {
        "pass_name": pass_name,
        "total": len(outcomes),
        "ok_count": sum(1 for outcome in outcomes if outcome.status == OK_STATUS),
        "fail_count": sum(1 for outcome in outcomes if outcome.status == FAIL_STATUS),
        "skip_count": sum(1 for outcome in outcomes if outcome.status == SKIP_STATUS),
        "total_elapsed_sec": total_elapsed_sec,
        "per_source": per_source,
        "slow_outliers": slow_outliers,
        "failures_by_cause": failures_by_cause,
        "tokens_and_cost": tokens_and_cost,
        "outstanding": outstanding,
    }


def _write_report(run_dir: Path, report: dict[str, Any]) -> None:
    (run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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

    Issue #526: the whole call runs inside one `axial.runlog.run_context`
    (named `f"run-{pass_name}"`). Every source's start/finish/failure is an
    `event()`; every attempted source still gets exactly one `record()`; a
    live progress line prints at each source's start; and an end-of-run
    `report.json` is written into the run directory on every exit path.
    None of this changes the table/tally text, the resume ledger, or the
    exit-code contract documented above -- see this module's own docstring.
    """
    corpus_pin = _label_corpus_pin(worklist_path, corpus, sources_dir)

    with run_context(f"run-{pass_name}", corpus_pin=corpus_pin) as run:
        outcomes: list[Outcome] = []
        durations: dict[str, float] = {}
        source_paths: list[str] = []
        run_start = time.monotonic()

        try:
            descriptor = PASS_REGISTRY.get(pass_name)
            if descriptor is None:
                _print_encoding_safe(f"error: {UnknownPassError(pass_name)}", stream=sys.stderr)
                run.set_status("failed")
                return _empty_summary(pass_name), 1

            try:
                source_paths = _resolve_source_paths(worklist_path, corpus, sources_dir)
            except (SourceSetError, WorklistError) as exc:
                _print_encoding_safe(f"error: {exc}", stream=sys.stderr)
                run.set_status("failed")
                return _empty_summary(pass_name), 1

            if ledger_path is None:
                ledger_path = LEDGER_PATH

            try:
                ledger_done_ids = _load_done_source_ids(ledger_path, pass_name)
            except LedgerError as exc:
                _print_encoding_safe(f"error: {exc}", stream=sys.stderr)
                run.set_status("failed")
                return _empty_summary(pass_name), 1

            if client is None:
                client = get_client(config_path=config_path)

            _print_encoding_safe("\t".join(TABLE_COLUMNS))

            if not source_paths:
                _print_encoding_safe(
                    f"run: pass={pass_name} nothing to do (0 sources in source set)"
                )
                return _summarize(pass_name, outcomes), 0

            total_sources = len(source_paths)
            for index, source_path_str in enumerate(source_paths, start=1):
                source_path = Path(source_path_str)
                source_start = time.monotonic()

                try:
                    source_id = compute_source_id(source_path)
                except MissingSourceError as exc:
                    _print_encoding_safe(f"error: {exc}", stream=sys.stderr)
                    run.event(
                        kind="source_fail", source_id="", pass_name=pass_name, detail=str(exc)
                    )
                    outcome = Outcome(str(source_path), "", FAIL_STATUS, str(exc))
                    outcomes.append(outcome)
                    _print_encoding_safe(_render_row(outcome))
                    run.record(
                        source_id="",
                        pass_name=pass_name,
                        model=None,
                        status="error",
                        duration_sec=time.monotonic() - source_start,
                        error=str(exc),
                    )
                    try:
                        _append_ledger_row(ledger_path, _ledger_row(pass_name, outcome))
                    except LedgerError as exc:
                        _print_encoding_safe(f"error: {exc}", stream=sys.stderr)
                        run.set_status("failed")
                        return _summarize(pass_name, outcomes), 1
                    continue

                if descriptor.done_predicate(source_id, ledger_done_ids, config_path):
                    run.event(kind="source_skip", source_id=source_id, pass_name=pass_name)
                    _print_encoding_safe(f"skip: {source_path} already done ({pass_name})")
                    outcome = Outcome(str(source_path), source_id, SKIP_STATUS)
                    outcomes.append(outcome)
                    _print_encoding_safe(_render_row(outcome))
                    continue

                fail_so_far = sum(1 for o in outcomes if o.status == FAIL_STATUS)
                eta_sec = (
                    statistics.median(durations.values()) * (total_sources - index + 1)
                    if durations
                    else None
                )
                _print_encoding_safe(
                    _render_progress_line(
                        index=index,
                        total=total_sources,
                        source_path=str(source_path),
                        elapsed_sec=time.monotonic() - run_start,
                        spent_usd=_spent_so_far(client, pass_name),
                        fail_count=fail_so_far,
                        eta_sec=eta_sec,
                    )
                )
                run.event(
                    kind="source_start",
                    source_id=source_id,
                    pass_name=pass_name,
                    detail=f"{index}/{total_sources}",
                )

                usage_before = client.usage_for_pass(pass_name)
                calls_before = client.calls_for_pass(pass_name)
                cost_before = client.cost_for_pass(pass_name)
                try:
                    descriptor.invoke(str(source_path), client, config_path, domain_dir)
                except descriptor.error as exc:
                    _print_encoding_safe(f"error: {source_path}: {exc}", stream=sys.stderr)
                    outcome = Outcome(str(source_path), source_id, FAIL_STATUS, str(exc))
                    run.event(
                        kind="source_fail",
                        source_id=source_id,
                        pass_name=pass_name,
                        detail=str(exc),
                    )
                else:
                    outcome = Outcome(str(source_path), source_id, OK_STATUS)
                    run.event(kind="source_finish", source_id=source_id, pass_name=pass_name)

                duration = time.monotonic() - source_start
                durations[str(source_path)] = duration
                # A model is reported only when THIS source's own invocation
                # actually made a call -- never a fabricated model id for a
                # pass (or a cache hit) that made no call (mirrors the eval
                # pass's own precedent, tests/test_runlog_passes.py). Issue
                # #734: gated on `calls_for_pass`, not `usage_for_pass` --  a
                # call that made no NEW usage (its response carried no
                # `usage` object) still real, and still names a real model.
                usage_after = client.usage_for_pass(pass_name)
                calls_after = client.calls_for_pass(pass_name)
                cost_after = client.cost_for_pass(pass_name)
                model = client.model_for_pass(pass_name) if calls_after != calls_before else None
                prompt_tokens, completion_tokens, total_tokens, usd = _source_usage_and_cost(
                    model,
                    usage_before,
                    usage_after,
                    calls_before,
                    calls_after,
                    cost_before,
                    cost_after,
                )
                run.record(
                    source_id=source_id,
                    pass_name=pass_name,
                    model=model,
                    status="ok" if outcome.status == OK_STATUS else "error",
                    duration_sec=duration,
                    error=outcome.reason or None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    usd=usd,
                )

                outcomes.append(outcome)
                _print_encoding_safe(_render_row(outcome))

                try:
                    _append_ledger_row(ledger_path, _ledger_row(pass_name, outcome))
                except LedgerError as exc:
                    _print_encoding_safe(f"error: {exc}", stream=sys.stderr)
                    run.set_status("failed")
                    return _summarize(pass_name, outcomes), 1
                if outcome.status == OK_STATUS:
                    ledger_done_ids.add(source_id)

            summary = _summarize(pass_name, outcomes)
            _print_encoding_safe(
                f"run: pass={pass_name} total={summary.total} ok={summary.ok_count} "
                f"skipped={summary.skip_count} failed={summary.fail_count}"
            )

            return summary, 0
        finally:
            _write_report(
                run.run_dir,
                _build_report(
                    pass_name,
                    outcomes,
                    durations,
                    source_paths,
                    client,
                    time.monotonic() - run_start,
                ),
            )
