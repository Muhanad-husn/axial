"""Stage 3: drafting, one call per section (specs/PHASE-C.md §4, §5, §8 P0-3).

**One call per section, over that section's assigned claims and nothing else.**
The "roughly twenty notes reach a model however much is supplied" figure this
paragraph used to cite (PHASE-B P2-7, issues #505 and #545) was measured at a
100k-character budget; it does not hold at the budgets Phase B now runs at --
the 2026-08-02 run at 200k composed 44 of 200 assembled notes, and the 250k
run composed 56 of 90. The per-section design still stands on its own
grounds, unrelated to that number: a section needs an argumentative role
(§7.2), and a single call over the whole inventory leaves no way to know
which claims fell off the end. An inventory across three records runs to
40-70 claims plus grounds, so a whole-inventory prompt would still hand the
drafter a mixed bag of unrelated argumentative roles in one call, whatever
the model's real attention turns out to be. The plan is what makes the
per-section prompt possible.

**A new (b) or (c) claim can still reach across sections**, and therefore
across records, because each call also carries what earlier sections already
cited: id, kind, band and text, never grounds text. Without that a
cross-source (b) inference, or a (c) verdict resting on claims from more than
one section, would be impossible whenever the plan grouped a section by
source.

**The drafter has no tools.** It cannot introduce a grounds pointer that was
not already in the inventory, because it never supplies grounds at all: a new
claim names the claims it reasons from, and `axial.paper.claims` derives the
pointers mechanically -- for a (b) claim, at least two distinct records'
worth; for a (c) claim, its own verdict, exempt from that count but never
from naming something (issue #577). Generate-then-cite is structurally
impossible here rather than forbidden by instruction.

Claim ids are assigned deterministically BEFORE drafting, so the drafter
writes real markers rather than placeholders. New claims are the exception --
the drafter names them with a local id it invents, and those are remapped to
stable ids after the call, because a claim that does not exist yet cannot have
been numbered.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, replace
from typing import Any

from axial.llm import PAPER_DRAFT_PASS_NAME
from axial.model_json import complete_json, parse_model_json
from axial.paper.claims import MIN_DISTINCT_RECORDS
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
    """Raised when a new claim derives from a claim the drafter could not
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


class InvalidNewClaimKindError(DraftError):
    """Raised when a new claim names a `kind` outside {"b", "c"} (issue #577).

    A new claim is either a cross-source inference (`b`) or the paper's own
    verdict (`c`) -- never a restated source assertion (`a`, §3 non-goal 4)
    and never anything outside the vocabulary."""

    def __init__(self, section_id: str, local_id: str, kind: object):
        self.section_id = section_id
        self.local_id = local_id
        self.kind = kind
        super().__init__(
            f"new claim {local_id!r} in section {section_id!r} names kind {kind!r}; "
            f"a new claim is 'b' (cross-source inference) or 'c' (this paper's "
            f"verdict) -- never 'a' and never anything else"
        )


class InsufficientRecordSpanError(DraftError):
    """Raised when a proposed new (b) claim does not derive from at least two
    distinct source records (§7.4) -- the drafting-time twin of
    `axial.paper.claims.SingleRecordInferenceError` (issue #616).

    `new_b_claim` still checks this again at construction time, as the
    backstop this predicts; that check runs after `draft_section` has
    already returned, which used to make a single-record proposal fatal on
    first occurrence and discard every section drafted so far. Checking it
    here, inside the bounded retry, makes it a re-ask like any other
    validation failure."""

    def __init__(self, section_id: str, local_id: str, brief_ids: set[str]):
        self.section_id = section_id
        self.local_id = local_id
        self.brief_ids = set(brief_ids)
        super().__init__(
            f"new (b) claim {local_id!r} in section {section_id!r} derives from "
            f"{sorted(self.brief_ids)!r} -- {len(self.brief_ids)} distinct source "
            f"record(s), and §7.4 requires at least {MIN_DISTINCT_RECORDS}. Reason "
            'across a claim from a second record, or mark this claim kind "c" if it '
            "is this paper's own verdict rather than a cross-source inference"
        )


