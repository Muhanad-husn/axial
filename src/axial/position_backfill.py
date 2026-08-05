"""The `position` backfill pass (issue #697): a one-question re-ask over the
6,148 notes interrogated under frame 0.1, which were never asked question 7
(`position` -- "what IS that position?", split from `position_of` -- "whose
position is this?" -- by frame 0.2, issue #496).

**Why this exists.** `query/reader.py`'s `stated_position()` reads `position`
when the key is present and falls back to `position_of` otherwise -- by
design (issue #496), since the corpus is a permanent mixed frame. But the
fallback is not a missing value, it is a silently WRONG one: `position_of`
answers "whose", not "what", so 91% of the corpus hands every consumer that
asks for the position a **holder name** ("the author's own", "Hinnebusch")
where it expects a **stance sentence**. This pass closes that gap without a
full re-interrogation: one question, over the notes that lack the key.

**Reuses `axial.interrogate` rather than duplicating it.** The book-level
context (author/title/date, thesis/scope/stated argument, chapter/section),
the frame-as-examples mechanism (D8), the abstention rule (D7), and the
directory-resolution/checkpoint-loading plumbing are IDENTICAL to the full
interrogation pass -- this module imports them rather than re-deriving them,
so `interrogate.py` itself needs no edit and carries no per-field mode
bolted onto its own prompt composer. Only the prompt (one question, not
sixteen) and the parser (one field, not seventeen) are new.

**Two rules the issue marks as not optional:**

1. **The examples block stays.** The 585 already-answered notes were asked
   with the frame's `theory_school` examples (`NEAREST_EXAMPLE_AXES["position"]
   == "theory_school"`); dropping them here would mix two different framings
   of the same field inside the field this backfill exists to unmix.
2. **The note's own recorded `position_of` is shown to the model.** The 585
   good notes answered "whose" and "what" in the same call, so the two are
   consistent by construction; a blind position-only re-ask has no such
   guarantee and could name a stance belonging to a different holder than
   the record already carries.

**Patches records in place; never appends a second one.** Every reader of
`data/answers/<source_id>.jsonl` (`axial.names.load_answer_records`,
`axial.gather`, `axial.argmap.build.select_passages`, ...) assumes exactly
one record per `chunk_id` and does not deduplicate -- a second `answers`
record for an already-answered chunk_id would be double-counted by every one
of them. So this pass loads the existing per-source checkpoint, merges
`position`/`position_nearest` into the matching record's own `answers` dict
in memory, and rewrites the whole (small, one-source) file atomically
(`axial.paths.atomic_write_text`) after each note completes -- a reader can
only ever see the fully-old or the fully-new file, never a torn one, which
is a stronger guarantee than the append-only convention's own "a torn tail
can only be the last line" tolerance.

**Resumable by construction, with no separate journal.** The selection
predicate -- "this note has an `answers` record and no `position` key" --
IS the resume predicate: a note this pass has already patched carries the
key and is never selected again, on this run or the next one. A kill
mid-source loses no more than the one in-flight call, since every completed
note's patch is written to disk before the next one starts (interrogate's
own single-collecting-thread discipline, `run_interrogate`'s docstring).
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from axial.chunk import (
    ChunkError,
    MissingSourceError as _ChunkMissingSourceError,
    _default_chunks_dir,
    read_chunks,
)
from axial.codebook import CodebookError, load_codebook
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    _default_envelopes_dir,
    compute_source_id,
    envelope_path,
)
from axial.intake import SOURCE_META_DIR, source_meta_path
from axial.interrogate import (
    NOT_IN_PASSAGE,
    InterrogateError,
    LLMFailedError,
    MissingContextError,
    SchemaLoadFailedError,
    CodebookLoadFailedError,
    ChunkingFailedError,
    _EXAMPLES_SECTION_TEMPLATE,
    _default_answers_dir,
    _default_domain_dir,
    _format_context_value,
    _is_blank,
    _read_json,
    abstention_rates,
    answers_checkpoint_path,
    chapter_for_section,
    corpus_note_count,
    cost_report,
    frame_examples,
    load_answer_checkpoint,
)
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    NOTE_INTERROGATE_PASS_NAME,
    ContentRefusedError,
    LLMClient,
    LLMError,
    get_client,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.paths import atomic_write_text
from axial.schema import SchemaError, load_schema

# The label recorded in run-log rows and the JSON summary's own `pass`
# field. Model/reasoning selection still goes through
# `NOTE_INTERROGATE_PASS_NAME` (this call reuses interrogate's config,
# stub wiring and cost accounting -- it is the same kind of call, only
# narrower) -- this string exists purely so a run-log reader can tell a
# backfill row from a full-interrogation row at a glance.
POSITION_BACKFILL_PASS_NAME = "position_backfill"

# Mirrors `axial.interrogate.DEFAULT_WORKERS` (issue #623's own measurement):
# the backfill call is smaller (one question, not sixteen) but otherwise the
# same shape of call against the same model, so the same starting
# concurrency applies until a real run measures otherwise.
DEFAULT_WORKERS = 12


class PositionAnswerParseError(InterrogateError):
    """Raised when a position-backfill response is valid JSON but not a
    usable answer -- missing the `position` key, or a blank value where an
    answer or the explicit abstention was required. Re-askable inside
    `complete_json`'s own bounded budget, exactly like a full interrogation
    call's `AnswerParseError`."""


