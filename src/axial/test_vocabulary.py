"""Inner unit tests for `axial.vocabulary` (issue #805, derived-vocabulary
slice 01). Every test here injects its own `encode`/`cluster_fn` (plain
callables, mirroring `axial.argmap.build.bag_passages`'s own seam), so no
test pays MiniLM's load cost or needs `scipy`/`sklearn` installed -- the
real clustering path is exercised once, at the CLI level, in
`test_cli.py::test_main_vocabulary_examine_reports_the_sweep_and_the_top_groups`.
"""

from __future__ import annotations

import json

import numpy as np

from axial.vocabulary import (
    PopulationEntry,
    examine_vocabulary,
    read_column,
)


def _write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_answers(answers_dir, records_by_source):
    answers_dir.mkdir(parents=True, exist_ok=True)
    for source_id, records in records_by_source.items():
        _write_jsonl(answers_dir / f"{source_id}.jsonl", records)


# ---------------------------------------------------------------------------
# read_column
# ---------------------------------------------------------------------------


def test_read_column_yields_one_value_per_note_with_chunk_and_source_id():
    records = [
        {"chunk_id": "book-a_1", "source_id": "book-a", "answers": {"mechanism": "sentence one"}},
        {"chunk_id": "book-b_1", "source_id": "book-b", "answers": {"mechanism": "sentence two"}},
    ]

    population, excluded = read_column(records, "mechanism")

    assert excluded == 0
    assert population == [
        PopulationEntry("sentence one", "book-a_1", "book-a"),
        PopulationEntry("sentence two", "book-b_1", "book-b"),
    ]


def test_read_column_excludes_abstention_and_does_not_cluster_it():
    records = [
        {"chunk_id": "book-a_1", "source_id": "book-a", "answers": {"mechanism": "not-in-passage"}},
        {"chunk_id": "book-a_2", "source_id": "book-a",
         "answers": {"mechanism": {"not-in-passage": "no mechanism named here"}}},
        {"chunk_id": "book-a_3", "source_id": "book-a", "answers": {"mechanism": "a real sentence"}},
    ]

    population, excluded = read_column(records, "mechanism")

    assert excluded == 2
    assert [entry.value for entry in population] == ["a real sentence"]


def test_read_column_excludes_literal_empty_list_string_and_empty_string_and_counts_them():
    records = [
        # Issue #810: the literal string "[]" stored where an empty list
        # belongs.
        {"chunk_id": "book-a_1", "source_id": "book-a", "answers": {"mechanism": "[]"}},
        {"chunk_id": "book-a_2", "source_id": "book-a", "answers": {"mechanism": ""}},
        {"chunk_id": "book-a_3", "source_id": "book-a", "answers": {"mechanism": "a real sentence"}},
    ]

    population, excluded = read_column(records, "mechanism")

    assert excluded == 2
    assert [entry.value for entry in population] == ["a real sentence"]


def test_read_column_list_valued_contributes_one_entry_per_list_element():
    records = [
        {
            "chunk_id": "book-a_1",
            "source_id": "book-a",
            "answers": {"arguing_against": ["claim one", "claim two", "claim three"]},
        },
        {
            "chunk_id": "book-b_1",
            "source_id": "book-b",
            "answers": {"arguing_against": ["claim four"]},
        },
    ]

    population, excluded = read_column(records, "arguing_against")

    assert excluded == 0
    assert [entry.value for entry in population] == [
        "claim one",
        "claim two",
        "claim three",
        "claim four",
    ]
    assert population[0].chunk_id == "book-a_1"
    assert population[3].chunk_id == "book-b_1"


def test_read_column_a_missing_key_is_neither_answered_nor_excluded():
    records = [
        {"chunk_id": "book-a_1", "source_id": "book-a", "answers": {"claim": "unrelated field"}},
    ]

    population, excluded = read_column(records, "mechanism")

    assert population == []
    assert excluded == 0


# ---------------------------------------------------------------------------
# examine_vocabulary: the clustering sweep, via injected encode/cluster_fn
# ---------------------------------------------------------------------------


def _counting_encoder(dimension=2):
    calls = {"n": 0, "batches": []}

    def encode(texts):
        calls["n"] += 1
        calls["batches"].append(list(texts))
        # One row per text, all zero -- content doesn't matter for tests
        # that inject their own cluster_fn.
        return np.zeros((len(texts), dimension))

    encode.calls = calls
    return encode


def _counting_cluster_fn(labels_by_threshold_fn):
    """A fake sweep function: given `vectors`/`thresholds`, returns
    `labels_by_threshold_fn(thresholds)` and counts how many times it was
    called -- the seam the "encodes/clusters once" tests assert against."""
    calls = {"n": 0}

    def cluster_fn(vectors, thresholds):
        calls["n"] += 1
        return labels_by_threshold_fn(thresholds)

    cluster_fn.calls = calls
    return cluster_fn


