"""Tests for `axial.argmap.compare` (issue #831): the structural verdict that
decides whether the re-formed map earned slices 07-09.

Fixtures throughout, no model call, no dependence on `data/` -- `positions.
jsonl`, `map.json`, `reads.jsonl`, `bag_state.json` and a vocabulary column
directory written to `tmp_path`, the same shapes `axial.argmap.build` and
`axial.vocabulary.build_vocabulary` persist for real. The encoder D3 needs is
injected (or `_default_encoder` monkeypatched), so nothing here loads MiniLM.

The acceptance test at the top drives the CLI. Everything below it is the
inner loop from `plans/positions-not-names/06-structural-comparison.md`."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Fixture writers -- the artifact shapes a real build leaves on disk.
# ---------------------------------------------------------------------------

# c01-c04 -> s1, c05-c08 -> s2, c09-c12 -> s3, c13-c15 -> s4.
SOURCES = {
    **{f"c{i:02d}": "s1" for i in range(1, 5)},
    **{f"c{i:02d}": "s2" for i in range(5, 9)},
    **{f"c{i:02d}": "s3" for i in range(9, 13)},
    **{f"c{i:02d}": "s4" for i in range(13, 16)},
}

# The held-out `position` axis: the variant's positions are drawn along it,
# the baseline's cut across it.
POSITION_CATEGORY = {
    **{c: "cat-p" for c in ("c01", "c02", "c05", "c06", "c09", "c10", "c13")},
    **{c: "cat-q" for c in ("c03", "c04", "c07", "c08", "c11", "c12")},
}

# The `claim` text each chunk carries, keyed to the same axis so the fake
# encoder below makes the variant's positions coherent and the baseline's not.
CLAIM_TEXT = {chunk: POSITION_CATEGORY.get(chunk, "u") for chunk in SOURCES}

SELECTED = tuple(sorted(SOURCES))


def fake_encode(texts) -> np.ndarray:
    """`cat-p` on one axis, `cat-q` on the other, anything else between --
    a two-dimensional stand-in for MiniLM that makes a same-category
    position read cosine 1.0 and a half-and-half one read 0.7071."""
    rows = []
    for text in texts:
        if text == "cat-p":
            rows.append([1.0, 0.0])
        elif text == "cat-q":
            rows.append([0.0, 1.0])
        else:
            rows.append([0.5, 0.5])
    return np.array(rows, dtype=float)


def write_positions(outdir: Path, positions) -> None:
    """`positions` as `(position_id, [chunk_id, ...])` pairs, written in the
    shape `axial.argmap.build.assign_position_ids` stamps."""
    outdir.mkdir(parents=True, exist_ok=True)
    with (outdir / "positions.jsonl").open("w", encoding="utf-8") as handle:
        for position_id, chunk_ids in positions:
            record = {
                "position_id": position_id,
                "argument": f"argument for {position_id}",
                "variants": [f"argument for {position_id}"],
                "chunk_ids": sorted(chunk_ids),
                "sources": sorted({SOURCES[c] for c in chunk_ids}),
                "authors": sorted({SOURCES[c] for c in chunk_ids}),
                "size": len(set(chunk_ids)),
                "named_times": 1,
            }
            handle.write(json.dumps(record) + "\n")


def write_map_json(outdir: Path, manifest: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "map.json").write_text(json.dumps(manifest), encoding="utf-8")


def write_reads(outdir: Path, reads) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    with (outdir / "reads.jsonl").open("w", encoding="utf-8") as handle:
        for read in reads:
            handle.write(json.dumps(read) + "\n")


def write_group_state(outdir: Path, chunk_ids) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "bag_state.json").write_text(
        json.dumps(
            {
                "config": {},
                "assignments": {chunk_id: 0 for chunk_id in chunk_ids},
                "centroids": {},
            }
        ),
        encoding="utf-8",
    )


def write_vocabulary(root: Path, column: str, records, *, max_level: int = 1) -> Path:
    column_dir = root / column
    column_dir.mkdir(parents=True, exist_ok=True)
    (column_dir / "assignments.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    (column_dir / "manifest.json").write_text(
        json.dumps(
            {
                "column": column,
                "scheme_version": "v1",
                "max_level": max_level,
                "categories": [],
            }
        ),
        encoding="utf-8",
    )
    return column_dir


def assignment(chunk_id: str, category_id: str | None, value: str, *, level: int = 1) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": SOURCES.get(chunk_id, "s0"),
        "column": "x",
        "element_index": 0,
        "level": level,
        "value": value,
        "category_id": category_id,
        "refused": category_id is None,
    }


def write_columns(root: Path) -> Path:
    """The two columns `map compare` reads: `claim` for each placed chunk's
    own source and claim sentence, `position` for the held-out axis D2
    scores. `c15` carries neither -- a selected passage the column never
    reached."""
    write_vocabulary(
        root,
        "claim",
        [
            assignment(chunk_id, "claim-cat", CLAIM_TEXT[chunk_id])
            for chunk_id in SELECTED
            if chunk_id != "c15"
        ],
    )
    write_vocabulary(
        root,
        "position",
        [
            assignment(chunk_id, POSITION_CATEGORY.get(chunk_id), CLAIM_TEXT[chunk_id])
            for chunk_id in SELECTED
            if chunk_id != "c15"
        ],
    )
    return root


# The baseline (default) build: positions cut WITHIN a book and ACROSS the
# held-out axis. `c01`, `c02`, `c05` and `c06` each sit in two positions, so
# member slots (17) exceed distinct placed passages (13) -- the shape that
# makes "selected minus slots" print a negative number.
BASELINE_POSITIONS = (
    ("pos-0001", ["c01", "c02", "c03", "c04"]),
    ("pos-0002", ["c05", "c06", "c07", "c08"]),
    ("pos-0003", ["c09", "c10", "c11", "c12"]),
    ("pos-0004", ["c01", "c02", "c05", "c06"]),
    ("pos-0005", ["c13"]),
)

# The variant: positions cut ACROSS books and ALONG the held-out axis.
VARIANT_POSITIONS = (
    ("pos-0001", ["c01", "c05", "c09", "c13"]),
    ("pos-0002", ["c02", "c06", "c10", "c13"]),
    ("pos-0003", ["c03", "c07", "c11", "c08"]),
    ("pos-0004", ["c04", "c08", "c12"]),
)

# The forced replicate of the variant: same shape, two members swapped.
REPLICATE_POSITIONS = (
    ("pos-0001", ["c01", "c05", "c09", "c13"]),
    ("pos-0002", ["c02", "c06", "c10", "c13"]),
    ("pos-0003", ["c03", "c07", "c11", "c12"]),
    ("pos-0004", ["c04", "c08", "c12"]),
)

BASELINE_MANIFEST = {
    "corpus_pin": "pin-1",
    # Deliberately the manifest a build predating slices 04-05 leaves: no
    # `grouping` block, no `answers_pin`, and the ambiguous `passages_placed`
    # slot sum instead of the two named counts.
    "counts": {
        "passages_selected": 15,
        "bags": 3,
        "reads": 9,
        "units_total": 9,
        "units_reused": 4,
        "units_asked": 5,
        "raw_positions": 6,
        "merged_positions": 5,
        "passages_placed": 17,
    },
    "embedding_merge": {
        "folds": 1,
        "positions_with_more_than_one_naming": 1,
        "folds_per_final_position": 0.2,
    },
    "model": "baseline-model",
    "cost_usd": 1.5,
    "wall_time_sec": 100.0,
}


def variant_manifest(*, units_reused: int = 0) -> dict:
    return {
        "corpus_pin": "pin-1",
        "grouping": {
            "mode": "category",
            "scheme_versions": {
                "claim": "2026-08-28-claim-v1",
                "mechanism": "2026-08-28-mechanism-v1",
            },
        },
        "counts": {
            "passages_selected": 15,
            "groups": 4,
            "reads": 6,
            "units_total": 6,
            "units_reused": units_reused,
            "units_asked": 6 - units_reused,
            "raw_positions": 8,
            "consolidated_positions": 5,
            "merged_positions": 4,
            "passages_placed_slots": 15,
            "passages_placed_distinct": 13,
            "passages_unassigned": 1,
            "passages_ungrouped": 1,
            "failed_reads": 0,
            "passages_in_failed_reads": 0,
        },
        "consolidation": {
            "counts": {
                "folds": 3,
                "positions_with_more_than_one_naming": 2,
                "folds_per_final_position": 0.6,
            }
        },
        "embedding_merge": {
            "folds": 1,
            "positions_with_more_than_one_naming": 1,
            "folds_per_final_position": 0.25,
        },
        "model": "variant-model",
        "cost_usd": 0.5,
        "wall_time_sec": 50.0,
    }


def build_baseline(root: Path) -> Path:
    outdir = root / "pin-1"
    write_positions(outdir, BASELINE_POSITIONS)
    write_map_json(outdir, BASELINE_MANIFEST)
    write_group_state(outdir, SELECTED)
    write_reads(
        outdir,
        [{"bag": 0, "slice": 0, "shown": 8, "positions": [], "unassigned": 1}],
    )
    return outdir


def build_variant(root: Path, name: str = "pin-1-category", **kwargs) -> Path:
    outdir = root / name
    write_positions(outdir, kwargs.pop("positions", VARIANT_POSITIONS))
    write_map_json(outdir, variant_manifest(**kwargs))
    # `c15` reached no group, so the group state holds 14 of 15 selected.
    write_group_state(outdir, [c for c in SELECTED if c != "c15"])
    write_reads(
        outdir,
        [{"bag": "cat-p::m", "slice": 0, "shown": 8, "positions": [], "unassigned": 1}],
    )
    return outdir


# ---------------------------------------------------------------------------
# Acceptance test (issue #831's Gherkin, at the CLI, over tmp fixture dirs).
# ---------------------------------------------------------------------------


def test_map_compare_prints_d1_to_d5_the_replicate_gap_and_the_side_by_side_identity_table(
    tmp_path, capsys, monkeypatch
):
    """Every `And` clause of issue #831's acceptance criterion, over three
    fixture builds: the baseline (default), the variant, and the variant's
    forced replicate."""
    from axial.argmap import compare as compare_mod
    from axial.cli import main

    monkeypatch.setattr(compare_mod, "_default_encoder", lambda: fake_encode)

    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    variant = build_variant(map_dir)
    replicate = build_variant(map_dir, "pin-1-category-replicate", positions=REPLICATE_POSITIONS)
    vocabulary_dir = write_columns(tmp_path / "vocab")

    exit_code = main(
        [
            "map",
            "compare",
            str(baseline),
            str(variant),
            "--replicate",
            str(replicate),
            "--vocabulary-dir",
            str(vocabulary_dir),
            "--seed",
            "4242",
            "--trials",
            "20",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0

    # ... the two builds side by side in one table naming the corpus pin, the
    # answers pin, the vocabulary scheme versions and both artifact paths.
    assert "IDENTITY" in out
    assert "corpus pin" in out
    assert "answers pin" in out
    assert "2026-08-28-claim-v1" in out
    assert "2026-08-28-mechanism-v1" in out
    assert str(baseline) in out and str(variant) in out and str(replicate) in out
    # Absent on one side is NOT a mismatch: a bag-mode build records no
    # grouping block and no answers pin at all.
    assert "not recorded" in out

    # ... D1 book-spread ratio per size band for each build, observed over its
    # own size-matched permutation null.
    assert "D1 BOOK-SPREAD RATIO" in out
    assert "3-5" in out
    assert "plurality band" in out

    # ... D2 held-out `position` purity per build over the same null, naming
    # the categorised base and the assignment-instability floor.
    assert "D2 HELD-OUT" in out
    assert "13 of 15 selected" in out
    assert "13 of 13 placed" in out
    assert "assignment-instability floor: 0.0331" in out

    # ... D3 mean member coherence per size band per build with that band's null.
    assert "D3 MEMBER COHERENCE" in out
    assert "all-MiniLM-L6-v2" in out

    # ... D4 as distinct chunk ids subtracted from selected, never a sum of
    # position sizes. 15 selected - 13 distinct placed = 2; the slot sum is 17,
    # so the wrong arithmetic would print -2.
    assert "D4 PASSAGES REACHING NO POSITION" in out
    assert "15 selected, 13 distinct placed, 2 unplaced" in out
    assert "-2 unplaced" not in out

    # ... the replicate gap on D1 and D2, and `units_reused` for the replicate.
    assert "REPLICATE" in out
    assert "units_reused: 0" in out
    assert "D1 gap" in out
    assert "D2 gap" in out

    # ... each build's context lines with their denominators named, and the
    # cross-book rate only alongside its null.
    assert "CONTEXT" in out
    assert "member slot(s)" in out
    assert "cross-book" in out
    assert "cross-book null" in out

    # ... consolidation as folds per final position, the embedding merge's
    # folds separate from the consolidation pass's own.
    assert "consolidation: 3 fold(s), 0.600 per final position" in out
    assert "embedding merge: 1 fold(s), 0.250 per final position" in out
    assert "no consolidation stage in this build" in out

    # D5 is a hand-sample: named, never computed.
    assert "D5 BLIND PAIRED HAND-SAMPLE" in out
    assert "not computed" in out

    # The verdict itself.
    assert "VERDICT" in out
    for metric in ("D1:", "D2:", "D3:", "D4:"):
        assert f"  {metric} passed" in out


def test_map_compare_refuses_when_a_vocabulary_scheme_version_differs(
    tmp_path, capsys, monkeypatch
):
    """... comparing builds that disagree on any of those pins or versions
    refuses with a message naming which one differs."""
    from axial.argmap import compare as compare_mod
    from axial.cli import main

    monkeypatch.setattr(compare_mod, "_default_encoder", lambda: fake_encode)

    map_dir = tmp_path / "map"
    baseline = build_variant(map_dir, "pin-1-category-a")
    variant = build_variant(map_dir, "pin-1-category-b")
    manifest = variant_manifest()
    manifest["grouping"]["scheme_versions"]["claim"] = "2026-09-01-claim-v2"
    write_map_json(variant, manifest)
    vocabulary_dir = write_columns(tmp_path / "vocab")

    exit_code = main(
        [
            "map",
            "compare",
            str(baseline),
            str(variant),
            "--vocabulary-dir",
            str(vocabulary_dir),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "claim" in captured.err
    assert "2026-08-28-claim-v1" in captured.err
    assert "2026-09-01-claim-v2" in captured.err


# ---------------------------------------------------------------------------
# D1: mean distinct sources per position, per size band, and its null.
# ---------------------------------------------------------------------------


def _stats(
    positions,
    *,
    manifest: dict | None = None,
    passages=None,
    seed: int = 1,
    trials: int = 5,
    group_state=None,
):
    """One build's stats, straight over in-memory fixtures."""
    from axial.argmap.compare import Build, Passage, compute_build_stats

    table = (
        passages
        if passages is not None
        else {
            chunk_id: Passage(
                SOURCES[chunk_id], CLAIM_TEXT[chunk_id], POSITION_CATEGORY.get(chunk_id)
            )
            for chunk_id in SOURCES
        }
    )
    texts = {c: p.claim for c, p in table.items() if p.claim}
    matrix = fake_encode(list(texts.values()))
    vectors = {
        chunk_id: row / np.linalg.norm(row)
        for chunk_id, row in zip(texts, matrix)
        if np.linalg.norm(row) > 0
    }
    build = Build(
        path=Path("/fixture"),
        label="A",
        manifest=manifest if manifest is not None else {"counts": {"passages_selected": 15}},
        positions=tuple(tuple(p) for p in positions),
        reads=(),
        group_state=frozenset(group_state) if group_state is not None else None,
    )
    return compute_build_stats(build, table, vectors, seed=seed, trials=trials)


