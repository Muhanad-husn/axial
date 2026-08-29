"""Sweep the subcluster candidate's inner distance threshold (#828, PR #843
fix round).

Committed evidence, not a shipped entry point -- it is not wired into the
CLI or the test suite. It backs the PR body's claim that the founder's
claim x mechanism choice is not a threshold artifact: `group_by_subcluster`
running the SAME real-corpus universe through a range of thresholds swings
group count 1181 -> 11 (0.55 -> 0.90) while `ungrouped` never moves off 17,
because the sub-cluster candidate's ungrouped count has one cause -- no
claim category at all -- not the threshold this sweep varies.

Run from the main checkout (`D:/axial`), never a worktree: `data/map` and
`data/vocabulary` are gitignored and do not exist anywhere else.

    uv run python docs/tdd-evidence/positions-not-names/03-inner-split-chosen/sweep.py
"""

import statistics
from pathlib import Path

from axial.argmap.build import (
    BAG_DISTANCE_THRESHOLD,
    EXTRACT_SLICE,
    _agglomerative_cluster,
    _default_encoder,
)
from axial.argmap.grouping import _load_column, group_by_subcluster, summarize
from axial.argmap.purity import _load_bag_assignments, resolve_map_pin_dir

MAP = Path("D:/axial/data/map")
VOC = Path("D:/axial/data/vocabulary")

outdir, pin = resolve_map_pin_dir(MAP, None)
chunk_ids = sorted(_load_bag_assignments(outdir))
claim_cat, claim_val, level = _load_column(VOC, "claim", None)

base = _default_encoder()
cache = {}


def encode(texts):
    key = tuple(texts)
    if key not in cache:
        cache[key] = base(texts)
    return cache[key]


print("pin=%s passages=%d baseline_threshold=%s" % (pin, len(chunk_ids), BAG_DISTANCE_THRESHOLD))
rows = []
for t in (BAG_DISTANCE_THRESHOLD, 0.5, 0.6, 0.7, 0.8, 0.9):
    result = group_by_subcluster(
        chunk_ids, claim_cat, claim_val, encode, lambda v, t=t: _agglomerative_cluster(v, t)
    )
    stats = summarize(result, extract_slice=EXTRACT_SLICE)
    sizes = sorted(len(g.chunk_ids) for g in result.groups)
    rows.append((t, stats.group_count, min(sizes), statistics.median(sizes), max(sizes),
                 stats.ungrouped_count, stats.projected_slices))
    print("threshold=%s groups=%d median=%.2f max=%d ungrouped=%d slices=%d"
          % (t, stats.group_count, statistics.median(sizes), max(sizes),
             stats.ungrouped_count, stats.projected_slices))

print()
print("threshold  groups   min/median/max   ungrouped   slices")
for t, g, lo, med, hi, un, sl in rows:
    print("%9s %7d   %d / %.2f / %d %11d %8d" % (t, g, lo, med, hi, un, sl))