def test_single_value_population_yields_one_group_without_calling_cluster_fn(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        {"book-a": [{"chunk_id": "book-a_1", "source_id": "book-a",
                     "answers": {"mechanism": "the only sentence"}}]},
    )
    encode = _counting_encoder()
    cluster_fn = _counting_cluster_fn(lambda thresholds: {t: [0] for t in thresholds})

    stats = examine_vocabulary(
        answers_dir=answers_dir,
        columns=["mechanism"],
        thresholds=[0.35, 0.55],
        encode=encode,
        cluster_fn=cluster_fn,
    )

    assert cluster_fn.calls["n"] == 0
    column = stats.columns[0]
    assert column.answered_count == 1
    for threshold_stats in column.thresholds:
        assert threshold_stats.group_count == 1
        assert threshold_stats.largest_group_size == 1
        assert threshold_stats.grouped_share == 0.0
        assert threshold_stats.cross_source_group_count == 0


def test_sweep_encodes_and_clusters_each_column_exactly_once(tmp_path):
    """The load-bearing performance property: a second threshold in the
    sweep must not trigger a second call to the encoder (or to the sweep's
    own clustering function -- one linkage fit services every threshold)."""
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        {
            "book-a": [
                {"chunk_id": f"book-a_{i}", "source_id": "book-a",
                 "answers": {"mechanism": f"sentence {i}"}}
                for i in range(4)
            ]
        },
    )
    encode = _counting_encoder()
    cluster_fn = _counting_cluster_fn(lambda thresholds: {t: [0, 0, 1, 1] for t in thresholds})

    stats = examine_vocabulary(
        answers_dir=answers_dir,
        columns=["mechanism"],
        thresholds=[0.30, 0.50, 0.70, 0.90],
        encode=encode,
        cluster_fn=cluster_fn,
    )

    assert encode.calls["n"] == 1
    assert cluster_fn.calls["n"] == 1
    assert len(stats.columns[0].thresholds) == 4


def test_per_threshold_reports_group_count_share_largest_and_cross_source(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        {
            "book-a": [
                {"chunk_id": "book-a_1", "source_id": "book-a", "answers": {"mechanism": "s0"}},
                {"chunk_id": "book-a_2", "source_id": "book-a", "answers": {"mechanism": "s1"}},
            ],
            "book-b": [
                {"chunk_id": "book-b_1", "source_id": "book-b", "answers": {"mechanism": "s2"}},
                {"chunk_id": "book-b_2", "source_id": "book-b", "answers": {"mechanism": "s3"}},
            ],
        },
    )
    encode = _counting_encoder()
    # s0 (book-a), s2 (book-b) -> label 0 (a real cross-source group of 2).
    # s1 (book-a) -> label 1, alone. s3 (book-b) -> label 2, alone.
    cluster_fn = _counting_cluster_fn(lambda thresholds: {t: [0, 1, 0, 2] for t in thresholds})

    stats = examine_vocabulary(
        answers_dir=answers_dir,
        columns=["mechanism"],
        thresholds=[0.55],
        encode=encode,
        cluster_fn=cluster_fn,
    )

    threshold_stats = stats.columns[0].thresholds[0]
    assert threshold_stats.group_count == 3
    assert threshold_stats.largest_group_size == 2
    assert threshold_stats.grouped_share == 0.5  # 2 of 4 values sit in a group of 2+
    assert threshold_stats.cross_source_group_count == 1


def test_population_above_ceiling_is_sampled_and_the_row_reports_it(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        {
            "book-a": [
                {"chunk_id": f"book-a_{i}", "source_id": "book-a",
                 "answers": {"mechanism": f"sentence {i}"}}
                for i in range(12)
            ]
        },
    )
    encode = _counting_encoder()
    cluster_fn = _counting_cluster_fn(lambda thresholds: {t: [0, 1, 2, 3, 4] for t in thresholds})

    stats = examine_vocabulary(
        answers_dir=answers_dir,
        columns=["mechanism"],
        thresholds=[0.55],
        sample_ceiling=5,
        encode=encode,
        cluster_fn=cluster_fn,
    )

    column = stats.columns[0]
    assert column.answered_count == 12  # the whole column, not the sample
    assert column.sampled is True
    assert column.sample_size == 5
    # The sample, not the whole column, is what got encoded and clustered.
    assert len(encode.calls["batches"][0]) == 5


def test_sampled_row_is_marked_on_every_threshold_row_and_the_summary(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_answers(
        answers_dir,
        {
            "book-a": [
                {"chunk_id": f"book-a_{i}", "source_id": "book-a",
                 "answers": {"mechanism": f"sentence {i}"}}
                for i in range(12)
            ]
        },
    )
    encode = _counting_encoder()
    cluster_fn = _counting_cluster_fn(lambda thresholds: {t: [0, 1, 2, 3, 4] for t in thresholds})

    stats = examine_vocabulary(
        answers_dir=answers_dir,
        columns=["mechanism"],
        thresholds=[0.35, 0.55, 0.75],
        sample_ceiling=5,
        encode=encode,
        cluster_fn=cluster_fn,
    )

    column = stats.columns[0]
    assert column.sampled is True
    # Every threshold row carries the same sampled marker -- not just the
    # column's own summary line -- so no reader can mistake one for a
    # whole-column measurement.
    for threshold_stats in column.thresholds:
        assert threshold_stats.sampled is True
        assert threshold_stats.sample_size == 5

    from axial.vocabulary import format_vocabulary_report

    report = format_vocabulary_report(stats)
    assert report.count("sampled n=5") == len(column.thresholds)
    assert "SAMPLED n=5" in report