_POSITION_QUESTION = (
    "What IS that position, in the passage's own terms? One sentence "
    "stating the stance itself, in your own words. Answer this even when "
    'the holder is the author -- "the author\'s own" answers a different '
    "question (whose position this is, already on record below) and is "
    "never an answer to this one."
)

_BACKFILL_PROMPT_TEMPLATE = """\
You are reading ONE passage from an academic book. This passage was already \
interrogated and its other answers are on record; one question was never \
asked, and this call asks it alone.

Answer ONLY from the passage and the book-level context supplied below. Do \
not use anything you may know about this book, this author, or this subject \
from anywhere else, and do not look anything up. If the passage does not \
support an answer, say so explicitly rather than reaching for a plausible \
one.

BOOK
Author: {author}
Title: {title}
Date: {date}
The author's stated thesis: {thesis}
The book's scope: {scope}
The book's stated argument: {stated_argument}
Chapter: {chapter}
Section (the author's own heading, verbatim): {section}

PASSAGE
{note_text}

This note's own already-recorded answer to "whose position is this" (a \
separate question, not asked again here): {position_of}

QUESTION -- answer this in your own words, before reading the EXAMPLES \
section further below.

position -- {question}

ABSTENTION. The answer must come from the passage. Where the passage does \
not support one, answer with the string "{not_in_passage}", or with \
{{"{not_in_passage}": "<one short clause saying why>"}} when there is \
something worth saying -- including the case where the passage bears on the \
question but does not settle it ("cannot judge between X and Y"). An \
abstention is an ordinary, expected answer. A guessed answer is worse than \
an abstention, because a reader cannot tell it from one you actually read.

{examples_section}
RESPONSE. Reply with ONLY a JSON object (no prose, no markdown fences) \
carrying exactly these keys: {answer_fields}.{ordering_note}
"""

_ORDERING_NOTE = (
    ' Write "position" BEFORE "position_nearest", and never let an example '
    "decide the free answer: the free answer is what you read in the "
    "passage, the nearest example is a separate, secondary note about "
    "which of someone else's categories it happens to sit closest to."
)


def compose_position_backfill_prompt(
    chunk_record: dict[str, Any],
    source_meta: dict[str, Any],
    envelope: dict[str, Any],
    position_of: Any,
    examples: dict[str, list[tuple[str, str]]],
) -> str:
    """Compose the position-only backfill prompt: the same book-level
    context and abstention rule §7.15 uses, this one question (not the other
    sixteen), the note's own recorded `position_of` shown back to it, and --
    when the frame declares one -- the `position` examples block (D8), never
    dropped for this pass (issue #697's own rule 1)."""
    pairs = examples.get("position", [])
    blocks = []
    if pairs:
        rendered = "\n".join(
            f"- {example_id}: {definition}" if definition else f"- {example_id}"
            for example_id, definition in pairs
        )
        blocks.append(f"Examples for 'position' (add position_nearest):\n{rendered}")
    examples_section = (
        _EXAMPLES_SECTION_TEMPLATE.format(blocks="\n\n".join(blocks)) if blocks else ""
    )
    answer_keys = ["position"] + (["position_nearest"] if pairs else [])
    return _BACKFILL_PROMPT_TEMPLATE.format(
        author=_format_context_value(source_meta.get("author")),
        title=_format_context_value(source_meta.get("title")),
        date=_format_context_value(source_meta.get("date")),
        thesis=_format_context_value(envelope.get("thesis")),
        scope=_format_context_value(envelope.get("scope")),
        stated_argument=_format_context_value(envelope.get("stated_argument")),
        chapter=_format_context_value(
            chapter_for_section(envelope.get("toc"), chunk_record.get("section"))
        ),
        section=_format_context_value(chunk_record.get("section")),
        note_text=chunk_record["text"],
        position_of=_format_context_value(position_of),
        question=_POSITION_QUESTION,
        not_in_passage=NOT_IN_PASSAGE,
        examples_section=examples_section,
        answer_fields=", ".join(answer_keys),
        ordering_note=_ORDERING_NOTE if pairs else "",
    )


