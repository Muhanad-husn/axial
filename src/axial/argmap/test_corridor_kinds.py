"""Issue #855: the corridor orders by relation KIND when the map's relations
have been filed under a committed kind (`axial vocabulary build --column
relation`), conflicts first; with no assignments on disk it keeps the bare
relation-count order it always had. The run record says which order ran and
which kinds the corridor used."""

from __future__ import annotations

import json
from pathlib import Path

from axial.answer.record import _map_retrieval_to_dict
from axial.answer.run_report import format_run_report
from axial.argmap.ask import (
    build_corridor,
    load_relation_kinds,
    run_map_ask_for_brief,
)
from axial.argmap.test_ask import _DecomposeOnlyClient, _brief, _fake_encode, _position, _write_map
from axial.argmap.ask import LandedPosition


def _landed(position_id: str = "pos-landed") -> LandedPosition:
    return LandedPosition(
        position_id=position_id, score=1.0, argument="x", size=1,
        sources=("src-1",), authors=("a",), chunk_ids=("n1",),
    )


def _relation(src: str, dst: str, label: str) -> dict:
    return {"from_position_id": src, "to_position_id": dst, "relation": label, "says": "s"}


def _kind_record(src: str, dst: str, label: str, category_id: str | None) -> dict:
    return {
        "from_position_id": src, "to_position_id": dst, "relation": label,
        "source_id": "", "column": "relation", "level": 1, "value": f"{label} -- s",
        "category_id": category_id, "refused": category_id is None,
    }


def _write_kinds(root: Path, records: list[dict], version: str = "rel-v1") -> Path:
    column_dir = root / "relation"
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "assignments.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    (column_dir / "manifest.json").write_text(
        json.dumps({"column": "relation", "scheme_version": version}), encoding="utf-8"
    )
    return root


POSITIONS = {
    pid: _position(pid, [f"n-{pid}"], [f"src-{pid}"], f"argument {pid}")
    for pid in ("pos-landed", "pos-support", "pos-conflict")
}

# `pos-support` is reached by TWO relations, `pos-conflict` by one: the
# count order puts support first, the kind order puts the conflict first.
RELATIONS = [
    _relation("pos-landed", "pos-support", "extends"),
    _relation("pos-support", "pos-landed", "restates"),
    _relation("pos-conflict", "pos-landed", "contradicts"),
]
KIND_RECORDS = [
    _kind_record("pos-landed", "pos-support", "extends", "inference"),
    _kind_record("pos-support", "pos-landed", "restates", "inference"),
    _kind_record("pos-conflict", "pos-landed", "contradicts", "conflict"),
]


def test_without_kinds_the_corridor_keeps_the_relation_count_order():
    corridor = build_corridor([_landed()], POSITIONS, RELATIONS)

    assert [p.position_id for p in corridor] == ["pos-support", "pos-conflict"]


def test_with_kinds_a_conflict_comes_before_a_position_more_relations_reach(tmp_path):
    kinds = load_relation_kinds(_write_kinds(tmp_path / "vocab", KIND_RECORDS))

    corridor = build_corridor([_landed()], POSITIONS, RELATIONS, kinds=kinds)

    assert [p.position_id for p in corridor] == ["pos-conflict", "pos-support"]
    by_id = {p.position_id: p for p in corridor}
    assert by_id["pos-conflict"].kinds == ("conflict",)
    assert by_id["pos-support"].kinds == ("inference", "inference")
    # The free labels are untouched.
    assert by_id["pos-conflict"].labels == ("contradicts <-",)


def test_a_relation_the_assignment_does_not_cover_is_unassigned_not_dropped(tmp_path):
    kinds = load_relation_kinds(_write_kinds(tmp_path / "vocab", KIND_RECORDS[:1]))

    corridor = build_corridor([_landed()], POSITIONS, RELATIONS, kinds=kinds)

    assert {p.position_id for p in corridor} == {"pos-support", "pos-conflict"}
    by_id = {p.position_id: p for p in corridor}
    assert by_id["pos-conflict"].kinds == (None,)
    # No conflict is known, so the count order decides.
    assert [p.position_id for p in corridor] == ["pos-support", "pos-conflict"]


