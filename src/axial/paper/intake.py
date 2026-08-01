"""Paper-brief intake stage 1: resolve the named analysis records and build
the claim inventory (specs/PHASE-C.md §7.1, §8 P0-1).

**Zero Phase-B invocations, structurally** (§3 non-goal 1). Nothing in this
module imports `axial.answer`, `axial.analyze` or `axial.brief`'s run path.
A paper brief naming a brief that has not been run fails with an error telling
the operator to run it through Phase B first; it never runs one. That is a
property of the import graph, not of a promise in a docstring, and the
acceptance test asserts it against `sys.modules`.

Three rejections, all mechanical and all blocking (§7.1):

1. an id that resolves to no record under `data/analyses/`;
2. a record whose `interrogation.disposition` is `refuse` -- a valid, complete
   Phase-B outcome that carries no claims, so it is not material for a paper;
3. a mixed `corpus_pin` set.

**Contradiction between records is NOT on that list and must never be added
to it** (§7.14, DEC-45). Two records arguing opposite sides are opposing
arguments -- the substance of the domain -- and are handled by charter
Principle IV at paper scale, never at this gate.

The pin rejection bites harder since Phase B v1 re-cut the pin (D6): its vault
hash now covers the name-layer index, so a Gather run, a name merge or a
materialize moves it. Records straddling one of those do not share a pin, and
the operator runs every brief for a paper inside one pin window (§7.1).

LLM-free by construction: pure file I/O over persisted records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.paths import default_analyses_dir

# `interrogation.disposition` values that carry no claims. §7.1 names
# `refuse`; the other dispositions (`proceed`, `proceed_bounded`) are all
# valid paper material.
_REFUSAL_DISPOSITION = "refuse"


class PaperIntakeError(Exception):
    """Base class for all paper-intake failures."""


class UnresolvableAnalysisError(PaperIntakeError):
    """Raised when a named `analysis_ids` entry resolves to no record.

    The message names the id and tells the operator to run it through Phase B,
    because Phase C never will (§3 non-goal 1)."""

    def __init__(self, brief_id: str, path: Path):
        self.brief_id = brief_id
        self.path = path
        super().__init__(
            f"paper brief names analysis {brief_id!r}, but no record exists at {path}; "
            f"run that brief through Phase B first (`axial brief run`) -- Phase C never "
            f"runs Phase B"
        )


class MalformedAnalysisError(PaperIntakeError):
    """Raised when a named record exists but is not a JSON object."""

    def __init__(self, brief_id: str, path: Path, reason: str):
        self.brief_id = brief_id
        self.path = path
        self.reason = reason
        super().__init__(f"analysis record {brief_id!r} at {path} is unreadable: {reason}")


class RefusedAnalysisError(PaperIntakeError):
    """Raised when a named record's disposition is `refuse` (§7.1).

    A refusal is a COMPLETE Phase-B run and a valid outcome, not an error one
    layer down. It is simply not material for a paper, because it carries no
    claims -- so the wording must not read as though the record were broken."""

    def __init__(self, brief_id: str):
        self.brief_id = brief_id
        super().__init__(
            f"analysis {brief_id!r} was refused by its interrogation pre-pass, so it "
            f"carries no claims; a refusal is a valid Phase-B outcome, but it is not "
            f"material for a paper -- drop it from the paper brief"
        )


class MixedCorpusPinError(PaperIntakeError):
    """Raised when the named records do not share one `corpus_pin` (§7.1)."""

    def __init__(self, pins_by_brief_id: dict[str, Any]):
        self.pins_by_brief_id = dict(pins_by_brief_id)
        rendered = ", ".join(
            f"{brief_id}={pin!r}" for brief_id, pin in sorted(pins_by_brief_id.items())
        )
        super().__init__(
            f"the named analysis records were produced against different corpora, so a "
            f"paper across them is not defensible: {rendered}. Re-run the stale briefs so "
            f"every record a paper draws on shares one pin (§7.1)"
        )


@dataclass(frozen=True)
class InventoryClaim:
    """One claim in the inventory, keyed by `(brief_id, claim_id)` (§7.1).

    `claim` is the source record's own claim dict, carried unmodified -- this
    stage copies nothing and re-derives nothing, so a later stage always sees
    exactly what Phase B persisted."""

    brief_id: str
    claim_id: str
    claim: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return (self.brief_id, self.claim_id)


@dataclass(frozen=True)
class PaperIntake:
    """Stage 1's whole output: the resolved records, their shared pin, and the
    claim inventory that is the drafter's entire world (§7.1, §4)."""

    corpus_pin: Any
    source_analyses: tuple[str, ...]
    records: dict[str, dict[str, Any]]
    inventory: tuple[InventoryClaim, ...]

    def by_key(self) -> dict[tuple[str, str], InventoryClaim]:
        """The inventory keyed by `(brief_id, claim_id)`, which is how a plan
        addresses a claim (§7.2's `assigned_claims`)."""
        return {entry.key: entry for entry in self.inventory}

    def record_for(self, brief_id: str) -> dict[str, Any]:
        return self.records[brief_id]


