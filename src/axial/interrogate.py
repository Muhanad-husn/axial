"""The interrogation pass (PRD §5 stage 6, §7.15, P0-6; Phase A v1 D6/D7/D8/
D14, issue #419): one open-question LLM call per note.

This is what replaces tagging. Where the tag pass asked "which of these 22
claim types is it", this pass asks what the passage claims, whose position it
is, who it argues against, who it cites and what it names -- in the model's
own words -- and records the answers. Notes meet each other at the names
those answers share (§7.16/§7.17), which is the edge mechanism v0 never had.

What it reads, and never recomputes (§7.15's context list, exactly):

  - the note itself, from the on-disk chunk artifact (`axial.chunk.
    read_chunks`, §7.7) -- boundaries are computed once, by `axial chunk`,
    and this pass never re-derives them;
  - its source's author/title/date, from the persisted source-metadata
    record (§7.12/§7.13). These are NOT envelope fields;
  - its source's thesis/scope/stated argument, from the envelope (§7.3), plus
    the chapter its section sits under, from the envelope's reconstructed
    `toc`;
  - its own verbatim section heading, from the chunk record;
  - the domain frame (§7.1) as EXAMPLES of the kind of answer wanted -- never
    a menu, never validated against.

Three rules carry the design, and each is load-bearing:

**D7 -- abstention is explicit.** Every field is in exactly one of three
states: an answer; the explicit abstention `not-in-passage` (optionally
`{"not-in-passage": "<one-clause reason>"}`, which is where "cannot judge
between X and Y" is said); or absent, meaning the call failed for that note
and a failure record says so. A guessed answer is worse than an abstention,
because nothing downstream can tell it from a read one.

**D8 -- examples must not capture the answer.** The prompt asks every free
question first, in full, and only then shows the frame's examples for the few
questions that have them. The record carries `<field>` (free text) and a
separate `<field>_nearest` = `{example, fit}`. Code in this module never
bridges the two: it does not normalise a free answer onto an example, does
not fill one from the other, and does not validate either against anything.
`collapse_rates` measures whether the model collapsed them anyway, and
reports the number without asserting a threshold -- none has been measured.

**D4 -- one draw.** No `votes_by_pass` entry, no voting layer, no vote or
draws field on the record.

Output is one durable JSONL per source (`data/answers/<source_id>.jsonl`),
mirroring the tag pass's per-source checkpoint convention (`append_answer_
checkpoint` / `load_answer_checkpoint` / torn-tail healing) so a later stage
reads a durable artifact and an interrupted run resumes instead of
restarting. Three record kinds share that file, each keyed by `chunk_id`: an
answer record, a failure record (`failure_reason`), and a garble-backstop
skip record (`skip_reason`). At the end of a complete run, answered + failed
+ skipped must equal the chunk artifact's own count for that source, or the
pass raises rather than returning a silently short result.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from axial.chunk import (
    ChunkError,
    MissingSourceError as _ChunkMissingSourceError,
    _default_chunks_dir,
    read_chunks,
)
from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.codebook import Codebook, CodebookError, load_codebook
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    _default_envelopes_dir,
    compute_source_id,
    envelope_path,
)
from axial.intake import SOURCE_META_DIR, source_meta_path
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    NOTE_INTERROGATE_PASS_NAME,
    ContentRefusedError,
    LLMClient,
    LLMError,
    estimate_cost,
    get_client,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.nonprose_guard import garble_only_skip_reason
from axial.paths import _read_configured_dir
from axial.schema import Schema, SchemaError, load_schema

DEFAULT_DOMAIN_DIR = Path("config/domains/syria")

# Where the answer records live (§6, §7.15). `ANSWERS_DIR_NAME` is the leaf
# `--data-dir` rebases: a probe pointed at another checkout's `data/` finds
# `chunks/`, `envelopes/`, `source_meta/` and `answers/` under the one parent.
ANSWERS_DIR_NAME = "answers"
ANSWERS_DIR = Path("data") / ANSWERS_DIR_NAME

# The thirteen D6 questions land as sixteen fields: three questions each
# produce two (what the claim ranges over / where it stops holding; whose
# position / who it argues against; what is defined / what is merely used).
# Order is the order the prompt asks them in and the order they are written.
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

# The fields the prompt asks for as JSON lists. `[]` is an ordinary answer on
# these ("the passage names none of that kind of thing"), distinct from the
# abstention ("the passage does not let me judge") -- see `_is_blank`.
LIST_VALUED_FIELDS = frozenset(
    {"about", "arguing_against", "names", "citations", "defines", "uses"}
)

# The four D8 questions that have a closed-vocabulary ancestor in the frame,
# mapped to the frame axis whose values are shown as EXAMPLES for them (D8:
# "claim, argument role, scope, theory-adjacent framing"), plus `about`, whose
# nearest example is the frame's field axis (Appendix H). An axis the loaded
# frame does not declare is simply not shown -- a minimal domain gets fewer
# example blocks, never an error.
NEAREST_EXAMPLE_AXES = {
    "about": "field",
    "claim": "claim_type",
    "move": "role_in_argument",
    "ranges_over": "empirical_scope",
    "position_of": "theory_school",
}

# The explicit abstention value (D7, §7.15). A field abstains when its value
# is this bare string, or an object `{"not-in-passage": "<one-clause
# reason>"}` -- structurally distinct from every real answer, which is a
# string, a list, or an object with other keys.
NOT_IN_PASSAGE = "not-in-passage"

_WHITESPACE = re.compile(r"\s+")


class InterrogateError(Exception):
    """Base class for every error this pass raises."""


class SchemaLoadFailedError(InterrogateError):
    """Raised when the domain frame's schema fails to load."""

    def __init__(self, cause: SchemaError):
        self.cause = cause
        super().__init__(str(cause))


