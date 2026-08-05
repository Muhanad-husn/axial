"""Issue #677 slice A: real-corpus validation, zero model calls.

Run from D:\\axial (main checkout, real data) with the WORKTREE's code on
the interpreter path (`uv run --project <worktree>`), so the branch's
incremental-assignment logic runs against the real 34-book corpus already on
disk. Never touches `data/names/embeddings.lance` or any other persisted
artifact -- read-only over the real corpus, everything else is computed
in-memory and only the report is written, under `data/logs/`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import lancedb

from axial.merge_names import build_batches, build_evidence_index
from axial.names import (
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_PCA_COMPONENTS,
    NOISE_LABEL,
    _approximate_predict,
    _cluster_floors,
    _cluster_reduced,
    _fit_cluster_reduced,
    _fit_reduce_vectors,
    _transform_vectors,
    build_inventory,
    collect_occurrences,
    load_answer_records,
    load_back_matter_sections,
)

DATA_DIR = Path("data")
ANSWERS_DIR = DATA_DIR / "answers"
TREES_DIR = DATA_DIR / "trees"
EMBEDDINGS_DIR = DATA_DIR / "names" / "embeddings.lance"

NEW_SOURCES = {
    "gelvin-1998-f7e1df5f9b1d",
    "hinnebusch-1990-ac29981e616e",
    "wedeen-2019-3ae1f7af318d",
}

LOG_DIR = DATA_DIR / "logs" / "2026-08-05-677-incremental-fit"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# A re-run must never truncate a previous run's own record in place (the
# same `brief_id`-overwrite lesson): if `run.jsonl` already exists, it is a
# PRIOR run's log, so it is preserved as `run-N.jsonl` before this run opens
# a fresh `run.jsonl` of its own.
if (LOG_DIR / "run.jsonl").exists():
    n = 1
    while (LOG_DIR / f"run-{n}.jsonl").exists():
        n += 1
    (LOG_DIR / "run.jsonl").rename(LOG_DIR / f"run-{n}.jsonl")

run_log = (LOG_DIR / "run.jsonl").open("w", encoding="utf-8")
console_log = (LOG_DIR / "console.log").open("w", encoding="utf-8")


def log(event: str, **fields) -> None:
    record = {"event": event, "ts": time.time(), **fields}
    run_log.write(json.dumps(record, ensure_ascii=False) + "\n")
    run_log.flush()
    line = f"{event}: " + ", ".join(f"{k}={v}" for k, v in fields.items())
    print(line)
    console_log.write(line + "\n")
    console_log.flush()


def build_and_key(labels, surface_forms, kinds, chunk_ids_by_surface):
    evidence = build_evidence_index(chunk_ids_by_surface)
    batches = build_batches(labels, surface_forms, kinds, evidence)
    return batches


def batch_keys(labels, surface_forms, kinds, chunk_ids_by_surface):
    batches = build_and_key(labels, surface_forms, kinds, chunk_ids_by_surface)
    return {b.key for b in batches}, len(batches)


def main() -> None:
    all_sources = {p.stem for p in ANSWERS_DIR.glob("*.jsonl")}
    old_sources = all_sources - NEW_SOURCES
    log("sources", total=len(all_sources), old=len(old_sources), new=len(NEW_SOURCES))
    assert len(old_sources) == 31 and len(NEW_SOURCES) == 3, "expected #623's 31-old/3-new split"

    t0 = time.time()
    all_records = load_answer_records(ANSWERS_DIR)
    old_records = [r for r in all_records if r.get("source_id") in old_sources]
    back_matter = load_back_matter_sections(TREES_DIR)
    log("records_loaded", all=len(all_records), old=len(old_records), elapsed=time.time() - t0)

    old_entries = build_inventory(list(collect_occurrences(old_records, back_matter)))
    full_entries = build_inventory(list(collect_occurrences(all_records, back_matter)))
    log("inventories_built", old_entries=len(old_entries), full_entries=len(full_entries))

    db = lancedb.connect(EMBEDDINGS_DIR)
    all_rows = db.open_table("names").to_arrow().to_pylist()
    vector_by_surface = {row["surface_form"]: row["vector"] for row in all_rows}
    log("persisted_vectors_loaded", rows=len(all_rows))

    missing = [e.surface_form for e in old_entries if e.surface_form not in vector_by_surface]
    missing_full = [e.surface_form for e in full_entries if e.surface_form not in vector_by_surface]
    log("vector_coverage", missing_for_old=len(missing), missing_for_full=len(missing_full))
    old_entries = [e for e in old_entries if e.surface_form in vector_by_surface]
    full_entries = [e for e in full_entries if e.surface_form in vector_by_surface]

    # --- Step 1: full fit over the 31-book subset -----------------------
    t0 = time.time()
    old_vectors = [vector_by_surface[e.surface_form] for e in old_entries]
    reduced_old, scaler, pca = _fit_reduce_vectors(
        old_vectors, pca_components=DEFAULT_PCA_COMPONENTS
    )
    clusterer_old = _fit_cluster_reduced(
        reduced_old, DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES, prediction_data=True
    )
    old_labels = [int(label) for label in clusterer_old.labels_]
    t_fit_31 = time.time() - t0
    log("fit_31_books", entries=len(old_entries), elapsed=t_fit_31)

    kinds_old = {e.surface_form: e.kind for e in old_entries}
    chunk_ids_old = {e.surface_form: e.chunk_ids for e in old_entries}
    baseline_batches = build_and_key(
        old_labels, [e.surface_form for e in old_entries], kinds_old, chunk_ids_old
    )
    baseline_keys = {b.key for b in baseline_batches}
    baseline_batch_count = len(baseline_batches)
    baseline_batches_by_label: dict[int, list] = {}
    for batch in baseline_batches:
        baseline_batches_by_label.setdefault(batch.cluster_label, []).append(batch)
    log("baseline_batches", count=baseline_batch_count, unique_keys=len(baseline_keys))

    # --- Step 2: incremental assignment of the 3-book delta -------------
    old_by_surface = {e.surface_form: label for e, label in zip(old_entries, old_labels)}
    known_indices = [i for i, e in enumerate(full_entries) if e.surface_form in old_by_surface]
    new_indices = [i for i, e in enumerate(full_entries) if e.surface_form not in old_by_surface]
    log("delta", known=len(known_indices), new=len(new_indices))

    vectors_full = [vector_by_surface[e.surface_form] for e in full_entries]
    labels_incremental = [NOISE_LABEL] * len(full_entries)
    for i in known_indices:
        labels_incremental[i] = old_by_surface[full_entries[i].surface_form]

    t0 = time.time()
    new_vectors = [vectors_full[i] for i in new_indices]
    reduced_new = _transform_vectors(new_vectors, scaler, pca)
    predicted_labels, strengths = _approximate_predict(clusterer_old, reduced_new)
    floors = _cluster_floors(clusterer_old)
    residue_positions = {
        pos
        for pos, (predicted, strength) in enumerate(zip(predicted_labels, strengths))
        if predicted == NOISE_LABEL or strength < floors.get(predicted, 1.0)
    }
    for pos, predicted in enumerate(predicted_labels):
        if pos not in residue_positions:
            labels_incremental[new_indices[pos]] = predicted
    t_predict = time.time() - t0
    log(
        "approximate_predict",
        new=len(new_indices),
        accepted=len(new_indices) - len(residue_positions),
        residue=len(residue_positions),
        elapsed=t_predict,
    )

    existing_max_label = max(
        (label for label in old_labels if label != NOISE_LABEL), default=NOISE_LABEL
    )
    t0 = time.time()
    if residue_positions:
        ordered_residue = sorted(residue_positions)
        residue_reduced = reduced_new[ordered_residue]
        residue_labels = _cluster_reduced(
            residue_reduced, DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES
        )
        offset = existing_max_label + 1
        for pos, raw_label in zip(ordered_residue, residue_labels):
            idx = new_indices[pos]
            labels_incremental[idx] = (
                NOISE_LABEL if raw_label == NOISE_LABEL else offset + raw_label
            )
    t_residue_fit = time.time() - t0
    residue_cluster_count = len(
        {label for label in labels_incremental if label != NOISE_LABEL}
        - set(old_by_surface.values())
    )
    log("residue_refit", elapsed=t_residue_fit, residue_cluster_count=residue_cluster_count)

    kinds_full = {e.surface_form: e.kind for e in full_entries}
    chunk_ids_full = {e.surface_form: e.chunk_ids for e in full_entries}
    incremental_batches = build_and_key(
        labels_incremental, [e.surface_form for e in full_entries], kinds_full, chunk_ids_full
    )
    incremental_keys = {b.key for b in incremental_batches}
    incremental_batch_count = len(incremental_batches)
    log("incremental_batches", count=incremental_batch_count, unique_keys=len(incremental_keys))

    identical = baseline_keys & incremental_keys
    new_only = incremental_keys - baseline_keys
    disturbed = baseline_keys - incremental_keys
    log(
        "comparison_incremental_vs_baseline",
        baseline=len(baseline_keys),
        identical_free=len(identical),
        new_batches=len(new_only),
        disturbed_old_batches=len(disturbed),
    )

    # --- Why did 580 accepted new entries disturb 1,355 old batches? ----
    # A disturbed baseline batch's own cluster (`cluster_label`) is either
    # (a) a cluster an accepted new entry actually joined ("grew"), (b) a
    # cluster whose membership is unchanged but a MEMBER's own evidence
    # suffix changed (issue #449: `render_member` appends "(in <source
    # ids>)" -- a known surface picking up an occurrence in one of the 3 new
    # books changes that suffix even with no new member), or (c) split-
    # amplification: `_split_into_batches` bin-packs a cluster into as few
    # batches as fit `member_char_budget`, so one member joining or one
    # member's evidence line growing can shift every later slice's contents.
    accepted_labels = {
        predicted for pos, predicted in enumerate(predicted_labels) if pos not in residue_positions
    }
    grew_labels = accepted_labels  # exactly the clusters an accepted entry joined

    evidence_changed_surfaces = {
        surface_form
        for surface_form in old_by_surface
        if build_evidence_index({surface_form: chunk_ids_old[surface_form]}).get(surface_form)
        != build_evidence_index({surface_form: chunk_ids_full[surface_form]}).get(surface_form)
    }
    log("evidence_changed_known_surfaces", count=len(evidence_changed_surfaces))

    disturbed_batches = [batch for batch in baseline_batches if batch.key in disturbed]
    grew_disturbance = 0
    evidence_only_disturbance = 0
    unexplained_disturbance = 0
    split_amplified_disturbance = 0  # grew AND that label had >1 baseline batch
    for batch in disturbed_batches:
        label = batch.cluster_label
        grew = label in grew_labels
        evidence_touched = any(member in evidence_changed_surfaces for member in batch.members)
        if grew:
            grew_disturbance += 1
            if len(baseline_batches_by_label.get(label, [])) > 1:
                split_amplified_disturbance += 1
        elif evidence_touched:
            evidence_only_disturbance += 1
        else:
            unexplained_disturbance += 1
    log(
        "disturbance_breakdown",
        total=len(disturbed_batches),
        cluster_grew=grew_disturbance,
        split_amplified_of_grew=split_amplified_disturbance,
        evidence_only=evidence_only_disturbance,
        unexplained=unexplained_disturbance,
    )

    # --- Step 3: a full re-fit over all 34 books, for the drift number --
    t0 = time.time()
    reduced_full, _scaler_full, _pca_full = _fit_reduce_vectors(
        vectors_full, pca_components=DEFAULT_PCA_COMPONENTS
    )
    clusterer_full = _fit_cluster_reduced(
        reduced_full, DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES, prediction_data=True
    )
    labels_full_fresh = [int(label) for label in clusterer_full.labels_]
    t_fit_34 = time.time() - t0
    log("fresh_fit_34_books", entries=len(full_entries), elapsed=t_fit_34)

    fresh_keys, fresh_batch_count = batch_keys(
        labels_full_fresh, [e.surface_form for e in full_entries], kinds_full, chunk_ids_full
    )
    log("fresh_batches", count=fresh_batch_count, unique_keys=len(fresh_keys))

    drift_identical = incremental_keys & fresh_keys
    drift_incremental_only = incremental_keys - fresh_keys
    drift_fresh_only = fresh_keys - incremental_keys
    log(
        "comparison_incremental_vs_fresh_34",
        identical=len(drift_identical),
        incremental_only=len(drift_incremental_only),
        fresh_only=len(drift_fresh_only),
    )

    summary_lines = [
        "# Issue #677 slice A: real-corpus validation",
        "",
        f"31-book subset: {len(old_entries)} entries, {baseline_batch_count} batches "
        f"({len(baseline_keys)} unique keys), fit in {t_fit_31:.1f}s",
        f"34-book (delta = 3 books) full inventory: {len(full_entries)} entries "
        f"({len(known_indices)} known, {len(new_indices)} new)",
        f"approximate_predict over the {len(new_indices)} new entries: "
        f"{len(new_indices) - len(residue_positions)} accepted "
        f"({(len(new_indices) - len(residue_positions)) / len(new_indices):.1%}), "
        f"{len(residue_positions)} residue ({len(residue_positions) / len(new_indices):.1%}) "
        f"({t_predict:.1f}s)",
        f"residue re-fit: {residue_cluster_count} new cluster(s) minted from "
        f"{len(residue_positions)} residue entries, offset above label {existing_max_label} "
        f"({t_residue_fit:.1f}s) -- {residue_cluster_count} distinct new clusters from one book-delta "
        "reads as new books genuinely bringing new names, not the floor being over-strict: a strict "
        "floor swallowing real new names into an existing cluster would show up as noise or as one or "
        "two oversized clusters, not 847 separately-shaped ones.",
        "",
        "## Incremental vs the 31-book baseline",
        f"- byte-identical batches (free, no re-ask): {len(identical)} of {len(baseline_keys)} "
        f"baseline batches ({len(identical) / len(baseline_keys):.1%})",
        f"- new batches (the 3-book delta's own work): {len(new_only)}",
        f"- disturbed old batches (baseline batches that no longer exist): {len(disturbed)} "
        f"({len(disturbed) / len(baseline_keys):.1%})",
        "- compare to #623's own baseline: 5,143 re-asks of 13,900 batches (37.0%) under the "
        "OLD global-refit build",
        "",
        "### Why 580 accepted new entries disturbed 1,355 old batches",
        f"- {evidence_only_disturbance} of {len(disturbed_batches)} disturbed batches have an "
        "UNCHANGED member set -- a member already in the cluster picked up a new-book occurrence, "
        "which changed its `(in <source ids>)` evidence suffix and so the batch's rendered content, "
        "with no accepted new entry involved at all.",
        f"- {grew_disturbance} of {len(disturbed_batches)} disturbed batches belong to a cluster an "
        f"accepted new entry actually joined ({split_amplified_disturbance} of those {grew_disturbance} "
        "belong to a cluster that baseline had already split into more than one batch -- one new "
        "member's char-budget bin-packing shifting every later slice, not just the one it landed in).",
        f"- {unexplained_disturbance} disturbed batches fit neither bucket above.",
        "",
        "## Incremental vs a fresh full re-fit over all 34 books -- the drift, stated honestly",
        f"- fresh 34-book fit: {fresh_batch_count} batches ({len(fresh_keys)} unique keys), "
        f"{t_fit_34:.1f}s",
        f"- incremental agrees with a fresh fit on {len(drift_identical)} of {len(fresh_keys)} "
        f"batches ({len(drift_identical) / len(fresh_keys):.1%}). This is NOT free reuse of a real "
        "decision -- most of these were never asked about under either fit -- it is how much the two "
        "PARTITIONS agree. The other {:.1%} is real drift: incremental assignment is an "
        "approximation of what a fresh fit would say, not a substitute for one.".format(
            1 - len(drift_identical) / len(fresh_keys)
        ),
        f"- incremental-only ({len(drift_incremental_only)}): batches incremental kept stable that a "
        "fresh fit would have reshuffled -- this is the whole POINT of the mechanism.",
        f"- fresh-only ({len(drift_fresh_only)}): batches only a fresh fit produces -- what "
        "`--recluster` is for. Periodic reclustering is the corrective this drift calls for, not a "
        "bug to fix in the incremental path itself.",
        "",
        "## Notes",
        "- Zero model/embedding calls: every vector reused from the persisted "
        f"{EMBEDDINGS_DIR}, the 31-book/34-book split is answer-record filtering, and both "
        "fits are local HDBSCAN/PCA/StandardScaler.",
        "- `fold_groups` (case/whitespace/punctuation dedup, upstream of the real `axial names "
        "merge`) is NOT applied here -- this measures label-key stability directly, not the "
        "full merge pipeline's exact batch count.",
    ]
    (LOG_DIR / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
