"""Stage 2: arc planning (specs/PHASE-C.md §7.2, §8 P0-2).

**The arc is planned before any prose exists**, which is what makes the paper
assembled rather than back-fitted, and what makes it inspectable before a
drafting dollar is spent. This pass emits sections, roles and claim
assignments. It writes no prose at all.

The plan is also the drafting boundary (§4): the drafter is called once per
section over that section's `assigned_claims`, so what the planner assigns is
what a drafting call gets to see. A claim assigned nowhere is a claim no call
can cite -- the planner's decision to make, and visible in `examine` output
before anything is paid for.

Takes a LIST of analysis records by way of the inventory, and a list of one is
not a special case (§0, §5).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from typing import Any

from axial.llm import PAPER_PLAN_PASS_NAME
from axial.model_json import complete_json, parse_model_json
from axial.paper.intake import InventoryClaim, PaperIntake
from axial.paper.lens import Lens

# §7.2: exactly these five, and the order of the list is not the order of a
# paper -- it is a vocabulary, not a template.
ROLES: tuple[str, ...] = ("setup", "claim", "evidence", "counter-position", "synthesis")

COUNTER_POSITION_ROLE = "counter-position"

# The only role whose section may carry no claims (§7.2). Every other section
# must earn its place with material.
_MAY_BE_EMPTY = frozenset({"setup"})


class PlanError(Exception):
    """Base class for arc-planning failures."""


class PlanParseError(PlanError):
    """Raised when the planner's response is not the §7.2 shape."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"arc plan response is malformed: {reason}")


class UnknownRoleError(PlanError):
    """Raised when a section names a role outside the closed vocabulary."""

    def __init__(self, section_id: str, role: Any):
        self.section_id = section_id
        self.role = role
        super().__init__(f"section {section_id!r} has role {role!r}, not one of {list(ROLES)!r}")


class UnassignedClaimError(PlanError):
    """Raised when a section assigns a claim the inventory does not hold."""

    def __init__(self, section_id: str, key: tuple[Any, Any]):
        self.section_id = section_id
        self.key = key
        # The two fields are reported separately because the failure this error
        # actually sees is a misfilled pair, not an invented claim (issue #592).
        brief_id, claim_id = key
        super().__init__(
            f"section {section_id!r} assigns brief_id={brief_id!r} claim_id={claim_id!r}, "
            f"which is not in the claim inventory; copy both fields verbatim from one "
            f"inventory line; the inventory is the drafter's entire world (§4)"
        )


class EmptySectionError(PlanError):
    """Raised when a non-`setup` section carries no claims (§7.2)."""

    def __init__(self, section_id: str, role: str):
        self.section_id = section_id
        self.role = role
        super().__init__(
            f"section {section_id!r} has role {role!r} and no assigned claims; only a "
            f"'setup' section may be empty (§7.2)"
        )


class MissingCounterPositionError(PlanError):
    """Raised when a plan carries no counter-position section and the source
    records do not all disclose a one-sided corpus (§7.2, charter IV).

    Neither present is a red flag, not a clean result. A `failed`
    counter-position section in a source record does NOT count as a
    one-sidedness disclosure (§7.3, PR #558): that state means a run died in
    its closing stage, and reading a bug as a finding about the corpus is
    exactly what that field's third state exists to prevent."""

    def __init__(self, disclosing: list[str], total: int):
        self.disclosing = list(disclosing)
        self.total = total
        super().__init__(
            f"the plan carries no {COUNTER_POSITION_ROLE!r} section, but only "
            f"{len(disclosing)} of {total} source record(s) disclose a one-sided corpus "
            f"({sorted(disclosing)!r}); a paper that drops its opposition without "
            f"disclosing why fails charter Principle IV"
        )


@dataclass(frozen=True)
class Section:
    """One planned section (§7.2)."""

    section_id: str
    heading: str
    role: str
    assigned_claims: tuple[tuple[str, str], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "heading": self.heading,
            "role": self.role,
            "assigned_claims": [
                {"brief_id": brief_id, "claim_id": claim_id}
                for brief_id, claim_id in self.assigned_claims
            ],
        }


@dataclass(frozen=True)
class Plan:
    """The arc (§7.2). `sections` is ordered and rendering never reorders.

    `retries` counts how many of `run_plan`'s attempts beyond the first were
    rejected before this plan was accepted (issue #598) -- a Python-side
    bookkeeping field, never part of the persisted §7.2 plan shape, which
    `to_json` below does not emit it into."""

    thesis_statement: str
    sections: tuple[Section, ...] = field(default_factory=tuple)
    retries: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "thesis_statement": self.thesis_statement,
            "sections": [section.to_json() for section in self.sections],
        }


