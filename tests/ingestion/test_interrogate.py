"""Outer acceptance test for issue #419 (Phase A v1 slice 02 -- the
interrogation pass).

Locked behavioural contract, read off specs/PRODUCT.md §7.15 / P0-6 (D6, D7,
D8, D14):

Given a source whose notes, envelope and source-metadata record are already
      on disk, and AXIAL_LLM_PROVIDER=stub
When  the operator runs `axial interrogate <source> --data-dir <dir>`
Then  every note in the chunk artifact produces exactly one answer record in
      `<dir>/answers/<source_id>.jsonl`, keyed by chunk_id
And   each record answers all thirteen D6 questions, carries its pass name,
      model, frame version and timestamp, and carries no vote/draws field
And   the prompt carries exactly §7.15's context (note text, author/title/
      date, thesis/scope/stated argument, chapter/section, the frame as
      examples) and asks each free answer BEFORE showing that question's
      examples (D8)
And   a field the passage does not support records the explicit abstention
      `not-in-passage`, distinguishable from an answer (D7)
And   the run reports the collapse check, the per-field abstention rate and
      the measured cost, extrapolated to the corpus (P0-6).

Seam decisions
-----------------------------------------------------------------------
1. **No extraction, no docling, no fixture PDF.** This pass reads three
   on-disk artifacts and never re-derives any of them (§7.7: boundaries are
   computed once by `axial chunk`). `compute_source_id` hashes the source
   file's bytes and never parses it, so the "source" here is a byte blob:
   the test arranges the chunk artifact, the envelope and the source-meta
   record itself. That keeps the acceptance criterion about the
   interrogation's own behaviour rather than about extraction, and it runs
   in milliseconds.

2. **`--data-dir` is the one directory override.** The cost probe has to be
   pointable at another checkout's `data/` from elsewhere (issue #419), and
   the four directories it needs (`chunks/`, `envelopes/`, `source_meta/`,
   `answers/`) share one parent. One flag, not four.

3. **The thirteen questions are asserted by their field names**, taken from
   §7.15's own table, not imported from the implementation -- importing the
   module's constant would make this test agree with whatever the code says.

4. **The stub's canned answer is not asserted verbatim.** What is asserted
   is the record's shape and the free/nearest separation. The one place the
   canned response is scripted (`AXIAL_STUB_NOTE_INTERROGATE_RESPONSE`) is
   where a specific abstention or a specific collapse has to be driven.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.cli import main
from axial.envelope import compute_source_id
from axial.interrogate import ANSWERS_DIR_NAME, answers_checkpoint_path, run_interrogate
from axial.llm import PROVIDER_ENV_VAR, STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR, StubLLMClient

# specs/PRODUCT.md §7.15's own answer-field table: thirteen questions, sixteen
# fields (three questions split in two).
ANSWER_FIELDS = (
    "about",
    "claim",
    "move",
    "ranges_over",
    "stops_holding",
    "position_of",
    "arguing_against",
    "names",
    "citations",
    "mechanism",
    "evidence",
    "comparison",
    "defines",
    "uses",
    "concedes",
    "assumes",
)

NOTE_TEXTS = (
    "The Ba'ath consolidated power by building a party apparatus that recruited "
    "its cadre from the rural periphery, and staffed the ministries with it. "
    "Batatu's officer-corps data supports this reading of the coalition.",
    "Against Hudson's legitimacy-deficit account, the durable change after 1963 "
    "was organisational rather than military: land reform displaced the landed "
    "elite from administration before the coalition narrowed.",
)


def _arrange(tmp_path: Path) -> tuple[Path, Path, str]:
    """Lay down a source file plus the three artifacts §7.15's context comes
    from, and return `(source_path, data_dir, source_id)`."""
    data_dir = tmp_path / "data"
    source_path = tmp_path / "hinnebusch2001.pdf"
    source_path.write_bytes(b"%PDF-1.4 not really a pdf, only ever hashed\n")
    source_id = compute_source_id(source_path)

    chunks_dir = data_dir / "chunks"
    chunks_dir.mkdir(parents=True)
    with (chunks_dir / f"{source_id}.jsonl").open("w", encoding="utf-8") as handle:
        for index, text in enumerate(NOTE_TEXTS, start=1):
            handle.write(
                json.dumps(
                    {
                        "chunk_id": f"{source_id}_2_the-ba-athist-state_{index:03d}",
                        "section": "Chapter 3 - The Ba'athist State",
                        "section_order": "2",
                        "text": text,
                    }
                )
                + "\n"
            )

    envelopes_dir = data_dir / "envelopes"
    envelopes_dir.mkdir(parents=True)
    (envelopes_dir / f"{source_id}.json").write_text(
        json.dumps(
            {
                "thesis": "Ba'athist state formation as authoritarian modernization from above.",
                "scope": "Syria, 1963-2000",
                "stated_argument": "Party organisation, not coercion, produced durable rule.",
                "toc": [
                    {"title": "Part I - Before the Ba'ath", "children": []},
                    {
                        "title": "Part II - Building the Ba'athist State",
                        "children": ["Chapter 3 - The Ba'athist State"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    source_meta_dir = data_dir / "source_meta"
    source_meta_dir.mkdir(parents=True)
    (source_meta_dir / f"{source_id}.json").write_text(
        json.dumps(
            {
                "source_id": source_id,
                "author": "Raymond Hinnebusch",
                "title": "Syria: Revolution from Above",
                "date": "2001",
            }
        ),
        encoding="utf-8",
    )
    return source_path, data_dir, source_id


@pytest.fixture(autouse=True)
def _stub_provider(monkeypatch):
    monkeypatch.setenv(PROVIDER_ENV_VAR, "stub")


def _read_answers(data_dir: Path, source_id: str) -> list[dict]:
    path = answers_checkpoint_path(source_id, data_dir / ANSWERS_DIR_NAME)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_one_answer_record_per_note_answering_all_thirteen_questions(tmp_path, capsys):
    source_path, data_dir, source_id = _arrange(tmp_path)

    exit_code = main(["interrogate", str(source_path), "--data-dir", str(data_dir)])

    assert exit_code == 0
    records = _read_answers(data_dir, source_id)
    assert [record["chunk_id"] for record in records] == [
        f"{source_id}_2_the-ba-athist-state_001",
        f"{source_id}_2_the-ba-athist-state_002",
    ]
    for record in records:
        assert record["source_id"] == source_id
        assert record["pass"] == "note_interrogate"
        assert record["model"]
        assert record["frame_version"]
        assert record["answered_at"]
        # One draw: the record shape carries no vote/draws field (D4).
        assert "votes" not in record
        assert "draws" not in record
        assert "abstained" not in record
        answers = record["answers"]
        for field in ANSWER_FIELDS:
            assert field in answers, f"missing answer field {field!r}"

    summary = json.loads(capsys.readouterr().out)
    assert summary["notes_total"] == 2
    assert summary["answered"] == 2
    assert summary["failed"] == 0


def test_free_answer_and_nearest_example_are_separate_and_unbridged(tmp_path, monkeypatch):
    """D8: the free answer is recorded verbatim in the model's own words and
    the nearest example lands in its own marked field. Code never bridges the
    two -- a free answer that matches no example is not normalised onto one,
    and the free field is never filled from the example."""
    source_path, data_dir, source_id = _arrange(tmp_path)
    monkeypatch.setenv(
        STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                **{field: "answered from the passage" for field in ANSWER_FIELDS},
                "move": "conceding the coup in order to narrow the claim to organisation",
                "move_nearest": {"example": "role:claim", "fit": "loose"},
                "claim": "the party apparatus, not the army, produced durable rule",
                "claim_nearest": {"example": "state-formation", "fit": "close"},
            }
        ),
    )

    assert main(["interrogate", str(source_path), "--data-dir", str(data_dir)]) == 0

    answers = _read_answers(data_dir, source_id)[0]["answers"]
    assert answers["move"] == "conceding the coup in order to narrow the claim to organisation"
    assert answers["move_nearest"] == {"example": "role:claim", "fit": "loose"}
    assert answers["claim"] == "the party apparatus, not the army, produced durable rule"
    assert answers["claim_nearest"] == {"example": "state-formation", "fit": "close"}


def test_abstention_is_explicit_and_distinguishable(tmp_path, monkeypatch):
    """D7: a field the passage does not support records `not-in-passage`,
    optionally carrying a one-clause reason -- including the "cannot judge
    between X and Y" case -- and is structurally distinct from an answer."""
    source_path, data_dir, source_id = _arrange(tmp_path)
    monkeypatch.setenv(
        STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                **{field: "answered from the passage" for field in ANSWER_FIELDS},
                "assumes": "not-in-passage",
                "comparison": {
                    "not-in-passage": "cannot judge between Iraq and Egypt as the implied case"
                },
            }
        ),
    )

    assert main(["interrogate", str(source_path), "--data-dir", str(data_dir)]) == 0

    answers = _read_answers(data_dir, source_id)[0]["answers"]
    assert answers["assumes"] == "not-in-passage"
    assert answers["comparison"] == {
        "not-in-passage": "cannot judge between Iraq and Egypt as the implied case"
    }
    assert answers["claim"] == "answered from the passage"


