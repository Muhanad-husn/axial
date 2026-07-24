"""Stage-5e outer eval -- the quality-per-dollar verdict (issue #353, DEC-32,
DEC-35, plan `plans/phase-a-completion/README.md` stage 5e).

The inner layer (5a-5d) already answered "which axes CAN a classifier
replace the LLM on" -- `claim_type`/`theory_school` (`axial.distill.classify`,
DEC-37/38) and `field`/`role_in_argument` (`axial.distill.classify_embedding`,
DEC-39) all graduated; `empirical_scope` (#349) did not and stays LLM-only.
This module answers the OUTER question DEC-32 actually gates a build
decision on: given those already-measured per-axis numbers, is the resulting
hybrid pipeline worth building, in real dollars, against the real gold set?
It is a measurement/eval artifact only -- like every other stage-5 module,
it is never wired into `axial.tag.run_tag` or any production tagging path.

Three pieces, three CLI subcommands (`axial distill tag-cost-probe`,
`axial distill drift-check`, `axial distill verdict`), mirroring the rest of
stage 5's one-manifest-per-pass shape:

1. `run_tag_cost_probe` -- issue #363/PR #367 shipped `estimate_cost` and a
   per-pass usage accumulator on the LLM client but the real production
   corpus-wide retag ran 2026-07-23, a day BEFORE that landed, so there is no
   historical token log for it. This fires a small number of REAL `tag`-pass
   completions (the real multi-axis prompt, the real model) and reads the
   real `$` back off the client -- a live-measured number, not a guess.
2. `run_drift_check` -- DEC-32/#296's own anticipated drift-monitor dry run:
   the graduated classifiers predict a small sample of already-tagged
   corpus chunks (excluding gold), the LLM freshly re-tags the same sample
   (today's model, not the historical cached tag it trained on), and the two
   are compared. A dry run, not a production drift-monitoring system -- N is
   small and bounded, documented below, not "a few hundred" (the issue's own
   suggestion, but DEC-32 already established no full-corpus all-LLM pass is
   needed for THIS eval, and a drift dry run needs enough chunks to see a
   gross signal, not a tight confidence interval).
3. `run_verdict` -- combines the already-shipped 5d manifests
   (`data/distill/classify_<axis>_manifest.json`), the cost probe, and the
   drift check into one `data/distill/quality_per_dollar_manifest.json`:
   per-axis hybrid-vs-baseline accuracy at a chosen confidence threshold,
   corpus-scale dollar cost for both pipelines, and quality-per-dollar for
   each. Pure/deterministic given its three JSON inputs -- no network, no
   sklearn -- so it is unit-tested without live data.

Structural cost model (why the saving is NOT just "skip some axis calls")
-----------------------------------------------------------------------
Every prose chunk's tag pass is ONE LLM call covering every axis at once
(`axial.tag.compose_multi_axis_tag_prompt`) -- there is no per-axis call to
skip. `votes=3` (`config/pipeline.yaml`'s `llm.votes_by_pass.tag`, DEC-31)
exists SOLELY to majority-vote `axial.tag.BLIND_AXES` (`claim_type`,
`theory_school`) -- the other axes already take the first draw's value
unvoted. Both blind axes graduate here, so a hybrid pipeline that hands them
to their classifiers has NOTHING left needing multi-draw voting: the
remaining LLM call (still required every chunk, because `empirical_scope`
never graduated) drops from 3 draws to 1. That is the dominant, structural,
measured saving this module counts -- not a per-axis token trim. This
module conservatively assumes the hybrid LLM call still asks about every
axis (no dynamic per-chunk prompt trimming for confidently-classified
`field`/`role_in_argument`) -- building that dynamic prompt is itself
production wiring, explicitly out of scope (see module docstring above);
the real achievable saving is therefore *at least* what this module reports,
likely somewhat more.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axial.codebook import Codebook
from axial.distill import classify as _classify_tfidf
from axial.distill import classify_embedding as _classify_embedding
from axial.distill.embed import DEFAULT_EMBEDDINGS_DIR
from axial.distill.staleness import resolve_current_pin
from axial.eval import corpus_pin as _corpus_pin
from axial.llm import LLMClient, TAG_PASS_NAME, estimate_cost
from axial.model_json import complete_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_vault_dir
from axial.query.reader import _iter_chunk_frontmatter, _require
from axial.schema import Schema
from axial.tag import (
    TAGGED_AXES,
    compose_multi_axis_tag_prompt,
    reject_degenerate_tag_values,
    _parse_and_validate_tags,
)

# The four axes DEC-37/38/39 measured as graduating (see module docstring).
# `empirical_scope` (#349) is deliberately absent -- it never graduated and
# has no classify manifest to read.
GRADUATED_AXES = ("claim_type", "theory_school", "field", "role_in_argument")
ALWAYS_LLM_AXES = ("empirical_scope",)

# The confidence-threshold operating point this eval reports the hybrid
# pipeline at. 0.6 is not re-tuned here -- it is the same point every 5d
# manifest's own prose already cites as "clears the teacher" for all four
# graduated axes (docs/eval/02-hybrid-tagging-distillation.md), so re-using
# it keeps this eval's headline number traceable to the inner layer's own
# citations rather than picking a fresh, unexplained operating point.
DEFAULT_OPERATING_THRESHOLD = 0.6

# DEC-39's own cited teacher-agreement figure for `role_in_argument`
# (docs/DECISIONS.md), used ONLY when the manifest's own freshly-computed
# `teacher_gold_agreement` is `None` (the real gold sheet carries no plain
# `role_in_argument` pre-fill column -- see `classify_embedding.py`'s module
# docstring). Recorded as `"cited"`, never `"measured"`, in this module's
# output -- never silently presented as a fresh measurement.
CITED_TEACHER_GOLD_AGREEMENT = {"role_in_argument": 0.533}

DEFAULT_MANIFEST_DIR = Path("data/distill")
DEFAULT_TAG_COST_PROBE_PATH = DEFAULT_MANIFEST_DIR / "tag_cost_probe_manifest.json"
DEFAULT_DRIFT_CHECK_PATH = DEFAULT_MANIFEST_DIR / "drift_check_manifest.json"
DEFAULT_VERDICT_PATH = DEFAULT_MANIFEST_DIR / "quality_per_dollar_manifest.json"

# The real production tag pass's own best-of-N (DEC-31, config/pipeline.yaml
# `llm.votes_by_pass.tag`) -- the cost probe mirrors this exactly so its
# baseline number is the real production cost, not a different config.
DEFAULT_COST_PROBE_VOTES = 3
DEFAULT_COST_PROBE_SAMPLE_SIZE = 10

# Bounded, cheap dry-run sample size for the drift-monitor spot check (see
# module docstring point 2) -- enough sampled chunks to see a gross
# agreement signal per axis without a live LLM sweep at "a few hundred"
# scale, which DEC-32 does not require for this eval.
DEFAULT_DRIFT_SAMPLE_SIZE = 25
DEFAULT_DRIFT_SEED = 353  # issue number; fixed only for reproducibility


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VerdictError(Exception):
    """Base class for all stage-5e outer-eval errors."""


class CorpusPinRequiredError(VerdictError):
    """Mirrors every other stage-5 module's own pin requirement (DEC-35)."""

    def __init__(self, cause: _corpus_pin.CorpusPinError):
        self.cause = cause
        super().__init__(
            f"the outer eval requires a corpus pin to record provenance against "
            f"({cause}); run `axial pin write <name>` first"
        )


