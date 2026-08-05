"""Acceptance tests for issue #677 (build's own slice): a new pin's argument
map places its new passages into the prior pin's own bags instead of
re-bagging the whole corpus, and seeds its reads ledger from the prior pin's
matching slices instead of re-asking a slice whose content did not change.

Fixtures and a fake client throughout -- no real model call, no scikit-learn
dependency for the fully-injected unit tests, and no dependence on `data/`
(a worktree has none). The two dense, well-separated fixture groups mirror
`axial.test_names`'s own `_GROUP_A`/`_GROUP_B` shape (see that module's
docstring for why): precise, known cosine distances relative to
`BAG_DISTANCE_THRESHOLD` are what let these tests assert exactly which
passage lands where.

Covered here:

  - `_members_key` depends on the ordered claim content, nothing else;
  - `_bag_state_reusable` requires the encoder, distance threshold, and
    installed scikit-learn version to all match, and rejects a malformed
    persisted file rather than crashing;
  - `_incremental_bag_passages` keeps an already-seen passage's own bag
    label, accepts a near-duplicate new passage into the nearest existing
    bag, and offsets a genuinely new cluster's label above the existing
    maximum -- never renumbering what already existed;
  - placement uses AVERAGE LINKAGE (the criterion the full fit's own
    clustering uses), not cosine distance to the centroid's own
    (renormalised) direction: a point built to pass the latter while
    failing the former must go to residue;
  - `_seed_reads_from_prior_pin` only ever seeds a job that is both pending
    (not already on this pin's own ledger) and content-matched, and rewrites
    the seeded record's own `(bag, slice)` to the current job's numbering;
  - end to end (`run_map_build`, two pins over a growing corpus): the
    unaffected bag's own read is reused with no model call, the bag that
    gained a member is re-asked, a genuinely new cluster gets its own read,
    and the four `units_*` counters in `map.json` add up correctly;
  - `--force` bypasses incremental bagging and ledger seeding entirely;
  - a rerun with no corpus change reports `units_asked: 0`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from axial.argmap.build import (
    BAG_DISTANCE_THRESHOLD,
    ENCODER_MODEL,
    CorruptReadsLedgerError,
    ExtractJob,
    Passage,
    _bag_state_path,
    _bag_state_reusable,
    _incremental_bag_passages,
    _load_json_or_none,
    _members_key,
    _seed_reads_from_prior_pin,
    _sklearn_version,
    _write_bag_state,
    run_map_build,
)
from axial.checkpoint import append_checkpoint_record, load_checkpoint_records

# ---------------------------------------------------------------------------
# Two dense, well-separated (near-orthogonal) groups -- distances relative to
# BAG_DISTANCE_THRESHOLD (0.55) verified directly against this exact fixture:
# within-group ~0.0002, group-to-group ~1.0, near-A-to-centroid-A ~0.000007,
# residue-to-either-centroid ~0.99-1.0.
# ---------------------------------------------------------------------------

_GROUP_A = [[1.0, 0.0, 0.0], [0.99, 0.02, 0.0], [0.98, 0.03, 0.0]]
_GROUP_B = [[0.0, 1.0, 0.0], [0.0, 0.99, 0.02]]
_ACCEPTED_NEAR_A = [0.97, 0.02, 0.0]
_RESIDUE_POINT = [0.0, 0.0, 1.0]


def _vector_lookup_encode(vectors_by_claim: dict[str, list[float]]):
    """An `Encoder` that returns pre-assigned, real-geometry vectors by
    exact claim text -- mirrors `axial.test_names._vector_lookup_encoder`,
    the seam these fixtures need for precise control over where a claim's
    vector lands relative to a persisted centroid."""
    calls: list[list[str]] = []

    def encode(claims):
        calls.append(list(claims))
        return [vectors_by_claim[claim] for claim in claims]

    encode.calls = calls  # type: ignore[attr-defined]
    return encode


def _passage(chunk_id: str, source_id: str, claim: str) -> Passage:
    return Passage(
        chunk_id=chunk_id, source_id=source_id, author=source_id.split("-")[0], claim=claim
    )


# ---------------------------------------------------------------------------
# _members_key
# ---------------------------------------------------------------------------


def test_members_key_depends_on_ordered_claim_content_only():
    a = (
        _passage("c1", "alpha-2020-book", "Claim one."),
        _passage("c2", "alpha-2020-book", "Claim two."),
    )
    same_content_different_ids = (
        _passage("c9", "alpha-2020-book", "Claim one."),
        _passage("c10", "alpha-2020-book", "Claim two."),
    )
    reordered = (a[1], a[0])

    assert _members_key(a) == _members_key(same_content_different_ids)
    assert _members_key(a) != _members_key(reordered)
    assert _members_key(a) != _members_key(a[:1])


# ---------------------------------------------------------------------------
# _bag_state_reusable
# ---------------------------------------------------------------------------


def test_bag_state_reusable_requires_encoder_threshold_and_library_version():
    good = {
        "config": {
            "encoder": ENCODER_MODEL,
            "bag_distance_threshold": BAG_DISTANCE_THRESHOLD,
            "sklearn_version": _sklearn_version(),
        },
        "assignments": {"c1": 0},
        "centroids": {"0": [1.0, 0.0, 0.0]},
    }
    assert _bag_state_reusable(good) is True
    assert _bag_state_reusable(dict(good, config={**good["config"], "encoder": "other"})) is False
    assert (
        _bag_state_reusable(dict(good, config={**good["config"], "bag_distance_threshold": 0.3}))
        is False
    )
    assert (
        _bag_state_reusable(dict(good, config={**good["config"], "sklearn_version": "0"})) is False
    )
    assert _bag_state_reusable(None) is False
    assert _bag_state_reusable({}) is False
    # Malformed shape: config present but assignments/centroids missing.
    assert _bag_state_reusable({"config": good["config"]}) is False


def test_load_json_or_none_tolerates_a_missing_or_corrupt_file(tmp_path: Path):
    assert _load_json_or_none(tmp_path / "nope.json") is None
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert _load_json_or_none(corrupt) is None


def test_write_bag_state_round_trips_through_bag_state_path_and_is_reusable(tmp_path: Path):
    known = [_passage(f"ca{i}", "alpha-2020-book", f"Claim A{i}.") for i in range(3)]
    bags = {0: known}
    centroids = {0: np.mean(_GROUP_A, axis=0)}
    outdir = tmp_path / "pin1"

    _write_bag_state(_bag_state_path(outdir), bags, centroids)
    state = _load_json_or_none(_bag_state_path(outdir))

    assert state is not None
    assert _bag_state_reusable(state) is True
    assert set(state["assignments"]) == {p.chunk_id for p in known}
    assert state["assignments"]["ca0"] == 0
    assert state["centroids"]["0"] == pytest.approx(list(np.mean(_GROUP_A, axis=0)))


# ---------------------------------------------------------------------------
# _incremental_bag_passages: known labels kept, near point accepted, a
# genuinely new cluster offsets above the existing maximum
# ---------------------------------------------------------------------------


def _prior_state_from(bags: dict[int, list[Passage]], vectors_by_chunk_id: dict[str, list[float]]):
    assignments = {p.chunk_id: label for label, members in bags.items() for p in members}
    centroids = {
        str(label): np.mean([vectors_by_chunk_id[p.chunk_id] for p in members], axis=0).tolist()
        for label, members in bags.items()
    }
    return {
        "config": {
            "encoder": ENCODER_MODEL,
            "bag_distance_threshold": BAG_DISTANCE_THRESHOLD,
            "sklearn_version": _sklearn_version(),
        },
        "assignments": assignments,
        "centroids": centroids,
    }


def test_incremental_bag_passages_keeps_known_labels_accepts_near_point_and_offsets_residue():
    known_a = [_passage(f"ca{i}", "alpha-2020-book", f"Claim A{i}.") for i in range(3)]
    known_b = [_passage(f"cb{i}", "alpha-2020-book", f"Claim B{i}.") for i in range(2)]
    vectors_by_chunk_id = {
        **{p.chunk_id: v for p, v in zip(known_a, _GROUP_A)},
        **{p.chunk_id: v for p, v in zip(known_b, _GROUP_B)},
    }
    prior_state = _prior_state_from({0: known_a, 1: known_b}, vectors_by_chunk_id)

    new_near_a = _passage("c_new_near_a", "beta-2021-book", "Claim near A.")
    new_residue = _passage("c_new_residue", "beta-2021-book", "Claim residue.")
    passages = [*known_a, *known_b, new_near_a, new_residue]
    encode = _vector_lookup_encode(
        {"Claim near A.": _ACCEPTED_NEAR_A, "Claim residue.": _RESIDUE_POINT}
    )

    bags, centroids, new_count = _incremental_bag_passages(passages, encode, prior_state)

    assert new_count == 2
    # Every known chunk_id kept its prior bag.
    assert {p.chunk_id for p in bags[0]} >= {p.chunk_id for p in known_a}
    assert {p.chunk_id for p in bags[1]} == {p.chunk_id for p in known_b}
    # The near-duplicate is accepted into bag 0 (nearest centroid, well
    # within BAG_DISTANCE_THRESHOLD), never bag 1 or a residue bag.
    assert new_near_a.chunk_id in {p.chunk_id for p in bags[0]}
    # The genuinely new direction is NOT swallowed into either existing bag,
    # and its label is disjoint from and above what already existed (0, 1).
    residue_label = next(label for label, members in bags.items() if new_residue in members)
    assert residue_label not in (0, 1)
    assert residue_label > 1
    # Only the touched bag's centroid moved.
    assert centroids[1] == pytest.approx(np.mean(_GROUP_B, axis=0))
    assert not np.allclose(centroids[0], np.mean(_GROUP_A, axis=0))


def test_incremental_bag_passages_with_no_new_passages_is_a_pure_relabel():
    known_a = [_passage(f"ca{i}", "alpha-2020-book", f"Claim A{i}.") for i in range(3)]
    vectors_by_chunk_id = {p.chunk_id: v for p, v in zip(known_a, _GROUP_A)}
    prior_state = _prior_state_from({0: known_a}, vectors_by_chunk_id)

    bags, centroids, new_count = _incremental_bag_passages(
        known_a, _vector_lookup_encode({}), prior_state
    )

    assert new_count == 0
    assert set(bags) == {0}
    assert {p.chunk_id for p in bags[0]} == {p.chunk_id for p in known_a}
    assert centroids[0] == pytest.approx(np.mean(_GROUP_A, axis=0))


def test_incremental_bag_passages_uses_average_linkage_not_cosine_to_centroid_direction():
    """Pins the criterion (coordinator review, #677 slice B): placement
    must be decided by AVERAGE LINKAGE -- the mean distance to the bag's
    actual members, `1 - dot(vector, centroid)` against the centroid AS
    STORED -- never by cosine distance to the centroid's own renormalised
    direction. A bag whose two members sit 150 degrees apart has a
    centroid whose OWN direction a candidate vector can match exactly
    (cosine distance to that direction == 0, always passes) while the mean
    distance to the bag's real members is still far over
    `BAG_DISTANCE_THRESHOLD` (measured: 0.741). Accepting this point would
    be the bug this fix closes -- it must go to residue instead."""
    member_a = [1.0, 0.0]
    member_b = [math.cos(math.radians(150)), math.sin(math.radians(150))]
    known = [
        _passage("c1", "alpha-2020-book", "Claim one."),
        _passage("c2", "alpha-2020-book", "Claim two."),
    ]
    vectors_by_chunk_id = {"c1": member_a, "c2": member_b}
    prior_state = _prior_state_from({0: known}, vectors_by_chunk_id)

    # The centroid's own (renormalised) direction bisects the 150-degree
    # angle, at 75 degrees -- a candidate placed exactly there has cosine
    # distance 0 to that direction, but average-linkage distance 0.741.
    centroid_direction = [math.cos(math.radians(75)), math.sin(math.radians(75))]
    new_passage = _passage("c_new", "beta-2021-book", "Claim aligned with centroid direction.")
    encode = _vector_lookup_encode({"Claim aligned with centroid direction.": centroid_direction})

    bags, _centroids, new_count = _incremental_bag_passages(
        [*known, new_passage], encode, prior_state
    )

    assert new_count == 1
    assert new_passage not in bags[0]
    residue_label = next(label for label, members in bags.items() if new_passage in members)
    assert residue_label != 0


# ---------------------------------------------------------------------------
# _seed_reads_from_prior_pin
# ---------------------------------------------------------------------------


def test_seed_reads_from_prior_pin_seeds_only_pending_content_matched_jobs(tmp_path: Path):
    unaffected = ExtractJob(
        bag=1,
        slice_index=0,
        members=(_passage("c1", "alpha-2020-book", "Claim one."),),
    )
    grown = ExtractJob(
        bag=0,
        slice_index=0,
        members=(
            _passage("c2", "alpha-2020-book", "Claim two."),
            _passage("c3", "beta-2021-book", "Claim three."),  # new member -> content changed
        ),
    )
    already_done = ExtractJob(
        bag=2,
        slice_index=0,
        members=(_passage("c4", "alpha-2020-book", "Claim four."),),
    )

    prior_reads_path = tmp_path / "prior" / "reads.jsonl"
    append_checkpoint_record(
        prior_reads_path,
        {
            "bag": 5,  # different numbering in the prior pin -- must be rewritten
            "slice": 0,
            "members_key": _members_key(unaffected.members),
            "shown": 1,
            "positions": [{"argument": "An argument.", "chunk_ids": ["c1"]}],
            "unassigned": 0,
        },
    )
    append_checkpoint_record(
        prior_reads_path,
        {
            "bag": 6,
            "slice": 0,
            "members_key": "deadbeef00000000",  # matches nothing in this run's own jobs
            "shown": 1,
            "positions": [],
            "unassigned": 0,
        },
    )

    reads_path = tmp_path / "current" / "reads.jsonl"
    append_checkpoint_record(
        reads_path,
        {
            "bag": 2,
            "slice": 0,
            "members_key": _members_key(already_done.members),
            "shown": 1,
            "positions": [],
        },
    )

    _seed_reads_from_prior_pin(
        [unaffected, grown, already_done], reads_path, prior_reads_path, log=lambda _msg: None
    )

    records = load_checkpoint_records(reads_path, CorruptReadsLedgerError)
    by_key = {(r["bag"], r["slice"]): r for r in records}
    # The unaffected job was seeded, with its bag/slice rewritten to THIS
    # job's own numbering (1, 0), not the prior pin's (5, 0).
    assert (1, 0) in by_key
    assert by_key[(1, 0)]["positions"][0]["argument"] == "An argument."
    # The grown job has no content match in the prior ledger -- never seeded.
    assert (0, 0) not in by_key
    # The already-done job was already on this pin's own ledger -- untouched,
    # never overwritten by a seed attempt.
    assert by_key[(2, 0)]["shown"] == 1
    assert len(records) == 2


def test_seed_reads_from_prior_pin_no_op_when_prior_ledger_is_absent(tmp_path: Path):
    reads_path = tmp_path / "reads.jsonl"
    job = ExtractJob(bag=0, slice_index=0, members=(_passage("c1", "alpha-2020-book", "Claim."),))

    _seed_reads_from_prior_pin(
        [job], reads_path, tmp_path / "nope" / "reads.jsonl", log=lambda _m: None
    )

    assert not reads_path.exists()


# ---------------------------------------------------------------------------
# End to end: run_map_build across two pins over a growing corpus
# ---------------------------------------------------------------------------


class _RecordingClient:
    """Returns an empty `arguments`/`unassigned` response for every call --
    these tests assert on which (bag, slice) got CALLED, not on position
    content, which `test_argmap_positions.py` already covers."""

    def __init__(self) -> None:
        self.call_count = 0
        self.seen_prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        self.seen_prompts.append(prompt)
        return json.dumps({"arguments": [], "unassigned": []})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "recording"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return None


def _write_answer(answers_dir: Path, source_id: str, chunk_id: str, claim: str) -> None:
    answers_dir.mkdir(parents=True, exist_ok=True)
    path = answers_dir / f"{source_id}.jsonl"
    record = {
        "source_id": source_id,
        "chunk_id": chunk_id,
        "answers": {
            "claim": claim,
            "mechanism": "a mechanism",
            "comparison": "not-in-passage",
            "concedes": "not-in-passage",
            "assumes": "not-in-passage",
            "position_of": "not-in-passage",
            "ranges_over": "not-in-passage",
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _distance_threshold_cluster(vectors: np.ndarray, threshold: float) -> list[int]:
    """A pure-Python distance-threshold agglomeration equivalent to
    `_agglomerative_cluster`'s own real (sklearn-backed) clustering, over
    this file's own well-separated fixtures (within-group distance ~0.0002,
    between-group ~1.0, so greedy nearest-first-match reproduces true
    average-linkage exactly here). Monkeypatched in for the end-to-end
    tests below so they never need scikit-learn installed -- mirrors
    `test_argmap_relations.py`'s own `_identity_cluster` monkeypatch."""
    reps: list[np.ndarray] = []
    labels: list[int] = []
    for vector in vectors:
        vector = np.asarray(vector, dtype=np.float64)
        match = None
        for label, rep in enumerate(reps):
            denom = float(np.linalg.norm(vector) * np.linalg.norm(rep))
            distance = 1.0 if denom == 0.0 else 1.0 - float(np.dot(vector, rep)) / denom
            if distance <= threshold:
                match = label
                break
        if match is None:
            match = len(reps)
            reps.append(vector)
        labels.append(match)
    return labels