class CodebookLoadFailedError(InterrogateError):
    """Raised when the domain frame's codebook fails to load."""

    def __init__(self, cause: CodebookError):
        self.cause = cause
        super().__init__(str(cause))


class ChunkingFailedError(InterrogateError):
    """Raised when reading the on-disk chunk artifact fails -- e.g. no source
    file, or no chunk artifact yet (`axial.chunk.MissingChunkArtifactError`,
    telling the operator to run `axial chunk` first). This pass never
    (re)computes chunk boundaries, so any `ChunkError` surfaces here."""

    def __init__(self, cause: ChunkError):
        self.cause = cause
        super().__init__(str(cause))


class MissingContextError(InterrogateError):
    """Raised when the envelope or the source-metadata record this note's
    context comes from is absent (§7.15: the context list is exactly those
    artifacts, so interrogating without one would silently drop the book-level
    grounding every answer depends on)."""

    def __init__(self, path: Path, what: str, remedy: str):
        self.path = path
        super().__init__(f"missing {what} at {path}; run `{remedy}` for this source first")


class LLMFailedError(InterrogateError):
    """Raised when the LLM client -- selection/config or a transport-level
    failure -- fails, so the CLI renders a clean `error: ...`."""

    def __init__(self, cause: LLMError | httpx.HTTPError):
        self.cause = cause
        super().__init__(str(cause))


class AnswerParseError(InterrogateError):
    """Raised when a response is valid JSON but not a usable answer record --
    a missing question field, or a blank/empty value where an answer or an
    explicit abstention was required. Re-askable inside `complete_json`'s
    bounded budget; a note whose response is still malformed after it lands
    as a failure record, never as a partial answer."""


