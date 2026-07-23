"""Command-line entry point for axial."""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable

import axial
from axial.analyze import format_examine_report as format_brief_examine_report
from axial.analyze import run_examine
from axial.analyze.synthesis import SynthesisError
from axial.answer import AnswerError, run_brief
from axial.answer.usage_report import build_usage_report, format_usage_report, load_analysis_records
from axial.artifacts import ArtifactsError, run_artifacts
from axial.brief import BriefError, load_brief
from axial.brief.interrogate import InterrogationError, interrogate, persist_interrogation
from axial.chunk import (
    ChunkError,
    _default_chunks_dir,
    examine_chunks,
    format_examine_report,
    run_chunk_recursive,
)
from axial.codebook import CodebookError, load_codebook
from axial.drive import DEFAULT_SECRETS_PATH as DRIVE_SECRETS_PATH
from axial.drive import DriveSecretsError, _load_drive_secrets, run_drive_ingest
from axial.envelope import EnvelopeError, MissingSourceError, compute_source_id, run_envelope
from axial.eval import EvalError, run_eval
from axial.eval.corpus_pin import CorpusPinError, write_pin
from axial.extract import ExtractError, extract
from axial.gold import (
    DEFAULT_MAX_SIZE,
    DEFAULT_MIN_SIZE,
    DEFAULT_SEED,
    GoldError,
    run_gold_deliver,
    run_gold_sample,
    run_gold_sheet,
)
from axial.ingest import run_ingest
from axial.intake import IntakeError, intake
from axial.llm import ENVELOPE_PASS_NAME, TAG_PASS_NAME, get_client
from axial.paths import default_analyses_dir
from axial.pipeline_ready import PipelineReadyError, run_pipeline_ready
from axial.polity_canonical import PolityCanonicalError, run_polity_build, run_polity_report
from axial.query.reader import QueryError
from axial.reconcile import ReconcileError, format_gc_report, run_gc
from axial.run import (
    PASS_REGISTRY,
    attach_theory_school_rates,
    render_theory_school_rates,
    run_pass,
)
from axial.runlog import run_context
from axial.schema import SchemaError, load_schema
from axial.tag import DEFAULT_DOMAIN_DIR, TagError, run_tag
from axial.validate import cross_validate
from axial.validators import (
    AttributionValidatorError,
    format_attribution_report,
    validate_attribution,
)
from axial.vault import VaultError, run_vault_write
from axial.xref import XrefError, run_xref


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axial")
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the axial version and exit",
    )

    subparsers = parser.add_subparsers(dest="command")

    schema_parser = subparsers.add_parser("schema", help="domain schema operations")
    schema_subparsers = schema_parser.add_subparsers(dest="schema_command")

    show_parser = schema_subparsers.add_parser(
        "show", help="show a domain schema's axes, cardinality, counts, and version"
    )
    show_parser.add_argument("domain_dir", help="path to a domain directory containing schema.yaml")

    validate_parser = schema_subparsers.add_parser(
        "validate", help="cross-check a domain's schema.yaml against its codebook.yaml"
    )
    validate_parser.add_argument(
        "domain_dir", help="path to a domain directory containing schema.yaml and codebook.yaml"
    )

    intake_parser = subparsers.add_parser(
        "intake", help="validate a source file and probe it for a real text layer"
    )
    intake_parser.add_argument("source_path", help="path to a .pdf or .docx source file")

    extract_parser = subparsers.add_parser(
        "extract", help="run structural extraction, emitting a hierarchical JSON tree"
    )
    extract_parser.add_argument("source_path", help="path to a .pdf or .docx source file")

    envelope_parser = subparsers.add_parser(
        "envelope",
        help="run the structural-envelope pass, writing data/envelopes/<source_id>.json",
    )
    envelope_parser.add_argument("source_path", help="path to a .pdf or .docx source file")

    chunk_parser = subparsers.add_parser(
        "chunk",
        help=(
            "run the recursive/structural chunk stage, writing bounded prose "
            "chunk records to data/chunks/<source_id>.jsonl (LLM-free); "
            "'examine' is a reserved source_path value that instead reports "
            "chunk-quality stats over data/chunks/ (zero LLM/embedding calls)"
        ),
    )
    chunk_parser.add_argument(
        "source_path",
        help=(
            "path to a .pdf or .docx source file, OR the literal value "
            "'examine' to report chunk-quality stats over data/chunks/ "
            "instead of running the chunk stage"
        ),
    )

    tag_parser = subparsers.add_parser(
        "tag",
        help="run the tagging pass, emitting tagged chunk records to stdout",
    )
    tag_parser.add_argument("source_path", help="path to a .pdf or .docx source file")
    tag_parser.add_argument(
        "--domain",
        dest="domain_dir",
        default=None,
        help=(
            "path to a domain directory containing schema.yaml and codebook.yaml "
            "(default: resolved from config/pipeline.yaml's paths.domain_dir, "
            f"falling back to {DEFAULT_DOMAIN_DIR} when absent)"
        ),
    )

    artifacts_parser = subparsers.add_parser(
        "artifacts",
        help="run the artifact-classification pass, emitting one record per artifact node to stdout",
    )
    artifacts_parser.add_argument("source_path", help="path to a .pdf or .docx source file")
    artifacts_parser.add_argument(
        "--domain",
        default=str(DEFAULT_DOMAIN_DIR),
        help=(
            "path to a domain directory containing schema.yaml and codebook.yaml "
            f"(default: {DEFAULT_DOMAIN_DIR})"
        ),
    )

    xref_parser = subparsers.add_parser(
        "xref",
        help=(
            "run the cross-reference-detection pass, emitting (chunk_id, "
            "artifact_id) reference pairs to stdout"
        ),
    )
    xref_parser.add_argument("source_path", help="path to a .pdf or .docx source file")
    xref_parser.add_argument(
        "--domain",
        default=str(DEFAULT_DOMAIN_DIR),
        help=(
            "path to a domain directory containing schema.yaml and codebook.yaml "
            f"(default: {DEFAULT_DOMAIN_DIR})"
        ),
    )

    gold_parser = subparsers.add_parser("gold", help="gold-set (Academic labeling) operations")
    gold_subparsers = gold_parser.add_subparsers(dest="gold_command")

    gold_sample_parser = gold_subparsers.add_parser(
        "sample",
        help=(
            "select a stratified set of tagged prose chunks from the vault and "
            "write one chunk record per selection to data/gold/chunks/"
        ),
    )
    gold_sample_parser.add_argument(
        "--min-size",
        type=int,
        default=DEFAULT_MIN_SIZE,
        help=f"target lower bound of the sample band (default: {DEFAULT_MIN_SIZE})",
    )
    gold_sample_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE,
        help=f"target upper bound of the sample band (default: {DEFAULT_MAX_SIZE})",
    )
    gold_sample_parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"seed for deterministic selection (default: {DEFAULT_SEED})",
    )

    gold_subparsers.add_parser(
        "sheet",
        help=(
            "render the sampled chunk records under data/gold/chunks/ into "
            "data/gold/label_sheet.xlsx with codebook dropdowns"
        ),
    )

    gold_subparsers.add_parser(
        "deliver",
        help=(
            "package data/gold/label_sheet.xlsx into a dated handoff bundle "
            "under data/gold/delivery/<date>/ for the Academic (sheet copy, "
            "README, and manifest.json)"
        ),
    )

    subparsers.add_parser(
        "eval",
        help=(
            "score the Academic's returned label_sheet.xlsx under "
            "data/gold/labels/ against the tagger's own chunk records, "
            "writing data/gold/labels/eval_report.json"
        ),
    )

    vault_parser = subparsers.add_parser("vault", help="vault operations")
    vault_subparsers = vault_parser.add_subparsers(dest="vault_command")

    vault_write_parser = vault_subparsers.add_parser(
        "write",
        help=(
            "run the chunking + artifact-classification passes and write one prose "
            "note per chunk to data/vault/prose/ and one note per artifact to "
            "data/vault/artifacts/"
        ),
    )
    vault_write_parser.add_argument("source_path", help="path to a .pdf or .docx source file")

    polity_parser = subparsers.add_parser(
        "polity", help="offline canonical polity-map operations (deterministic, model-free)"
    )
    polity_subparsers = polity_parser.add_subparsers(dest="polity_command")

    polity_subparsers.add_parser(
        "build",
        help=(
            "scan the vault's prose notes for distinct polity verbatims and "
            "emit a deterministic seed canonical tree (YAML) to stdout, for "
            "the operator to curate into polity_canonical.yaml"
        ),
    )

    polity_subparsers.add_parser(
        "report",
        help=(
            "canonicalize the vault's collected polity verbatims against "
            "<domain>/polity_canonical.yaml, printing a JSON report (mapped/"
            "candidates/leaks/candidate_count) to stdout and a human "
            "notification to stderr"
        ),
    )

    drive_parser = subparsers.add_parser(
        "drive", help="Google Drive source connector operations (Sec. 7.10, P0-11)"
    )
    drive_subparsers = drive_parser.add_subparsers(dest="drive_command")

    drive_ingest_parser = drive_subparsers.add_parser(
        "ingest",
        help=(
            "list the Drive 'Books' folder, download each .pdf/.docx candidate "
            "to a local cache, and hand each off to the ingestion pipeline"
        ),
    )
    drive_ingest_parser.add_argument(
        "folder_id",
        nargs="?",
        default=None,
        help=(
            f"Drive folder id to list (default: [drive].books_folder_id from {DRIVE_SECRETS_PATH})"
        ),
    )

    ingest_parser = subparsers.add_parser(
        "ingest",
        help=(
            "run vault-write over every source path listed in a line-delimited "
            "worklist file, skipping sources already recorded as vault_status=OK "
            "in data/gold/ingest.results.tsv"
        ),
    )
    ingest_parser.add_argument(
        "worklist_path", help="path to a line-delimited worklist file of source paths"
    )

    run_parser = subparsers.add_parser(
        "run",
        help=(
            "run one registered per-source pass over a source set (a "
            "line-delimited worklist file or the data/sources/ corpus glob), "
            "isolating each source's failure (record FAIL and continue), and "
            "printing an end-of-run OK/FAIL/SKIP summary -- see issue #277"
        ),
    )
    run_parser.add_argument(
        "pass_name",
        metavar="pass",
        help=f"registered pass name (one of: {', '.join(sorted(PASS_REGISTRY))})",
    )
    run_parser.add_argument(
        "--worklist",
        dest="worklist_path",
        default=None,
        help=(
            "path to a line-delimited worklist file of source paths; "
            "mutually exclusive with --corpus, exactly one is required"
        ),
    )
    run_parser.add_argument(
        "--corpus",
        action="store_true",
        help=(
            "run over every data/sources/*.pdf and *.docx file, sorted; "
            "mutually exclusive with --worklist, exactly one is required"
        ),
    )
    run_parser.add_argument(
        "--domain",
        dest="domain_dir",
        default=str(DEFAULT_DOMAIN_DIR),
        help=(
            "path to a domain directory containing schema.yaml and codebook.yaml "
            f"(default: {DEFAULT_DOMAIN_DIR}); ignored by passes that take no domain"
        ),
    )
    run_parser.add_argument(
        "--ledger",
        dest="ledger_path",
        default=None,
        help=(
            "path to this run's resume ledger TSV (default: "
            "data/run/ledger.tsv, axial.run.LEDGER_PATH); give each of "
            "several concurrent `axial run` processes over disjoint source "
            "sets its own --ledger so they never share one append-mode file"
        ),
    )

    pipeline_ready_parser = subparsers.add_parser(
        "pipeline-ready",
        help=(
            "ingest every canary named in a TOML manifest and evaluate it "
            "against the 'pipeline ready' bar (single-attempt completion, "
            "quarantine budget, time envelope), printing a per-canary "
            "PASS/FAIL table"
        ),
    )
    pipeline_ready_parser.add_argument(
        "--manifest", required=True, help="path to a TOML manifest of canaries"
    )

    brief_parser = subparsers.add_parser(
        "brief", help="Phase-B brief intake operations (specs/PHASE-B.md §7.1)"
    )
    brief_subparsers = brief_parser.add_subparsers(dest="brief_command")

    brief_show_parser = brief_subparsers.add_parser(
        "show",
        help=(
            "load and validate a brief file, printing its case, request, "
            "lens, and computed brief_id (read-only, LLM-free)"
        ),
    )
    brief_show_parser.add_argument("brief_path", help="path to a versioned brief YAML file")

    brief_interrogate_parser = brief_subparsers.add_parser(
        "interrogate",
        help=(
            "run the bounded interrogation pre-pass over a loaded brief "
            "(specs/PHASE-B.md §7.2), persist the interrogation result, "
            "and print its disposition -- exits 0 on every disposition, "
            "including refuse"
        ),
    )
    brief_interrogate_parser.add_argument("brief_path", help="path to a versioned brief YAML file")

    brief_examine_parser = brief_subparsers.add_parser(
        "examine",
        help=(
            "run interrogation and retrieval and report the retrieved "
            "chunk_ids (retrieval order), the raw per-polity coverage "
            "counts, and the interrogation result -- makes ZERO stage-4 "
            "synthesis calls and writes nothing under data/analyses/ "
            "(specs/PHASE-B.md §5 stage 4, §7.5, §8 P0-9, issue #255)"
        ),
    )
    brief_examine_parser.add_argument("brief_path", help="path to a versioned brief YAML file")

    brief_run_parser = brief_subparsers.add_parser(
        "run",
        help=(
            "run the full engine (stages 1-6) over a brief and persist the "
            "analysis record to data/analyses/<brief_id>.json "
            "(specs/PHASE-B.md §7.3, §8 P0-8/P0-9) -- exits 0 on every "
            "disposition, including refuse"
        ),
    )
    brief_run_parser.add_argument("brief_path", help="path to a versioned brief YAML file")

    brief_validate_parser = brief_subparsers.add_parser(
        "validate",
        help=(
            "run the stage-5 attribution validator over a persisted "
            "analysis record at data/analyses/<brief_id>.json "
            "(specs/PHASE-B.md §7.9, issue #258) -- exits 0 only when every "
            "claim is marked and every (a)/(b) grounds pointer resolves"
        ),
    )
    brief_validate_parser.add_argument(
        "brief_id", help="brief_id of a persisted record under data/analyses/"
    )

    brief_usage_parser = brief_subparsers.add_parser(
        "usage",
        help=(
            "read analysis records under data/analyses/ and report per-source "
            "usage ratios pooled across runs sharing a corpus pin, broken down "
            "by tag filter (specs/PHASE-B.md §7.13, §8 P0-13, issue #266) -- "
            "makes ZERO model calls and gates nothing"
        ),
    )
    brief_usage_parser.add_argument(
        "--pin",
        default=None,
        help="corpus_pin to report on (default: the pin the most records share)",
    )

    pin_parser = subparsers.add_parser(
        "pin", help="corpus-pin manifest operations (specs/PHASE-B.md §7.12, §8 P0-10)"
    )
    pin_subparsers = pin_parser.add_subparsers(dest="pin_command")

    pin_write_parser = pin_subparsers.add_parser(
        "write",
        help=(
            "compute and write a corpus-pin manifest (source list + content "
            "hashes, ingest-code SHA, vault snapshot hash) to "
            "evals/corpus_pin/<name>.json (LLM-free)"
        ),
    )
    pin_write_parser.add_argument(
        "name", help="pin name, e.g. 'baseline' -> evals/corpus_pin/baseline.json"
    )

    reconcile_parser = subparsers.add_parser(
        "reconcile", help="safe reconciliation/GC for orphaned derived artifacts (issue #291)"
    )
    reconcile_subparsers = reconcile_parser.add_subparsers(dest="reconcile_command")

    reconcile_gc_parser = reconcile_subparsers.add_parser(
        "gc",
        help=(
            "list derived artifacts (trees/envelopes/chunks/tags/artifacts/"
            "xref/vault) whose source_id has no live file in data/sources/; "
            "dry run by default (nothing removed), --apply removes them after "
            "confirmation (or --yes for non-interactive) and writes a paths/"
            "source_ids-only removal log under data/logs/reconcile/"
        ),
    )
    reconcile_gc_parser.add_argument(
        "--apply",
        action="store_true",
        help="remove the listed orphaned files (after confirmation)",
    )
    reconcile_gc_parser.add_argument(
        "--yes",
        action="store_true",
        help="auto-confirm removal under --apply, for non-interactive runs",
    )

    return parser


