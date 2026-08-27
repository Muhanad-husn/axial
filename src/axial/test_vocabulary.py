"""Inner unit tests for `axial.vocabulary` (issue #805, derived-vocabulary
slice 01). Every test injects its own fake client (`_FakeVocabClient`,
mirroring `axial.argmap.build.run_map_build`/`axial.gather.run_gather`'s own
client-injection seam), so no test makes a network call or pays for a real
completion -- the real CLI wiring (`get_client()`) is exercised once, at
the CLI level, in `test_cli.py::test_main_vocabulary_examine_...`.
"""

from __future__ import annotations

import collections
import json

import pytest

from axial.vocabulary import (
    CategoryReport,
    ColumnVocabularyStats,
    PopulationEntry,
    SelfConsistencyError,
    VocabularyExamineStats,
    draw_vocabulary_samples,
    examine_vocabulary,
    format_vocabulary_report,
    read_column,
)
import axial.vocabulary as vocabulary_mod


def _write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_answers(answers_dir, records_by_source):
    answers_dir.mkdir(parents=True, exist_ok=True)
    for source_id, records in records_by_source.items():
        _write_jsonl(answers_dir / f"{source_id}.jsonl", records)


def _propose_json(name_glosses):
    return json.dumps(
        {"categories": [{"name": name, "gloss": gloss} for name, gloss in name_glosses]}
    )


def _assign_json(pairs):
    return json.dumps({"assignments": [{"n": n, "category": category} for n, category in pairs]})


class _FakeVocabClient:
    """A minimal `LLMClient`: canned responses, queued per pass name in the
    order they are expected to be asked for; raises loudly (an
    `AssertionError`, not a silent stall) if a test's own scripted queue
    for a pass runs dry, so a test that under-scripts a call fails instead
    of hanging. Records every prompt by pass name, so a test can assert on
    what a call actually saw (the held-out property this slice exists to
    prove)."""

    def __init__(self, responses_by_pass, models):
        self._responses = {name: list(queue) for name, queue in responses_by_pass.items()}
        self._models = models
        self.prompts_by_pass: dict[str, list[str]] = collections.defaultdict(list)
        self._calls: dict[str, int] = collections.defaultdict(int)
        self._cost: dict[str, float] = collections.defaultdict(float)

    def complete(self, prompt, pass_name=None):
        self.prompts_by_pass[pass_name].append(prompt)
        self._calls[pass_name] += 1
        self._cost[pass_name] += 0.001
        queue = self._responses.get(pass_name)
        if not queue:
            raise AssertionError(f"_FakeVocabClient: no canned response left for pass {pass_name!r}")
        return queue.pop(0)

    def model_for_pass(self, pass_name=None):
        return self._models.get(pass_name, "fake/default")

    def calls_for_pass(self, pass_name=None):
        return self._calls.get(pass_name, 0)

    def cost_for_pass(self, pass_name=None):
        return self._cost.get(pass_name) if self._calls.get(pass_name, 0) else None


# ---------------------------------------------------------------------------
# read_column (kept, unchanged behaviour)
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


def test_read_column_excludes_abstention_and_does_not_categorise_it():
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
# draw_vocabulary_samples: the propose/assign split
# ---------------------------------------------------------------------------


def test_draw_vocabulary_samples_propose_and_assign_never_intersect():
    population = [PopulationEntry(f"v{i}", f"c{i}", "book-a") for i in range(15)]

    propose, assign, reduced = draw_vocabulary_samples(population, propose_n=6, assign_n=6, seed=3)

    assert len(propose) == 6
    assert len(assign) == 6
    assert set(propose).isdisjoint(set(assign))
    assert reduced is False


def test_draw_vocabulary_samples_is_reproducible_under_the_same_seed():
    population = [PopulationEntry(f"v{i}", f"c{i}", "book-a") for i in range(15)]

    propose_a, assign_a, _ = draw_vocabulary_samples(population, propose_n=6, assign_n=6, seed=7)
    propose_b, assign_b, _ = draw_vocabulary_samples(population, propose_n=6, assign_n=6, seed=7)

    assert propose_a == propose_b
    assert assign_a == assign_b


def test_draw_vocabulary_samples_reduces_when_population_is_smaller_than_combined():
    population = [PopulationEntry(f"v{i}", f"c{i}", "book-a") for i in range(5)]

    propose, assign, reduced = draw_vocabulary_samples(population, propose_n=3, assign_n=3, seed=0)

    assert reduced is True
    assert len(propose) == 3
    assert len(assign) == 2  # only 2 left after propose took 3 of the 5


# ---------------------------------------------------------------------------
# examine_vocabulary: propose -> assign held-out -> self-consistency check
# ---------------------------------------------------------------------------


