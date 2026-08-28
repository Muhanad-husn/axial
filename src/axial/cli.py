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
from axial.argmap.vocabulary_join import (
    DEFAULT_VOCABULARY_COLUMN,
    PER_CATEGORY_CAP,
    NoVocabularyError,
)
from axial.argmap.build import MapError
from axial.argmap.build import PASS_NAME as MAP_BUILD_PASS_NAME
from axial.argmap.build import WORKERS as MAP_BUILD_DEFAULT_WORKERS
from axial.argmap.build import run_map_build
from axial.argmap.residue import WORKERS as MAP_RESIDUE_DEFAULT_WORKERS
from axial.argmap.residue import run_residue_pass
from axial.pidguard import AlreadyRunningError
from axial.analyze import run_examine
from axial.analyze.synthesis import SynthesisError
from axial.answer import KNOWN_ARMS, MAP_ARM, MAP_VOCAB_ARM, NAME_ARM, AnswerError, run_brief
from axial.answer.render import render_analyst_answer
from axial.answer.run_report import format_run_report
from axial.answer.usage_report import build_usage_report, format_usage_report, load_analysis_records
from axial.artifacts import ArtifactsError, run_artifacts
from axial.ask import AskError as AskSessionError
from axial.ask import Turn as AskTurn
from axial.ask import ask as ask_question
from axial.ask import new_session_id as new_ask_session_id
from axial.ask.history import PastTurn, list_past_turns, load_turn
from axial.ask.paper import PAPER_PIPELINE_ERRORS, draft_paper_for_turn
from axial.ask.role import ANALYST, InvalidRoleError, current_role
from axial.brief import BriefError, load_brief
from axial.brief.fork import ForkAnswer, ForkCheckError, ForkCheckResult
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
from axial.drive import DEFAULT_SECRETS_PATH as DRIVE_SECRETS_PATH
from axial.drive import DriveSecretsError, _load_drive_secrets, run_drive_ingest, run_drive_sources
from axial.envelope import EnvelopeError, MissingSourceError, compute_source_id, run_envelope
from axial.interrogate import DEFAULT_WORKERS as INTERROGATE_DEFAULT_WORKERS
from axial.interrogate import InterrogateError, run_interrogate
from axial.position_backfill import POSITION_BACKFILL_PASS_NAME, run_position_backfill
from axial.eval.corpus_pin import CorpusPinError, write_pin
from axial.eval.layers import LayerComparisonError, compare_arms, format_layer_comparison
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
from axial.paper.brief import (
    PaperBriefError,
    load_paper_brief,
)
from axial.paper.examine import format_paper_examine_report, run_paper_examine
from axial.paper.intake import PaperIntakeError
from axial.paper.lens import LensError
from axial.paper.plan import PlanError
from axial.paper.record import run_paper
from axial.paths import DEFAULT_DOMAIN_DIR, default_analyses_dir
from axial.pipeline_ready import PipelineReadyError, run_pipeline_ready
from axial.polity_canonical import PolityCanonicalError, run_polity_build, run_polity_report
from axial.query.reader import QueryError
from axial.reconcile import ReconcileError, format_gc_report, run_gc
from axial.run import (
    PASS_REGISTRY,
    run_pass,
)
from axial.runlog import RunNotFoundError, follow_run, list_runs, load_run, run_context
from axial.schema import SchemaError, load_schema
from axial.sources import (
    render_report,
    resolve_backend,
    scan_local,
    scan_orphaned_envelopes,
    sync_local,
)
from axial.sources import CHANGED as SOURCES_CHANGED
from axial.sources import NEW as SOURCES_NEW
from axial.sources import PARTIAL as SOURCES_PARTIAL
from axial.status import (
    compute_status,
    render_follow_line,
    render_run_list,
    render_run_view,
    render_status,
    resolve_run_dir,
)
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
from axial.vocabulary import (
    DEFAULT_ASSIGN_N,
    DEFAULT_ASSIGN_WORKERS,
    DEFAULT_PROPOSE_N,
    DEFAULT_VOCABULARY_SCHEME_PATH,
    VOCABULARY_COLUMNS,
    SchemeVersionMismatchError,
    SelfConsistencyError,
    VocabularySchemeError,
    build_vocabulary,
    examine_vocabulary,
    format_vocabulary_build_report,
    format_vocabulary_report,
)


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
        "--workers",
        type=int,
        default=INTERROGATE_DEFAULT_WORKERS,
        help=(
            "bounded concurrent per-note workers (this pass waits on the "
            f"model, it does not compute) (default: {INTERROGATE_DEFAULT_WORKERS})"
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

    position_backfill_parser = subparsers.add_parser(
        "position-backfill",
        help=(
            "backfill the `position` field onto every note of a source that "
            "was interrogated under frame 0.1 and lacks it (issue #697): one "
            "question, keeping the frame's examples and showing the note its "
            "own recorded position_of, patching <data>/answers/<source_id>"
            ".jsonl in place -- a note that already carries the key is never "
            "re-asked, so a rerun resumes for free"
        ),
    )
    position_backfill_parser.add_argument("source_path", help="path to a .pdf or .docx source file")
    position_backfill_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many notes are backfilled this run -- a smoke arm before the corpus",
    )
    position_backfill_parser.add_argument(
        "--workers",
        type=int,
        default=INTERROGATE_DEFAULT_WORKERS,
        help=(
            "bounded concurrent per-note workers (default: "
            f"{INTERROGATE_DEFAULT_WORKERS}, mirrors `interrogate`'s own)"
        ),
    )
    position_backfill_parser.add_argument(
        "--data-dir",
        dest="data_dir",
        default=None,
        help=(
            "rebase the four directories this pass touches (chunks/, "
            "envelopes/, source_meta/, answers/) onto this parent (default: "
            "each resolved from config/pipeline.yaml)"
        ),
    )
    position_backfill_parser.add_argument(
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
    names_build_parser.add_argument(
        "--recluster",
        action="store_true",
        help=(
            "force a full HDBSCAN re-fit over every surface form and refresh "
            "the persisted fit (issue #677); by default, when a persisted fit "
            "exists at these same model/dials/library versions, a surface form "
            "already in the previous build keeps its cluster label unchanged "
            "and only new surface forms are assigned into that fit -- a full "
            "re-fit reshuffles which cluster everything sits in, which is what "
            "made adding a handful of books re-ask the whole corpus's already-"
            "decided merges (#623)"
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

    names_materialize_parser = names_subparsers.add_parser(
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
    names_materialize_parser.add_argument(
        "--residue-decisions-path",
        default=None,
        help=(
            "issue #651: fold the semantic residue resolver's decision log "
            "(written by 'axial map residue', e.g. "
            "data/map/<pin>/residue_decisions.jsonl) into the store's "
            "note_opposed_position table. positions.jsonl is read from the "
            "same directory as this file. Omitted (default): that table is "
            "left empty, exactly as before this table existed"
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

    vocabulary_parser = subparsers.add_parser(
        "vocabulary",
        help=(
            "issue #805 (derived-vocabulary, slice 01): 'examine' is a "
            "read-only categorisation pass over the twelve sentence-valued "
            "answer columns -- whether they group by MEANING even though "
            "they never repeat as strings, the go/no-go for the feature "
            "(plans/derived-vocabulary/README.md)"
        ),
    )
    vocabulary_subparsers = vocabulary_parser.add_subparsers(dest="vocabulary_command")
    vocabulary_examine_parser = vocabulary_subparsers.add_parser(
        "examine",
        help=(
            "read data/answers/ and, per column: report its answered/"
            "distinct/excluded counts, have a model propose a category "
            "scheme from a random sample, assign a disjoint held-out sample "
            "against it in batches, and have a SECOND model re-assign a "
            "subsample of the same held-out values for a self-consistency "
            "check -- writes no pipeline artifact, only propose/assign/"
            "check model calls"
        ),
    )
    vocabulary_examine_parser.add_argument(
        "--columns",
        default=None,
        help=(
            "comma-separated column names to examine (default: all twelve, "
            f"{','.join(VOCABULARY_COLUMNS)})"
        ),
    )
    vocabulary_examine_parser.add_argument(
        "--propose-n",
        type=int,
        default=None,
        help=(
            "how many values a random sample offers the model that proposes "
            f"the category scheme (default: {DEFAULT_PROPOSE_N}, measured at "
            "$0.026 for one column)"
        ),
    )
    vocabulary_examine_parser.add_argument(
        "--assign-n",
        type=int,
        default=None,
        help=(
            "how many further, disjoint values the held-out sample offers "
            f"(default: {DEFAULT_ASSIGN_N})"
        ),
    )
    vocabulary_examine_parser.add_argument(
        "--answers-dir",
        default=None,
        help="override data/answers/ (default: resolved from config/pipeline.yaml)",
    )

    vocabulary_build_parser = vocabulary_subparsers.add_parser(
        "build",
        help=(
            "issue #806 (derived-vocabulary, slice 02): assign every "
            "answered value in a column against the category scheme frozen "
            f"in {DEFAULT_VOCABULARY_SCHEME_PATH} and persist the assignment "
            "under data/vocabulary/<column>/. The scheme is an INPUT a "
            "person commits, never derived here. A second run over "
            "unchanged answers and an unchanged scheme re-assigns nothing "
            "and makes zero model calls; a run after new answers land "
            "assigns only those"
        ),
    )
    vocabulary_build_parser.add_argument(
        "--columns",
        default=None,
        help=(
            "comma-separated column names to build (default: every column "
            "the frozen scheme file commits a scheme for -- widening the "
            "build is an edit to that file, not a code change)"
        ),
    )
    vocabulary_build_parser.add_argument(
        "--scheme-path",
        default=None,
        help=f"override {DEFAULT_VOCABULARY_SCHEME_PATH} (default: that path)",
    )
    vocabulary_build_parser.add_argument(
        "--vocabulary-dir",
        default=None,
        help="override data/vocabulary/ (default: that path)",
    )
    vocabulary_build_parser.add_argument(
        "--answers-dir",
        default=None,
        help="override data/answers/ (default: resolved from config/pipeline.yaml)",
    )
    vocabulary_build_parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_ASSIGN_WORKERS,
        help=(
            "how many assignment batches run concurrently (default: "
            f"{DEFAULT_ASSIGN_WORKERS})"
        ),
    )
    vocabulary_build_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "re-assign each column whatever is on disk, and the only way "
            "past the refusal a scheme-version change raises -- what "
            "re-assigning under an edited scheme takes, deliberately, with "
            "the safe default kept (the same shape as 'map build --force'). "
            "Moves the previous artifact aside to a timestamped sibling "
            "rather than deleting it: it is the only record of what each "
            "note was filed under, and it was paid for"
        ),
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

    map_residue_parser = map_subparsers.add_parser(
        "residue",
        help=(
            "the semantic residue resolver's full pass (issue #651): every "
            "arguing_against target the relational join reaches nothing with "
            "(data/answers/ + the name layer), matched against the pinned "
            "map's own positions by one model call per target, both blocking "
            "arms, threaded. Requires a map already built at this pin ('axial "
            "map build' first); writes residue_decisions.jsonl as a sibling "
            "of positions.jsonl under the same pinned directory. Fold the "
            "result into the store with 'axial names materialize "
            "--residue-decisions-path <that file>'"
        ),
    )
    map_residue_parser.add_argument(
        "--workers",
        type=int,
        default=MAP_RESIDUE_DEFAULT_WORKERS,
        help=(
            "bounded concurrent resolve-target workers (this pass is "
            f"I/O-bound, like 'map build') (default: {MAP_RESIDUE_DEFAULT_WORKERS})"
        ),
    )

    eval_parser = subparsers.add_parser(
        "eval",
        help=(
            "offline eval instruments: `eval coherence` (the argument-"
            "coherence track, specs/PHASE-C.md §10.2) and `eval layers` (the "
            "per-arm layer comparison, issue #809)"
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

    eval_layers_parser = eval_subparsers.add_parser(
        "layers",
        help=(
            "issue #809: compare the retrieval arms off the sweep directories "
            "they already wrote. One table -- per brief, per arm, the "
            "grounding gate's figure and the count of distinct sources cited, "
            "each carrying that brief's spread across its own draws. A pure "
            "reader: no model call, no retrieval, no second gate scoring. "
            "Refuses directories that do not cover the same briefs, the same "
            "draw count and the same commit"
        ),
    )
    eval_layers_parser.add_argument(
        "--arm-dir",
        action="append",
        required=True,
        dest="arm_dirs",
        metavar="DIR",
        help=(
            "a sweep directory ('axial brief sweep --sweep-dir'), one per arm; "
            "repeat the flag once per arm being compared"
        ),
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

    subparsers.add_parser(
        "status",
        help=(
            "one screen, zero model calls: how many sources and what stage "
            "each is at (derived from the artifacts on disk, never from the "
            "resume ledger alone), the live corpus pin, vault note/name-page "
            "counts, what failed and why, and whether a run is alive right "
            "now (issue #530)"
        ),
    )

    subparsers.add_parser(
        "console",
        help=(
            "open the local operator console in a browser -- sources and "
            "ingest, a live run monitor, and status, over this same CLI "
            "(issue #689; needs `uv sync --group operator`)"
        ),
    )

    runs_parser = subparsers.add_parser(
        "runs", help="watch a run's own log directory (issue #530; reads what CLI-1/#526 writes)"
    )
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command")

    runs_subparsers.add_parser(
        "list", help="list every run, past and present, newest first, with status and liveness"
    )

    runs_show_parser = runs_subparsers.add_parser(
        "show", help="read one run's meta, record tally and failures -- live or finished"
    )
    runs_show_parser.add_argument(
        "run", help="a run_id (e.g. run-interrogate-20260802T115000Z) or a run directory path"
    )

    runs_follow_parser = runs_subparsers.add_parser(
        "follow",
        help=(
            "tail a run's records/events as they are appended; stops and "
            "reports the outcome once the run finishes, or reports the "
            "run as dead once its heartbeat goes stale -- never hangs"
        ),
    )
    runs_follow_parser.add_argument(
        "run", help="a run_id (e.g. run-interrogate-20260802T115000Z) or a run directory path"
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
            "synthesis and everything after it is unchanged. Superseded by "
            "--arm when both are given; kept so no existing invocation breaks"
        ),
    )
    brief_run_parser.add_argument(
        "--arm",
        choices=KNOWN_ARMS,
        default=None,
        help=(
            "named retrieval arm to run (issue #807): 'name' (default) is "
            "the existing name-layer loop, 'map' is the argument-map path "
            "(issue #572) with no vocabulary step, 'map+vocab' adds the "
            "vocabulary step -- passages that share a derived-vocabulary "
            "category (issue #806) join the map's own walk between the "
            "corridor and assembly. Takes precedence over --map when both "
            "are given."
        ),
    )

    # The four vocabulary knobs (issue #822). #809 measures the `map+vocab`
    # arm next and the per-category cap binds on every category, so a knob
    # only settable in code would force an edit mid-measurement. Every one
    # is ignored on any arm but `map+vocab`, and every default is
    # `axial.argmap.vocabulary_join`'s own constant rather than a literal
    # restated here.
    brief_run_parser.add_argument(
        "--vocabulary-column",
        dest="vocabulary_column",
        default=DEFAULT_VOCABULARY_COLUMN,
        help=(
            "derived-vocabulary column the join reads (issue #806/#807; "
            f"default: {DEFAULT_VOCABULARY_COLUMN}) -- only used on --arm map+vocab"
        ),
    )
    brief_run_parser.add_argument(
        "--vocabulary-level",
        dest="vocabulary_level",
        type=int,
        default=None,
        help=(
            "level of that column's scheme to join at (default: the "
            "column's finest level, read off its own manifest)"
        ),
    )
    brief_run_parser.add_argument(
        "--vocabulary-dir",
        dest="vocabulary_dir",
        default=None,
        help="override data/vocabulary/ (default: that path)",
    )
    brief_run_parser.add_argument(
        "--vocabulary-cap",
        dest="vocabulary_cap",
        type=int,
        default=PER_CATEGORY_CAP,
        help=(
            "most neighbours ONE category may hand to assembly (default: "
            f"{PER_CATEGORY_CAP}, against the shared assembly cap of 90) -- the "
            "selection rule in practice, not a safety valve"
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
    brief_sweep_parser.add_argument(
        "--arm",
        default="name",
        help=(
            "named retrieval arm every draw runs through (issue #808): "
            "'name' (default) is the existing name-layer loop, 'map' is "
            "the argument-map path (issue #572), 'map+vocab' the same walk "
            "with the vocabulary step (issue #807) -- forwarded verbatim, "
            "with no fixed list of valid names here, so an arm added "
            "elsewhere is usable with no edit to this command; resuming "
            "--sweep-dir under a different arm than the one already "
            "recorded there is refused"
        ),
    )
    brief_sweep_parser.add_argument(
        "--map",
        dest="arm",
        action="store_const",
        const="map",
        # Same default as `--arm` above, so neither registration order nor
        # which of the two carries the default decides what a bare `brief
        # sweep` runs: argparse seeds a dest from the FIRST action that
        # declares it, so a `None` here would become the no-flag default
        # if the two calls were ever swapped.
        default="name",
        help="alias for --arm map (issue #572), kept so no existing invocation breaks",
    )

    # The four vocabulary knobs (issue #822). #809 measures the `map+vocab`
    # arm next and the per-category cap binds on every category, so a knob
    # only settable in code would force an edit mid-measurement. Every one
    # is ignored on any arm but `map+vocab`, and every default is
    # `axial.argmap.vocabulary_join`'s own constant rather than a literal
    # restated here.
    brief_sweep_parser.add_argument(
        "--vocabulary-column",
        dest="vocabulary_column",
        default=DEFAULT_VOCABULARY_COLUMN,
        help=(
            "derived-vocabulary column the join reads (issue #806/#807; "
            f"default: {DEFAULT_VOCABULARY_COLUMN}) -- only used on --arm map+vocab"
        ),
    )
    brief_sweep_parser.add_argument(
        "--vocabulary-level",
        dest="vocabulary_level",
        type=int,
        default=None,
        help=(
            "level of that column's scheme to join at (default: the "
            "column's finest level, read off its own manifest)"
        ),
    )
    brief_sweep_parser.add_argument(
        "--vocabulary-dir",
        dest="vocabulary_dir",
        default=None,
        help="override data/vocabulary/ (default: that path)",
    )
    brief_sweep_parser.add_argument(
        "--vocabulary-cap",
        dest="vocabulary_cap",
        type=int,
        default=PER_CATEGORY_CAP,
        help=(
            "most neighbours ONE category may hand to assembly (default: "
            f"{PER_CATEGORY_CAP}, against the shared assembly cap of 90) -- the "
            "selection rule in practice, not a safety valve"
        ),
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
    brief_smoke_parser.add_argument(
        "--arm",
        # `None`, never "name" (issue #822): a "name" default would override
        # --map and silently run the name layer. `run_sweep` resolves the
        # pair -- `arm` wins when given, `--map` alone still reads as "map".
        default=None,
        help=(
            "named retrieval arm the whole smoke set runs through (issue "
            "#822): 'name' is the name-layer loop, 'map' the argument-map "
            "path (issue #572), 'map+vocab' the same walk with the "
            "vocabulary step (issue #807) -- forwarded verbatim, with no "
            "fixed list of valid names here, so an arm added elsewhere is "
            "usable with no edit to this command. Unset by default, so "
            "--map still decides; takes precedence over --map when both "
            "are given"
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

    publish_parser = subparsers.add_parser(
        "publish",
        help=(
            "publish the built corpus as an immutable, read-only snapshot "
            "(issue #684): the vault, name layer, envelopes, argument map, "
            "config and corpus-pin manifest, copied under "
            "<snapshots-dir>/<version>/ and never overwritten. The raw "
            "source files are deliberately NOT included"
        ),
    )
    publish_parser.add_argument(
        # `snapshot_version`, NOT `version`: the parser carries a global
        # `--version` store_true flag whose dest is `version`, and `main`
        # checks `args.version` before any command dispatch. A positional
        # spelled `version` writes the snapshot name into that same dest, so
        # `axial publish 2026-08-10` printed "axial 0.1.0" and exited 0
        # having published nothing. `metavar` keeps the command's own
        # surface syntax unchanged.
        "snapshot_version",
        metavar="version",
        help="the snapshot version, e.g. '2026-08-10' -> data/snapshots/2026-08-10/",
    )
    publish_parser.add_argument(
        "--snapshots-dir",
        default=None,
        help="where snapshots land (default: data/snapshots)",
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

    ask_parser = subparsers.add_parser(
        "ask",
        help=(
            "open a session: state the case, ask a question, watch the "
            "engine work in plain words, read the answer, ask a follow-up "
            "-- no brief YAML to author (issue #534). A full engine run "
            "(specs/PHASE-B.md §7.3) either way, exactly like `brief run`"
        ),
    )
    ask_parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="the question to ask; omit to be prompted for it interactively",
    )
    ask_parser.add_argument(
        "--case",
        default=None,
        help=(
            "the case (§7.1): a polity or set of polities, written as the "
            "corpus writes them. Supplying both QUESTION and --case runs one "
            "turn and exits, with no follow-up prompt; omit either (or both) "
            "to be prompted, and to keep the session open for follow-ups"
        ),
    )
    ask_parser.add_argument(
        "--list",
        dest="list_past",
        action="store_true",
        help=(
            "list past questions (issue #536): when each was asked, what "
            "case, what happened, and the headline cross-book number -- "
            "never spends money and never calls the engine"
        ),
    )
    ask_parser.add_argument(
        "--reopen",
        type=int,
        default=None,
        metavar="N",
        help=(
            "reopen past question N from `--list`'s own numbering (1 is "
            "most recent) and render it exactly like a fresh answer -- "
            "never spends money and never calls the engine"
        ),
    )
    ask_parser.add_argument(
        "--no-paper",
        dest="no_paper",
        action="store_true",
        help=(
            "stop at the answer instead of drafting the paper it would "
            "otherwise end in (issue #668). Every turn drafts one by "
            "default; this is the way to ask a cheap exploratory question"
        ),
    )
    ask_parser.add_argument(
        "--weight",
        dest="weight",
        action="append",
        default=None,
        metavar="SOURCE_ID=FLOAT",
        help=(
            "give a source more or fewer rotation slots in the evidence "
            "round-robin, repeatable (issue #639); every source defaults "
            "to 1.0 and this is never a filter -- a source at any weight, "
            "including 0, stays reachable"
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
    workers: int = INTERROGATE_DEFAULT_WORKERS,
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
                workers=workers,
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


def _position_backfill(
    source_path: str,
    domain_dir: str | None,
    data_dir: str | None,
    limit: int | None,
    workers: int = INTERROGATE_DEFAULT_WORKERS,
    *,
    root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> int:
    """Run the `position` backfill pass on `source_path` (issue #697):
    mirrors `_interrogate`'s own run-logging wrapper -- one `run.jsonl`
    record per invocation, not per note. The run summary (missing/backfilled
    counts, `position`'s own abstention rate, measured cost) is the stdout
    payload."""
    resolved_data_dir = Path(data_dir) if data_dir else None
    if root is None and resolved_data_dir is not None:
        root = resolved_data_dir / "logs"
    with run_context("position-backfill", root=root, clock=clock) as run:
        start = time.monotonic()
        try:
            client = get_client()
        except LLMError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        try:
            summary = run_position_backfill(
                source_path,
                client=client,
                data_dir=resolved_data_dir,
                domain_dir=domain_dir,
                limit=limit,
                workers=workers,
            )
        except (InterrogateError, LLMError) as exc:
            run.record(
                source_id=_safe_source_id(source_path),
                pass_name=POSITION_BACKFILL_PASS_NAME,
                model=None,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id=summary["source_id"],
            pass_name=POSITION_BACKFILL_PASS_NAME,
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
        exit_code = _sources_local(check)
    elif backend == "drive":
        exit_code = _sources_drive(check)
    else:
        print(
            f"error: unknown sources backend {backend!r} (expected 'local' or 'drive')",
            file=sys.stderr,
        )
        return 1

    # The reverse pass, after whichever backend reported (issue #819). It is
    # not a `--check`-only extra and not backend-specific: both backends
    # ingest into the same `data/sources`, and an envelope the corpus pin
    # cannot resolve a raw file for kills the pin whatever put it there.
    # Silent when the corpus is sound, so the healthy output is unchanged.
    #
    # To STDERR, not stdout, and after the backend's own report: stdout is a
    # single tab-separated table with one header row, and anything parsing
    # it must not break on the corpus state it most needs to detect. The
    # unknown-backend error above goes to stderr for the same reason.
    orphans = scan_orphaned_envelopes()
    if orphans:
        print(
            "error: the corpus pin cannot be computed -- "
            f"{len(orphans)} ingested source(s) have no raw file:",
            file=sys.stderr,
        )
        print(render_report(orphans), file=sys.stderr)
        return 1
    return exit_code


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


def _status() -> int:
    print(render_status(compute_status()))
    return 0


def _console() -> int:
    """`axial console` (issue #689): hand `streamlit run` the console app and
    stay out of the way. Deliberately a wrapper with no options of its own --
    the app takes none, and Streamlit's own flags are one `streamlit run`
    away for the rare case that wants them. Run from the checkout, so the
    console resolves `data/` and `.streamlit/config.toml` the same way every
    other `axial` command resolves its paths."""
    import importlib.util
    import subprocess

    if importlib.util.find_spec("streamlit") is None:
        print(
            "error: streamlit is not installed -- run `uv sync --group operator`",
            file=sys.stderr,
        )
        return 1
    app_path = Path(__file__).resolve().parent / "operator" / "app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)])


def _runs_list() -> int:
    print(render_run_list(list_runs()))
    return 0


def _runs_show(run: str) -> int:
    try:
        run_dir = resolve_run_dir(run)
        view = load_run(run_dir)
    except RunNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(render_run_view(view))
    return 0


def _runs_follow(run: str) -> int:
    try:
        run_dir = resolve_run_dir(run)
    except RunNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    last_status: str | None = None
    for item in follow_run(run_dir, stop_when_stale=True):
        print(render_follow_line(item))
        if item.get("stream") == "status":
            last_status = item.get("status")

    if last_status == "stale":
        print("[done] the run's heartbeat went stale -- it appears to have died mid-run")
        return 1

    final_status = load_run(run_dir).meta.get("status")
    print(f"[done] status: {final_status}")
    return 0 if final_status == "ok" else 1


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


_ARM_DISPLAY = {
    NAME_ARM: "name layer",
    MAP_ARM: "argument map",
    MAP_VOCAB_ARM: "argument map + vocabulary",
}


def _brief_run(
    brief_path: str,
    *,
    use_map: bool = False,
    arm: str | None = None,
    vocabulary_column: str = DEFAULT_VOCABULARY_COLUMN,
    vocabulary_level: int | None = None,
    vocabulary_dir: str | None = None,
    vocabulary_cap: int = PER_CATEGORY_CAP,
) -> int:
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
            arm=arm,
            vocabulary_column=vocabulary_column,
            vocabulary_level=vocabulary_level,
            vocabulary_dir=Path(vocabulary_dir) if vocabulary_dir is not None else None,
            vocabulary_cap=vocabulary_cap,
            on_event=_print_event,
        )
    except (
        InterrogationError,
        ForkCheckError,
        QueryError,
        SynthesisError,
        CorpusPinError,
        AnswerError,
        AskError,
        # issue #807: the `map+vocab` arm's own declared failure -- a column
        # with no persisted vocabulary. Listed explicitly rather than given
        # `AskError` as a base, because `axial.argmap.ask` imports
        # `vocabulary_join` and the inheritance would be a cycle.
        NoVocabularyError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # `arm`, given, wins over `--map` (`run_brief`'s own precedence, issue
    # #807) -- this is display-only, mirrored from that same rule so the
    # printed line never disagrees with what actually ran.
    resolved_arm = arm if arm is not None else (MAP_ARM if use_map else NAME_ARM)
    print(f"retrieval: {_ARM_DISPLAY.get(resolved_arm, resolved_arm)}")
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


def _ask_prompt(label: str) -> str | None:
    """One `input()` prompt for `axial ask`, returning `None` on EOF/
    interrupt rather than raising -- the caller reads that as "end the
    session", mirroring `_key_set`'s own EOF-is-a-clean-exit rule."""
    try:
        return input(label)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _fork_prompt(fork: ForkCheckResult) -> ForkAnswer | None:
    """`axial ask`'s own interactive answer to a genuine intake fork (issue
    #649, specs/PHASE-B.md §7, DEC-62): print the question and its numbered
    options -- always alongside free text, never a form -- and read one
    line. A reply matching an option's own number or label (case-
    insensitive) becomes that option's own answer; anything else is read as
    free text verbatim. A blank line or EOF returns `None`: the analyst
    declined to answer, and the run proceeds unconstrained, recorded as
    such in the persisted record's `intake_fork` block."""
    print(f"\n{fork.question}", file=sys.stderr)
    for index, option in enumerate(fork.options, start=1):
        print(f"  {index}) {option.label}", file=sys.stderr)
    print("  (or type your own answer)", file=sys.stderr)
    reply = _ask_prompt("> ")
    if reply is None or not reply.strip():
        return None
    reply = reply.strip()
    for index, option in enumerate(fork.options, start=1):
        if reply == str(index) or reply.casefold() == option.label.casefold():
            return ForkAnswer(option=option.label)
    return ForkAnswer(free_text=reply)


def _print_ask_turn(turn: AskTurn) -> int:
    """Print one `axial ask` turn's answer: the analyst-facing rendering
    (issue #535, `render_analyst_answer`) of its own just-persisted record
    and run report -- which books it drew on by title, how much of the
    corpus it read and used, how well that corpus covers what it discusses,
    how confident it is and why, and the cross-book headline -- so a
    question is answered in the session itself, in plain language, never
    only as a file path to go find (issue #534's own "not a usable surface"
    complaint). `_print_encoding_safe`, never a bare `print`, since the
    answer is real corpus prose (mirrors `_brief_run`). The persisted paths
    still print below it for the operator/debugging case; an analyst never
    needs to open either to trust the answer above them."""
    _print_encoding_safe(render_analyst_answer(turn.result.record, turn.result.report))
    print(f"\npersisted: {turn.result.path}")
    print(f"run report: {turn.result.report_path}")
    return 0


def _format_past_turns(turns: list[PastTurn]) -> str:
    """`axial ask --list` (issue #536): every past turn, most recently
    asked first, numbered so `--reopen` never needs a `brief_id`."""
    if not turns:
        return "no past questions yet"
    lines = []
    for index, turn in enumerate(turns, start=1):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(turn.asked_at))
        headline = f"{turn.cross_source_rate:.0%}" if turn.cross_source_rate is not None else "n/a"
        lines.append(
            f"{index}. [{when}] case={turn.case!r} {turn.disposition} cross-book={headline}"
        )
        lines.append(f"     {turn.question}")
    return "\n".join(lines)


def _ask_list() -> int:
    """List past questions (issue #536), never spending money: pure reads
    over `<analyses_dir>`/`<runs_dir>`, no client constructed."""
    _print_encoding_safe(_format_past_turns(list_past_turns()))
    return 0


def _ask_reopen(index: int) -> int:
    """Reopen past question number `index` from `--list`'s own numbering
    (1-based, most recent first) and render it exactly as commit 1 renders
    a fresh answer (issue #536's own acceptance: "no knowledge of hashes or
    paths"). Never spends money: no client is constructed on this path."""
    turns = list_past_turns()
    if index < 1 or index > len(turns):
        print(
            f"error: no past question numbered {index} (there are {len(turns)}); "
            "run `axial ask --list` first",
            file=sys.stderr,
        )
        return 1
    loaded = load_turn(turns[index - 1].brief_id)
    if loaded is None:
        print("error: that question's record could not be re-read", file=sys.stderr)
        return 1
    record, report = loaded
    _print_encoding_safe(render_analyst_answer(record, report))
    return 0


# Every error `axial.ask.ask` can raise: its own precondition
# (`AskSessionError`, a blank case or question) plus whatever the engine it
# drives (`run_brief`, unchanged from `_brief_run`'s own set) can raise.
_ASK_ERRORS = (
    AskSessionError,
    InterrogationError,
    ForkCheckError,
    QueryError,
    SynthesisError,
    CorpusPinError,
    AnswerError,
    AskError,
)


class WeightArgError(Exception):
    """Raised by `_parse_weight_args` on a malformed `--weight` value."""


def _parse_weight_args(raw: list[str] | None) -> dict[str, float]:
    """Parse `--weight <source_id>=<float>` (issue #639), repeatable: `raw`
    is argparse's own `action="append"` list, `None` when the flag was
    never given. Each entry must split on exactly one `=` into a non-empty
    `source_id` and a float; a later repeat of the same `source_id`
    overrides an earlier one rather than erroring, the same "last flag
    wins" rule argparse itself would give a non-repeatable option. Raises
    `WeightArgError` naming the offending value on any malformed entry --
    never a partial dict silently returned alongside an error."""
    if not raw:
        return {}
    weights: dict[str, float] = {}
    for entry in raw:
        source_id, sep, value = entry.partition("=")
        if not sep or not source_id.strip():
            raise WeightArgError(f"invalid --weight {entry!r}: expected SOURCE_ID=FLOAT")
        try:
            weight = float(value)
        except ValueError:
            raise WeightArgError(f"invalid --weight {entry!r}: {value!r} is not a number") from None
        if weight < 0:
            raise WeightArgError(f"invalid --weight {entry!r}: weight must be >= 0")
        weights[source_id.strip()] = weight
    return weights


def _ask_paper(client: Any, turn: AskTurn) -> int:
    """Draft the paper a question ends in (issue #668) -- PHASE-C §0's own
    "a call plus a mechanical module move", made here rather than by hand.

    The question is the paper's `thesis` (§7.1 defines thesis as "the paper's
    organizing question", which is what a question is), the record this turn
    just persisted is its single `analysis_ids` entry, and no lens is named so
    the stage chooses and records its own. Pin agreement is trivial on one
    fresh record, and Phase C is never asked to run Phase B -- the record
    already exists when this is called (§3 non-goal 1).

    **A refusal is skipped, not failed.** §7.1 rejects a refused record at
    paper intake because it carries no claims, so drafting one would turn a
    valid Phase-B outcome into an error.

    A `weak` shape check does NOT fail the turn the way it fails
    `axial paper draft`: the analyst asked a question and has both the answer
    and the paper in front of them, and `_print_paper` has already named the
    defects on stderr. Only a drafting failure is non-zero here."""
    try:
        paper_record = draft_paper_for_turn(client, turn)
    except _PAPER_PIPELINE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if paper_record is None:
        print("\nno paper drafted: the question was refused, so there are no claims to draft.")
        return 0

    print()
    _print_paper(paper_record["paper_brief_id"], paper_record)
    return 0


def _ask(
    question: str | None,
    case: str | None,
    *,
    list_past: bool = False,
    reopen: int | None = None,
    weight_args: list[str] | None = None,
    draft_paper: bool = True,
) -> int:
    """`axial ask` (issue #534): a session over the plain `axial.ask.ask`
    function -- state the case, ask the question, watch the work happen in
    plain words (`_print_event`, the same rendering `axial brief run`
    already uses), read the answer, ask a follow-up. Supplying BOTH
    `question` and `case` up front is the one-shot form -- one turn, no
    prompts, no follow-up loop, `axial ask "..." --case "..."` -- anything
    else opens an interactive session, prompting only for what was not
    already given, and keeps prompting for follow-ups until a blank line or
    EOF ends it. A follow-up is answered by `axial.ask.ask` as a full run of
    its own, carrying the previous turn's question and claims forward as
    context -- never a chat turn answering from memory.

    `list_past`/`reopen` (issue #536) short-circuit before any client is
    constructed -- neither ever spends money, both are pure reads over
    already-persisted records (`axial.ask.history`).

    `weight_args` (issue #639) is argparse's raw `--weight` list, parsed
    once here (`_parse_weight_args`) and threaded into every turn of this
    session -- a malformed value is rejected before any client is
    constructed or any prompt shown, the same "fail before spending"
    discipline `list_past`/`reopen` already get."""
    if list_past:
        return _ask_list()
    if reopen is not None:
        return _ask_reopen(reopen)

    try:
        weights = _parse_weight_args(weight_args)
    except WeightArgError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    one_shot = question is not None and case is not None

    if case is None:
        case = _ask_prompt("case: ")
    if case is None or not case.strip():
        print("error: a case is required", file=sys.stderr)
        return 1

    if question is None:
        question = _ask_prompt("question: ")
    if question is None or not question.strip():
        print("no question asked -- nothing to do")
        return 0

    client = get_client()
    session_id = new_ask_session_id()
    previous: AskTurn | None = None
    turn_index = 1
    exit_code = 0

    while question is not None and question.strip():
        try:
            turn = ask_question(
                question,
                case,
                client=client,
                session_id=session_id,
                turn_index=turn_index,
                previous=previous,
                weights=weights,
                on_event=_print_event,
                # One-shot (both `question` and `case` given up front) is
                # this docstring's own promise of "no prompts": `on_fork=
                # None` is `ask()`'s documented way of declining an
                # interactive answer, so a genuine fork is recorded
                # unanswered (`intake_fork.answer: null`) instead of
                # blocking on `input()` with no stdin to read (#790).
                on_fork=None if one_shot else _fork_prompt,
            )
        except _ASK_ERRORS as exc:
            print(f"error: {exc}", file=sys.stderr)
            exit_code = 1
            if one_shot:
                return exit_code
            question = _ask_prompt("\nfollow-up (blank to end): ")
            continue

        _print_ask_turn(turn)
        if draft_paper:
            paper_exit = _ask_paper(client, turn)
            if paper_exit:
                exit_code = paper_exit
        if one_shot:
            return exit_code

        previous = turn
        turn_index += 1
        question = _ask_prompt("\nfollow-up (blank to end): ")

    print("session ended.")
    return exit_code


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


def _brief_sweep(
    worklist_path: str,
    draws: int,
    sweep_dir: str,
    workers: int,
    *,
    arm: str = "name",
    vocabulary_column: str = DEFAULT_VOCABULARY_COLUMN,
    vocabulary_level: int | None = None,
    vocabulary_dir: str | None = None,
    vocabulary_cap: int = PER_CATEGORY_CAP,
) -> int:
    try:
        summary = run_sweep(
            worklist_path,
            draws=draws,
            sweep_dir=Path(sweep_dir),
            workers=workers,
            arm=arm,
            vocabulary_column=vocabulary_column,
            vocabulary_level=vocabulary_level,
            vocabulary_dir=Path(vocabulary_dir) if vocabulary_dir is not None else None,
            vocabulary_cap=vocabulary_cap,
        )
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
    briefs_dir: str | None,
    sweep_dir: str,
    workers: int,
    *,
    use_map: bool = False,
    arm: str | None = None,
) -> int:
    try:
        summary = run_smoke(
            sweep_dir=Path(sweep_dir),
            briefs_dir=Path(briefs_dir) if briefs_dir is not None else None,
            workers=workers,
            use_map=use_map,
            arm=arm,
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
# never catches either -- see its own docstring). Caught together so every
# rejection reports as a named, non-zero failure -- never a traceback --
# exactly like `_brief_run`'s own tuple one layer down.
#
# The tuple itself moved to `axial.ask.paper` in issue #784, so the service
# worker catches the same set rather than keeping a second idea of what a
# drafting failure is. Aliased here under its old name because this module
# names it in two places and it is the CLI's own vocabulary.
_PAPER_PIPELINE_ERRORS = PAPER_PIPELINE_ERRORS


def _print_paper(paper_brief_id: str, record: dict[str, Any]) -> bool:
    """Print one drafted paper's own summary and paths, returning whether its
    shape check came back `weak`. Shared by `axial paper draft` and by the
    paper `axial ask` drafts at the end of a turn (issue #668), so the two
    surfaces report a paper identically."""
    markdown_path = Path(record["paper_markdown_path"])
    record_path = markdown_path.with_suffix(".json")
    shape = record.get("shape") or {}
    print(f"paper_brief_id: {paper_brief_id}")
    print(f"corpus_pin: {record['corpus_pin']}")
    print(f"lens: {record['lens']}")
    print(f"sections: {len(record['plan']['sections'])}")
    print(f"claims cited: {len(record['claims'])}")
    print(f"confidence: {record['confidence']['overall_band']}")
    print(f"shape: {shape.get('band')}")
    repetition = shape.get("repetition") or {}
    if "fraction" in repetition:
        print(f"cross-section repetition: {repetition['fraction']:.2%}")
    print(f"persisted: {record_path}")
    print(f"paper: {markdown_path}")

    # The shape check reports; it never blocks the record or the rendered
    # paper from being written (§3 non-goal 9, §7.16). It DOES say so loudly
    # -- the operator reads the named defects and decides whether to re-run;
    # there is no re-draft loop.
    if shape.get("band") == "weak":
        defects = shape.get("defects") or []
        print(
            f"shape check: WEAK -- {len(defects)} defect(s) named; the paper was still "
            "written to disk, but its own shape check flagged it. Review the defects on "
            f"{record_path} before treating this draft as done.",
            file=sys.stderr,
        )
        return True
    return False


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

    return 1 if _print_paper(paper_brief.paper_brief_id, record) else 0


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


def _publish(version: str, snapshots_dir: str | None) -> int:
    """`axial publish <version>` (issue #684). Imported inside the handler
    so the CLI's own import does not pull `axial.service`, which needs the
    optional `service` dependency group."""
    from axial.service.snapshot import SnapshotError, publish

    try:
        snapshot = publish(version, snapshots_dir=Path(snapshots_dir) if snapshots_dir else None)
    except (SnapshotError, CorpusPinError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"published {snapshot.version} to {snapshot.root}")
    print(f"corpus_pin: {snapshot.corpus_pin}")
    print(f"map_pin: {snapshot.map_pin or '(no argument map built)'}")
    print(f"sources: {len(snapshot.sources)}")
    return 0


def _names_build(min_cluster_size: int | None, min_samples: int | None, recluster: bool) -> int:
    kwargs: dict[str, Any] = {"recluster": recluster}
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
    print(f"units_total: {result.units_total}")
    print(f"units_reused: {result.units_reused}")
    print(f"units_asked: {result.units_asked}")
    print(f"units_asked_touching_new: {result.units_asked_touching_new}")
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


def _parse_vocabulary_columns(raw: str | None) -> list[str]:
    if raw is None:
        return list(VOCABULARY_COLUMNS)
    return [value.strip() for value in raw.split(",") if value.strip()]


def _vocabulary_examine(
    columns: str | None, propose_n: int | None, assign_n: int | None, answers_dir: str | None
) -> int:
    try:
        stats = examine_vocabulary(
            answers_dir=Path(answers_dir) if answers_dir is not None else None,
            columns=_parse_vocabulary_columns(columns),
            propose_n=propose_n if propose_n is not None else DEFAULT_PROPOSE_N,
            assign_n=assign_n if assign_n is not None else DEFAULT_ASSIGN_N,
        )
    except SelfConsistencyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_encoding_safe(format_vocabulary_report(stats))
    return 0


def _vocabulary_build(
    columns: str | None,
    scheme_path: str | None,
    vocabulary_dir: str | None,
    answers_dir: str | None,
    workers: int,
    force: bool = False,
) -> int:
    """Exit 1 on a scheme the operator has to fix, on a scheme-version
    mismatch the operator has to decide about, and on a build that left a
    value unanswered -- an unanswered value is a failed run, not a
    result."""
    try:
        stats = build_vocabulary(
            answers_dir=Path(answers_dir) if answers_dir is not None else None,
            columns=_parse_vocabulary_columns(columns) if columns is not None else None,
            scheme_path=(
                Path(scheme_path)
                if scheme_path is not None
                else DEFAULT_VOCABULARY_SCHEME_PATH
            ),
            vocabulary_dir=Path(vocabulary_dir) if vocabulary_dir is not None else None,
            workers=workers,
            force=force,
        )
    except (VocabularySchemeError, SchemeVersionMismatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_encoding_safe(format_vocabulary_build_report(stats))
    return 0 if stats.complete else 1


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
        "units_total",
        "units_reused",
        "units_asked",
        "units_asked_touching_new",
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


def _names_materialize(residue_decisions_path: str | None = None) -> int:
    try:
        result = run_materialize(
            residue_decisions_path=Path(residue_decisions_path) if residue_decisions_path else None
        )
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
        "store_notes",
        "store_notes_back_matter",
        "store_note_names",
        "store_note_arguing_against",
        "store_note_citations",
        "store_note_opposed_position",
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
        "units_total",
        "units_reused",
        "units_asked",
        "units_asked_touching_new",
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


def _map_residue(*, workers: int = MAP_RESIDUE_DEFAULT_WORKERS) -> int:
    """`axial map residue` (issue #651): run the semantic residue resolver's
    full pass -- every unresolved `arguing_against` target, both blocking
    arms, threaded -- and print the union resolution rate and cost per arm.
    Requires a map already built at this corpus's pin (`axial map build`
    first, `MapNotBuiltError` otherwise); refuses a second concurrent copy
    over the same pinned directory (`AlreadyRunningError`)."""
    with run_context("map-residue") as run:
        start = time.monotonic()

        def _tee(message: str) -> None:
            print(message, flush=True)
            run.logger.info(message)

        try:
            manifest = run_residue_pass(workers=workers, log=_tee)
        except (AskError, AlreadyRunningError, LLMError) as exc:
            run.record(
                source_id="",
                pass_name="residue_resolve",
                model=None,
                status="error",
                duration_sec=time.monotonic() - start,
                error=str(exc),
            )
            print(f"error: {exc}", file=sys.stderr)
            return 1

        run.record(
            source_id=manifest["pin"],
            pass_name="residue_resolve",
            model=None,
            status="ok",
            duration_sec=time.monotonic() - start,
            error=None,
        )

    print(f"pin: {manifest['pin']}")
    print(f"decisions_path: {manifest['decisions_path']}")
    print(f"positions: {manifest['positions_count']}")
    print(f"unresolved targets: {manifest['unresolved_count']}")
    print(f"resolved (union of both arms): {manifest['union_resolved']}")
    for mode, stats in manifest["modes"].items():
        cost = f"${stats['cost_usd']:.4f}" if stats["cost_usd"] is not None else "unpriced"
        print(
            f"  {mode}: resolved {stats['resolved']} | calls made {stats['calls_made']} | "
            f"reused {stats['calls_reused']} | {stats['wall_time_sec']:.1f}s | cost {cost}"
        )
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


def _eval_layers(arm_dirs: list[str]) -> int:
    """The issue #809 layer comparison: sweep directories in, one table out.
    A pure reader -- every figure it prints was computed by the sweep and
    persisted, so this makes no model call and scores no gate."""
    try:
        comparison = compare_arms([Path(arm_dir) for arm_dir in arm_dirs])
    except LayerComparisonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_encoding_safe(format_layer_comparison(comparison))
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


# The analyst role's whole reachable surface (issue #536, `plans/
# multiuser-analyst-service/README.md`): `axial ask` (issue #534), nothing
# else. `--version` is a top-level flag, not a subparser choice, so it is
# untouched by this restriction either way.
_ANALYST_ALLOWED_COMMANDS = frozenset({"ask"})


def _restrict_parser_to_analyst_role(parser: argparse.ArgumentParser) -> None:
    """Prune every subcommand but `ask` from `parser`'s own top-level
    `_SubParsersAction` (issue #536): pruning `choices` (what `argparse`
    rejects a `parser_name not in choices` dispatch against) and
    `_choices_actions` (what the help formatter lists) with the same one
    edit makes an excluded command neither listed in `--help` nor runnable.

    This is a post-build prune, not a role parameter threaded through
    `build_parser`'s own ~1500 lines of subcommand wiring: `src/axial/
    cli.py` is hot (another builder edits it concurrently), and this way
    the role never touches a single line inside that function -- this is
    the one place it touches the parser at all."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name in list(action.choices):
            if name not in _ANALYST_ALLOWED_COMMANDS:
                del action.choices[name]
        action._choices_actions = [
            choice_action
            for choice_action in action._choices_actions
            if choice_action.dest in _ANALYST_ALLOWED_COMMANDS
        ]
        return


def main(argv: list[str] | None = None) -> int:
    try:
        role = current_role()
    except InvalidRoleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser = build_parser()
    if role == ANALYST:
        _restrict_parser_to_analyst_role(parser)
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
        return _interrogate(
            args.source_path, args.domain_dir, args.data_dir, args.limit, args.workers
        )

    if args.command == "position-backfill":
        return _position_backfill(
            args.source_path, args.domain_dir, args.data_dir, args.limit, args.workers
        )

    if args.command == "names" and args.names_command == "build":
        return _names_build(args.min_cluster_size, args.min_samples, args.recluster)

    if args.command == "names" and args.names_command == "examine":
        return _names_examine(args.min_cluster_sizes, args.min_samples)

    if args.command == "vocabulary" and args.vocabulary_command == "examine":
        return _vocabulary_examine(
            args.columns, args.propose_n, args.assign_n, args.answers_dir
        )

    if args.command == "vocabulary" and args.vocabulary_command == "build":
        return _vocabulary_build(
            args.columns,
            args.scheme_path,
            args.vocabulary_dir,
            args.answers_dir,
            args.workers,
            args.force,
        )

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
        return _names_materialize(args.residue_decisions_path)

    if args.command == "names" and args.names_command == "gather":
        return _names_gather(args.limit, args.workers)

    if args.command == "names" and args.names_command == "escalations":
        return _names_escalations(args.decisions_path, args.inventory_path, args.as_json)

    if args.command == "map" and args.map_command == "build":
        return _map_build(workers=args.workers, force=args.force)

    if args.command == "map" and args.map_command == "ask":
        return _map_ask(args.brief_path)

    if args.command == "map" and args.map_command == "residue":
        return _map_residue(workers=args.workers)

    if args.command == "artifacts":
        return _artifacts(args.source_path)

    if args.command == "gather-eval" and args.gather_eval_command == "sheet":
        return _gather_eval_sheet(sample_size=args.sample_size, seed=args.seed)

    if args.command == "gather-eval" and args.gather_eval_command == "score":
        return _gather_eval_score(
            limit=args.limit,
            null_sample_size=args.null_sample_size,
            seed=args.seed,
            workers=args.workers,
        )

    if args.command == "eval" and args.eval_command == "coherence":
        return _eval_coherence(args.sample, reviewers=args.reviewers, out_path=args.out)

    if args.command == "eval" and args.eval_command == "layers":
        return _eval_layers(args.arm_dirs)

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
        return _brief_run(
            args.brief_path,
            use_map=args.use_map,
            arm=args.arm,
            vocabulary_column=args.vocabulary_column,
            vocabulary_level=args.vocabulary_level,
            vocabulary_dir=args.vocabulary_dir,
            vocabulary_cap=args.vocabulary_cap,
        )

    if args.command == "brief" and args.brief_command == "validate":
        return _brief_validate(args.brief_id)

    if args.command == "brief" and args.brief_command == "coverage":
        return _brief_coverage(args.brief_id)

    if args.command == "brief" and args.brief_command == "usage":
        return _brief_usage(args.pin)

    if args.command == "brief" and args.brief_command == "sweep":
        return _brief_sweep(
            args.worklist_path,
            args.draws,
            args.sweep_dir,
            args.workers,
            arm=args.arm,
            vocabulary_column=args.vocabulary_column,
            vocabulary_level=args.vocabulary_level,
            vocabulary_dir=args.vocabulary_dir,
            vocabulary_cap=args.vocabulary_cap,
        )

    if args.command == "brief" and args.brief_command == "smoke":
        return _brief_smoke(
            args.briefs_dir,
            args.sweep_dir,
            args.workers,
            use_map=args.use_map,
            arm=args.arm,
        )

    if args.command == "paper" and args.paper_command == "draft":
        return _paper_draft(args.paper_brief_file)

    if args.command == "paper" and args.paper_command == "examine":
        return _paper_examine(args.paper_brief_file)

    if args.command == "pin" and args.pin_command == "write":
        return _pin_write(args.name)

    if args.command == "publish":
        return _publish(args.snapshot_version, args.snapshots_dir)

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

    if args.command == "ask":
        return _ask(
            args.question,
            args.case,
            list_past=args.list_past,
            reopen=args.reopen,
            weight_args=args.weight,
            draft_paper=not args.no_paper,
        )

    if args.command == "status":
        return _status()

    if args.command == "console":
        return _console()

    if args.command == "runs" and args.runs_command == "list":
        return _runs_list()

    if args.command == "runs" and args.runs_command == "show":
        return _runs_show(args.run)

    if args.command == "runs" and args.runs_command == "follow":
        return _runs_follow(args.run)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
