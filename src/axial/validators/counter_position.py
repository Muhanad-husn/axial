"""Stage-5 counter-position validator (specs/PHASE-B.md §7.8, §7.9, §5 stage
5, issues #259 and #490).

Reads a persisted §7.3 analysis record and reports pass/fail, never editing
it -- same "never edits the record" contract as the attribution validator
(src/axial/validators/attribution.py). Two checks, run in this order:

1. **Contested predicate (mechanical), from what the notes say (D3).**
   Whether the brief is contested is determined from corpus signal, never
   the brief's wording (§7.8). The union of chunk-typed grounds cited across
   every claim ("this run's evidence", the same union §7.7's coverage map
   reads) is resolved through the query API and its interrogation answers
   inspected. Contested when either fires, checked in this order:
   - **opposed_positions** -- two grounds notes state different positions
     and one of them NAMES the other's side in its `arguing_against`: the
     other's stated position, the other's author, or a name the other note
     itself names. Matching is literal, through the alias map alone.
   - **gather_disagreement** -- a name this run both retrieved on and
     grounded a claim in carries a Gather disagreement section
     (`specs/PRODUCT.md` §7.18). A hint only, per D4: it decides that the
     brief is contested, never what gets cited.
   The fired signal (or `None` on an uncontested brief) is always recorded
   on the report.
2. **Presence-or-disclosure check (mechanical), on a contested brief only.**
   The record's `counter_position` section (§7.8, locked shape) must be
   either `present: true` with non-empty `grounds`, or `corpus_one_sided:
   true` with a non-empty `one_sided_reason`. Neither fails with
   `REASON_CONTESTED_WITHOUT_COUNTER_POSITION` and blocks release (§7.8: "a
   red flag, not a clean result").

**Why the `arguing_against` half carries the predicate, measured (#490,
2026-07-29).** The two clauses D3 names are not equal. `position_of` is free
text with 90% singletons and 76% of it answers "the author", so "positions
differ" is true of 99% of names and discriminates nothing; no count
threshold rescues it. `arguing_against` separates at 1.9x-2.4x over a 0.26
base rate, but **only when "names the other side" is implemented
literally** -- read loosely as "an `arguing_against` exists" it is a 1.00x
no-op. So the differing-positions clause is a guard against a note counting
as arguing with itself, and the literal naming is what fires.

**Two abstentions must never compare as different positions.** `[]` is an
answer and 19.3% of notes give it on `arguing_against`; only 4.9% abstain
there, and 23.6% abstain on `position_of`. The predicate applies
`axial.query.reader.is_abstention` -- 04's one shared predicate, imported,
never reimplemented -- before reading any answer.

**Recall is capped and that is a stated limit, not a bug.** The measurement
puts this predicate's recall at 0.35-0.59: a disagreement the corpus states
only implicitly is not seen. Contested stays a boolean anyway (two contracts
block on it, this validator's own presence check and #405's one-sided
outcome), so the validator requires a counter-position exactly where it sees
the disagreement, and nowhere else.

A **bounded model steelman-quality check**, anchored to the counter-position
`grounds` text and run under its own `pass_name` (never the generating
model), runs whenever the section itself is genuinely present (`present:
true` with non-empty `grounds`). It only reports (`SteelmanCheck.verdict`);
it never blocks release (§7.9).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from axial.llm import COUNTER_POSITION_PASS_NAME, SYNTHESIZE_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.query.names import (
    NameNotFoundError,
    as_string_list,
    canonical_name_for_surface,
    fold_surface_form,
    get_name,
)
from axial.query.reader import ChunkNotFoundError, ChunkNote, get_chunk, is_abstention
from axial.validators.coverage import coverage_scope

# The two contested signals this validator ever persists -- a fixed, small
# vocabulary (mirrors attribution.py's REASON_* constants), never open text.
SIGNAL_OPPOSED_POSITIONS = "opposed_positions"
SIGNAL_GATHER_DISAGREEMENT = "gather_disagreement"

# The one blocking reason this validator ever reports.
REASON_CONTESTED_WITHOUT_COUNTER_POSITION = "contested_without_counter_position"

# The steelman-quality judge's closed verdict vocabulary.
VERDICT_STEELMAN = "steelman"
VERDICT_STRAWMAN = "strawman"


class CounterPositionValidatorError(Exception):
    """Base class for all counter-position-validator errors."""


class CounterPositionCheckFailedError(CounterPositionValidatorError):
    """Raised when the bounded steelman-quality model call itself fails: a
    transport error, or a response that never parsed as usable JSON (or
    never carried a real verdict) within `complete_json`'s bounded re-ask
    budget."""


class SamePassModelError(CounterPositionValidatorError):
    """Raised when `steelman_pass_name` resolves (via
    `client.model_for_pass`) to the same model as `SYNTHESIZE_PASS_NAME` --
    mirrors `axial.validators.attribution.SamePassModelError` exactly: the
    steelman-quality check must never run under the model that generated the
    counter-position it is grading (§7.9, charter §2). Raised before any
    model call is made."""

    def __init__(self, pass_name: str, model: str):
        self.pass_name = pass_name
        self.model = model
        super().__init__(
            f"the steelman-quality check (pass_name={pass_name!r}) resolves to "
            f"model {model!r}, the SAME model as the synthesis pass "
            f"(pass_name={SYNTHESIZE_PASS_NAME!r}) -- configure model_by_pass "
            "so the steelman-quality check runs under a different model family "
            "than the pass that generated the counter-position it checks"
        )


@dataclass(frozen=True)
class ContestedResult:
    """Whether the brief is contested (§7.8), and which signal fired
    (`None` when uncontested). Persisted on the report regardless of
    pass/fail so the rule can be tuned on evidence."""

    contested: bool
    signal: str | None


@dataclass(frozen=True)
class SteelmanCheck:
    """The bounded steelman-quality check's outcome. `ran` is `False` (and
    `verdict`/`detail` are `None`) whenever the counter-position section
    itself is not genuinely present -- zero model calls in that case."""

    ran: bool
    verdict: str | None
    detail: str | None


@dataclass(frozen=True)
class CounterPositionFailure:
    """One failed mechanical check, with a human-readable detail."""

    reason: str
    detail: str


@dataclass(frozen=True)
class CounterPositionReport:
    """The validator's whole verdict. `passed` is `True` only when
    `failures` is empty -- the steelman check never contributes a failure,
    it only informs `steelman`."""

    passed: bool
    contested: ContestedResult
    failures: list[CounterPositionFailure]
    steelman: SteelmanCheck


def _evidence_chunk_ids(claims: list[Any]) -> list[str]:
    """The deduplicated, ordered set of chunk ids ("this run's evidence")
    cited across every claim's `grounds` -- the same union §7.7's coverage
    map reads to compute `evidence_note_count`. Artifact grounds are
    skipped: an artifact note carries no interrogation answers."""
    seen: dict[str, None] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for entry in claim.get("grounds") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("ref_type") == "chunk":
                ref_id = entry.get("ref_id")
                if isinstance(ref_id, str) and ref_id:
                    seen[ref_id] = None
    return list(seen)


def resolve_grounds_notes(claims: list[Any], *, vault_dir: Path | None) -> list[ChunkNote]:
    """This run's grounds notes, in first-seen citation order. A chunk id
    that fails to resolve is skipped: grounds-resolution failures are the
    attribution validator's own job (§7.9), not this one's."""
    notes: list[ChunkNote] = []
    for chunk_id in _evidence_chunk_ids(claims):
        try:
            notes.append(get_chunk(chunk_id, vault_dir=vault_dir))
        except ChunkNotFoundError:
            continue
    return notes


def stated_position(note: ChunkNote) -> str | None:
    """A note's own stated position, across issue #496's mixed frame: its
    `position` answer where it has one, its `position_of` answer otherwise
    (§7.5/§7.15). An abstention (all three forms) is not an answer and never
    stands in for one, so two abstaining notes never compare as two
    different positions -- the manufactured-disagreement failure D3's own
    measurement warns about. `None` when the note states no position at
    all."""
    for value in (note.position, note.position_of):
        if value is None or is_abstention(value):
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _opposition_surfaces(note: ChunkNote) -> list[str]:
    """The surface forms a note says it argues against (§7.15's
    `arguing_against`), abstentions dropped. `[]` -- the answer that the
    passage names no opponent, given by 19.3% of the corpus -- yields no
    surfaces, exactly as it should, and is never read as an abstention."""
    if is_abstention(note.arguing_against):
        return []
    return as_string_list(note.arguing_against)


def _side_of(note: ChunkNote, *, names_dir: Path | None) -> tuple[set[str], set[str]]:
    """What names this note's side, as §7.8 puts it: "the other's position,
    its author, or a name that side is a member of".

    Returns `(folded_literals, canonicals)` -- the folded strings that name
    the side directly (its stated position and its source's author) and the
    canonical names the note itself names, which are the pages the note is a
    member of. Canonical resolution is through the alias map alone
    (`canonical_name_for_surface`), never `find_names`' embedding tier: a
    nearest-neighbour hit here would manufacture an opposition the corpus
    never stated, the same rule §7.4 applies to `names_touched`."""
    literals: set[str] = set()
    position = stated_position(note)
    if position:
        literals.add(fold_surface_form(position))
    author = (note.source_meta or {}).get("author")
    if isinstance(author, str) and author.strip():
        literals.add(fold_surface_form(author))
        canonical = canonical_name_for_surface(author.strip(), names_dir=names_dir)
        if canonical:
            literals.add(fold_surface_form(canonical))

    canonicals: set[str] = set()
    if not is_abstention(note.names):
        for entry in note.names if isinstance(note.names, list) else []:
            surface = entry.get("name") if isinstance(entry, dict) else entry
            if not isinstance(surface, str) or not surface.strip():
                continue
            resolved = canonical_name_for_surface(surface.strip(), names_dir=names_dir)
            if resolved:
                canonicals.add(resolved)
    return literals, canonicals


def _names_the_other_side(arguer: ChunkNote, other: ChunkNote, *, names_dir: Path | None) -> bool:
    """Whether `arguer`'s `arguing_against` LITERALLY names `other`'s side.
    Loose reading -- "an `arguing_against` exists" -- is a measured 1.00x
    no-op, so nothing here settles for one."""
    literals, canonicals = _side_of(other, names_dir=names_dir)
    for surface in _opposition_surfaces(arguer):
        folded = fold_surface_form(surface)
        if folded in literals:
            return True
        resolved = canonical_name_for_surface(surface, names_dir=names_dir)
        if resolved is not None and (
            resolved in canonicals or fold_surface_form(resolved) in literals
        ):
            return True
    return False


def _different_sides(first: ChunkNote, second: ChunkNote) -> bool:
    """Whether two grounds notes are two sides at all, rather than one
    passage's argument with itself.

    Two notes are different sides when their stated positions differ, or
    when they come from different sources. The second disjunct is what makes
    the first usable on the real corpus: 76% of notes answer `position_of`
    with "the author", and "the author" of one book is a different person
    from "the author" of another, so comparing those two strings for
    inequality would throw away the corpus's most common disagreement
    shape."""
    if first.chunk_id == second.chunk_id:
        return False
    first_position = stated_position(first)
    second_position = stated_position(second)
    if first_position and second_position and first_position != second_position:
        return True
    return _source_of(first) != _source_of(second)


def _source_of(note: ChunkNote) -> str:
    """A note's source, for the different-sides test. `source_meta`'s own
    author/title, not a chunk-id parse: the id's `source_id` seam and the
    author are the same fact here, and `source_meta` is what a name page's
    member lines already show."""
    meta = note.source_meta or {}
    return f"{meta.get('author')}|{meta.get('title')}"


def opposed_grounds_notes(
    notes: list[ChunkNote], *, names_dir: Path | None = None
) -> list[ChunkNote]:
    """§7.8 path 1, as a list rather than a verdict: every grounds note on
    either side of a stated opposition -- the note whose `arguing_against`
    names another's side, and the note it names -- in first-seen citation
    order, deduplicated.

    Both sides are returned because both are the disagreement. The
    counter-position whitelist (`axial.analyze.synthesis`) offers them to the
    model, which decides which one opposes the primary claims; the predicate
    below only needs to know the list is non-empty. One function, so the
    generator and the gate that checks it can never disagree about what a
    stated opposition is (issue #399)."""
    opposed: dict[str, ChunkNote] = {}
    for arguer in notes:
        if not _opposition_surfaces(arguer):
            continue
        for other in notes:
            if not _different_sides(arguer, other):
                continue
            if _names_the_other_side(arguer, other, names_dir=names_dir):
                opposed.setdefault(arguer.chunk_id, arguer)
                opposed.setdefault(other.chunk_id, other)
    return list(opposed.values())


def _gather_disagreement_at(
    names: list[str], *, vault_dir: Path | None, names_dir: Path | None = None
) -> bool:
    """§7.8 path 2: one of `names` carries a Gather disagreement section.
    A retrieval hint, never a citation (D4). Reads only `page.disagreement`,
    parsed off the page's whole body regardless of `limit` (issue #505) --
    the default `get_name` cap on `members` is irrelevant here, unlike
    `axial.validators.coverage._evidence_note_count`, which reads members."""
    for canonical in names:
        try:
            page = get_name(canonical, vault_dir=vault_dir, names_dir=names_dir)
        except NameNotFoundError:
            continue
        if page.disagreement is not None:
            return True
    return False


def detect_contested(
    claims: list[Any],
    trajectory: list[dict[str, Any]] | None = None,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> ContestedResult:
    """The §7.8 contested predicate over the record's own resolved evidence
    -- never the brief's wording. Public because
    `axial.analyze.synthesis.generate_counter_position` reuses it VERBATIM
    (issue #399): two implementations of "is this contested" would let the
    generator and the gate that checks it disagree.

    Path 2's name set is the §7.7 coverage scope (`coverage_scope`): the
    names this run retrieved on that a claim's grounds note is a member of.
    Not every name in `names_touched` -- a real evidence set's notes name
    423 distinct canonicals on average, mostly one-off mentions, and a Gather
    finding at a name the answer merely brushed past says nothing about
    whether the answer is contested."""
    notes = resolve_grounds_notes(claims, vault_dir=vault_dir)
    if opposed_grounds_notes(notes, names_dir=names_dir):
        return ContestedResult(contested=True, signal=SIGNAL_OPPOSED_POSITIONS)
    scope = coverage_scope([c for c in claims if isinstance(c, dict)], trajectory or [])
    if _gather_disagreement_at(scope, vault_dir=vault_dir, names_dir=names_dir):
        return ContestedResult(contested=True, signal=SIGNAL_GATHER_DISAGREEMENT)
    return ContestedResult(contested=False, signal=None)


def _is_present_with_grounds(counter_position: dict[str, Any]) -> bool:
    grounds = counter_position.get("grounds")
    return counter_position.get("present") is True and isinstance(grounds, list) and bool(grounds)


def _is_disclosed_one_sided(counter_position: dict[str, Any]) -> bool:
    reason = counter_position.get("one_sided_reason")
    return counter_position.get("corpus_one_sided") is True and bool(
        isinstance(reason, str) and reason.strip()
    )


def _check_presence_or_disclosure(
    counter_position: dict[str, Any],
) -> CounterPositionFailure | None:
    """The §7.8 mechanical presence-or-disclosure check, called only on a
    contested brief. `present: true` with empty `grounds` is not a real
    counter-position (a stance with no grounds), and `corpus_one_sided: true`
    with an empty/absent reason is not a real disclosure -- both fail
    exactly as absence would."""
    if _is_present_with_grounds(counter_position) or _is_disclosed_one_sided(counter_position):
        return None
    return CounterPositionFailure(
        reason=REASON_CONTESTED_WITHOUT_COUNTER_POSITION,
        detail=(
            "the brief is contested and the record's counter_position section is "
            "neither present with non-empty grounds nor disclosed as corpus "
            "one-sided with a reason (§7.8)"
        ),
    )


def _compose_steelman_prompt(counter_position: dict[str, Any], grounds_texts: list[str]) -> str:
    lines = "\n".join(f"- {text}" for text in grounds_texts) or "(no grounds text resolved)"
    stance = counter_position.get("stance") or ""
    return f"""You are the independent steelman-quality check of an analysis engine's stage-5 counter-position validator (specs/PHASE-B.md §7.9). You are NOT the model that generated this counter-position -- you are judging its quality.

The counter-position's stated stance:
"{stance}"

The corpus grounds it cites:
{lines}

Judge whether this stance represents the opposing school at its STRONGEST (a steelman), grounded in the cited material, or whether it is a weakened, dismissible version of the opposing view (a strawman).

Return ONLY this JSON object, no prose and no code fence:
{{"verdict": "steelman" or "strawman", "detail": "<one sentence why>"}}"""


def _resolve_grounds_text(grounds: list[Any], *, vault_dir: Path | None) -> list[str]:
    """Best-effort chunk text for every chunk-typed grounds entry, anchoring
    the steelman judge to real corpus material (§7.9). A grounds pointer
    that fails to resolve is skipped -- grounds resolution is the
    attribution validator's own job, not this check's."""
    texts: list[str] = []
    for entry in grounds:
        if not isinstance(entry, dict) or entry.get("ref_type") != "chunk":
            continue
        ref_id = entry.get("ref_id")
        if not isinstance(ref_id, str) or not ref_id:
            continue
        try:
            chunk = get_chunk(ref_id, vault_dir=vault_dir)
        except ChunkNotFoundError:
            continue
        texts.append(chunk.chunk_text)
    return texts


def _run_steelman_check(
    counter_position: dict[str, Any],
    *,
    client: LLMClient,
    vault_dir: Path | None,
    steelman_pass_name: str,
) -> SteelmanCheck:
    synthesis_model = client.model_for_pass(SYNTHESIZE_PASS_NAME)
    steelman_model = client.model_for_pass(steelman_pass_name)
    if steelman_model == synthesis_model:
        raise SamePassModelError(steelman_pass_name, steelman_model)

    grounds_texts = _resolve_grounds_text(
        counter_position.get("grounds") or [], vault_dir=vault_dir
    )
    prompt = _compose_steelman_prompt(counter_position, grounds_texts)
    try:
        raw = complete_json(client, prompt, pass_name=steelman_pass_name)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise CounterPositionCheckFailedError(f"steelman-quality check call failed: {exc}") from exc

    data = parse_model_json(raw)
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict not in {VERDICT_STEELMAN, VERDICT_STRAWMAN}:
        raise CounterPositionCheckFailedError(
            f"steelman-quality response is missing a valid 'verdict': {data!r}"
        )
    detail = data.get("detail") if isinstance(data.get("detail"), str) else ""
    return SteelmanCheck(ran=True, verdict=verdict, detail=detail)


def validate_counter_position(
    record: dict[str, Any],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
    steelman_pass_name: str = COUNTER_POSITION_PASS_NAME,
) -> CounterPositionReport:
    """Validate `record`'s §7.8 counter-position section against its own
    claim-graph evidence. Never edits `record` -- returns a report, nothing
    more.

    1. Detects contested-ness (`ContestedResult`) from the evidence resolved
       out of `record["claims"]`'s grounds and the names its
       `record["trajectory"]` retrieved on.
    2. On a contested brief only, checks the section is present-with-grounds
       or disclosed-one-sided-with-reason; failing both is
       `REASON_CONTESTED_WITHOUT_COUNTER_POSITION` and blocks release.
    3. Runs the bounded steelman-quality check whenever the section is
       genuinely present-with-grounds, regardless of contested-ness --
       zero model calls otherwise.
    """
    claims = record.get("claims") or []
    contested = detect_contested(
        claims,
        record.get("trajectory") or [],
        vault_dir=vault_dir,
        names_dir=names_dir,
    )

    counter_position = record.get("counter_position") or {}
    failures: list[CounterPositionFailure] = []
    if contested.contested:
        failure = _check_presence_or_disclosure(counter_position)
        if failure is not None:
            failures.append(failure)

    steelman = SteelmanCheck(ran=False, verdict=None, detail=None)
    if _is_present_with_grounds(counter_position):
        steelman = _run_steelman_check(
            counter_position,
            client=client,
            vault_dir=vault_dir,
            steelman_pass_name=steelman_pass_name,
        )

    return CounterPositionReport(
        passed=not failures, contested=contested, failures=failures, steelman=steelman
    )


def format_counter_position_report(report: CounterPositionReport) -> str:
    """Render `report` as human-readable text for the CLI (`axial brief
    validate`): the contested verdict + signal, a one-line pass/fail
    verdict plus one line per failure, and the steelman-quality verdict
    when the check ran."""
    lines = [
        f"counter-position validator: contested={report.contested.contested} "
        f"signal={report.contested.signal!r}"
    ]
    if report.passed:
        lines.append("counter-position validator: PASS (0 failures)")
    else:
        lines.append(f"counter-position validator: FAIL ({len(report.failures)} failure(s))")
        for failure in report.failures:
            lines.append(f"  {failure.reason} -- {failure.detail}")
    if report.steelman.ran:
        lines.append(
            f"counter-position validator: steelman-quality={report.steelman.verdict} "
            f"({report.steelman.detail})"
        )
    return "\n".join(lines)
