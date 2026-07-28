"""Command-line entry point for axial."""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import axial
from axial.analyze import format_examine_report as format_brief_examine_report
from axial.analyze import run_examine
from axial.analyze.synthesis import SynthesisError
from axial.answer import AnswerError, run_brief
from axial.answer.usage_report import build_usage_report, format_usage_report, load_analysis_records
from axial.artifacts import ArtifactsError, run_artifacts
from axial.brief import BriefError, load_brief
from axial.brief.interrogate import InterrogationError, interrogate, persist_interrogation
from axial.brief.sweep import DEFAULT_WORKERS as SWEEP_DEFAULT_WORKERS
from axial.brief.sweep import SweepError, format_sweep_summary, run_sweep
from axial.chunk import (
    ChunkError,
    _default_chunks_dir,
    examine_chunks,
    format_examine_report,
    run_chunk_recursive,
)
from axial.codebook import CodebookError, load_codebook
from axial.distill.classify import AXES as DISTILL_CLASSIFY_AXES
from axial.distill.classify import ClassifyError, run_classify
from axial.distill.classify_embedding import AXES as DISTILL_CLASSIFY_EMBEDDING_AXES
from axial.distill.classify_embedding import ClassifyEmbeddingError, run_classify_embedding
from axial.distill.embed import EmbedError, run_embed
from axial.distill.readiness import ReadinessError, run_readiness
from axial.drive import DEFAULT_SECRETS_PATH as DRIVE_SECRETS_PATH
from axial.drive import DriveSecretsError, _load_drive_secrets, run_drive_ingest
from axial.envelope import EnvelopeError, MissingSourceError, compute_source_id, run_envelope
from axial.eval import EvalError, run_eval
from axial.interrogate import InterrogateError, run_interrogate
from axial.eval.corpus_pin import CorpusPinError, write_pin
from axial.extract import ExtractError, extract
from axial.gates import (
    ADVERSARIAL_GATE_NAME,
    AdversarialGateError,
    CalibrationGateError,
    GateError,
    GroundingGateError,
    format_report,
    load_records,
    load_seeded_briefs,
    resolve_trusted,
    run_gate,
    write_report,
)
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
from axial.llm import (
    ENVELOPE_PASS_NAME,
    NOTE_INTERROGATE_PASS_NAME,
    LLMError,
    get_client,
)
from axial.merge_names import DEFAULT_WORKERS as MERGE_DEFAULT_WORKERS
from axial.merge_names import MergeNamesError, run_merge_names
from axial.names import (
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES,
    NamesError,
    examine_names,
    format_names_report,
    run_names,
)
from axial.panel import (
    MIN_REVIEWERS as PANEL_MIN_REVIEWERS,
)
from axial.panel import (
    ControlError,
    PacketError,
    PanelError,
    VendorError,
    format_panel_run,
    run_panel,
)
from axial.paths import DEFAULT_DOMAIN_DIR, default_analyses_dir
from axial.pipeline_ready import PipelineReadyError, run_pipeline_ready
from axial.polity_canonical import PolityCanonicalError, run_polity_build, run_polity_report
from axial.query.reader import QueryError
from axial.reconcile import ReconcileError, format_gc_report, run_gc
from axial.run import (
    PASS_REGISTRY,
    run_pass,
)
from axial.runlog import run_context
from axial.schema import SchemaError, load_schema
from axial.tagging_schema import TagError
from axial.validate import cross_validate
from axial.validators import (
    AttributionValidatorError,
    CounterPositionValidatorError,
    format_attribution_report,
    format_counter_position_report,
    validate_attribution,
    validate_counter_position,
)
from axial.validators.coverage import (
    compute_coverage_map,
    format_coverage_confidence_report,
    format_coverage_map,
    validate_coverage_and_confidence,
)
from axial.vault import VaultError, run_vault_write


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

    interrogate_parser = subparsers.add_parser(
        "interrogate",
        help=(
            "run the per-note interrogation pass (one open-question call per "
            "note), appending one answer record per note to "
            "<data>/answers/<source_id>.jsonl and printing the run summary "
            "(collapse check, abstention rates, measured cost) to stdout"
        ),
    )
    interrogate_parser.add_argument("source_path", help="path to a .pdf or .docx source file")
    interrogate_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "stop after this many notes are interrogated this run -- the "
            "~50-output sample gate (D14): the outputs and the summary are "
            "read before the rest of the corpus is paid for"
        ),
    )
    interrogate_parser.add_argument(
        "--data-dir",
        dest="data_dir",
        default=None,
        help=(
            "rebase the four directories this pass touches (chunks/, "
            "envelopes/, source_meta/, answers/) onto this parent, so a probe "
            "can be pointed at another checkout's data/ (default: each "
            "resolved from config/pipeline.yaml)"
        ),
    )
    interrogate_parser.add_argument(
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

    names_parser = subparsers.add_parser(
        "names",
        help=(
            "Phase A v1 slice 04 (issue #415): the name inventory and "
            "similarity view (LLM-free, D10, spec §7.16) -- 'build' collects "
            "every distinct name surface form (names[]/citations[].cited) "
            "out of data/answers/, writes the lossless inventory to "
            "data/names/inventory.jsonl, embeds and clusters it, and persists "
            "the result to data/names/embeddings.lance; 'examine' reports the "
            "cluster-size and nearest-neighbour similarity distribution over "
            "that persisted result (zero model/embedding calls); 'merge' is "
            "slice 05 (Reconcile, issue #416) -- the model's own merge calls, "
            "one cluster at a time, into a reversible alias map. Unrelated to "
            "`axial reconcile gc`, which is model-free orphan GC (#291)"
        ),
    )
    names_subparsers = names_parser.add_subparsers(dest="names_command")
    names_build_parser = names_subparsers.add_parser(
        "build",
        help=(
            "collect every distinct name surface form from data/answers/ "
            "(names[]/citations[].cited only, §7.16), write "
            "data/names/inventory.jsonl, embed each with the local "
            "sentence-transformer, cluster with HDBSCAN, and persist vectors "
            "+ cluster labels to data/names/embeddings.lance "
            "(data/names/similarity_manifest.json)"
        ),
    )
    names_build_parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=None,
        help=(
            "HDBSCAN's min_cluster_size for the single clustering persisted "
            f"by this build (default: {DEFAULT_MIN_CLUSTER_SIZE}, D10's "
            "loosest -- explore tightness afterwards via `names examine`, "
            "which re-clusters the persisted vectors instead of rebuilding)"
        ),
    )
    names_build_parser.add_argument(
        "--min-samples",
        type=int,
        default=None,
        help=(
            "HDBSCAN's min_samples for the single clustering persisted by "
            f"this build (default: {DEFAULT_MIN_SAMPLES}, D10's loosest)"
        ),
    )
    names_examine_parser = names_subparsers.add_parser(
        "examine",
        help=(
            "read the persisted name inventory back and report the cluster-"
            "size, noise-fraction and nearest-neighbour similarity "
            "distribution at a sweep of candidate tightnesses, plus a "
            "borderline-pair sample per tightness -- the viewing aid slice "
            "05 (Reconcile) sets its merge aggressiveness from (D10, P0-12); "
            "re-clusters the persisted vectors, zero model/embedding calls"
        ),
    )
    names_examine_parser.add_argument(
        "--min-cluster-sizes",
        default=None,
        help=(
            "comma-separated min_cluster_size candidates to sweep -- the "
            "cheap axis: one HDBSCAN fit total, every other candidate is a "
            "near-instant relabel of that fit's own tree (default: "
            f"{','.join(str(value) for value in DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES)})"
        ),
    )
    names_examine_parser.add_argument(
        "--min-samples",
        type=int,
        default=None,
        help=(
            "HDBSCAN's min_samples, held fixed across the sweep (default: "
            f"{DEFAULT_MIN_SAMPLES}) -- the expensive axis: changing it costs "
            "a fresh fit, so compare it by re-running `examine` at a "
            "different value rather than passing a list"
        ),
    )

    names_merge_parser = names_subparsers.add_parser(
        "merge",
        help=(
            "Phase A v1 slice 05 (issue #416): Reconcile -- re-cluster the "
            "persisted name vectors at the configured merge tightness and let "
            "the model decide which surface forms in each cluster name the "
            "same thing (temperature 1, reasoning high, §7.9's `reconcile` "
            "pass), asking a bounded number of clusters at once (--workers). "
            "Writes the reversible alias map to data/names/alias_map.json, the "
            "surviving-name index to data/names/index.json, and whether this "
            "run answered every cluster to data/names/merge_manifest.json; "
            "every decision is logged to data/names/merge_decisions.jsonl, so "
            "a re-run reproduces the same merges (regardless of which worker "
            "finished first) and resumes where it stopped"
        ),
    )
    names_merge_parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=None,
        help=(
            "merge aggressiveness (D10): HDBSCAN's min_cluster_size for the "
            "clusters the model is asked about (default: config/pipeline.yaml's "
            "names.merge_min_cluster_size) -- pick it by reading `axial names "
            "examine`'s tightness sweep"
        ),
    )
    names_merge_parser.add_argument(
        "--min-samples",
        type=int,
        default=None,
        help=(
            "HDBSCAN's min_samples for the same clustering (default: "
            "config/pipeline.yaml's names.merge_min_samples)"
        ),
    )
    names_merge_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "stop after this many model calls this run, still writing the map "
            "from every decision recorded so far -- a bounded, cheap first look "
            "before committing to a full pass"
        ),
    )
    names_merge_parser.add_argument(
        "--workers",
        type=int,
        default=MERGE_DEFAULT_WORKERS,
        help=(
            "bounded concurrent cluster-decision workers (issue #416: this pass "
            "is I/O-bound, and serial calls project to hours for a corpus this "
            f"size) (default: {MERGE_DEFAULT_WORKERS}, a starting value -- "
            "per-call latency has not been observed on the real corpus yet)"
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
            "run the stage-5 attribution, counter-position, and "
            "coverage/confidence validators over a persisted analysis record "
            "at data/analyses/<brief_id>.json (specs/PHASE-B.md §7.9, issues "
            "#258/#259/#260) -- exits 0 only when every claim is marked, "
            "every (a)/(b) grounds pointer resolves, a contested brief's "
            "§7.8 counter-position section is present or explicitly "
            "disclosed one-sided, every polity the claims touch has a "
            "coverage_map entry, and a confidence disclosure is present and "
            "not overconfident"
        ),
    )
    brief_validate_parser.add_argument(
        "brief_id", help="brief_id of a persisted record under data/analyses/"
    )

    brief_coverage_parser = brief_subparsers.add_parser(
        "coverage",
        help=(
            "print the §7.7 per-polity coverage map (corpus/evidence chunk "
            "counts and coverage_band) computed from a persisted record's "
            "claims -- the inspection affordance for the coverage_bands "
            "config, LLM-free (specs/PHASE-B.md §7.7, issue #260)"
        ),
    )
    brief_coverage_parser.add_argument(
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

    brief_sweep_parser = brief_subparsers.add_parser(
        "sweep",
        help=(
            "run every brief in a worklist N times each ('draws'), concurrently "
            "and resumably, then score each brief's own 4 rung-3 gates and "
            "quorum-accuracy (self-consistency) figure over just its own draws "
            "(issue #368) -- each (brief, draw) writes to its own directory "
            "under --sweep-dir, never clobbering another draw's record"
        ),
    )
    brief_sweep_parser.add_argument(
        "worklist_path", help="path to a line-delimited worklist file of brief YAML paths"
    )
    brief_sweep_parser.add_argument(
        "--draws", type=int, required=True, help="number of times to run each brief"
    )
    brief_sweep_parser.add_argument(
        "--sweep-dir",
        dest="sweep_dir",
        required=True,
        help="root directory for this sweep's per-(brief, draw) output and gate reports",
    )
    brief_sweep_parser.add_argument(
        "--workers",
        type=int,
        default=SWEEP_DEFAULT_WORKERS,
        help=f"bounded concurrent (brief, draw) workers (default: {SWEEP_DEFAULT_WORKERS})",
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

    distill_parser = subparsers.add_parser(
        "distill", help="stage-5 distillation-eval operations (DEC-35, issue #296)"
    )
    distill_subparsers = distill_parser.add_subparsers(dest="distill_command")

    distill_subparsers.add_parser(
        "embed",
        help=(
            "embed every vault prose chunk once via a local sentence-transformer "
            "and persist the vectors + filterable metadata (source_id, tag axes) "
            "in a LanceDB store (data/distill/embeddings.lance), recording the "
            "corpus-pin id/hash this pass ran against (data/distill/embedding_manifest.json)"
        ),
    )

    distill_subparsers.add_parser(
        "readiness-map",
        help=(
            "cluster every persisted chunk embedding (PCA + HDBSCAN, DEC-35, zero "
            "LLM spend) and emit the readiness map: per tag, whether it sits in a "
            "tight cluster or smears as noise (HDBSCAN's own -1 label, never "
            "cluster 0, is the LLM-routed tail) -- data/distill/readiness_manifest.json"
        ),
    )

    classify_parser = distill_subparsers.add_parser(
        "classify",
        help=(
            "stage-5d classifier eval: TF-IDF + LogisticRegression for claim_type/"
            "theory_school (DEC-37/38), LogisticRegression on dense embeddings for "
            "field (DEC-39) -- trains on the corpus's existing tags (gold chunks "
            "excluded), scores against the independent gold sheet at a confidence-"
            "threshold sweep -- data/distill/classify_<axis>_manifest.json. Eval "
            "artifact only; never wired into the production tag pass."
        ),
    )
    classify_parser.add_argument(
        "axis",
        choices=list(DISTILL_CLASSIFY_AXES) + list(DISTILL_CLASSIFY_EMBEDDING_AXES),
        help="the tag axis to train a classifier for",
    )

    panel_parser = subparsers.add_parser(
        "panel",
        help=(
            "sealed-packet peer-reviewer panel -- eval #1's OFFLINE "
            "answer-quality instrument (specs/PHASE-B.md §9.4, issue #385); "
            "never part of a brief run"
        ),
    )
    panel_subparsers = panel_parser.add_subparsers(dest="panel_command")

    panel_run_parser = panel_subparsers.add_parser(
        "run",
        help=(
            "run the positive control, then review a sample of analysis "
            "records; no number is trusted unless the control caught every "
            "planted defect"
        ),
    )
    panel_run_parser.add_argument(
        "--records",
        required=True,
        help="directory of analysis-record JSON files to review (the sample)",
    )
    panel_run_parser.add_argument(
        "--control-record",
        required=True,
        dest="control_record",
        help=(
            "path to the analysis record the positive control plants its "
            "three defects into; it must be able to carry all three"
        ),
    )
    panel_run_parser.add_argument(
        "--reviewers",
        type=int,
        default=PANEL_MIN_REVIEWERS,
        help=f"how many independent reviewers (default and minimum: {PANEL_MIN_REVIEWERS})",
    )
    panel_run_parser.add_argument(
        "--out",
        default=None,
        help=(
            "optional path to write the run's JSON verdicts to. Nothing is "
            "written without it, deliberately: a reviewer's free-text note "
            "can quote source text, and DEC-23 keeps that out of the repo -- "
            "point this under data/ (gitignored), never at evals/"
        ),
    )

    gate_parser = subparsers.add_parser(
        "gate", help="rung-3 eval-gate harness (specs/PHASE-B.md §10, §8 P0-12)"
    )
    gate_subparsers = gate_parser.add_subparsers(dest="gate_command")

    gate_run_parser = gate_subparsers.add_parser(
        "run",
        help=(
            "score a named gate (attribution-fidelity, grounding, "
            "synthesis-quality, calibration, adversarial) over a directory of "
            "analysis records or (adversarial) seeded briefs, writing "
            "evals/reports/<gate>.json"
        ),
    )
    gate_run_parser.add_argument(
        "gate",
        help=(
            "which gate to run: attribution-fidelity, grounding, "
            "synthesis-quality, calibration, or adversarial"
        ),
    )
    gate_run_parser.add_argument(
        "--dry-run",
        action="store_true",
        required=False,
        help=(
            "accepted for backward compatibility; has no effect. `trusted` "
            "resolves from the corpus pin alone (§9.2, issue #387) -- an "
            "unambiguous pin under evals/corpus_pin/ makes a run trusted "
            "regardless of this flag"
        ),
    )
    gate_run_parser.add_argument(
        "--records",
        default=None,
        help="directory of analysis-record JSON files to score (attribution-fidelity, grounding)",
    )
    gate_run_parser.add_argument(
        "--briefs",
        default=None,
        help="directory of seeded adversarial brief YAML files to score (adversarial, issue #264)",
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


def _interrogate(
    source_path: str,
    domain_dir: str | None,
    data_dir: str | None,
    limit: int | None,
    *,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    """Run the per-note interrogation pass on `source_path` (PRD §7.15,
    P0-6), wrapped in a run-logging context like every other per-source pass
    -- one `run.jsonl` record per invocation, not per note; the per-CALL
    visibility a long run needs is already `llm.py`'s own
    `llm_call_request`/`llm_call_response` lines plus this pass's own
    per-note stderr line. The run summary (collapse check, abstention rates,
    measured and extrapolated cost) is the stdout payload."""
    resolved_data_dir = Path(data_dir) if data_dir else None
    if root is None and resolved_data_dir is not None:
        root = resolved_data_dir / "logs"
    with run_context("interrogate", root=root, clock=clock) as run:
        start = time.monotonic()
        try:
            client = get_client()
        except LLMError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        try:
            summary = run_interrogate(
                source_path,
                client=client,
                data_dir=resolved_data_dir,
                domain_dir=domain_dir,
                limit=limit,
            )
        except (InterrogateError, LLMError) as exc:
            run.record(
                source_id=_safe_source_id(source_path),
                pass_name=NOTE_INTERROGATE_PASS_NAME,
                model=None,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id=summary["source_id"],
            pass_name=NOTE_INTERROGATE_PASS_NAME,
            model=summary["model"],
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )

    print(json.dumps(summary))
    return 0


def _artifacts(source_path: str, domain: str) -> int:
    try:
        records = run_artifacts(source_path, domain_dir=domain)
    except (ArtifactsError, TagError) as exc:
        # `TagError` (specifically `axial.tagging_schema.TagNotInSchemaError`)
        # is caught here too: `axial.artifacts` reuses that shared error for
        # both the `artifact_role` and `field` axes (issue #32 slice 02's
        # carry-in convergence), and it is a `TagError`, not an
        # `ArtifactsError` -- so this CLI handler must catch both to avoid a
        # bare traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(records))
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
    _summary, exit_code = run_pass(
        pass_name,
        worklist_path,
        corpus=corpus,
        domain_dir=domain_dir,
        ledger_path=Path(ledger_path) if ledger_path is not None else None,
    )
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
    print(f"answer: {result.markdown_path}")
    # §7.2: a `refuse` disposition is a completed, valid run -- exit 0 on
    # every disposition (mirrors `_brief_interrogate`/`_brief_examine`).
    return 0


def _load_analysis_record(brief_id: str) -> tuple[dict[str, Any], Path] | None:
    """Shared by `_brief_validate`/`_brief_coverage`: load
    `<analyses_dir>/<brief_id>.json`, printing a named error and returning
    `None` when no record exists rather than raising."""
    record_path = default_analyses_dir() / f"{brief_id}.json"
    if not record_path.is_file():
        print(
            f"error: no analysis record found for brief_id {brief_id!r} "
            f"(expected at {record_path})",
            file=sys.stderr,
        )
        return None
    return json.loads(record_path.read_text(encoding="utf-8")), record_path


def _brief_validate(brief_id: str) -> int:
    loaded = _load_analysis_record(brief_id)
    if loaded is None:
        return 1
    record, _record_path = loaded

    client = get_client()
    try:
        attribution_report = validate_attribution(record, client=client)
    except AttributionValidatorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        counter_position_report = validate_counter_position(record, client=client)
    except CounterPositionValidatorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # The coverage/confidence validator (§7.9, issue #260) is a pure,
    # model-free check over the record's own `coverage_map`/`confidence`
    # fields -- it never touches `client`, so it cannot itself trip the
    # `explode` provider.
    coverage_report = validate_coverage_and_confidence(record)

    print(f"brief_id: {brief_id}")
    print(format_attribution_report(attribution_report))
    print(format_counter_position_report(counter_position_report))
    print(format_coverage_confidence_report(coverage_report))
    # Prints the record's own persisted coverage_map alongside the gate's
    # verdict (§7.7: "a band is never rendered instead of the counts that
    # justify it") -- the same rendering `_brief_coverage` uses for its
    # freshly-computed map, reused here over the record's AS-PERSISTED one.
    print(format_coverage_map(record.get("coverage_map") or {}))
    # A failure blocks release (§7.9): no answer is emitted on a non-zero
    # exit, and this command never writes to the record either way -- every
    # validator here only ever reports (README.md: "it never edits the
    # record"). All three validators run regardless of each other's outcome
    # so the operator sees the full picture in one pass; the exit code
    # blocks release when ANY fails.
    return (
        0
        if (attribution_report.passed and counter_position_report.passed and coverage_report.passed)
        else 1
    )


def _brief_coverage(brief_id: str) -> int:
    loaded = _load_analysis_record(brief_id)
    if loaded is None:
        return 1
    record, _record_path = loaded

    claims = record.get("claims") or []
    coverage_map = compute_coverage_map(claims)

    print(f"brief_id: {brief_id}")
    print(format_coverage_map(coverage_map))
    return 0


def _brief_usage(pin: str | None) -> int:
    analyses_dir = default_analyses_dir()
    records, unreadable_count = load_analysis_records(analyses_dir)
    report = build_usage_report(records, pin=pin, unreadable_count=unreadable_count)
    print(format_usage_report(report))
    # P0-13: the report gates nothing -- no ratio value drives the exit
    # code, mirroring `chunk examine`'s own inspect-before-spend contract.
    return 0


def _brief_sweep(worklist_path: str, draws: int, sweep_dir: str, workers: int) -> int:
    try:
        summary = run_sweep(worklist_path, draws=draws, sweep_dir=Path(sweep_dir), workers=workers)
    except SweepError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_sweep_summary(summary))
    # Every declared per-(brief, draw) failure is already isolated and
    # recorded (issue #368) -- a sweep that ran to completion with some
    # FAILed draws is still a successful invocation of the loop itself,
    # mirroring `axial run`'s own exit-code rule (`axial.run.run_pass`).
    return 0


def _pin_write(name: str) -> int:
    try:
        path = write_pin(name)
    except CorpusPinError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(str(path)))
    return 0


def _distill_embed() -> int:
    try:
        result = run_embed()
    except EmbedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"chunk_count: {result.chunk_count}")
    print(f"embeddings_dir: {result.embeddings_dir}")
    print(f"manifest_path: {result.manifest_path}")
    return 0


def _distill_readiness_map() -> int:
    try:
        result = run_readiness()
    except ReadinessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"chunk_count: {result.chunk_count}")
    print(f"cluster_count: {result.cluster_count}")
    print(f"noise_count: {result.noise_count}")
    print(f"noise_fraction: {result.noise_fraction}")
    print(f"manifest_path: {result.manifest_path}")
    return 0