def _schema_show(domain_dir: str) -> int:
    try:
        schema = load_schema(domain_dir)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"schema version: {schema.version}")
    for axis_name, axis in schema.axes.items():
        print(f"{axis_name}: cardinality={axis.cardinality} count={axis.value_count}")
    return 0


def _schema_validate(domain_dir: str) -> int:
    try:
        schema = load_schema(domain_dir)
        codebook = load_codebook(domain_dir)
    except (SchemaError, CodebookError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    findings = cross_validate(schema, codebook)

    if not findings:
        for axis_name in schema.axes:
            print(f"axis {axis_name}: consistent")
        return 0

    for finding in findings:
        print(f"error: {finding.message}", file=sys.stderr)
    return 1


def _intake(source_path: str) -> int:
    try:
        source = intake(source_path)
    except IntakeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"intake ok: {source.path.name} (format={source.format}, text_layer_ok=True)")
    return 0


def _safe_source_id(source_path: str) -> str:
    """Best-effort source_id for a run.jsonl record: falls back to "" when
    the path doesn't resolve to a real file (mirrors axial.ingest's own
    missing-source fallback row), so a record is always written even when
    `extract()` failed before a source_id could otherwise be computed."""
    try:
        return compute_source_id(Path(source_path))
    except MissingSourceError:
        return ""


