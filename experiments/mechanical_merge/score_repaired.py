"""Score resolvers against the gold with the parser artifact excluded.

Same metrics as `harness.score_all`, minus the 1,568 pairs whose "refused"
label was produced by `parse_merge_response`'s normalization collision rather
than by the model (see `repair`). Run it alongside the raw score, never
instead of it.

    uv run python -m experiments.mechanical_merge.score_repaired \
        experiments.mechanical_merge.resolvers.orthographic:best
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from experiments.mechanical_merge.bench import load
from experiments.mechanical_merge.harness import (
    DEFAULT_DECISIONS,
    DEFAULT_INVENTORY,
    HEADER,
    Resolver,
    Score,
    load_gold,
    load_kinds,
    pairs,
)
from experiments.mechanical_merge.repair import collided_pairs, summary


def score_repaired(name: str, resolver: Resolver, clusters, kinds) -> Score:
    score = Score(name=name, clusters=len(clusters))
    started = time.perf_counter()
    for cluster in clusters:
        excluded = collided_pairs(cluster)
        gold = pairs(cluster.gold) - excluded
        predicted = pairs(resolver(cluster.members, kinds)) - excluded
        score.gold_pairs += len(gold)
        tp = predicted & gold
        fp = predicted - gold
        fn = gold - predicted
        score.true_pairs += len(tp)
        score.false_pairs += len(fp)
        score.missed_pairs += len(fn)
        # A cluster counts as exact when it agrees on every pair the model
        # actually decided.
        if not fp and not fn:
            score.exact += 1
        score.over_merged_clusters += bool(fp)
        score.under_merged_clusters += bool(fn)
    score.seconds = time.perf_counter() - started
    return score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("resolvers", nargs="+")
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    args = parser.parse_args()

    clusters = load_gold(args.decisions)
    kinds = load_kinds(args.inventory)
    stats = summary(clusters)
    print(
        f"excluding {stats['pairs']:,} parser-collided pairs across "
        f"{stats['clusters']:,} of {stats['total_clusters']:,} clusters\n"
    )
    print(HEADER)
    for spec in args.resolvers:
        name = spec.rsplit(":", 1)[-1]
        print(score_repaired(name, load(spec), clusters, kinds).row(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
