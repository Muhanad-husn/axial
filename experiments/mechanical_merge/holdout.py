"""A held-out half, because three agents tuned their rules by reading the
errors they made on this same corpus.

Every resolver in `resolvers/` was written by looking at disagreements and
adding a rule to fix them. That is the right way to build one, and it is also
exactly how a rule set comes to describe its sample rather than its subject.
Nothing in the harness stops it, so the split does.

The split is by a hash of the batch key, not by position: cluster labels run in
HDBSCAN's own order, which correlates with density and therefore with
difficulty, so a first-half/second-half cut would compare two different
problems. Hashing the key is stable across runs, independent of the tightness
dial, and puts a cluster on the same side every time.

Report a resolver's DEV score and its HELD score side by side. A gap between
them is the amount of the result that is memory rather than method.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from experiments.mechanical_merge.bench import load
from experiments.mechanical_merge.harness import (
    DEFAULT_DECISIONS,
    DEFAULT_INVENTORY,
    Cluster,
    load_gold,
    load_kinds,
    score_all,
)
from experiments.mechanical_merge.score_repaired import score_repaired


def side(cluster: Cluster) -> str:
    """`dev` or `held`, from the batch key alone."""
    digest = hashlib.sha256(cluster.batch_key.encode("utf-8")).digest()
    return "dev" if digest[0] % 2 == 0 else "held"


def split(clusters: list[Cluster]) -> dict[str, list[Cluster]]:
    halves: dict[str, list[Cluster]] = {"dev": [], "held": []}
    for cluster in clusters:
        halves[side(cluster)].append(cluster)
    return halves


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("resolvers", nargs="+")
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--repaired", action="store_true", help="exclude the parser-collided pairs")
    args = parser.parse_args()

    halves = split(load_gold(args.decisions))
    kinds = load_kinds(args.inventory)
    print(f"dev {len(halves['dev']):,} clusters | held {len(halves['held']):,} clusters\n")
    print("| resolver | half | agreement | precision | recall | F1 | FP pairs |")
    print("|---|---|---|---|---|---|---|")
    for spec in args.resolvers:
        name = spec.rsplit(":", 1)[-1]
        resolver = load(spec)
        for half in ("dev", "held"):
            if args.repaired:
                score = score_repaired(name, resolver, halves[half], kinds)
            else:
                score, _ = score_all(name, resolver, halves[half], kinds)
            print(
                f"| {name} | {half} | {score.agreement:.1%} | {score.precision:.1%} | "
                f"{score.recall:.1%} | {score.f1:.3f} | {score.false_pairs} |",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