def _inventory_lines(inventory: tuple[InventoryClaim, ...]) -> str:
    """The claim inventory as the planner sees it: enough to arrange by, and
    no grounds text. The planner decides order and assignment, not wording.

    Each line names `brief_id` and `claim_id` in the same shape the response
    schema asks for. Rendering them as one `(brief_id / claim_id)` pair instead
    is what issue #592 was: the planner could not tell where the compound
    identifier split, and filled the two fields wrong on every draw."""
    lines = []
    for entry in inventory:
        claim = entry.claim
        lines.append(
            f"- brief_id={entry.brief_id} claim_id={entry.claim_id} "
            f"[kind {claim.get('kind')}] "
            f"[confidence {claim.get('confidence')}] {claim.get('text')}"
        )
    return "\n".join(lines) or "(the named records carry no claims)"


def compose_plan_prompt(thesis: str, lens: Lens, intake: PaperIntake) -> str:
    """The stage-2 prompt. No prose is requested and none is accepted."""
    return f"""You are the arc-planning pass of a paper author (specs/PHASE-C.md §7.2). You plan the argument of a paper; you do NOT write it. Emit no prose, no sentences of the paper, and no new claims.

Thesis the paper must argue: "{thesis}"
Lens the argument is read through: {lens.for_prompt()}

The claim inventory below is every claim available, drawn from {len(intake.source_analyses)} analysis record(s). It is the whole world this paper may cite -- there is no retrieval and nothing else can be reached.

{_inventory_lines(intake.inventory)}

Plan an arc. Order the sections so each earns the next, and assign each claim to the section that uses it. A claim you assign nowhere is a claim the paper cannot cite, so assign deliberately rather than exhaustively. Do not assign one claim to two sections.

Each section carries exactly one role, from: {", ".join(ROLES)}. Only a "setup" section may carry no claims; every other section must carry at least one.

At least one section must have role "counter-position" and state the opposing position at its strongest, unless the records themselves report the corpus is one-sided. A paper that quietly drops the side it disagrees with is the failure this pass most needs to avoid.

Also state the thesis as the PAPER will state it -- one sentence, in the paper's own voice, read through the lens. That sentence is the paper's claim, not a restatement of the question.

Every entry in "assigned_claims" copies "brief_id" and "claim_id" verbatim from one inventory line above, as two separate fields. Do not combine them into one field, and do not put a claim's text in either.

Return JSON only:
{{"thesis_statement": "...", "sections": [{{"section_id": "s1", "heading": "...", "role": "...", "assigned_claims": [{{"brief_id": "...", "claim_id": "..."}}]}}]}}"""


def parse_plan_response(raw: str, intake: PaperIntake) -> Plan:
    """Parse and validate the planner's response against the inventory."""
    parsed = parse_model_json(raw)
    if not isinstance(parsed, dict):
        raise PlanParseError(f"expected an object, got {type(parsed).__name__}")

    thesis_statement = parsed.get("thesis_statement")
    if not isinstance(thesis_statement, str) or not thesis_statement.strip():
        raise PlanParseError("'thesis_statement' is missing or empty")

    raw_sections = parsed.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise PlanParseError("'sections' is missing or empty")

    known = set(intake.by_key())
    sections: list[Section] = []
    for index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            raise PlanParseError(f"section {index} is not an object")

        section_id = str(raw_section.get("section_id") or f"s{index + 1}")
        role = raw_section.get("role")
        if role not in ROLES:
            raise UnknownRoleError(section_id, role)

        assigned: list[tuple[str, str]] = []
        for entry in raw_section.get("assigned_claims") or []:
            if not isinstance(entry, dict):
                raise UnassignedClaimError(section_id, (None, entry))
            key = (entry.get("brief_id"), entry.get("claim_id"))
            if key not in known:
                raise UnassignedClaimError(section_id, key)
            assigned.append((str(key[0]), str(key[1])))

        if not assigned and role not in _MAY_BE_EMPTY:
            raise EmptySectionError(section_id, str(role))

        sections.append(
            Section(
                section_id=section_id,
                heading=str(raw_section.get("heading") or section_id),
                role=str(role),
                assigned_claims=tuple(assigned),
            )
        )

    return Plan(thesis_statement=thesis_statement.strip(), sections=tuple(sections))


def _discloses_one_sided(record: dict[str, Any]) -> bool:
    """Whether a source record reports its corpus one-sided (§7.2).

    A `failed` section is not a disclosure, whatever else it carries."""
    counter_position = record.get("counter_position")
    if not isinstance(counter_position, dict):
        return False
    if counter_position.get("failed"):
        return False
    return counter_position.get("corpus_one_sided") is True