class AnswerCheckpointCorruptError(InterrogateError):
    """Raised by `load_answer_checkpoint` when a NON-final line of an answer
    artifact is not valid JSON. A torn FINAL line is tolerated (a hard kill
    can only tear the line in flight, always the last one) and simply
    re-interrogated on the resume run; a torn line anywhere else is genuine
    corruption and is loud, naming the path and the 1-indexed line."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt answer artifact {path}: line {line_no} is not valid JSON: {cause}"
        )


class AllNotesFailedError(InterrogateError):
    """Raised when a source's answer artifact holds failures and no answers
    at all (§7.15): a source that answered nothing must fail loudly, never
    report an empty success. Read off the artifact rather than off this run's
    own counters, so a rerun after a total failure -- which re-sends no note
    and so fails nothing itself -- raises exactly the same way instead of
    marking the source done with zero answers on disk."""

    def __init__(self, source_id: str, failed: int):
        self.source_id = source_id
        self.failed = failed
        super().__init__(
            f"{source_id!r} has {failed} failed note(s) and no answers at all; "
            "fix the cause and delete the failure records to retry them"
        )


class AnswerRecordCountMismatchError(InterrogateError):
    """Raised when answered + failed + skipped does not equal the chunk
    artifact's own note count for the source (§7.15's reconciliation)."""

    def __init__(self, source_id: str, expected: int, accounted_for: int):
        self.source_id = source_id
        self.expected = expected
        self.accounted_for = accounted_for
        super().__init__(
            f"interrogation of {source_id!r} accounted for {accounted_for} of its "
            f"{expected} note(s) -- {expected - accounted_for} note(s) went missing "
            "without an answer, failure, or skip record"
        )


# ---------------------------------------------------------------------------
# The durable artifact (§7.15), mirroring the tag pass's checkpoint convention
# ---------------------------------------------------------------------------


def answers_checkpoint_path(source_id: str, answers_dir: Path = ANSWERS_DIR) -> Path:
    """Where `source_id`'s answer records live: one JSON record per line,
    appended as each note is interrogated, keyed by the content-hashed
    source_id so an edited file never reuses a stale answer set."""
    return answers_dir / f"{source_id}.jsonl"


def append_answer_checkpoint(path: Path, record: dict[str, Any]) -> None:
    """Append one record AS IT IS PRODUCED: heal any torn tail left by an
    earlier hard kill, then write+flush the JSON line, so a mid-run failure
    leaves every already-interrogated note durably on disk."""
    append_checkpoint_record(path, record)


def load_answer_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load already-written records (the inverse of `append_answer_
    checkpoint`), returning `[]` when the file does not exist yet."""
    return load_checkpoint_records(path, AnswerCheckpointCorruptError)


def _default_answers_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Honour `paths.answers_dir` when config declares it, else `ANSWERS_DIR`
    -- the same config-then-fallback resolution every other pipeline
    directory uses (`axial.paths`)."""
    return _read_configured_dir(config_path, "answers_dir", ANSWERS_DIR)


def _default_domain_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Honour `paths.domain_dir` when config declares it, else the default
    domain directory (mirrors `axial.tag._default_domain_dir`)."""
    return _read_configured_dir(config_path, "domain_dir", DEFAULT_DOMAIN_DIR)


# ---------------------------------------------------------------------------
# Abstention (D7)
# ---------------------------------------------------------------------------


def is_abstention(value: Any) -> bool:
    """Whether `value` is the explicit abstention rather than an answer: the
    bare `not-in-passage` string, `{"not-in-passage": "<reason>"}`, or either
    of those alone inside a one-element list.

    The list form exists because six fields are asked for as JSON lists and
    the abstention rule is written for a scalar, so `["not-in-passage"]` is
    the natural middle form for a multi-valued field. Read as an answer it
    would under-report abstention on exactly those fields, and Reconcile
    (§7.16) would mint `not-in-passage` as a name in the corpus. A list with
    a second element is a real answer, however malformed -- an abstention is
    never partial."""
    if value == NOT_IN_PASSAGE:
        return True
    if isinstance(value, dict):
        return set(value) == {NOT_IN_PASSAGE}
    if isinstance(value, list) and len(value) == 1:
        return is_abstention(value[0])
    return False


# ---------------------------------------------------------------------------
# The domain frame, as examples (§7.1, D8/D9)
# ---------------------------------------------------------------------------


def frame_examples(schema: Schema, codebook: Codebook) -> dict[str, list[tuple[str, str]]]:
    """Per answer field that has one, the frame's examples as
    `(example_id, definition)` pairs, in the frame's own order. Loaded from
    the domain directory, never hardcoded, and never used as a vocabulary to
    validate against -- a field whose axis the frame does not declare simply
    has no examples."""
    examples: dict[str, list[tuple[str, str]]] = {}
    for field, axis_name in NEAREST_EXAMPLE_AXES.items():
        axis = schema.axes.get(axis_name)
        if axis is None:
            continue
        entries = codebook.axes.get(axis_name, {})
        pairs = [(tag_id, entry.definition) for tag_id, entry in entries.items()]
        if not pairs:
            pairs = [(tag_id, "") for tag_id in sorted(axis.tag_ids)]
        if pairs:
            examples[field] = pairs
    return examples


# ---------------------------------------------------------------------------
# The prompt (D6 questions verbatim, free answer first -- D8)
# ---------------------------------------------------------------------------

