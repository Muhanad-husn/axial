"""The intake fork-check (specs/PHASE-B.md §7, DEC-62, issue #649): before
retrieval runs, measure the question against the corpus it actually has, and
ask the analyst only at a genuine fork.

**Measurement is deterministic SQL, scoped to the question's own terms --
never the whole index.** Every content word of the brief's `case` and
`request` (`axial.query.names.content_words`, the same tokenizer `find_names`'
own compound-query fallback already uses) is resolved to a door
(`find_names(word, limit=1)`); each resolved door's per-source breakdown
(`axial.query.store.concept_sources`) is the raw material -- how many notes,
from how many sources, the largest single source's own share, and each
source's publication year. A word that resolves to nothing is recorded as a
term the corpus is silent on. This is bounded by the question's own vocabulary
(typically well under twenty words), never the vault's 49,674 names --
`interrogate.py`'s own docstring measured that whole-index render at ~500k
tokens and rules it out for exactly this reason.

**One model call decides whether that measurement is a genuine fork, and
phrases the question.** No hand-tuned imbalance threshold decides this --
that is the tripwire this repo names explicitly (issue #268: three review
rounds hand-tuning six constants that read 4/30 real cases, replaced by one
model call). The model proposes `{is_fork, concept, kind, question, options}`;
`parse_fork_response` is the deterministic wrapper (`disposition_for`'s own
"model proposes, code decides" pattern, charter Principle III): it validates
every option's `drop_source_ids` against the measurement's own real source
ids and rejects an unresolvable concept or an out-of-vocabulary `kind`,
exactly as `axial.brief.interrogate`'s parser rejects an out-of-vocabulary
`assessment`. No concept resolved at all (the corpus is silent on every term
the question names) skips the call entirely -- there is nothing to judge, the
same zero-model-call shape `generate_counter_position` already takes on an
uncontested brief.

**An answer compiles to exactly one shape, `ForkConstraint`** -- no
constraint DSL: a set of source ids to drop from evidence, an optional
per-source cap, and free-text guidance. A temporal fork compiles through the
same shape: DEC-62's rule ("dates assign roles, not cutoffs") means the
DEFAULT option a temporal fork offers carries no `drop_source_ids` at all,
only guidance describing what each era witnesses; an option that excludes a
period does so only because the analyst explicitly picked it, never as the
fork's only choice. `compile_constraint` is pure and deterministic: it looks
up the analyst's chosen option by label (case-insensitive) and/or appends
free text to guidance, never interprets free text into a filter.

**Batch vs interactive.** `axial ask` is where a fork question is actually
asked, live, of the analyst (`axial.cli._fork_prompt`); `axial brief run`/
`smoke`/`sweep` never prompt. A batch caller either supplies `brief.fork_answer`
(the pre-known answer, §7.1) or leaves it `None`, in which case a genuine
fork found on that brief is recorded in the analysis record's `intake_fork`
disclosure with `answer: null` and the run proceeds fully unconstrained --
never guessed at, never blocked on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from axial.brief.intake import Brief
from axial.llm import FORK_CHECK_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.paths import default_vault_dir
from axial.query import store as note_store
from axial.query.names import content_words, find_names
from axial.query.reader import MalformedChunkIdError, source_id_from_chunk_id

# The §649 fork `kind` vocabulary -- closed, not open text (mirrors
# `axial.brief.interrogate.ASSESSMENTS`'s own closed-vocabulary discipline).
FORK_KINDS = frozenset({"source_imbalance", "temporal_role", "temporal_consequence"})


class ForkCheckError(Exception):
    """Base class for all intake fork-check errors."""


class ForkCheckFailedError(ForkCheckError):
    """Raised when the fork-check model call itself fails: a transport
    error, or a response that never parsed as usable JSON within
    `complete_json`'s bounded re-ask budget. Never a silent "no fork"."""


class ForkCheckParseError(ForkCheckError):
    """Raised when a well-formed-JSON fork-check response does not match
    the expected shape, or names a concept/source/kind the measurement it
    was shown does not carry -- a genuine schema-vocabulary miss, immediately
    fatal, never smoothed over (the same P0-6 discipline
    `axial.brief.interrogate.InvalidAssessmentError` already follows)."""


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptMeasurement:
    """One concept the question touches, measured against the note store:
    how many notes carry it, from how many sources, each source's own
    contribution (`axial.query.store.SourceShare`, ranked by note count),
    and the largest single source's share of the total."""

    canonical: str
    matched_on: str
    note_count: int
    source_count: int
    sources: tuple[note_store.SourceShare, ...]
    top_share: float


