"""Stage 3: drafting, one call per section (specs/PHASE-C.md §4, §5, §8 P0-3).

**One call per section, over that section's assigned claims and nothing else.**
Phase B measured that roughly twenty notes reach a model however much is
supplied -- 62% more evidence assembled between two runs put exactly the same
127 notes in front of it (PHASE-B P2-7, issues #505 and #545). An inventory
across three records runs to 40-70 claims plus grounds, so a whole-inventory
prompt would have a tail nothing reads and no way to know which claims fell
off it. The plan is what makes the smaller prompt possible.

**A new (b) claim can still reach across sections**, and therefore across
records, because each call also carries what earlier sections already cited:
id, kind, band and text, never grounds text. Without that a cross-source
inference would be impossible whenever the plan grouped a section by source.

**The drafter has no tools.** It cannot introduce a grounds pointer that was
not already in the inventory, because it never supplies grounds at all: a new
(b) claim names the claims it reasons from, and `axial.paper.claims` derives
the pointers mechanically. Generate-then-cite is structurally impossible here
rather than forbidden by instruction.

Claim ids are assigned deterministically BEFORE drafting, so the drafter
writes real markers rather than placeholders. New claims are the exception --
the drafter names them with a local id it invents, and those are remapped to
stable ids after the call, because a claim that does not exist yet cannot have
been numbered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from axial.llm import PAPER_DRAFT_PASS_NAME
from axial.model_json import complete_json, parse_model_json
from axial.paper.lens import Lens
from axial.paper.plan import Plan, Section

# Stable id prefix for a paper claim (§7.4: "stable, deterministic within a
# run"). Numbered in plan order, so the same plan always numbers the same.
_CLAIM_ID_PREFIX = "pc"


class DraftError(Exception):
    """Base class for drafting failures."""


class DraftParseError(DraftError):
    """Raised when a drafting response is not the expected shape."""

    def __init__(self, section_id: str, reason: str):
        self.section_id = section_id
        self.reason = reason
        super().__init__(f"draft of section {section_id!r} is malformed: {reason}")


class UnknownDerivationError(DraftError):
    """Raised when a new (b) claim derives from a claim the drafter could not
    see -- one not assigned to this section and not cited earlier."""

    def __init__(self, section_id: str, local_id: str, unknown: list[str]):
        self.section_id = section_id
        self.local_id = local_id
        self.unknown = list(unknown)
        super().__init__(
            f"new claim {local_id!r} in section {section_id!r} derives from "
            f"{sorted(unknown)!r}, which this call was never shown; a claim may only "
            f"reason from its own section's claims and what earlier sections cited"
        )


@dataclass(frozen=True)
class NewClaimDraft:
    """A new (b) claim as the drafter proposed it: text and what it reasons
    from. No kind, no grounds, no band -- all three are derived, never asked."""

    local_id: str
    text: str
    derived_from: tuple[str, ...]


@dataclass(frozen=True)
class SectionDraft:
    """One section's drafted prose and the new claims it introduced."""

    section_id: str
    prose: str
    new_claims: tuple[NewClaimDraft, ...] = ()


def assign_claim_ids(plan: Plan) -> dict[tuple[str, str], str]:
    """Assign a stable `pc-NNN` to every claim the plan assigns, in plan order.

    Deterministic within a run and stable across re-runs of the same plan: the
    same plan numbers the same claims the same way, which is what §7.4 means
    by a stable id and what makes a citation marker reproducible."""
    ids: dict[tuple[str, str], str] = {}
    for section in plan.sections:
        for key in section.assigned_claims:
            if key not in ids:
                ids[key] = f"{_CLAIM_ID_PREFIX}-{len(ids) + 1:03d}"
    return ids


def _claim_lines(
    section: Section,
    claim_ids: dict[tuple[str, str], str],
    claims_by_id: dict[str, dict[str, Any]],
) -> str:
    lines = []
    for key in section.assigned_claims:
        paper_claim_id = claim_ids[key]
        claim = claims_by_id.get(paper_claim_id, {})
        lines.append(
            f"[{paper_claim_id}] (kind {claim.get('kind')}, confidence "
            f"{claim.get('confidence')}) {claim.get('text')}"
        )
    return "\n".join(lines) or "(this section is assigned no claims)"


def _earlier_lines(already_cited: list[dict[str, Any]]) -> str:
    if not already_cited:
        return "(nothing has been cited yet -- this is the first section)"
    return "\n".join(
        f"[{claim.get('paper_claim_id')}] (kind {claim.get('kind')}, confidence "
        f"{claim.get('confidence')}) {claim.get('text')}"
        for claim in already_cited
    )


