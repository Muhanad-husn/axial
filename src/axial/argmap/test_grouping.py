"""Unit tests for `axial.argmap.grouping` (issue #828): the two candidate
inner splits from the approach doc's own §6 (`docs/approach-positions-not-
names.md`) as pure functions over already-loaded chunk -> category/value
maps -- no file I/O, no model call. Mirrors `axial.argmap.build.
bag_passages`'s own `encode`/`cluster_fn` injection seam so a fake encoder
and a fake cluster function are all a test ever needs; neither sentence-
transformers nor scikit-learn has to be installed for this file to pass."""

from __future__ import annotations

import numpy as np

from axial.argmap.grouping import (
    NOISE_LABEL,
    group_by_intersection,
    group_by_subcluster,
    slice_projection,
    summarize,
)


def _fake_encode(texts):
    """A deterministic, model-free encoder: one feature, the text's own
    length. Never imports sentence-transformers."""
    return np.array([[float(len(text))] for text in texts])


# ---------------------------------------------------------------------------
# group_by_intersection: claim x mechanism. Shared (claim, mechanism) cells
# land together; refused/unassigned on EITHER axis is reported ungrouped.
# ---------------------------------------------------------------------------


def test_group_by_intersection_groups_shared_claim_and_mechanism_cells():
    claim = {"n1": "cat-a", "n2": "cat-a", "n3": "cat-b"}
    mechanism = {"n1": "mech-x", "n2": "mech-y", "n3": "mech-x"}

    result = group_by_intersection(["n1", "n2", "n3"], claim, mechanism)

    by_label = {group.label: group.chunk_ids for group in result.groups}
    assert by_label == {
        "cat-a::mech-x": ("n1",),
        "cat-a::mech-y": ("n2",),
        "cat-b::mech-x": ("n3",),
    }
    assert result.ungrouped_chunk_ids == ()


def test_group_by_intersection_reports_a_passage_refused_on_either_axis_as_ungrouped():
    # n2: claim assigned, mechanism never answered. n3: mechanism assigned,
    # claim never answered. Neither is silently dropped -- both are counted.
    claim = {"n1": "cat-a", "n2": "cat-a"}
    mechanism = {"n1": "mech-x", "n3": "mech-x"}

    result = group_by_intersection(["n1", "n2", "n3"], claim, mechanism)

    assert [group.chunk_ids for group in result.groups] == [("n1",)]
    assert result.ungrouped_chunk_ids == ("n2", "n3")


def test_group_by_intersection_labels_are_deterministic_regardless_of_input_order():
    claim = {"n1": "cat-a", "n2": "cat-b", "n3": "cat-a"}
    mechanism = {"n1": "mech-x", "n2": "mech-x", "n3": "mech-y"}

    forward = group_by_intersection(["n1", "n2", "n3"], claim, mechanism)
    backward = group_by_intersection(["n3", "n2", "n1"], claim, mechanism)

    assert forward == backward


# ---------------------------------------------------------------------------
# group_by_subcluster: claim category outer, injected cluster_fn inner.
# ---------------------------------------------------------------------------


def test_group_by_subcluster_splits_one_claim_category_by_the_injected_cluster_fn():
    claim = {"n1": "cat-a", "n2": "cat-a", "n3": "cat-a"}
    values = {"n1": "a", "n2": "bb", "n3": "ccc"}

    def cluster_fn(vectors):
        # `_fake_encode` gives length 1/2/3 -> label 0 below 3, 1 at/above.
        return [0 if vector[0] < 3 else 1 for vector in vectors]

    result = group_by_subcluster(["n1", "n2", "n3"], claim, values, _fake_encode, cluster_fn)

    by_label = {group.label: group.chunk_ids for group in result.groups}
    assert by_label == {"cat-a::0": ("n1", "n2"), "cat-a::1": ("n3",)}
    assert result.ungrouped_chunk_ids == ()


def test_group_by_subcluster_every_passage_with_a_claim_category_lands_in_exactly_one_group():
    claim = {"n1": "cat-a", "n2": "cat-a", "n3": "cat-b"}  # n4: no claim category at all
    values = {"n1": "a", "n2": "a", "n3": "a"}

    def cluster_fn(vectors):
        return [0] * len(vectors)

    result = group_by_subcluster(["n1", "n2", "n3", "n4"], claim, values, _fake_encode, cluster_fn)

    seen = [chunk_id for group in result.groups for chunk_id in group.chunk_ids]
    assert sorted(seen) == ["n1", "n2", "n3"]
    assert len(seen) == len(set(seen))  # exactly one group each, never two
    assert result.ungrouped_chunk_ids == ("n4",)


def test_group_by_subcluster_treats_a_cluster_fn_noise_label_as_ungrouped_encoder_residue():
    """A passage WITH a claim category can still end up ungrouped: the
    approach doc's "encoder residue" clause, for a `cluster_fn` that follows
    the same noise-label convention `axial.names.NOISE_LABEL` already uses
    (a residue re-fit is exactly the kind of `cluster_fn` slice 04 might
    inject here)."""
    claim = {"n1": "cat-a", "n2": "cat-a"}
    values = {"n1": "a", "n2": "bb"}

    def cluster_fn(_vectors):
        return [0, NOISE_LABEL]

    result = group_by_subcluster(["n1", "n2"], claim, values, _fake_encode, cluster_fn)

    assert [group.chunk_ids for group in result.groups] == [("n1",)]
    assert result.ungrouped_chunk_ids == ("n2",)


def test_group_by_subcluster_labels_are_deterministic_regardless_of_input_order():
    claim = {"n1": "cat-a", "n2": "cat-a", "n3": "cat-b"}
    values = {"n1": "a", "n2": "bb", "n3": "c"}

    def cluster_fn(vectors):
        return [0 if vector[0] < 2 else 1 for vector in vectors]

    forward = group_by_subcluster(["n1", "n2", "n3"], claim, values, _fake_encode, cluster_fn)
    backward = group_by_subcluster(["n3", "n2", "n1"], claim, values, _fake_encode, cluster_fn)

    assert forward == backward


# ---------------------------------------------------------------------------
# Slice projection: ceil(n / EXTRACT_SLICE) per group, summed per candidate.
# ---------------------------------------------------------------------------


def test_slice_projection_ceils_each_group_size_and_sums():
    assert slice_projection([1, 55, 56, 110], extract_slice=55) == 1 + 1 + 2 + 2


def test_slice_projection_is_zero_for_no_groups():
    assert slice_projection([], extract_slice=55) == 0


def test_summarize_reports_group_count_size_distribution_ungrouped_and_projected_slices():
    claim = {"n1": "cat-a", "n2": "cat-a", "n3": "cat-a", "n4": "cat-a"}
    mechanism = {"n1": "mech-x", "n2": "mech-x"}  # n3, n4 never answered

    result = group_by_intersection(["n1", "n2", "n3", "n4"], claim, mechanism)
    stats = summarize(result, extract_slice=55)

    assert stats.group_count == 1
    assert stats.min_size == 2
    assert stats.median_size == 2
    assert stats.max_size == 2
    assert stats.ungrouped_count == 2
    assert stats.projected_slices == 1
