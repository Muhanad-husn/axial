"""The post-draft shape check (specs/PHASE-C.md §7.16, issue #578).

**One model call, after all section drafts complete, comparing the rendered
prose against the plan the same run produced.** The arc-planning stage
(`axial.paper.plan`) already emits a `thesis_statement` and a section list
where every section carries one role from a closed vocabulary -- `setup`,
`claim`, `evidence`, `counter-position`, `synthesis`. That plan is the paper's
stated intent, and this check asks only whether the drafted prose delivered
it: a conformance question, not an open-ended "is this good".

**It reports; it never blocks.** The result is one of `strong`, `adequate`,
`weak`, with at least one named defect whenever the band is not `strong` --
`parse_shape_response` treats a `weak`/`adequate` verdict with an empty
defect list as a parse error, never a silent pass. But the band itself never
raises: `run_shape_check` writes whatever band the judge returns onto the
record, and `axial paper draft` decides what to do with a `weak` one (exit
non-zero, still write the files). Nothing here gates release, and nothing
here is the reviewer panel (§3 non-goal 9): a panel is N >= 3 sealed
reviewers from a different vendor, run offline over a sample; this is one
call, on the per-run path, that reports and moves on.

**It runs on a different model than the drafter**, reusing the self-grading
guard `axial.gates.grounding` already carries for its own judge, re-anchored
from the synthesis pass to `PAPER_DRAFT_PASS_NAME`: the model that wrote a
section's prose must never grade whether that prose did its job.

**A `synthesis` section that reaches a verdict is success, not overreach.**
Issue #577 landed first for exactly this reason: it made a new kind-(c)
claim -- the paper's own verdict -- a legitimate part of a paper, distinct
from a (b) claim's cross-source inference. A rubric written before that
would have scored a `synthesis` section that commits to a position as
reaching beyond its evidence. `compose_shape_prompt` below says the opposite
explicitly, because that is precisely the paper doing what this check
exists to look for.

**Calibrated against planted defects, issue #600.** The first live paper
returned `strong`/`[]` in 13 completion tokens -- a bare-band answer with no
visible reasoning. Measured against one clean control and three
single-section planted defects (synthesis-summarizes, evidence-as-list,
counter-position-as-strawman), the bare-band prompt caught **1 of 12
planted defects (8.3%)**, missing two of the three defect classes in four
tries each. Requiring a one-sentence `section_review` entry per section
--`meets_bar`/`reason`-- *before* `band`/`defects` in the response raised
that to **6 of 12 (50%)**, with zero false positives on the clean control
either way (`data/logs/2026-08-02-shape-check-calibration/`). This is a
real improvement, not a fix to reliable: the same content still draws a
different band across replicates for two of the three defect classes. That
is expected of a single-draw check (§7.16) and is not a regression to chase
here -- multi-draw agreement is what the §10.2 panel is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from axial.llm import PAPER_DRAFT_PASS_NAME, PAPER_SHAPE_PASS_NAME
from axial.llm import estimate_cost as _estimate_cost
from axial.model_json import complete_json, parse_model_json

BANDS: tuple[str, ...] = ("strong", "adequate", "weak")


class ShapeCheckError(Exception):
    """Base class for shape-check failures."""


class ShapeParseError(ShapeCheckError):
    """Raised when the shape check's response is not the expected shape, or
    names a band below `strong` with no defect naming what went wrong."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"shape check response is malformed: {reason}")


class SelfGradingError(ShapeCheckError):
    """Raised when the shape check's configured pass resolves to the SAME
    model as the drafting pass -- the model that wrote the prose must never
    grade whether its own prose did its job (§10.1, charter §2). Raised
    before any judge call is made; zero calls are made when this fires."""

    def __init__(self, judge_pass_name: str, model: str):
        self.judge_pass_name = judge_pass_name
        self.model = model
        super().__init__(
            f"the shape check (pass_name={judge_pass_name!r}) resolves to model {model!r}, "
            f"the SAME model as the drafting pass (pass_name={PAPER_DRAFT_PASS_NAME!r}) -- "
            "self-grading: configure model_by_pass so the shape check runs under a different "
            "model than the pass whose prose it is judging"
        )


@dataclass(frozen=True)
class ShapeDefect:
    """One named thing that went wrong: which section, and why (§7.16). A
    band below `strong` with no defects is a parse error, never a pass."""

    section_id: str
    note: str

    def to_json(self) -> dict[str, Any]:
        return {"section_id": self.section_id, "note": self.note}


@dataclass(frozen=True)
class ShapeResult:
    """The whole of what the check writes onto the paper record: the band,
    the named defects, which model judged, and what the call cost. `cost` is
    `None` when the client cannot report per-pass usage (mirrors
    `axial.llm.estimate_cost`'s own null-for-unpriced convention -- never a
    fabricated zero)."""

    band: str
    defects: tuple[ShapeDefect, ...]
    model: str
    cost: float | None

    def to_json(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "defects": [defect.to_json() for defect in self.defects],
            "model": self.model,
            "cost": self.cost,
        }


def _section_block(section_id: str, heading: str, role: str, prose: str) -> str:
    return f'### Section {section_id} -- "{heading}" (assigned role: {role})\n{prose}\n'


