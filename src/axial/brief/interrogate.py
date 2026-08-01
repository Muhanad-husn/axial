"""Brief interrogation pre-pass (Phase-B stage 1, specs/PHASE-B.md §7.2,
issue #252).

A bounded model pass over a loaded `Brief` (§7.1) that surfaces the
premises smuggled into a `case`/`request`, tests each against the corpus
coverage it is shown, and reports what the corpus can and cannot answer. The
model proposes; it never decides disposition. `disposition_for` -- a small,
pure, table-driven function -- is the single place that sets `disposition`,
from the model's own `premises_found`/`bounds_applied`/`refusal` fields,
discarding any `disposition` the model itself emitted (charter Principle III:
the model is not trusted to grade its own answer).

**The pre-pass shows no coverage table yet, and the prompt says so plainly
(§7.2, issue #487).** The §7.7 coverage map is per-name and scoped to the
brief's own resolved names; resolving them is the retrieval loop's job (issue
#488), which passes a scoped map through `compose_prompt`'s unchanged table
path. Rendering the whole name index instead was measured at 62,821 rows /
2.08 MB / ~500k tokens plus a 37-63s whole-vault read on every `axial brief
run` (`data/logs/2026-07-30-name-query-487/`), and under the retired
per-polity facet the table was empty on every real run anyway -- so showing
nothing is what the engine actually did, minus the cost. What must not happen
is a prompt that promises real coverage and then shows an empty table: absence
read as zero coverage produces false refusals, the same failure mode the
fabricated `case` row produced below. `_NO_COVERAGE_TABLE` states the absence
and its reason instead.

A row is never synthesized for the brief's `case` itself. An earlier version
injected the brief's raw `case` string as its own row (at `0` when it
didn't already appear in `counts`), meaning to flag a place the corpus has
never heard of; in practice nearly every real `case` bundles a place with a
date range ("Syria, 2011-2024"), the coverage table has no time dimension
at all, and that phrase almost never byte-for-byte matches a bare corpus
key -- so the fabricated row fired as a false "zero coverage" signal on
almost every real brief, producing false refusals (issue root-caused
2026-07-23). See `render_coverage_section`'s own docstring for the current,
simpler behavior, and `compose_prompt`'s prompt text for how the model is
told to map a case's name onto the table's real rows itself when there is
one.

On `refuse`, per §7.2, the run is COMPLETE: this module raises nothing
special for a refusal -- the CLI persists the result and exits 0 exactly as
on any other disposition, and simply never goes on to make a synthesis call
(no synthesis call exists in this slice to make in the first place).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from axial.brief.intake import Brief
from axial.llm import INTERROGATE_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_analyses_dir

# The §7.2 assessment vocabulary -- closed, not open text: a value outside
# this set is a named parse error, never silently accepted or coerced.
ASSESSMENTS = frozenset({"supports", "contradicts", "silent"})

# The §7.2 disposition vocabulary -- exactly one of these three is always
# set by `disposition_for`, never null/absent.
DISPOSITIONS = frozenset({"proceed", "proceed_bounded", "refuse"})


class InterrogationError(Exception):
    """Base class for all brief-interrogation errors."""


class InterrogationParseError(InterrogationError):
    """Raised when a well-formed-JSON model response does not match the
    §7.2 interrogation-result shape (a missing/mistyped field, a
    non-object entry, a blank premise text, a malformed `refusal`)."""


class InvalidAssessmentError(InterrogationParseError):
    """Raised when a `premises_found` entry's `assessment` is outside
    `ASSESSMENTS` -- a named, immediately-fatal error, never a silent
    pass-through (the P0-6 schema-gap precedent `axial.tag` already
    follows: a vocabulary miss is not smoothed over by a bounded re-ask)."""

    def __init__(self, assessment: Any):
        self.assessment = assessment
        super().__init__(
            f"premises_found entry has assessment {assessment!r}, expected one of "
            f"{sorted(ASSESSMENTS)!r}"
        )


class InterrogationFailedError(InterrogationError):
    """Raised when the interrogation model call itself fails: a transport
    error, or a response that never parsed as usable JSON even after
    `complete_json`'s bounded re-ask budget. Never a silent `proceed`."""