def _names_build(min_cluster_size: int | None, min_samples: int | None) -> int:
    kwargs: dict[str, int] = {}
    if min_cluster_size is not None:
        kwargs["min_cluster_size"] = min_cluster_size
    if min_samples is not None:
        kwargs["min_samples"] = min_samples

    try:
        result = run_names(**kwargs)
    except NamesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"entry_count: {result.entry_count}")
    print(f"occurrence_count: {result.occurrence_count}")
    print(f"cluster_count: {result.cluster_count}")
    print(f"noise_count: {result.noise_count}")
    print(f"inventory_path: {result.inventory_path}")
    print(f"embeddings_dir: {result.embeddings_dir}")
    print(f"manifest_path: {result.manifest_path}")
    return 0


def _parse_min_cluster_sizes(raw: str | None) -> list[int]:
    if raw is None:
        return list(DEFAULT_TIGHTNESS_MIN_CLUSTER_SIZES)
    return [int(value.strip()) for value in raw.split(",") if value.strip()]


def _names_examine(min_cluster_sizes: str | None, min_samples: int | None) -> int:
    try:
        stats = examine_names(
            min_cluster_sizes=_parse_min_cluster_sizes(min_cluster_sizes),
            min_samples=min_samples if min_samples is not None else DEFAULT_MIN_SAMPLES,
        )
    except NamesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_encoding_safe(format_names_report(stats))
    return 0