_QUESTIONS = """\
1. about -- What is this passage about? Give one or more short phrases in \
your own words. (multi-valued: a JSON list of strings)
2. claim -- What is being claimed, in one sentence.
3. move -- What is this passage DOING in the argument? Not a label like \
"evidence" but the move itself, e.g. "conceding a point in order to narrow \
it".
4. ranges_over -- What does the claim range over?
5. stops_holding -- Where does the author say it stops holding?
6. position_of -- Whose position is this?
7. arguing_against -- Who or what is it arguing against? (multi-valued: a \
JSON list of strings)
8. names -- Every named thing: people, places, institutions, events, \
movements, periods, and any figure or table the passage names. (a JSON list \
of {"name": ..., "kind": ...} objects; kind is usually one of person, \
country/state/place, institution/group, movement/religion, period, event, \
concept, work, figure, table -- use the joined label whole, e.g. \
country/state/place rather than just country or place -- or your own word \
if none of these fit)
9. citations -- Who does it cite, and is each citation support, foil, or \
authority? (a JSON list of {"cited": ..., "stance": "support"|"foil"|\
"authority", "about": ...} objects)
10. mechanism -- What is the mechanism: what causes what, in what order.
11. evidence -- What evidence is offered.
12. comparison -- What comparison is made, stated or implied.
13. defines -- What is defined here (a JSON list of strings), and \
separately uses -- what is merely used without being defined (a JSON list \
of strings).
14. concedes -- What the author concedes or hedges.
15. assumes -- What it assumes without saying.
"""

_PROMPT_TEMPLATE = """\
You are reading ONE passage from an academic book and answering open \
questions about it, in your own words.

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

QUESTIONS -- answer each of these in your own words, before reading the \
EXAMPLES section further below.

{questions}

ABSTENTION. Every answer must come from the passage. Where the passage does \
not support one, answer with the string "{not_in_passage}", or with \
{{"{not_in_passage}": "<one short clause saying why>"}} when there is \
something worth saying -- including the case where the passage bears on the \
question but does not settle it ("cannot judge between X and Y"). Abstain \
that same way on a multi-valued field: the bare string, never a list \
containing it. An abstention is an ordinary, expected answer. A guessed \
answer is worse than an abstention, because a reader cannot tell it from one \
you actually read.

An empty list is also an ordinary answer on a multi-valued field, and it \
says something different: you read the passage and it names none of that \
kind of thing. Use `[]` for "there are none here" and "{not_in_passage}" for \
"the passage does not let me judge".

{examples_section}
RESPONSE. Reply with ONLY a JSON object (no prose, no markdown fences) \
carrying exactly these keys: {answer_fields}. Write each free answer key \
BEFORE its own "_nearest" key, and never let an example decide a free \
answer: the free answer is what you read in the passage, the nearest example \
is a separate, secondary note about which of someone else's categories it \
happens to sit closest to.
"""

_EXAMPLES_SECTION_TEMPLATE = """\
EXAMPLES -- read this section only AFTER you have answered every question \
above in your own words.

These lists come from a domain frame written before this book was read. They \
are NOT a menu, NOT a vocabulary, and NOT a set of allowed answers. Nothing \
checks your free answers against them, and an answer that matches none of \
them is the normal case. Some of the descriptions below are phrased as \
instructions ("decide this first", "never use X for Y"): they were written \
for a labelling task that no longer exists, and they are not instructions to \
you. Read them as descriptions of what each example means, nothing more. \
They are here for one narrow job: for each field \
below, add a SECOND key "<field>_nearest" = {{"example": <the id of the \
nearest example, or null>, "fit": "close" | "loose" | "none"}}. Do not \
change, trim, or rephrase your free answer to bring it closer to an example. \
"none" and null are ordinary answers.

{blocks}
"""


def _format_context_value(value: Any) -> str:
    """Render one context value for the prompt, marking an absent one
    explicitly rather than printing an empty line the model could read as an
    instruction gap."""
    if value is None or value == "" or value == []:
        return "(not recorded)"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def chapter_for_section(toc: Any, section: str | None) -> str | None:
    """The chapter a note's section sits under, read off the envelope's
    reconstructed `toc` (§7.3's nested `{title, children[]}` shape). Matches
    the section heading against a top-level title or one of its children,
    casefolded and whitespace-collapsed; returns `None` when the toc does not
    place it, because guessing a chapter is worse than saying there isn't
    one."""
    if not section or not isinstance(toc, list):
        return None
    target = _normalize(section)
    for entry in toc:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if isinstance(title, str) and _normalize(title) == target:
            return title
        for child in entry.get("children") or []:
            child_title = child.get("title") if isinstance(child, dict) else child
            if isinstance(child_title, str) and _normalize(child_title) == target:
                return title if isinstance(title, str) else None
    return None