def _extract(
    source_path: str,
    *,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    """Run structural extraction on `source_path`, wrapped in a run-logging
    context (issue #270 slice 01): one `run.jsonl` record per call, teed
    `console.log`, and the pass's existing stdout unchanged. `root`/`clock`
    are the run_context determinism seam -- tests inject both; the CLI's own
    call site (main(), below) passes neither and gets the real
    `data/logs/extract-<now>/`."""
    with run_context("extract", root=root, clock=clock) as run:
        start = time.monotonic()
        try:
            tree = extract(source_path)
        except ExtractError as exc:
            run.record(
                source_id=_safe_source_id(source_path),
                pass_name="extract",
                model=None,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id=_safe_source_id(source_path),
            pass_name="extract",
            model=None,
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )

    print(json.dumps(tree, sort_keys=True))
    return 0


def _envelope(
    source_path: str,
    *,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    """Run the structural-envelope pass on `source_path`, wrapped in a
    run-logging context (issue #270 slice 02): one `run.jsonl` record per
    call, teed `console.log`, the pass's existing stdout unchanged.
    `root`/`clock` are the run_context determinism seam (mirrors
    `_extract`, slice 01).

    The client is built once here, before calling `run_envelope`, rather
    than left for `run_envelope` to build lazily on its own cache miss --
    mirroring `axial.run.run_pass`'s own already-established precedent of
    constructing the pass's client once up front. This is how the record's
    `model` field is known even on a cache hit (`run_envelope` then returns
    the stored envelope without ever calling `.complete()` on the client
    passed in -- the "no recompute" guarantee, PRD §10, is unaffected: only
    construction moved earlier, no completion call was added)."""
    with run_context("envelope", root=root, clock=clock) as run:
        start = time.monotonic()
        client = get_client()
        model = client.model_for_pass(ENVELOPE_PASS_NAME)
        try:
            envelope = run_envelope(source_path, client=client)
        except EnvelopeError as exc:
            run.record(
                source_id=_safe_source_id(source_path),
                pass_name="envelope",
                model=model,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id=_safe_source_id(source_path),
            pass_name="envelope",
            model=model,
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )

    print(json.dumps(envelope, sort_keys=True))
    return 0


def _chunk(source_path: str) -> int:
    """Run the recursive/structural chunk stage (issue #165, slice 06; the
    sole chunk mechanism as of issue #191): deterministic, zero-embedding,
    zero-LLM."""
    try:
        records = run_chunk_recursive(source_path)
    except ChunkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"chunk: wrote {len(records)} record(s) for {Path(source_path).name}")
    return 0


def _print_encoding_safe(text: str) -> None:
    """Print `text` to stdout without crashing when stdout's codec (e.g.
    Windows' default `cp1252`) cannot represent one of its characters.
    Reconfigures stdout to UTF-8 where supported; falls back to writing
    backslash-escaped bytes through the raw buffer so the report is still
    emitted (never dropped) if reconfigure isn't available. Content/wording
    is untouched -- only the emission path changes."""
    stdout = sys.stdout
    reconfigure = getattr(stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
            print(text)
            return
        except (ValueError, OSError):
            pass

    buffer = getattr(stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8", errors="backslashreplace"))
        buffer.write(b"\n")
        buffer.flush()
    else:
        print(text.encode("ascii", errors="backslashreplace").decode("ascii"))


def _chunk_examine() -> int:
    """`axial chunk examine` (issue #153): read-only inspection over the
    on-disk chunk artifact(s) under `data/chunks/` -- zero LLM/embedding
    calls, zero mutation. Resolves the chunks dir via the same seam the
    producer uses (`_default_chunks_dir`) so it honors `config/pipeline.
    yaml`'s `paths.chunks_dir` when declared."""
    chunks_dir = _default_chunks_dir()
    try:
        stats = examine_chunks(chunks_dir)
    except ChunkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_encoding_safe(format_examine_report(stats))
    return 0


def _tag(
    source_path: str,
    domain_dir: str,
    *,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    """Run the tagging pass on `source_path`, wrapped in a run-logging
    context (issue #270 slice 02): one `run.jsonl` record per CALL (per
    source, not per chunk -- `run_tag` makes one LLM call per chunk
    internally, but this wraps the whole invocation in a single record, so
    `run.jsonl` stays ~one row/source, mirroring the plan's per-source
    granularity default). `root`/`clock` mirror `_extract`/`_envelope`."""
    with run_context("tag", root=root, clock=clock) as run:
        start = time.monotonic()
        client = get_client()
        model = client.model_for_pass(TAG_PASS_NAME)
        try:
            records = run_tag(source_path, client=client, domain_dir=domain_dir)
        except TagError as exc:
            run.record(
                source_id=_safe_source_id(source_path),
                pass_name="tag",
                model=model,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id=_safe_source_id(source_path),
            pass_name="tag",
            model=model,
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )

    print(json.dumps(records))
    return 0


def _artifacts(source_path: str, domain: str) -> int:
    try:
        records = run_artifacts(source_path, domain_dir=domain)
    except (ArtifactsError, TagError) as exc:
        # `TagError` (specifically `axial.tag.TagNotInSchemaError`) is
        # caught here too: `axial.artifacts` reuses that shared error for
        # both the `artifact_role` and `field` axes (issue #32 slice 02's
        # carry-in convergence), and it is a `TagError`, not an
        # `ArtifactsError` -- so this CLI handler must catch both to avoid a
        # bare traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(records))
    return 0


def _xref(source_path: str, domain: str) -> int:
    try:
        pairs = run_xref(source_path, domain_dir=domain)
    except XrefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(pairs))
    return 0


def _gold_sample(min_size: int, max_size: int, seed: int) -> int:
    try:
        written = run_gold_sample(min_size=min_size, max_size=max_size, seed=seed)
    except GoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps([str(path) for path in written]))
    return 0


def _gold_sheet() -> int:
    try:
        path = run_gold_sheet()
    except GoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(str(path)))
    return 0


def _gold_deliver() -> int:
    try:
        delivery_dir = run_gold_deliver()
    except GoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(str(delivery_dir)))
    return 0


