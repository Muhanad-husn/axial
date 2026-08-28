"""Inner unit tests for `axial.argmap.vocabulary_join.vocabulary_neighbours`
and `category_for_note` (issue #807): the deterministic table join that
reaches a passage through a category a derived vocabulary (issue #806)
assigned it, the way `positions_on` (issue #650) already reaches one through
a shared name.

Fixtures throughout, no model call, no dependence on `data/` -- a manifest
and an assignments file written to `tmp_path`, the same shape
`axial.vocabulary.build_vocabulary` persists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from axial.argmap.ask import LandedPosition
from axial.argmap.vocabulary_join import (
    ALL_REASONS,
    REASON_ASSIGNED,
    REASON_NOT_FOUND,
    REASON_OUT_OF_SCHEME,
    REASON_REFUSED,
    NoVocabularyError,
    category_for_note,
    vocabulary_neighbours,
)


def _position(position_id: str, chunk_ids: list[str], sources: list[str], **overrides: Any) -> dict:
    base = {
        "position_id": position_id,
        "argument": f"Argument of {position_id}.",
        "size": len(chunk_ids),
        "sources": sources,
        "authors": [f"{source}-author" for source in sources],
        "chunk_ids": chunk_ids,
    }
    base.update(overrides)
    return base


def _landed(position: dict) -> LandedPosition:
    return LandedPosition(
        position_id=position["position_id"],
        score=0.9,
        argument=position["argument"],
        size=position["size"],
        sources=tuple(position["sources"]),
        authors=tuple(position["authors"]),
        chunk_ids=tuple(position["chunk_ids"]),
    )


def _assignment(chunk_id: str, source_id: str, category_id: str | None, **overrides: Any) -> dict:
    record = {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "column": "mechanism",
        "element_index": 0,
        "level": 1,
        "value": f"value for {chunk_id}",
        "category_id": category_id,
        "refused": category_id is None,
    }
    record.update(overrides)
    return record


def _write_vocabulary(
    root: Path,
    column: str,
    assignments: list[dict],
    *,
    categories: list[dict] | None = None,
    max_level: int = 1,
) -> Path:
    column_dir = root / column
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "assignments.jsonl").write_text(
        "\n".join(json.dumps(record) for record in assignments), encoding="utf-8"
    )
    manifest = {
        "column": column,
        "scheme_version": "v1",
        "max_level": max_level,
        "categories": categories or [],
    }
    (column_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# category_for_note: the four distinguishable reasons
# ---------------------------------------------------------------------------


def test_category_for_note_returns_assigned_and_the_category_id():
    by_chunk = {"n1": [_assignment("n1", "src-1", "war-and-state")]}

    category_id, reason = category_for_note("n1", by_chunk)

    assert category_id == "war-and-state"
    assert reason == REASON_ASSIGNED


def test_category_for_note_distinguishes_refused_from_not_found():
    by_chunk = {"n1": [_assignment("n1", "src-1", None)]}

    refused_id, refused_reason = category_for_note("n1", by_chunk)
    not_found_id, not_found_reason = category_for_note("n2", by_chunk)

    assert (refused_id, refused_reason) == (None, REASON_REFUSED)
    assert (not_found_id, not_found_reason) == (None, REASON_NOT_FOUND)
    assert refused_reason != not_found_reason


def test_category_for_note_distinguishes_out_of_scheme_from_refused():
    by_chunk = {
        "n1": [_assignment("n1", "src-1", None, out_of_scheme="a stray answer")],
    }

    category_id, reason = category_for_note("n1", by_chunk)

    assert category_id is None
    assert reason == REASON_OUT_OF_SCHEME
    assert reason != REASON_REFUSED


# ---------------------------------------------------------------------------
# vocabulary_neighbours: the join itself
# ---------------------------------------------------------------------------


def test_neighbours_are_positions_whose_notes_share_a_category_with_landed(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    pos_other = _position("pos-other", ["n3"], ["src-2"])
    positions = [pos_landed, pos_other]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),
            _assignment("n3", "src-2", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert [p.position_id for p in result.positions] == ["pos-other"]
    neighbour = result.positions[0]
    assert neighbour.categories == ("war-and-state",)
    assert neighbour.chunk_ids == ("n3",)
    assert neighbour.sources == ("src-2",)
    assert [c.category_id for c in result.categories] == ["war-and-state"]


def test_a_position_already_landed_or_in_the_corridor_is_never_returned_again(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    pos_corridor = _position("pos-corridor", ["n2"], ["src-2"])
    pos_other = _position("pos-other", ["n3"], ["src-3"])
    positions = [pos_landed, pos_corridor, pos_other]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),
            _assignment("n2", "src-2", "war-and-state"),
            _assignment("n3", "src-3", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        {"pos-corridor"},
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert [p.position_id for p in result.positions] == ["pos-other"]


def test_a_refused_note_contributes_no_edge(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    pos_other = _position("pos-other", ["n3"], ["src-2"])
    positions = [pos_landed, pos_other]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", None),  # refused
            _assignment("n3", "src-2", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert result.positions == ()
    assert result.categories == ()


def test_a_note_never_answered_the_column_contributes_no_edge(tmp_path: Path):
    """No assignment record exists for the landed note at all ("not-found",
    module docstring) -- distinct from a refusal, and still yields no
    edge."""
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    positions = [pos_landed]

    vocabulary_dir = _write_vocabulary(tmp_path / "vocab", "mechanism", [])

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert result.positions == ()
    assert result.categories == ()


def test_a_singleton_category_is_reached_but_contributes_no_neighbours(tmp_path: Path):
    """The landed note is the ONLY member of its category -- reached, but
    with nobody else in it, distinguishable from a refusal (which never
    shows up in `categories` at all) because the category still appears
    here, just with empty `chunk_ids`."""
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    positions = [pos_landed]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [_assignment("n1", "src-1", "lonely-category")],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert result.positions == ()
    assert [c.category_id for c in result.categories] == ["lonely-category"]
    assert result.categories[0].chunk_ids == ()


def test_no_persisted_vocabulary_for_the_column_raises_naming_the_column(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])

    with pytest.raises(NoVocabularyError) as exc_info:
        vocabulary_neighbours(
            [_landed(pos_landed)],
            set(),
            [pos_landed],
            "no-such-column",
            vocabulary_dir=tmp_path / "vocab",
        )

    assert "no-such-column" in str(exc_info.value)


def test_neighbours_from_a_different_source_are_ordered_before_the_same_source(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    pos_same_source = _position("pos-same", ["n2"], ["src-1"])
    pos_cross_source = _position("pos-cross", ["n3"], ["src-2"])
    positions = [pos_landed, pos_same_source, pos_cross_source]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),
            _assignment("n2", "src-1", "war-and-state"),
            _assignment("n3", "src-2", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert [p.position_id for p in result.positions] == ["pos-cross", "pos-same"]


def test_the_per_category_cap_is_applied_and_reported(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n0"], ["src-0"])
    other_positions = [
        _position(f"pos-{i}", [f"n{i}"], [f"src-{i}"]) for i in range(1, 6)
    ]
    positions = [pos_landed, *other_positions]

    assignments = [_assignment("n0", "src-0", "war-and-state")]
    assignments += [
        _assignment(f"n{i}", f"src-{i}", "war-and-state") for i in range(1, 6)
    ]
    vocabulary_dir = _write_vocabulary(tmp_path / "vocab", "mechanism", assignments)

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
        cap=3,
    )

    category = result.categories[0]
    assert category.cap_applied is True
    assert len(category.chunk_ids) == 3
    assert sum(len(p.chunk_ids) for p in result.positions) == 3


def test_the_cap_is_reported_as_not_applied_when_candidates_fit(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n0"], ["src-0"])
    pos_other = _position("pos-other", ["n1"], ["src-1"])
    positions = [pos_landed, pos_other]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n0", "src-0", "war-and-state"),
            _assignment("n1", "src-1", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
        cap=20,
    )

    assert result.categories[0].cap_applied is False


def test_level_defaults_to_the_columns_manifest_max_level(tmp_path: Path):
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    pos_other = _position("pos-other", ["n2"], ["src-2"])
    positions = [pos_landed, pos_other]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state", level=1),
            _assignment("n2", "src-2", "war-and-state", level=1),
        ],
        max_level=1,
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert result.level == 1
    assert [p.position_id for p in result.positions] == ["pos-other"]


def test_cross_source_ordering_is_judged_per_category_not_against_every_landed_source(
    tmp_path: Path,
):
    """issue #807, second cut. The first cut ranked every candidate against
    the union of all landed sources. With 22 landed positions over a
    35-source corpus that union covers most of the corpus, so no candidate
    can enter the preferred tier and the cap fills by `position_id`
    ascending -- no book-diversity property at all, which is the opposite of
    what #651 asks for.

    Two landed positions, two categories, two books. `src-2` is a landed
    source, but it is landed under the OTHER category, so for
    `war-and-state` it is a genuinely different book and must lead. Under
    the union rule `pos-cross` is disqualified and `pos-same` -- the asking
    note's own book -- wins on `position_id`, which is exactly backwards."""
    pos_landed_war = _position("pos-landed-war", ["n1"], ["src-1"])
    pos_landed_econ = _position("pos-landed-econ", ["n9"], ["src-2"])
    pos_same_source = _position("pos-a-same", ["n2"], ["src-1"])
    pos_cross_source = _position("pos-b-cross", ["n3"], ["src-2"])
    positions = [pos_landed_war, pos_landed_econ, pos_same_source, pos_cross_source]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),
            _assignment("n9", "src-2", "economic-dependency"),
            _assignment("n2", "src-1", "war-and-state"),
            _assignment("n3", "src-2", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed_war), _landed(pos_landed_econ)],
        {"pos-landed-war", "pos-landed-econ"},
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    war = next(c for c in result.categories if c.category_id == "war-and-state")
    assert war.chunk_ids == ("n3", "n2")
    assert [p.position_id for p in result.positions][0] == "pos-b-cross"


