"""Corpus-wide pass runner: drives one registered per-source pass over a
worklist of source paths, one source at a time, with per-source failure
isolation (issue #277, slice 01; `plans/run/01-runner-core-and-failure-
isolation.md`).

This is the walking skeleton for `axial run <pass> --worklist <file>`. It
generalizes `axial.ingest.run_ingest`'s proven loop shape -- read the source
set, run one source, record an outcome, continue on failure, exit non-zero
only when the loop itself cannot run -- from one hard-wired pass
(`run_vault_write`, caught only for `VaultError`) to any pass in the
**pass registry**: a plain dict mapping a pass name to a small descriptor
carrying that pass's per-source callable and the `*Error` base it declares.
This is the retirement path for the bare-`except Exception` loop wrapper the
postmortem named as root cause D -- every registered pass's OWN declared
error type is now what gets caught, never a catch-all.

Out of scope for this slice (see the plan): the unified resume ledger and
done-predicate protocol (slice 02, each pass's own file-exists/checkpoint
idempotence still applies unchanged); the corpus glob source set and the
polished end-of-run summary (slice 03); the #270 run-log emitter and the
#288 rates report; parallelism; cross-pass chaining.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from axial.artifacts import ArtifactsError, run_artifacts
from axial.chunk import ChunkError, run_chunk_recursive
from axial.envelope import EnvelopeError, MissingSourceError, compute_source_id, run_envelope
from axial.extract import ExtractError, extract
from axial.ingest import WorklistError, read_worklist
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient, get_client
from axial.tag import DEFAULT_DOMAIN_DIR, TagError, run_tag
from axial.vault import VaultError, run_vault_write
from axial.xref import XrefError, run_xref

OK_STATUS = "OK"
FAIL_STATUS = "FAIL"

# The printed per-source outcome table's column order (mirrors
# axial.pipeline_ready.TABLE_COLUMNS's convention: a header row + one row per
# source, columns looked up by name -- never by position). `reason` is empty
# for an OK outcome.
TABLE_COLUMNS = ("source_path", "source_id", "status", "reason")


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


@dataclass(frozen=True)
class Outcome:
    """One source's recorded in-process outcome: OK or FAIL, with a short
    reason (DEC-23: ids, statuses, and short reasons only, never source
    text)."""

    source_path: str
    source_id: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class PassDescriptor:
    """One registered pass: its per-source invoker and the `*Error` base it
    raises. `invoke` normalizes every pass's own differently-shaped
    entrypoint (some take no client, some no domain_dir -- see each pass
    module) behind one uniform `(source_path, client, config_path,
    domain_dir)` call shape, so the runner loop never special-cases a pass by
    name."""

    name: str
    invoke: Callable[[str, LLMClient | None, Path, str | Path], Any]
    error: type[Exception]


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


# The pass registry (module docstring): a plain dict, not a plugin system --
# seven known passes, all in this repo, each with a `(source_path, client,
# config_path, domain_dir)`-shaped invoker (via the `_invoke_*` adapters
# above) and the `*Error` base it declares.
PASS_REGISTRY: dict[str, PassDescriptor] = {
    "extract": PassDescriptor("extract", _invoke_extract, ExtractError),
    "envelope": PassDescriptor("envelope", _invoke_envelope, EnvelopeError),
    "chunk": PassDescriptor("chunk", _invoke_chunk, ChunkError),
    "tag": PassDescriptor("tag", _invoke_tag, TagError),
    "artifacts": PassDescriptor("artifacts", _invoke_artifacts, ArtifactsError),
    "xref": PassDescriptor("xref", _invoke_xref, XrefError),
    "vault-write": PassDescriptor("vault-write", _invoke_vault_write, VaultError),
}


def _render_row(outcome: Outcome) -> str:
    row = {
        "source_path": outcome.source_path,
        "source_id": outcome.source_id,
        "status": outcome.status,
        "reason": outcome.reason,
    }
    return "\t".join(row[column] for column in TABLE_COLUMNS)


def run_pass(
    pass_name: str,
    worklist_path: str | Path,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
) -> tuple[list[Outcome], int]:
    """Drive the registered pass named `pass_name` over every source path in
    `worklist_path`, one source at a time (module docstring). Prints a
    tab-separated outcome table (header + one row per attempted source) to
    stdout, plus one `error:` diagnostic line to stderr per FAIL, and returns
    `(outcomes, exit_code)`.

    Exit code is 0 even when some sources FAIL -- a per-source failure is
    expected, recoverable operator signal, not a crash (mirroring
    `axial.ingest.run_ingest`). It is non-zero ONLY when the loop itself
    cannot run: an unknown pass name, or an unreadable worklist. Both fatal
    conditions are checked before any source is touched, and `outcomes` is
    empty in that case.

    The shared `client` is constructed once for the whole run (if not passed
    explicitly) and threaded, along with `config_path`/`domain_dir`, into
    every source's pass invocation -- never rebuilt per source.
    """
    descriptor = PASS_REGISTRY.get(pass_name)
    if descriptor is None:
        print(f"error: {UnknownPassError(pass_name)}", file=sys.stderr)
        return [], 1

    try:
        source_paths = read_worklist(worklist_path)
    except WorklistError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return [], 1

    if client is None:
        client = get_client(config_path=config_path)

    outcomes: list[Outcome] = []
    print("\t".join(TABLE_COLUMNS))
    for source_path_str in source_paths:
        source_path = Path(source_path_str)

        try:
            source_id = compute_source_id(source_path)
        except MissingSourceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            outcome = Outcome(str(source_path), "", FAIL_STATUS, str(exc))
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

    ok_count = sum(1 for outcome in outcomes if outcome.status == OK_STATUS)
    fail_count = len(outcomes) - ok_count
    print(f"run: pass={pass_name} total={len(outcomes)} ok={ok_count} failed={fail_count}")

    return outcomes, 0