def test_prompt_carries_the_context_and_asks_the_free_answer_first(tmp_path, monkeypatch):
    """P0-6: the assembled prompt carries its book's thesis, its author/
    title/date, its chapter and verbatim section heading, and the note text
    -- and asks each free question BEFORE presenting that question's
    examples (D8)."""
    source_path, data_dir, _ = _arrange(tmp_path)
    record_path = tmp_path / "prompts.jsonl"
    monkeypatch.setenv(PROVIDER_ENV_VAR, "record")
    monkeypatch.setenv("AXIAL_LLM_RECORD_PATH", str(record_path))

    assert main(["interrogate", str(source_path), "--data-dir", str(data_dir)]) == 0

    prompts = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == len(NOTE_TEXTS)
    prompt = prompts[0]
    assert "Ba'athist state formation as authoritarian modernization" in prompt
    assert "Syria, 1963-2000" in prompt
    assert "Raymond Hinnebusch" in prompt
    assert "Syria: Revolution from Above" in prompt
    assert "2001" in prompt
    assert "Chapter 3 - The Ba'athist State" in prompt
    assert "Part II - Building the Ba'athist State" in prompt
    assert NOTE_TEXTS[0] in prompt
    # No text from any other note of the same source leaks into this call.
    assert NOTE_TEXTS[1] not in prompt
    # D8 ordering: every free question is asked before any example list is
    # shown. `role:claim` is a role_in_argument example from the domain frame.
    assert "role:claim" in prompt
    assert prompt.index("assumes") < prompt.index("role:claim")


