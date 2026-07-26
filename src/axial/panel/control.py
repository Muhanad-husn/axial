"""The positive control (issue #385, specs/PHASE-B.md §9.4 property 6,
DEC-23).

**The panel produces no reportable number until it has caught planted
defects.** LLM judges are systematically generous and are moved by confident
prose, so a panel that waves a defective packet through is measuring
nothing, and its clean verdicts on real packets are worthless until it is
fixed. No live positive control exists anywhere else in this repo (#323);
this is the first.

**Plants are content-free transformations** (DEC-23). Nothing here writes
prose, invents a claim, or embeds chunk text: each plant is a deterministic
mutation of an existing record, driven by selectors over what the record
already holds. A committed fixture carrying book text is exactly what DEC-23
forbids, and a hand-written "bad analysis" would also measure the plant
author's prose rather than the panel.

The three plants are §9.4's stated minimum set, one per failure the panel
exists to catch:

- **mis_grounded** -- a claim's grounds are repointed at another claim's
  evidence, so it cites material that does not support it.
- **strawman_counter_position** -- the counter-position is repointed at the
  primary claim's own grounds, so the "opposition" rests on the very
  material it supposedly opposes.
- **overconfident** -- a claim over a polity the coverage map discloses as
  thin is raised to the `high` band.

A plant that cannot be applied to the given record is an **error**, never a
skip. A control that quietly plants two defects instead of three and then
passes is worse than no control.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from axial.panel.review import PanelReport, ReviewerVerdict

# A plant counts as caught when a MAJORITY of reviewers name it -- not one.
# The control exists to measure whether the panel is systematically
# generous; a single catcher among three is consistent with a panel that
# mostly waves defects through, which is the failure mode being tested for.
_MAJORITY = 0.5

MIS_GROUNDED = "mis_grounded"
STRAWMAN = "strawman_counter_position"
OVERCONFIDENT = "overconfident"

PLANT_KINDS: tuple[str, ...] = (MIS_GROUNDED, STRAWMAN, OVERCONFIDENT)

# The band a plant raises an under-evidenced claim to, and the coverage
# bands that count as "thin" for selecting one. Both read off §7.4/§7.7's
# own vocabularies rather than introducing a fourth.
_HIGH_BAND = "high"
_THIN_COVERAGE_BANDS = frozenset({"thin", "none"})


class ControlError(Exception):
    """Base class for positive-control failures."""


class PlantNotApplicableError(ControlError):
    """Raised when a record cannot carry one of the three plants. Never
    skipped silently (module docstring)."""

    def __init__(self, kind: str, reason: str):
        self.kind = kind
        self.reason = reason
        super().__init__(
            f"cannot plant a {kind!r} defect: {reason} -- pick a control "
            "record that can carry all three plants rather than running a "
            "partial control"
        )


@dataclass(frozen=True)
class Plant:
    """One planted defect and where it was planted, so the check knows what
    the panel was supposed to name."""

    kind: str
    claim_id: str


@dataclass(frozen=True)
class PlantOutcome:
    plant: Plant
    caught_by: int
    n_reviewers: int

    @property
    def caught(self) -> bool:
        return self.caught_by > self.n_reviewers * _MAJORITY

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.plant.kind,
            "claim_id": self.plant.claim_id,
            "caught": self.caught,
            "caught_by": self.caught_by,
            "n_reviewers": self.n_reviewers,
        }


@dataclass(frozen=True)
class ControlReport:
    """The control's own result, reported alongside every panel number so a
    reader can see which defects the referee is known to catch and which it
    is not (§9.4 property 6)."""

    outcomes: list[PlantOutcome]

    @property
    def passed(self) -> bool:
        return bool(self.outcomes) and all(outcome.caught for outcome in self.outcomes)

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "plants": [outcome.to_json() for outcome in self.outcomes],
        }


def _claims_with_grounds(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        claim
        for claim in record.get("claims") or []
        if isinstance(claim, dict) and claim.get("grounds")
    ]


def _claim_id_of(claim: dict[str, Any], index: int) -> str:
    return claim.get("claim_id") or f"<claim #{index}>"


def plant_mis_grounded(record: dict[str, Any]) -> tuple[dict[str, Any], Plant]:
    """Repoint the first claim's grounds at another claim's evidence. The
    claim now cites material that does not support it, and no prose moved."""
    mutated = copy.deepcopy(record)
    claims = _claims_with_grounds(mutated)
    if len(claims) < 2:
        raise PlantNotApplicableError(
            MIS_GROUNDED, "the record carries fewer than two claims with grounds"
        )
    target, donor = claims[0], None
    for candidate in claims[1:]:
        if candidate["grounds"] != target["grounds"]:
            donor = candidate
            break
    if donor is None:
        raise PlantNotApplicableError(
            MIS_GROUNDED, "every claim in the record cites the same grounds"
        )
    target["grounds"] = copy.deepcopy(donor["grounds"])
    return mutated, Plant(kind=MIS_GROUNDED, claim_id=_claim_id_of(target, 1))


def plant_strawman_counter_position(record: dict[str, Any]) -> tuple[dict[str, Any], Plant]:
    """Repoint the counter-position at the primary claim's own grounds, so
    the stated opposition rests on the material it opposes."""
    mutated = copy.deepcopy(record)
    counter = mutated.get("counter_position")
    if not isinstance(counter, dict) or not counter.get("present"):
        raise PlantNotApplicableError(STRAWMAN, "the record carries no present counter-position")
    claims = _claims_with_grounds(mutated)
    if not claims:
        raise PlantNotApplicableError(STRAWMAN, "the record carries no claim with grounds")
    counter["grounds"] = copy.deepcopy(claims[0]["grounds"])
    return mutated, Plant(kind=STRAWMAN, claim_id="<counter_position>")


def plant_overconfident(record: dict[str, Any]) -> tuple[dict[str, Any], Plant]:
    """Raise to `high` a claim over a polity the coverage map discloses as
    thin -- the band now asserts more than the evidence behind it. Matched
    against `polities_touched` (§7.4's own claim field, a list -- a claim
    can touch more than one polity), not a nonexistent singular `polity`
    field."""
    mutated = copy.deepcopy(record)
    coverage_map = mutated.get("coverage_map") or {}
    thin = {
        polity
        for polity, entry in coverage_map.items()
        if isinstance(entry, dict) and entry.get("coverage_band") in _THIN_COVERAGE_BANDS
    }
    if not thin:
        raise PlantNotApplicableError(
            OVERCONFIDENT, "the coverage map discloses no thin-coverage polity"
        )
    for index, claim in enumerate(mutated.get("claims") or [], start=1):
        if not isinstance(claim, dict):
            continue
        touched = set(claim.get("polities_touched") or [])
        if touched & thin and claim.get("confidence") != _HIGH_BAND:
            claim["confidence"] = _HIGH_BAND
            return mutated, Plant(kind=OVERCONFIDENT, claim_id=_claim_id_of(claim, index))
    raise PlantNotApplicableError(
        OVERCONFIDENT,
        "no claim sits over a thin-coverage polity at a band below 'high'",
    )


PLANTERS = {
    MIS_GROUNDED: plant_mis_grounded,
    STRAWMAN: plant_strawman_counter_position,
    OVERCONFIDENT: plant_overconfident,
}


def plant_all(record: dict[str, Any]) -> list[tuple[dict[str, Any], Plant]]:
    """Every plant, each applied to its own copy of `record`, in the stated
    order. Raises `PlantNotApplicableError` if any one cannot be applied."""
    return [PLANTERS[kind](record) for kind in PLANT_KINDS]


def _caught_by(verdicts: list[ReviewerVerdict], plant: Plant) -> int:
    """How many reviewers named a defect of the planted kind on the planted
    claim. The claim id must match too: naming the right defect on the wrong
    claim is not a catch."""
    count = 0
    for verdict in verdicts:
        if any(
            defect.kind == plant.kind and defect.claim_id == plant.claim_id
            for defect in verdict.defects
        ):
            count += 1
    return count


def score_control(results: list[tuple[Plant, PanelReport]]) -> ControlReport:
    """Score one panel report per plant into a control verdict. `passed`
    requires EVERY plant caught by a majority of reviewers -- a panel that
    catches two of three is a panel with a known blind spot, and its clean
    verdicts on real packets cannot be trusted past it."""
    return ControlReport(
        outcomes=[
            PlantOutcome(
                plant=plant,
                caught_by=_caught_by(report.reviewers, plant),
                n_reviewers=len(report.reviewers),
            )
            for plant, report in results
        ]
    )


def format_control_report(report: ControlReport) -> str:
    lines = ["positive control:"]
    for outcome in report.outcomes:
        verdict = "CAUGHT" if outcome.caught else "MISSED"
        lines.append(
            f"  {outcome.plant.kind}: {verdict} "
            f"({outcome.caught_by}/{outcome.n_reviewers} reviewers, "
            f"claim={outcome.plant.claim_id})"
        )
    lines.append(f"passed: {report.passed}")
    if not report.passed:
        lines.append("no panel number is reportable until every plant is caught (§9.4 property 6)")
    return "\n".join(lines)
