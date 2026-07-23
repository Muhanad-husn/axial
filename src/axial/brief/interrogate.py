"""Brief interrogation pre-pass (Phase-B stage 1, specs/PHASE-B.md §7.2,
issue #252).

A bounded model pass over a loaded `Brief` (§7.1) that surfaces the
premises smuggled into a `case`/`request`, tests each against real corpus
coverage read from the vault query API (`axial.query.reader`), and reports
what the corpus can and cannot answer. The model proposes; it never decides
disposition. `disposition_for` -- a small, pure, table-driven function -- is
the single place that sets `disposition`, from the model's own
`premises_found`/`bounds_applied`/`refusal` fields, discarding any
`disposition` the model itself emitted (charter Principle III: the model is
not trusted to grade its own answer).

Coverage counts come from `axial.query.reader.coverage_count()`, never from
the model's recall of the corpus, and never from a free-text guess at which
polities a premise names: the prompt renders `coverage_count()`'s entire
real key set (§7.5's own small, deterministic result), plus the brief's
`case` unconditionally -- rendered at `0` when the corpus is silent on it
rather than omitted, since a case with zero coverage is itself a
first-class interrogation signal. See `render_coverage_section`'s own
docstring for why the earlier free-text-scan design was replaced.

On `refuse`, per §7.2, the run is COMPLETE: this module raises nothing
special for a refusal -- the CLI persists the result and exits 0 exactly as
on any other disposition, and simply never goes on to make a synthesis call
(no synthesis call exists in this slice to make in the first place).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from axial.brief.intake import Brief
from axial.llm import INTERROGATE_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_analyses_dir
from axial.query.reader import coverage_count

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
    refusal, disposition}`. `disposition` is always set by `disposition_for`,
    never read from the model's own answer."""

    premises_found: list[PremiseAssessment]
    bounds_applied: list[str]
    refusal: dict[str, Any] | None
    disposition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "premises_found": [
                {"premise": p.premise, "assessment": p.assessment} for p in self.premises_found
            ],
            "bounds_applied": list(self.bounds_applied),
            "refusal": self.refusal,
            "disposition": self.disposition,
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


def parse_interrogation_response(
    raw: str,
) -> tuple[list[PremiseAssessment], list[str], dict[str, Any] | None]:
    """Parse a raw model completion into the §7.2 fields the wrapper needs:
    `(premises_found, bounds_applied, refusal)`. The model's own
    `disposition` key, if present, is never read here -- the wrapper
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
    return premises_found, bounds_applied, refusal


def render_coverage_section(case: str, counts: dict[str, int]) -> str:
    """Render the corpus's REAL coverage as prompt text, one line per
    polity: every polity `counts` (`axial.query.reader.coverage_count()`'s
    own result) actually names, plus `case` unconditionally.

    No guessing from free text: `counts` already IS the corpus's real,
    deterministic key set, so showing it in full is both simpler and more
    honest than trying to spot which polities a premise names (a Title-Case
    text scan over `case`/`request` was tried and dropped -- issue #252
    review -- because it merges adjacent capitalized words into one wrong
    candidate, e.g. "Does Tunisia" instead of "Tunisia", and never matches
    an adjectival form like "Egyptian" against the corpus's own "Egypt"
    key; either failure fabricates a count instead of showing the real
    one). `case` is added even when `counts` does not name it -- rendered
    at `0`, never omitted -- because a case the corpus is silent on is
    itself a first-class interrogation signal (§7.2), not a gap to hide.
    Sorted by polity name for a deterministic prompt (`coverage_count`
    already returns ascending order; re-sorting here covers `case` too,
    however it interleaves)."""
    polities = dict(counts)
    polities.setdefault(case.strip(), 0)
    return "\n".join(f"- {polity}: {polities[polity]} chunks" for polity in sorted(polities))


def compose_prompt(brief: Brief, coverage_counts: dict[str, int]) -> str:
    """Assemble the interrogation prompt (§7.2): the brief's case, request,
    and lens, plus a coverage table of the corpus's real, full polity
    coverage (`render_coverage_section`), read straight from
    `coverage_counts` (the real `axial.query.reader.coverage_count()`
    result, not model recall, and not a free-text guess at which polities
    matter). The model is asked to surface every smuggled premise, judge it
    against the coverage table, state what the corpus can/cannot answer,
    and refuse only when the request cannot be answered as posed at all."""
    lens_line = (
        f'Lens: "{brief.lens}"'
        if brief.lens
        else "Lens: (none specified; the analysis stage will choose one)"
    )
    coverage_section = render_coverage_section(brief.case, coverage_counts)

    return f"""You are the brief-interrogation pre-pass of an analysis engine (specs/PHASE-B.md §7.2). Before any retrieval or synthesis runs, find every premise smuggled into this brief's case and request, and test each one against the corpus's REAL coverage below -- never against what you recall or assume about the world.

Case: "{brief.case}"
Request: "{brief.request}"
{lens_line}

Known corpus coverage (chunk count per polity, read from the vault query API -- a count of 0 means the corpus holds no chunk touching that polity, not that none was checked):
{coverage_section}

For every premise the case or request smuggles in (an assumption the brief takes for granted rather than states as a question), decide, from the coverage table above ONLY:
- "supports" -- the coverage plausibly sustains the premise.
- "contradicts" -- the coverage is too thin or absent (a 0 or near-0 count for the polity the premise depends on) to sustain the premise.
- "silent" -- the coverage table gives no clear evidence either way.

Also state any bound on what the corpus can/cannot answer for this brief (e.g. "covers X, not Y"), and refuse only when the request cannot be answered as posed at all given this coverage.

Return ONLY this JSON object, no prose and no code fence:
{{"premises_found": [{{"premise": "<premise text>", "assessment": "supports|contradicts|silent"}}], "bounds_applied": ["<statement of what the corpus can/cannot answer>", ...], "refusal": {{"reason": "<reason>"}} or null}}"""


def interrogate(
    brief: Brief,
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
) -> InterrogationResult:
    """Run the §7.2 interrogation pre-pass over `brief`: one bounded model
    call (`INTERROGATE_PASS_NAME`) over a prompt carrying real vault
    coverage counts, then the deterministic wrapper (`disposition_for`) sets
    `disposition` from the parsed fields.

    Raises `InterrogationFailedError` when the underlying model call
    transport-fails or never returns parseable JSON within `complete_json`'s
    bounded re-ask budget; raises `InterrogationParseError` (or its
    `InvalidAssessmentError` subclass) when the response parses as JSON but
    does not match the §7.2 shape -- both are named, immediately-fatal
    failures, never a silent `proceed`."""
    coverage_counts = coverage_count(vault_dir=vault_dir)
    prompt = compose_prompt(brief, coverage_counts)

    try:
        raw = complete_json(client, prompt, pass_name=INTERROGATE_PASS_NAME)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise InterrogationFailedError(f"interrogation call failed: {exc}") from exc

    premises_found, bounds_applied, refusal = parse_interrogation_response(raw)
    disposition = disposition_for(premises_found, bounds_applied, refusal)

    return InterrogationResult(
        premises_found=premises_found,
        bounds_applied=bounds_applied,
        refusal=refusal,
        disposition=disposition,
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