@dataclass(frozen=True)
class NewClaimDraft:
    """A new claim as the drafter proposed it: text, its kind ('b' or 'c'),
    and what it reasons from. No grounds, no band -- both are derived, never
    asked."""

    local_id: str
    text: str
    derived_from: tuple[str, ...]
    kind: str = "b"


@dataclass(frozen=True)
class SectionDraft:
    """One section's drafted prose and the new claims it introduced.

    `retries` counts how many of `draft_section`'s attempts beyond the
    first were rejected before this draft was accepted (issue #598) --
    bookkeeping only, carried through `remap_local_ids` so the count
    survives the local-id rewrite untouched."""

    section_id: str
    prose: str
    new_claims: tuple[NewClaimDraft, ...] = ()
    retries: int = 0


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


def _brief_ids_of_claim(
    claim: dict[str, Any],
    claims_by_id: dict[str, dict[str, Any]],
    visited: set[str] | None = None,
) -> set[str]:
    """The distinct source records one BUILT claim rests on (issue #616).

    A carried claim names its own record in `origin`. A new (b)/(c) claim
    names none of its own -- it resolves through `derived_from`,
    transitively, because a claim's parents can themselves be new claims
    (`axial.paper.claims._brief_ids_of` is the same walk, over the record
    that check ultimately runs against; this is the drafting-time twin, used
    to SHOW the record on a claim line rather than to gate one)."""
    origin = claim.get("origin")
    if isinstance(origin, dict) and origin.get("brief_id"):
        return {str(origin["brief_id"])}
    visited = visited if visited is not None else set()
    brief_ids: set[str] = set()
    for parent_id in claim.get("derived_from") or []:
        if parent_id in visited:
            continue
        visited.add(parent_id)
        parent = claims_by_id.get(parent_id)
        if parent is not None:
            brief_ids |= _brief_ids_of_claim(parent, claims_by_id, visited)
    return brief_ids


def _record_label(brief_ids: set[str]) -> str:
    """`§7.4`'s span rule is stated over `origin.brief_id`; a claim line that
    omits it holds the drafter to a field it cannot see (issue #616)."""
    if not brief_ids:
        return "record unknown"
    return "record " + ", ".join(sorted(brief_ids))


def _claim_lines(
    section: Section,
    claim_ids: dict[tuple[str, str], str],
    claims_by_id: dict[str, dict[str, Any]],
) -> str:
    lines = []
    for key in section.assigned_claims:
        paper_claim_id = claim_ids[key]
        claim = claims_by_id.get(paper_claim_id, {})
        record = _record_label(_brief_ids_of_claim(claim, claims_by_id))
        lines.append(
            f"[{paper_claim_id}] (kind {claim.get('kind')}, confidence "
            f"{claim.get('confidence')}, {record}) {claim.get('text')}"
        )
    return "\n".join(lines) or "(this section is assigned no claims)"


def _earlier_lines(
    already_cited: list[dict[str, Any]], claims_by_id: dict[str, dict[str, Any]]
) -> str:
    if not already_cited:
        return "(nothing has been cited yet -- this is the first section)"
    lines = []
    for claim in already_cited:
        record = _record_label(_brief_ids_of_claim(claim, claims_by_id))
        lines.append(
            f"[{claim.get('paper_claim_id')}] (kind {claim.get('kind')}, confidence "
            f"{claim.get('confidence')}, {record}) {claim.get('text')}"
        )
    return "\n".join(lines)


