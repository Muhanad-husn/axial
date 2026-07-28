"""Scoring harness for the mechanical name-merge experiment.

The question: how much of the `axial names merge` pass can a model-free
resolver decide, and at what cost in judgment? PR #441 measured two "clever"
levers (packing, reasoning off) against the live pass's own decisions and
rejected both. This reuses that method -- the live pass's 18,873 recorded
decisions ARE the baseline, so scoring any candidate resolver is free -- and
points it at mechanical string methods instead of at another model setting.

Everything here is comparison-only. It reads `merge_decisions.jsonl` and
writes nothing to `data/`.

Two things PR #441 established that this harness encodes:

  * A decision is a PARTITION of the cluster's members -- which surfaces ended
    up grouped -- not a node list. Which member is elected canonical is a
    separate, reversible question and is not scored.
  * Over-merging and under-merging are not symmetric errors. Fusing two
    entities destroys information (one page misrepresents both); splitting one
    entity only leaves two pages that can be rejoined. So the headline is never
    a single agreement number: it is precision and recall on the pairwise
    same-entity relation, reported apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Callable, Iterable

Partition = frozenset[frozenset[str]]
Resolver = Callable[[tuple[str, ...], dict[str, str | None]], Partition]

DEFAULT_DECISIONS = Path("D:/axial/data/names/merge_decisions.jsonl")
DEFAULT_INVENTORY = Path("D:/axial/data/names/inventory.jsonl")


@dataclass(frozen=True)
class Cluster:
    """One recorded merge decision, read as a scoring case."""

    batch_key: str
    cluster_label: int
    members: tuple[str, ...]
    gold: Partition

    @property
    def gold_merges(self) -> int:
        """How many same-entity pairs the model asserted."""
        return sum(len(group) * (len(group) - 1) // 2 for group in self.gold)


def as_partition(groups: Iterable[Iterable[str]], members: tuple[str, ...]) -> Partition:
    """Close a set of groups into a partition of `members`: anything a group
    did not name survives as its own singleton, which is exactly what
    `merge_names.build_alias_map_nodes` does with an unplaced surface form."""
    placed: set[str] = set()
    blocks: list[frozenset[str]] = []
    for group in groups:
        block = frozenset(item for item in group if item in members and item not in placed)
        if not block:
            continue
        placed |= block
        blocks.append(block)
    blocks.extend(frozenset({member}) for member in members if member not in placed)
    return frozenset(blocks)


def load_gold(path: Path = DEFAULT_DECISIONS) -> list[Cluster]:
    """Every recorded decision as a scoring case.

    A decision's `nodes` are `{canonical, aliases[]}`; the group is the
    canonical together with its aliases. `parse_merge_response` already
    restricted both to the batch's own members, so the only closure needed is
    for a member the response never placed.
    """
    clusters: list[Cluster] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            members = tuple(record["members"])
            groups = [[node["canonical"], *node["aliases"]] for node in record["nodes"]]
            clusters.append(
                Cluster(
                    batch_key=record["batch_key"],
                    cluster_label=int(record["cluster_label"]),
                    members=members,
                    gold=as_partition(groups, members),
                )
            )
    return clusters


def load_kinds(path: Path = DEFAULT_INVENTORY) -> dict[str, str | None]:
    """`{surface form: kind}` from the inventory -- the same map the live pass
    put in front of the model, so a resolver that reads `kind` is using
    information the baseline also had."""
    kinds: dict[str, str | None] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            kinds[record["surface"]] = record.get("kind") or None
    return kinds


def pairs(partition: Partition) -> set[frozenset[str]]:
    """The same-entity pairs a partition asserts."""
    return {frozenset(pair) for block in partition for pair in combinations(sorted(block), 2)}


@dataclass
class Score:
    """One resolver's result over a set of clusters."""

    name: str
    clusters: int = 0
    exact: int = 0
    over_merged_clusters: int = 0
    under_merged_clusters: int = 0
    true_pairs: int = 0
    false_pairs: int = 0
    missed_pairs: int = 0
    gold_pairs: int = 0
    seconds: float = 0.0

    @property
    def agreement(self) -> float:
        return self.exact / self.clusters if self.clusters else 0.0

    @property
    def precision(self) -> float:
        predicted = self.true_pairs + self.false_pairs
        return self.true_pairs / predicted if predicted else 1.0

    @property
    def recall(self) -> float:
        return self.true_pairs / self.gold_pairs if self.gold_pairs else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def row(self) -> str:
        return (
            f"| {self.name} | {self.agreement:.1%} | {self.precision:.1%} | "
            f"{self.recall:.1%} | {self.f1:.3f} | {self.false_pairs} | "
            f"{self.missed_pairs} | {self.over_merged_clusters} | "
            f"{self.under_merged_clusters} | {self.seconds:.1f}s |"
        )


HEADER = (
    "| resolver | partition agreement | pair precision | pair recall | F1 | "
    "FP pairs | FN pairs | over-merged clusters | under-merged clusters | wall |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def score_all(
    name: str,
    resolver: Resolver,
    clusters: list[Cluster],
    kinds: dict[str, str | None],
    collect_errors: int = 0,
) -> tuple[Score, list[dict]]:
    """Run `resolver` over every cluster and score it.

    `collect_errors` caps how many disagreeing clusters are returned alongside
    the score, for inspection -- over-merges first, because those are the ones
    that decide whether a resolver is usable at all.
    """
    import time

    score = Score(name=name, clusters=len(clusters))
    over: list[dict] = []
    under: list[dict] = []
    started = time.perf_counter()
    for cluster in clusters:
        predicted = resolver(cluster.members, kinds)
        gold_pairs = pairs(cluster.gold)
        pred_pairs = pairs(predicted)
        score.gold_pairs += len(gold_pairs)
        tp = pred_pairs & gold_pairs
        fp = pred_pairs - gold_pairs
        fn = gold_pairs - pred_pairs
        score.true_pairs += len(tp)
        score.false_pairs += len(fp)
        score.missed_pairs += len(fn)
        if predicted == cluster.gold:
            score.exact += 1
        if fp:
            score.over_merged_clusters += 1
            if len(over) < collect_errors:
                over.append(_error_row(cluster, predicted, fp, fn, "over"))
        if fn:
            score.under_merged_clusters += 1
            if len(under) < collect_errors:
                under.append(_error_row(cluster, predicted, fp, fn, "under"))
    score.seconds = time.perf_counter() - started
    return score, over + under


def _error_row(cluster: Cluster, predicted: Partition, fp: set, fn: set, direction: str) -> dict:
    return {
        "direction": direction,
        "cluster_label": cluster.cluster_label,
        "members": list(cluster.members),
        "gold": sorted(sorted(block) for block in cluster.gold),
        "predicted": sorted(sorted(block) for block in predicted),
        "false_pairs": sorted(sorted(pair) for pair in fp),
        "missed_pairs": sorted(sorted(pair) for pair in fn),
    }