@dataclass(frozen=True)
class QuestionMeasurement:
    """The whole measurement a fork-check judges: every concept the
    question's own words resolved to a door for, plus every content word
    that resolved to nothing -- the corpus's silence, stated rather than
    omitted."""

    concepts: tuple[ConceptMeasurement, ...] = ()
    silent_terms: tuple[str, ...] = ()


def measure_question(brief: Brief, *, vault_dir: Path | None = None) -> QuestionMeasurement:
    """Measure `brief`'s own `case`/`request` against the note store
    (module docstring): resolve every content word to a door, and read that
    door's per-source breakdown. `QuestionMeasurement()` (empty) when the
    vault carries no store at all -- the store is what this measurement
    reads (DEC-62, issue #648); a vault materialized before it existed has
    nothing here to measure, and the fork-check is skipped entirely rather
    than falling back to a second read path built for a feature this new."""
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    connection = note_store.connect(vault)
    if connection is None:
        return QuestionMeasurement()
    try:
        terms = list(dict.fromkeys(content_words(brief.case) + content_words(brief.request)))
        concepts: dict[str, ConceptMeasurement] = {}
        silent: list[str] = []
        for term in terms:
            hits = find_names(term, limit=1, vault_dir=vault)
            if not hits:
                silent.append(term)
                continue
            canonical = hits[0].canonical
            if canonical in concepts:
                continue
            sources = tuple(note_store.concept_sources(connection, canonical))
            note_count = sum(source.note_count for source in sources)
            if note_count == 0:
                continue
            concepts[canonical] = ConceptMeasurement(
                canonical=canonical,
                matched_on=term,
                note_count=note_count,
                source_count=len(sources),
                sources=sources,
                top_share=sources[0].note_count / note_count,
            )
        return QuestionMeasurement(concepts=tuple(concepts.values()), silent_terms=tuple(silent))
    finally:
        connection.close()


