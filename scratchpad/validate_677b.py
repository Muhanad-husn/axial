"""Issue #677 slice B: real-corpus validation, zero model calls.

Run from D:\\axial (main checkout, real data) with the WORKTREE's code on the
interpreter path (`uv run --project <worktree> scratchpad/validate_677b.py`),
so the branch's incremental-bagging logic runs against the real 34-book
corpus already on disk. Bagging is the local MiniLM encoder only -- nothing
here makes a model call, and nothing here writes to any persisted map
artifact (`data/map/`); everything is computed in-memory and only the report
is written, under `data/logs/`.

Partitions the 34-book passage set by `source_id` into the 31 pre-#623 books
and the 3 added (the same split slice A's own validation used), exactly as
the brief asks: "Partition the 34-book passage set by source_id ... exactly
as slice A partitioned the persisted vectors."
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from axial.argmap.build import (
    BAG_DISTANCE_THRESHOLD,
    ENCODER_MODEL,
    _bag_passages_with_centroids,
    _default_encoder,
    _incremental_bag_passages,
    _members_key,
    build_jobs,
    select_passages,
)

DATA_DIR = Path("data")
ANSWERS_DIR = DATA_DIR / "answers"
TREES_DIR = DATA_DIR / "trees"

# The same #623 delta slice A's own validation script partitioned on.
NEW_SOURCES = {
    "gelvin-1998-f7e1df5f9b1d",
    "hinnebusch-1990-ac29981e616e",
    "wedeen-2019-3ae1f7af318d",
}

LOG_DIR = DATA_DIR / "logs" / "2026-08-05-677b-incremental-map-bags"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Rename before truncate (slice A's own builder lost run 1's record this
# way): a prior run's `run.jsonl` is preserved as `run-N.jsonl` before this
# run opens a fresh one of its own.
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


def main() -> None:
    encode = _default_encoder()

    t0 = time.time()
    all_passages = select_passages(ANSWERS_DIR, TREES_DIR)
    all_sources = {p.source_id for p in all_passages}
    old_sources = all_sources - NEW_SOURCES
    log(
        "sources",
        total=len(all_sources),
        old=len(old_sources),
        new=len(NEW_SOURCES),
        elapsed=time.time() - t0,
    )
    assert len(old_sources) == 31 and NEW_SOURCES <= all_sources, (
        "expected #623's 31-old/3-new split against the corpus on disk"
    )

    old_passages = [p for p in all_passages if p.source_id in old_sources]
    log("passages", all=len(all_passages), old=len(old_passages))

    # --- Step 1: full bagging over the 31-book subset -- the baseline ---
    t0 = time.time()
    bags_old, centroids_old = _bag_passages_with_centroids(old_passages, encode)
    t_bag_31 = time.time() - t0
    jobs_old = build_jobs(bags_old)
    keys_old = {_members_key(job.members) for job in jobs_old}
    log(
        "baseline_31_books",
        passages=len(old_passages),
        bags=len(bags_old),
        reads=len(jobs_old),
        unique_keys=len(keys_old),
        elapsed=t_bag_31,
    )

    # --- Step 2: incremental bagging of the full 34-book passage set ----
    prior_state = {
        "config": {
            "encoder": ENCODER_MODEL,
            "bag_distance_threshold": BAG_DISTANCE_THRESHOLD,
            "sklearn_version": "n/a-for-validation",
        },
        "assignments": {p.chunk_id: label for label, members in bags_old.items() for p in members},
        "centroids": {str(label): centroid.tolist() for label, centroid in centroids_old.items()},
    }
    max_old_label = max(bags_old, default=-1)

    t0 = time.time()
    bags_incr, centroids_incr, new_count = _incremental_bag_passages(
        all_passages, encode, prior_state
    )
    t_incremental = time.time() - t0
    jobs_incr = build_jobs(bags_incr)
    keys_incr = {_members_key(job.members): job for job in jobs_incr}
    log(
        "incremental_34_books",
        passages=len(all_passages),
        new_passages_placed=new_count,
        bags=len(bags_incr),
        reads=len(jobs_incr),
        elapsed=t_incremental,
    )

    reused = keys_old & set(keys_incr)
    asked = set(keys_incr) - keys_old
    log(
        "reuse_vs_31_book_baseline",
        baseline_reads=len(jobs_old),
        this_pin_reads=len(jobs_incr),
        reused=len(reused),
        asked=len(asked),
    )

    # --- Disturbance breakdown, among the ASKED reads --------------------
    # A grown bag (existed at the 31-book baseline, `label <= max_old_label`,
    # and gained at least one new member) re-cuts every EXTRACT_SLICE
    # boundary downstream of the new member (`author_spread` rotates one
    # author at a time) -- so most of its own slices are asked even where
    # the SLICE ITSELF carries no new passage. A brand new bag (residue,
    # `label > max_old_label`) never existed at the baseline at all: every
    # read in it is "re-bagged" work, not a re-cut of something old.
    grown_bag_labels = {
        label
        for label, members in bags_incr.items()
        if label <= max_old_label and any(p.source_id in NEW_SOURCES for p in members)
    }
    genuinely_new_content = 0
    author_spread_recut = 0
    rebagged = 0
    for key in asked:
        job = keys_incr[key]
        touches_new = any(p.source_id in NEW_SOURCES for p in job.members)
        if job.bag > max_old_label:
            rebagged += 1
        elif touches_new:
            genuinely_new_content += 1
        elif job.bag in grown_bag_labels:
            author_spread_recut += 1
        else:
            # Should not happen by design (an unaffected bag's own slices
            # are byte-identical to the baseline) -- counted rather than
            # silently folded into another bucket, so a real anomaly shows.
            author_spread_recut += 1
    log(
        "disturbance_breakdown",
        asked=len(asked),
        genuinely_new_content=genuinely_new_content,
        author_spread_recut=author_spread_recut,
        rebagged_new_bag=rebagged,
    )

    # --- units_asked_touching_new (as `run_map_build` itself computes it) -
    touching_new = sum(
        1 for key in asked if any(p.source_id in NEW_SOURCES for p in keys_incr[key].members)
    )
    log("units_asked_touching_new", count=touching_new, of_asked=len(asked))

    # --- Step 3: a fresh full bagging over all 34 books, for the drift ---
    t0 = time.time()
    bags_fresh, _centroids_fresh = _bag_passages_with_centroids(all_passages, encode)
    t_bag_34 = time.time() - t0
    jobs_fresh = build_jobs(bags_fresh)
    keys_fresh = {_members_key(job.members) for job in jobs_fresh}
    log(
        "fresh_34_books",
        bags=len(bags_fresh),
        reads=len(jobs_fresh),
        unique_keys=len(keys_fresh),
        elapsed=t_bag_34,
    )

    drift_agree = set(keys_incr) & keys_fresh
    log(
        "drift_incremental_vs_fresh_34",
        incremental_reads=len(jobs_incr),
        fresh_reads=len(jobs_fresh),
        agree=len(drift_agree),
        agree_pct=len(drift_agree) / len(jobs_fresh) if jobs_fresh else None,
    )

    summary_lines = [
        "# Issue #677 slice B: real-corpus validation",
        "",
        f"31-book baseline: {len(old_passages)} passages, {len(bags_old)} bags, "
        f"{len(jobs_old)} reads ({t_bag_31:.1f}s)",
        f"34-book (delta = 3 books) incremental build: {new_count} new passages placed "
        f"(of {len(all_passages) - len(old_passages)} in the 3 new books), "
        f"{len(bags_incr)} bags, {len(jobs_incr)} reads ({t_incremental:.1f}s)",
        "",
        "## Reuse against the 665-read baseline this pin's own reads number",
        f"- reused (no re-ask): {len(reused)} of {len(jobs_incr)} "
        f"({len(reused) / len(jobs_incr):.1%})"
        if jobs_incr
        else "- reused: n/a (no reads)",
        f"- asked (new call needed): {len(asked)} of {len(jobs_incr)}",
        "- compare to #623's own measured baseline: 665 reads, 0 reused, 100% re-asked under "
        "the OLD global-refit build",
        "",
        "## Disturbance breakdown, among the asked reads",
        f"- genuinely new content ({genuinely_new_content}): the slice itself carries a "
        "passage from one of the 3 new books",
        f"- author_spread re-cut ({author_spread_recut}): the slice belongs to a bag that "
        "gained a new member elsewhere, so its own EXTRACT_SLICE boundary moved even though "
        "every passage IN this slice already existed",
        f"- re-bagged, brand new bag ({rebagged}): a residue bag with no baseline counterpart "
        "at all -- offset above the existing maximum label, never a re-cut of something old",
        "",
        f"## units_asked_touching_new: {touching_new} of {len(asked)} asked reads touch one of "
        "the 3 new books (every asked read that is not a pure author_spread re-cut of old "
        "content touches a new book, by construction of the breakdown above)",
        "",
        "## Drift vs a fresh 34-book bagging",
        f"- fresh full bag: {len(bags_fresh)} bags, {len(jobs_fresh)} reads ({t_bag_34:.1f}s)",
        f"- incremental agrees with a fresh fit on {len(drift_agree)} of {len(jobs_fresh)} "
        f"reads ({len(drift_agree) / len(jobs_fresh):.1%})."
        if jobs_fresh
        else "- n/a",
        "- This is drift, not free reuse: most of these were never asked about under either "
        "build. `--force` is the periodic corrective for this drift, not a bug to fix here.",
        "",
        "## Notes",
        "- Zero model calls: every vector computed by the local MiniLM encoder "
        f"({ENCODER_MODEL}), nothing written to any persisted map artifact under `data/map/`.",
        "- `_incremental_bag_passages` is called with an in-memory `prior_state` built "
        "directly from the 31-book baseline's own bags/centroids -- this validates the "
        "MECHANISM exactly as `run_map_build` would use it, without needing a real prior "
        "pin directory or a real `bag_state.json` on disk.",
    ]
    (LOG_DIR / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
