"""Acceptance tests for issue #697: the `position` backfill pass.

91% of the corpus (6,148 of 6,733 notes) was interrogated under frame 0.1
and never asked question 7 (`position`), so `query/reader.py`'s
`stated_position()` falls back to `position_of` -- a holder name, not a
stance sentence. `axial.position_backfill.run_position_backfill` closes
that gap: one question, over the notes that lack the key, keeping the
frame's `theory_school` examples and showing the note its own recorded
`position_of` (issue #697's two non-optional rules).

Covered here:

  - the composed prompt asks exactly one question, keeps the `position`
    examples block, and includes the note's own recorded `position_of`;
  - only notes lacking `position` are selected -- a note that already
    carries it (frame 0.2) is never re-asked and its record is untouched;
  - resume: a second run over an already-backfilled source makes zero
    calls and changes nothing on disk;
  - the patched record carries `position` (and `position_nearest`, when the
    model supplied one) while every other field -- including `position_of`
    -- is preserved unchanged;
  - the CLI is wired end to end (`axial position-backfill`), including the
    `axial run position-backfill --worklist` corpus-runner registration.

Zero real model calls anywhere: every test drives `run_position_backfill`
with a fake in-process client, or the CLI/`axial run` path with the stub
provider (`AXIAL_LLM_PROVIDER=stub`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from axial.cli import main
from axial.envelope import compute_source_id
from axial.interrogate import answers_checkpoint_path
from axial.llm import PROVIDER_ENV_VAR
from axial.position_backfill import (
    compose_position_backfill_prompt,
    run_position_backfill,
)
from axial.run import PASS_REGISTRY


class FakeClient:
    """Records every prompt, replies with a scripted position answer for
    each call in order (last entry repeats if more calls arrive than
    scripted)."""

    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.pass_names: list[str | None] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.prompts.append(prompt)
        self.pass_names.append(pass_name)
        index = min(len(self.prompts) - 1, len(self._responses) - 1)
        return json.dumps(self._responses[index])

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "fake-model"

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _full_answers(**overrides: Any) -> dict[str, Any]:
    answers = {
        "about": ["state formation"],
        "claim": "The party apparatus, not the army, produced durable rule.",
        "move": "conceding a point in order to narrow it",
        "ranges_over": "Syria, 1963-1970",
        "stops_holding": "not-in-passage",
        "position_of": "the author's own",
        "arguing_against": ["Hudson's legitimacy-deficit account"],
        "names": [{"name": "Ba'ath Party", "kind": "institution/group"}],
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }
    answers.update(overrides)
    return answers


def _record(chunk_id: str, source_id: str, **answer_overrides: Any) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": "Chapter 3 - The Ba'athist State",
        "pass": "note_interrogate",
        "model": "z-ai/glm-5.2",
        "frame_version": "0.1",
        "answered_at": "2026-07-27T09:14:02Z",
        "answers": _full_answers(**answer_overrides),
    }


def _arrange(tmp_path: Path, note_count: int) -> tuple[Path, Path, str, list[str]]:
    """Lay down a source file plus the chunk/envelope/source_meta artifacts
    `run_position_backfill` reads context from, with `note_count` notes.
    Returns `(source_path, data_dir, source_id, chunk_ids)`."""
    data_dir = tmp_path / "data"
    source_path = tmp_path / "hinnebusch2001.pdf"
    source_path.write_bytes(b"%PDF-1.4 not really a pdf, only ever hashed\n")
    source_id = compute_source_id(source_path)
    chunk_ids = [
        f"{source_id}_2_the-ba-athist-state_{index:03d}" for index in range(1, note_count + 1)
    ]

    _write_jsonl(
        data_dir / "chunks" / f"{source_id}.jsonl",
        [
            {
                "chunk_id": chunk_id,
                "section": "Chapter 3 - The Ba'athist State",
                "section_order": "2",
                "text": (
                    f"Passage {chunk_id}: the party apparatus, not the army, "
                    "produced durable rule in Syria."
                ),
            }
            for chunk_id in chunk_ids
        ],
    )
    _write_json(
        data_dir / "envelopes" / f"{source_id}.json",
        {
            "thesis": "Ba'athist state formation as authoritarian modernization from above.",
            "scope": "Syria, 1963-2000",
            "stated_argument": "Party organisation, not coercion, produced durable rule.",
            "toc": [
                {
                    "title": "Part II - Building the Ba'athist State",
                    "children": ["Chapter 3 - The Ba'athist State"],
                }
            ],
        },
    )
    _write_json(
        data_dir / "source_meta" / f"{source_id}.json",
        {
            "source_id": source_id,
            "author": "Raymond Hinnebusch",
            "title": "Syria: Revolution from Above",
            "date": "2001",
        },
    )
    return source_path, data_dir, source_id, chunk_ids


def _read_answers(data_dir: Path, source_id: str) -> list[dict[str, Any]]:
    path = answers_checkpoint_path(source_id, data_dir / "answers")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# The composed prompt
# ---------------------------------------------------------------------------


def test_prompt_asks_one_question_keeps_examples_and_shows_recorded_position_of():
    chunk_record = {
        "section": "Chapter 3 - The Ba'athist State",
        "text": "The party apparatus, not the army, produced durable rule.",
    }
    source_meta = {
        "author": "Raymond Hinnebusch",
        "title": "Syria: Revolution from Above",
        "date": "2001",
    }
    envelope = {
        "thesis": "Ba'athist state formation as authoritarian modernization from above.",
        "scope": "Syria, 1963-2000",
        "stated_argument": "Party organisation, not coercion, produced durable rule.",
        "toc": [],
    }
    examples = {"position": [("institutionalist-state-centered", "the state built itself")]}

    prompt = compose_position_backfill_prompt(
        chunk_record, source_meta, envelope, "the author's own", examples
    )

    # Exactly one question is asked -- none of the OTHER sixteen questions'
    # own wording leaks in.
    assert "position -- " in prompt
    assert "arguing_against --" not in prompt
    assert "mechanism --" not in prompt
    assert "stops_holding --" not in prompt

    # The examples block stays (issue #697 rule 1).
    assert "institutionalist-state-centered" in prompt
    assert "EXAMPLES" in prompt

    # The note's own recorded `position_of` is shown back to it (rule 2).
    assert "the author's own" in prompt

    # The passage and book context are both present.
    assert "The party apparatus, not the army" in prompt
    assert "Raymond Hinnebusch" in prompt
    assert "Syria, 1963-2000" in prompt


def test_prompt_omits_examples_block_when_frame_declares_none():
    chunk_record = {"section": "Intro", "text": "Some passage."}
    prompt = compose_position_backfill_prompt(chunk_record, {}, {}, "not-in-passage", examples={})
    assert "EXAMPLES --" not in prompt
    # No examples means no `_nearest` key is asked for.
    assert "carrying exactly these keys: position." in prompt
    assert "position_nearest" not in prompt


# ---------------------------------------------------------------------------
# Selection: only notes lacking `position` are asked
# ---------------------------------------------------------------------------


def test_selects_only_notes_lacking_position_leaves_the_others_untouched(tmp_path):
    source_path, data_dir, source_id, (chunk_id_missing, chunk_id_has_it) = _arrange(tmp_path, 2)

    already_good = _record(chunk_id_has_it, source_id, position="the pre-existing stance")
    # `_record`'s default answers carry no `position` key at all -- the
    # frame-0.1 shape every one of the 6,148 corpus notes has on disk.
    missing = _record(chunk_id_missing, source_id)
    assert "position" not in missing["answers"]

    _write_jsonl(data_dir / "answers" / f"{source_id}.jsonl", [missing, already_good])

    client = FakeClient([{"position": "durable rule was built by the party, not the army"}])

    summary = run_position_backfill(source_path, client=client, data_dir=data_dir)

    assert summary["missing_position"] == 1
    assert summary["backfilled"] == 1
    assert len(client.prompts) == 1  # the already-answered note was never asked

    records = {r["chunk_id"]: r for r in _read_answers(data_dir, source_id)}
    assert records[chunk_id_missing]["answers"]["position"] == (
        "durable rule was built by the party, not the army"
    )
    # The 585-notes-shaped record is byte-for-byte untouched.
    assert records[chunk_id_has_it] == already_good


# ---------------------------------------------------------------------------
# Resume: a second run makes zero calls and changes nothing
# ---------------------------------------------------------------------------


def test_resume_skips_already_backfilled_notes(tmp_path):
    source_path, data_dir, source_id, (chunk_id,) = _arrange(tmp_path, 1)
    missing = _record(chunk_id, source_id)
    _write_jsonl(data_dir / "answers" / f"{source_id}.jsonl", [missing])

    first_client = FakeClient(
        [{"position": "durable rule", "position_nearest": {"example": "x", "fit": "loose"}}]
    )
    first_summary = run_position_backfill(source_path, client=first_client, data_dir=data_dir)
    assert first_summary["backfilled"] == 1
    assert len(first_client.prompts) == 1

    on_disk_after_first = _read_answers(data_dir, source_id)

    second_client = FakeClient([{"position": "SHOULD NEVER BE WRITTEN"}])
    second_summary = run_position_backfill(source_path, client=second_client, data_dir=data_dir)

    assert second_summary["missing_position"] == 0
    assert second_summary["backfilled"] == 0
    assert len(second_client.prompts) == 0  # zero model calls on resume

    assert _read_answers(data_dir, source_id) == on_disk_after_first


# ---------------------------------------------------------------------------
# The record patch: position + position_nearest, everything else preserved
# ---------------------------------------------------------------------------


def test_writes_position_and_position_nearest_preserving_every_other_field(tmp_path):
    source_path, data_dir, source_id, (chunk_id,) = _arrange(tmp_path, 1)
    missing = _record(chunk_id, source_id)
    _write_jsonl(data_dir / "answers" / f"{source_id}.jsonl", [missing])

    client = FakeClient(
        [
            {
                "position": "durable authoritarian rule was built by a party, not an army",
                "position_nearest": {"example": "institutionalist-state-centered", "fit": "close"},
            }
        ]
    )
    run_position_backfill(source_path, client=client, data_dir=data_dir)

    record = _read_answers(data_dir, source_id)[0]
    assert record["answers"]["position"] == (
        "durable authoritarian rule was built by a party, not an army"
    )
    assert record["answers"]["position_nearest"] == {
        "example": "institutionalist-state-centered",
        "fit": "close",
    }
    # Every field the original interrogation call wrote is unchanged.
    for field, value in missing["answers"].items():
        assert record["answers"][field] == value
    # Record-level provenance of the ORIGINAL call is preserved, not
    # overwritten by this patch.
    assert record["model"] == "z-ai/glm-5.2"
    assert record["frame_version"] == "0.1"
    assert record["answered_at"] == "2026-07-27T09:14:02Z"


# ---------------------------------------------------------------------------
# CLI wiring: `axial position-backfill` and the `axial run` registration
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_provider(monkeypatch):
    monkeypatch.setenv(PROVIDER_ENV_VAR, "stub")


def test_cli_position_backfill_patches_the_record(tmp_path):
    source_path, data_dir, source_id, (chunk_id,) = _arrange(tmp_path, 1)
    missing = _record(chunk_id, source_id)
    _write_jsonl(data_dir / "answers" / f"{source_id}.jsonl", [missing])

    exit_code = main(["position-backfill", str(source_path), "--data-dir", str(data_dir)])

    assert exit_code == 0
    record = _read_answers(data_dir, source_id)[0]
    assert "position" in record["answers"]
    # `position_of` -- and every other pre-existing field -- rides unchanged.
    assert record["answers"]["position_of"] == missing["answers"]["position_of"]


def test_registered_with_run_pass_for_the_corpus_wide_runner():
    """`axial run position-backfill --worklist/--corpus` (the real backfill's
    own command, issue #697) resolves through the same registry every other
    pass does."""
    assert "position-backfill" in PASS_REGISTRY
    descriptor = PASS_REGISTRY["position-backfill"]
    assert descriptor.name == "position-backfill"