def _proposed_brief_ids(
    proposal: NewClaimDraft,
    proposals_by_local_id: dict[str, NewClaimDraft],
    claims_by_id: dict[str, dict[str, Any]],
    visited: set[str] | None = None,
) -> set[str]:
    """The distinct source records a JUST-PROPOSED claim would rest on,
    before it has a stable id or an entry in `claims_by_id` (issue #616).

    Same walk as `_brief_ids_of_claim`, except a parent may still be another
    proposal in THIS SAME response, named by the local id the drafter
    invented for it (`derived_from` is validated against local ids by
    `parse_draft_response` before this ever runs) -- the case
    `_brief_ids_of_claim` alone cannot resolve, because that sibling has no
    entry in `claims_by_id` yet."""
    visited = visited if visited is not None else set()
    brief_ids: set[str] = set()
    for parent_id in proposal.derived_from:
        if parent_id in visited:
            continue
        visited.add(parent_id)
        sibling = proposals_by_local_id.get(parent_id)
        if sibling is not None:
            brief_ids |= _proposed_brief_ids(sibling, proposals_by_local_id, claims_by_id, visited)
            continue
        parent = claims_by_id.get(parent_id)
        if parent is not None:
            brief_ids |= _brief_ids_of_claim(parent, claims_by_id, visited)
    return brief_ids


def _check_record_span(draft: SectionDraft, claims_by_id: dict[str, dict[str, Any]]) -> None:
    """The §7.4 span check for every proposed (b) claim, run BEFORE this
    draft is accepted (issue #616), so a single-record proposal is retried
    like any other validation failure rather than fatal after acceptance.

    `axial.paper.claims.new_b_claim` still checks again at construction
    time, unchanged, as the backstop this predicts."""
    proposals_by_local_id = {proposal.local_id: proposal for proposal in draft.new_claims}
    for proposal in draft.new_claims:
        if proposal.kind != "b":
            continue
        brief_ids = _proposed_brief_ids(proposal, proposals_by_local_id, claims_by_id)
        if len(brief_ids) < MIN_DISTINCT_RECORDS:
            raise InsufficientRecordSpanError(draft.section_id, proposal.local_id, brief_ids)


_NEW_CLAIMS_HEADER = """You may introduce new claims of your own. Each carries a local id you invent (e.g. "n1"), cited in the prose exactly like any other marker, and names the claims above it reasons from -- do NOT supply grounds, they are derived mechanically from the claims you name:"""

_NEW_CLAIM_B = """- kind "b", a cross-source inference: it must reason across claims drawn from at least TWO different analysis records, and it may characterise a disagreement between them but may not declare a winner beyond what those claims support."""

_NEW_CLAIM_C = """- kind "c", this paper's own verdict: where the thesis calls for a verdict, a commitment between positions, or a statement of where the account you commit to is weak, mark it "c" rather than smuggling it into a "b" claim or a source's own voice. It may rest on claims from a single record. Do not mark a claim "c" only to give it more grounds than a "b" claim would need -- "c" is for judgment the sources do not themselves make, not for a shortcut past the two-record rule."""

_ONLY_ONE_RECORD = """This paper stands on ONE analysis record, so a kind "b" cross-source inference is impossible here: there is no second record to reason across, and a claim drawn from a single record is a restatement rather than synthesis. Every new claim you introduce is kind "c"."""

_NEW_CLAIMS_IMPOSSIBLE = """This section is assigned no claims, and no earlier section has cited any, so there is nothing here for a new claim to reason from. Introduce NO new claims: return "new_claims" as an empty list. Frame the question in your own sentences, from the thesis statement above -- stating the thesis is what this section is for, and it needs no claim of its own. The paper's verdict belongs in the section whose role is "synthesis"."""


def _new_claims_block(has_visible_claims: bool, cross_source_possible: bool) -> str:
    """What the drafter may introduce, given what this paper actually has.

    The prompt used to describe the general case unconditionally, which invited
    a claim the validator then refused: with nothing visible, one that could not
    be grounded (#596), and on a single-record paper, a (b) claim that can never
    span two records (#597)."""
    if not has_visible_claims:
        return _NEW_CLAIMS_IMPOSSIBLE
    if not cross_source_possible:
        return "\n".join([_NEW_CLAIMS_HEADER, _NEW_CLAIM_C, "", _ONLY_ONE_RECORD])
    return "\n".join([_NEW_CLAIMS_HEADER, _NEW_CLAIM_B, _NEW_CLAIM_C])


