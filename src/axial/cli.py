"""Command-line entry point for axial."""

import argparse
import getpass
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import axial
from axial.analyze import format_examine_report as format_brief_examine_report
from axial.argmap.ask import AskError, run_map_ask
from axial.argmap.build import MapError
from axial.argmap.build import PASS_NAME as MAP_BUILD_PASS_NAME
from axial.argmap.build import WORKERS as MAP_BUILD_DEFAULT_WORKERS
from axial.argmap.build import run_map_build
from axial.pidguard import AlreadyRunningError
from axial.analyze import run_examine
from axial.analyze.synthesis import SynthesisError
from axial.answer import AnswerError, run_brief
from axial.answer.run_report import format_run_report
from axial.answer.usage_report import build_usage_report, format_usage_report, load_analysis_records
from axial.artifacts import ArtifactsError, run_artifacts
from axial.brief import BriefError, load_brief
from axial.brief.interrogate import InterrogationError, interrogate, persist_interrogation
from axial.brief.smoke import SMOKE_BRIEFS_DIR, format_smoke_summary, run_smoke
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
from axial.drive import DriveSecretsError, _load_drive_secrets, run_drive_ingest, run_drive_sources
from axial.envelope import EnvelopeError, MissingSourceError, compute_source_id, run_envelope
from axial.eval import EvalError, run_eval
from axial.interrogate import InterrogateError, run_interrogate
from axial.eval.corpus_pin import CorpusPinError, write_pin
from axial.extract import ExtractError, extract
from axial.gates import (
    ADVERSARIAL_GATE_NAME,
    COUNTER_POSITION_GATE_NAME,
    PAPER_ATTRIBUTION_FIDELITY_GATE_NAME,
    PAPER_GROUNDING_GATE_NAME,
    PROVENANCE_GATE_NAME,
    AdversarialGateError,
    CalibrationGateError,
    CounterPositionGateError,
    GateError,
    GroundingGateError,
    ProvenanceGateError,
    format_report,
    load_paper_records,
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
    KeyCheckResult,
    LLMError,
    check_key,
    get_client,
    write_api_key,
)
from axial.gather import DEFAULT_WORKERS as GATHER_DEFAULT_WORKERS, GatherError, run_gather
from axial.gather_eval import CALIBRATION_SAMPLE_SIZE, NULL_SAMPLE_SIZE
from axial.gather_eval import DEFAULT_SEED as GATHER_EVAL_DEFAULT_SEED
from axial.gather_eval import (
    GatherEvalError,
    run_gather_eval_score,
    run_gather_eval_sheet,
)
from axial.materialize import MaterializeError, run_materialize
from axial.merge_names import DEFAULT_WORKERS as MERGE_DEFAULT_WORKERS
from axial.merge_names import (
    DEFAULT_DECISIONS_PATH,
    MergeNamesError,
    escalations_to_json,
    format_escalations_report,
    list_escalations,
    run_merge_names,
)
from axial.model_json import ModelJsonError
from axial.names import (
    DEFAULT_INVENTORY_PATH,
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
from axial.panel.coherence_eval import (
    CoherenceEvalError,
    format_coherence_eval_report,
    run_coherence_eval,
)
from axial.panel.sample import SampleSpecError, load_sample_spec
from axial.paper.biblio import BibliographyError
from axial.paper.brief import PaperBriefError, load_paper_brief
from axial.paper.citations import CitationError
from axial.paper.claims import PaperClaimError
from axial.paper.coverage import PaperCoverageError
from axial.paper.draft import DraftError
from axial.paper.examine import format_paper_examine_report, run_paper_examine
from axial.paper.intake import PaperIntakeError
from axial.paper.lens import LensError
from axial.paper.plan import PlanError
from axial.paper.record import PaperRunError, run_paper
from axial.paper.shape import ShapeCheckError
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
from axial.sources import render_report, resolve_backend, scan_local, sync_local
from axial.sources import CHANGED as SOURCES_CHANGED
from axial.sources import NEW as SOURCES_NEW
from axial.sources import PARTIAL as SOURCES_PARTIAL
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
        help="run the artifact-collection pass, emitting one record per artifact node to stdout",
    )
    artifacts_parser.add_argument("source_path", help="path to a .pdf or .docx source file")

    names_parser = subparsers.add_parser(
        "names",
        help=(
            "Phase A v1 slice 04 (issue #415): the name inventory and "
            "similarity view (D10, spec §7.16) -- 'build' collects "
            "every distinct name surface form (names[] only, issue #508) "
            "out of data/answers/, writes the inventory to "
            "data/names/inventory.jsonl, embeds and clusters it, and persists "
            "the result to data/names/embeddings.lance; 'examine' reports the "
            "cluster-size and nearest-neighbour similarity distribution over "
            "that persisted result (zero model/embedding calls); 'merge' is "
            "slice 05 (Reconcile, issue #416) -- the model's own merge calls, "
            "one cluster at a time, into a reversible alias map; 'materialize' "
            "is slice 06 (issue #411) -- writes the vault (prose notes, "
            "artifact notes, name pages) from the alias map, zero model calls. "
            "Unrelated to `axial reconcile gc`, which is model-free orphan GC "
            "(#291)"
        ),
    )
    names_subparsers = names_parser.add_subparsers(dest="names_command")
    names_build_parser = names_subparsers.add_parser(
        "build",
        help=(
            "collect every distinct name surface form from data/answers/ "
            "(names[] only, minus §7.16's cut set), write "
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
            "Phase A v1 slice 05 (issue #416): Reconcile -- cluster the "
            "persisted name vectors at the configured merge tightness "
            "(reusing `axial names build`'s own persisted labels when the "
            "tightness matches, issue #458 -- otherwise a fresh HDBSCAN fit, "
            "--recluster to force one) and let the model decide which "
            "surface forms in each cluster name the same thing (temperature "
            "1, reasoning high, §7.9's `reconcile` "
            "pass), asking a bounded number of clusters at once (--workers). "
            "Writes the reversible alias map to data/names/alias_map.json, the "
            "surviving-name index to data/names/index.json, and whether this "
            "run answered every cluster to data/names/merge_manifest.json; "
            "every decision is logged to data/names/merge_decisions.jsonl, so "
            "a re-run reproduces the same merges (regardless of which worker "
            "finished first) and resumes where it stopped. Also asks about "
            "the pairs clustering never co-located (issue #446: initial vs "
            "full forename, bare surname vs its one full-name candidate, "
            "case/whitespace-only variants) as additional cluster-shaped "
            "batches, deterministically generated, never merged mechanically"
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
    names_merge_parser.add_argument(
        "--recluster",
        action="store_true",
        help=(
            "re-fit HDBSCAN over the persisted name vectors even when this "
            "run's own min_cluster_size/min_samples/pca_components match "
            "data/names/similarity_manifest.json (issue #458): by default a "
            "match reuses the cluster labels `axial names build` already "
            "persisted, since a full-corpus re-fit at the SAME settings costs "
            "10+ minutes for the identical answer"
        ),
    )
    names_merge_parser.add_argument(
        "--confirm-reask",
        action="store_true",
        help=(
            "issue #449's rollout gate: a batch already decided before evidence "
            "was attached looks, by key, exactly like an undecided one -- so "
            "the run refuses to spend on it and names the exact count instead, "
            "unless this flag confirms purging those decisions and re-asking "
            "them with evidence attached"
        ),
    )
    names_merge_parser.add_argument(
        "--decisions-path",
        default=None,
        help=(
            "override data/names/merge_decisions.jsonl -- point a run at a COPY "
            "of the real decision log (e.g. for a --confirm-reask comparison "
            "run) so the real log is never at risk from this invocation "
            "(default: data/names/merge_decisions.jsonl)"
        ),
    )

    names_subparsers.add_parser(
        "materialize",
        help=(
            "Phase A v1 slice 06 (issue #411): Materialize -- write the vault "
            "with zero model calls (D11, spec §7.17). (Re)writes one prose note "
            "per interrogated chunk (interrogation-answer frontmatter, Appendix "
            "H), one artifact note per data/artifacts/ record, and one name "
            "page per data/names/alias_map.json node (name, kind, aliases, and "
            "its member notes as [[chunk_id]] links -- link direction is "
            "name-page -> note only). Re-running against an unchanged alias map "
            "rewrites nothing; a changed one rewrites only the affected name "
            "pages, never a prose note"
        ),
    )

    names_gather_parser = names_subparsers.add_parser(
        "gather",
        help=(
            "Phase A v1 slice 07 (issue #412): Gather -- ask the model what "
            "the authors gathered at each name actually disagree about, from a "
            "packet code assembles per member note (author, year, the "
            "one-sentence claim, whose position it is, who it argues against) "
            "under a hard character budget in code (D12; a name over it is "
            "split into batches and a short final call merges the findings). "
            "Writes the disagreement plus name-to-name links onto each "
            "data/vault/names/ page, and a per-name provenance record to "
            "data/names/disagreements.jsonl, so a re-run reproduces the same "
            "text and resumes where it stopped. Never reads a note's full "
            "text (D13)"
        ),
    )
    names_gather_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "stop after this many names this run, still writing every page a "
            "record already exists for -- a bounded, cheap first look before "
            "committing to a full pass"
        ),
    )
    names_gather_parser.add_argument(
        "--workers",
        type=int,
        default=GATHER_DEFAULT_WORKERS,
        help=(
            "bounded concurrent per-name workers (this pass is I/O-bound, like "
            f"`names merge`) (default: {GATHER_DEFAULT_WORKERS})"
        ),
    )

    names_escalations_parser = names_subparsers.add_parser(
        "escalations",
        help=(
            "issue #461: list every escalated surface form -- the merge "
            "call's third outcome, 'cannot tell' (issue #450) -- with the "
            "co-members it was proposed with and the source book(s) it "
            "appears in, plus a per-kind count. Read-only over "
            "data/names/merge_decisions.jsonl and data/names/inventory.jsonl; "
            "no resolution UI, no queue, no write path"
        ),
    )
    names_escalations_parser.add_argument(
        "--decisions-path",
        default=None,
        help=f"override {DEFAULT_DECISIONS_PATH} (default: that path)",
    )
    names_escalations_parser.add_argument(
        "--inventory-path",
        default=None,
        help=f"override {DEFAULT_INVENTORY_PATH} (default: that path)",
    )
    names_escalations_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="machine-readable JSON array instead of the human-readable report",
    )

    map_parser = subparsers.add_parser(
        "map",
        help=(
            "the argument map (issue #572, PRs 1-2 of 4): 'build' selects "
            "argument-bearing passages out of data/answers/, bags them by "
            "claim similarity (local encoder, zero model calls), extracts "
            "the arguments each bag actually holds (one blind model call per "
            "author-spread slice), merges near-duplicate namings into "
            "positions, then groups positions into neighbourhoods and relates "
            "each neighbourhood in one further blind model call -- writing "
            "data/map/<corpus content hash>/{positions.jsonl,relations.jsonl,"
            "map.json,reads.jsonl,relation_reads.jsonl}"
        ),
    )
    map_subparsers = map_parser.add_subparsers(dest="map_command")
    map_build_parser = map_subparsers.add_parser(
        "build",
        help=(
            "run both stages (positions, then relations) and pin the result "
            "to the corpus's own content hash; each stage is independently "
            "resumable (positions by (bag, slice) via reads.jsonl, relations "
            "by neighbourhood via relation_reads.jsonl), and the command "
            "refuses to start a second copy over the same pin while an "
            "earlier one is still running"
        ),
    )
    map_build_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "re-read everything under the current pin instead of resuming, "
            "for both stages (issue #572 follow-up: the pin is content-only, "
            "so a prompt or model-tier change alone would otherwise resume "
            "under the old prompt's ledger). Moves each stage's own existing "
            "ledger aside to a timestamped sibling rather than deleting it -- "
            "a paid ledger is never destroyed by this flag"
        ),
    )
    map_build_parser.add_argument(
        "--workers",
        type=int,
        default=MAP_BUILD_DEFAULT_WORKERS,
        help=(
            "bounded concurrent extraction workers (this pass is I/O-bound) "
            f"(default: {MAP_BUILD_DEFAULT_WORKERS})"
        ),
    )
    map_ask_parser = map_subparsers.add_parser(
        "ask",
        help=(
            "the door and the landing (issue #572, PR 3 of 4): one model call "
            "states the arguments a brief's case/request are actually about, "
            "then each is matched against the pinned map's own positions by "
            "cosine similarity -- prints the stated arguments and the landed "
            "positions, each with its score, passage count, authors, and text"
        ),
    )
    map_ask_parser.add_argument("brief_path", help="path to a brief YAML file (§7.1)")

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

    eval_parser = subparsers.add_parser(
        "eval",
        help=(
            "score the Academic's returned label_sheet.xlsx under "
            "data/gold/labels/ against the tagger's own chunk records, "
            "writing data/gold/labels/eval_report.json (bare `eval`); or "
            "run the argument-coherence eval track (`eval coherence`, "
            "specs/PHASE-C.md §10.2)"
        ),
    )
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command")

    eval_coherence_parser = eval_subparsers.add_parser(
        "coherence",
        help=(
            "the argument-coherence eval track (offline, sampled, blocks "
            "nothing): reads a committed sample spec (specs/PHASE-C.md "
            "§7.13), runs the sealed-packet panel over its papers, and "
            "reports one coherence figure per stratum -- never a pooled "
            "system-wide mean (§8 P0-10, P0-12, issue #611)"
        ),
    )
    eval_coherence_parser.add_argument(
        "--sample",
        required=True,
        help="path to a committed sample spec JSON file (specs/PHASE-C.md §7.13)",
    )
    eval_coherence_parser.add_argument(
        "--reviewers",
        type=int,
        default=PANEL_MIN_REVIEWERS,
        help=f"how many independent reviewers per packet (default and minimum: {PANEL_MIN_REVIEWERS})",
    )
    eval_coherence_parser.add_argument(
        "--out",
        default=None,
        help="optional path to write the run's JSON report to",
    )

    gather_eval_parser = subparsers.add_parser(
        "gather-eval",
        help=(
            "issue #478: score Gather's disagreement entries "
            "(data/names/disagreements.jsonl) on grounding -- attribution "
            "(is each attributed position actually present in a cited note) "
            "and conflict (do the attributed positions actually oppose each "
            "other) -- calibrated against the founder"
        ),
    )
    gather_eval_subparsers = gather_eval_parser.add_subparsers(dest="gather_eval_command")

    gather_eval_sheet_parser = gather_eval_subparsers.add_parser(
        "sheet",
        help=(
            "emit a real seeded, stratified sample of disagreement entries "
            "across the member-count bands (10-20, 20-50, 50-100, 100-300, "
            "300+) for the founder to mark grounded/not grounded, to "
            "data/gather_eval/label_sheet.xlsx. Each row's full evidence is "
            "written to data/gather_eval/evidence/ -- the sheet's own "
            "evidence cell is a short preview plus a pointer to that file, "
            "since large names' evidence clears Excel's per-cell limit. "
            "Mark it and return the same file, unrenamed, under "
            "data/gather_eval/labels/. Offline -- no LLM call"
        ),
    )
    gather_eval_sheet_parser.add_argument(
        "--sample-size",
        type=int,
        default=CALIBRATION_SAMPLE_SIZE,
        help=f"target calibration sample size (default: {CALIBRATION_SAMPLE_SIZE})",
    )
    gather_eval_sheet_parser.add_argument(
        "--seed",
        type=int,
        default=GATHER_EVAL_DEFAULT_SEED,
        help=f"seed for deterministic, replayable sampling (default: {GATHER_EVAL_DEFAULT_SEED})",
    )

    gather_eval_score_parser = gather_eval_subparsers.add_parser(
        "score",
        help=(
            "judge every disagreement entry not already recorded in "
            "data/names/gather_eval.jsonl, score the founder-marked "
            "calibration sheet under data/gather_eval/labels/ if one has "
            "been returned, and re-ask a seeded sample of null entries "
            "bypassing Gather's own checkpoint to report a flip rate"
        ),
    )
    gather_eval_score_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "stop the main judge loop after this many entries this run -- a "
            "cheap smoke flag, never the sampling mechanism (DEC-53): the "
            "calibration join and the null re-ask always use their own "
            "seeded samples"
        ),
    )
    gather_eval_score_parser.add_argument(
        "--null-sample-size",
        type=int,
        default=NULL_SAMPLE_SIZE,
        help=f"how many null entries to re-ask (default: {NULL_SAMPLE_SIZE})",
    )
    gather_eval_score_parser.add_argument(
        "--seed",
        type=int,
        default=GATHER_EVAL_DEFAULT_SEED,
        help=f"seed for the null re-ask sample (default: {GATHER_EVAL_DEFAULT_SEED})",
    )
    gather_eval_score_parser.add_argument(
        "--workers",
        type=int,
        default=GATHER_DEFAULT_WORKERS,
        help=f"bounded concurrent judge workers (default: {GATHER_DEFAULT_WORKERS})",
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

    sources_parser = subparsers.add_parser(
        "sources",
        help=(
            "what is new, changed, already done, or rejected (with reason) in "
            "the configured source backend -- local folder or Google Drive -- "
            "then ingest whatever is new or changed; see issue #528"
        ),
    )
    sources_parser.add_argument(
        "--backend",
        choices=("local", "drive"),
        default=None,
        help=(
            "override config/pipeline.yaml's sources.backend for this run "
            "(default: read from config, falling back to 'local')"
        ),
    )
    sources_parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "report only, then stop -- no ingest, no pipeline or model call, "
            "no write. Free on the local backend (reads data/run/ledger.tsv "
            "only, no download); on the Drive backend it is NOT free -- it "
            "still downloads each new/changed candidate's bytes to run the "
            "English-only language gate (the only way to know it would be "
            "rejected), it just never hands the download to ingest or writes "
            "the fetch-state manifest"
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
            "chunk_ids (retrieval order) with each note's own claim, a plain "
            "count of assembled notes per name, and the interrogation result "
            "-- makes ZERO stage-4 synthesis calls and writes nothing under "
            "data/analyses/ (specs/PHASE-B.md §5 stage 4, §7.5, §8 P0-9, "
            "issues #255 and #489)"
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
    brief_run_parser.add_argument(
        "--map",
        action="store_true",
        dest="use_map",
        help=(
            "retrieve through the argument map (issue #572) instead of the "
            "name-layer loop: the door states the arguments the brief is "
            "about, lands them on the map's positions, follows every "
            "relation into the corridor, and assembles evidence round-robin "
            "across positions and sources -- opt-in, off by default; "
            "synthesis and everything after it is unchanged"
        ),
    )

    brief_validate_parser = brief_subparsers.add_parser(
        "validate",
        help=(
            "run the stage-5 attribution, counter-position, and "
            "coverage/confidence validators over a persisted analysis record "
            "at data/analyses/<brief_id>.json (specs/PHASE-B.md §7.9, issues "
            "#258/#259/#260) -- exits 0 only when every claim is marked, "
            "every (a)/(b) grounds pointer resolves, a contested brief's "
            "§7.8 counter-position section is present or explicitly "
            "disclosed one-sided, every name the answer is about has a "
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
            "print the §7.7 per-name coverage map (corpus/evidence note "
            "counts and coverage_band) computed from a persisted record's "
            "claims and trajectory -- the inspection affordance for the "
            "coverage_bands config, LLM-free (specs/PHASE-B.md §7.7, "
            "issues #260 and #490)"
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
            "by name query (specs/PHASE-B.md §7.13, §8 P0-13, issues #266/#491) -- "
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

    brief_smoke_parser = brief_subparsers.add_parser(
        "smoke",
        help=(
            "run the five-brief smoke set once each and report pass/fail on "
            "MECHANICAL checks plus a per-brief cost and latency budget "
            "(specs/PHASE-B.md §9.0, §8 P0-11, issue #491) -- a smoke alarm, "
            "not an eval: exits NON-ZERO on any mechanical failure, and scores "
            "no rung-3 gate"
        ),
    )
    brief_smoke_parser.add_argument(
        "--briefs-dir",
        dest="briefs_dir",
        default=None,
        help=f"directory of smoke brief YAML files (default: {SMOKE_BRIEFS_DIR})",
    )
    brief_smoke_parser.add_argument(
        "--sweep-dir",
        dest="sweep_dir",
        default="data/runs/smoke",
        help="root directory for this smoke run's per-brief output (default: data/runs/smoke)",
    )
    brief_smoke_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="bounded concurrent brief workers (default: 1, so latency is uncontended)",
    )
    brief_smoke_parser.add_argument(
        "--map",
        action="store_true",
        dest="use_map",
        help=(
            "run the whole smoke set through the argument-map retrieval "
            "path instead of the name-layer loop (issue #572) -- the "
            "coverage-map check adapts itself to whichever path ran"
        ),
    )

    paper_parser = subparsers.add_parser(
        "paper", help="Phase-C paper authorship operations (specs/PHASE-C.md §7.1, §8 P0-12)"
    )
    paper_subparsers = paper_parser.add_subparsers(dest="paper_command")

    paper_draft_parser = paper_subparsers.add_parser(
        "draft",
        help=(
            "run the paper pipeline end to end -- intake, arc planning, "
            "section-by-section drafting, citation indexing, the "
            "bibliography and rendering -- and persist the paper record "
            "plus the rendered markdown under data/papers/<paper_brief_id> "
            "(specs/PHASE-C.md §5, §7.3, §7.10, §8 P0-12)"
        ),
    )
    paper_draft_parser.add_argument(
        "paper_brief_file",
        help="path to a versioned paper brief YAML file (specs/PHASE-C.md §7.1)",
    )

    paper_examine_parser = paper_subparsers.add_parser(
        "examine",
        help=(
            "run intake and arc planning, and report the resolved lens, "
            "the claim inventory, and each section's assigned claims -- "
            "makes ZERO drafting calls and writes nothing under "
            "data/papers/, analogous to `axial brief examine` "
            "(specs/PHASE-C.md §5 stages 1-2, §8 P0-12)"
        ),
    )
    paper_examine_parser.add_argument(
        "paper_brief_file",
        help="path to a versioned paper brief YAML file (specs/PHASE-C.md §7.1)",
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
            "synthesis-quality, calibration, adversarial, provenance-integrity, "
            "paper-attribution-fidelity, paper-grounding, counter-position) "
            "over a directory of analysis records, (adversarial) seeded briefs, "
            "or (provenance-integrity, paper-attribution-fidelity, paper-grounding, "
            "counter-position) Phase-C paper records, writing evals/reports/<gate>.json"
        ),
    )
    gate_run_parser.add_argument(
        "gate",
        help=(
            "which gate to run: attribution-fidelity, grounding, "
            "synthesis-quality, calibration, adversarial, provenance-integrity, "
            "paper-attribution-fidelity, paper-grounding, or counter-position "
            "(specs/PHASE-C.md §10.1)"
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
        help=(
            "directory of analysis-record JSON files to score (attribution-fidelity, "
            "grounding, synthesis-quality, calibration), or of Phase-C paper-record "
            "JSON files (provenance-integrity, paper-attribution-fidelity, "
            "paper-grounding, counter-position)"
        ),
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

    key_parser = subparsers.add_parser("key", help="manage the OpenRouter API key (issue #527)")
    key_subparsers = key_parser.add_subparsers(dest="key_command")

    key_subparsers.add_parser(
        "set",
        help=(
            "prompt for the OpenRouter API key (never read from the command "
            "line) and write it to the resolved secrets file"
        ),
    )
    key_subparsers.add_parser(
        "check",
        help=(
            "spend one cheap call to prove the configured key works, and "
            "report which model tiers secrets.toml configures"
        ),
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


def _artifacts(source_path: str) -> int:
    try:
        records = run_artifacts(source_path)
    except ArtifactsError as exc:
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


def _gather_eval_sheet(sample_size: int, seed: int) -> int:
    try:
        path = run_gather_eval_sheet(sample_size=sample_size, seed=seed)
    except GatherEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(str(path)))
    return 0


def _gather_eval_score(
    *,
    limit: int | None,
    null_sample_size: int,
    seed: int,
    workers: int,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    with run_context("gather-eval-score", root=root, clock=clock) as run:
        start = time.monotonic()
        try:
            result = run_gather_eval_score(
                limit=limit, null_sample_size=null_sample_size, seed=seed, workers=workers
            )
        except (GatherEvalError, LLMError) as exc:
            run.record(
                source_id="",
                pass_name="gather_eval",
                model=None,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id="",
            pass_name="gather_eval",
            model=None,
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )

    print(json.dumps(result, indent=2, sort_keys=True))
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


def _sources(backend_override: str | None, check: bool) -> int:
    """`axial sources` (issue #528): the operator's everyday "what's new,
    then ingest it" command, for whichever backend `config/pipeline.yaml`'s
    `sources.backend` names (or `--backend`, for a one-off override) --
    `axial.sources.resolve_backend` falls back to 'local' when unset.
    `check=True` (`--check`) stops after the report -- no ingest -- see
    `_sources_local`/`_sources_drive` for each backend's own cost."""
    backend = backend_override or resolve_backend()
    if backend == "local":
        return _sources_local(check)
    if backend == "drive":
        return _sources_drive(check)
    print(
        f"error: unknown sources backend {backend!r} (expected 'local' or 'drive')",
        file=sys.stderr,
    )
    return 1


def _sources_local(check: bool) -> int:
    """The local folder backend: report first (free -- no LLM call, no
    download, just a handful of artifact-file checks plus a ledger read,
    never a parse -- see `axial.sources.scan_local`), then ingest whatever
    the report shows as new, changed, or partial (a partial source is
    exactly what `sync_local`'s resumable pass chain is for: finishing a
    run that died halfway, not restarting it). A report with nothing new,
    changed, or partial says so and runs no pipeline pass at all.

    `check=True` returns right after printing the report: `sync_local` (the
    only path that reaches `axial.run.run_pass`) is never called, so a
    checked run is provably zero pipeline calls, zero model calls, zero
    writes -- this is the founder's standing "don't touch the 31 already-
    ingested sources" guard made safe to run on the real corpus."""
    records = scan_local()
    print(render_report(records))

    if check:
        return 0

    pending = [
        record
        for record in records
        if record.status in (SOURCES_NEW, SOURCES_CHANGED, SOURCES_PARTIAL)
    ]
    if not pending:
        print("sources: nothing new (0 to ingest)")
        return 0

    client = get_client()
    sync_local(client=client)
    return 0


def _sources_drive(check: bool) -> int:
    """The Drive backend: resolves `folder_id` from `[drive]` secrets
    exactly like `axial drive ingest`, then reports and ingests in the one
    pass `run_drive_sources` already performs (see its docstring for why
    Drive's report and its ingest cannot be split into two cheap steps the
    way the local backend's can).

    `check=True` is NOT free here, unlike the local backend: a new/changed
    candidate's bytes still get downloaded to run the language gate, since
    that is the only way to know whether it would be rejected. What it
    never does is call `ingest_fn` or write the fetch-state manifest --
    `run_drive_sources`'s own docstring has the full contract."""
    try:
        secrets = _load_drive_secrets(DRIVE_SECRETS_PATH)
    except DriveSecretsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    records, exit_code = run_drive_sources(secrets["books_folder_id"], check=check)
    print(render_report(records))
    return exit_code


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

    # Emitted as one encoding-safe block: the premise, bound and refusal lines
    # are model prose that echoes the brief's own names, so a diacritic in one
    # would kill the command on a narrow stdout codec after the interrogation
    # call was already paid for. Byte-for-byte the same report as the per-line
    # prints it replaces.
    lines = [f"brief_id: {brief.brief_id}", f"disposition: {result.disposition}"]
    for premise in result.premises_found:
        lines.append(f"  premise ({premise.assessment}): {premise.premise}")
    for bound in result.bounds_applied:
        lines.append(f"  bound: {bound}")
    if result.refusal is not None:
        lines.append(f"refusal: {result.refusal['reason']}")
    lines.append(f"persisted: {path}")
    _print_encoding_safe("\n".join(lines))
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

    # `_print_encoding_safe`, never a bare `print` (issue #489): the report
    # now carries corpus prose -- each note's own `claim` -- and a real
    # `brief examine` run against the live corpus crashed with
    # `UnicodeEncodeError` on a transliterated Arabic ayn (U+02BF) once stdout
    # was redirected and picked up Windows' cp1252, after every retrieval call
    # had already been paid for. Same class as `chunk examine` (#153 fix) and
    # `names examine`; same one-line remedy.
    _print_encoding_safe(format_brief_examine_report(brief, result))
    # P0-9 inspect-before-spend: examine makes no stage-4 synthesis call, so
    # a `refuse` disposition -- like every other disposition -- is a
    # completed run, exit 0 (mirrors `_brief_interrogate`'s own §7.2 rule).
    return 0


def _print_event(message: str, _detail: dict[str, Any]) -> None:
    """The CLI's live renderer for the engine's event seam (issue #533):
    prints exactly the plain sentence the engine composed, live, while the
    run goes -- "the plain-language view is the only view" (no tool names,
    ids or argument shapes in `message` at all, by the seam's own contract)
    -- and never the `detail` dict, which exists for a future renderer
    (e.g. an activity log) to pick from instead."""
    print(message, file=sys.stderr)


def _brief_run(brief_path: str, *, use_map: bool = False) -> int:
    try:
        brief = load_brief(brief_path)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = get_client()
    try:
        # `case_id` is the brief file's own stem: that is the join
        # `evals/cases/sim/` uses (§9.3), and a brief with no case file of
        # that name simply has no mechanical retrieval-hit oracle.
        result = run_brief(
            brief,
            client=client,
            case_id=Path(brief_path).stem,
            use_map=use_map,
            on_event=_print_event,
        )
    except (
        InterrogationError,
        QueryError,
        SynthesisError,
        CorpusPinError,
        AnswerError,
        AskError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"retrieval: {'argument map' if use_map else 'name layer'}")
    print(f"brief_id: {brief.brief_id}")
    print(f"disposition: {result.record['interrogation']['disposition']}")
    print(f"persisted: {result.path}")
    print(f"answer: {result.markdown_path}")
    print(f"run report: {result.report_path}")
    # §7.14: nothing renders `cost` in the markdown answer -- "a human-readable
    # cost report is the run report's job". Encoding-safe because the report
    # names the passes and the counts, and a coverage band travels with names
    # the live index holds (`Uğur Ümit Üngör`).
    _print_encoding_safe(format_run_report(result.report))
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

    # One encoding-safe block, byte-identical to the per-line prints it
    # replaces. Every part of it can carry non-cp1252 text: a counter-position
    # stance and one_sided_reason are model prose, and the coverage map is
    # keyed by the names the answer is about -- the live index holds
    # `Uğur Ümit Üngör`. The last part is the record's own persisted
    # coverage_map alongside the gate's verdict (§7.7: "a band is never
    # rendered instead of the counts that justify it") -- the same rendering
    # `_brief_coverage` uses for its freshly-computed map, reused here over
    # the record's AS-PERSISTED one.
    _print_encoding_safe(
        "\n".join(
            [
                f"brief_id: {brief_id}",
                format_attribution_report(attribution_report),
                format_counter_position_report(counter_position_report),
                format_coverage_confidence_report(coverage_report),
                format_coverage_map(record.get("coverage_map") or {}),
            ]
        )
    )
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
    coverage_map = compute_coverage_map(claims, trajectory=record.get("trajectory") or [])

    # Encoding-safe for the same reason as `brief validate`'s copy: the map is
    # keyed by the names a claim touches.
    _print_encoding_safe("\n".join([f"brief_id: {brief_id}", format_coverage_map(coverage_map)]))
    return 0


def _brief_usage(pin: str | None) -> int:
    analyses_dir = default_analyses_dir()
    records, unreadable_count = load_analysis_records(analyses_dir)
    report = build_usage_report(records, pin=pin, unreadable_count=unreadable_count)
    # Encoding-safe: the per-filter rows are labelled with the tool args a run
    # actually queried, which under the name tool set are canonical names.
    _print_encoding_safe(format_usage_report(report))
    # P0-13: the report gates nothing -- no ratio value drives the exit
    # code, mirroring `chunk examine`'s own inspect-before-spend contract.
    return 0


def _brief_sweep(worklist_path: str, draws: int, sweep_dir: str, workers: int) -> int:
    try:
        summary = run_sweep(worklist_path, draws=draws, sweep_dir=Path(sweep_dir), workers=workers)
    except SweepError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Encoding-safe: a draw's failure reason quotes the underlying error, which
    # can carry model or corpus text.
    _print_encoding_safe(format_sweep_summary(summary))
    # Every declared per-(brief, draw) failure is already isolated and
    # recorded (issue #368) -- a sweep that ran to completion with some
    # FAILed draws is still a successful invocation of the loop itself,
    # mirroring `axial run`'s own exit-code rule (`axial.run.run_pass`).
    return 0


def _brief_smoke(
    briefs_dir: str | None, sweep_dir: str, workers: int, *, use_map: bool = False
) -> int:
    try:
        summary = run_smoke(
            sweep_dir=Path(sweep_dir),
            briefs_dir=Path(briefs_dir) if briefs_dir is not None else None,
            workers=workers,
            use_map=use_map,
        )
    except SweepError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Encoding-safe: the names a run queried are canonical names, and the
    # live index holds `Uğur Ümit Üngör`.
    _print_encoding_safe(format_smoke_summary(summary))
    # DELIBERATELY the opposite of `_brief_sweep` above, which returns 0 even
    # with FAILed draws (issue #368, mirroring `axial run`'s loop rule).
    # Smoke is a GATE, not a loop: it exists to make a regression loud the
    # day it lands, so any mechanical failure exits non-zero. This is not a
    # copied bug.
    return 0 if summary.passed else 1


# Every failure `axial.paper`'s five stages can raise before a record is
# persisted: the brief loader's own family, the three §7.1 intake rejections,
# lens resolution, arc planning, drafting, the shape check's own self-grading
# guard and parse failures (§7.16, issue #578 -- these ARE blocking: the
# check's BAND never blocks, but a misconfigured judge or a malformed
# response is a genuine pipeline failure like any other), claim assembly
# (the §7.4 confidence ceiling and the single-record-inference check),
# citation indexing (§7.5), the bibliography (§7.6), and
# `LLMError`/`ModelJsonError` from the model seam itself (`complete_json`
# never catches either -- see its own docstring). `PaperRunError` is
# `run_paper`'s own base class, held open for a future whole-pipeline failure
# though nothing raises it yet. Caught together so every rejection reports as
# a named, non-zero failure -- never a traceback -- exactly like
# `_brief_run`'s own tuple one layer down.
_PAPER_PIPELINE_ERRORS = (
    PaperIntakeError,
    LensError,
    PlanError,
    DraftError,
    ShapeCheckError,
    PaperClaimError,
    CitationError,
    PaperCoverageError,
    BibliographyError,
    PaperRunError,
    LLMError,
    ModelJsonError,
)


def _paper_draft(paper_brief_file: str) -> int:
    try:
        paper_brief = load_paper_brief(paper_brief_file)
    except PaperBriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = get_client()
    try:
        record = run_paper(client, paper_brief)
    except _PAPER_PIPELINE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    markdown_path = Path(record["paper_markdown_path"])
    record_path = markdown_path.with_suffix(".json")
    shape = record.get("shape") or {}
    print(f"paper_brief_id: {paper_brief.paper_brief_id}")
    print(f"corpus_pin: {record['corpus_pin']}")
    print(f"lens: {record['lens']}")
    print(f"sections: {len(record['plan']['sections'])}")
    print(f"claims cited: {len(record['claims'])}")
    print(f"confidence: {record['confidence']['overall_band']}")
    print(f"shape: {shape.get('band')}")
    print(f"persisted: {record_path}")
    print(f"paper: {markdown_path}")

    # The shape check reports; it never blocks the record or the rendered
    # paper from being written (§3 non-goal 9, §7.16). It DOES make a `weak`
    # run exit non-zero and say so loudly -- the operator reads the named
    # defects and decides whether to re-run; there is no re-draft loop.
    if shape.get("band") == "weak":
        defects = shape.get("defects") or []
        print(
            f"shape check: WEAK -- {len(defects)} defect(s) named; the paper was still "
            "written to disk, but its own shape check flagged it. Review the defects on "
            f"{record_path} before treating this draft as done.",
            file=sys.stderr,
        )
        return 1
    return 0


def _paper_examine(paper_brief_file: str) -> int:
    try:
        paper_brief = load_paper_brief(paper_brief_file)
    except PaperBriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = get_client()
    try:
        result = run_paper_examine(client, paper_brief)
    except (PaperIntakeError, LensError, PlanError, LLMError, ModelJsonError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # `_print_encoding_safe`: the report carries corpus prose -- each
    # inventory claim's own `text` -- exactly the class of report that broke
    # `axial brief examine` on a transliterated diacritic once stdout picked
    # up a narrow codec (issue #489), after the retrieval/planning call had
    # already been paid for.
    _print_encoding_safe(format_paper_examine_report(paper_brief, result))
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
    min_cluster_size: int | None,
    min_samples: int | None,
    limit: int | None,
    workers: int,
    confirm_reask: bool,
    decisions_path: str | None,
    recluster: bool,
) -> int:
    try:
        result = run_merge_names(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            limit=limit,
            workers=workers,
            confirm_reask=confirm_reask,
            decisions_path=Path(decisions_path) if decisions_path else None,
            recluster=recluster,
        )
    except (NamesError, MergeNamesError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for key in (
        "surface_forms",
        "fold_groups",
        "clusters",
        "batches",
        "candidate_batches",
        "decided",
        "reused",
        "failed",
        "workers",
        "evidence_tier",
        "stale_evidence_tier_reasked",
        "escalated_surfaces",
        "canonical_names",
        "merged_surface_forms",
        "seeded_surface_forms",
        "complete",
        "alias_map_path",
        "index_path",
        "manifest_path",
        "failures_path",
    ):
        print(f"{key}: {result[key]}")
    return 0


def _names_materialize() -> int:
    try:
        result = run_materialize()
    except MaterializeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for key in (
        "vault_dir",
        "sources",
        "notes_written",
        "notes_skipped_no_answer",
        "artifact_sources",
        "artifact_notes_written",
        "name_pages",
        "name_pages_written",
        "name_pages_unchanged",
        "name_pages_deleted",
    ):
        print(f"{key}: {result[key]}")
    return 0


def _names_gather(limit: int | None, workers: int) -> int:
    try:
        result = run_gather(limit=limit, workers=workers)
    except (MaterializeError, GatherError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for key in (
        "names",
        "names_skipped_single_member",
        "names_skipped_below_min_members",
        "min_gather_members",
        "names_gathered",
        "asked",
        "reused",
        "failed",
        "batch_calls",
        "merge_calls",
        "pages_written",
        "workers",
        "vault_dir",
        "disagreements_path",
    ):
        print(f"{key}: {result[key]}")
    return 0


def _names_escalations(
    decisions_path: str | None, inventory_path: str | None, as_json: bool
) -> int:
    kwargs: dict[str, Path] = {}
    if decisions_path:
        kwargs["decisions_path"] = Path(decisions_path)
    if inventory_path:
        kwargs["inventory_path"] = Path(inventory_path)
    entries = list_escalations(**kwargs)

    if as_json:
        # Surfaces are transliterated Arabic/Turkish scholarship -- non-Latin-1
        # characters are the normal case, not an edge case. `ensure_ascii=False`
        # keeps them readable, but that hands stdout characters a Windows
        # cp1252 console/redirect can't encode; route through the same
        # encoding-safe emission path as the text listing.
        _print_encoding_safe(json.dumps(escalations_to_json(entries), indent=2, ensure_ascii=False))
    else:
        _print_encoding_safe(format_escalations_report(entries))
    return 0


def _format_map_build_summary(manifest: dict[str, Any]) -> str:
    """The real narrative `_map_build` overwrites `run_context`'s summary.md
    stub with (issue #572: "a 27-minute paid pass ... cost recorded") --
    every other pass leaves that file an operator-authored stub, but this
    one's own cost is exactly the thing a founder needs on disk without
    re-deriving it from `map.json`."""
    counts = manifest["counts"]
    lines = [
        "# Run: map-build",
        "",
        f"corpus pin: {manifest['corpus_pin']}",
        f"model: {manifest['model']} (reasoning={manifest['reasoning']})",
        f"cost: ${manifest['cost_usd']:.4f}"
        if manifest["cost_usd"] is not None
        else "cost: unpriced",
        f"wall time: {manifest['wall_time_sec']:.1f}s",
        "",
        "## counts",
        "",
    ]
    for key, value in counts.items():
        lines.append(f"- {key}: {value}")

    relations = manifest.get("relations")
    if relations is not None:
        lines += [
            "",
            "## relations",
            "",
            f"model: {relations['model']} (reasoning={relations['reasoning']})",
            f"cost: ${relations['cost_usd']:.4f}"
            if relations["cost_usd"] is not None
            else "cost: unpriced",
            "",
        ]
        for key, value in relations["counts"].items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def _map_build(
    *,
    workers: int = MAP_BUILD_DEFAULT_WORKERS,
    force: bool = False,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    """`axial map build` (issue #572, PRs 1-2 of 4): wrapped in a run-logging
    context like every other pass -- one `run.jsonl` record for the whole
    build (both stages), `console.log` teed with real-time per-read
    progress, and (uniquely to this pass, see `_format_map_build_summary`) a
    real `summary.md` carrying the measured cost, not just the header
    stub."""
    with run_context("map-build", root=root, clock=clock) as run:
        start = time.monotonic()
        try:
            client = get_client()
        except LLMError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        def _tee(message: str) -> None:
            print(message, flush=True)
            run.logger.info(message)

        try:
            manifest = run_map_build(client=client, log=_tee, workers=workers, force=force)
        except (MapError, AlreadyRunningError, LLMError, CorpusPinError) as exc:
            run.record(
                source_id="",
                pass_name=MAP_BUILD_PASS_NAME,
                model=None,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id=manifest["corpus_pin"],
            pass_name=MAP_BUILD_PASS_NAME,
            model=manifest["model"],
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )
        summary_path = run.run_dir / "summary.md"

    summary_path.write_text(_format_map_build_summary(manifest), encoding="utf-8")
    for key in ("corpus_pin", "model", "reasoning", "cost_usd", "wall_time_sec"):
        print(f"{key}: {manifest[key]}")
    for key, value in manifest["counts"].items():
        print(f"{key}: {value}")
    relations = manifest.get("relations")
    if relations is not None:
        print(f"relations model: {relations['model']} (reasoning={relations['reasoning']})")
        print(f"relations cost_usd: {relations['cost_usd']}")
        for key, value in relations["counts"].items():
            print(f"relations {key}: {value}")
    return 0


def _map_ask(brief_path: str) -> int:
    """`axial map ask <brief.yaml>` (issue #572, PR 3 of 4): a thin wrapper
    over `run_map_ask` -- every error class it can raise (a malformed brief,
    no map built at this pin, a mismatched encoder, an unusable door
    response) is a plain, non-zero-exit failure, never a traceback."""
    try:
        result = run_map_ask(brief_path)
    except (BriefError, AskError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    lines = [
        f"brief_id: {result.brief.brief_id}",
        "",
        f"THE QUESTION AS ARGUMENTS ({len(result.asks)}):",
    ]
    for ask in result.asks:
        lines.append(f"  - {ask}")
    lines.append("")
    lines.append(f"LANDED ON {len(result.landed)} POSITION(S):")
    for position in result.landed:
        lines.append(
            f"  [{position.score:.2f}] {position.size:3d} passage(s), "
            f"{'+'.join(position.authors)}: {position.argument}"
        )
    _print_encoding_safe("\n".join(lines))
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


def _eval_coherence(sample_path: str, *, reviewers: int, out_path: str | None) -> int:
    """The §10.2 coherence eval track: a committed sample spec in, a per-
    stratum report out. Offline instrument, same as `_panel_run` below:
    nothing in a paper run reaches this, and no gate reads its output.

    Ships unrun by design (issue #611 PR body): a coherence sample must
    span more than one performance tier and more than one model
    combination (§7.13), and the corpus does not yet hold enough papers to
    build one. The frame carries its own `corpus_pin` (§7.13), read from
    the sample spec itself rather than the runtime `resolve_trusted()` seam
    the per-run gates use -- a committed sample is pinned to whichever
    corpus its named papers were drafted against, not to whatever pin is
    live in the working tree today."""
    try:
        spec = load_sample_spec(Path(sample_path))
    except SampleSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        report = run_coherence_eval(spec, client=get_client(), n_reviewers=reviewers)
    except (CoherenceEvalError, PanelError, PacketError, VendorError, ControlError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(report.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    _print_encoding_safe(format_coherence_eval_report(report))
    # Mirrors `_panel_run`'s own exit-code convention: a failed positive
    # control must not read as a clean run (§7.9) -- this run's own numbers
    # are not trustworthy yet, whatever they say.
    return 0 if report.trusted else 1


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
        elif gate == PROVENANCE_GATE_NAME:
            if records_dir is None:
                print(f"error: gate {gate!r} requires --records <dir>", file=sys.stderr)
                return 1
            records = load_paper_records(Path(records_dir))
        elif gate == PAPER_ATTRIBUTION_FIDELITY_GATE_NAME:
            if records_dir is None:
                print(f"error: gate {gate!r} requires --records <dir>", file=sys.stderr)
                return 1
            records = load_paper_records(Path(records_dir))
        elif gate == COUNTER_POSITION_GATE_NAME:
            if records_dir is None:
                print(f"error: gate {gate!r} requires --records <dir>", file=sys.stderr)
                return 1
            records = load_paper_records(Path(records_dir))
        elif gate == PAPER_GROUNDING_GATE_NAME:
            if records_dir is None:
                print(f"error: gate {gate!r} requires --records <dir>", file=sys.stderr)
                return 1
            records = load_paper_records(Path(records_dir))
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
        ProvenanceGateError,
        CounterPositionGateError,
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


def _key_set() -> int:
    """`axial key set` (issue #527): prompt for the key via `getpass` --
    never `sys.argv`, so it never lands in shell history -- and write it to
    the resolved secrets file. The key itself is never printed here; only
    the path it landed at is."""
    try:
        key = getpass.getpass("OpenRouter API key: ")
    except (EOFError, KeyboardInterrupt):
        print("error: no key entered", file=sys.stderr)
        return 1
    try:
        path = write_api_key(key)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"key written to {path}")
    return 0


def _format_key_check(result: KeyCheckResult) -> str:
    lines = ["key: valid"]
    lines.append(
        "reachable tiers: "
        + (", ".join(result.reachable_tiers) if result.reachable_tiers else "(none configured)")
    )
    if result.unreachable_tiers:
        lines.append("unconfigured tiers:")
        for tier in sorted(result.unreachable_tiers):
            lines.append(f"  {tier}: {result.unreachable_tiers[tier]}")
    return "\n".join(lines)


def _key_check() -> int:
    """`axial key check` (issue #527): one cheap completion call proves the
    configured key authenticates; the tier report that follows costs no
    further network call (`check_key`'s own docstring)."""
    result = check_key()
    if not result.valid:
        print(f"error: {result.error}", file=sys.stderr)
        return 1
    print(_format_key_check(result))
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
        return _names_merge(
            args.min_cluster_size,
            args.min_samples,
            args.limit,
            args.workers,
            args.confirm_reask,
            args.decisions_path,
            args.recluster,
        )

    if args.command == "names" and args.names_command == "materialize":
        return _names_materialize()

    if args.command == "names" and args.names_command == "gather":
        return _names_gather(args.limit, args.workers)

    if args.command == "names" and args.names_command == "escalations":
        return _names_escalations(args.decisions_path, args.inventory_path, args.as_json)

    if args.command == "map" and args.map_command == "build":
        return _map_build(workers=args.workers, force=args.force)

    if args.command == "map" and args.map_command == "ask":
        return _map_ask(args.brief_path)

    if args.command == "artifacts":
        return _artifacts(args.source_path)

    if args.command == "gold" and args.gold_command == "sample":
        return _gold_sample(args.min_size, args.max_size, args.seed)

    if args.command == "gold" and args.gold_command == "sheet":
        return _gold_sheet()

    if args.command == "gold" and args.gold_command == "deliver":
        return _gold_deliver()

    if args.command == "gather-eval" and args.gather_eval_command == "sheet":
        return _gather_eval_sheet(sample_size=args.sample_size, seed=args.seed)

    if args.command == "gather-eval" and args.gather_eval_command == "score":
        return _gather_eval_score(
            limit=args.limit,
            null_sample_size=args.null_sample_size,
            seed=args.seed,
            workers=args.workers,
        )

    if args.command == "eval" and not getattr(args, "eval_command", None):
        return _eval()

    if args.command == "eval" and args.eval_command == "coherence":
        return _eval_coherence(args.sample, reviewers=args.reviewers, out_path=args.out)

    if args.command == "vault" and args.vault_command == "write":
        return _vault_write(args.source_path)

    if args.command == "polity" and args.polity_command == "build":
        return _polity_build()

    if args.command == "polity" and args.polity_command == "report":
        return _polity_report()

    if args.command == "drive" and args.drive_command == "ingest":
        return _drive_ingest(args.folder_id)

    if args.command == "sources":
        return _sources(args.backend, args.check)

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
        return _brief_run(args.brief_path, use_map=args.use_map)

    if args.command == "brief" and args.brief_command == "validate":
        return _brief_validate(args.brief_id)

    if args.command == "brief" and args.brief_command == "coverage":
        return _brief_coverage(args.brief_id)

    if args.command == "brief" and args.brief_command == "usage":
        return _brief_usage(args.pin)

    if args.command == "brief" and args.brief_command == "sweep":
        return _brief_sweep(args.worklist_path, args.draws, args.sweep_dir, args.workers)

    if args.command == "brief" and args.brief_command == "smoke":
        return _brief_smoke(args.briefs_dir, args.sweep_dir, args.workers, use_map=args.use_map)

    if args.command == "paper" and args.paper_command == "draft":
        return _paper_draft(args.paper_brief_file)

    if args.command == "paper" and args.paper_command == "examine":
        return _paper_examine(args.paper_brief_file)

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

    if args.command == "key" and args.key_command == "set":
        return _key_set()

    if args.command == "key" and args.key_command == "check":
        return _key_check()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