def test_reports_collapse_abstention_and_cost_extrapolated_to_the_corpus(
    tmp_path, monkeypatch, capsys
):
    """P0-6: the run reports the collapse-check rate, the abstention rate per
    field, and the measured token/cost figures extrapolated to the corpus."""
    source_path, data_dir, _ = _arrange(tmp_path)
    monkeypatch.setenv(
        STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                **{field: "answered from the passage" for field in ANSWER_FIELDS},
                # A free answer that IS one of the frame's own example strings:
                # the collapse the check exists to make visible.
                "move": "role:claim",
                "move_nearest": {"example": "role:claim", "fit": "close"},
                "assumes": "not-in-passage",
            }
        ),
    )

    exit_code = main(["interrogate", str(source_path), "--data-dir", str(data_dir)])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["collapse"]["frame_example_rate"]["move"] == 1.0
    assert summary["collapse"]["frame_example_rate"]["claim"] == 0.0
    assert summary["collapse"]["nearest_example_rate"]["move"] == 1.0
    assert summary["abstention_rate"]["assumes"] == 1.0
    assert summary["abstention_rate"]["claim"] == 0.0
    cost = summary["cost"]
    assert cost["total_tokens"] > 0
    assert cost["corpus_notes"] == 2
    assert "usd_per_note" in cost
    assert "usd_corpus_extrapolated" in cost


def test_limit_stops_the_run_for_the_sample_gate(tmp_path, capsys):
    """D14/P0-6: the sample gate. `--limit` stops the pass after roughly N
    notes so ~50 outputs can be read before the rest of the corpus is paid
    for, and the partial run is not mistaken for a complete one."""
    source_path, data_dir, source_id = _arrange(tmp_path)

    assert main(["interrogate", str(source_path), "--data-dir", str(data_dir), "--limit", "1"]) == 0

    assert len(_read_answers(data_dir, source_id)) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["answered"] == 1
    assert summary["limit"] == 1
    assert summary["complete"] is False


def test_an_empty_list_answer_costs_one_call_and_keeps_the_note(tmp_path, monkeypatch):
    """A list-valued field answered `[]` -- "this passage defines nothing" --
    is an answer. It used to be read as a blank, and since the re-ask carries
    no error feedback the model repeated the identical response until the
    budget was spent, then the note was discarded whole over that one field.
    Measured on a real 10-note probe: 1 note in 10 lost on the first book."""
    source_path, data_dir, source_id = _arrange(tmp_path)
    monkeypatch.setenv(
        STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR,
        json.dumps(
            {
                **{field: "answered from the passage" for field in ANSWER_FIELDS},
                "defines": [],
                "citations": [],
            }
        ),
    )
    client = StubLLMClient()

    summary = run_interrogate(source_path, client=client, data_dir=data_dir)

    assert summary["failed"] == 0
    assert summary["answered"] == len(NOTE_TEXTS)
    # One call per note: no re-ask was burned on a valid answer.
    assert client.call_count == len(NOTE_TEXTS)
    answers = _read_answers(data_dir, source_id)[0]["answers"]
    assert answers["defines"] == []
    assert answers["citations"] == []


def test_the_pass_registers_with_the_corpus_runner(tmp_path):
    """P1-4/§8: "`interrogate` registers as a pass like any other, so the
    corpus re-run resumes rather than restarting" -- `axial run interrogate`
    drives it with the same per-source failure isolation and ledger resume
    every other pass gets."""
    from axial.interrogate import InterrogateError
    from axial.run import PASS_REGISTRY

    descriptor = PASS_REGISTRY["interrogate"]
    assert descriptor.error is InterrogateError


def test_resume_never_re_interrogates_an_already_answered_note(tmp_path):
    """The durable artifact is a resume point, not a log: a second run over
    the same source makes zero model calls and leaves one record per note."""
    source_path, data_dir, source_id = _arrange(tmp_path)

    first = StubLLMClient()
    run_interrogate(source_path, client=first, data_dir=data_dir)
    assert first.call_count == len(NOTE_TEXTS)

    second = StubLLMClient()
    run_interrogate(source_path, client=second, data_dir=data_dir)
    assert second.call_count == 0
    assert len(_read_answers(data_dir, source_id)) == len(NOTE_TEXTS)