def _new_claims_example(has_visible_claims: bool, cross_source_possible: bool) -> str:
    """The example follows the same branch as the instruction above it.

    An example is the strongest instruction in a prompt -- issue #592 -- so it
    must never demonstrate a claim kind this paper's validator would reject."""
    if not has_visible_claims:
        return "[]"
    if not cross_source_possible:
        return '[{"local_id": "n1", "kind": "c", "text": "...", "derived_from": ["pc-004"]}]'
    return '[{"local_id": "n1", "kind": "b", "text": "...", "derived_from": ["pc-004", "pc-011"]}]'


def compose_draft_prompt(
    thesis_statement: str,
    lens: Lens,
    section: Section,
    section_claims: str,
    earlier_claims: str,
    has_visible_claims: bool = True,
    cross_source_possible: bool = True,
) -> str:
    """The stage-3 prompt for one section.

    `has_visible_claims` is false only when the section is assigned no claims
    and no earlier section has cited any. Inviting a new claim there is issue
    #596: the drafter minted a verdict it could not ground, because there was
    nothing to ground it on. The condition is "nothing visible" rather than
    "role is setup" -- a `setup` section later in an arc can see earlier
    sections' claims and may derive from them legitimately.

    `cross_source_possible` is false when the paper stands on one analysis
    record, where §7.4 makes a (b) claim impossible and (c) the only new claim
    available (issue #597)."""
    return f"""You are the drafting pass of a paper author (specs/PHASE-C.md §7.4). Write ONE section of a paper. You have no tools, no retrieval, and no access to any source: the claims below are the whole world, and you may not assert anything that is not traceable to one of them.

The paper argues: "{thesis_statement}"
Read through the lens: {lens.for_prompt()}

This section: "{section.heading}" -- its role in the argument is "{section.role}".

Claims assigned to this section, each with the marker that cites it:
{section_claims}

Claims already cited by earlier sections, available to reason across (cite them only if this section genuinely uses them):
{earlier_claims}

Write the section's prose. End every sentence that rests on a claim with that claim's marker, exactly as shown, e.g. "... its own terms [pc-004]." Adjoin multiple markers with no separator: [pc-004][pc-011]. Use square brackets for nothing else.

THE ARGUMENT LEADS AND THE SOURCES SUPPORT IT. This is the single thing that decides whether this reads as scholarship or as a reading list, so it outranks every other instruction here except honesty about grounds.

- Open the section with the point IT makes, in your own sentences. Do not open with a source.
- The subject of a sentence should usually be the thing being explained -- a mechanism, a case, a disagreement -- not a scholar. Write "Extraction follows coercion where rulers lack an alternative revenue base [pc-002]", not "Tilly argues that extraction follows coercion [pc-002]". Same claim, same marker, same grounds; one is an argument and one is a report about a book.
- Name a scholar in the sentence only when WHO holds the position is what the sentence is about: attributing a contested position, marking a disagreement, or crediting a specific formulation. That is a deliberate move, not the default shape.
- Do not walk the claims in the order they are listed, and do not give each claim its own sentence. Claims are evidence for the point, so several may support one sentence and some may carry a clause rather than a sentence.
- A section is not a summary of its claims. If it could be rewritten as "the literature says X, Y and Z", it has failed.

Voice is the other seam, and it is about honesty rather than style. A claim marked kind "a" is a SOURCE's assertion; you may state it as established and attribute it where attribution is the point. A claim marked "b" is this system's own inference across sources and must NEVER be voiced as though a source asserted it. A claim marked "c" is this paper's OWN verdict -- your judgment, never a source's -- and must be voiced the same honest way, as this paper's own conclusion. Write either in your own register, and do not launder either into "scholars have shown".

{_new_claims_block(has_visible_claims, cross_source_possible)}

Return JSON only:
{{"prose": "...", "new_claims": {_new_claims_example(has_visible_claims, cross_source_possible)}}}"""


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

        # Missing 'kind' defaults to "b": every new claim before issue #577
        # was a cross-source inference, and nothing else was ever asked.
        kind = entry.get("kind", "b")
        if kind not in {"b", "c"}:
            raise InvalidNewClaimKindError(section.section_id, local_id, kind)

        derived = [str(value) for value in (entry.get("derived_from") or [])]
        unknown = [
            value for value in derived if value not in visible_ids and value not in local_ids
        ]
        if unknown:
            raise UnknownDerivationError(section.section_id, local_id, unknown)

        local_ids.add(local_id.strip())
        new_claims.append(
            NewClaimDraft(
                local_id=local_id.strip(),
                text=text.strip(),
                derived_from=tuple(derived),
                kind=kind,
            )
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
                kind=claim.kind,
            )
            for claim in draft.new_claims
        ),
        retries=draft.retries,
    )


