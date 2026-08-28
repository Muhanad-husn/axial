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
    DEFAULT_VOCABULARY_SCHEME_PATH,
    PopulationEntry,
    SchemeVersionMismatchError,
    SelfConsistencyError,
    VocabularyExamineStats,
    _cost_delta,
    build_vocabulary,
    draw_vocabulary_samples,
    examine_vocabulary,
    format_vocabulary_report,
    load_vocabulary_scheme,
    read_column,
    scheme_columns,
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


# ---------------------------------------------------------------------------
# _cost_delta: computing the cost incurred in a pass
# ---------------------------------------------------------------------------


def test_cost_delta_none_before_with_float_after_returns_full_after_value():
    """When before is None (nothing had been spent on that pass yet), treat it
    as 0.0, so the delta is after - 0.0 = after."""
    assert _cost_delta(None, 0.5) == 0.5
    assert _cost_delta(None, 0.001) == 0.001
    assert _cost_delta(None, 10.0) == 10.0


def test_cost_delta_normal_case_returns_difference():
    """When both before and after are floats, return the difference."""
    assert _cost_delta(0.1, 0.5) == 0.4
    assert _cost_delta(1.0, 3.5) == 2.5


def test_cost_delta_none_after_returns_none():
    """When after is None, the genuine unknown case, return None."""
    assert _cost_delta(0.1, None) is None
    assert _cost_delta(None, None) is None


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


def test_read_column_numbers_each_list_element_by_its_raw_position():
    """`element_index` (issue #806) is the third part of the key a persisted
    assignment is filed under, so it must tell two elements of one note's
    list apart -- and it counts RAW list positions, so an element excluded
    as an abstention consumes its own index instead of shifting the ones
    after it onto keys another element already holds."""
    records = [
        {
            "chunk_id": "book-a_1",
            "source_id": "book-a",
            "answers": {"arguing_against": ["claim one", "not-in-passage", "claim three"]},
        },
        {
            "chunk_id": "book-b_1",
            "source_id": "book-b",
            "answers": {"arguing_against": ["claim four"]},
        },
    ]

    population, excluded = read_column(records, "arguing_against")

    assert excluded == 1
    assert [(entry.chunk_id, entry.element_index) for entry in population] == [
        ("book-a_1", 0),
        ("book-a_1", 2),
        ("book-b_1", 0),
    ]