def render_measurement(
    measurement: QuestionMeasurement, question_scope: dict[str, Any] | None
) -> str:
    """Render `measurement` as prompt text: one block per concept (its
    total notes/sources, then each contributing source's own count, author
    and year), the silent terms, and the question's own stated period when
    interrogation (§7.2) found one."""
    if not measurement.concepts:
        lines = ["(no concept in this question resolved to anything the corpus holds)"]
    else:
        lines = []
        for concept in measurement.concepts:
            lines.append(
                f'- "{concept.canonical}" (matched the word "{concept.matched_on}"): '
                f"{concept.note_count} notes, {concept.source_count} source(s), "
                f"largest single source is {concept.top_share:.0%} of it"
            )
            for source in concept.sources:
                year = source.year if source.year is not None else "year unknown"
                author = source.author or source.source_id
                lines.append(
                    f"    - {source.source_id} ({author}, {year}): {source.note_count} notes"
                )
    if measurement.silent_terms:
        lines.append(
            "Terms in the question the corpus holds nothing under: "
            + ", ".join(measurement.silent_terms)
        )
    if question_scope and question_scope.get("period"):
        lines.append(f"The question itself states this period: {question_scope['period']}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The fork-check call
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForkOption:
    """One option a fork question offers (module docstring): a label the
    analyst can pick by name, the source ids that option excludes entirely
    (empty for a non-excluding option -- the DEC-62 default for a temporal
    fork), an optional per-source note cap, and the guidance text that
    option's own reading assigns."""

    label: str
    drop_source_ids: tuple[str, ...] = ()
    per_source_cap: int | None = None
    guidance: str = ""


@dataclass(frozen=True)
class ForkCheckResult:
    """The fork-check's own verdict: `is_fork` gates everything else.
    `measured` is `False` only when the measurement resolved no concept at
    all, in which case the model was never called (module docstring) --
    distinct from `is_fork=False`, which is the model's own real "no fork"
    verdict after actually being asked."""

    is_fork: bool
    measured: bool = True
    concept: str | None = None
    kind: str | None = None
    question: str | None = None
    options: tuple[ForkOption, ...] = ()


def compose_fork_prompt(
    brief: Brief, measurement: QuestionMeasurement, question_scope: dict[str, Any] | None
) -> str:
    """The fork-check prompt (module docstring): the brief, the measurement,
    and the two fork shapes DEC-62 names, with the explicit instruction that
    a small, ordinary imbalance is not a fork -- "no fork found" is the
    common, correct answer."""
    return f"""You are the intake fork-check of an analysis engine (specs/PHASE-B.md \
section 7, DEC-62, issue #649). Before retrieval runs, decide whether this \
question's own measured corpus coverage presents a GENUINE FORK worth asking \
the analyst about -- a real choice that would change what evidence retrieval \
assembles, not a routine gap or an ordinary imbalance every corpus has.

Case: "{brief.case}"
Request: "{brief.request}"

Measured corpus coverage for the concepts this question touches:
{render_measurement(measurement, question_scope)}

A genuine fork is one of:
- source_imbalance: one source (or a small handful) so dominates a concept's \
coverage that treating it as one voice among many would misrepresent the \
corpus, and the analyst might reasonably want it read as background rather \
than as a full voice.
- temporal_role / temporal_consequence: the question's own period sits after \
some sources' publication year and before others'. DEC-62 names two shapes: \
a concept asked about after an event but rooted older, where the older \
sources are full voices on the roots ("temporal_role"); or a consequence \
question -- did the event change its own causes -- where pre-event sources \
witness the causes and post-event sources the consequences, and comparing \
them IS the answer ("temporal_consequence").

Do NOT invent a fork from an ordinary, small imbalance -- most questions have \
none, and "no fork found" is the common, correct answer. Only propose one \
when a real choice exists that would change what gets retrieved.

If you find a genuine fork, phrase ONE short question naming the measured \
numbers (never a vague generality), and offer 2-4 options. Each option may \
name specific source_ids from the measurement above, under drop_source_ids, \
to exclude from evidence entirely, and/or a per_source_cap limiting how many \
notes from any one source the evidence set may hold, plus guidance text \
stating what that option means for how retrieval should read the corpus. \
**Per DEC-62, dates assign roles, not cutoffs: a temporal fork's default \
option keeps every source in and states what each era witnesses in its own \
guidance -- add drop_source_ids only to an option that is a genuine, \
explicit EXCLUSION the analyst is choosing, never as the fork's only \
option.**

Return ONLY this JSON object, no prose and no code fence:
{{"is_fork": true|false, "concept": "<canonical from the measurement above, \
or null>", "kind": "source_imbalance"|"temporal_role"|"temporal_consequence"\
|null, "question": "<the question text, or null>", "options": [{{"label": \
"<short option label>", "drop_source_ids": ["<source_id>", ...], \
"per_source_cap": <int or null>, "guidance": "<what this option means for \
retrieval>"}}, ...]}}"""


def parse_fork_response(raw: str, measurement: QuestionMeasurement) -> ForkCheckResult:
    """Parse a raw fork-check completion against `measurement` -- the
    deterministic wrapper (module docstring): `is_fork` must be a bool; a
    `False` verdict short-circuits to the trivial result regardless of
    whatever else the model wrote. A `True` verdict must name a concept the
    measurement actually carries, a non-blank question, and at least one
    option whose `drop_source_ids` are all real source ids of that
    concept's own measurement -- any of these failing is a
    `ForkCheckParseError`, never silently repaired."""
    data = parse_model_json(raw)
    if not isinstance(data, dict):
        raise ForkCheckParseError(
            f"fork-check response must be a JSON object, got {type(data).__name__}"
        )

    is_fork = data.get("is_fork")
    if not isinstance(is_fork, bool):
        raise ForkCheckParseError(f"is_fork must be a bool, got {data.get('is_fork')!r}")
    if not is_fork:
        return ForkCheckResult(is_fork=False)

    concept = data.get("concept")
    by_canonical = {c.canonical: c for c in measurement.concepts}
    if not isinstance(concept, str) or concept not in by_canonical:
        raise ForkCheckParseError(
            f"a genuine fork must name a concept the measurement carries, got {concept!r}"
        )

    kind = data.get("kind")
    if kind is not None and kind not in FORK_KINDS:
        raise ForkCheckParseError(f"kind {kind!r} outside {sorted(FORK_KINDS)!r}")

    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ForkCheckParseError("a genuine fork must carry a non-blank question")

    known_source_ids = {source.source_id for source in by_canonical[concept].sources}

    raw_options = data.get("options")
    if not isinstance(raw_options, list) or not raw_options:
        raise ForkCheckParseError("a genuine fork must carry at least one option")
    options: list[ForkOption] = []
    for entry in raw_options:
        if not isinstance(entry, dict):
            raise ForkCheckParseError(f"option entry must be an object, got {entry!r}")
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ForkCheckParseError(f"option entry missing a non-blank label: {entry!r}")
        drop_raw = entry.get("drop_source_ids") or []
        if not isinstance(drop_raw, list):
            raise ForkCheckParseError(f"drop_source_ids must be a list: {entry!r}")
        drop: list[str] = []
        for source_id in drop_raw:
            if not isinstance(source_id, str) or source_id not in known_source_ids:
                raise ForkCheckParseError(
                    f"drop_source_ids names {source_id!r}, not a real source of "
                    f"{concept!r}'s own measurement ({sorted(known_source_ids)!r})"
                )
            drop.append(source_id)
        cap = entry.get("per_source_cap")
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
            raise ForkCheckParseError(f"per_source_cap must be a positive int or null, got {cap!r}")
        guidance = entry.get("guidance")
        if guidance is not None and not isinstance(guidance, str):
            raise ForkCheckParseError(f"guidance must be a string or null, got {guidance!r}")
        options.append(
            ForkOption(
                label=label.strip(),
                drop_source_ids=tuple(drop),
                per_source_cap=cap,
                guidance=(guidance or "").strip(),
            )
        )

    return ForkCheckResult(
        is_fork=True,
        concept=concept,
        kind=kind,
        question=question.strip(),
        options=tuple(options),
    )


def assess_fork(
    brief: Brief,
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    question_scope: dict[str, Any] | None = None,
) -> ForkCheckResult:
    """Run the fork-check: measure, then -- only when the measurement
    resolved at least one concept -- make the one bounded model call and
    parse it through `parse_fork_response`. `ForkCheckResult(is_fork=False,
    measured=False)` with zero model calls when the measurement is empty
    (module docstring)."""
    measurement = measure_question(brief, vault_dir=vault_dir)
    if not measurement.concepts:
        return ForkCheckResult(is_fork=False, measured=False)
    prompt = compose_fork_prompt(brief, measurement, question_scope)
    try:
        raw = complete_json(client, prompt, pass_name=FORK_CHECK_PASS_NAME)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise ForkCheckFailedError(f"fork-check call failed: {exc}") from exc
    return parse_fork_response(raw, measurement)


# ---------------------------------------------------------------------------
# The answer, compiled to one shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForkAnswer:
    """The analyst's own answer to a fork question: an option picked by
    label, free text, or both -- "every question offers options AND free
    text" (issue #649's own acceptance bar)."""

    option: str | None = None
    free_text: str | None = None

    def is_blank(self) -> bool:
        return not (self.option and self.option.strip()) and not (
            self.free_text and self.free_text.strip()
        )


@dataclass(frozen=True)
class ForkConstraint:
    """The one shape every fork answer compiles to (module docstring): a
    set of source ids excluded from evidence entirely, an optional
    per-source note cap, and free-text guidance -- no constraint DSL."""

    drop_source_ids: frozenset[str] = frozenset()
    per_source_cap: int | None = None
    guidance: str = ""


def compile_constraint(fork: ForkCheckResult, answer: ForkAnswer) -> ForkConstraint:
    """Compile `answer` against `fork`'s own options into a `ForkConstraint`
    -- pure and deterministic, never a second model call. `answer.option` is
    matched by label, case-insensitively; an unmatched or absent option
    contributes no drop/cap, only whatever free text was given. A temporal
    fork's DEC-62-default option therefore compiles to guidance alone,
    exactly as it should."""
    option = None
    if answer.option and answer.option.strip():
        wanted = answer.option.strip().casefold()
        option = next((o for o in fork.options if o.label.strip().casefold() == wanted), None)

    guidance_parts: list[str] = []
    drop: frozenset[str] = frozenset()
    cap: int | None = None
    if option is not None:
        drop = frozenset(option.drop_source_ids)
        cap = option.per_source_cap
        if option.guidance:
            guidance_parts.append(option.guidance)
    if answer.free_text and answer.free_text.strip():
        guidance_parts.append(answer.free_text.strip())

    return ForkConstraint(
        drop_source_ids=drop, per_source_cap=cap, guidance="\n".join(guidance_parts)
    )


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------


def _source_of(chunk_id: str) -> str:
    try:
        return source_id_from_chunk_id(chunk_id)
    except MalformedChunkIdError:
        return ""


def describe_effect(before: list[str], after: list[str]) -> dict[str, int]:
    """What a compiled constraint actually did to the assembled evidence
    set (§7.3's own disclosure requirement): notes and distinct sources
    before versus after the constraint's drop/cap were applied to the same
    trajectory. Pure counting -- no model call, no vault read."""
    before_sources = {_source_of(chunk_id) for chunk_id in before} - {""}
    after_sources = {_source_of(chunk_id) for chunk_id in after} - {""}
    return {
        "notes_before": len(before),
        "notes_after": len(after),
        "sources_before": len(before_sources),
        "sources_after": len(after_sources),
    }