def _write_small_column(answers_dir, n=6):
    _write_answers(
        answers_dir,
        {
            "book-a": [
                {"chunk_id": f"book-a_{i}", "source_id": "book-a",
                 "answers": {"mechanism": f"sentence {i}"}}
                for i in range(n)
            ]
        },
    )


def test_propose_call_never_sees_any_value_from_the_held_out_assign_sample(tmp_path):
    """The whole measurement: the propose prompt is built only from the
    propose sample, so it can never be asked to grade against, or leak
    into, values the assign sample holds out."""
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=10)

    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([("Cat A", "gloss a")]),
                _assign_json([(1, "Cat A"), (2, "Cat A"), (3, "Cat A"), (4, "Cat A")]),
            ],
            vocabulary_mod.CHECK_PASS_NAME: [
                _assign_json([(1, "Cat A"), (2, "Cat A"), (3, "Cat A"), (4, "Cat A")])
            ],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    stats = examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=4, assign_n=4, seed=0, client=client
    )

    column = stats.columns[0]
    propose_prompt = client.prompts_by_pass[vocabulary_mod.EXAMINE_PASS_NAME][0]
    _, assign_sample, _ = draw_vocabulary_samples(
        read_column(
            [
                {"chunk_id": f"book-a_{i}", "source_id": "book-a", "answers": {"mechanism": f"sentence {i}"}}
                for i in range(10)
            ],
            "mechanism",
        )[0],
        propose_n=4,
        assign_n=4,
        seed=0,
    )
    for entry in assign_sample:
        assert entry.value not in propose_prompt
    assert column.assignment_rate == 1.0


def test_a_returned_label_outside_the_scheme_counts_as_unassigned_never_a_new_category(tmp_path, monkeypatch):
    """Assignment runs in batches, and the model may not invent a category
    at assignment time -- a label it returns that names no proposed
    category counts as unassigned, exactly like "none"."""
    monkeypatch.setattr(vocabulary_mod, "BATCH_SIZE", 2)
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=6)

    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([("Cat A", "gloss a")]),
                _assign_json([(1, "Cat A"), (2, "an invented category")]),
                _assign_json([(3, "Cat A"), (4, "Cat A")]),
            ],
            vocabulary_mod.CHECK_PASS_NAME: [
                _assign_json([(1, "Cat A"), (2, "Cat A"), (3, "Cat A"), (4, "Cat A")])
            ],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    stats = examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=2, assign_n=4, seed=0, client=client
    )

    column = stats.columns[0]
    # 2 batches of BATCH_SIZE=2 over a 4-item held-out sample.
    assert client.calls_for_pass(vocabulary_mod.EXAMINE_PASS_NAME) == 3  # 1 propose + 2 assign batches
    assert column.assignment_rate == 0.75  # 3 of 4 assigned, 1 unassigned (the invented label)
    assert column.categories[0].member_count == 3


def test_proposal_returning_roughly_as_many_categories_as_shown_is_flagged_and_assignment_is_skipped(tmp_path):
    """A model that restates the sample rather than categorising it must
    never have its numbers reported as a result, and assignment/the check
    must never spend on a scheme that already failed."""
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=10)

    # 4 categories for a 6-value propose sample -- above RESTATEMENT_RATIO's
    # own 0.5 floor (4 > 6 * 0.5 == 3).
    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([(f"cat-{i}", f"gloss {i}") for i in range(4)])
            ],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    stats = examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=6, assign_n=4, seed=0, client=client
    )

    column = stats.columns[0]
    assert column.proposal_failed is True
    assert column.assignment_rate is None
    assert column.agreement_rate is None
    assert client.calls_for_pass(vocabulary_mod.EXAMINE_PASS_NAME) == 1  # propose only
    assert client.calls_for_pass(vocabulary_mod.CHECK_PASS_NAME) == 0


def test_second_model_agreement_rate_is_measured_against_the_first_models_own_assignment(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=6)

    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([("Cat A", "gloss a")]),
                _assign_json([(1, "Cat A"), (2, "none"), (3, "Cat A"), (4, "none")]),
            ],
            vocabulary_mod.CHECK_PASS_NAME: [
                _assign_json([(1, "Cat A"), (2, "Cat A"), (3, "none"), (4, "none")])
            ],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    stats = examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=2, assign_n=4, seed=0, client=client
    )

    column = stats.columns[0]
    # 1: Cat A/Cat A agree. 2: none/Cat A disagree. 3: Cat A/none disagree.
    # 4: none/none agree (both models saying "nowhere in scheme" IS
    # agreement about where the value belongs).
    assert column.agreement_sample_size == 4
    assert column.agreement_rate == 0.5