def _eval(
    *,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    """Score the gold set, wrapped in a run-logging context (issue #270
    slice 02). Two deliberate departures from the other three passes, both
    because `run_eval` genuinely differs from them, not by oversight:

    - `model=None` always -- `run_eval` is an offline join over two on-disk
      inputs (the tagger's own sampled chunk records and the Academic's
      returned answer key) and makes no LLM call at all (see
      `axial.eval.run_eval`'s own docstring: "Offline and deterministic: no
      LLM call, no network"). This mirrors slice 01's own `extract`
      precedent for a model-free pass (`plans/run-logging/README.md`: "The
      model field is nullable ... that is a feature, not a gap").
    - One record per invocation, `source_id=""` -- `axial eval` takes no
      source_path (unlike extract/envelope/tag); it scores the WHOLE gold
      set in one atomic pass, so "one record per source" does not apply.
      `source_id=""` mirrors `_safe_source_id`'s own no-source-resolved
      fallback."""
    with run_context("eval", root=root, clock=clock) as run:
        start = time.monotonic()
        try:
            path = run_eval()
        except (EvalError, GoldError, PolityCanonicalError) as exc:
            run.record(
                source_id="",
                pass_name="eval",
                model=None,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id="",
            pass_name="eval",
            model=None,
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )

    print(json.dumps(str(path)))
    return 0


def _vault_write(source_path: str) -> int:
    try:
        written = run_vault_write(source_path)
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps([str(path) for path in written]))
    return 0


