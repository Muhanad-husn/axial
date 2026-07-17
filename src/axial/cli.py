"""Command-line entry point for axial."""

import argparse
import json
import sys
from pathlib import Path

import axial
from axial.artifacts import ArtifactsError, run_artifacts
from axial.chunk import (
    ChunkError,
    _default_chunks_dir,
    examine_chunks,
    format_examine_report,
    run_chunk_recursive,
)
from axial.codebook import CodebookError, load_codebook
from axial.envelope import EnvelopeError, run_envelope
from axial.eval import EvalError, run_eval
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
from axial.pipeline_ready import PipelineReadyError, run_pipeline_ready
from axial.polity_canonical import PolityCanonicalError, run_polity_build, run_polity_report
from axial.schema import SchemaError, load_schema
from axial.tag import DEFAULT_DOMAIN_DIR, TagError, run_tag
from axial.validate import cross_validate
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


def _extract(source_path: str) -> int:
    try:
        tree = extract(source_path)
    except ExtractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(tree, sort_keys=True))
    return 0


def _envelope(source_path: str) -> int:
    try:
        envelope = run_envelope(source_path)
    except EnvelopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

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


def _tag(source_path: str, domain_dir: str) -> int:
    try:
        records = run_tag(source_path, domain_dir=domain_dir)
    except TagError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

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


def _eval() -> int:
    try:
        path = run_eval()
    except (EvalError, GoldError, PolityCanonicalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

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


def _ingest(worklist_path: str) -> int:
    return run_ingest(worklist_path)


def _pipeline_ready(manifest_path: str) -> int:
    try:
        table_text, exit_code = run_pipeline_ready(manifest_path)
    except PipelineReadyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(table_text)
    return exit_code


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

    if args.command == "ingest":
        return _ingest(args.worklist_path)

    if args.command == "pipeline-ready":
        return _pipeline_ready(args.manifest)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