def _analysis_path(brief_id: str, analyses_dir: Path) -> Path:
    return analyses_dir / f"{brief_id}.json"


def _load_analysis(brief_id: str, analyses_dir: Path) -> dict[str, Any]:
    path = _analysis_path(brief_id, analyses_dir)
    if not path.is_file():
        raise UnresolvableAnalysisError(brief_id, path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MalformedAnalysisError(brief_id, path, str(exc)) from exc
    if not isinstance(record, dict):
        raise MalformedAnalysisError(brief_id, path, "not a JSON object")
    return record


def _reject_refusal(brief_id: str, record: dict[str, Any]) -> None:
    interrogation = record.get("interrogation")
    disposition = interrogation.get("disposition") if isinstance(interrogation, dict) else None
    if disposition == _REFUSAL_DISPOSITION:
        raise RefusedAnalysisError(brief_id)


def _require_one_pin(records: dict[str, dict[str, Any]]) -> Any:
    pins = {brief_id: record.get("corpus_pin") for brief_id, record in records.items()}
    distinct = {json.dumps(pin, sort_keys=True) for pin in pins.values()}
    if len(distinct) > 1:
        raise MixedCorpusPinError(pins)
    return next(iter(pins.values()))


def _inventory_for(brief_id: str, record: dict[str, Any]) -> list[InventoryClaim]:
    """Every claim in one record, in record order.

    A claim with no `claim_id` is skipped rather than given a positional
    fallback: the inventory is addressed by `(brief_id, claim_id)`, and an id
    invented here would be an id no source record carries, so a plan citing it
    would resolve against nothing real."""
    claims = record.get("claims")
    if not isinstance(claims, list):
        return []
    entries: list[InventoryClaim] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            continue
        entries.append(InventoryClaim(brief_id=brief_id, claim_id=claim_id, claim=claim))
    return entries


def run_intake(
    analysis_ids: tuple[str, ...] | list[str],
    *,
    analyses_dir: Path | None = None,
) -> PaperIntake:
    """Resolve every named record, apply §7.1's three rejections, and build
    the claim inventory.

    Rejections are applied in the order §7.1 states them, and each names the
    offending id. Resolution and refusal are per-record and fail on the first
    offender; the pin check is over the whole set and names every id with its
    pin, because "which one is wrong" is not a question a mixed set answers."""
    analyses_dir = Path(analyses_dir) if analyses_dir is not None else default_analyses_dir()

    ordered_ids = tuple(analysis_ids)
    records: dict[str, dict[str, Any]] = {}
    for brief_id in ordered_ids:
        record = _load_analysis(brief_id, analyses_dir)
        _reject_refusal(brief_id, record)
        records[brief_id] = record

    corpus_pin = _require_one_pin(records)

    inventory: list[InventoryClaim] = []
    for brief_id in ordered_ids:
        inventory.extend(_inventory_for(brief_id, records[brief_id]))

    return PaperIntake(
        corpus_pin=corpus_pin,
        source_analyses=ordered_ids,
        records=records,
        inventory=tuple(inventory),
    )
