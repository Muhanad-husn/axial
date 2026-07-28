"""The scoring math every number in RESULTS.md rests on.

Small on purpose: the harness is 200 lines and the experiment's whole claim is
that its arithmetic is right, so the arithmetic is what gets pinned.
"""

from __future__ import annotations

from experiments.mechanical_merge.harness import Cluster, as_partition, pairs, score_all
from experiments.mechanical_merge.repair import collided_pairs
from experiments.mechanical_merge.resolvers.baselines import merge_all, split_all

MEMBERS = ("A", "B", "C")
GOLD = as_partition([["A", "B"]], MEMBERS)
CLUSTER = Cluster(batch_key="k", cluster_label=0, members=MEMBERS, gold=GOLD)


def test_unplaced_members_survive_as_singletons():
    assert as_partition([["A", "B"]], MEMBERS) == frozenset(
        {frozenset({"A", "B"}), frozenset({"C"})}
    )


def test_a_group_never_invents_a_member():
    assert as_partition([["A", "Z"]], MEMBERS) == frozenset(
        {frozenset({"A"}), frozenset({"B"}), frozenset({"C"})}
    )


def test_pairs_are_the_same_entity_assertions():
    assert pairs(GOLD) == {frozenset({"A", "B"})}


def test_split_all_is_all_precision_and_no_recall():
    score, _ = score_all("split", split_all, [CLUSTER], {})
    assert (score.true_pairs, score.false_pairs, score.missed_pairs) == (0, 0, 1)
    assert score.precision == 1.0 and score.recall == 0.0
    assert score.over_merged_clusters == 0 and score.under_merged_clusters == 1


def test_merge_all_finds_every_merge_and_fuses_the_rest():
    score, _ = score_all("merge", merge_all, [CLUSTER], {})
    # A-B is right; A-C and B-C are entities fused.
    assert (score.true_pairs, score.false_pairs, score.missed_pairs) == (1, 2, 0)
    assert score.recall == 1.0 and score.over_merged_clusters == 1


def test_exact_agreement_needs_the_whole_partition():
    score, _ = score_all("gold", lambda members, kinds: GOLD, [CLUSTER], {})
    assert score.exact == 1 and score.agreement == 1.0


def test_collided_pairs_finds_what_the_parser_could_not_keep_apart():
    cluster = Cluster(
        batch_key="k",
        cluster_label=0,
        members=("Janjaweed", "janjaweed", "Other"),
        gold=as_partition([], ("Janjaweed", "janjaweed", "Other")),
    )
    assert collided_pairs(cluster) == {frozenset({"Janjaweed", "janjaweed"})}
