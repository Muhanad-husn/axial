"""Acceptance tests for issue #572, PR 2 of 4: the argument map's relation
layer (`axial.argmap.build`'s neighbourhood/relate functions) -- a port of
the scratchpad's own `stage2_relations.py`, already run and measured over
the real corpus; these tests pin the behavioral contract the port must
preserve, not a new design. Fixtures and a fake client throughout -- no real
model call, no dependence on `data/` (a worktree has none), and no
dependence on scikit-learn being installed (every clustering call here is
either injected or hits `build_neighbourhoods`'s own no-op shortcuts).

Covered here:

  - an oversized coarse group is split recursively until no neighbourhood
    exceeds `MAX_NEIGHBOURHOOD`, and singletons are skipped;
  - neighbourhood keys are stable across two runs on identical positions
    regardless of input order, so the resume ledger is sound;
  - the rendered listing carries no author, book, or year;
  - a relation naming a handle that was not offered is dropped and
    counted, and so is a self-relation;
  - resume: a populated relation ledger makes no call for a neighbourhood
    already on disk;
  - a full `run_map_build` continues past positions into relations,
    writing `relations.jsonl` with position ids that resolve back to real
    positions, and `--force` re-asks both stages while preserving the
    prior ledgers.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from axial.llm import StubLLMClient
from axial.argmap.build import (
    MAX_NEIGHBOURHOOD,
    Neighbourhood,
    build_neighbourhoods,
    relate_neighbourhood,
    render_positions_blind,
    run_map_build,
    run_relations,
)

# ---------------------------------------------------------------------------
# build_neighbourhoods: oversized groups split, singletons skipped
# ---------------------------------------------------------------------------


def _position(position_id: str, argument: str = "Shared argument text.") -> dict[str, Any]:
    return {
        "position_id": position_id,
        "argument": argument,
        "variants": [argument],
        "chunk_ids": [f"c-{position_id}"],
        "sources": ["alpha-2020-book"],
        "authors": ["alpha"],
        "size": 1,
        "named_times": 1,
    }


def _fake_encode_by_index(texts: Any) -> np.ndarray:
    # Content is irrelevant to every cluster_fn used in this file -- only
    # vector COUNT matters, so a trivial index vector is enough.
    return np.arange(len(texts)).reshape(-1, 1).astype(float)


def _make_scripted_cluster_fn(script: list[list[int]]):
    """Returns labels from `script` in call order, ignoring `n_clusters`
    (irrelevant here -- these tests fix the exact group sizes by hand to
    exercise the SPLIT recursion deterministically, without needing real
    scikit-learn clustering installed)."""
    calls = {"n": 0}

    def cluster_fn(vectors: np.ndarray, n_clusters: int) -> list[int]:
        labels = script[calls["n"]]
        calls["n"] += 1
        assert len(labels) == len(vectors)
        return labels

    return cluster_fn


def test_an_oversized_neighbourhood_is_split_until_none_exceeds_the_max_and_singletons_are_skipped() -> (
    None
):
    # 55 positions: a coarse pass puts 53 of them in one group (mirrors the
    # real 53-position group the scratchpad run measured) and 2 in
    # singleton groups of their own.
    positions = [_position(f"pos-{i:04d}") for i in range(1, 56)]

    coarse_labels = [0] * 53 + [1] + [2]
    # The oversized group of 53 is split on the second call into 7 pieces,
    # each well under MAX_NEIGHBOURHOOD -- so the recursion stops there.
    split_labels = [i % 7 for i in range(53)]
    cluster_fn = _make_scripted_cluster_fn([coarse_labels, split_labels])

    neighbourhoods = build_neighbourhoods(positions, _fake_encode_by_index, cluster_fn=cluster_fn)

    assert all(len(n.position_ids) <= MAX_NEIGHBOURHOOD for n in neighbourhoods)
    # The two singleton groups (label 1, label 2) never became a
    # neighbourhood: only the 53 split members are covered.
    covered = {pid for n in neighbourhoods for pid in n.position_ids}
    assert len(covered) == 53
    assert "pos-0054" not in covered
    assert "pos-0055" not in covered
    # 53 split round-robin over 7 buckets -> 7 non-empty pieces, all kept.
    assert len(neighbourhoods) == 7


def test_neighbourhood_keys_are_stable_across_two_runs_regardless_of_input_order() -> None:
    positions = [_position(f"pos-{i:04d}") for i in range(1, 9)]  # 8 positions, one group
    cluster_fn_first = _make_scripted_cluster_fn([[0] * 8])
    first = build_neighbourhoods(positions, _fake_encode_by_index, cluster_fn=cluster_fn_first)

    reordered = [
        positions[3],
        positions[0],
        positions[7],
        positions[1],
        positions[2],
        positions[6],
        positions[5],
        positions[4],
    ]
    cluster_fn_second = _make_scripted_cluster_fn([[0] * 8])
    second = build_neighbourhoods(reordered, _fake_encode_by_index, cluster_fn=cluster_fn_second)

    assert {n.key for n in first} == {n.key for n in second}
    assert [n.position_ids for n in first] == [n.position_ids for n in second]


def test_a_single_position_and_an_empty_set_yield_no_neighbourhoods() -> None:
    assert build_neighbourhoods([], _fake_encode_by_index) == []
    assert build_neighbourhoods([_position("pos-0001")], _fake_encode_by_index) == []


# ---------------------------------------------------------------------------
# render_positions_blind: no author, book, or year
# ---------------------------------------------------------------------------


def test_render_positions_blind_carries_no_author_or_source() -> None:
    by_id = {
        "pos-0001": _position("pos-0001", "States extract resources through coercion."),
        "pos-0002": _position("pos-0002", "Ethnic identity is socially constructed."),
    }
    by_id["pos-0001"]["authors"] = ["elcheroth"]
    by_id["pos-0001"]["sources"] = ["elcheroth-2017-abc"]
    by_id["pos-0002"]["authors"] = ["malesevic"]
    by_id["pos-0002"]["sources"] = ["malesevic-2010-xyz"]
    neighbourhood = Neighbourhood(key="k1", position_ids=("pos-0001", "pos-0002"))

    listing, handles = render_positions_blind(neighbourhood, by_id)

    assert listing == (
        "[a1] States extract resources through coercion.\n"
        "[a2] Ethnic identity is socially constructed."
    )
    assert "elcheroth" not in listing
    assert "malesevic" not in listing
    assert "2017" not in listing
    assert "2010" not in listing
    assert handles == {"a1": "pos-0001", "a2": "pos-0002"}


# ---------------------------------------------------------------------------
# relate_neighbourhood: an invented handle and a self-relation are dropped
# ---------------------------------------------------------------------------


class _ScriptedClient(StubLLMClient):
    def __init__(self, response: str) -> None:
        super().__init__()
        self._response = response

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return self._response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "scripted"


def test_an_invented_handle_and_a_self_relation_are_both_dropped_and_counted() -> None:
    by_id = {
        "pos-0001": _position("pos-0001", "Argument one."),
        "pos-0002": _position("pos-0002", "Argument two."),
        "pos-0003": _position("pos-0003", "Argument three."),
    }
    neighbourhood = Neighbourhood(key="k1", position_ids=("pos-0001", "pos-0002", "pos-0003"))
    response = json.dumps(
        {
            "relations": [
                {"from": "a1", "to": "a2", "relation": " Extends ", "says": "a1 extends a2"},
                {"from": "a1", "to": "a99", "relation": "ghost", "says": "invented handle"},
                {"from": "a3", "to": "a3", "relation": "self", "says": "self relation"},
            ]
        }
    )
    client = _ScriptedClient(response)

    record = relate_neighbourhood(neighbourhood, by_id, client)

    assert record["relations"] == [
        {
            "from_position_id": "pos-0001",
            "to_position_id": "pos-0002",
            "relation": "extends",
            "says": "a1 extends a2",
        }
    ]
    assert record["dropped"] == 2
    assert "error" not in record


def test_a_malformed_response_is_recorded_as_a_failed_read_not_a_crash() -> None:
    by_id = {"pos-0001": _position("pos-0001"), "pos-0002": _position("pos-0002")}
    neighbourhood = Neighbourhood(key="k1", position_ids=("pos-0001", "pos-0002"))
    client = _ScriptedClient(json.dumps(["not", "the", "expected", "shape"]))

    record = relate_neighbourhood(neighbourhood, by_id, client)

    assert "error" in record
    assert record["relations"] == []


# ---------------------------------------------------------------------------
# run_relations: resume skips a neighbourhood already on disk
# ---------------------------------------------------------------------------


class _CountingClient(StubLLMClient):
    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return json.dumps({"relations": []})

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "counting"


def test_resume_makes_no_call_for_a_neighbourhood_already_on_disk(tmp_path: Path) -> None:
    reads_path = tmp_path / "relation_reads.jsonl"
    reads_path.write_text(
        json.dumps({"neighbourhood": "k-done", "positions": 2, "relations": [], "dropped": 0})
        + "\n",
        encoding="utf-8",
    )

    by_id = {
        "pos-0001": _position("pos-0001"),
        "pos-0002": _position("pos-0002"),
        "pos-0003": _position("pos-0003"),
    }
    neighbourhood_done = Neighbourhood(key="k-done", position_ids=("pos-0001", "pos-0002"))
    neighbourhood_pending = Neighbourhood(key="k-pending", position_ids=("pos-0002", "pos-0003"))
    client = _CountingClient()

    reads = run_relations(
        [neighbourhood_done, neighbourhood_pending],
        by_id,
        client=client,
        reads_path=reads_path,
        workers=2,
        log=lambda _msg: None,
    )

    assert client.call_count == 1
    assert len(reads) == 2
    keys = {r["neighbourhood"] for r in reads}
    assert keys == {"k-done", "k-pending"}


# ---------------------------------------------------------------------------
# run_map_build: continues into relations; --force re-asks both stages
# ---------------------------------------------------------------------------


def _record(chunk_id: str, source_id: str, claim: str, **extra_answers: Any) -> dict[str, Any]:
    answers = {
        "claim": claim,
        "mechanism": "coercive taxation",
        "comparison": "not-in-passage",
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
        "position_of": "not-in-passage",
        "ranges_over": "not-in-passage",
    }
    answers.update(extra_answers)
    return {"source_id": source_id, "chunk_id": chunk_id, "answers": answers}


def _write_four_passages(answers_dir: Path) -> None:
    answers_dir.mkdir(parents=True, exist_ok=True)
    with (answers_dir / "alpha-2020-book.jsonl").open("w", encoding="utf-8") as handle:
        for i in (1, 2):
            handle.write(
                json.dumps(
                    _record(f"alpha-2020-book_00{i}", "alpha-2020-book", f"Alpha claim {i}.")
                )
                + "\n"
            )
    with (answers_dir / "beta-2019-book.jsonl").open("w", encoding="utf-8") as handle:
        for i in (1, 2):
            handle.write(
                json.dumps(_record(f"beta-2019-book_00{i}", "beta-2019-book", f"Beta claim {i}."))
                + "\n"
            )


class _TwoStageClient(StubLLMClient):
    """Routes to a canned response per `pass_name`, so one client can drive
    both the extraction pass and the relate pass of a full `run_map_build`
    in one scripted test."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: collections.Counter[str] = collections.Counter()

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls[pass_name or ""] += 1
        if pass_name == "position_relate":
            return json.dumps(
                {
                    "relations": [
                        # pos-0001 -> pos-0003: a real, cross-author relation.
                        {"from": "a1", "to": "a3", "relation": " Extends ", "says": "extends it"},
                        # a99 is never offered -- dropped.
                        {"from": "a1", "to": "a99", "relation": "ghost", "says": "x"},
                        # a2 -> a2 is a self-relation -- dropped.
                        {"from": "a2", "to": "a2", "relation": "self", "says": "y"},
                    ]
                }
            )
        # position_extract: each job offers exactly one passage (handle p1)
        # because bag/merge clustering is monkeypatched to keep every
        # passage in its own bag and its own position (see the test below).
        return json.dumps(
            {
                "arguments": [{"argument": "Shared argument text.", "handles": ["p1"]}],
                "unassigned": [],
            }
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "scripted"


def _fake_encode_any(texts: Any) -> np.ndarray:
    return np.zeros((len(texts), 2))


def _identity_cluster(vectors: np.ndarray, threshold: float) -> list[int]:
    # Keeps every row its own group/bag/position regardless of content --
    # bypasses the real (sklearn-backed) distance-threshold clustering
    # `bag_passages`/`merge_positions` use by default, so this test never
    # needs scikit-learn installed.
    return list(range(len(vectors)))


def test_run_map_build_continues_into_relations_with_ids_resolving_to_real_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr("axial.argmap.build._agglomerative_cluster", _identity_cluster)
    _write_four_passages(tmp_path / "answers")

    client = _TwoStageClient()
    manifest = run_map_build(
        answers_dir=tmp_path / "answers",
        trees_dir=tmp_path / "trees",
        map_dir=tmp_path / "map",
        client=client,
        encode=_fake_encode_any,
        pin="testpin",
        guard=False,
        # workers=1: arrival order into raw_positions/merged positions is
        # otherwise thread-completion order, which this test's assertion
        # about WHICH position_id lands on which author does not need to
        # be robust to -- pin it to submission order instead.
        workers=1,
        log=lambda _msg: None,
    )
    outdir = tmp_path / "map" / "testpin"

    # 4 distinct positions -> one call each to position_extract.
    assert client.calls["position_extract"] == 4
    # 4 positions fit in one neighbourhood (well under MAX_NEIGHBOURHOOD)
    # -> exactly one call to position_relate.
    assert client.calls["position_relate"] == 1

    positions_on_disk = [
        json.loads(line)
        for line in (outdir / "positions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    real_ids = {p["position_id"] for p in positions_on_disk}
    assert len(real_ids) == 4

    relations_on_disk = [
        json.loads(line)
        for line in (outdir / "relations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(relations_on_disk) == 1
    relation = relations_on_disk[0]
    assert relation["from_position_id"] in real_ids
    assert relation["to_position_id"] in real_ids
    assert relation["from_position_id"] != relation["to_position_id"]
    assert relation["relation"] == "extends"
    assert relation["says"] == "extends it"

    relation_counts = manifest["relations"]["counts"]
    assert relation_counts["neighbourhoods_read"] == 1
    assert relation_counts["failed_reads"] == 0
    assert relation_counts["relations_asserted"] == 1
    assert relation_counts["pairs_possible"] == 4 * 3 // 2
    assert relation_counts["distinct_labels"] == 1
    assert relation_counts["dropped_relations"] == 2
    # pos-0001 is alpha's first passage, pos-0003 is beta's first (workers=1
    # above pins arrival order to submission order) -- a genuine
    # cross-author relation.
    assert relation_counts["cross_author_relations"] == 1


def test_force_reasks_both_stages_and_keeps_the_prior_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("axial.argmap.build.load_back_matter_sections", lambda trees_dir: {})
    monkeypatch.setattr("axial.argmap.build._agglomerative_cluster", _identity_cluster)
    _write_four_passages(tmp_path / "answers")

    def _build(client: _TwoStageClient, force: bool = False) -> Path:
        run_map_build(
            answers_dir=tmp_path / "answers",
            trees_dir=tmp_path / "trees",
            map_dir=tmp_path / "map",
            client=client,
            encode=_fake_encode_any,
            pin="testpin",
            guard=False,
            force=force,
            workers=1,
            log=lambda _msg: None,
        )
        return tmp_path / "map" / "testpin"

    first_client = _TwoStageClient()
    outdir = _build(first_client)
    relation_reads_path = outdir / "relation_reads.jsonl"
    reads_path = outdir / "reads.jsonl"
    assert first_client.calls["position_extract"] == 4
    assert first_client.calls["position_relate"] == 1
    prior_relation_ledger = relation_reads_path.read_text(encoding="utf-8")
    prior_reads_ledger = reads_path.read_text(encoding="utf-8")

    # Without --force: both stages resume, no new calls.
    resumed_client = _TwoStageClient()
    _build(resumed_client)
    assert resumed_client.calls["position_extract"] == 0
    assert resumed_client.calls["position_relate"] == 0
    assert relation_reads_path.read_text(encoding="utf-8") == prior_relation_ledger

    # With --force: both stages are re-asked, and both prior ledgers
    # survive on disk under a new name rather than being deleted.
    forced_client = _TwoStageClient()
    _build(forced_client, force=True)
    assert forced_client.calls["position_extract"] == 4
    assert forced_client.calls["position_relate"] == 1

    relation_siblings = list(outdir.glob("relation_reads.*.jsonl"))
    assert len(relation_siblings) == 1
    assert relation_siblings[0].read_text(encoding="utf-8") == prior_relation_ledger
    assert relation_reads_path.exists()

    reads_siblings = list(outdir.glob("reads.*.jsonl"))
    assert len(reads_siblings) == 1
    assert reads_siblings[0].read_text(encoding="utf-8") == prior_reads_ledger
    assert reads_path.exists()