def _names_merge(
    min_cluster_size: int | None, min_samples: int | None, limit: int | None, workers: int
) -> int:
    try:
        result = run_merge_names(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            limit=limit,
            workers=workers,
        )
    except (NamesError, MergeNamesError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for key in (
        "surface_forms",
        "clusters",
        "batches",
        "decided",
        "reused",
        "failed",
        "workers",
        "canonical_names",
        "merged_surface_forms",
        "seeded_surface_forms",
        "complete",
        "alias_map_path",
        "index_path",
        "manifest_path",
    ):
        print(f"{key}: {result[key]}")
    return 0


def _distill_classify(axis: str) -> int:
    try:
        if axis in DISTILL_CLASSIFY_EMBEDDING_AXES:
            result = run_classify_embedding(axis)
        else:
            result = run_classify(axis)
    except (ClassifyError, ClassifyEmbeddingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"axis: {result.axis}")
    print(f"train_chunk_count: {result.train_chunk_count}")
    print(f"dropped_classes: {result.dropped_classes}")
    print(f"gold_chunk_count: {result.gold_chunk_count}")
    print(f"full_coverage_accuracy: {result.full_coverage_accuracy}")
    print(f"teacher_gold_agreement: {result.teacher_gold_agreement}")
    print(f"manifest_path: {result.manifest_path}")
    return 0


def _panel_run(
    records_dir: str, control_record_path: str, reviewers: int, out_path: str | None
) -> int:
    """Run the §9.4 panel over a sample. Offline instrument: nothing in a
    brief run reaches this, and its verdict never lands on an analysis
    record or a gate report."""
    try:
        records = load_records(Path(records_dir))
        control_record = json.loads(Path(control_record_path).read_text(encoding="utf-8"))
    except (GateError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    corpus_pin, _ = resolve_trusted()

    try:
        run = run_panel(
            records,
            control_record,
            client=get_client(),
            corpus_pin=corpus_pin,
            n_reviewers=reviewers,
        )
    except (PanelError, PacketError, VendorError, ControlError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(run.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    _print_encoding_safe(format_panel_run(run))
    # A failed positive control is the one outcome that must not read as a
    # clean run: the panel has a known blind spot, so nothing it said about
    # the sample is trustworthy yet (§9.4 property 6).
    return 0 if run.control.passed else 1


def _gate_run(gate: str, records_dir: str | None, briefs_dir: str | None) -> int:
    try:
        if gate == ADVERSARIAL_GATE_NAME:
            if briefs_dir is None:
                print(f"error: gate {gate!r} requires --briefs <dir>", file=sys.stderr)
                return 1
            records: list[Any] = load_seeded_briefs(Path(briefs_dir))
        else:
            if records_dir is None:
                print(f"error: gate {gate!r} requires --records <dir>", file=sys.stderr)
                return 1
            records = load_records(Path(records_dir))
    except (GateError, AdversarialGateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    corpus_pin, trusted = resolve_trusted()

    client = get_client()
    try:
        report = run_gate(gate, records, client=client, corpus_pin=corpus_pin, trusted=trusted)
    except (
        GateError,
        AttributionValidatorError,
        GroundingGateError,
        CounterPositionValidatorError,
        CalibrationGateError,
        AdversarialGateError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    write_report(report)
    print(format_report(report))
    # `trusted` above is already false unless an unambiguous corpus pin
    # resolves (§9.2, issue #387), regardless of this exit code. A failing
    # metric still exits non-zero so a caller never mistakes a scaffold FAIL
    # for a PASS. `report.passed` is tri-state (issues #401/#402): `None`
    # (not-scoreable) is falsy in Python, so this also exits non-zero for a
    # gate that never fully ran -- the shell's own binary exit code can't
    # carry the third state, but it must never read as the clean 0 a real
    # pass gets. `format_report` above is where the NOT-SCOREABLE text
    # actually distinguishes the two.
    return 0 if report.passed else 1


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

    if args.command == "interrogate":
        return _interrogate(args.source_path, args.domain_dir, args.data_dir, args.limit)

    if args.command == "names" and args.names_command == "build":
        return _names_build(args.min_cluster_size, args.min_samples)

    if args.command == "names" and args.names_command == "examine":
        return _names_examine(args.min_cluster_sizes, args.min_samples)

    if args.command == "names" and args.names_command == "merge":
        return _names_merge(args.min_cluster_size, args.min_samples, args.limit, args.workers)

    if args.command == "artifacts":
        return _artifacts(args.source_path, args.domain)

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

    if args.command == "brief" and args.brief_command == "coverage":
        return _brief_coverage(args.brief_id)

    if args.command == "brief" and args.brief_command == "usage":
        return _brief_usage(args.pin)

    if args.command == "brief" and args.brief_command == "sweep":
        return _brief_sweep(args.worklist_path, args.draws, args.sweep_dir, args.workers)

    if args.command == "pin" and args.pin_command == "write":
        return _pin_write(args.name)

    if args.command == "distill" and args.distill_command == "embed":
        return _distill_embed()

    if args.command == "distill" and args.distill_command == "readiness-map":
        return _distill_readiness_map()

    if args.command == "distill" and args.distill_command == "classify":
        return _distill_classify(args.axis)

    if args.command == "panel" and args.panel_command == "run":
        return _panel_run(args.records, args.control_record, args.reviewers, args.out)

    if args.command == "gate" and args.gate_command == "run":
        return _gate_run(args.gate, args.records, args.briefs)

    if args.command == "reconcile" and args.reconcile_command == "gc":
        return _reconcile_gc(args.apply, args.yes)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