def test_d1_reports_mean_distinct_sources_per_position_in_each_size_band():
    """Band 2: one within-book pair, one cross-book pair -> 1.5. Band 3-5: a
    single four-source position -> 4.0. A size-1 position is in neither."""
    stats = _stats(
        [
            ["c01", "c02"],  # both s1
            ["c03", "c05"],  # s1, s2
            ["c01", "c05", "c09", "c13"],  # s1, s2, s3, s4
            ["c04"],
        ]
    )

    assert stats.band("2").positions == 2
    assert stats.band("2").sources_observed == pytest.approx(1.5)
    assert stats.band("3-5").positions == 1
    assert stats.band("3-5").sources_observed == pytest.approx(4.0)
    assert [band.label for band in stats.bands] == ["2", "3-5"]


def test_the_permutation_null_is_reproducible_from_one_seed_and_moves_with_another():
    """The seeded size-matched permutation gives the same figure twice, and a
    different seed is a different draw -- so the null is an estimate, not a
    constant."""
    positions = [
        ["c01", "c02"],
        ["c03", "c05"],
        ["c01", "c05", "c09", "c13"],
        ["c04", "c06", "c08"],
    ]

    first = _stats(positions, seed=7, trials=3)
    again = _stats(positions, seed=7, trials=3)
    other = _stats(positions, seed=99, trials=3)

    assert first.band("2").sources_null == again.band("2").sources_null
    assert first.band("3-5").coherence_null == again.band("3-5").coherence_null
    assert first.purity.null == again.purity.null
    assert first.band("2").sources_null != other.band("2").sources_null