class NoChunksToSampleError(VerdictError):
    """Raised when the vault holds no non-gold prose chunks to sample from."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = vault_dir
        super().__init__(f"no non-gold prose chunks found under {vault_dir} to sample")


class NoUsageReportedError(VerdictError):
    """Raised when the LLM client reports no usage for the tag pass after
    the probe's completions -- a misconfigured/stub client, never silently
    treated as a $0 cost."""

    def __init__(self):
        super().__init__(
            "no token usage reported for the tag pass after the cost probe's "
            "completions; is `client` a real, usage-tracking LLMClient?"
        )


# --- shared: sampling real vault chunks -------------------------------------


def _all_gold_chunk_ids(vault_dir: Path, gold_sheet_path: Path) -> set[str]:
    """The union of every gold-sheet chunk_id across every axis this module
    cares about -- one shared exclusion set, so the cost probe and drift
    check never accidentally sample a gold-reserved chunk (leakage-free,
    same convention `axial.distill.classify`/`classify_embedding` use)."""
    ids: set[str] = set()
    for axis in _classify_tfidf.AXES:
        chunk_ids, _records = _classify_tfidf._load_gold_sheet(gold_sheet_path, axis)
        ids |= chunk_ids
    for axis in _classify_embedding.AXES:
        chunk_ids, _records, _agreement = _classify_embedding._load_gold_labels(
            gold_sheet_path, axis
        )
        ids |= chunk_ids
    return ids


def _load_chunk_text_map(vault_dir: Path) -> dict[str, str]:
    """Every vault prose chunk's `chunk_id -> chunk_text`, the shared
    projection both the cost probe and the drift check sample from."""
    chunk_text_by_id: dict[str, str] = {}
    for path, frontmatter in _iter_chunk_frontmatter(vault_dir):
        chunk_id = _require(frontmatter, path, "chunk_id")
        chunk_text = _require(frontmatter, path, "chunk_text")
        chunk_text_by_id[chunk_id] = chunk_text
    return chunk_text_by_id


def sample_chunks(
    chunk_text_by_id: dict[str, str],
    excluded_chunk_ids: set[str],
    sample_size: int,
    seed: int,
) -> list[tuple[str, str]]:
    """`sample_size` `(chunk_id, chunk_text)` pairs, excluding
    `excluded_chunk_ids`, chosen deterministically from `seed` -- sorted
    before shuffling so the sample is reproducible regardless of filesystem
    iteration order (NTFS `iterdir` is not stable)."""
    candidates = sorted(
        (chunk_id, text)
        for chunk_id, text in chunk_text_by_id.items()
        if chunk_id not in excluded_chunk_ids
    )
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:sample_size]


# --- 1. tag-pass cost probe --------------------------------------------------


@dataclass(frozen=True)
class TagCostProbeResult:
    manifest_path: Path
    model: str
    sample_chunk_count: int
    votes: int
    total_cost_usd: float | None
    cost_per_chunk_usd_at_votes: float | None
    cost_per_chunk_usd_single_draw: float | None


def run_tag_cost_probe(
    client: LLMClient,
    schema: Schema,
    codebook: Codebook,
    *,
    vault_dir: Path | None = None,
    gold_sheet_path: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    evals_dir: Path | None = None,
    manifest_path: Path | None = None,
    sample_size: int = DEFAULT_COST_PROBE_SAMPLE_SIZE,
    votes: int = DEFAULT_COST_PROBE_VOTES,
    seed: int = DEFAULT_DRIFT_SEED,
    sample: list[tuple[str, str]] | None = None,
) -> TagCostProbeResult:
    """Fire `votes` real multi-axis tag-pass completions for `sample_size`
    real, non-gold vault chunks (the same prompt shape and `votes` count
    `axial.tag.run_tag` uses in production) and read the real dollar cost
    back off `client.usage_for_pass(TAG_PASS_NAME)` / `estimate_cost`. This
    is a LIVE probe -- `client` should be a real `LLMClient` for a
    meaningful number; a stub client with injected usage (issue #363's own
    seam) makes this deterministic for unit tests.

    `sample`, when given, replaces the vault-sampling step entirely (the
    seam tests use to pin an exact chunk set). Calls fire sequentially, not
    threaded like `run_tag`'s own per-chunk draws -- only wall-clock differs,
    never the dollar total, since cost is additive regardless of order.
    """
    if vault_dir is None:
        vault_dir = default_vault_dir(config_path)
    vault_dir = Path(vault_dir)
    if gold_sheet_path is None:
        gold_sheet_path = _classify_tfidf.DEFAULT_GOLD_SHEET_PATH
    gold_sheet_path = Path(gold_sheet_path)
    if manifest_path is None:
        manifest_path = DEFAULT_TAG_COST_PROBE_PATH
    manifest_path = Path(manifest_path)

    try:
        pin = resolve_current_pin(evals_dir)
    except _corpus_pin.CorpusPinError as exc:
        raise CorpusPinRequiredError(exc) from exc

    if sample is None:
        chunk_text_by_id = _load_chunk_text_map(vault_dir)
        excluded = _all_gold_chunk_ids(vault_dir, gold_sheet_path)
        sample = sample_chunks(chunk_text_by_id, excluded, sample_size, seed)
    if not sample:
        raise NoChunksToSampleError(vault_dir)

    axes_to_tag = [axis_name for axis_name in TAGGED_AXES if axis_name in schema.axes]

    for _chunk_id, chunk_text in sample:
        prompt = compose_multi_axis_tag_prompt(
            chunk_text, axes_to_tag, codebook, schema, polity_examples=schema.polity_examples
        )
        for _draw in range(votes):
            complete_json(
                client,
                prompt,
                pass_name=TAG_PASS_NAME,
                validate=lambda raw: reject_degenerate_tag_values(raw, axes_to_tag, schema),
            )

    usage = client.usage_for_pass(TAG_PASS_NAME)
    if not usage:
        raise NoUsageReportedError()
    model = client.model_for_pass(TAG_PASS_NAME)
    total_cost = estimate_cost(model, usage["prompt_tokens"], usage["completion_tokens"])

    sample_chunk_count = len(sample)
    cost_per_chunk_at_votes = total_cost / sample_chunk_count if total_cost is not None else None
    cost_per_chunk_single_draw = (
        cost_per_chunk_at_votes / votes if cost_per_chunk_at_votes is not None else None
    )

    manifest = {
        "corpus_pin_id": pin["corpus_pin_id"],
        "vault_snapshot_hash": pin["vault_snapshot_hash"],
        "model": model,
        "axes_tagged": axes_to_tag,
        "sample_chunk_count": sample_chunk_count,
        "sampled_chunk_ids": [chunk_id for chunk_id, _text in sample],
        "votes": votes,
        "total_prompt_tokens": usage["prompt_tokens"],
        "total_completion_tokens": usage["completion_tokens"],
        "total_cost_usd": total_cost,
        "cost_per_chunk_usd_at_votes": cost_per_chunk_at_votes,
        "cost_per_chunk_usd_single_draw": cost_per_chunk_single_draw,
        "measured_at": _now_iso(),
        "note": (
            "live-measured against the real deepseek/deepseek-v4-flash "
            "production_low model (issue #363's price table); "
            "cost_per_chunk_usd_single_draw is the real total divided by "
            "sample_chunk_count*votes, i.e. the real average per-draw cost, "
            "not an assumed 1/votes split."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return TagCostProbeResult(
        manifest_path=manifest_path,
        model=model,
        sample_chunk_count=sample_chunk_count,
        votes=votes,
        total_cost_usd=total_cost,
        cost_per_chunk_usd_at_votes=cost_per_chunk_at_votes,
        cost_per_chunk_usd_single_draw=cost_per_chunk_single_draw,
    )


# --- 2. drift-monitor dry run -------------------------------------------------


def _train_tfidf_predict_fn(axis: str, vault_dir: Path, gold_chunk_ids: set[str]):
    records = _classify_tfidf._load_vault_axis_records(vault_dir, axis)
    training = [record for record in records if record[0] not in gold_chunk_ids and record[2]]
    training, _dropped = _classify_tfidf._drop_rare_classes(
        training, _classify_tfidf.DEFAULT_MIN_CLASS_COUNT
    )
    return _classify_tfidf._default_train_fn(
        [text for _cid, text, _label in training], [label for _cid, _text, label in training]
    )


def _train_embedding_predict_fn(
    axis: str, embeddings_dir: Path, gold_chunk_ids: set[str]
) -> tuple[Any, dict[str, list[float]]]:
    axis_column = _classify_embedding.AXIS_METADATA_COLUMNS[axis]
    lookup = _classify_embedding._load_embedding_lookup(embeddings_dir, axis_column)
    training = [
        (chunk_id, vector, label)
        for chunk_id, (vector, label) in lookup.items()
        if chunk_id not in gold_chunk_ids and label
    ]
    training, _dropped = _classify_embedding._drop_rare_classes(
        training, _classify_embedding.DEFAULT_MIN_CLASS_COUNT
    )
    predict_fn = _classify_embedding._default_train_fn(
        [vector for _cid, vector, _label in training], [label for _cid, _vector, label in training]
    )
    vectors_by_id = {chunk_id: vector for chunk_id, (vector, _label) in lookup.items()}
    return predict_fn, vectors_by_id


@dataclass(frozen=True)
class DriftCheckResult:
    manifest_path: Path
    sample_size: int
    per_axis_agreement: dict[str, float | None]


def run_drift_check(
    client: LLMClient,
    schema: Schema,
    codebook: Codebook,
    *,
    vault_dir: Path | None = None,
    embeddings_dir: Path | None = None,
    gold_sheet_path: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    evals_dir: Path | None = None,
    manifest_path: Path | None = None,
    sample_size: int = DEFAULT_DRIFT_SAMPLE_SIZE,
    seed: int = DEFAULT_DRIFT_SEED,
    sample: list[tuple[str, str]] | None = None,
    classifier_predictions: dict[str, dict[str, str]] | None = None,
) -> DriftCheckResult:
    """The drift-monitor dry run (module docstring point 2): each graduated
    axis's classifier, trained exactly as `axial.distill.classify`/
    `classify_embedding` train it (gold excluded), predicts a small sample
    of already-tagged, non-gold corpus chunks; the LLM freshly re-tags the
    SAME sample in one multi-axis call per chunk (votes=1 -- a dry run, not
    production, needs no best-of-N); the two are compared per axis.

    This is deliberately NOT a train/test-split leakage check (5d's gold-set
    evaluation already covers that) -- it asks a different question: does
    the classifier, trained on the corpus's historical tags, still agree
    with what the LLM says TODAY. A sampled chunk may well have been part of
    that classifier's own training set; that is expected, not a bug (module
    docstring).

    A per-chunk LLM failure (a malformed response, an out-of-vocabulary
    miss) is logged to stderr and excluded from that axis's agreement
    denominator rather than aborting the whole dry run -- bounded, best-
    effort, matching the "dry run" framing.

    `classifier_predictions` (`chunk_id -> {axis: predicted_label}`), when
    given, replaces training four real classifiers and reading their
    features entirely -- the seam this module's own inner unit tests use to
    exercise the sampling/LLM-comparison/manifest logic without a real
    vault, embeddings store, or corpus of training tags.
    """
    if vault_dir is None:
        vault_dir = default_vault_dir(config_path)
    vault_dir = Path(vault_dir)
    if embeddings_dir is None:
        embeddings_dir = DEFAULT_EMBEDDINGS_DIR
    embeddings_dir = Path(embeddings_dir)
    if gold_sheet_path is None:
        gold_sheet_path = _classify_tfidf.DEFAULT_GOLD_SHEET_PATH
    gold_sheet_path = Path(gold_sheet_path)
    if manifest_path is None:
        manifest_path = DEFAULT_DRIFT_CHECK_PATH
    manifest_path = Path(manifest_path)

    try:
        pin = resolve_current_pin(evals_dir)
    except _corpus_pin.CorpusPinError as exc:
        raise CorpusPinRequiredError(exc) from exc

    gold_chunk_ids = _all_gold_chunk_ids(vault_dir, gold_sheet_path)

    if classifier_predictions is None:
        claim_predict = _train_tfidf_predict_fn("claim_type", vault_dir, gold_chunk_ids)
        theory_predict = _train_tfidf_predict_fn("theory_school", vault_dir, gold_chunk_ids)
        field_predict, field_vectors = _train_embedding_predict_fn(
            "field", embeddings_dir, gold_chunk_ids
        )
        role_predict, role_vectors = _train_embedding_predict_fn(
            "role_in_argument", embeddings_dir, gold_chunk_ids
        )

        if sample is None:
            chunk_text_by_id = _load_chunk_text_map(vault_dir)
            sampleable = {
                chunk_id: text
                for chunk_id, text in chunk_text_by_id.items()
                if chunk_id in field_vectors and chunk_id in role_vectors
            }
            sample = sample_chunks(sampleable, gold_chunk_ids, sample_size, seed)

        def _predict_for(chunk_id: str, chunk_text: str) -> dict[str, str]:
            return {
                "claim_type": claim_predict([chunk_text])[0][0],
                "theory_school": theory_predict([chunk_text])[0][0],
                "field": field_predict([field_vectors[chunk_id]])[0][0],
                "role_in_argument": role_predict([role_vectors[chunk_id]])[0][0],
            }
    else:
        if sample is None:
            chunk_text_by_id = _load_chunk_text_map(vault_dir)
            sampleable = {
                chunk_id: text
                for chunk_id, text in chunk_text_by_id.items()
                if chunk_id in classifier_predictions
            }
            sample = sample_chunks(sampleable, gold_chunk_ids, sample_size, seed)

        def _predict_for(chunk_id: str, _chunk_text: str) -> dict[str, str]:
            return classifier_predictions[chunk_id]

    if not sample:
        raise NoChunksToSampleError(vault_dir)

    axes_to_tag = [axis_name for axis_name in TAGGED_AXES if axis_name in GRADUATED_AXES]

    agreements: dict[str, list[bool]] = {axis: [] for axis in GRADUATED_AXES}
    llm_error_count = 0
    for chunk_id, chunk_text in sample:
        predicted = _predict_for(chunk_id, chunk_text)

        prompt = compose_multi_axis_tag_prompt(
            chunk_text, axes_to_tag, codebook, schema, polity_examples=schema.polity_examples
        )
        try:
            raw_response = complete_json(
                client,
                prompt,
                pass_name=TAG_PASS_NAME,
                validate=lambda raw: reject_degenerate_tag_values(raw, axes_to_tag, schema),
            )
            values, multi_value_axes, _many_valued, _polity = _parse_and_validate_tags(
                raw_response, axes_to_tag, schema
            )
        except Exception as exc:  # dry run: best-effort, never fatal for one chunk
            print(f"drift-check: LLM error on chunk {chunk_id}: {exc}", file=sys.stderr)
            llm_error_count += 1
            continue

        fresh = {
            "claim_type": multi_value_axes.get("claim_type", {}).get("primary"),
            "theory_school": multi_value_axes.get("theory_school", {}).get("primary"),
            "field": multi_value_axes.get("field", {}).get("primary"),
            "role_in_argument": values.get("role_in_argument"),
        }
        for axis in GRADUATED_AXES:
            if fresh[axis] is not None:
                agreements[axis].append(predicted[axis] == fresh[axis])

    per_axis_agreement: dict[str, float | None] = {}
    per_axis_compared: dict[str, int] = {}
    for axis in GRADUATED_AXES:
        compared = agreements[axis]
        per_axis_compared[axis] = len(compared)
        per_axis_agreement[axis] = (sum(compared) / len(compared)) if compared else None

    manifest = {
        "corpus_pin_id": pin["corpus_pin_id"],
        "vault_snapshot_hash": pin["vault_snapshot_hash"],
        "sample_size": len(sample),
        "seed": seed,
        "sampled_chunk_ids": [chunk_id for chunk_id, _text in sample],
        "llm_error_count": llm_error_count,
        "per_axis_agreement": per_axis_agreement,
        "per_axis_compared_count": per_axis_compared,
        "measured_at": _now_iso(),
        "note": (
            "classifier prediction vs a FRESH single-draw LLM tag on the "
            "same chunk (votes=1, not production's votes=3) -- a drift "
            "dry run (DEC-32/#296), not a leakage check: the classifier may "
            "have trained on some of these chunks' historical tags."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return DriftCheckResult(
        manifest_path=manifest_path,
        sample_size=len(sample),
        per_axis_agreement=per_axis_agreement,
    )


# --- 3. the verdict -----------------------------------------------------------


def _resolve_operating_point(manifest: dict[str, Any], threshold: float) -> dict[str, Any]:
    for entry in manifest["thresholds"]:
        if entry["threshold"] == threshold:
            return entry
    available = [entry["threshold"] for entry in manifest["thresholds"]]
    raise VerdictError(
        f"threshold {threshold} not found in manifest {manifest.get('axis')!r}'s own "
        f"threshold sweep {available!r}"
    )


def compute_axis_verdict(axis: str, manifest: dict[str, Any], threshold: float) -> dict[str, Any]:
    """One axis's hybrid-vs-baseline comparison at `threshold`:
    `hybrid_accuracy = coverage * accuracy_on_covered + (1 - coverage) *
    teacher_gold_agreement` -- the confident subset uses the classifier, the
    low-confidence tail falls back to the LLM (assumed to perform at the
    LLM's own overall gold agreement on that tail -- a simplifying,
    explicitly-flagged assumption; the tail is a minority of chunks by
    construction). `teacher_gold_agreement` is the manifest's own freshly-
    measured figure when present, else `CITED_TEACHER_GOLD_AGREEMENT`'s
    decision-log citation for `role_in_argument` -- recorded as `"cited"`,
    never `"measured"`."""
    point = _resolve_operating_point(manifest, threshold)
    coverage = point["coverage"]
    accuracy_on_covered = point["accuracy_on_covered"]

    teacher = manifest.get("teacher_gold_agreement")
    source = "measured" if teacher is not None else None
    if teacher is None and axis in CITED_TEACHER_GOLD_AGREEMENT:
        teacher = CITED_TEACHER_GOLD_AGREEMENT[axis]
        source = "cited"

    hybrid_accuracy = None
    if accuracy_on_covered is not None and teacher is not None:
        hybrid_accuracy = coverage * accuracy_on_covered + (1 - coverage) * teacher

    meets_or_beats_teacher = (
        hybrid_accuracy >= teacher if hybrid_accuracy is not None and teacher is not None else None
    )

    return {
        "axis": axis,
        "threshold": threshold,
        "coverage": coverage,
        "accuracy_on_covered": accuracy_on_covered,
        "teacher_gold_agreement": teacher,
        "teacher_gold_agreement_source": source,
        "hybrid_accuracy": hybrid_accuracy,
        "meets_or_beats_teacher": meets_or_beats_teacher,
    }


@dataclass(frozen=True)
class VerdictResult:
    manifest_path: Path
    axis_verdicts: dict[str, dict[str, Any]]
    overall_verdict: str


def run_verdict(
    *,
    manifest_dir: Path = DEFAULT_MANIFEST_DIR,
    threshold: float = DEFAULT_OPERATING_THRESHOLD,
    cost_probe_path: Path | None = None,
    drift_check_path: Path | None = None,
    embedding_manifest_path: Path | None = None,
    output_path: Path | None = None,
    evals_dir: Path | None = None,
) -> VerdictResult:
    """Combine the four graduated axes' already-shipped 5d manifests, the
    tag-pass cost probe, and the drift check into one verdict manifest.
    Pure/deterministic given those JSON inputs on disk -- reads, never
    trains, never calls the LLM.

    Raises `VerdictError` when a graduated axis's own manifest is missing
    (run `axial distill classify <axis>` first) -- there is nothing to
    verdict without it. The cost probe and drift check are read when present
    and reported as `null`/absent otherwise, so this can still run (with an
    honestly incomplete cost section) before either live probe has been run.
    """
    manifest_dir = Path(manifest_dir)
    if cost_probe_path is None:
        cost_probe_path = DEFAULT_TAG_COST_PROBE_PATH
    cost_probe_path = Path(cost_probe_path)
    if drift_check_path is None:
        drift_check_path = DEFAULT_DRIFT_CHECK_PATH
    drift_check_path = Path(drift_check_path)
    if embedding_manifest_path is None:
        embedding_manifest_path = manifest_dir / "embedding_manifest.json"
    embedding_manifest_path = Path(embedding_manifest_path)
    if output_path is None:
        output_path = DEFAULT_VERDICT_PATH
    output_path = Path(output_path)

    try:
        pin = resolve_current_pin(evals_dir)
    except _corpus_pin.CorpusPinError as exc:
        raise CorpusPinRequiredError(exc) from exc

    axis_verdicts: dict[str, dict[str, Any]] = {}
    for axis in GRADUATED_AXES:
        axis_manifest_path = manifest_dir / f"classify_{axis}_manifest.json"
        if not axis_manifest_path.is_file():
            raise VerdictError(
                f"no classify manifest for graduated axis {axis!r} at "
                f"{axis_manifest_path}; run `axial distill classify {axis}` first"
            )
        axis_manifest = json.loads(axis_manifest_path.read_text(encoding="utf-8"))
        axis_verdicts[axis] = compute_axis_verdict(axis, axis_manifest, threshold)
    axis_verdicts["empirical_scope"] = {
        "axis": "empirical_scope",
        "graduated": False,
        "note": (
            "#349: neither embeddings nor TF-IDF beat the teacher for this "
            "axis; always LLM in both the baseline and the hybrid pipeline, "
            "so it contributes identically to both and does not move the "
            "quality comparison -- excluded from the aggregate accuracy "
            "below for that reason, not omitted from this report."
        ),
    }

    corpus_chunk_count = None
    if embedding_manifest_path.is_file():
        embedding_manifest = json.loads(embedding_manifest_path.read_text(encoding="utf-8"))
        corpus_chunk_count = embedding_manifest.get("chunk_count")

    cost_probe = None
    if cost_probe_path.is_file():
        cost_probe = json.loads(cost_probe_path.read_text(encoding="utf-8"))

    drift_check = None
    if drift_check_path.is_file():
        drift_check = json.loads(drift_check_path.read_text(encoding="utf-8"))

    cost_section: dict[str, Any] = {"measured": cost_probe is not None}
    if cost_probe is not None and corpus_chunk_count is not None:
        cost_per_chunk_baseline = cost_probe["cost_per_chunk_usd_at_votes"]
        cost_per_chunk_hybrid = cost_probe["cost_per_chunk_usd_single_draw"]
        overall_baseline = (
            cost_per_chunk_baseline * corpus_chunk_count
            if cost_per_chunk_baseline is not None
            else None
        )
        overall_hybrid = (
            cost_per_chunk_hybrid * corpus_chunk_count
            if cost_per_chunk_hybrid is not None
            else None
        )
        savings_fraction = (
            1 - overall_hybrid / overall_baseline
            if overall_baseline not in (None, 0) and overall_hybrid is not None
            else None
        )
        cost_section.update(
            {
                "model": cost_probe["model"],
                "corpus_chunk_count": corpus_chunk_count,
                "cost_per_chunk_usd_baseline_votes3": cost_per_chunk_baseline,
                "cost_per_chunk_usd_hybrid_votes1": cost_per_chunk_hybrid,
                "overall_baseline_cost_usd": overall_baseline,
                "overall_hybrid_cost_usd": overall_hybrid,
                "dollar_savings_fraction": savings_fraction,
                "basis": (
                    "votes drop from 3 to 1: both BLIND_AXES (claim_type, "
                    "theory_school) -- the only reason votes=3 exists -- "
                    "graduate off the LLM. The remaining LLM call (still "
                    "required every chunk for empirical_scope) needs no "
                    "further voting. Conservative: assumes the hybrid call "
                    "still asks about every axis (no prompt trimming)."
                ),
            }
        )

    graduated_hybrid = [
        axis_verdicts[axis]["hybrid_accuracy"]
        for axis in GRADUATED_AXES
        if axis_verdicts[axis]["hybrid_accuracy"] is not None
    ]
    graduated_teacher = [
        axis_verdicts[axis]["teacher_gold_agreement"]
        for axis in GRADUATED_AXES
        if axis_verdicts[axis]["teacher_gold_agreement"] is not None
    ]
    pipeline_quality = {
        "graduated_axes_averaged": GRADUATED_AXES,
        "hybrid_mean_accuracy": (
            sum(graduated_hybrid) / len(graduated_hybrid) if graduated_hybrid else None
        ),
        "baseline_mean_accuracy": (
            sum(graduated_teacher) / len(graduated_teacher) if graduated_teacher else None
        ),
    }
    if pipeline_quality["hybrid_mean_accuracy"] is not None and cost_section.get(
        "overall_hybrid_cost_usd"
    ):
        pipeline_quality["quality_per_dollar_hybrid"] = (
            pipeline_quality["hybrid_mean_accuracy"] / cost_section["overall_hybrid_cost_usd"]
        )
    if pipeline_quality["baseline_mean_accuracy"] is not None and cost_section.get(
        "overall_baseline_cost_usd"
    ):
        pipeline_quality["quality_per_dollar_baseline"] = (
            pipeline_quality["baseline_mean_accuracy"] / cost_section["overall_baseline_cost_usd"]
        )
    if (
        "quality_per_dollar_hybrid" in pipeline_quality
        and "quality_per_dollar_baseline" in pipeline_quality
    ):
        pipeline_quality["quality_per_dollar_ratio"] = (
            pipeline_quality["quality_per_dollar_hybrid"]
            / pipeline_quality["quality_per_dollar_baseline"]
        )

    per_axis_calls = {}
    for axis in GRADUATED_AXES:
        verdict = axis_verdicts[axis]
        if verdict["meets_or_beats_teacher"] is True:
            per_axis_calls[axis] = "graduate"
        elif verdict["meets_or_beats_teacher"] is False:
            per_axis_calls[axis] = "stay-llm"
        else:
            per_axis_calls[axis] = "unmeasured"
    per_axis_calls["empirical_scope"] = "stay-llm (#349, never graduated)"

    quality_holds = all(
        call == "graduate" or call.startswith("stay-llm")
        for axis, call in per_axis_calls.items()
        if axis != "empirical_scope"
    )
    any_graduates = any(call == "graduate" for call in per_axis_calls.values())
    if any_graduates and cost_section.get("dollar_savings_fraction"):
        overall = "hybrid" if quality_holds else "mixed"
    elif any_graduates:
        overall = "mixed (quality measured, cost not measured -- run the cost probe)"
    else:
        overall = "stay-llm"

    manifest = {
        "corpus_pin_id": pin["corpus_pin_id"],
        "vault_snapshot_hash": pin["vault_snapshot_hash"],
        "threshold": threshold,
        "axis_verdicts": axis_verdicts,
        "per_axis_calls": per_axis_calls,
        "cost": cost_section,
        "pipeline_quality": pipeline_quality,
        "drift_check": drift_check,
        "overall_verdict": overall,
        "measured_at": _now_iso(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return VerdictResult(
        manifest_path=output_path, axis_verdicts=axis_verdicts, overall_verdict=overall
    )