# Bounded retry (issue #598): first attempt plus up to two re-asks, same
# budget and same reasoning as `axial.paper.plan._MAX_ATTEMPTS` -- a fresh
# draw usually avoids whatever a rejected draw got wrong, and this is not
# the transport-level retry `llm.py` already runs.
_MAX_ATTEMPTS = 3


# `DraftError` has four subclasses today -- `DraftParseError`, the two
# new-claim validation errors `UnknownDerivationError` and
# `InvalidNewClaimKindError` issue #598 named as retryable, and
# `InsufficientRecordSpanError` (issue #616), the §7.4 span check moved
# inside this same retry -- so catching the shared base is equivalent to
# naming all four and simpler to keep in sync if a fifth is ever added
# deliberately.
def _log_draft_retry(section_id: str, attempt: int, error: DraftError) -> None:
    """One structured stderr line per rejected attempt (issue #598),
    matching `axial.paper.plan._log_plan_retry`'s convention."""
    print(
        f"paper_retry pass={PAPER_DRAFT_PASS_NAME} section={section_id} "
        f"attempt={attempt}/{_MAX_ATTEMPTS} validator={type(error).__name__}",
        file=sys.stderr,
    )


def _draft_retry_prompt(base_prompt: str, error: DraftError, attempt: int) -> str:
    """Re-ask with the error text appended -- not a repair loop, exactly
    like `axial.paper.plan._plan_retry_prompt`."""
    return (
        f"{base_prompt}\n\n"
        f"Your previous draft (attempt {attempt} of {_MAX_ATTEMPTS}) was rejected: {error}\n"
        "Write a new, complete section from scratch that does not repeat this mistake."
    )


def draft_section(
    client: Any,
    thesis_statement: str,
    lens: Lens,
    section: Section,
    claim_ids: dict[tuple[str, str], str],
    claims_by_id: dict[str, dict[str, Any]],
    already_cited: list[dict[str, Any]],
    cross_source_possible: bool = True,
) -> SectionDraft:
    """One section, with a bounded retry (issue #598) on `DraftError` --
    `DraftParseError`, the new-claim validation errors, and the §7.4 span
    check on a proposed (b) claim (issue #616), which used to run only after
    this function returned and was fatal on the first occurrence."""
    visible = {claim_ids[key] for key in section.assigned_claims}
    visible.update(str(claim.get("paper_claim_id")) for claim in already_cited)
    base_prompt = compose_draft_prompt(
        thesis_statement,
        lens,
        section,
        _claim_lines(section, claim_ids, claims_by_id),
        _earlier_lines(already_cited, claims_by_id),
        has_visible_claims=bool(visible),
        cross_source_possible=cross_source_possible,
    )
    prompt = base_prompt
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        raw = complete_json(client, prompt, pass_name=PAPER_DRAFT_PASS_NAME)
        try:
            draft = parse_draft_response(raw, section, visible)
            _check_record_span(draft, claims_by_id)
        except DraftError as exc:
            if attempt == _MAX_ATTEMPTS:
                raise
            _log_draft_retry(section.section_id, attempt, exc)
            prompt = _draft_retry_prompt(base_prompt, exc, attempt)
            continue
        return replace(draft, retries=attempt - 1)
    raise AssertionError("unreachable: the retry loop always returns or raises")