def _build(tmp_path: Path, *, pin: str, client: Any, vectors_by_claim: dict, force: bool = False):
    return run_map_build(
        answers_dir=tmp_path / "answers",
        trees_dir=tmp_path / "trees",
        map_dir=tmp_path / "map",
        client=client,
        encode=_vector_lookup_encode(vectors_by_claim),
        pin=pin,
        guard=False,
        force=force,
        log=lambda _msg: None,
    )


def test_run_map_build_reuses_an_unaffected_bag_and_reasks_a_grown_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr("axial.argmap.build._agglomerative_cluster", _distance_threshold_cluster)
    answers_dir = tmp_path / "answers"
    for i, vector in enumerate(_GROUP_A):
        _write_answer(
            answers_dir, "alpha-2020-book", f"alpha-2020-book_0{i}0_body_001", f"Claim A{i}."
        )
    for i, vector in enumerate(_GROUP_B):
        _write_answer(
            answers_dir, "alpha-2020-book", f"alpha-2020-book_1{i}0_body_001", f"Claim B{i}."
        )
    run1_vectors = {f"Claim A{i}.": v for i, v in enumerate(_GROUP_A)}
    run1_vectors.update({f"Claim B{i}.": v for i, v in enumerate(_GROUP_B)})

    run1_client = _RecordingClient()
    manifest1 = _build(tmp_path, pin="pin1", client=run1_client, vectors_by_claim=run1_vectors)
    assert manifest1["counts"]["bags"] == 2
    assert run1_client.call_count == 2  # one read per bag, both fit in one EXTRACT_SLICE

    # A new source: two near-A passages (join bag 0) and one genuinely new
    # direction (a fresh residue bag). alpha's own passages are unchanged.
    _write_answer(answers_dir, "beta-2021-book", "beta-2021-book_010_body_001", "Claim near A.")
    _write_answer(answers_dir, "beta-2021-book", "beta-2021-book_020_body_001", "Claim near A 2.")
    _write_answer(answers_dir, "beta-2021-book", "beta-2021-book_030_body_001", "Claim residue.")
    run2_vectors = dict(run1_vectors)
    run2_vectors["Claim near A."] = _ACCEPTED_NEAR_A
    run2_vectors["Claim near A 2."] = [0.96, 0.01, 0.0]
    run2_vectors["Claim residue."] = _RESIDUE_POINT

    run2_client = _RecordingClient()
    manifest2 = _build(tmp_path, pin="pin2", client=run2_client, vectors_by_claim=run2_vectors)

    counts = manifest2["counts"]
    # 3 bags: the unaffected B bag, the grown A bag, and a new residue bag.
    assert counts["bags"] == 3
    assert counts["units_total"] == 3
    # The unaffected bag's own read is reused -- no call for it.
    assert counts["units_reused"] == 1
    assert counts["units_asked"] == 2
    # Both asked reads touch beta-2021-book, absent from pin1's manifest.
    assert counts["units_asked_touching_new"] == 2
    assert run2_client.call_count == 2

    # The known alpha chunk_ids kept their own bag label across the pins.
    state1 = json.loads((tmp_path / "map" / "pin1" / "bag_state.json").read_text(encoding="utf-8"))
    state2 = json.loads((tmp_path / "map" / "pin2" / "bag_state.json").read_text(encoding="utf-8"))
    for chunk_id, label in state1["assignments"].items():
        assert state2["assignments"][chunk_id] == label

    # A rerun of the exact same pin (no corpus change) asks nothing.
    rerun_client = _RecordingClient()
    manifest3 = _build(tmp_path, pin="pin2", client=rerun_client, vectors_by_claim=run2_vectors)
    assert manifest3["counts"]["units_asked"] == 0
    assert manifest3["counts"]["units_reused"] == manifest3["counts"]["units_total"]
    assert rerun_client.call_count == 0


def test_run_map_build_force_skips_incremental_bagging_and_seeding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr("axial.argmap.build._agglomerative_cluster", _distance_threshold_cluster)
    answers_dir = tmp_path / "answers"
    for i, vector in enumerate(_GROUP_A):
        _write_answer(
            answers_dir, "alpha-2020-book", f"alpha-2020-book_0{i}0_body_001", f"Claim A{i}."
        )
    vectors = {f"Claim A{i}.": v for i, v in enumerate(_GROUP_A)}

    _build(tmp_path, pin="pin1", client=_RecordingClient(), vectors_by_claim=vectors)

    forced_client = _RecordingClient()
    manifest = _build(
        tmp_path, pin="pin2", client=forced_client, vectors_by_claim=vectors, force=True
    )

    # Nothing was seeded (force never even looks at a prior pin), so every
    # read under the new pin is freshly asked despite identical content.
    assert manifest["counts"]["units_reused"] == 0
    assert manifest["counts"]["units_asked"] == manifest["counts"]["units_total"]
    assert forced_client.call_count == manifest["counts"]["units_total"]