def validate_plan(plan: Plan, records: dict[str, dict[str, Any]]) -> None:
    """The §7.2 counter-position presence guard.

    Cheap and read off the source records alone; the authoritative check is
    the post-draft counter-position gate (§7.14, §10.1), which sees what the
    paper actually cited."""
    if any(section.role == COUNTER_POSITION_ROLE for section in plan.sections):
        return
    disclosing = [brief_id for brief_id, record in records.items() if _discloses_one_sided(record)]
    if len(disclosing) != len(records) or not records:
        raise MissingCounterPositionError(disclosing, len(records))


# Bounded retry (issue #598): a rejected plan is re-asked with the error
# text appended, never repaired. First attempt plus up to two re-asks -- one
# number, matching `axial.llm`'s own `_MAX_ATTEMPTS` retry budget for
# transport failures, which this is not: that budget catches a stalled
# connection or a 5xx; this one catches a well-formed response that fails
# Phase C's own rules (measured: #598's seven-draw sample was 5 valid, 2
# rejected on the exact §7.2 empty-section rule, 1 indeterminate).
_MAX_ATTEMPTS = 3

# Exactly the four errors issue #598 names as retryable. Deliberately NOT
# `PlanError` (the shared base): `MissingCounterPositionError` is also a
# `PlanError` and is raised by `validate_plan`, called only after a parse
# already succeeded -- the issue scopes retry to a malformed or
# rule-violating PARSE, not to the counter-position presence guard, which
# stays a hard first-attempt failure exactly as before (§7.2's own note
# that a plan carrying no counter-position section is a red flag either way).
_PLAN_RETRYABLE_ERRORS: tuple[type[PlanError], ...] = (
    PlanParseError,
    UnknownRoleError,
    EmptySectionError,
    UnassignedClaimError,
)


def _log_plan_retry(attempt: int, error: PlanError) -> None:
    """One structured stderr line per rejected attempt (issue #598): a
    silent retry turns a measured flake rate into an invisible one. Bare
    print, matching `axial.llm._log_retry`'s convention -- this repo has no
    logging framework."""
    print(
        f"paper_retry pass={PAPER_PLAN_PASS_NAME} attempt={attempt}/{_MAX_ATTEMPTS} "
        f"validator={type(error).__name__}",
        file=sys.stderr,
    )


def _plan_retry_prompt(base_prompt: str, error: PlanError, attempt: int) -> str:
    """Re-ask with the error text appended -- not a repair loop. The prompt
    the model sees next is the original prompt plus what went wrong, so it
    can avoid the mistake; nothing here patches the rejected plan itself."""
    return (
        f"{base_prompt}\n\n"
        f"Your previous plan (attempt {attempt} of {_MAX_ATTEMPTS}) was rejected: {error}\n"
        "Produce a new, complete plan from scratch that does not repeat this mistake."
    )


def run_plan(client: Any, thesis: str, lens: Lens, intake: PaperIntake) -> Plan:
    """Stage 2, end to end: parsed and validated, with a bounded retry
    (issue #598) on the four §7.2 errors a malformed or rule-violating
    response can raise. `validate_plan`'s counter-position guard is not
    retried -- see `_PLAN_RETRYABLE_ERRORS`."""
    base_prompt = compose_plan_prompt(thesis, lens, intake)
    prompt = base_prompt
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        raw = complete_json(client, prompt, pass_name=PAPER_PLAN_PASS_NAME)
        try:
            plan = parse_plan_response(raw, intake)
        except _PLAN_RETRYABLE_ERRORS as exc:
            if attempt == _MAX_ATTEMPTS:
                raise
            _log_plan_retry(attempt, exc)
            prompt = _plan_retry_prompt(base_prompt, exc, attempt)
            continue
        validate_plan(plan, intake.records)
        return replace(plan, retries=attempt - 1)
    raise AssertionError("unreachable: the retry loop always returns or raises")


def format_plan(plan: Plan) -> str:
    """The inspect-before-spend view (`axial paper examine`, P0-12)."""
    lines = [f"thesis: {plan.thesis_statement}", ""]
    for section in plan.sections:
        lines.append(f"[{section.role}] {section.heading} ({section.section_id})")
        for brief_id, claim_id in section.assigned_claims:
            lines.append(f"    {brief_id} / {claim_id}")
        if not section.assigned_claims:
            lines.append("    (no claims assigned)")
    return "\n".join(lines)


def plan_json(plan: Plan) -> str:
    return json.dumps(plan.to_json(), indent=2, ensure_ascii=False)
