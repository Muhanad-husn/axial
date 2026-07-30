"""The instant-dismissal judge (specs/PHASE-B.md §10.0, §9.3, issue #491):
did the answer do a thing its case declares disqualifying on sight?

`instant_dismissal_criteria` is non-empty on all 21 sim cases and **nothing
in `src/` read it** before this module. It is the sharpest judged oracle the
case set holds -- a case states plainly what would get the paper rejected --
and it is also the cheapest, because a criterion is a single yes/no question
about the rendered answer rather than a rubric to grade against.

**It is NOT a sixth rung-3 gate** (§10.0): no violation rate has ever been
observed, and a threshold asserted before measurement would be a guess. The
number is computed, reported in the run report (§7.15) and gates nothing;
promotion follows §7.13's stated discipline.

**One call per criterion, under its own pass name, never the generating
model.** The judge runs as `axial.llm.INSTANT_DISMISSAL_PASS_NAME` and this
module raises `SelfGradingError` -- before any judge call is made -- when
that pass resolves to the same model as `SYNTHESIZE_PASS_NAME`, mirroring
`axial.gates.grounding`'s own guard. A model ruling on whether its own
answer is disqualified is not a check.

The judge reads the **rendered markdown answer** (§7.10), not the record:
a dismissal criterion is about what the analysis says and does, which is
exactly what the rendered answer is, and the record's JSON scaffolding would
only add noise to the question.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from axial.answer.render import render_markdown
from axial.llm import (
    INSTANT_DISMISSAL_PASS_NAME,
    SYNTHESIZE_PASS_NAME,
    LLMClient,
    LLMError,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json

_VIOLATION = "violation"
_NO_VIOLATION = "no_violation"
_VERDICTS = frozenset({_VIOLATION, _NO_VIOLATION})


class DismissalJudgeError(Exception):
    """Base class for all instant-dismissal judge errors."""


class SelfGradingError(DismissalJudgeError):
    """Raised when the dismissal judge's configured pass resolves to the
    SAME model as the synthesis pass -- the generating model must never rule
    on its own answer (§10.0, charter §2). Raised before any judge call is
    made; zero calls are made when this fires."""

    def __init__(self, judge_pass_name: str, model: str):
        self.judge_pass_name = judge_pass_name
        self.model = model
        super().__init__(
            f"the instant-dismissal judge (pass_name={judge_pass_name!r}) resolves to "
            f"model {model!r}, the SAME model as the synthesis pass "
            f"(pass_name={SYNTHESIZE_PASS_NAME!r}) -- self-grading: configure "
            "model_by_pass so the judge runs under a different model than the pass "
            "that generated the answer it is judging"
        )


class DismissalCheckFailedError(DismissalJudgeError):
    """Raised when the judge's own call fails (transport error, or a
    response that never parsed to a valid verdict)."""


@dataclass(frozen=True)
class DismissalResult:
    """How many of a case's criteria the answer violated, and which. `rate`
    is violations over criteria -- never inverted into a score, since §10.0
    reports a violation count, not a grade."""

    violations: int
    criteria_count: int
    violated_criteria: list[str]

    @property
    def rate(self) -> float | None:
        if self.criteria_count == 0:
            return None
        return self.violations / self.criteria_count


def _compose_judge_prompt(criterion: str, answer_text: str) -> str:
    return f"""You are the independent instant-dismissal judge of an analysis engine (specs/PHASE-B.md §10.0). You did NOT write this answer -- you are ruling on it against one disqualifying criterion an expert reader stated in advance.

The criterion, verbatim:
"{criterion}"

The analysis being judged:
"{answer_text}"

Decide: does this analysis do the thing the criterion declares disqualifying? Rule only on what the analysis actually says. An analysis that simply does not address the topic the criterion is about has not committed the violation.

Return ONLY this JSON object, no prose and no code fence:
{{"verdict": "violation"}} or {{"verdict": "no_violation"}}"""


def _parse_judge_response(raw: str, criterion: str) -> str:
    data = parse_model_json(raw)
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict not in _VERDICTS:
        raise DismissalCheckFailedError(
            f"instant-dismissal judge response for criterion {criterion[:60]!r} carries "
            f"no valid 'verdict' in {sorted(_VERDICTS)!r}: {data!r}"
        )
    return verdict


def judge_instant_dismissal(
    record: dict[str, Any],
    criteria: list[str],
    *,
    client: LLMClient,
    judge_pass_name: str = INSTANT_DISMISSAL_PASS_NAME,
) -> DismissalResult:
    """Judge the rendered answer for `record` against every criterion in
    `criteria`, one bounded call each.

    Raises `SelfGradingError` before any call when `judge_pass_name`
    resolves to the same model as `SYNTHESIZE_PASS_NAME`; raises
    `DismissalCheckFailedError` when a judge call or its response fails. An
    empty `criteria` list makes zero calls and reports a `None` rate rather
    than a vacuous 0 violations out of 0."""
    if not criteria:
        return DismissalResult(violations=0, criteria_count=0, violated_criteria=[])

    judge_model = client.model_for_pass(judge_pass_name)
    if judge_model == client.model_for_pass(SYNTHESIZE_PASS_NAME):
        raise SelfGradingError(judge_pass_name, judge_model)

    answer_text = render_markdown(record)
    violated: list[str] = []
    for criterion in criteria:
        prompt = _compose_judge_prompt(criterion, answer_text)
        try:
            raw = complete_json(client, prompt, pass_name=judge_pass_name)
        except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
            raise DismissalCheckFailedError(
                f"instant-dismissal judge call failed for criterion {criterion[:60]!r}: {exc}"
            ) from exc
        if _parse_judge_response(raw, criterion) == _VIOLATION:
            violated.append(criterion)

    return DismissalResult(
        violations=len(violated), criteria_count=len(criteria), violated_criteria=violated
    )