def compose_draft_prompt(
    thesis_statement: str,
    lens: Lens,
    section: Section,
    section_claims: str,
    earlier_claims: str,
) -> str:
    """The stage-3 prompt for one section."""
    return f"""You are the drafting pass of a paper author (specs/PHASE-C.md §7.4). Write ONE section of a paper. You have no tools, no retrieval, and no access to any source: the claims below are the whole world, and you may not assert anything that is not traceable to one of them.

The paper argues: "{thesis_statement}"
Read through the lens: {lens.for_prompt()}

This section: "{section.heading}" -- its role in the argument is "{section.role}".

Claims assigned to this section, each with the marker that cites it:
{section_claims}

Claims already cited by earlier sections, available to reason across (cite them only if this section genuinely uses them):
{earlier_claims}

Write the section's prose. End every sentence that rests on a claim with that claim's marker, exactly as shown, e.g. "... its own terms [pc-004]." Adjoin multiple markers with no separator: [pc-004][pc-011]. Use square brackets for nothing else.

Voice is the seam that matters. A claim marked kind "a" is a SOURCE's assertion and may be attributed to it ("Tilly argues..."). A claim marked "b" is this system's own inference across sources and must NEVER be voiced as though a source asserted it. Write it in your own register.

You may introduce new cross-source inferences of your own. Each must reason across claims drawn from at least TWO different analysis records, name the claims it reasons from, and carry a local id you invent (e.g. "n1") which you cite in the prose exactly like any other marker. Do NOT supply grounds -- they are derived from the claims you name. Do not introduce speculation: every new claim is an inference across the claims listed above.

Return JSON only:
{{"prose": "...", "new_claims": [{{"local_id": "n1", "text": "...", "derived_from": ["pc-004", "pc-011"]}}]}}"""


def parse_draft_response(raw: str, section: Section, visible_ids: set[str]) -> SectionDraft:
    """Parse one section's response, checking every derivation was visible."""
    parsed = parse_model_json(raw)
    if not isinstance(parsed, dict):
        raise DraftParseError(
            section.section_id, f"expected an object, got {type(parsed).__name__}"
        )

    prose = parsed.get("prose")
    if not isinstance(prose, str) or not prose.strip():
        raise DraftParseError(section.section_id, "'prose' is missing or empty")

    new_claims: list[NewClaimDraft] = []
    local_ids: set[str] = set()
    for entry in parsed.get("new_claims") or []:
        if not isinstance(entry, dict):
            raise DraftParseError(section.section_id, "a new_claims entry is not an object")
        local_id = entry.get("local_id")
        text = entry.get("text")
        if not isinstance(local_id, str) or not local_id.strip():
            raise DraftParseError(section.section_id, "a new claim has no local_id")
        if not isinstance(text, str) or not text.strip():
            raise DraftParseError(section.section_id, f"new claim {local_id!r} has no text")

        derived = [str(value) for value in (entry.get("derived_from") or [])]
        unknown = [
            value for value in derived if value not in visible_ids and value not in local_ids
        ]
        if unknown:
            raise UnknownDerivationError(section.section_id, local_id, unknown)

        local_ids.add(local_id.strip())
        new_claims.append(
            NewClaimDraft(local_id=local_id.strip(), text=text.strip(), derived_from=tuple(derived))
        )

    return SectionDraft(
        section_id=section.section_id, prose=prose.strip(), new_claims=tuple(new_claims)
    )


def remap_local_ids(draft: SectionDraft, assigned: dict[str, str]) -> SectionDraft:
    """Rewrite a draft's local new-claim ids to their stable `pc-NNN`.

    Markers are unique bracketed tokens, so this is an exact token
    substitution rather than a text search: `[n1]` becomes `[pc-013]` and
    nothing else in the prose can match."""
    prose = draft.prose
    for local_id, paper_claim_id in assigned.items():
        prose = re.sub(rf"\[{re.escape(local_id)}\]", f"[{paper_claim_id}]", prose)

    return SectionDraft(
        section_id=draft.section_id,
        prose=prose,
        new_claims=tuple(
            NewClaimDraft(
                local_id=assigned.get(claim.local_id, claim.local_id),
                text=claim.text,
                derived_from=tuple(assigned.get(parent, parent) for parent in claim.derived_from),
            )
            for claim in draft.new_claims
        ),
    )


def draft_section(
    client: Any,
    thesis_statement: str,
    lens: Lens,
    section: Section,
    claim_ids: dict[tuple[str, str], str],
    claims_by_id: dict[str, dict[str, Any]],
    already_cited: list[dict[str, Any]],
) -> SectionDraft:
    """One section, one model call."""
    visible = {claim_ids[key] for key in section.assigned_claims}
    visible.update(str(claim.get("paper_claim_id")) for claim in already_cited)
    prompt = compose_draft_prompt(
        thesis_statement,
        lens,
        section,
        _claim_lines(section, claim_ids, claims_by_id),
        _earlier_lines(already_cited),
    )
    raw = complete_json(client, prompt, pass_name=PAPER_DRAFT_PASS_NAME)
    return parse_draft_response(raw, section, visible)
