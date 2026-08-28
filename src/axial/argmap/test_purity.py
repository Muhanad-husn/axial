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
    InvalidNamedPairError,
    NoBagStateError,
    NoMapDirError,
    compute_purity,
    parse_named_pair,
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


# ---------------------------------------------------------------------------
# Issue #827 fix round (reviewer F2): the scatter table's own population is
# NOT the same base as purity's `eligible_bag_count`.
# ---------------------------------------------------------------------------


def test_scatter_population_differs_from_purity_eligible_bag_count(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    # bag 0: 2 categorised members -- purity-eligible AND scattered.
    # bag 1: 1 categorised member -- scattered, but NOT purity-eligible.
    # bag 2: 0 categorised members (refused) -- neither.
    _write_bag_state(outdir, {"n1": 0, "n2": 0, "n3": 1, "n4": 2})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", "cat-a"),
            _assignment("n2", "cat-a"),
            _assignment("n3", "cat-a"),
            _assignment("n4", None),
        ],
        categories=[_category("cat-a")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.purity.eligible_bag_count == 1
    assert report.scatter.population_bag_count == 2
    assert report.scatter.population_bag_count != report.purity.eligible_bag_count


def test_format_purity_report_names_the_scatter_tables_own_population(tmp_path: Path):
    from axial.argmap.purity import format_purity_report

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 1})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [_assignment("n1", "cat-a"), _assignment("n2", "cat-a")],
        categories=[_category("cat-a")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )
    text = format_purity_report(report)

    assert "CATEGORY SCATTER (over 2 bag(s) holding at least one categorised member)" in text


# ---------------------------------------------------------------------------
# Issue #827 fix round (reviewer F4): a chunk carrying 2+ categories is
# counted into coverage, never silently folded into a chunk-count denominator
# that assumes one category per chunk.
# ---------------------------------------------------------------------------


