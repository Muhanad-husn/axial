"""Unit tests for `axial.materialize._resolved_opposition_edges` (issue
#651): folding the semantic residue resolver's own content-keyed decision
log (`axial.argmap.residue`) into `note_opposed_position` rows. Offline
throughout -- plain JSONL fixtures, no LLM, no answers/inventory/alias-map
scaffolding (`tests/analysis/test_relational_store.py` owns the full
`build_note_store` pipeline contract; this is the one new join it adds).
"""

from __future__ import annotations

import json
from pathlib import Path

from axial.materialize import _resolved_opposition_edges


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _decision(
    key: str,
    chunk_id: str,
    source_id: str | None,
    target: str,
    mode: str,
    matches: list[str],
) -> dict:
    return {
        "key": key,
        "chunk_id": chunk_id,
        "source_id": source_id,
        "target": target,
        "section": None,
        "mode": mode,
        "candidate_ids": matches,
        "matches": matches,
    }


def test_no_paths_means_no_rows(tmp_path: Path) -> None:
    assert _resolved_opposition_edges(None, None) == []


def test_missing_decision_log_means_no_rows_not_an_error(tmp_path: Path) -> None:
    positions_path = tmp_path / "positions.jsonl"
    _write_jsonl(positions_path, [{"position_id": "pos-0001", "sources": ["alpha-2020-book"]}])
    decisions_path = tmp_path / "residue_decisions.jsonl"  # never written

    assert _resolved_opposition_edges(decisions_path, positions_path) == []


def test_one_decision_becomes_one_row(tmp_path: Path) -> None:
    positions_path = tmp_path / "positions.jsonl"
    _write_jsonl(positions_path, [{"position_id": "pos-0001", "sources": ["beta-2019-book"]}])
    decisions_path = tmp_path / "residue_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            _decision(
                "k1",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "a paraphrased opposing claim",
                "unblocked",
                ["pos-0001"],
            )
        ],
    )

    rows = _resolved_opposition_edges(decisions_path, positions_path)

    assert rows == [
        (
            "alpha-2020-book_001_intro_001",
            "alpha-2020-book",
            "a paraphrased opposing claim",
            "pos-0001",
            "unblocked",
            0,
        )
    ]


def test_an_empty_matches_record_contributes_no_row(tmp_path: Path) -> None:
    positions_path = tmp_path / "positions.jsonl"
    _write_jsonl(positions_path, [{"position_id": "pos-0001", "sources": ["beta-2019-book"]}])
    decisions_path = tmp_path / "residue_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            _decision(
                "k1",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "opposes nothing on the map",
                "unblocked",
                [],
            )
        ],
    )

    assert _resolved_opposition_edges(decisions_path, positions_path) == []


def test_matched_by_both_arms_is_labelled_both(tmp_path: Path) -> None:
    positions_path = tmp_path / "positions.jsonl"
    _write_jsonl(positions_path, [{"position_id": "pos-0001", "sources": ["beta-2019-book"]}])
    decisions_path = tmp_path / "residue_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            _decision(
                "k-blocked",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "a claim two arms both land on",
                "blocked",
                ["pos-0001"],
            ),
            _decision(
                "k-unblocked",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "a claim two arms both land on",
                "unblocked",
                ["pos-0001"],
            ),
        ],
    )

    rows = _resolved_opposition_edges(decisions_path, positions_path)

    assert len(rows) == 1
    assert rows[0][4] == "both"


def test_matched_by_one_arm_only_keeps_that_arms_label(tmp_path: Path) -> None:
    positions_path = tmp_path / "positions.jsonl"
    _write_jsonl(
        positions_path,
        [
            {"position_id": "pos-0001", "sources": ["beta-2019-book"]},
            {"position_id": "pos-0002", "sources": ["beta-2019-book"]},
        ],
    )
    decisions_path = tmp_path / "residue_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            _decision(
                "k-blocked",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "a claim only the blocked arm lands on",
                "blocked",
                ["pos-0001"],
            ),
            _decision(
                "k-unblocked",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "a claim only the blocked arm lands on",
                "unblocked",
                ["pos-0002"],
            ),
        ],
    )

    rows = _resolved_opposition_edges(decisions_path, positions_path)

    by_position = {row[3]: row[4] for row in rows}
    assert by_position == {"pos-0001": "blocked", "pos-0002": "unblocked"}


def test_self_referential_when_the_notes_own_source_matches_the_positions(tmp_path: Path) -> None:
    """The target and the matched position drawn from the same book (issue
    #651's own measured example: a note stating an opposing view and, in the
    same breath, the claim the argument map extracted from that exact
    passage) -- a real match, but not the cross-source opposition #651 is
    chasing, so it must be flagged rather than mixed silently into a
    resolved count."""
    positions_path = tmp_path / "positions.jsonl"
    _write_jsonl(
        positions_path,
        [
            {"position_id": "pos-0001", "sources": ["alpha-2020-book"]},
            {"position_id": "pos-0002", "sources": ["beta-2019-book", "gamma-2021-book"]},
        ],
    )
    decisions_path = tmp_path / "residue_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            _decision(
                "k1",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "a same-book self-referential match",
                "unblocked",
                ["pos-0001"],
            ),
            _decision(
                "k2",
                "alpha-2020-book_002_intro_002",
                "alpha-2020-book",
                "a genuine cross-source match",
                "unblocked",
                ["pos-0002"],
            ),
        ],
    )

    rows = _resolved_opposition_edges(decisions_path, positions_path)

    by_position = {row[3]: row[5] for row in rows}
    assert by_position["pos-0001"] == 1  # self-referential: same source
    assert by_position["pos-0002"] == 0  # cross-source: a real opposition edge


def test_the_last_record_on_disk_under_a_repeated_key_wins(tmp_path: Path) -> None:
    """Content-keyed (issue #486): a decision log is a written history a
    resumed run only ever appends to, but if the same key is somehow
    written twice, the fold must read the log the same way
    `axial.argmap.residue.load_decisions` does -- last one on disk wins."""
    positions_path = tmp_path / "positions.jsonl"
    _write_jsonl(positions_path, [{"position_id": "pos-0001", "sources": ["beta-2019-book"]}])
    decisions_path = tmp_path / "residue_decisions.jsonl"
    _write_jsonl(
        decisions_path,
        [
            _decision(
                "k1", "alpha-2020-book_001_intro_001", "alpha-2020-book", "a claim", "unblocked", []
            ),
            _decision(
                "k1",
                "alpha-2020-book_001_intro_001",
                "alpha-2020-book",
                "a claim",
                "unblocked",
                ["pos-0001"],
            ),
        ],
    )

    rows = _resolved_opposition_edges(decisions_path, positions_path)

    assert len(rows) == 1
    assert rows[0][3] == "pos-0001"