def test_the_permutation_null_preserves_the_size_profile_and_the_placed_pool():
    from axial.argmap.compare import permute_positions

    positions = [("c01", "c02"), ("c03", "c05", "c09"), ("c01",)]
    drawn = permute_positions(positions, 11)

    assert [len(p) for p in drawn] == [2, 3, 1]
    assert sorted(c for p in drawn for c in p) == sorted(c for p in positions for c in p)


# ---------------------------------------------------------------------------
# D2: modal-category share over CATEGORISED members only.
# ---------------------------------------------------------------------------


def test_d2_scores_the_modal_share_of_categorised_members_and_ignores_uncategorised_ones():
    """`c14` carries no `position` category. The position holding it scores 2
    of 2 categorised, not 2 of 3 -- an uncategorised member is not in the
    denominator."""
    from axial.argmap.compare import Passage

    table = {
        "c01": Passage("s1", "cat-p", "cat-p"),
        "c02": Passage("s1", "cat-p", "cat-p"),
        "c14": Passage("s4", "u", None),
    }
    stats = _stats([["c01", "c02", "c14"]], passages=table)

    assert stats.purity.scored_positions == 1
    assert stats.purity.member_weighted == pytest.approx(1.0)


def test_d2_excludes_a_position_whose_members_are_all_uncategorised_and_counts_it():
    """Never scored zero -- excluded, and reported as excluded (the plan's
    inner loop, issue #831's D2)."""
    from axial.argmap.compare import Passage

    table = {
        "c01": Passage("s1", "cat-p", "cat-p"),
        "c02": Passage("s1", "cat-p", "cat-q"),
        "c14": Passage("s4", "u", None),
        "c15": Passage("s4", "u", None),
    }
    stats = _stats([["c01", "c02"], ["c14", "c15"]], passages=table)

    assert stats.purity.scored_positions == 1
    assert stats.purity.excluded_positions == 1
    assert stats.purity.excluded_uncategorised == 1
    # 1 modal of 2 categorised on the one scored position -- the excluded
    # position contributes no zero to either mean.
    assert stats.purity.member_weighted == pytest.approx(0.5)
    assert stats.purity.per_position_mean == pytest.approx(0.5)