@dataclass(frozen=True)
class PremiseAssessment:
    """One `premises_found` entry (§7.2): the premise text and the corpus's
    verdict on it, one of `ASSESSMENTS`."""

    premise: str
    assessment: str


@dataclass(frozen=True)
class InterrogationResult:
    """The §7.2 interrogation result: `{premises_found[], bounds_applied[],
    refusal, disposition, question_scope}`. `disposition` is always set by
    `disposition_for`, never read from the model's own answer.

    `question_scope` (§7.2, §7.4) is the period and/or setting the QUESTION
    ITSELF states -- read from the brief's own `case`/`request` text, never
    inferred from what the corpus covers -- so synthesis can state it as a
    soft preference rather than reopening a second read of the same brief.
    `None` when the question states neither (the honest, common case for an
    open request); a `{"period": ..., "setting": ...}` dict, each half
    independently `None` when the question states only the other, when it
    states either. Never a guess: an unscoped question abstains here exactly
    as a `refusal`-free brief abstains from `bounds_applied`."""

    premises_found: list[PremiseAssessment]
    bounds_applied: list[str]
    refusal: dict[str, Any] | None
    disposition: str
    question_scope: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "premises_found": [
                {"premise": p.premise, "assessment": p.assessment} for p in self.premises_found
            ],
            "bounds_applied": list(self.bounds_applied),
            "refusal": self.refusal,
            "disposition": self.disposition,
            "question_scope": self.question_scope,
        }


def disposition_for(
    premises_found: list[PremiseAssessment],
    bounds_applied: list[str],
    refusal: dict[str, Any] | None,
) -> str:
    """The deterministic wrapper (§7.2): sets `disposition` from the parsed
    fields, never from anything the model itself proposed. Total -- always
    returns exactly one of `DISPOSITIONS`.

    Precedence: a non-null `refusal` always wins (`refuse`); otherwise any
    `contradicts` premise, or a non-empty `bounds_applied`, means the run
    may proceed but not without qualification (`proceed_bounded`); only a
    brief with no contradicted premise and no stated bound proceeds clean
    (`proceed`)."""
    if refusal is not None:
        return "refuse"
    if any(p.assessment == "contradicts" for p in premises_found):
        return "proceed_bounded"
    if bounds_applied:
        return "proceed_bounded"
    return "proceed"


def _parse_premises_found(raw: Any) -> list[PremiseAssessment]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InterrogationParseError(f"premises_found must be a list, got {type(raw).__name__}")
    premises: list[PremiseAssessment] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise InterrogationParseError(
                f"premises_found entry must be an object, got {type(entry).__name__}"
            )
        premise = entry.get("premise")
        if not isinstance(premise, str) or not premise.strip():
            raise InterrogationParseError(
                f"premises_found entry has a missing/blank premise: {entry!r}"
            )
        assessment = entry.get("assessment")
        if assessment not in ASSESSMENTS:
            raise InvalidAssessmentError(assessment)
        premises.append(PremiseAssessment(premise=premise.strip(), assessment=assessment))
    return premises


