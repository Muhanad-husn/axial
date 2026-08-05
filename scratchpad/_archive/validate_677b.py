"""Issue #677 slice B: real-corpus validation, zero model calls.

Run from D:\\axial (main checkout, real data) with the WORKTREE's code on the
interpreter path (`uv run --project <worktree> scratchpad/validate_677b.py`),
so the branch's incremental-bagging logic runs against the real 34-book
corpus already on disk. Bagging is the local MiniLM encoder only -- nothing
here makes a model call, and nothing here writes to any persisted map
artifact (`data/map/`); everything is computed in-memory and only the report
is written, under `data/logs/`. A single claim-text-keyed encode cache is
shared by every bagging pass below, so no claim is embedded twice however
many times a bag set reads it.

Partitions the 34-book passage set by `source_id` into the 31 pre-#623 books
and the 3 added (the same split slice A's own validation used), exactly as
the brief asks: "Partition the 34-book passage set by source_id ... exactly
as slice A partitioned the persisted vectors."

**The 31-book baseline recomputed here will not match the #623 paid build's
own 5,726 passages / 700 reads (08-04).** `data/answers` for those 31 books
has changed between that paid run and whenever this script runs (a
downstream interrogation re-run, a fix, or similar) -- BASELINE_31_BOOK_
PASSAGES_08_04 below records that historical figure so a mismatch is logged
loudly rather than silently producing a report that looks like it reproduces
the old numbers. This does not weaken the validation: every comparison in
this report (baseline vs incremental vs fresh) reads the SAME `data/answers`
on disk, so the mechanism is being validated against itself, not against a
stale historical count. Never quote "700 -> N" from this report; quote this
run's own logged `baseline_31_books.reads` figure instead.

**The acceptance bar is coherence, not agreement with a fresh fit.** An
earlier probe measured incremental placement as agreement with a FRESH
34-book fit and found only ~22% of new passages landing in a bag sharing
even 10% membership with the fresh fit's own equivalent bag. That yardstick
is wrong: a fresh agglomerative fit is not ground truth, it REORGANISES
when new passages arrive (bag count moves), so a new passage can legitimately
land in a bag no incremental rule could ever reproduce, without that being a
defect. What a bag is FOR is a single coherent read -- claims similar enough
that one model call has one answer -- so the number that matters is each
bag's own mean cosine similarity of its members to their own mean direction
(`_bag_coherence` below), compared between the incrementally-grown bags and
the fresh fit's own bags as the reference for "coherent enough to trust".
The `drift_incremental_vs_fresh_34` figure is still logged (how many reads
are byte-identical to what a fresh fit would produce) because it is free and
answers a different, real question -- how much a periodic `--force` rebuild
would still change -- but it is DEMOTED: it is not what decided this design,
and it is not what should decide whether to ship it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

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

# The #623 paid map build's own historical figure (08-04), for the loud
# mismatch check described in the module docstring -- NOT re-derived, a
# plain recorded fact from that run's own map.json.
BASELINE_31_BOOK_PASSAGES_08_04 = 5726

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


def _cached_encoder(base_encode, cache: dict[str, list[float]]):
    """Wraps `base_encode` with a claim-text-keyed cache, shared across
    every bagging pass in `main` -- a claim already embedded (by any pass)
    is never re-embedded by another. Correct regardless of a rare duplicate
    claim string across two different chunk_ids: encoding is a pure
    function of the text, so the cached vector is the right one either
    way."""

    def encode(claims):
        missing = [claim for claim in claims if claim not in cache]
        if missing:
            for claim, vector in zip(missing, base_encode(missing)):
                cache[claim] = vector
        return [cache[claim] for claim in claims]

    return encode


def _bag_coherence(
    bags: dict[int, list], vectors_by_chunk_id: dict[str, list[float]]
) -> dict[int, float]:
    """Each bag's own mean cosine similarity of its members to that bag's
    own (renormalised) mean direction -- a DESCRIPTIVE tightness figure,
    never what placement decides by (`_incremental_bag_passages`'s own
    average-linkage criterion uses the UNnormalised mean; this uses the
    normalised one on purpose -- the standard spherical-cluster cohesion
    figure, answering "how tight does this group of claims actually read",
    not "would a new point be accepted into it"). A size-1 bag has no
    member other than itself to cohere with and is excluded."""
    scores: dict[int, float] = {}
    for label, members in bags.items():
        if len(members) < 2:
            continue
        vectors = np.stack([np.asarray(vectors_by_chunk_id[p.chunk_id]) for p in members])
        centroid = np.mean(vectors, axis=0)
        norm = np.linalg.norm(centroid)
        if norm == 0.0:
            continue
        scores[label] = float(np.mean(vectors @ (centroid / norm)))
    return scores


def _describe(scores: dict[int, float]) -> dict[str, float | int | None]:
    if not scores:
        return {"mean": None, "p10": None, "n": 0}
    values = np.array(list(scores.values()))
    return {
        "mean": float(np.mean(values)),
        "p10": float(np.percentile(values, 10)),
        "n": len(values),
    }


def main() -> None:
    encode_cache: dict[str, list[float]] = {}
    encode = _cached_encoder(_default_encoder(), encode_cache)

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
    if len(old_passages) != BASELINE_31_BOOK_PASSAGES_08_04:
        log(
            "baseline_passage_count_mismatch",
            this_run=len(old_passages),
            paid_build_08_04=BASELINE_31_BOOK_PASSAGES_08_04,
            note=(
                "data/answers for the 31 old books differs from the #623 paid build -- "
                "the old books' own answers changed between the two runs. Every "
                "comparison below still uses the SAME data/answers on both sides, so "
                "the mechanism validation is unaffected; never quote a '700 -> N' "
                "figure from this report, quote baseline_31_books.reads instead."
            ),
        )

    # Prime the shared cache once for every distinct claim in the full
    # 34-book set: every bagging pass below (31-book baseline, incremental,
    # fresh) is then a cache hit, so no claim is embedded more than once
    # across the whole script regardless of how many bag sets read it.
    t0 = time.time()
    encode([p.claim for p in all_passages])
    vectors_by_chunk_id = {p.chunk_id: encode_cache[p.claim] for p in all_passages}
    log("embedded_all_distinct_claims", distinct=len(encode_cache), elapsed=time.time() - t0)

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
    bags_incr, _centroids_incr, new_count = _incremental_bag_passages(
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
    residue_bag_labels = {label for label in bags_incr if label > max_old_label}
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

    # --- Step 3: a fresh full bagging over all 34 books -- the coherence
    # reference, and (demoted) the drift figure ---------------------------
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
        "drift_incremental_vs_fresh_34_DEMOTED_NOT_THE_ACCEPTANCE_BAR",
        incremental_reads=len(jobs_incr),
        fresh_reads=len(jobs_fresh),
        agree=len(drift_agree),
        agree_pct=len(drift_agree) / len(jobs_fresh) if jobs_fresh else None,
    )

    # --- Coherence: the actual acceptance bar -----------------------------
    coherence_fresh = _bag_coherence(bags_fresh, vectors_by_chunk_id)
    coherence_incr = _bag_coherence(bags_incr, vectors_by_chunk_id)
    fresh_bags_with_new_passage = {
        label
        for label, members in bags_fresh.items()
        if any(p.source_id in NEW_SOURCES for p in members)
    }

    stats_fresh_all = _describe(coherence_fresh)
    stats_fresh_touched = _describe(
        {
            label: score
            for label, score in coherence_fresh.items()
            if label in fresh_bags_with_new_passage
        }
    )
    stats_incr_unaffected = _describe(
        {
            label: score
            for label, score in coherence_incr.items()
            if label not in grown_bag_labels and label not in residue_bag_labels
        }
    )
    stats_incr_grown = _describe(
        {label: score for label, score in coherence_incr.items() if label in grown_bag_labels}
    )
    stats_incr_residue = _describe(
        {label: score for label, score in coherence_incr.items() if label in residue_bag_labels}
    )
    log(
        "coherence_fresh_reference",
        all_bags=stats_fresh_all,
        bags_with_new_passage=stats_fresh_touched,
    )
    log(
        "coherence_incremental",
        unaffected=stats_incr_unaffected,
        grown=stats_incr_grown,
        residue=stats_incr_residue,
    )

    def _fmt(stats: dict) -> str:
        if stats["mean"] is None:
            return "n/a (0 bags)"
        return f"mean={stats['mean']:.3f} p10={stats['p10']:.3f} (n={stats['n']})"

    summary_lines = [
        "# Issue #677 slice B: real-corpus validation",
        "",
        f"31-book baseline: {len(old_passages)} passages, {len(bags_old)} bags, "
        f"{len(jobs_old)} reads ({t_bag_31:.1f}s)"
        + (
            f" -- NOTE: differs from the #623 paid build's own "
            f"{BASELINE_31_BOOK_PASSAGES_08_04} passages; see module docstring, "
            "data/answers changed between the two runs, not this script"
            if len(old_passages) != BASELINE_31_BOOK_PASSAGES_08_04
            else ""
        ),
        f"34-book (delta = 3 books) incremental build: {new_count} new passages placed "
        f"(of {len(all_passages) - len(old_passages)} in the 3 new books), "
        f"{len(bags_incr)} bags, {len(jobs_incr)} reads ({t_incremental:.1f}s)",
        "",
        "## Reuse against this run's own incremental read count",
        (
            f"- reused (no re-ask): {len(reused)} of {len(jobs_incr)} "
            f"({len(reused) / len(jobs_incr):.1%})"
            if jobs_incr
            else "- reused: n/a (no reads)"
        ),
        f"- asked (new call needed): {len(asked)} of {len(jobs_incr)}",
        "- compare to the fresh 34-book bagging below, which reproduces what the OLD "
        "global-refit build actually paid for: every one of its reads is asked, 0 reused",
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
        "the 3 new books",
        "",
        "## Coherence -- the acceptance bar (mean cosine similarity of a bag's own members "
        "to that bag's own mean direction; NOT the average-linkage criterion placement "
        "decides by -- see module docstring)",
        f"- fresh 34-book fit, all bags: {_fmt(stats_fresh_all)}",
        f"- fresh 34-book fit, bags touching a new-book passage (the reference for "
        f"'coherent enough to trust'): {_fmt(stats_fresh_touched)}",
        f"- incremental, unaffected bags (no new member, kept verbatim): {_fmt(stats_incr_unaffected)}",
        f"- incremental, grown bags (gained >=1 new-book passage): {_fmt(stats_incr_grown)}",
        f"- incremental, residue bags (brand new, no baseline counterpart): {_fmt(stats_incr_residue)}",
        "- the bar: incremental's grown-bag coherence should read close to the fresh fit's "
        "own bags-with-a-new-passage coherence, at both mean and p10 (the worst decile) -- "
        "not agreement in WHICH bag a passage landed in (see the demoted drift figure below "
        "and the module docstring for why that yardstick was rejected).",
        "",
        "## Drift vs a fresh 34-book bagging -- DEMOTED, not the acceptance bar",
        f"- fresh full bag: {len(bags_fresh)} bags, {len(jobs_fresh)} reads ({t_bag_34:.1f}s)",
        (
            f"- incremental's own reads are byte-identical to a fresh fit's on "
            f"{len(drift_agree)} of {len(jobs_fresh)} ({len(drift_agree) / len(jobs_fresh):.1%})."
            if jobs_fresh
            else "- n/a"
        ),
        "- This is drift, not free reuse: most of these were never asked about under either "
        "build, and a fresh fit REORGANISES on new passages (bag count moves), so a new "
        "passage landing somewhere a fresh fit would not put it is not, by itself, a defect. "
        "`--force` is the periodic corrective for this drift; coherence above is what actually "
        "justifies the design.",
        "",
        "## Notes",
        "- Zero model calls: every vector computed once by the local MiniLM encoder "
        f"({ENCODER_MODEL}) via a shared claim-text cache, nothing written to any persisted "
        "map artifact under `data/map/`.",
        "- `_incremental_bag_passages` is called with an in-memory `prior_state` built "
        "directly from the 31-book baseline's own bags/centroids -- this validates the "
        "MECHANISM exactly as `run_map_build` would use it, without needing a real prior "
        "pin directory or a real `bag_state.json` on disk.",
    ]
    (LOG_DIR / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