def test_d2_reports_the_categorised_base_of_selected_and_of_placed():
    stats = _stats(
        [["c01", "c02", "c03", "c04"]],
        manifest={"counts": {"passages_selected": 15}},
        group_state=SELECTED,
    )

    # 13 of the 15 selected carry a `position` category; all 4 placed do.
    assert (stats.purity.categorised_of_selected, stats.purity.selected) == (13, 15)
    assert (stats.purity.categorised_of_placed, stats.purity.placed) == (4, 4)
    assert stats.purity.universe == 15
    assert stats.purity.selected_outside_universe == 0


# ---------------------------------------------------------------------------
# D3: mean cosine to the position's own centroid.
# ---------------------------------------------------------------------------


def test_d3_is_the_mean_cosine_to_the_positions_own_centroid_band_by_band():
    """A same-category position reads 1.0; a half-and-half one reads cos 45
    degrees = 0.7071 under the two-axis fake encoder."""
    stats = _stats(
        [
            ["c01", "c02"],  # both cat-p
            ["c03", "c04"],  # both cat-q
            ["c01", "c02", "c03", "c04"],  # two of each
        ]
    )

    assert stats.band("2").coherence_observed == pytest.approx(1.0)
    assert stats.band("3-5").coherence_observed == pytest.approx(0.70710678)