def test_read_column_scalar_values_are_always_element_index_zero():
    records = [
        {"chunk_id": "book-a_1", "source_id": "book-a", "answers": {"mechanism": "one"}},
        {"chunk_id": "book-b_1", "source_id": "book-b", "answers": {"mechanism": "two"}},
    ]

    population, _ = read_column(records, "mechanism")

    assert [entry.element_index for entry in population] == [0, 0]


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
    category counts as unassigned, exactly like "none". PR #815 review
    (F4): this is specifically a REFUSAL (the index came back, its label
    just names no known category) and must be counted on `refused_count`,
    not `unanswered_count` -- an index the model never returned at all is
    the other, distinct failure mode."""
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
    assert column.unanswered_count == 0  # both batches returned every index they were asked about
    assert column.refused_count == 1  # index 2's "an invented category" is a refusal, not a drop


def test_assign_batch_raises_when_a_batch_response_is_missing_an_index():
    """F4 (PR #815 review): a truncated completion -- these calls run
    170-250s producing ~10k completion tokens, squarely the regime where a
    completion loses its tail -- must not be trusted as "the rest is
    unassigned". `_assign_batch` validates the returned keys are exactly
    the indexes the batch asked about and raises `VocabularyResponseError`
    when they are not; `complete_json`'s own `validate` seam re-asks on
    that within its bounded attempt budget."""
    batch = [
        PopulationEntry("v1", "c1", "book-a"),
        PopulationEntry("v2", "c2", "book-a"),
    ]

    class _TruncatedClient:
        def __init__(self):
            self.calls = 0

        def complete(self, prompt, pass_name=None):
            self.calls += 1
            # Always missing index 2 -- a persistent truncation, not a
            # one-off stochastic glitch.
            return _assign_json([(1, "Cat A")])

    client = _TruncatedClient()
    with pytest.raises(vocabulary_mod.VocabularyResponseError):
        vocabulary_mod._assign_batch(client, "some-pass", "- Cat A: gloss a", batch, start=0)
    # complete_json's default attempts=3 re-asks the same batch on a
    # bounded budget rather than trusting the first truncated response.
    assert client.calls == 3


def test_assign_batch_raises_when_a_later_batch_is_renumbered_from_one():
    """A model that renumbers a later batch 1..N instead of continuing the
    global numbering must never be merged in silently -- `dict.update`
    would overwrite the earlier batch's real assignments with a response
    about the wrong indexes, and those earlier indexes would read as
    unanswered with no way to tell why."""
    batch = [
        PopulationEntry("v101", "c101", "book-a"),
        PopulationEntry("v102", "c102", "book-a"),
    ]

    class _RenumberedClient:
        def complete(self, prompt, pass_name=None):
            # This batch starts at index 101 (start=100) but the model
            # numbers it 1, 2 as though it were the first batch.
            return _assign_json([(1, "Cat A"), (2, "Cat A")])

    client = _RenumberedClient()
    with pytest.raises(vocabulary_mod.VocabularyResponseError):
        vocabulary_mod._assign_batch(client, "some-pass", "- Cat A: gloss a", batch, start=100)


def test_examine_vocabulary_reasks_a_truncated_assign_batch_and_then_succeeds(tmp_path):
    """The re-ask path end to end: a first assign-batch response missing an
    index is rejected and re-asked (`complete_json`'s own seam), and the
    resulting stats show a clean, fully-accounted-for assignment -- no
    value silently lost to a truncated completion's tail."""
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=4)

    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([("Cat A", "gloss a")]),
                _assign_json([(1, "Cat A")]),  # truncated: missing index 2
                _assign_json([(1, "Cat A"), (2, "Cat A")]),  # re-ask: complete
            ],
            vocabulary_mod.CHECK_PASS_NAME: [_assign_json([(1, "Cat A"), (2, "Cat A")])],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    stats = examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=2, assign_n=2, seed=0, client=client
    )

    column = stats.columns[0]
    assert column.assignment_rate == 1.0
    assert column.unanswered_count == 0
    assert column.refused_count == 0
    # 1 propose + 2 assign attempts (1 truncated, re-asked once).
    assert client.calls_for_pass(vocabulary_mod.EXAMINE_PASS_NAME) == 3


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
    # agreement about where the value belongs) -- this is the OVERALL rate,
    # and it is what's computed here.
    assert column.agreement_sample_size == 4
    assert column.agreement_rate == 0.5

    # Restricted to entries the FIRST model placed in a real category
    # (indices 1 and 3 -- 2 and 4 were "none" on the first model's own
    # assignment and are excluded from this denominator, not counted as
    # agreement). Of those two, only index 1 (Cat A/Cat A) agrees.
    assert column.agreement_where_assigned_sample_size == 2
    assert column.agreement_where_assigned_rate == 0.5