def _polity_build() -> int:
    text = run_polity_build()
    print(text, end="")
    return 0


def _polity_report() -> int:
    try:
        report = run_polity_report()
    except PolityCanonicalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report))

    notes: list[str] = []
    if report["candidates"]:
        notes.append(f"{len(report['candidates'])} candidate(s) unresolved:")
        for candidate in report["candidates"]:
            notes.append(f"  - {candidate['verbatim']} (count={candidate['count']})")
    if report["leaks"]:
        notes.append(f"{len(report['leaks'])} leak(s) flagged (never folded):")
        for leak in report["leaks"]:
            notes.append(f"  - {leak['verbatim']} -> {', '.join(leak['parts'])}")
    if notes:
        print("\n".join(notes), file=sys.stderr)
    else:
        print("nothing to resolve: all polities resolved", file=sys.stderr)

    return 0


def _drive_ingest(folder_id: str | None) -> int:
    """`axial drive ingest [folder_id]`: resolve `folder_id` to
    `[drive].books_folder_id` when omitted, then run the connector with
    production defaults (real `DriveClient`, real `run_vault_write`)."""
    if folder_id is None:
        try:
            secrets = _load_drive_secrets(DRIVE_SECRETS_PATH)
        except DriveSecretsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        folder_id = secrets["books_folder_id"]

    return run_drive_ingest(folder_id)