def test_d3_treats_a_member_with_no_claim_text_as_missing_never_as_zero():
    """Three members, one without a claim sentence: the position scores over
    the two that have one and reads 1.0, not the 0.67 an implicit zero would
    give. The missing member is counted and reported."""
    from axial.argmap.compare import Passage

    table = {
        "c01": Passage("s1", "cat-p", "cat-p"),
        "c02": Passage("s1", "cat-p", "cat-p"),
        "c03": Passage("s2", None, "cat-p"),
    }
    stats = _stats([["c01", "c02", "c03"]], passages=table)

    assert stats.band("3-5").coherence_observed == pytest.approx(1.0)
    assert stats.missing_claim == 1


def test_d3s_band_floor_is_the_midpoint_of_the_baselines_own_value_and_null():
    """The default build's 11-48 band reads 0.791 observed against a 0.537
    null, and issue #831 states its floor as 0.664."""
    from axial.argmap.compare import BandStat, band_floor

    band = BandStat(
        label="11+",
        positions=10,
        slots=200,
        sources_observed=None,
        sources_null=None,
        cross_book_observed=None,
        cross_book_null=None,
        coherence_positions=10,
        coherence_observed=0.791,
        coherence_null=0.537,
    )

    assert band_floor(band) == pytest.approx(0.664)


# ---------------------------------------------------------------------------
# D4: selected minus DISTINCT chunk ids -- never a sum of position sizes.
# ---------------------------------------------------------------------------


def test_d4_subtracts_distinct_chunk_ids_and_a_chunk_in_two_positions_never_goes_negative():
    """The `build.py:1395` bug in miniature: 6 member slots over 4 distinct
    passages against 5 selected. The slot sum would print -1; the distinct
    count prints 1."""
    stats = _stats(
        [["c01", "c02", "c03"], ["c01", "c02", "c04"]],
        manifest={"counts": {"passages_selected": 5}},
    )

    assert stats.unplaced.slots == 6
    assert stats.unplaced.placed_distinct == 4
    assert stats.unplaced.unplaced == 1
    assert stats.unplaced.share == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# Context: every share names its denominator; the cross-book rate never
# appears without its null.
# ---------------------------------------------------------------------------


def _run_report(tmp_path, monkeypatch, *, replicate=True, units_reused=0, variant_positions=None):
    """The rendered report over the standard three-build fixture."""
    from axial.argmap import compare as compare_mod
    from axial.argmap.compare import compute_comparison, format_comparison_report

    monkeypatch.setattr(compare_mod, "_default_encoder", lambda: fake_encode)
    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    variant = build_variant(
        map_dir, positions=variant_positions or VARIANT_POSITIONS, units_reused=units_reused
    )
    replicate_dir = (
        build_variant(map_dir, "pin-1-category-replicate", positions=REPLICATE_POSITIONS)
        if replicate
        else None
    )
    vocabulary_dir = write_columns(tmp_path / "vocab")
    report = compute_comparison(
        baseline,
        variant,
        replicate_dir,
        vocabulary_dir=vocabulary_dir,
        seed=4242,
        trials=10,
    )
    return format_comparison_report(report)