def _normalize(text: str) -> str:
    """Casefold + collapse whitespace -- the one string normalisation this
    module uses, shared by the toc match and the collapse check so the two
    can never drift."""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def compose_interrogation_prompt(
    chunk_record: dict[str, Any],
    source_meta: dict[str, Any],
    envelope: dict[str, Any],
    examples: dict[str, list[tuple[str, str]]],
) -> str:
    """Compose one note's interrogation prompt: §7.15's context list, the
    thirteen D6 questions asked in the model's own words, the abstention
    rule, and -- last, after every free question -- the frame's examples for
    the few fields that have them (D8)."""
    blocks = []
    for field, pairs in examples.items():
        rendered = "\n".join(
            f"- {example_id}: {definition}" if definition else f"- {example_id}"
            for example_id, definition in pairs
        )
        blocks.append(f"Examples for {field!r} (add {field}_nearest):\n{rendered}")
    examples_section = (
        _EXAMPLES_SECTION_TEMPLATE.format(blocks="\n\n".join(blocks)) if blocks else ""
    )
    answer_keys = list(ANSWER_FIELDS) + [f"{field}_nearest" for field in examples]
    return _PROMPT_TEMPLATE.format(
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
        questions=_QUESTIONS,
        not_in_passage=NOT_IN_PASSAGE,
        examples_section=examples_section,
        answer_fields=", ".join(answer_keys),
    )


# ---------------------------------------------------------------------------
# Parsing (no vocabulary gate anywhere -- D9)
# ---------------------------------------------------------------------------


def parse_answer_response(raw: str, examples: dict[str, list[tuple[str, str]]]) -> dict[str, Any]:
    """Parse one raw response into an answer set: every field of
    `ANSWER_FIELDS`, plus whichever `<field>_nearest` the model supplied.

    Nothing here is checked against the frame (D9): a free answer matching no
    example is the normal case, and a `nearest` naming an example the frame
    does not declare is recorded verbatim rather than corrected. The only
    rejections are shape ones -- a missing field, or a blank/empty value
    where §7.15 requires an answer or an explicit abstention -- and they are
    re-askable, since a response missing a question is response noise, not a
    judgment.
    """
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise AnswerParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AnswerParseError(
            f"expected a top-level JSON object of answers, got {type(data).__name__}"
        )

    answers: dict[str, Any] = {}
    for field in ANSWER_FIELDS:
        if field not in data:
            raise AnswerParseError(f"answer field {field!r} is missing from the response")
        value = data[field]
        if _is_blank(value, field):
            raise AnswerParseError(
                f"answer field {field!r} is empty: an answer or the explicit "
                f"{NOT_IN_PASSAGE!r} abstention is required, never a blank"
            )
        answers[field] = value
        nearest_key = f"{field}_nearest"
        if field in examples and nearest_key in data:
            answers[nearest_key] = data[nearest_key]
    return answers


def _is_blank(value: Any, field: str | None = None) -> bool:
    """Whether a parsed value is response noise rather than an answer: an
    empty/whitespace-only string, `None`, or an empty object.

    An empty LIST on a list-valued field is an answer, not a blank: "this
    passage defines nothing", "this passage cites no one" is what the
    passage says, and it is the natural JSON for it. Rejecting it cost a real
    note -- the re-ask carries no error feedback, so the model repeats the
    identical response until the budget is spent and all sixteen answers are
    discarded over one field, permanently (a note carrying any record is
    never re-sent, §7.15). It is recorded verbatim rather than normalised
    onto `not-in-passage`, because the two say different things: `[]` is a
    read, an abstention is a refusal to guess (§7.15's own three states).
    On a scalar field an empty list is still shape noise."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0 and field not in LIST_VALUED_FIELDS
    if isinstance(value, dict):
        return len(value) == 0
    return False


def build_answer_record(
    chunk_record: dict[str, Any],
    source_id: str,
    model: str,
    frame_version: str,
    answers: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Assemble one answer record (§7.15's record shape). Carries no vote or
    draws field: one draw (D4)."""
    return {
        "chunk_id": chunk_record["chunk_id"],
        "source_id": source_id,
        "section": chunk_record.get("section"),
        "pass": NOTE_INTERROGATE_PASS_NAME,
        "model": model,
        "frame_version": frame_version,
        "answered_at": now or _utc_now(),
        "answers": answers,
    }