def test_population_smaller_than_combined_samples_is_measured_on_what_it_has_and_reduced_is_reported(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=5)

    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([("Cat A", "gloss a")]),
                _assign_json([(1, "Cat A"), (2, "Cat A")]),
            ],
            vocabulary_mod.CHECK_PASS_NAME: [_assign_json([(1, "Cat A"), (2, "Cat A")])],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    stats = examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=3, assign_n=3, seed=0, client=client
    )

    column = stats.columns[0]
    assert column.answered_count == 5  # the whole column, not the reduced sample
    assert column.reduced is True
    assert column.propose_sample_size == 3
    assert column.assign_sample_size == 2
    assert column.assignment_rate == 1.0


def test_self_consistency_error_raised_before_any_call_when_check_resolves_to_the_same_model(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=1)

    client = _FakeVocabClient(
        responses_by_pass={},
        models={
            vocabulary_mod.EXAMINE_PASS_NAME: "same/model",
            vocabulary_mod.CHECK_PASS_NAME: "same/model",
        },
    )

    with pytest.raises(SelfConsistencyError):
        examine_vocabulary(answers_dir=answers_dir, columns=["mechanism"], client=client)

    assert client.calls_for_pass(vocabulary_mod.EXAMINE_PASS_NAME) == 0
    assert client.calls_for_pass(vocabulary_mod.CHECK_PASS_NAME) == 0


def test_examine_vocabulary_writes_nothing_outside_the_answers_dir(tmp_path):
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=4)

    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([("Cat A", "gloss a")]),
                _assign_json([(1, "Cat A"), (2, "Cat A")]),
            ],
            vocabulary_mod.CHECK_PASS_NAME: [_assign_json([(1, "Cat A"), (2, "Cat A")])],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    before = sorted(str(p) for p in tmp_path.rglob("*"))
    examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=2, assign_n=2, seed=0, client=client
    )
    after = sorted(str(p) for p in tmp_path.rglob("*"))

    assert before == after


# ---------------------------------------------------------------------------
# format_vocabulary_report
# ---------------------------------------------------------------------------


def test_format_report_includes_every_bar_figure_and_the_agreement_rate():
    column = ColumnVocabularyStats(
        column="mechanism",
        answered_count=400,
        distinct_count=400,
        excluded_count=3,
        propose_sample_size=400,
        assign_sample_size=400,
        reduced=False,
        proposal_failed=False,
        categories=[
            CategoryReport("Elite networks and clientelism", "elite capture of the state", 25, 13),
            CategoryReport("One-off", "a category nothing else joined", 1, 1),
        ],
        assignment_rate=0.708,
        categories_5plus=1,
        categories_5plus_cross_source=1,
        largest_category_share=0.108,
        agreement_rate=0.82,
        agreement_sample_size=100,
        examine_model="z-ai/glm-5.2",
        check_model="deepseek/deepseek-v4-pro",
        examine_calls=5,
        examine_cost=0.021,
        check_calls=1,
        check_cost=0.004,
    )

    report = format_vocabulary_report(VocabularyExamineStats(columns=[column]))

    assert "mechanism: 400 answered value(s), 400 distinct string(s), 3 excluded" in report
    assert "Elite networks and clientelism" in report
    assert "elite capture of the state" in report
    assert "25 member(s), 13 source(s)" in report
    assert "assignment rate on held-out sample: 70.8%" in report
    assert "categories with 5+ members: 1" in report
    assert "spanning 2+ sources: 1" in report
    assert "largest category share: 10.8%" in report
    assert "two-model agreement on subsample of 100: 82.0%" in report
    assert "z-ai/glm-5.2" in report
    assert "deepseek/deepseek-v4-pro" in report
    assert "5 call(s)" in report
    assert "cost $0.0210" in report


def test_format_report_flags_a_proposal_failure_instead_of_reporting_numbers():
    column = ColumnVocabularyStats(
        column="mechanism",
        answered_count=10,
        distinct_count=10,
        excluded_count=0,
        propose_sample_size=6,
        assign_sample_size=4,
        reduced=False,
        proposal_failed=True,
        categories=[CategoryReport(f"cat-{i}", f"gloss {i}", 0, 0) for i in range(4)],
        assignment_rate=None,
        categories_5plus=None,
        categories_5plus_cross_source=None,
        largest_category_share=None,
        agreement_rate=None,
        agreement_sample_size=None,
        examine_model="model-a",
        check_model="model-b",
        examine_calls=1,
        examine_cost=0.001,
        check_calls=0,
        check_cost=None,
    )

    report = format_vocabulary_report(VocabularyExamineStats(columns=[column]))

    assert "PROPOSAL FAILED" in report
    assert "assignment rate" not in report
    assert "two-model agreement" not in report