def test_d4_prints_the_slot_sum_beside_the_distinct_count_so_neither_is_read_as_the_other(
    tmp_path, monkeypatch
):
    out = _run_report(tmp_path, monkeypatch)

    assert "member slots 17, which is not a passage count" in out
    assert "15 selected, 13 distinct placed, 2 unplaced = 13.3% of selected" in out


def test_context_prints_single_passage_and_cross_book_shares_both_weightings_with_denominators(
    tmp_path, monkeypatch
):
    out = _run_report(tmp_path, monkeypatch)

    assert "single-passage: 1 = 20.0% of 5 position(s), 5.9% of 17 member slot(s)" in out
    assert (
        "cross-book: 25.0% of 4 position(s) of size 2+, 23.5% of 17 member slot(s), "
        "30.8% of 13 distinct placed passage(s)" in out
    )


def test_the_cross_book_rate_never_appears_without_its_null(tmp_path, monkeypatch):
    """D1's table carries the per-band null in the column beside it, and the
    context line points at that table rather than standing alone."""
    out = _run_report(tmp_path, monkeypatch)
    lines = out.splitlines()

    header = next(line for line in lines if "cross-book null" in line)
    assert "cross-book" in header
    context_line = next(line for line in lines if line.strip().startswith("cross-book:"))
    assert "against its own null in D1's table" in context_line


# ---------------------------------------------------------------------------
# Consolidation and the embedding merge: two figures, never summed.
# ---------------------------------------------------------------------------


def test_consolidation_and_the_embedding_merge_are_reported_as_two_separate_fold_figures(
    tmp_path, monkeypatch
):
    """3 consolidation folds at 0.600 per final position, 1 embedding-merge
    fold at 0.250 -- and nowhere the 4 a sum would print."""
    out = _run_report(tmp_path, monkeypatch)

    assert "consolidation: 3 fold(s), 0.600 per final position" in out
    assert "embedding merge: 1 fold(s), 0.250 per final position" in out
    assert "4 fold(s)" not in out


def test_a_build_with_no_consolidation_block_says_so_rather_than_raising(tmp_path, monkeypatch):
    """The default build has no consolidation stage and its manifest has no
    such block. That is reported, never an error and never a zero pretending
    to be a measurement."""
    out = _run_report(tmp_path, monkeypatch)

    assert "consolidation: no consolidation stage in this build" in out


# ---------------------------------------------------------------------------
# The replicate: units_reused, and what an unusable gap does to the verdict.
# ---------------------------------------------------------------------------


def test_a_replicate_with_units_reused_above_zero_is_flagged_and_its_gap_is_not_an_error_bar(
    tmp_path, monkeypatch
):
    """`_seed_reads_from_prior_pin` can refill a forced replicate's ledger
    from a slice-identical sibling and reproduce it byte for byte, reading a
    zero error bar (issue #831). A non-zero `units_reused` says so, and the
    margins fall back to 'not resolved at this sample'."""
    from axial.argmap import compare as compare_mod
    from axial.argmap.compare import NOT_RESOLVED, compute_comparison, format_comparison_report

    monkeypatch.setattr(compare_mod, "_default_encoder", lambda: fake_encode)
    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    variant = build_variant(map_dir)
    replicate = build_variant(
        map_dir, "pin-1-category-replicate", positions=REPLICATE_POSITIONS, units_reused=3
    )
    report = compute_comparison(
        baseline,
        variant,
        replicate,
        vocabulary_dir=write_columns(tmp_path / "vocab"),
        seed=4242,
        trials=10,
    )
    out = format_comparison_report(report)

    assert report.replicate_gap_usable is False
    assert "units_reused: 3" in out
    assert "NOT usable as an error bar" in out
    assert {v.status for v in report.verdicts if v.metric in ("D1", "D2")} == {NOT_RESOLVED}


def test_units_reused_is_read_from_each_manifest_and_printed(tmp_path, monkeypatch):
    out = _run_report(tmp_path, monkeypatch)

    assert "units reused 4" in out  # the baseline's own
    assert "units reused 0" in out  # the variant's
    assert "C units_reused: 0 -- the gap is usable as an error bar" in out


def test_without_a_replicate_the_gap_is_reported_as_not_measured_never_assumed(
    tmp_path, monkeypatch
):
    out = _run_report(tmp_path, monkeypatch, replicate=False)

    assert "not supplied -- the D1 and D2 replicate gaps were NOT measured" in out
    assert "D1: not resolved at this sample" in out
    assert "D2: not resolved at this sample" in out
    assert "the replicate gap was not measured" in out