# ---------------------------------------------------------------------------
# The reason counts (issue #822, item 1): why each landed note produced no
# edge, counted rather than discarded.
# ---------------------------------------------------------------------------


def test_the_four_reasons_are_counted_over_the_landed_notes(tmp_path: Path):
    """A reader of the recorded block must be able to tell "the scheme does
    not fit this corpus" (refused/out-of-scheme) from "these notes were never
    assigned" (not-found) -- the conflation §7.18 records as having cost #805
    a 50.7%-vs-88.5% misreading."""
    pos_landed = _position("pos-landed", ["n1", "n2", "n3", "n4"], ["src-1"])
    pos_other = _position("pos-other", ["n9"], ["src-2"])
    positions = [pos_landed, pos_other]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),  # assigned
            _assignment("n2", "src-1", None),  # refused
            _assignment("n3", "src-1", None, out_of_scheme="a stray answer"),
            # n4 has no record at all -- not-found
            _assignment("n9", "src-2", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert result.reasons == {
        REASON_ASSIGNED: 1,
        REASON_REFUSED: 1,
        REASON_OUT_OF_SCHEME: 1,
        REASON_NOT_FOUND: 1,
    }


def test_every_reason_key_is_present_even_at_zero(tmp_path: Path):
    """An absent key would read as "not measured"; a zero says the reason
    was looked for and did not occur."""
    pos_landed = _position("pos-landed", ["n1"], ["src-1"])
    pos_other = _position("pos-other", ["n2"], ["src-2"])
    positions = [pos_landed, pos_other]

    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [
            _assignment("n1", "src-1", "war-and-state"),
            _assignment("n2", "src-2", "war-and-state"),
        ],
    )

    result = vocabulary_neighbours(
        [_landed(pos_landed)],
        set(),
        positions,
        "mechanism",
        vocabulary_dir=vocabulary_dir,
    )

    assert set(result.reasons) == set(ALL_REASONS)
    assert result.reasons[REASON_ASSIGNED] == 1
    assert result.reasons[REASON_REFUSED] == 0
    assert result.reasons[REASON_OUT_OF_SCHEME] == 0
    assert result.reasons[REASON_NOT_FOUND] == 0