def test_no_assignment_file_loads_as_no_kinds(tmp_path):
    assert load_relation_kinds(tmp_path / "nothing-here") is None


def _ask(tmp_path: Path, vocabulary_dir: Path):
    map_root = _write_map(tmp_path / "map", list(POSITIONS.values()), relations=RELATIONS)
    return run_map_ask_for_brief(
        _brief(),
        client=_DecomposeOnlyClient(["argument pos-landed"]),
        map_dir=map_root,
        pin="pin",
        encode=_fake_encode,
        vocabulary_dir=vocabulary_dir,
        top_k=1,
    )


def test_the_ask_orders_by_kind_by_default_when_assignments_exist(tmp_path):
    result = _ask(tmp_path, _write_kinds(tmp_path / "vocab", KIND_RECORDS))

    assert result.corridor_order == "kind"
    assert result.relation_scheme_version == "rel-v1"
    assert [p.position_id for p in result.corridor] == ["pos-conflict", "pos-support"]


def test_the_ask_falls_back_to_count_order_with_no_assignments(tmp_path):
    result = _ask(tmp_path, tmp_path / "empty-vocab")

    assert result.corridor_order == "count"
    assert [p.position_id for p in result.corridor] == ["pos-support", "pos-conflict"]


def test_the_run_record_says_which_kinds_the_corridor_used(tmp_path):
    result = _ask(tmp_path, _write_kinds(tmp_path / "vocab", KIND_RECORDS))

    payload = _map_retrieval_to_dict(result)

    assert payload["relation_kinds"] == {
        "order": "kind",
        "scheme_version": "rel-v1",
        "kind_counts": {"conflict": 1, "inference": 2},
        "unassigned": 0,
    }
    corridor = {entry["position_id"]: entry for entry in payload["corridor"]}
    assert corridor["pos-conflict"]["kinds"] == ["conflict"]


def test_a_count_order_run_record_carries_no_kinds_block(tmp_path):
    payload = _map_retrieval_to_dict(_ask(tmp_path, tmp_path / "empty-vocab"))

    assert "relation_kinds" not in payload
    assert all("kinds" not in entry for entry in payload["corridor"])


def test_the_run_report_prints_the_corridor_kinds():
    report = {
        "operational": {
            "corridor_kinds": {
                "order": "kind",
                "scheme_version": "rel-v1",
                "kind_counts": {"conflict": 1, "inference": 2},
                "unassigned": 0,
            }
        }
    }
    text = format_run_report(report)
    assert "corridor: order=kind" in text
    assert "conflict=1" in text


def test_the_ask_hands_synthesis_each_conflict_between_assembled_positions(tmp_path):
    """Issue #881: a conflict relation whose two positions both reached
    assembly comes back as a contested pair of their assembled chunks."""
    from axial.analyze.assembly import ContestedPair

    result = _ask(tmp_path, _write_kinds(tmp_path / "vocab", KIND_RECORDS))

    assert result.conflicts == (
        ContestedPair(
            from_chunk_ids=("n-pos-conflict",),
            to_chunk_ids=("n-pos-landed",),
            relation="contradicts",
        ),
    )
    payload = _map_retrieval_to_dict(result)
    assert payload["conflicts"] == [
        {
            "from_chunk_ids": ["n-pos-conflict"],
            "to_chunk_ids": ["n-pos-landed"],
            "relation": "contradicts",
        }
    ]


def test_without_kinds_the_ask_names_no_conflicts(tmp_path):
    result = _ask(tmp_path, tmp_path / "empty-vocab")

    assert result.conflicts == ()