def test_a_chunk_carrying_two_categories_is_counted_in_coverage(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "about",
        [
            # n1 answers a list-valued column with two elements, each filed
            # under a different category -- category_ids_by_chunk["n1"]
            # ends up a 2-element frozenset.
            _assignment("n1", "cat-a", element_index=0),
            _assignment("n1", "cat-b", element_index=1),
            _assignment("n2", "cat-a"),
        ],
        categories=[_category("cat-a"), _category("cat-b")],
    )

    report = compute_purity(
        column="about", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.coverage.overlap_multi_category_count == 1


def test_no_multi_category_chunks_reads_as_an_explicit_zero_not_an_absent_key(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab", "claim", [_assignment("n1", "cat-a")], categories=[_category("cat-a")]
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.coverage.overlap_multi_category_count == 0


# ---------------------------------------------------------------------------
# Issue #827 fix round (reviewer F6): the two #826 category ids are a
# default, not a hardwired gate -- `named_pairs` overrides them.
# ---------------------------------------------------------------------------


def test_compute_purity_accepts_a_named_pairs_override(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "mechanism",
        [_assignment("n1", "war-and-state"), _assignment("n2", "elite-competition")],
        categories=[_category("war-and-state"), _category("elite-competition")],
    )

    report = compute_purity(
        column="mechanism",
        map_dir=map_dir,
        pin="pin-1",
        vocabulary_dir=vocabulary_dir,
        named_pairs=(("war-and-state", "elite-competition"),),
    )

    assert len(report.pairs.named_pairs) == 1
    named = report.pairs.named_pairs[0]
    assert named.applicable is True
    assert named.bag_count == 1
    # The module's own NAMED_PAIRS default was NOT consulted -- nothing
    # about the #826 claim-scheme ids appears in a mechanism-scheme report.
    assert {p.category_a for p in report.pairs.named_pairs} == {"elite-competition"}


def test_compute_purity_default_named_pairs_is_still_the_module_constant(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab", "claim", [_assignment("n1", "cat-a")], categories=[_category("cat-a")]
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    reported_ids = {(p.category_a, p.category_b) for p in report.pairs.named_pairs}
    expected_ids = {tuple(sorted(pair)) for pair in NAMED_PAIRS}
    assert reported_ids == expected_ids


def test_parse_named_pair_splits_on_comma():
    assert parse_named_pair("cat-a,cat-b") == ("cat-a", "cat-b")
    assert parse_named_pair(" cat-a , cat-b ") == ("cat-a", "cat-b")


def test_parse_named_pair_rejects_a_malformed_value():
    with pytest.raises(InvalidNamedPairError):
        parse_named_pair("only-one-id")
    with pytest.raises(InvalidNamedPairError):
        parse_named_pair("a,b,c")
    with pytest.raises(InvalidNamedPairError):
        parse_named_pair("a,")


# ---------------------------------------------------------------------------
# Issue #827 fix round, 2026-08-29: ranking pairs by raw count ranks them by
# category PREVALENCE. `lift` (observed / expected under independence, over
# presence among the multi-category bags specifically) is what separates
# "these two categories are both common" from "these two categories actually
# co-occur more than their own prevalence predicts."
# ---------------------------------------------------------------------------


def test_lift_flags_a_small_elevated_pair_and_clears_a_large_pair_at_chance(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)

    # 12 multi-category bags. `big` sits in every one of them (a large,
    # common category); `small` sits in exactly 3, always alongside `big`
    # and nothing else -- their co-occurrence (3) matches what independence
    # predicts EXACTLY (presence(big)=12, presence(small)=3, N=12 ->
    # expected = 12*3/12 = 3), so lift is ~1.0. `catx`/`caty` are each as
    # rare as `small` (presence 3) but co-occur together in all 3 of their
    # bags -- far above the 0.75 independence predicts (lift = 4.0).
    bag_state = {}
    assignments = []
    bag_label = 0
    chunk_n = 0

    def _next_chunk():
        nonlocal chunk_n
        chunk_n += 1
        return f"c{chunk_n}"

    # 6 bags: big + a unique filler category each.
    for i in range(6):
        bag_label += 1
        big_chunk, filler_chunk = _next_chunk(), _next_chunk()
        bag_state[big_chunk] = bag_label
        bag_state[filler_chunk] = bag_label
        assignments.append(_assignment(big_chunk, "big"))
        assignments.append(_assignment(filler_chunk, f"filler{i}"))

    # 3 bags: big + small.
    for _ in range(3):
        bag_label += 1
        big_chunk, small_chunk = _next_chunk(), _next_chunk()
        bag_state[big_chunk] = bag_label
        bag_state[small_chunk] = bag_label
        assignments.append(_assignment(big_chunk, "big"))
        assignments.append(_assignment(small_chunk, "small"))

    # 3 bags: big + catx + caty.
    for _ in range(3):
        bag_label += 1
        big_chunk, x_chunk, y_chunk = _next_chunk(), _next_chunk(), _next_chunk()
        bag_state[big_chunk] = bag_label
        bag_state[x_chunk] = bag_label
        bag_state[y_chunk] = bag_label
        assignments.append(_assignment(big_chunk, "big"))
        assignments.append(_assignment(x_chunk, "catx"))
        assignments.append(_assignment(y_chunk, "caty"))

    _write_bag_state(outdir, bag_state)
    categories = [_category("big"), _category("small"), _category("catx"), _category("caty")]
    categories += [_category(f"filler{i}") for i in range(6)]
    vocabulary_dir = _write_vocabulary(tmp_path / "vocab", "claim", assignments, categories=categories)

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )

    assert report.pairs.multi_category_bag_count == 12

    by_key = {(p.category_a, p.category_b): p for p in report.pairs.pairs}
    big_small = by_key[("big", "small")]
    catx_caty = by_key[("catx", "caty")]

    assert big_small.bag_count == 3
    assert big_small.expected == pytest.approx(3.0)
    assert big_small.lift == pytest.approx(1.0)

    assert catx_caty.bag_count == 3
    assert catx_caty.expected == pytest.approx(0.75)
    assert catx_caty.lift == pytest.approx(4.0)

    # The elevated small pair tops the lift ranking; the large/small pair
    # sitting at chance does not, even though its raw count (3) ties catx-
    # caty's raw count exactly.
    assert report.pairs.pairs_by_lift[0].category_a == "catx"
    assert report.pairs.pairs_by_lift[0].category_b == "caty"
    lift_rank_by_key = {
        (p.category_a, p.category_b): i for i, p in enumerate(report.pairs.pairs_by_lift, start=1)
    }
    assert lift_rank_by_key[("big", "small")] > 1


def test_format_purity_report_prints_lift_and_a_separate_by_lift_ranking(tmp_path: Path):
    from axial.argmap.purity import format_purity_report

    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 0, "n3": 1, "n4": 1})
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", "cat-a"),
            _assignment("n2", "cat-b"),
            _assignment("n3", "cat-a"),
            _assignment("n4", "cat-b"),
        ],
        categories=[_category("cat-a"), _category("cat-b")],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )
    text = format_purity_report(report)

    assert "expected 2.00, lift 1.00x" in text
    assert "CATEGORY PAIR CO-OCCURRENCE BY LIFT" in text
    assert "multi-category bags specifically" in text


def test_named_pair_report_carries_its_own_lift_and_lift_rank(tmp_path: Path):
    map_dir = tmp_path / "map"
    outdir = map_dir / "pin-1"
    _write_map_json(outdir)
    _write_bag_state(outdir, {"n1": 0, "n2": 0, "n3": 1, "n4": 1})
    id_a, id_b = NAMED_PAIRS[0]
    vocabulary_dir = _write_vocabulary(
        tmp_path / "vocab",
        "claim",
        [
            _assignment("n1", id_a),
            _assignment("n2", id_b),
            _assignment("n3", id_a),
            _assignment("n4", id_b),
        ],
        categories=[_category(id_a), _category(id_b)],
    )

    report = compute_purity(
        column="claim", map_dir=map_dir, pin="pin-1", vocabulary_dir=vocabulary_dir
    )
    named = report.pairs.named_pairs[0]

    assert named.expected == pytest.approx(2.0)
    assert named.lift == pytest.approx(1.0)
