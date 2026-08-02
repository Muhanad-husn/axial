"""The coherence sample spec (specs/PHASE-C.md §7.13, issue #611 P0-12).

A coherence measurement run reads a **committed** sample spec rather than
selecting its own sample, so a run is reproducible and a number is
attributable. Two stratification axes are required -- performance tier and
model combination -- because a single-tier or single-model-combination
sample answers no question the eval track exists to ask (§7.13): it cannot
say which configuration writes coherent papers, and it lets a system's best
work stand in for the system as a whole.

**`control_paper_id` is this module's one addition to §7.13's literal
schema.** The spec text names `sample_id`, `corpus_pin` and `strata` alone.
But §7.9 makes the positive control mandatory, and `axial.panel`'s own
existing analysis-record API (`run_control` / `run_panel`, issue #385)
already takes a control record as an explicit argument, distinct from the
sample and never inferred from it -- the same record shape needs the same
treatment here. §7.9 is explicit that a control paper which cannot carry all
three plants is "an operator error the harness refuses to absorb," which is
only nameable if a field exists to name it wrong. Leaving the choice
implicit (which paper, chosen how) would be the larger, quieter break.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SampleSpecError(Exception):
    """Base class for sample-spec failures."""


class SampleSpecParseError(SampleSpecError):
    """Raised when a sample spec file is missing a required field."""

    def __init__(self, path: Path, detail: str):
        self.path = path
        self.detail = detail
        super().__init__(f"sample spec {path}: {detail}")


class UnstratifiedAxisError(SampleSpecError):
    """Raised when a sample spans fewer than two values on a required
    stratification axis (§7.13). Names which axis and what it saw, so a
    single-tier sample is never confused with a single-model-combination
    one."""

    def __init__(self, axis: str, values: set[str]):
        self.axis = axis
        self.values = values
        super().__init__(
            f"sample spans only {sorted(values)!r} on the {axis!r} axis -- a "
            "coherence sample must span more than one, so a figure is never "
            "read off a single tier or a single model combination (§7.13)"
        )


@dataclass(frozen=True)
class Stratum:
    stratum_id: str
    tier: str
    model_combination: str
    paper_brief_ids: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "stratum_id": self.stratum_id,
            "tier": self.tier,
            "model_combination": self.model_combination,
            "paper_brief_ids": list(self.paper_brief_ids),
        }


@dataclass(frozen=True)
class SampleSpec:
    sample_id: str
    corpus_pin: str
    control_paper_id: str
    strata: tuple[Stratum, ...]

    def paper_brief_ids(self) -> list[str]:
        """Every paper named anywhere in the sample, in stratum order,
        deduplicated -- what the eval report's own frame lists as its
        `paper_brief_ids` (§7.13)."""
        seen: list[str] = []
        for stratum in self.strata:
            for paper_brief_id in stratum.paper_brief_ids:
                if paper_brief_id not in seen:
                    seen.append(paper_brief_id)
        return seen


def _validate_stratification(spec: SampleSpec) -> None:
    tiers = {stratum.tier for stratum in spec.strata}
    if len(tiers) < 2:
        raise UnstratifiedAxisError("performance tier", tiers)
    combinations = {stratum.model_combination for stratum in spec.strata}
    if len(combinations) < 2:
        raise UnstratifiedAxisError("model combination", combinations)


def load_sample_spec(path: Path) -> SampleSpec:
    """Load and validate a committed sample spec. Raises
    `UnstratifiedAxisError` before any paper record or panel call is
    touched -- a single-tier or single-model-combination sample is rejected
    outright, naming the unstratified axis."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        strata = tuple(
            Stratum(
                stratum_id=entry["stratum_id"],
                tier=entry["tier"],
                model_combination=entry["model_combination"],
                paper_brief_ids=tuple(entry["paper_brief_ids"]),
            )
            for entry in data["strata"]
        )
        spec = SampleSpec(
            sample_id=data["sample_id"],
            corpus_pin=data["corpus_pin"],
            control_paper_id=data["control_paper_id"],
            strata=strata,
        )
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise SampleSpecParseError(path, f"{type(exc).__name__}: {exc}") from exc

    _validate_stratification(spec)
    return spec