def _ingest(worklist_path: str) -> int:
    return run_ingest(worklist_path)


def _run(
    pass_name: str,
    worklist_path: str | None,
    corpus: bool,
    domain_dir: str,
    ledger_path: str | None = None,
) -> int:
    summary, exit_code = run_pass(
        pass_name,
        worklist_path,
        corpus=corpus,
        domain_dir=domain_dir,
        ledger_path=Path(ledger_path) if ledger_path is not None else None,
    )

    # Issue #288: attach and print the theory_school not-applicable/unlisted
    # rates report as a post-processing step over this run's own OK/SKIP
    # sources -- a CONSUMER of `summary`, never reaching into `run_pass`'s
    # own loop, and safe to call after any pass (a pass with no persisted
    # theory_school data simply yields no rows to print). Never affects
    # `exit_code`: the report must never block or fail the run.
    summary = attach_theory_school_rates(summary)
    rendered = render_theory_school_rates(summary.rates or [])
    if rendered:
        print("theory_school not-applicable/unlisted rates:")
        print(rendered)

    return exit_code


def _pipeline_ready(manifest_path: str) -> int:
    try:
        table_text, exit_code = run_pipeline_ready(manifest_path)
    except PipelineReadyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(table_text)
    return exit_code


def _brief_show(brief_path: str) -> int:
    try:
        brief = load_brief(brief_path)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"brief_id: {brief.brief_id}")
    print(f"case: {brief.case}")
    print(f"request: {brief.request}")
    print(f"lens: {brief.lens if brief.lens is not None else '(none)'}")
    return 0


