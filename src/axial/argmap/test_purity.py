"""Inner unit tests for `axial.argmap.purity` (issue #827): the pure-function
cross-tab that joins a map build's own bag assignments against a built
vocabulary column. Fixtures throughout, no model call, no dependence on
`data/` -- a `bag_state.json` and a vocabulary column directory written to
`tmp_path`, the same shapes `axial.argmap.build._write_bag_state` and
`axial.vocabulary.build_vocabulary` persist for real."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from axial.argmap.purity import (
    NAMED_PAIRS,
    NoBagStateError,
    NoMapDirError,
    compute_purity,
    resolve_map_pin_dir,
)
from axial.argmap.vocabulary_join import NoVocabularyError


def _write_bag_state(outdir: Path, assignments: dict[str, int]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    state = {
        "config": {"encoder": "test-encoder", "bag_distance_threshold": 0.2},
        "assignments": assignments,
        "centroids": {},
    }
    (outdir / "bag_state.json").write_text(json.dumps(state), encoding="utf-8")


def _write_map_json(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "map.json").write_text(json.dumps({"corpus_pin": outdir.name}), encoding="utf-8")


def _assignment(
    chunk_id: str, category_id: str | None, *, level: int = 1, **overrides
) -> dict:
    record = {
        "chunk_id": chunk_id,
        "source_id": f"{chunk_id}-source",
        "column": "claim",
        "element_index": 0,
        "level": level,
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


def _category(category_id: str, name: str | None = None) -> dict:
    return {"category_id": category_id, "name": name or category_id, "member_count": 0, "source_count": 0}


# ---------------------------------------------------------------------------
# Purity: modal-category share over categorised members only.
# ---------------------------------------------------------------------------


def test_bag_purity_is_the_modal_category_share_over_categorised_members(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    # bag 0: n1, n2, n3, n4 -- three filed under cat-a, one under cat-b.
    _write_bag_state(
        outdir, {"n1": 0, "n2": 0, "n3": 0, "n4": 0}
    )
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", "cat-a"),
            _assignment("n2", "cat-a"),
            _assignment("n3", "cat-a"),
            _assignment("n4", "cat-b"),
        ],
        categories=[_category("cat-a"), _category("cat-b")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.purity.eligible_bag_count == 1
    assert report.purity.median_purity == pytest.approx(0.75)
    assert report.purity.mean_purity == pytest.approx(0.75)
    assert report.purity.pure_bag_count == 0
    assert report.purity.median_distinct_categories == pytest.approx(2)


def test_a_bag_where_every_categorised_member_shares_one_category_is_pure(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 0, "n3": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [_assignment("n1", "cat-a"), _assignment("n2", "cat-a"), _assignment("n3", "cat-a")],
        categories=[_category("cat-a")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.purity.eligible_bag_count == 1
    assert report.purity.pure_bag_count == 1
    assert report.purity.pure_bag_share == pytest.approx(1.0)
    assert report.purity.median_distinct_categories == pytest.approx(1)


# ---------------------------------------------------------------------------
# Bags with fewer than 2 categorised members are excluded from purity but
# counted.
# ---------------------------------------------------------------------------


def test_bags_with_fewer_than_two_categorised_members_are_excluded_but_counted(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    # bag 0: eligible (2 categorised). bag 1: one categorised, one refused --
    # not eligible. bag 2: single member, categorised -- not eligible either.
    _write_bag_state(
        outdir, {"n1": 0, "n2": 0, "n3": 1, "n4": 1, "n5": 2}
    )
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", "cat-a"),
            _assignment("n2", "cat-a"),
            _assignment("n3", "cat-a"),
            _assignment("n4", None),
            _assignment("n5", "cat-a"),
        ],
        categories=[_category("cat-a")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.purity.eligible_bag_count == 1
    assert report.purity.excluded_bag_count == 2
    assert report.coverage.overlap_refused_count == 1


# ---------------------------------------------------------------------------
# Category scatter: distinct bag count per category, min/median/max.
# ---------------------------------------------------------------------------


def test_category_scatter_counts_distinct_bags_and_reports_min_median_max(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    # cat-a members sit in bags 0 and 1 (scatter 2); cat-b members all sit
    # in bag 0 (scatter 1).
    _write_bag_state(outdir, {"n1": 0, "n2": 1, "n3": 0, "n4": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", "cat-a"),
            _assignment("n2", "cat-a"),
            _assignment("n3", "cat-b"),
            _assignment("n4", "cat-b"),
        ],
        categories=[_category("cat-a"), _category("cat-b")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    by_id = {c.category_id: c for c in report.scatter.categories}
    assert by_id["cat-a"].bag_count == 2
    assert by_id["cat-b"].bag_count == 1
    assert report.scatter.min_bag_count == 1
    assert report.scatter.max_bag_count == 2
    assert report.scatter.median_bag_count == pytest.approx(1.5)


def test_a_committed_category_with_zero_members_is_reported_not_dropped(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [_assignment("n1", "cat-a")],
        categories=[_category("cat-a"), _category("cat-never-used")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    by_id = {c.category_id: c for c in report.scatter.categories}
    assert by_id["cat-never-used"].bag_count == 0
    assert by_id["cat-never-used"].member_count == 0
    # the empty category never drags the min/median/max, which is over
    # populated categories only.
    assert report.scatter.min_bag_count == 1


# ---------------------------------------------------------------------------
# Coverage: chunks on one side only, and refused assignments.
# ---------------------------------------------------------------------------


def test_chunks_present_on_only_one_side_land_in_coverage_not_an_exception(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "bag-only": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [_assignment("n1", "cat-a"), _assignment("vocab-only", "cat-a")],
        categories=[_category("cat-a")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.coverage.bag_only_count == 1
    assert report.coverage.vocabulary_only_count == 1
    assert report.coverage.overlap_count == 1


def test_refused_and_out_of_scheme_overlap_chunks_are_counted_separately(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 0, "n3": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", "cat-a"),
            _assignment("n2", None),
            _assignment("n3", None, out_of_scheme="a stray answer"),
        ],
        categories=[_category("cat-a")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.coverage.overlap_assigned_count == 1
    assert report.coverage.overlap_refused_count == 1
    assert report.coverage.overlap_out_of_scheme_count == 1


# ---------------------------------------------------------------------------
# Latest-pin resolution.
# ---------------------------------------------------------------------------


def test_with_no_pin_the_newest_map_directory_is_used(tmp_path: Path):
    map_dir = tmp_path / "map"
    older = map_dir / "pin-older"
    newer = map_dir / "pin-newer"
    _write_map_json(older)
    time.sleep(0.01)
    _write_map_json(newer)
    _write_bag_state(newer, {"n1": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab", "claim", [_assignment("n1", "cat-a")], categories=[_category("cat-a")]
    )

    report = compute_purity(column="claim", map_dir=map_dir, vocabulary_dir=vocabulary_dir)

    assert report.pin == "pin-newer"
    assert report.map_dir == newer


def test_no_pin_and_no_completed_build_raises_named_error(tmp_path: Path):
    map_dir = tmp_path / "map"
    map_dir.mkdir()

    with pytest.raises(NoMapDirError):
        compute_purity(column="claim", map_dir=map_dir)


def test_an_explicit_pin_with_no_bag_state_raises_a_named_error_not_a_traceback(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)  # map.json exists, bag_state.json never written

    with pytest.raises(NoBagStateError):
        resolve_map_pin_dir(map_dir, "pin-1")


def test_an_unbuilt_vocabulary_column_raises_no_vocabulary_error(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0})

    with pytest.raises(NoVocabularyError):
        compute_purity(
            column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=tmp_path / "vocab"
        )


# ---------------------------------------------------------------------------
# The category-pair confusion table (issue #827 comment).
# ---------------------------------------------------------------------------


def test_category_pairs_co_occurring_in_a_bag_are_ranked_with_raw_counts_and_shares(
    tmp_path: Path,
):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    # bag 0: cat-a + cat-b co-occur. bag 1: cat-a + cat-b co-occur again.
    # bag 2: cat-a + cat-c co-occur once.
    _write_bag_state(
        outdir,
        {
            "n1": 0, "n2": 0,
            "n3": 1, "n4": 1,
            "n5": 2, "n6": 2,
        },
    )
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", "cat-a"), _assignment("n2", "cat-b"),
            _assignment("n3", "cat-a"), _assignment("n4", "cat-b"),
            _assignment("n5", "cat-a"), _assignment("n6", "cat-c"),
        ],
        categories=[_category("cat-a"), _category("cat-b"), _category("cat-c")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.pairs.multi_category_bag_count == 3
    top = report.pairs.pairs[0]
    assert (top.category_a, top.category_b) == ("cat-a", "cat-b")
    assert top.bag_count == 2
    assert top.share == pytest.approx(2 / 3)
    second = report.pairs.pairs[1]
    assert (second.category_a, second.category_b) == ("cat-a", "cat-c")
    assert second.bag_count == 1


def test_named_pairs_are_reported_even_when_absent_from_the_ranking(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    # Only cat-x/cat-y ever co-occur -- neither #826 pair appears anywhere.
    _write_bag_state(outdir, {"n1": 0, "n2": 0})
    id_a, id_b = NAMED_PAIRS[0]
    id_c, id_d = NAMED_PAIRS[1]
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [_assignment("n1", "cat-x"), _assignment("n2", "cat-y")],
        categories=[
            _category("cat-x"), _category("cat-y"),
            _category(id_a), _category(id_b), _category(id_c), _category(id_d),
        ],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert len(report.pairs.named_pairs) == 2
    for named in report.pairs.named_pairs:
        assert named.applicable is True
        assert named.bag_count == 0
        assert {named.category_a, named.category_b} in (
            set(NAMED_PAIRS[0]), set(NAMED_PAIRS[1])
        )
    # Neither #826 pair is in the ranked table at all -- absent, not zeroed
    # out inside it.
    ranked_keys = {(p.category_a, p.category_b) for p in report.pairs.pairs}
    assert tuple(sorted(NAMED_PAIRS[0])) not in ranked_keys
    assert tuple(sorted(NAMED_PAIRS[1])) not in ranked_keys


def test_a_named_pair_whose_categories_are_not_in_this_columns_scheme_is_marked_not_applicable(
    tmp_path: Path,
):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 0})
    # A "mechanism"-shaped column whose scheme holds neither #826 category.
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [_assignment("n1", "war-and-state"), _assignment("n2", "war-and-state")],
        categories=[_category("war-and-state")],
    )

    report = compute_purity(
        column="mechanism", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert all(not named.applicable for named in report.pairs.named_pairs)
    assert all(named.bag_count == 0 for named in report.pairs.named_pairs)