def test_agreement_where_assigned_is_none_when_the_first_model_assigned_nothing_in_the_subsample(
    tmp_path,
):
    """Bar condition 5 is about the rate on values the FIRST model actually
    placed in a category. When the first model assigned every value in the
    check subsample to "none", the restricted rate has no denominator and
    must be reported as `None`, never `0.0` -- a zero would read as "the
    models disagreed" when in fact nothing was measured."""
    answers_dir = tmp_path / "answers"
    _write_small_column(answers_dir, n=6)

    client = _FakeVocabClient(
        responses_by_pass={
            vocabulary_mod.EXAMINE_PASS_NAME: [
                _propose_json([("Cat A", "gloss a")]),
                _assign_json([(1, "none"), (2, "none"), (3, "none"), (4, "none")]),
            ],
            vocabulary_mod.CHECK_PASS_NAME: [
                _assign_json([(1, "Cat A"), (2, "none"), (3, "Cat A"), (4, "none")])
            ],
        },
        models={vocabulary_mod.EXAMINE_PASS_NAME: "model-a", vocabulary_mod.CHECK_PASS_NAME: "model-b"},
    )

    stats = examine_vocabulary(
        answers_dir=answers_dir, columns=["mechanism"], propose_n=2, assign_n=4, seed=0, client=client
    )

    column = stats.columns[0]
    # Overall agreement is still measurable (both-"none" counted).
    assert column.agreement_sample_size == 4
    assert column.agreement_rate == 0.5  # 2 and 4 agree (both "none")

    assert column.agreement_where_assigned_sample_size == 0
    assert column.agreement_where_assigned_rate is None


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
        unanswered_count=0,
        refused_count=117,
        categories_5plus=1,
        categories_5plus_cross_source=1,
        largest_category_share=0.108,
        agreement_rate=0.82,
        agreement_sample_size=100,
        agreement_where_assigned_rate=0.91,
        agreement_where_assigned_sample_size=71,
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
    # F4 (PR #815 review): unanswered (no returned entry) and refused
    # ("none"/out-of-scheme) are printed separately, never merged into one
    # "unassigned" figure a reader cannot split back apart.
    assert "unanswered (no returned entry): 0" in report
    assert 'refused ("none"/out-of-scheme): 117' in report
    assert "categories with 5+ members: 1" in report
    assert "spanning 2+ sources: 1" in report
    # F3 (PR #815 review): the denominator is named in the line itself.
    assert "largest category share (of the held-out sample): 10.8%" in report
    assert "two-model agreement overall (subsample of 100): 82.0%" in report
    assert (
        "two-model agreement where the first model assigned a category "
        "(n=71): 91.0%" in report
    )
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
        unanswered_count=None,
        refused_count=None,
        categories_5plus=None,
        categories_5plus_cross_source=None,
        largest_category_share=None,
        agreement_rate=None,
        agreement_sample_size=None,
        agreement_where_assigned_rate=None,
        agreement_where_assigned_sample_size=None,
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


# ---------------------------------------------------------------------------
# The committed `claim` scheme (issue #826, positions-not-names slice 01)
# ---------------------------------------------------------------------------

# The nine ids the founder approved 2026-08-28 -- a pin against silent
# drift in `config/vocabulary.yaml`.
_CLAIM_SCHEME_IDS = {
    "causal-argument-state-formation-or-power",
    "empirical-finding-without-causal-claim",
    "characterization-of-regime-movement-or-system",
    "causal-argument-violence-war-or-conflict",
    "critique-of-existing-theories-or-concepts",
    "bibliographic-source-note-or-formal-description",
    "causal-argument-nationalism-or-identity",
    "methodological-preconditions",
    "comparative-or-typological-classification",
}


def test_the_committed_claim_scheme_parses_with_unique_ids_names_glosses_and_own_version():
    claim = load_vocabulary_scheme("claim", DEFAULT_VOCABULARY_SCHEME_PATH)
    mechanism = load_vocabulary_scheme("mechanism", DEFAULT_VOCABULARY_SCHEME_PATH)

    assert claim.version
    # A scheme edit is a version bump -- two columns must never share one,
    # or a mismatch in one would silently read as settled by the other's.
    assert claim.version != mechanism.version

    ids = [category.id for category in claim.categories]
    names = [category.name for category in claim.categories]
    assert len(ids) == len(set(ids))
    assert all(category.name.strip() for category in claim.categories)
    assert all(category.gloss.strip() for category in claim.categories)
    assert len(names) == len(set(names))


def test_scheme_columns_returns_claim_alongside_mechanism():
    columns = scheme_columns(DEFAULT_VOCABULARY_SCHEME_PATH)

    assert "mechanism" in columns
    assert "claim" in columns


def test_the_committed_claim_scheme_pins_nine_categories_and_their_exact_ids():
    """A pin against silent drift: the founder approved exactly these nine
    categories 2026-08-28, folding the drafted tenth (below the 5-member
    bar) into the bibliographic/formal-description category rather than
    dropping it."""
    claim = load_vocabulary_scheme("claim", DEFAULT_VOCABULARY_SCHEME_PATH)

    assert len(claim.categories) == 9
    assert {category.id for category in claim.categories} == _CLAIM_SCHEME_IDS