def _brief_interrogate(brief_path: str) -> int:
    try:
        brief = load_brief(brief_path)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = get_client()
    try:
        result = interrogate(brief, client=client)
    except InterrogationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    path = persist_interrogation(brief, result)

    print(f"brief_id: {brief.brief_id}")
    print(f"disposition: {result.disposition}")
    for premise in result.premises_found:
        print(f"  premise ({premise.assessment}): {premise.premise}")
    for bound in result.bounds_applied:
        print(f"  bound: {bound}")
    if result.refusal is not None:
        print(f"refusal: {result.refusal['reason']}")
    print(f"persisted: {path}")
    # §7.2: a `refuse` disposition is a completed, valid run -- exit 0 on
    # every disposition, never just the non-refusing ones.
    return 0


def _brief_examine(brief_path: str) -> int:
    try:
        brief = load_brief(brief_path)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = get_client()
    try:
        result = run_examine(brief, client=client)
    except (InterrogationError, QueryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_brief_examine_report(brief, result))
    # P0-9 inspect-before-spend: examine makes no stage-4 synthesis call, so
    # a `refuse` disposition -- like every other disposition -- is a
    # completed run, exit 0 (mirrors `_brief_interrogate`'s own §7.2 rule).
    return 0


def _brief_run(brief_path: str) -> int:
    try:
        brief = load_brief(brief_path)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = get_client()
    try:
        result = run_brief(brief, client=client)
    except (InterrogationError, QueryError, SynthesisError, CorpusPinError, AnswerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"brief_id: {brief.brief_id}")
    print(f"disposition: {result.record['interrogation']['disposition']}")
    print(f"persisted: {result.path}")
    # §7.2: a `refuse` disposition is a completed, valid run -- exit 0 on
    # every disposition (mirrors `_brief_interrogate`/`_brief_examine`).
    return 0