def _parse_bounds_applied(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InterrogationParseError(f"bounds_applied must be a list, got {type(raw).__name__}")
    bounds: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise InterrogationParseError(
                f"bounds_applied entry must be a non-empty string, got {entry!r}"
            )
        bounds.append(entry.strip())
    return bounds


def _parse_refusal(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InterrogationParseError(
            f"refusal must be an object or null, got {type(raw).__name__}"
        )
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise InterrogationParseError(f"refusal is missing a non-empty reason: {raw!r}")
    return {"reason": reason.strip()}


def _parse_question_scope(raw: Any) -> dict[str, Any] | None:
    """Parse the §7.2 `question_scope` field: the period and/or setting the
    QUESTION ITSELF states, read from the brief's own text -- never a guess
    at what the corpus covers, and never invented when the question states
    neither. `None` (the model's own `null`, or a `{"period": null,
    "setting": null}` object that says the same thing the long way) collapses
    to the one abstention shape every caller checks, mirroring `_parse_refusal`'s
    own null-is-the-honest-default convention for this same pre-pass."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InterrogationParseError(
            f"question_scope must be an object or null, got {type(raw).__name__}"
        )
    period = raw.get("period")
    setting = raw.get("setting")
    for field_name, value in (("period", period), ("setting", setting)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise InterrogationParseError(
                f"question_scope.{field_name} must be a non-blank string or null: {raw!r}"
            )
    period = period.strip() if isinstance(period, str) else None
    setting = setting.strip() if isinstance(setting, str) else None
    if period is None and setting is None:
        return None
    return {"period": period, "setting": setting}


def parse_interrogation_response(
    raw: str,
) -> tuple[list[PremiseAssessment], list[str], dict[str, Any] | None, dict[str, Any] | None]:
    """Parse a raw model completion into the §7.2 fields the wrapper needs:
    `(premises_found, bounds_applied, refusal, question_scope)`. The model's
    own `disposition` key, if present, is never read here -- the wrapper
    (`disposition_for`) is the sole source of that field (issue #252's
    ratified rule).

    Raises `ModelJsonError` (from `parse_model_json`) when `raw` is not
    parseable JSON at all, or `InterrogationParseError` (`InvalidAssessmentError`
    for an out-of-vocabulary `assessment`) when it parses but does not match
    the §7.2 shape. Never returns a partial result alongside an error."""
    data = parse_model_json(raw)
    if not isinstance(data, dict):
        raise InterrogationParseError(
            f"interrogation response must be a JSON object, got {type(data).__name__}"
        )
    premises_found = _parse_premises_found(data.get("premises_found"))
    bounds_applied = _parse_bounds_applied(data.get("bounds_applied"))
    refusal = _parse_refusal(data.get("refusal"))
    question_scope = _parse_question_scope(data.get("question_scope"))
    return premises_found, bounds_applied, refusal, question_scope


def render_coverage_section(counts: dict[str, int]) -> str:
    """Render the corpus's REAL coverage as prompt text, one line per name
    `counts` (`axial.query.names.coverage_count()`'s own result) actually
    names -- nothing else. Sorted by name for a deterministic prompt
    (`coverage_count` already returns ascending order; re-sorting here is
    belt-and-suspenders). Live code, not dead: #488 passes it the map scoped
    to a brief's own resolved names.

    Earlier versions also injected a row for the brief's raw `case`
    string, at `0` when it wasn't already one of `counts`' keys, meaning
    to flag a place the corpus has never heard of. That was dropped: a
    real `case` almost always bundles a place with a date range (e.g.
    "Syria, 2011-2024"), the coverage table has no time dimension to
    speak to at all, and the bundled phrase essentially never
    byte-for-byte matches a bare corpus key -- so the fabricated row fired
    as a false "zero coverage" signal on nearly every real brief, not as a
    rare true positive. There is no cheap way to strip the date
    qualifier and reliably recover the bare place name from free text (a
    Title-Case scan was tried for a related problem -- see the coverage
    table's own git history -- and merges/misses in exactly this way); the
    model is asked instead to map the case's place name(s) onto this
    table's real rows itself (`compose_prompt`'s added guidance line),
    the same kind of judgment the rest of the pipeline already trusts it
    to make."""
    return "\n".join(f"- {name}: {counts[name]} notes" for name in sorted(counts))


# What the prompt says in place of a coverage table when there is none, and
# why. **The prompt must not promise a table and then show nothing** -- an
# empty table under a "here is the corpus's REAL coverage" heading invites the
# model to read absence as zero coverage and refuse, which is the same false
# signal the fabricated `case` row produced (see `render_coverage_section`).
_NO_COVERAGE_TABLE = (
    "No coverage table is available at this corpus pin. The table is per-name "
    "(specs/PHASE-B.md §7.7) and is scoped to the names this brief is about, "
    "and this pre-pass does not resolve those names yet (issue #488). Absence "
    "of a table here says NOTHING about what the corpus holds: judge every "
    'premise "silent" unless the brief\'s own text settles it, and do not '
    "refuse for lack of coverage evidence you were not shown."
)

# The mapping guidance only makes sense when there are rows to map onto.
_COVERAGE_MAPPING_GUIDANCE = (
    "This table counts notes per name only -- it has no time/period dimension. "
    'A date or period qualifier in the case (e.g. "2011-2024") is not something '
    "this table can confirm or deny; map the name(s) the case and request name, "
    "however phrased, to their corresponding row above yourself -- do not expect "
    "an exact string match."
)


def compose_prompt(brief: Brief, coverage_counts: dict[str, int]) -> str:
    """Assemble the interrogation prompt (§7.2): the brief's case, request,
    and lens, plus a coverage table read straight from `coverage_counts`
    (real counts, never model recall and never a free-text guess at which
    names matter). The model is asked to surface every smuggled premise,
    judge it against the coverage table, state what the corpus can/cannot
    answer, and refuse only when the request cannot be answered as posed at
    all.

    `coverage_counts` empty is a first-class case, not a degenerate one: the
    §7.7 map is scoped to the brief's own resolved names and this pre-pass
    does not resolve them yet (issue #488), so the prompt says so plainly
    (`_NO_COVERAGE_TABLE`) instead of printing an empty table under a heading
    that promises real coverage. The table path is unchanged and stays under
    test -- #488 passes a scoped map through it."""
    lens_line = (
        f'Lens: "{brief.lens}"'
        if brief.lens
        else "Lens: (none specified; the analysis stage will choose one)"
    )
    if coverage_counts:
        coverage_heading = (
            "Known corpus coverage (note count per name, read from the vault query "
            "API -- a count of 0 means the corpus holds no note naming that name, "
            "not that none was checked):"
        )
        coverage_block = render_coverage_section(coverage_counts)
        mapping_guidance = _COVERAGE_MAPPING_GUIDANCE
        premise_basis = "from the coverage table above ONLY"
        contradicts_rule = (
            '- "contradicts" -- the coverage is too thin or absent (a 0 or near-0 '
            "count for the name the premise depends on) to sustain the premise."
        )
    else:
        coverage_heading = "Corpus coverage:"
        coverage_block = _NO_COVERAGE_TABLE
        mapping_guidance = ""
        premise_basis = "from the corpus-coverage statement above ONLY"
        contradicts_rule = (
            '- "contradicts" -- coverage you were shown is too thin or absent to '
            "sustain the premise. With no coverage table, this does not apply."
        )

    return f"""You are the brief-interrogation pre-pass of an analysis engine (specs/PHASE-B.md §7.2). Before any retrieval or synthesis runs, find every premise smuggled into this brief's case and request, and test each one against the corpus coverage stated below -- never against what you recall or assume about the world.

Case: "{brief.case}"
Request: "{brief.request}"
{lens_line}

{coverage_heading}
{coverage_block}
{mapping_guidance}
For every premise the case or request smuggles in (an assumption the brief takes for granted rather than states as a question), decide, {premise_basis}:
- "supports" -- the coverage plausibly sustains the premise.
{contradicts_rule}
- "silent" -- the coverage stated above gives no clear evidence either way.

Also state any bound on what the corpus can/cannot answer for this brief (e.g. "covers X, not Y"), and refuse only when the request cannot be answered as posed at all given this coverage.

Also state the scope the QUESTION ITSELF names -- its period and its setting -- read from the case and request text alone, never inferred from what the corpus covers or from what you know about the world. State only what the question's own words establish; if it names no period, or no setting, or neither, say so plainly (null) rather than inferring one.

Return ONLY this JSON object, no prose and no code fence:
{{"premises_found": [{{"premise": "<premise text>", "assessment": "supports|contradicts|silent"}}], "bounds_applied": ["<statement of what the corpus can/cannot answer>", ...], "refusal": {{"reason": "<reason>"}} or null, "question_scope": {{"period": "<stated period, or null>", "setting": "<stated setting, or null>"}} or null}}"""


def interrogate(
    brief: Brief,
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
) -> InterrogationResult:
    """Run the §7.2 interrogation pre-pass over `brief`: one bounded model
    call (`INTERROGATE_PASS_NAME`), then the deterministic wrapper
    (`disposition_for`) sets `disposition` from the parsed fields.

    **The prompt carries no coverage table yet, and says so (§7.2, issue
    #487).** The §7.7 map is per-name and scoped to the brief's own resolved
    names, which this pre-pass does not resolve; issue #488 does, and passes
    a scoped map through `compose_prompt`'s unchanged table path. Feeding the
    whole name index instead was measured at 62,821 rows / 2.08 MB / ~500k
    tokens plus a 37-63s whole-vault read on every run
    (`data/logs/2026-07-30-name-query-487/`), and against the tag-era vault
    this table was empty on every real run anyway -- so passing nothing is
    what the engine actually did, without the cost or the false precision.

    `vault_dir` is kept in the signature: every caller already passes it, and
    #488's scoped read needs it back.

    **`question_scope` is read for free off the same call.** This pass
    already reads the brief's `case`/`request` to find smuggled premises, so
    it also extracts the period and/or setting the question ITSELF states --
    never the corpus's coverage of one -- for synthesis to carry as a soft
    preference (§7.4). `None` when the question states neither; abstention,
    not a guess, is the correct answer for an unscoped question.

    Raises `InterrogationFailedError` when the underlying model call
    transport-fails or never returns parseable JSON within `complete_json`'s
    bounded re-ask budget; raises `InterrogationParseError` (or its
    `InvalidAssessmentError` subclass) when the response parses as JSON but
    does not match the §7.2 shape -- both are named, immediately-fatal
    failures, never a silent `proceed`."""
    print(f"interrogate: starting for brief case={brief.case!r}", file=sys.stderr)
    prompt = compose_prompt(brief, {})

    try:
        raw = complete_json(client, prompt, pass_name=INTERROGATE_PASS_NAME)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise InterrogationFailedError(f"interrogation call failed: {exc}") from exc

    premises_found, bounds_applied, refusal, question_scope = parse_interrogation_response(raw)
    disposition = disposition_for(premises_found, bounds_applied, refusal)

    print(f"interrogate: done, disposition={disposition}", file=sys.stderr)
    return InterrogationResult(
        premises_found=premises_found,
        bounds_applied=bounds_applied,
        refusal=refusal,
        disposition=disposition,
        question_scope=question_scope,
    )


def persist_interrogation(
    brief: Brief,
    result: InterrogationResult,
    *,
    analyses_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> Path:
    """Persist `result` to `<analyses_dir>/<brief_id>.json` (§7.3's eventual
    home for the full analysis record; this slice writes only the
    `interrogation` block it owns, per issue #252's own scope). Keyed
    deterministically on `brief.brief_id` -- re-running the same brief
    overwrites the same file rather than accumulating one per run."""
    if analyses_dir is None:
        analyses_dir = default_analyses_dir(config_path)
    analyses_dir = Path(analyses_dir)
    analyses_dir.mkdir(parents=True, exist_ok=True)
    path = analyses_dir / f"{brief.brief_id}.json"
    payload = {"brief_id": brief.brief_id, "interrogation": result.to_dict()}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