def _build_failure_record(chunk_id: str, source_id: str, reason: str) -> dict[str, Any]:
    """A note whose call did not complete (§7.15 state 3): recorded against
    its chunk_id with the reason, never as an answer with fields missing."""
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "pass": NOTE_INTERROGATE_PASS_NAME,
        "failed_at": _utc_now(),
        "failure_reason": reason,
    }


def _build_skip_record(chunk_id: str, source_id: str, reason: str) -> dict[str, Any]:
    """A note the garble backstop dropped before any model call (§7.8):
    durably recorded, not just logged, so a skip can never again be a silent
    loss."""
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "pass": NOTE_INTERROGATE_PASS_NAME,
        "skipped_at": _utc_now(),
        "skip_reason": reason,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# The reports: abstention, the D8 collapse check, and the cost probe
# ---------------------------------------------------------------------------


def abstention_rates(records: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Per answer field, the share of answered notes that abstained (D7).
    Read off the artifact, so it is the same number for a 50-note sample and
    for a full corpus run."""
    answered = [record["answers"] for record in records if "answers" in record]
    if not answered:
        return {}
    return {
        field: round(
            sum(1 for answers in answered if is_abstention(answers.get(field))) / len(answered), 4
        )
        for field in ANSWER_FIELDS
    }


def collapse_rates(
    records: Iterable[dict[str, Any]], examples: dict[str, list[tuple[str, str]]]
) -> dict[str, dict[str, float]]:
    """The D8 collapse check (§7.15). Two rates per example-bearing field,
    both exact-match after casefolding and whitespace collapse:

      - `frame_example_rate`: the share of free answers that are string-equal
        to ANY of that question's example values;
      - `nearest_example_rate`: the share that are string-equal to that
        record's OWN `<field>_nearest.example`.

    A field whose free answers are overwhelmingly verbatim example strings
    means the interrogation has rebuilt the tag list through the back door.
    No threshold is asserted and nothing here gates: the number is reported
    and read. Abstentions are excluded from both denominators -- an
    abstention is not a collapsed answer.
    """
    answered = [record["answers"] for record in records if "answers" in record]
    frame_rate: dict[str, float] = {}
    nearest_rate: dict[str, float] = {}
    for field, pairs in examples.items():
        example_forms = {_normalize(example_id) for example_id, _ in pairs}
        considered = 0
        frame_hits = 0
        nearest_hits = 0
        for answers in answered:
            value = answers.get(field)
            if is_abstention(value):
                continue
            considered += 1
            for form in _free_answer_forms(value):
                if form in example_forms:
                    frame_hits += 1
                    break
            nearest = answers.get(f"{field}_nearest")
            example = nearest.get("example") if isinstance(nearest, dict) else None
            example_strings = example if isinstance(example, list) else [example]
            own = {_normalize(item) for item in example_strings if isinstance(item, str)}
            if own and any(form in own for form in _free_answer_forms(value)):
                nearest_hits += 1
        if considered:
            frame_rate[field] = round(frame_hits / considered, 4)
            nearest_rate[field] = round(nearest_hits / considered, 4)
    return {"frame_example_rate": frame_rate, "nearest_example_rate": nearest_rate}


def _free_answer_forms(value: Any) -> set[str]:
    """The normalised string forms of one free answer -- one for a string
    answer, one per entry for a multi-valued one -- so the collapse check
    reads a list-valued field (`about`) the same way it reads a scalar."""
    if isinstance(value, str):
        return {_normalize(value)}
    if isinstance(value, list):
        return {_normalize(item) for item in value if isinstance(item, str)}
    return set()


def corpus_note_count(chunks_dir: Path) -> int:
    """How many notes the whole corpus holds, counted off the chunk artifact
    (§7.7) -- the multiplier the cost probe extrapolates a measured per-note
    cost by. Zero when no chunk artifact exists (e.g. a worktree with no
    `data/`), which reports an extrapolation of `null` rather than a
    fabricated number."""
    if not chunks_dir.is_dir():
        return 0
    total = 0
    for path in sorted(chunks_dir.glob("*.jsonl")):
        if path.name.endswith(".skips.jsonl"):
            continue
        with path.open("r", encoding="utf-8") as handle:
            total += sum(1 for line in handle if line.strip())
    return total


def cost_report(
    usage: dict[str, int] | None, model: str, answered: int, corpus_notes: int
) -> dict[str, Any]:
    """The cost probe (P0-6): measured tokens and dollars for the notes this
    run actually paid for, per note, and extrapolated to the corpus. `usd` is
    `None` for a model absent from `PRICE_TABLE_USD_PER_1K` (e.g. the stub) --
    never a fabricated zero."""
    prompt_tokens = (usage or {}).get("prompt_tokens", 0)
    completion_tokens = (usage or {}).get("completion_tokens", 0)
    total_tokens = (usage or {}).get("total_tokens", prompt_tokens + completion_tokens)
    usd = estimate_cost(model, prompt_tokens, completion_tokens) if answered else None
    usd_per_note = usd / answered if usd is not None and answered else None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "tokens_per_note": round(total_tokens / answered, 1) if answered else None,
        "usd": usd,
        "usd_per_note": usd_per_note,
        "corpus_notes": corpus_notes,
        "usd_corpus_extrapolated": (
            usd_per_note * corpus_notes if usd_per_note is not None else None
        ),
    }


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def _read_json(path: Path, what: str, remedy: str) -> dict[str, Any]:
    if not path.is_file():
        raise MissingContextError(path, what, remedy)
    return json.loads(path.read_text(encoding="utf-8"))


def run_interrogate(
    source_path: str | Path,
    *,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    data_dir: Path | None = None,
    domain_dir: str | Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Interrogate every note of `source_path` and return the run summary.

    One call per note (D4/D6), reading the note from the on-disk chunk
    artifact and its context from the envelope and the source-metadata
    record. Each answer is appended to `<answers_dir>/<source_id>.jsonl` as it
    is produced, so an interrupted run resumes and a note already answered is
    never re-sent to the model.

    `data_dir`, when given, rebases all four directories this pass touches
    (`chunks/`, `envelopes/`, `source_meta/`, `answers/`) onto that one
    parent -- the seam that lets a cost probe run against another checkout's
    `data/` from anywhere. Omitted, each resolves from `config_path` exactly
    as every other pass resolves its own.

    `limit`, when given, stops the run after that many notes are interrogated
    THIS run (D14's ~50-output sample gate): the summary reports
    `complete: false`, and the end-of-source reconciliation is deliberately
    not applied, since a deliberately partial run is not a short one.

    Per-note fault isolation (§7.15): a content-shaped failure -- a
    moderation refusal, or malformed/unusable JSON surviving the re-ask
    budget -- is recorded against that chunk_id with its reason and the
    source continues. A transport-level failure still propagates. A source
    where every attempted note failed raises `AllNotesFailedError`.
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

    # `data_dir` rebases all four directories at once; without it each
    # resolves from config exactly as its own writing pass resolves it.
    chunks_dir = data_dir / "chunks" if data_dir is not None else _default_chunks_dir(config_path)
    envelopes_dir = (
        data_dir / "envelopes" if data_dir is not None else _default_envelopes_dir(config_path)
    )
    source_meta_dir = data_dir / "source_meta" if data_dir is not None else SOURCE_META_DIR
    answers_dir = (
        data_dir / ANSWERS_DIR_NAME if data_dir is not None else _default_answers_dir(config_path)
    )

    try:
        chunk_records = read_chunks(source_id, chunks_dir=chunks_dir, config_path=config_path)
    except ChunkError as exc:
        raise ChunkingFailedError(exc) from exc

    envelope = _read_json(
        envelope_path(source_id, envelopes_dir), "envelope", f"axial envelope {source_path}"
    )
    source_meta = _read_json(
        source_meta_path(source_id, source_meta_dir),
        "source-metadata record",
        f"axial ingest {source_path}",
    )

    checkpoint_path = answers_checkpoint_path(source_id, answers_dir)
    # Split by record kind on load, not just by chunk_id: a note carrying any
    # of the three is not re-sent to the model, but an earlier run's FAILURES
    # must still count as failures at the end of this one -- otherwise a
    # rerun after a total failure makes zero calls and reports success with
    # no answers on disk (mirrors `axial.tag`'s own resumed-quarantine fold).
    already_answered: set[str] = set()
    already_failed: set[str] = set()
    already_skipped: set[str] = set()
    for record in load_answer_checkpoint(checkpoint_path):
        if "answers" in record:
            already_answered.add(record["chunk_id"])
        elif "failure_reason" in record:
            already_failed.add(record["chunk_id"])
        else:
            already_skipped.add(record["chunk_id"])
    already_done = already_answered | already_failed | already_skipped

    answered = 0
    failed = 0
    skipped = 0
    reused = 0
    attempted = 0
    model: str | None = None
    total_notes = len(chunk_records)
    for index, chunk_record in enumerate(chunk_records, start=1):
        chunk_id = chunk_record["chunk_id"]
        if chunk_id in already_done:
            reused += 1
            continue
        if limit is not None and attempted >= limit:
            break

        skip_reason = garble_only_skip_reason(chunk_record["text"])
        if skip_reason is not None:
            print(
                f"note_interrogate: skipping {chunk_id}: {skip_reason}",
                file=sys.stderr,
            )
            append_answer_checkpoint(
                checkpoint_path, _build_skip_record(chunk_id, source_id, skip_reason)
            )
            skipped += 1
            continue

        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc
        model = client.model_for_pass(NOTE_INTERROGATE_PASS_NAME)

        prompt = compose_interrogation_prompt(chunk_record, source_meta, envelope, examples)
        attempted += 1
        started = time.monotonic()
        try:
            raw = complete_json(
                client,
                prompt,
                pass_name=NOTE_INTERROGATE_PASS_NAME,
                validate=lambda response: parse_answer_response(response, examples),
            )
            answers = parse_answer_response(raw, examples)
        except (ContentRefusedError, ModelJsonError, AnswerParseError) as exc:
            # Content-shaped, not transient: re-sending the identical prompt
            # to the same model cannot change the outcome, so this note is
            # recorded as a failure and the source carries on (§7.15).
            print(
                f"note_interrogate: {chunk_id} failed ({index}/{total_notes}): {exc}",
                file=sys.stderr,
            )
            append_answer_checkpoint(
                checkpoint_path, _build_failure_record(chunk_id, source_id, str(exc))
            )
            failed += 1
            continue
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc

        append_answer_checkpoint(
            checkpoint_path,
            build_answer_record(chunk_record, source_id, model, str(schema.version), answers),
        )
        answered += 1
        print(
            f"note_interrogate: {chunk_id} answered ({index}/{total_notes}) "
            f"in {time.monotonic() - started:.1f}s",
            file=sys.stderr,
        )

    records = load_answer_checkpoint(checkpoint_path)
    answer_records = [record for record in records if "answers" in record]
    failure_count = sum(1 for record in records if "failure_reason" in record)

    # A source that produced nothing fails loudly rather than reporting an
    # empty success (§7.15), and it keeps failing on every rerun until the
    # cause is fixed -- the artifact is read here, so an earlier run's
    # failures count even when this run made no call at all. Skips are not
    # failures: a source whose every note is a garble skip legitimately has
    # zero answer records and is not an error.
    if not answer_records and failure_count:
        raise AllNotesFailedError(source_id, failure_count)

    complete = limit is None or (answered + failed + skipped + reused) == total_notes
    if complete:
        accounted_for = answered + failed + skipped + reused
        if accounted_for != total_notes:
            raise AnswerRecordCountMismatchError(source_id, total_notes, accounted_for)

    return {
        "source_id": source_id,
        "pass": NOTE_INTERROGATE_PASS_NAME,
        "model": model,
        "answers_path": str(checkpoint_path),
        "notes_total": total_notes,
        "answered": answered,
        "failed": failed,
        "skipped": skipped,
        "reused": reused,
        # What the artifact holds in total, this run plus every earlier one:
        # the count slice 04 will actually read, which `answered` alone does
        # not give on a resumed run.
        "answer_records": len(answer_records),
        "failure_records": failure_count,
        "limit": limit,
        "complete": complete,
        "abstention_rate": abstention_rates(records),
        "collapse": collapse_rates(records, examples),
        "cost": cost_report(
            client.usage_for_pass(NOTE_INTERROGATE_PASS_NAME) if client is not None else None,
            model or "",
            answered,
            corpus_note_count(chunks_dir),
        ),
    }