# ---------------------------------------------------------------------------
# The verdict: both of D2's floors bind, and a gap inside either is "not
# resolved at this sample", never "passed".
# ---------------------------------------------------------------------------


def _d2_verdict_over(*, variant_purity, baseline_purity, replicate_gap, floor, lift=2.0):
    from axial.argmap.compare import PurityStat, _d2_verdict

    def stat(value):
        return type(
            "Stub",
            (),
            {
                "purity": PurityStat(
                    scored_positions=1,
                    excluded_positions=0,
                    excluded_uncategorised=0,
                    member_weighted=value,
                    per_position_mean=value,
                    null=value / lift,
                    categorised_of_selected=1,
                    selected=1,
                    universe=1,
                    selected_outside_universe=0,
                    categorised_of_placed=1,
                    placed=1,
                )
            },
        )()

    return _d2_verdict(
        stat(baseline_purity),
        stat(variant_purity),
        replicate_gap,
        replicate_gap is not None,
        floor,
    )


def test_d2_fails_outright_when_the_gap_is_inside_the_assignment_instability_floor():
    from axial.argmap.compare import FAILED

    verdict = _d2_verdict_over(
        variant_purity=0.7700, baseline_purity=0.7597, replicate_gap=0.0001, floor=0.0331
    )

    assert verdict.status == FAILED
    assert "assignment-instability floor" in verdict.reason


def test_d2_is_not_resolved_when_the_gap_clears_the_floor_but_not_twice_the_replicate_gap():
    from axial.argmap.compare import NOT_RESOLVED

    verdict = _d2_verdict_over(
        variant_purity=0.8100, baseline_purity=0.7597, replicate_gap=0.0400, floor=0.0331
    )

    assert verdict.status == NOT_RESOLVED
    assert "does not exceed 2x the replicate gap" in verdict.reason


def test_d2_passes_only_when_the_gap_clears_whichever_floor_is_larger():
    from axial.argmap.compare import PASSED

    verdict = _d2_verdict_over(
        variant_purity=0.8600, baseline_purity=0.7597, replicate_gap=0.0100, floor=0.0331
    )

    assert verdict.status == PASSED


def test_d2_fails_outright_when_the_lift_is_at_or_below_one_whatever_the_gap():
    from axial.argmap.compare import FAILED

    verdict = _d2_verdict_over(
        variant_purity=0.9000,
        baseline_purity=0.7597,
        replicate_gap=0.0001,
        floor=0.0331,
        lift=1.0,
    )

    assert verdict.status == FAILED
    assert "lift" in verdict.reason


def test_d1_fails_when_the_ratio_falls_against_the_baseline_in_any_band(tmp_path, monkeypatch):
    """Issue #831's failure condition 1 is a no-go on either half: the
    plurality band here clears 2x, and band 2 -- where the variant puts a
    within-book pair against the baseline's cross-book one -- falls."""
    from axial.argmap import compare as compare_mod
    from axial.argmap.compare import FAILED, compute_comparison

    monkeypatch.setattr(compare_mod, "_default_encoder", lambda: fake_encode)
    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    write_positions(
        baseline,
        (*BASELINE_POSITIONS, ("pos-0006", ["c01", "c05"])),  # a cross-book band-2 pair
    )
    variant = build_variant(
        map_dir,
        positions=(*VARIANT_POSITIONS, ("pos-0005", ["c01", "c02"])),  # a within-book one
    )
    report = compute_comparison(
        baseline,
        variant,
        vocabulary_dir=write_columns(tmp_path / "vocab"),
        seed=4242,
        trials=5,
    )

    d1 = next(v for v in report.verdicts if v.metric == "D1")
    assert d1.status == FAILED
    assert "falls against the baseline in band(s) 2" in d1.reason


def test_the_verdict_is_no_go_when_d4_rises(tmp_path, monkeypatch):
    """Issue #831's failure condition 4: the no-position share must not
    rise."""
    from axial.argmap import compare as compare_mod
    from axial.argmap.compare import FAILED, compute_comparison

    monkeypatch.setattr(compare_mod, "_default_encoder", lambda: fake_encode)
    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    # The variant places 8 of the 15 selected -- 7 unplaced against the
    # baseline's 2.
    variant = build_variant(
        map_dir,
        positions=(
            ("pos-0001", ["c01", "c05", "c09", "c13"]),
            ("pos-0002", ["c02", "c06", "c10", "c04"]),
        ),
    )
    report = compute_comparison(
        baseline,
        variant,
        vocabulary_dir=write_columns(tmp_path / "vocab"),
        seed=4242,
        trials=5,
    )

    d4 = next(v for v in report.verdicts if v.metric == "D4")
    assert d4.status == FAILED
    assert report.overall == "no-go on slices 07-09"