def _brief_validate(brief_id: str) -> int:
    record_path = default_analyses_dir() / f"{brief_id}.json"
    if not record_path.is_file():
        print(
            f"error: no analysis record found for brief_id {brief_id!r} "
            f"(expected at {record_path})",
            file=sys.stderr,
        )
        return 1

    record = json.loads(record_path.read_text(encoding="utf-8"))

    client = get_client()
    try:
        report = validate_attribution(record, client=client)
    except AttributionValidatorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"brief_id: {brief_id}")
    print(format_attribution_report(report))
    # A failure blocks release (§7.9): no answer is emitted on a non-zero
    # exit, and this command never writes to `record_path` either way --
    # the validator only ever reports (README.md: "it never edits the
    # record").
    return 0 if report.passed else 1


def _brief_usage(pin: str | None) -> int:
    analyses_dir = default_analyses_dir()
    records, unreadable_count = load_analysis_records(analyses_dir)
    report = build_usage_report(records, pin=pin, unreadable_count=unreadable_count)
    print(format_usage_report(report))
    # P0-13: the report gates nothing -- no ratio value drives the exit
    # code, mirroring `chunk examine`'s own inspect-before-spend contract.
    return 0


def _pin_write(name: str) -> int:
    try:
        path = write_pin(name)
    except CorpusPinError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(str(path)))
    return 0


def _reconcile_gc(apply: bool, yes: bool) -> int:
    try:
        result = run_gc(apply=apply, yes=yes)
    except ReconcileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_gc_report(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"axial {axial.__version__}")
        return 0

    if args.command == "schema" and args.schema_command == "show":
        return _schema_show(args.domain_dir)

    if args.command == "schema" and args.schema_command == "validate":
        return _schema_validate(args.domain_dir)

    if args.command == "intake":
        return _intake(args.source_path)

    if args.command == "extract":
        return _extract(args.source_path)

    if args.command == "envelope":
        return _envelope(args.source_path)

    if args.command == "chunk" and args.source_path == "examine":
        return _chunk_examine()

    if args.command == "chunk":
        return _chunk(args.source_path)

    if args.command == "tag":
        return _tag(args.source_path, args.domain_dir)

    if args.command == "artifacts":
        return _artifacts(args.source_path, args.domain)

    if args.command == "xref":
        return _xref(args.source_path, args.domain)

    if args.command == "gold" and args.gold_command == "sample":
        return _gold_sample(args.min_size, args.max_size, args.seed)

    if args.command == "gold" and args.gold_command == "sheet":
        return _gold_sheet()

    if args.command == "gold" and args.gold_command == "deliver":
        return _gold_deliver()

    if args.command == "eval":
        return _eval()

    if args.command == "vault" and args.vault_command == "write":
        return _vault_write(args.source_path)

    if args.command == "polity" and args.polity_command == "build":
        return _polity_build()

    if args.command == "polity" and args.polity_command == "report":
        return _polity_report()

    if args.command == "drive" and args.drive_command == "ingest":
        return _drive_ingest(args.folder_id)

    if args.command == "ingest":
        return _ingest(args.worklist_path)

    if args.command == "run":
        return _run(
            args.pass_name, args.worklist_path, args.corpus, args.domain_dir, args.ledger_path
        )

    if args.command == "pipeline-ready":
        return _pipeline_ready(args.manifest)

    if args.command == "brief" and args.brief_command == "show":
        return _brief_show(args.brief_path)

    if args.command == "brief" and args.brief_command == "interrogate":
        return _brief_interrogate(args.brief_path)

    if args.command == "brief" and args.brief_command == "examine":
        return _brief_examine(args.brief_path)

    if args.command == "brief" and args.brief_command == "run":
        return _brief_run(args.brief_path)

    if args.command == "brief" and args.brief_command == "validate":
        return _brief_validate(args.brief_id)

    if args.command == "brief" and args.brief_command == "usage":
        return _brief_usage(args.pin)

    if args.command == "pin" and args.pin_command == "write":
        return _pin_write(args.name)

    if args.command == "reconcile" and args.reconcile_command == "gc":
        return _reconcile_gc(args.apply, args.yes)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
