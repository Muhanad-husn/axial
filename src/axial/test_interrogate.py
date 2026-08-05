"""Unit tests for the interrogation pass's pure pieces (issue #419): the D7
abstention shapes, the D8 collapse check, response parsing, the chapter
lookup, and the cost probe's arithmetic. The end-to-end contract is
tests/ingestion/test_interrogate.py.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

import axial.interrogate as interrogate_mod
from axial.codebook import load_codebook
from axial.interrogate import (
    ANSWER_FIELDS,
    DEFAULT_DOMAIN_DIR,
    LIST_VALUED_FIELDS,
    RETIRED_SENTINEL_EXAMPLE_IDS,
    AllNotesFailedError,
    AnswerParseError,
    abstention_rates,
    chapter_for_section,
    collapse_rates,
    corpus_note_count,
    cost_report,
    frame_examples,
    is_abstention,
    parse_answer_response,
    run_interrogate,
)
from axial.schema import load_schema

EXAMPLES = {"move": [("role:claim", "asserts a claim"), ("role:evidence", "offers evidence")]}


def _answers(**overrides: object) -> dict[str, object]:
    answers = {field: f"an answer for {field}" for field in ANSWER_FIELDS}
    answers.update(overrides)
    return answers


# --- D7: abstention is explicit and distinguishable -------------------------


def test_bare_sentinel_and_reasoned_object_both_abstain():
    assert is_abstention("not-in-passage")
    assert is_abstention({"not-in-passage": "cannot judge between Iraq and Egypt"})


def test_a_multi_valued_field_abstains_inside_a_one_element_list_too():
    """Six fields are asked for as JSON lists while the abstention rule is
    written for a scalar, so `["not-in-passage"]` is the natural middle form.
    Read as an answer it would under-report abstention on exactly those
    fields, and Reconcile (§7.16) harvests `names`, so it would mint
    `not-in-passage` as a name in the corpus."""
    assert is_abstention(["not-in-passage"])
    assert is_abstention([{"not-in-passage": "the passage names no one"}])
    records = [{"answers": _answers(names=["not-in-passage"])}]
    assert abstention_rates(records)["names"] == 1.0


def test_a_real_answer_is_never_read_as_an_abstention():
    assert not is_abstention("the passage names no mechanism worth stating")
    assert not is_abstention({"with": "Iraq's Ba'ath", "stated": True})
    assert not is_abstention(["a", "b"])
    # A second element makes it an answer, however malformed: an abstention
    # is never partial.
    assert not is_abstention(["not-in-passage", "Syria"])
    assert not is_abstention([])


def test_abstention_rate_is_per_field_over_answered_notes():
    records = [
        {"answers": _answers(assumes="not-in-passage")},
        {"answers": _answers(assumes={"not-in-passage": "no unspoken premise"})},
        {"answers": _answers()},
        # A failure record carries no answers and never enters the denominator.
        {"chunk_id": "c4", "failure_reason": "boom"},
    ]
    rates = abstention_rates(records)
    assert rates["assumes"] == pytest.approx(2 / 3, abs=1e-4)
    assert rates["claim"] == 0.0


# --- D8: the collapse check -------------------------------------------------


def test_collapse_rate_counts_free_answers_equal_to_an_example_string():
    records = [
        {"answers": _answers(move="Role:Claim  ")},
        {"answers": _answers(move="conceding the coup in order to narrow the claim")},
    ]
    rates = collapse_rates(records, EXAMPLES)
    assert rates["frame_example_rate"]["move"] == 0.5


def test_collapse_rate_also_counts_a_free_answer_equal_to_its_own_nearest():
    records = [
        {
            "answers": _answers(
                move="role:evidence", move_nearest={"example": "role:evidence", "fit": "close"}
            )
        },
        {
            "answers": _answers(
                move="narrowing a concession", move_nearest={"example": "role:claim", "fit": "none"}
            )
        },
    ]
    rates = collapse_rates(records, EXAMPLES)
    assert rates["nearest_example_rate"]["move"] == 0.5


def test_abstentions_are_excluded_from_the_collapse_denominator():
    records = [
        {"answers": _answers(move="not-in-passage")},
        {"answers": _answers(move="role:claim")},
    ]
    assert collapse_rates(records, EXAMPLES)["frame_example_rate"]["move"] == 1.0


# --- Parsing: no vocabulary gate, no bridging -------------------------------


def test_parse_keeps_the_free_answer_and_its_nearest_example_separate():
    raw = json.dumps(
        {
            **_answers(move="conceding a point in order to narrow it"),
            "move_nearest": {"example": "role:claim", "fit": "loose"},
        }
    )
    parsed = parse_answer_response(raw, EXAMPLES)
    assert parsed["move"] == "conceding a point in order to narrow it"
    assert parsed["move_nearest"] == {"example": "role:claim", "fit": "loose"}


def test_parse_accepts_an_answer_matching_no_example_and_a_nearest_of_none():
    raw = json.dumps(
        {
            **_answers(move="something the frame has no word for"),
            "move_nearest": {"example": None, "fit": "none"},
        }
    )
    parsed = parse_answer_response(raw, EXAMPLES)
    assert parsed["move_nearest"] == {"example": None, "fit": "none"}


def test_parse_rejects_a_missing_question_and_a_blank_answer():
    incomplete = json.dumps({field: "x" for field in ANSWER_FIELDS if field != "claim"})
    with pytest.raises(AnswerParseError, match="claim"):
        parse_answer_response(incomplete, EXAMPLES)

    blank = json.dumps(_answers(mechanism="   "))
    with pytest.raises(AnswerParseError, match="mechanism"):
        parse_answer_response(blank, EXAMPLES)

    null = json.dumps(_answers(concedes=None))
    with pytest.raises(AnswerParseError, match="concedes"):
        parse_answer_response(null, EXAMPLES)

    # An empty list on a SCALAR field is still shape noise.
    with pytest.raises(AnswerParseError, match="mechanism"):
        parse_answer_response(json.dumps(_answers(mechanism=[])), EXAMPLES)


def test_an_empty_list_is_an_answer_on_a_list_valued_field_not_a_blank():
    """`[]` is what "this passage defines nothing" looks like in JSON, and it
    is the model's read, not a blank. Rejecting it burned the whole re-ask
    budget on an identical repeated response and then discarded all sixteen
    answers over one field -- permanently, since a note carrying any record is
    never re-sent (§7.15). Measured on a real 10-note probe: `ayubi-1995`
    note 2 lost to `defines: []`."""
    for field in sorted(LIST_VALUED_FIELDS):
        parsed = parse_answer_response(json.dumps(_answers(**{field: []})), EXAMPLES)
        assert parsed[field] == [], field
    # Recorded verbatim, never normalised onto the abstention: `[]` is a read,
    # an abstention is a refusal to guess (§7.15's three states).
    records = [{"answers": _answers(names=[])}]
    assert abstention_rates(records)["names"] == 0.0


# --- #431: joined kind vocabulary offered for `names` -----------------------


def test_the_names_question_offers_joined_kinds_never_their_bare_halves():
    """The founder's decision (#431) is to join ambiguous kind families into
    one label -- `country/state/place`, not `country` or `place` separately --
    so a model that picks a bare half reintroduces the collision the join was
    meant to kill. The prompt must offer the joined label whole and must not
    offer any of its halves as a separate kind."""
    from axial.interrogate import _QUESTIONS

    # Isolate the offered kind list itself -- the property under test is what
    # the model is invited to pick FROM, not the surrounding prose that has to
    # name the bare halves in order to tell the model not to use them.
    offered = _QUESTIONS.split("kind is usually one of ", 1)[1].split(
        " -- use the joined label whole", 1
    )[0]
    kinds = [k.strip() for k in offered.split(",")]

    assert "country/state/place" in kinds
    for bare in ("country", "state", "place"):
        assert bare not in kinds


# --- Frame examples never leak a retired sentinel ---------------------------


def test_position_examples_exclude_the_retired_sentinels_but_keep_the_rest():
    """PRD §D4/§D9 (specs/PRODUCT.md:188,890) retires `not-applicable` and
    `unlisted` for the interrogation pass -- D7's abstention and a verbatim
    free answer do both jobs now. `frame_examples` must not offer either id
    as one of the `position` examples, even though both stay declared in
    the schema/codebook for the gold-set dropdown (`axial.gold`)."""
    schema = load_schema(DEFAULT_DOMAIN_DIR)
    codebook = load_codebook(DEFAULT_DOMAIN_DIR)

    examples = frame_examples(schema, codebook)
    offered_ids = {tag_id for tag_id, _definition in examples["position"]}

    assert offered_ids.isdisjoint(RETIRED_SENTINEL_EXAMPLE_IDS)
    assert offered_ids == schema.axes["theory_school"].tag_ids - RETIRED_SENTINEL_EXAMPLE_IDS


def test_frame_examples_fallback_also_filters_the_retired_sentinels():
    """The codebook-missing fallback (line ~348) reads the schema's raw
    `tag_ids` rather than the codebook, so it must filter independently or a
    domain with no codebook would leak the retired ids back in."""
    schema = load_schema(DEFAULT_DOMAIN_DIR)

    empty_codebook = load_codebook(DEFAULT_DOMAIN_DIR)
    empty_codebook.axes = {}

    examples = frame_examples(schema, empty_codebook)
    offered_ids = {tag_id for tag_id, _definition in examples["position"]}

    assert offered_ids.isdisjoint(RETIRED_SENTINEL_EXAMPLE_IDS)
    assert offered_ids == schema.axes["theory_school"].tag_ids - RETIRED_SENTINEL_EXAMPLE_IDS


# --- #496: whose position and what the position is are two questions --------


def test_the_two_position_questions_are_asked_separately_and_position_of_is_unchanged():
    """`position_of` keeps its wording and its meaning -- it answers WHOSE.
    The new `position` answers WHAT, openly, and the prompt says so sharply
    enough that a passage stating the book's own view is expected to yield
    both an attribution and a substantive stance rather than one or the
    other (76% of the fused field's answers were "the author")."""
    from axial.interrogate import _QUESTIONS

    assert "position_of -- Whose position is this?" in _QUESTIONS
    assert "position -- What IS that position, in the passage's own terms?" in _QUESTIONS
    # The distinction is drawn where the model can act on it: naming the
    # holder must not be accepted as an answer to the second question.
    assert _QUESTIONS.index("position_of --") < _QUESTIONS.index("7. position --")
    assert '"the author\'s own" answers question 6' in _QUESTIONS
    assert ANSWER_FIELDS.index("position") == ANSWER_FIELDS.index("position_of") + 1


def test_the_theory_school_examples_sit_on_position_and_position_of_has_none():
    """The school labels are what a position IS, not whose it is -- they are
    exactly the 24% of fused answers that named a stance. There is no
    vocabulary of position-holders, so `position_of` correctly gets no
    example axis and no `_nearest` key is ever asked for it."""
    schema = load_schema(DEFAULT_DOMAIN_DIR)
    codebook = load_codebook(DEFAULT_DOMAIN_DIR)

    examples = frame_examples(schema, codebook)

    assert "position" in examples
    assert "position_of" not in examples


def test_position_is_required_and_blank_is_rejected_like_every_other_answer():
    missing = json.dumps({field: "x" for field in ANSWER_FIELDS if field != "position"})
    with pytest.raises(AnswerParseError, match="position"):
        parse_answer_response(missing, EXAMPLES)

    with pytest.raises(AnswerParseError, match="position"):
        parse_answer_response(json.dumps(_answers(position="  ")), EXAMPLES)

    parsed = parse_answer_response(
        json.dumps(_answers(position_of="the author", position="war built the state")), EXAMPLES
    )
    assert parsed["position_of"] == "the author"
    assert parsed["position"] == "war built the state"


def test_a_field_a_record_does_not_carry_is_left_out_of_its_own_denominator():
    """The corpus is a mixed frame and stays one: a record written before
    `position` existed has no such key, and `is_abstention(None)` is False,
    so reading over every answered note would silently report a question
    that record was never asked as answered."""
    old_shape = _answers()
    del old_shape["position"]
    records = [
        {"answers": old_shape},
        {"answers": _answers(position="not-in-passage")},
    ]

    rates = abstention_rates(records)

    # One record carries the field, and it abstained.
    assert rates["position"] == 1.0
    # A field both records carry is unaffected.
    assert rates["claim"] == 0.0


def test_a_field_a_record_does_not_carry_is_left_out_of_the_collapse_denominator():
    old_shape = _answers()
    del old_shape["move"]
    records = [{"answers": old_shape}, {"answers": _answers(move="role:claim")}]

    assert collapse_rates(records, EXAMPLES)["frame_example_rate"]["move"] == 1.0


# --- Context assembly -------------------------------------------------------


def test_chapter_is_read_off_the_toc_and_never_guessed():
    toc = [
        {"title": "Part I", "children": []},
        {"title": "Part II", "children": ["Chapter 3 - The State"]},
    ]
    assert chapter_for_section(toc, "chapter 3 -  the state") == "Part II"
    assert chapter_for_section(toc, "Part I") == "Part I"
    assert chapter_for_section(toc, "An Unplaced Heading") is None
    assert chapter_for_section(None, "Part I") is None


# --- The cost probe ---------------------------------------------------------


def test_corpus_note_count_reads_the_chunk_artifact_and_ignores_skip_sidecars(tmp_path):
    (tmp_path / "a.jsonl").write_text('{"chunk_id": "1"}\n{"chunk_id": "2"}\n', encoding="utf-8")
    (tmp_path / "b.jsonl").write_text('{"chunk_id": "3"}\n', encoding="utf-8")
    (tmp_path / "b.skips.jsonl").write_text('{"chunk_id": "4"}\n', encoding="utf-8")
    assert corpus_note_count(tmp_path) == 3
    assert corpus_note_count(tmp_path / "nope") == 0


def test_cost_report_extrapolates_a_measured_per_note_cost_to_the_corpus():
    # Priced off the live table rather than two copied literals: this test is
    # about extrapolating a measured per-note cost, and a price refresh
    # (2026-07-31, issue #493) should not read as a failure of that.
    from axial.llm import PRICE_TABLE_USD_PER_1K

    price = PRICE_TABLE_USD_PER_1K["z-ai/glm-5.2"]
    usage = {"prompt_tokens": 2000, "completion_tokens": 1000, "total_tokens": 3000}
    report = cost_report(usage, "z-ai/glm-5.2", answered=2, corpus_notes=6000)
    assert report["usd"] == pytest.approx(
        2000 / 1000 * price["input"] + 1000 / 1000 * price["output"]
    )
    assert report["usd_per_note"] == pytest.approx(report["usd"] / 2)
    assert report["usd_corpus_extrapolated"] == pytest.approx(report["usd_per_note"] * 6000)
    assert report["tokens_per_note"] == 1500.0


def test_cost_report_reports_null_for_an_unpriced_model_never_zero():
    report = cost_report({"prompt_tokens": 10, "completion_tokens": 5}, "stub", 1, 100)
    assert report["usd"] is None
    assert report["usd_corpus_extrapolated"] is None
    assert report["total_tokens"] == 15


# --- Per-note fault isolation -----------------------------------------------


class _ScriptedClient:
    """A client whose responses are scripted per call, so one note can fail
    while the next answers -- the fault-isolation contract §7.15 states.

    Responses are handed out BY CALL INDEX, so which note receives which
    response is only defined while the calls are serial. Every test using
    this client therefore passes `workers=1` (issue #623, which made the
    pass concurrent by default); concurrency itself is pinned separately by
    `test_notes_are_interrogated_concurrently`, below."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        response = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return response

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "scripted"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return None


def _arrange_source(tmp_path: Path, note_count: int = 2) -> tuple[Path, Path]:
    from axial.envelope import compute_source_id

    data_dir = tmp_path / "data"
    source_path = tmp_path / "book.pdf"
    source_path.write_bytes(b"only ever hashed")
    source_id = compute_source_id(source_path)

    (data_dir / "chunks").mkdir(parents=True)
    with (data_dir / "chunks" / f"{source_id}.jsonl").open("w", encoding="utf-8") as handle:
        for index in range(1, note_count + 1):
            handle.write(
                json.dumps(
                    {
                        "chunk_id": f"{source_id}_1_intro_{index:03d}",
                        "section": "Introduction",
                        "section_order": "1",
                        "text": (
                            "A paragraph of ordinary scholarly prose about state "
                            f"formation, number {index}, long enough to read as prose."
                        ),
                    }
                )
                + "\n"
            )
    (data_dir / "envelopes").mkdir(parents=True)
    (data_dir / "envelopes" / f"{source_id}.json").write_text(
        json.dumps({"thesis": "t", "scope": "s", "stated_argument": "a", "toc": []}),
        encoding="utf-8",
    )
    (data_dir / "source_meta").mkdir(parents=True)
    (data_dir / "source_meta" / f"{source_id}.json").write_text(
        json.dumps({"author": "A", "title": "T", "date": "1999"}), encoding="utf-8"
    )
    return source_path, data_dir


def test_one_failing_note_is_recorded_and_the_source_continues(tmp_path):
    good = json.dumps(_answers())
    client = _ScriptedClient(["not json at all"] * 3 + [good])
    source_path, data_dir = _arrange_source(tmp_path)

    summary = run_interrogate(source_path, client=client, data_dir=data_dir, workers=1)

    assert summary["failed"] == 1
    assert summary["answered"] == 1
    records = [
        json.loads(line)
        for line in (data_dir / "answers" / f"{summary['source_id']}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "failure_reason" in records[0]
    assert "answers" in records[1]


def test_a_source_whose_every_note_failed_raises_rather_than_reporting_success(tmp_path):
    client = _ScriptedClient(["not json at all"])
    source_path, data_dir = _arrange_source(tmp_path)

    with pytest.raises(AllNotesFailedError):
        run_interrogate(source_path, client=client, data_dir=data_dir, workers=1)


def test_rerunning_after_a_total_failure_raises_again_instead_of_reporting_success(tmp_path):
    """The path an operator actually takes after seeing the error is to run
    it again. Every note already carries a failure record, so the second run
    makes no call at all -- and must still raise. Reporting success here
    would let `axial run interrogate` mark the source done with zero answers
    on disk, and slice 04 would read an empty answer set for the whole book."""
    source_path, data_dir = _arrange_source(tmp_path)
    with pytest.raises(AllNotesFailedError):
        run_interrogate(
            source_path,
            client=_ScriptedClient(["not json at all"]),
            data_dir=data_dir,
            workers=1,
        )

    second = _ScriptedClient([json.dumps(_answers())])
    with pytest.raises(AllNotesFailedError):
        run_interrogate(source_path, client=second, data_dir=data_dir, workers=1)
    assert second.call_count == 0


def test_a_source_whose_every_note_is_a_garble_skip_is_not_a_failure(tmp_path):
    """Skips are not failures: a source the backstop dropped entirely has
    zero answer records legitimately, and must not raise."""
    source_path, data_dir = _arrange_source(tmp_path, note_count=1)
    from axial.envelope import compute_source_id

    source_id = compute_source_id(source_path)
    (data_dir / "chunks" / f"{source_id}.jsonl").write_text(
        json.dumps(
            {
                "chunk_id": f"{source_id}_1_intro_001",
                "section": "Introduction",
                "section_order": "1",
                "text": "%%%% 1234 ;;;; ---- @@@@ 5678 //// ==== ++++ 9012 ****",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = _ScriptedClient([json.dumps(_answers())])

    summary = run_interrogate(source_path, client=client, data_dir=data_dir, workers=1)

    assert client.call_count == 0
    assert summary["skipped"] == 1
    assert summary["answer_records"] == 0


class _BarrierClient:
    """A client whose calls block until `expected` of them are simultaneously
    in flight, so the pass can only finish if it really overlaps them (issue
    #623). Serial code deadlocks here and trips the barrier's own timeout --
    which is the point: this test cannot pass without concurrency."""

    def __init__(self, expected: int, answer: str) -> None:
        self._barrier = threading.Barrier(expected, timeout=10)
        self._answer = answer
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = threading.Lock()

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        self._barrier.wait()
        with self._lock:
            self._in_flight -= 1
        return self._answer

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "barrier"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return None


def test_notes_are_interrogated_concurrently(tmp_path):
    """Issue #623: this pass made one call at a time, so a 234-note source took
    102 minutes at an effective concurrency of 1.00 while every other
    model-backed pass ran at 20-34. The barrier only releases once all four
    notes are in flight together."""
    source_path, data_dir = _arrange_source(tmp_path, note_count=4)
    client = _BarrierClient(expected=4, answer=json.dumps(_answers()))

    summary = run_interrogate(source_path, client=client, data_dir=data_dir, workers=4)

    assert summary["answered"] == 4
    assert client.max_in_flight == 4


def test_every_note_is_still_recorded_exactly_once_when_run_concurrently(tmp_path):
    """Concurrency must not cost the checkpoint's one-record-per-note
    guarantee: every append happens on the single collecting thread."""
    source_path, data_dir = _arrange_source(tmp_path, note_count=12)
    client = _BarrierClient(expected=12, answer=json.dumps(_answers()))

    summary = run_interrogate(source_path, client=client, data_dir=data_dir, workers=12)

    lines = (
        (data_dir / "answers" / f"{summary['source_id']}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    chunk_ids = [json.loads(line)["chunk_id"] for line in lines]
    assert len(chunk_ids) == 12
    assert len(set(chunk_ids)) == 12
    assert summary["answered"] == 12


def test_pass_worker_defaults_are_concurrent_by_default():
    """Issue #623: the founder's standing requirement that a pass is fast by
    DEFAULT, not only when an operator remembers a flag."""
    import axial.argmap.build as argmap_build
    import axial.argmap.residue as argmap_residue
    import axial.gather as gather_mod
    import axial.merge_names as merge_mod

    assert interrogate_mod.DEFAULT_WORKERS == 12
    assert gather_mod.DEFAULT_WORKERS == 48
    assert argmap_build.WORKERS == 40
    assert argmap_residue.WORKERS == argmap_build.WORKERS
    assert merge_mod.DEFAULT_WORKERS == 36