# ---------------------------------------------------------------------------
# Identity: refuse on a mismatch, never on an absence.
# ---------------------------------------------------------------------------


def test_identity_refuses_on_a_corpus_pin_mismatch_naming_it(tmp_path):
    from axial.argmap.compare import IdentityMismatchError, check_identity, load_build

    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    variant = build_variant(map_dir)
    manifest = variant_manifest()
    manifest["corpus_pin"] = "pin-2"
    write_map_json(variant, manifest)

    with pytest.raises(IdentityMismatchError) as excinfo:
        check_identity([load_build(baseline, "A"), load_build(variant, "B")])

    assert "the corpus pin" in str(excinfo.value)
    assert "pin-1" in str(excinfo.value) and "pin-2" in str(excinfo.value)


def test_identity_refuses_on_an_answers_pin_mismatch_naming_it(tmp_path):
    from axial.argmap.compare import IdentityMismatchError, check_identity, load_build

    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    write_map_json(baseline, {**BASELINE_MANIFEST, "answers_pin": "aaaa"})
    variant = build_variant(map_dir)
    write_map_json(variant, {**variant_manifest(), "answers_pin": "bbbb"})

    with pytest.raises(IdentityMismatchError) as excinfo:
        check_identity([load_build(baseline, "A"), load_build(variant, "B")])

    assert "the answers pin" in str(excinfo.value)
    assert "aaaa" in str(excinfo.value) and "bbbb" in str(excinfo.value)


def test_a_field_absent_on_one_side_is_not_a_mismatch(tmp_path, monkeypatch):
    """The pair this command exists to compare: the default build carries no
    `grouping` block and no answers pin at all, the variant carries both.
    Absent is reported as `not recorded`, never refused."""
    out = _run_report(tmp_path, monkeypatch, replicate=False)

    assert "answers pin" in out
    assert "not recorded" in out
    assert "2026-08-28-claim-v1" in out


def test_load_build_names_a_directory_that_is_not_a_build_rather_than_raising_a_traceback(
    tmp_path,
):
    from axial.argmap.compare import NoBuildError, load_build

    empty = tmp_path / "not-a-build"
    empty.mkdir()

    with pytest.raises(NoBuildError) as excinfo:
        load_build(empty, "A")
    assert "map.json" in str(excinfo.value)

    write_map_json(empty, {"corpus_pin": "pin-1"})
    with pytest.raises(NoBuildError) as excinfo:
        load_build(empty, "A")
    assert "positions.jsonl" in str(excinfo.value)


def test_compute_comparison_names_a_column_that_has_never_been_built(tmp_path):
    from axial.argmap.compare import compute_comparison
    from axial.argmap.vocabulary_join import NoVocabularyError

    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    variant = build_variant(map_dir)
    # `claim` alone -- the held-out `position` column is missing.
    write_vocabulary(tmp_path / "vocab", "claim", [assignment("c01", "claim-cat", "cat-p")])

    with pytest.raises(NoVocabularyError) as excinfo:
        compute_comparison(baseline, variant, vocabulary_dir=tmp_path / "vocab", trials=1)
    assert "position" in str(excinfo.value)


def test_position_coverage_is_reported_per_book_for_this_draw_never_as_a_corpus_fact(
    tmp_path, monkeypatch
):
    """Issue #831's D2 correction 2: roughly 5% of the `position` column is
    refused and WHICH passages varies by model, so the per-source coverage is
    printed next to the verdict per draw. `c14` is refused on this draw, and
    it is `s4`'s only placed passage on the baseline side."""
    from axial.argmap import compare as compare_mod
    from axial.argmap.compare import compute_comparison, format_comparison_report

    monkeypatch.setattr(compare_mod, "_default_encoder", lambda: fake_encode)
    map_dir = tmp_path / "map"
    baseline = build_baseline(map_dir)
    write_positions(baseline, (*BASELINE_POSITIONS, ("pos-0006", ["c13", "c14"])))
    variant = build_variant(map_dir)
    vocabulary_dir = write_columns(tmp_path / "vocab")
    report = compute_comparison(
        baseline, variant, vocabulary_dir=vocabulary_dir, seed=4242, trials=5
    )
    out = format_comparison_report(report)

    by_source = {row.source_id: row for row in report.position_coverage}
    # c13 carries a category, c14 does not -- 1 of 2 for s4.
    assert (by_source["s4"].categorised, by_source["s4"].placed) == (1, 2)
    assert by_source["s1"].share == 1.0
    # Worst-covered first, so the refused book leads.
    assert report.position_coverage[0].source_id == "s4"
    assert "`position` coverage per book for THIS DRAW" in out
    assert "never of the corpus" in out
    assert "s4: 1 of 2 (50.0%)" in out
