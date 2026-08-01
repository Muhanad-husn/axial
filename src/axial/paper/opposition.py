"""Stage 1.5: the opposition gap-and-repair pass (specs/PHASE-C.md §7.1x,
§3, §7.11; issue #570, DEC-60, issues #568/#569).

**Placement (orchestrator decision, 2026-08-01): after intake, before
planning.** `who_argues_against` keys on canonical names, and a new (b)
claim's `names_touched` is the union of the claims it derives from, so
drafting adds no name intake did not already hold and `reduce_to_cited` only
removes. The intake-time name set is therefore a superset of the post-draft
one: an early check finds every gap a late one would, plan and draft run once
instead of twice, and no re-draft can open a fresh gap.

**Decision 1 (founder): Phase C retrieves directly**, through the existing
deterministic query API -- never by commissioning a bounded Phase B run. The
tool returns real vault ids, so the layer cannot invent opposition to look
balanced (#570 rule 1: no new trust surface).

**What this measures is a FLOOR, and the reason is a join, not a content gap
(founder measurement, 2026-08-01).** `who_argues_against` finds an opposing
note by exact-matching a note's own `arguing_against` answer against a
canonical name page. `arguing_against` stores PROSE, not a pointer: across
4,695 notes carrying 10,883 targets, only **4.7%** exact-match a name page
this way. The other 95.3% are free text -- 91.2% run longer than three words,
values like "the assumption that all peasants can be lumped together
politically" or "a macro-structural Weberianism that gives no room to
agency" -- and 87.0% of THOSE contain a real canonical name of 6+ characters
somewhere inside the string (4,716 concept, 1,628 institution/group, 786
movement/religion, 687 person). So the miss is not that the opposition went
unnamed; it is that the join cannot parse a name back out of a sentence. A
zero from this pass means no EXACT-MATCH opposition went unread -- never that
the corpus holds no counter-argument, and never that the unmatched 95.3% was
unnamed. `OPPOSITION_GAP_SCOPE_NOTE` is the one sentence, carrying this
number, that travels with every count this module produces, into the record
and the rendered paper alike.

**The lookup is an injected parameter, not a hardcoded call (founder
direction, 2026-08-01).** A richer resolution pass that recovers targets from
free text is real, separate, future work, and it must slot in without anyone
reopening the gap arithmetic, the repair retrieval, the record shape or the
disclosure below. `run_opposition_repair`'s `lookup` parameter is exactly
that seam: it defaults to `axial.query.names.who_argues_against` and takes
the same `(canonical, limit, *, vault_dir, names_dir) -> (edges, total)`
shape, so everything downstream of the edge set -- already-read filtering,
claim shaping, the trajectory, the coverage map, the two gap counts -- is
correct regardless of which lookup produced the edges.

**Step 1: the gap, recorded before anything repairs it (#570 rule 3).** Over
every name the intake inventory's claims touch, the lookup is called once. An
edge is "already read" when its chunk id appears in some named source
record's own retrieval trajectory (issue #556's persisted §7.6 log:
`result_ids` on a chunk-returning tool call) OR among that record's own
claims' grounds -- the union of both, which is the more generous reading, so
an analysis record that saw a note but never cited it is still credited with
having read it. Understating "already read" is what overstates the gap.

**Step 2: retrieval only happens where the gap is non-zero.** A trajectory
entry is appended, and the pass proceeds to shape claims, only for a name the
lookup returned unread material for. Most names in a real inventory will not
fire this at all (#570 rule 2): there is nothing to pay for beyond the lookup
itself, which -- for the default `who_argues_against` -- is a plain, free
vault read, not a retrieval loop, not a model call, not the
commissioned-Phase-B-run alternative the founder rejected.

**Step 3: shaping, with ZERO model calls.** `OppositionEdge` already carries
`chunk_id` (a real vault id), `source_id`, and the note's own one-sentence
`claim` -- a source's own assertion, with grounds that come out of the index
together with the text, so generate-then-cite stays structurally impossible.
Measured over the real corpus (2026-08-01, `D:/axial/data/vault/prose`,
6,148 live notes): 6,009 (97.7%) carry a real `claim` answer; 139 (2.3%)
carry the `not-in-passage` abstention. This module skips those rather than
inventing text for them -- `skipped_abstentions` on `OppositionRepair` counts
them.

**Every repair claim is injected into the intake as though it came from an
extra source record** (`REPAIR_BRIEF_ID`), whose own `coverage_map` is
computed natively over the repair pass's own trajectory via
`axial.validators.coverage.compute_coverage_map` -- the same intersection
Phase B computes for a real analysis record, now possible because the paper
has a trajectory to compute it over (§7.11's founder amendment). This is what
makes "repaired claims flow through everything else unchanged" literally
true: `axial.paper.claims.carried_claim` clamps a repair claim's band exactly
as it clamps any carried claim, reading `intake.records[REPAIR_BRIEF_ID]
["coverage_map"]` the same way it reads any real source record's map, and the
provenance-integrity gate, the grounding gate and the (b)-seam gate need no
special case for a repair claim at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from axial.paper.intake import InventoryClaim, PaperIntake
from axial.query.names import DEFAULT_LIMIT, OppositionEdge, who_argues_against
from axial.query.reader import NOT_IN_PASSAGE
from axial.validators.coverage import compute_coverage_map

# The synthetic "source" a repair claim's `origin.brief_id` names. Never a
# real Phase-B `brief_id` -- naming it distinctly is what lets a reader (or
# `assert_ceilings`, `build_claims`, the citation table) tell a repair claim
# apart from a carried one at a glance, while every existing code path that
# resolves a claim's origin against `intake.records`/`intake.by_key()` needs
# no change at all to do so (§7.4's `origin` shape is reused unchanged).
REPAIR_BRIEF_ID = "phase-c-opposition-repair"

# The tool name every trajectory entry this module writes carries. Fixed to
# the query API's own name even when `lookup` is overridden: the entry
# describes what §7.5 CALL shape the edges came through, and a future
# resolution pass that still ultimately reads `arguing_against` should keep
# recording itself this way unless it changes the underlying call.
_TOOL_NAME = "who_argues_against"

# The lookup this module calls once per anchor name: `(canonical, limit, *,
# vault_dir, names_dir) -> (edges, total)`. A parameter, not a hardcoded call
# (founder direction, 2026-08-01) -- a future resolution pass that recovers
# opposition from free-text `arguing_against` targets (today only 4.7% of
# them exact-match a name page) is separate work, and it slots in here
# without touching anything downstream.
OppositionLookup = Callable[..., tuple[list[OppositionEdge], int]]

# The one sentence that must travel with every gap/repair number this module
# produces (founder measurement, 2026-08-01): the join's true recall, stated
# as a number rather than a bare caveat, and why it is a floor rather than a
# claim about the corpus. See the module docstring for the full measurement.
OPPOSITION_GAP_SCOPE_NOTE = (
    "this only counts opposition whose target text EXACTLY MATCHES a name page "
    "(today's who_argues_against join); measured 2026-08-01 over 4,695 notes / "
    "10,883 recorded arguing_against targets, only 4.7% exact-match this way -- "
    "91.2% of targets are free text longer than three words, and 87.0% of THOSE "
    "contain a real canonical name inside the string that the join cannot parse "
    "out. So this measure is a FLOOR: a zero here means no exact-match "
    "opposition went unread, never that the corpus holds no counter-argument, "
    "and never that the unmatched opposition had no name in it"
)


def _names_the_inventory_touches(intake: PaperIntake) -> list[str]:
    """Every canonical name the intake inventory's claims touch (§7.4's
    `names_touched`), sorted -- the anchor set the gap check runs over.

    Deliberately every claim already in the inventory, not only what a later
    plan assigns or a draft cites: the orchestrator's placement decision
    (issue #570) is that this early, wider check finds every gap a later,
    narrower one would."""
    names: set[str] = set()
    for entry in intake.inventory:
        for name in entry.claim.get("names_touched") or []:
            if isinstance(name, str) and name:
                names.add(name)
    return sorted(names)


# Trajectory tools whose `result_ids` are real chunk/artifact ids rather than
# canonical names or a bare source id -- restated locally rather than
# imported from `axial.retrieve.tools`, which pulls the tool-dispatch loop
# Phase C has no reason to depend on. Mirrors the same local-restatement
# choice `axial.validators.coverage` already makes for its own
# `NAME_ARG_TOOLS`/`NAME_RESULT_TOOLS`.
_CHUNK_RESULT_TOOLS = frozenset(
    {
        "get_chunk",
        "get_artifact",
        "get_name",
        "who_cites",
        "who_argues_against",
        "where_names_meet",
        "query_by_source",
    }
)


def _already_read_chunk_ids(record: dict[str, Any]) -> set[str]:
    """Every chunk id one source record already surfaced: its own §7.6
    trajectory (issue #556's persisted log) union its own claims' grounds.

    The union, not either alone, is the generous reading -- a note the
    retrieval loop saw but the synthesis model did not cite is still "already
    read", and understating this set is what overstates the gap. A record
    with no `trajectory` at all (an older record, or a hand-built fixture)
    still degrades to its claims' grounds rather than crashing."""
    read: set[str] = set()
    trajectory = record.get("trajectory")
    if isinstance(trajectory, list):
        for entry in trajectory:
            if not isinstance(entry, dict) or entry.get("tool") not in _CHUNK_RESULT_TOOLS:
                continue
            for chunk_id in entry.get("result_ids") or []:
                if isinstance(chunk_id, str):
                    read.add(chunk_id)
    for claim in record.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for ground in claim.get("grounds") or []:
            if isinstance(ground, dict) and ground.get("ref_type") == "chunk":
                ref_id = ground.get("ref_id")
                if isinstance(ref_id, str):
                    read.add(ref_id)
    return read


@dataclass(frozen=True)
class OppositionGap:
    """One anchor name's gap: the lookup's edges for `canonical`, restricted
    to the notes no named source record already read.

    `checked`/`total` are the lookup's own capped/pre-cap counts (issue
    #505's shape, which `who_argues_against` follows): a hub name can carry
    far more opposition edges than `limit`, and the true total travels
    beside the window exactly as it does everywhere else this product reads
    that tool."""

    canonical: str
    gap_edges: tuple[OppositionEdge, ...]
    checked: int
    already_read: int
    total: int


@dataclass(frozen=True)
class OppositionRepair:
    """Stage 1.5's whole output: the gap as found, what got shaped into
    claims, and the trajectory that carries the repair pass's own retrieval
    (#570 rule 3 -- the gap survives the repair; §7.3's amendment)."""

    names_checked: tuple[str, ...]
    gaps: tuple[OppositionGap, ...] = ()
    repair_claims: tuple[InventoryClaim, ...] = ()
    skipped_abstentions: int = 0
    trajectory: tuple[dict[str, Any], ...] = ()
    coverage_map: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def gap_found(self) -> int:
        """Distinct opposing notes not already read, across every checked
        name (deduplicated: one note can oppose more than one anchor)."""
        seen: set[str] = set()
        for gap in self.gaps:
            seen.update(edge.chunk_id for edge in gap.gap_edges)
        return len(seen)

    @property
    def gap_repaired(self) -> int:
        return len(self.repair_claims)

    def gap_restricted_to(self, names: set[str]) -> int:
        """The same `gap_found` count, restricted to a name subset -- the
        "gap over what the finished paper actually cited" disclosure (#570's
        placement decision: the gap is computed over every source claim, so
        it can repair opposition to a name the paper does not end up
        citing, and both numbers are reported, labelled)."""
        seen: set[str] = set()
        for gap in self.gaps:
            if gap.canonical not in names:
                continue
            seen.update(edge.chunk_id for edge in gap.gap_edges)
        return len(seen)

    def by_name(self) -> dict[str, dict[str, int]]:
        """A per-name breakdown of what was found and what got repaired,
        sorted -- the detail behind the record's two headline counts."""
        repaired_by_name: dict[str, int] = {}
        for entry in self.repair_claims:
            for name in entry.claim.get("names_touched") or []:
                repaired_by_name[name] = repaired_by_name.get(name, 0) + 1
        return {
            gap.canonical: {
                "gap_found": len(gap.gap_edges),
                "gap_repaired": repaired_by_name.get(gap.canonical, 0),
                "already_read": gap.already_read,
                "total_opposition_edges": gap.total,
            }
            for gap in sorted(self.gaps, key=lambda entry: entry.canonical)
        }


def run_opposition_repair(
    intake: PaperIntake,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    lookup: OppositionLookup = who_argues_against,
) -> OppositionRepair:
    """Stage 1.5, end to end: compute the gap over every name the intake
    inventory touches, and -- only for a name the gap is non-zero on --
    shape what `lookup` returns into kind-(a) claims with zero model calls
    (#570 rules 1-3).

    `lookup` defaults to `axial.query.names.who_argues_against` and is the
    seam a future, richer opposition-resolution pass replaces (module
    docstring): everything below this call -- already-read filtering, claim
    shaping, the trajectory, the coverage map, both gap counts -- is correct
    for whatever edge set `lookup` returns."""
    names_checked = tuple(_names_the_inventory_touches(intake))

    already_read: set[str] = set()
    for record in intake.records.values():
        already_read |= _already_read_chunk_ids(record)

    gaps: list[OppositionGap] = []
    repair_claims: list[InventoryClaim] = []
    trajectory: list[dict[str, Any]] = []
    skipped_abstentions = 0

    for name in names_checked:
        edges, total = lookup(name, limit, vault_dir=vault_dir, names_dir=names_dir)
        gap_edges = tuple(edge for edge in edges if edge.chunk_id not in already_read)
        if not gap_edges:
            continue

        trajectory.append(
            {
                "step": len(trajectory) + 1,
                "tool": _TOOL_NAME,
                "args": {"canonical": name},
                "result_ids": [edge.chunk_id for edge in edges],
                "result_count": len(edges),
                "total": total,
                "detail": None,
            }
        )
        gaps.append(
            OppositionGap(
                canonical=name,
                gap_edges=gap_edges,
                checked=len(edges),
                already_read=len(edges) - len(gap_edges),
                total=total,
            )
        )

        for edge in gap_edges:
            if edge.claim is None or edge.claim == NOT_IN_PASSAGE:
                skipped_abstentions += 1
                continue
            claim_dict = {
                "claim_id": edge.chunk_id,
                "kind": "a",
                "text": edge.claim,
                # Emitted at the top band deliberately: there is no model
                # judgment behind this claim to disclose, so the CEILING --
                # never the emitted value -- is what governs the band that
                # actually renders, exactly as it does for every other
                # carried claim (`axial.paper.claims.carried_claim`,
                # `clamped_band_for`).
                "confidence": "high",
                "grounds": [{"ref_type": "chunk", "ref_id": edge.chunk_id}],
                "names_touched": [name],
            }
            repair_claims.append(
                InventoryClaim(brief_id=REPAIR_BRIEF_ID, claim_id=edge.chunk_id, claim=claim_dict)
            )

    coverage_map: dict[str, dict[str, Any]] = {}
    if repair_claims:
        coverage_map = compute_coverage_map(
            [entry.claim for entry in repair_claims], trajectory=trajectory, vault_dir=vault_dir
        )

    return OppositionRepair(
        names_checked=names_checked,
        gaps=tuple(gaps),
        repair_claims=tuple(repair_claims),
        skipped_abstentions=skipped_abstentions,
        trajectory=tuple(trajectory),
        coverage_map=coverage_map,
    )


def extend_intake(intake: PaperIntake, repair: OppositionRepair) -> PaperIntake:
    """Merge a repair pass's claims into the intake inventory, as though they
    came from one extra source record (`REPAIR_BRIEF_ID`) whose own
    `coverage_map` is the repair pass's own earned map.

    A no-op, returning `intake` unchanged, when nothing was repaired -- so a
    zero-gap run pays nothing beyond the lookups already made and carries no
    trace of a pass that found nothing to add."""
    if not repair.repair_claims:
        return intake

    return replace(
        intake,
        records={**intake.records, REPAIR_BRIEF_ID: {"coverage_map": repair.coverage_map}},
        inventory=intake.inventory + repair.repair_claims,
    )
