"""The gold is not clean, and this is the part of it that is provably wrong.

`merge_names.parse_merge_response` resolves the model's answer back onto the
batch's members through `polity_canonical._normalize`, which casefolds and
collapses whitespace:

    known = {_normalize(surface_form): surface_form for surface_form in members}

Two members that differ ONLY by case collapse to one dict entry. The model's
answer then resolves both of its strings to the same member; the second is
already `claimed`, so it is dropped, and the surface it came from is left
unplaced and survives as its own node. The merge the model asked for is
destroyed by the parser, every time.

Measured on the live decision log: 1,471 clusters (7.8%) contain such a
collision, over 1,568 pairs, and every one of those 1,568 is recorded as
"refused" -- 1,568 of 1,568, which is what a deterministic bug looks like next
to a model's judgment. The shipped `alias_map.json` carries 1,514 canonical
names that differ from another canonical only by case.

Nothing here can recover what the model actually said: the decision log keeps
the parsed `nodes`, not the raw response. So these pairs are EXCLUDED from
scoring rather than flipped. Scoring a resolver against them would mark it
wrong for merging `Janjaweed` with `janjaweed`, which is not a judgment the
baseline ever made.

Every headline in the report is given both ways -- raw gold and repaired gold --
so the correction is visible rather than assumed.
"""

from __future__ import annotations

import re
from collections import Counter

from experiments.mechanical_merge.harness import Cluster


def _normalize(text: str) -> str:
    """`polity_canonical._normalize`, copied so this module states the exact
    key the parser collides on rather than importing the pipeline."""
    return re.sub(r"\s+", " ", text.strip()).casefold()


def collided_pairs(cluster: Cluster) -> set[frozenset[str]]:
    """The pairs in this cluster whose gold label the parser determined rather
    than the model."""
    groups: dict[str, list[str]] = {}
    for member in cluster.members:
        groups.setdefault(_normalize(member), []).append(member)
    return {
        frozenset((left, right))
        for members in groups.values()
        if len(members) > 1
        for left in members
        for right in members
        if left < right
    }


def summary(clusters: list[Cluster]) -> dict[str, int]:
    counts = Counter()
    for cluster in clusters:
        collided = collided_pairs(cluster)
        if collided:
            counts["clusters"] += 1
            counts["pairs"] += len(collided)
    counts["total_clusters"] = len(clusters)
    return dict(counts)