def parse_position_backfill_response(
    raw: str, examples: dict[str, list[tuple[str, str]]]
) -> dict[str, Any]:
    """Parse one raw response into `{"position": ..., "position_nearest":
    ...}` (the second key only when the frame declares `position` examples
    and the model supplied one). Nothing here is checked against the frame
    (D9, mirrors `axial.interrogate.parse_answer_response`): the only
    rejections are shape ones, and they are re-askable."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise PositionAnswerParseError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PositionAnswerParseError(
            f"expected a top-level JSON object, got {type(data).__name__}"
        )
    if "position" not in data:
        raise PositionAnswerParseError("answer field 'position' is missing from the response")
    value = data["position"]
    if _is_blank(value, "position"):
        raise PositionAnswerParseError(
            f"answer field 'position' is empty: an answer or the explicit "
            f"{NOT_IN_PASSAGE!r} abstention is required, never a blank"
        )
    patch: dict[str, Any] = {"position": value}
    if "position" in examples and "position_nearest" in data:
        patch["position_nearest"] = data["position_nearest"]
    return patch


def _rewrite_answers_file(path: Path, records: list[dict[str, Any]]) -> None:
    """Rewrite `path` to hold exactly `records`, atomically
    (`axial.paths.atomic_write_text`, issue #705): a reader opening `path`
    mid-write always sees either the fully-old or the fully-new file, never
    a partial one -- stronger than the append-only convention's own "a torn
    tail is at most the last line" tolerance, which does not apply once a
    file is rewritten rather than appended to. `atomic_write_text` also
    retries the final rename past a transient Windows `PermissionError`
    (#653) -- issue #705's own bug -- rather than aborting a whole run on
    the first antivirus/indexer handle."""
    atomic_write_text(path, "".join(json.dumps(record) + "\n" for record in records))


def notes_missing_position(records: list[dict[str, Any]]) -> list[int]:
    """The indices, into `records`, of every answer record that lacks a
    `position` key -- the selection AND resume predicate in one (module
    docstring): a note this pass has already patched is excluded exactly
    the same way a note interrogated under frame 0.2 already was."""
    return [
        index
        for index, record in enumerate(records)
        if "answers" in record and "position" not in record["answers"]
    ]


def run_position_backfill(
    source_path: str | Path,
    *,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    data_dir: Path | None = None,
    domain_dir: str | Path | None = None,
    limit: int | None = None,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Backfill `position` onto every note of `source_path` that lacks it,
    patching `<answers_dir>/<source_id>.jsonl` in place (module docstring).
    Mirrors `axial.interrogate.run_interrogate`'s shape and concurrency
    discipline: bounded worker threads make the calls, the single collecting
    thread applies every result and rewrites the file, so a mid-run kill can
    never race two threads onto the same write.

    `limit`, when given, stops after that many notes are backfilled THIS
    run -- the same smoke-arm affordance `run_interrogate`'s own `limit`
    gives, for trying the prompt against a handful of notes before paying
    for the rest of the corpus.
    """
    if domain_dir is None:
        domain_dir = _default_domain_dir(config_path)

    try:
        schema = load_schema(domain_dir)
    except SchemaError as exc:
        raise SchemaLoadFailedError(exc) from exc
    try:
        codebook = load_codebook(domain_dir)
    except CodebookError as exc:
        raise CodebookLoadFailedError(exc) from exc
    examples = frame_examples(schema, codebook)

    try:
        source_id = compute_source_id(Path(source_path))
    except _EnvelopeMissingSourceError as exc:
        raise ChunkingFailedError(_ChunkMissingSourceError(exc)) from exc

    chunks_dir = data_dir / "chunks" if data_dir is not None else _default_chunks_dir(config_path)
    envelopes_dir = (
        data_dir / "envelopes" if data_dir is not None else _default_envelopes_dir(config_path)
    )
    source_meta_dir = data_dir / "source_meta" if data_dir is not None else SOURCE_META_DIR
    answers_dir = (
        data_dir / "answers" if data_dir is not None else _default_answers_dir(config_path)
    )

    try:
        chunk_records = read_chunks(source_id, chunks_dir=chunks_dir, config_path=config_path)
    except ChunkError as exc:
        raise ChunkingFailedError(exc) from exc
    chunk_by_id = {record["chunk_id"]: record for record in chunk_records}

    envelope = _read_json(
        envelope_path(source_id, envelopes_dir), "envelope", f"axial envelope {source_path}"
    )
    source_meta = _read_json(
        source_meta_path(source_id, source_meta_dir),
        "source-metadata record",
        f"axial ingest {source_path}",
    )

    checkpoint_path = answers_checkpoint_path(source_id, answers_dir)
    records = load_answer_checkpoint(checkpoint_path)

    candidates = notes_missing_position(records)
    missing_position = len(candidates)
    pending = candidates if limit is None else candidates[:limit]

    backfilled = 0
    failed = 0
    model: str | None = None

    if pending:
        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc
        model = client.model_for_pass(NOTE_INTERROGATE_PASS_NAME)

        def _backfill_one(index: int) -> tuple[int, Any, float]:
            record = records[index]
            chunk_id = record["chunk_id"]
            chunk_record = chunk_by_id.get(chunk_id)
            if chunk_record is None:
                return (
                    index,
                    MissingContextError(
                        Path(chunk_id), "chunk record", f"axial chunk {source_path}"
                    ),
                    0.0,
                )
            position_of = record["answers"].get("position_of")
            prompt = compose_position_backfill_prompt(
                chunk_record, source_meta, envelope, position_of, examples
            )
            started = time.monotonic()
            try:
                raw = complete_json(
                    client,
                    prompt,
                    pass_name=NOTE_INTERROGATE_PASS_NAME,
                    validate=lambda response: parse_position_backfill_response(response, examples),
                )
                return (
                    index,
                    parse_position_backfill_response(raw, examples),
                    time.monotonic() - started,
                )
            except (ContentRefusedError, ModelJsonError, PositionAnswerParseError) as exc:
                return index, exc, time.monotonic() - started

        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            futures = [pool.submit(_backfill_one, index) for index in pending]
            settled = 0
            for future in as_completed(futures):
                try:
                    index, outcome, elapsed = future.result()
                except (LLMError, httpx.HTTPError) as exc:
                    raise LLMFailedError(exc) from exc

                chunk_id = records[index]["chunk_id"]
                settled += 1
                if isinstance(outcome, Exception):
                    print(
                        f"position_backfill: {chunk_id} failed "
                        f"({settled}/{len(pending)}): {outcome}",
                        file=sys.stderr,
                    )
                    failed += 1
                    continue

                records[index]["answers"] = {**records[index]["answers"], **outcome}
                _rewrite_answers_file(checkpoint_path, records)
                backfilled += 1
                print(
                    f"position_backfill: {chunk_id} backfilled "
                    f"({settled}/{len(pending)}) in {elapsed:.1f}s",
                    file=sys.stderr,
                )

    return {
        "source_id": source_id,
        "pass": POSITION_BACKFILL_PASS_NAME,
        "model": model,
        "answers_path": str(checkpoint_path),
        "notes_answered": sum(1 for record in records if "answers" in record),
        "missing_position": missing_position,
        "backfilled": backfilled,
        "failed": failed,
        "limit": limit,
        "complete": limit is None or (backfilled + failed) == len(pending),
        "abstention_rate": abstention_rates(records),
        "cost": cost_report(
            client.usage_for_pass(NOTE_INTERROGATE_PASS_NAME) if client is not None else None,
            model or "",
            backfilled,
            corpus_note_count(chunks_dir),
        ),
    }