def test_vocabulary_build_refuses_a_claim_manifest_built_under_a_different_scheme_version(
    tmp_path,
):
    """Existing behaviour (proven on `mechanism` in
    `test_vocabulary_build.py`), extended here to prove it is column-generic
    rather than something `mechanism` alone happens to satisfy."""
    scheme_path = tmp_path / "vocabulary.yaml"
    answers_dir = tmp_path / "answers"
    vocabulary_dir = tmp_path / "vocabulary"
    answers_dir.mkdir(parents=True, exist_ok=True)
    (answers_dir / "book-a.jsonl").write_text(
        json.dumps(
            {"chunk_id": "book-a_1", "source_id": "book-a", "answers": {"claim": "a claim sentence"}}
        )
        + "\n",
        encoding="utf-8",
    )

    def _write_claim_scheme(version):
        scheme_path.write_text(
            "columns:\n"
            "  claim:\n"
            f'    version: "{version}"\n'
            "    categories:\n"
            "      - id: cat-a\n"
            '        name: "Cat A"\n'
            '        gloss: "gloss a"\n',
            encoding="utf-8",
        )

    _write_claim_scheme("claim-test-v1")
    first_client = _FakeVocabClient(
        responses_by_pass={vocabulary_mod.BUILD_PASS_NAME: [_assign_json([(1, "Cat A")])]},
        models={vocabulary_mod.BUILD_PASS_NAME: "model-a"},
    )
    build_vocabulary(
        answers_dir=answers_dir,
        columns=["claim"],
        scheme_path=scheme_path,
        vocabulary_dir=vocabulary_dir,
        client=first_client,
    )

    _write_claim_scheme("claim-test-v2")
    second_client = _FakeVocabClient(
        responses_by_pass={vocabulary_mod.BUILD_PASS_NAME: [_assign_json([(1, "Cat A")])]},
        models={vocabulary_mod.BUILD_PASS_NAME: "model-a"},
    )

    with pytest.raises(SchemeVersionMismatchError) as excinfo:
        build_vocabulary(
            answers_dir=answers_dir,
            columns=["claim"],
            scheme_path=scheme_path,
            vocabulary_dir=vocabulary_dir,
            client=second_client,
        )

    message = str(excinfo.value)
    assert "claim" in message
    assert "claim-test-v1" in message
    assert "claim-test-v2" in message
    assert second_client.calls_for_pass(vocabulary_mod.BUILD_PASS_NAME) == 0


def test_format_report_says_restricted_agreement_is_not_applicable_rather_than_zero():
    """When the check subsample's first-model assignments were all "none",
    `agreement_where_assigned_rate` is `None` -- the report must say so in
    words, never print a `0.0%` that would read as measured disagreement."""
    column = ColumnVocabularyStats(
        column="mechanism",
        answered_count=10,
        distinct_count=10,
        excluded_count=0,
        propose_sample_size=6,
        assign_sample_size=4,
        reduced=False,
        proposal_failed=False,
        categories=[CategoryReport("Cat A", "gloss a", 1, 1)],
        assignment_rate=0.25,
        unanswered_count=0,
        refused_count=3,
        categories_5plus=0,
        categories_5plus_cross_source=0,
        largest_category_share=0.25,
        agreement_rate=0.5,
        agreement_sample_size=4,
        agreement_where_assigned_rate=None,
        agreement_where_assigned_sample_size=0,
        examine_model="model-a",
        check_model="model-b",
        examine_calls=2,
        examine_cost=0.002,
        check_calls=1,
        check_cost=0.001,
    )

    report = format_vocabulary_report(VocabularyExamineStats(columns=[column]))

    assert "unanswered (no returned entry): 0" in report
    assert 'refused ("none"/out-of-scheme): 3' in report
    assert "two-model agreement overall (subsample of 4): 50.0%" in report
    assert (
        "two-model agreement where the first model assigned a category: "
        "not applicable" in report
    )
    assert "assigned a category: 0.0%" not in report