def compose_shape_prompt(thesis_statement: str, sections: list[dict[str, str]]) -> str:
    """The §7.16 prompt: the plan's stated intent, then the prose that either
    delivered it or did not. `sections` is `[{section_id, heading, role,
    prose}]` in plan order."""
    sections_text = "\n".join(
        _section_block(s["section_id"], s["heading"], s["role"], s["prose"]) for s in sections
    )
    return f"""You are the shape check on a finished paper (specs/PHASE-C.md §7.16). You are NOT grading quality, style, or correctness -- you are checking CONFORMANCE: did the drafted prose deliver the argument its own plan committed it to.

The paper's thesis: "{thesis_statement}"

The plan assigned each section below exactly one role from a closed vocabulary -- setup, claim, evidence, counter-position, synthesis -- and that assignment is the paper's stated intent. Judge only whether the prose performed the role it was assigned, and whether the sections build on each other toward the thesis rather than each one restarting.

{sections_text}

Role-specific bar, section by section:
- "setup": does it orient the reader toward the thesis, rather than merely describing the sources?
- "claim": does it argue a position, rather than listing what sources said?
- "evidence": does the material support a point the section itself is making, rather than being cited claim by claim with no throughline?
- "counter-position": does it state the opposing account at its strongest, in its own right, rather than as a weak foil built to be knocked down?
- "synthesis": does it reach the paper's OWN position -- a verdict, a commitment between the accounts, or a statement of where the account it commits to is weak? A synthesis section that reaches a verdict is doing exactly what its role requires: THAT IS SUCCESS, never overreach, and must not be scored as a defect. The failure is the opposite one: a synthesis section that only restates or summarizes what earlier sections already said, without committing to anything, has done the job of an "evidence" section wearing a "synthesis" label.

Also judge across the whole paper: does the argument advance section to section toward the stated thesis, or does each section restart as though the others were not there?

Before naming a band, work through EVERY section against its own bar above: for each section_id, state in one sentence whether it met the bar for its assigned role and why. Do this for all sections, not just ones you suspect are weak -- a section can only be judged "strong" by a reviewer who checked it, not by one who did not find a reason to flag it.

Only after that section-by-section review, return a band -- "strong", "adequate", or "weak" -- for the paper as a whole. If the band is not "strong", you MUST name at least one defect: which section_id failed its role and, in one sentence, what went wrong. A "weak" or "adequate" verdict naming no defects is not a valid answer.

Return JSON only, in this order:
{{"section_review": [{{"section_id": "s1", "meets_bar": true, "reason": "..."}}, ...one entry per section...], "band": "strong", "defects": [{{"section_id": "s2", "note": "..."}}]}}"""


def parse_shape_response(raw: str) -> tuple[str, list[ShapeDefect]]:
    """Parse and validate one shape-check response. A band below `strong`
    with an empty (or missing) `defects` list is a parse error, not a pass
    (§7.16, issue #578 acceptance criterion 3)."""
    parsed = parse_model_json(raw)
    if not isinstance(parsed, dict):
        raise ShapeParseError(f"expected an object, got {type(parsed).__name__}")

    band = parsed.get("band")
    if band not in BANDS:
        raise ShapeParseError(f"'band' is {band!r}, not one of {list(BANDS)!r}")

    defects: list[ShapeDefect] = []
    for entry in parsed.get("defects") or []:
        if not isinstance(entry, dict):
            raise ShapeParseError("a 'defects' entry is not an object")
        section_id = entry.get("section_id")
        note = entry.get("note")
        if not isinstance(section_id, str) or not section_id.strip():
            raise ShapeParseError("a defect names no 'section_id'")
        if not isinstance(note, str) or not note.strip():
            raise ShapeParseError(f"defect on section {section_id!r} carries no 'note'")
        defects.append(ShapeDefect(section_id=section_id.strip(), note=note.strip()))

    if band != "strong" and not defects:
        raise ShapeParseError(
            f"band is {band!r} but 'defects' is empty; a band below 'strong' must name at "
            "least one section_id and what went wrong"
        )

    return str(band), defects


def run_shape_check(
    client: Any,
    thesis_statement: str,
    sections: list[dict[str, str]],
    *,
    judge_pass_name: str = PAPER_SHAPE_PASS_NAME,
    drafting_pass_name: str = PAPER_DRAFT_PASS_NAME,
) -> ShapeResult:
    """One call, over the whole paper regardless of section count. Raises
    `SelfGradingError` before any call is made when `judge_pass_name` resolves
    to the same model as `drafting_pass_name`; raises `ShapeParseError` on a
    malformed or incomplete response."""
    drafting_model = client.model_for_pass(drafting_pass_name)
    judge_model = client.model_for_pass(judge_pass_name)
    if judge_model == drafting_model:
        raise SelfGradingError(judge_pass_name, judge_model)

    prompt = compose_shape_prompt(thesis_statement, sections)
    raw = complete_json(client, prompt, pass_name=judge_pass_name)
    band, defects = parse_shape_response(raw)

    usage_for_pass = getattr(client, "usage_for_pass", None)
    usage = usage_for_pass(judge_pass_name) if usage_for_pass is not None else None
    cost = (
        _estimate_cost(
            judge_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        )
        if usage
        else None
    )

    return ShapeResult(band=band, defects=tuple(defects), model=judge_model, cost=cost)
