"""Rung-3 eval gates: pass/fail harnesses scoring an analysis engine's
attribution fidelity and grounding over a directory of analysis records
(specs/PHASE-B.md §10, §8 P0-12, issue #262).

Slice 01 ships the common gate shape (`axial.gates.harness`) plus two gates:
`attribution-fidelity` (`axial.gates.attribution`) and `grounding`
(`axial.gates.grounding`). Later slices (issues #263, #264) plug additional
gates into `GATE_RUNNERS` without reshaping this package -- see
plans/rung3-gates/README.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.gates.attribution import GATE_NAME as ATTRIBUTION_FIDELITY_GATE_NAME
from axial.gates.attribution import run_attribution_fidelity_gate
from axial.gates.grounding import GATE_NAME as GROUNDING_GATE_NAME
from axial.gates.grounding import (
    GroundingCheckFailedError,
    GroundingGateError,
    SelfGradingError,
    UnresolvableGroundsError,
    run_grounding_gate,
)
from axial.gates.harness import (
    CASES_DIR,
    REPORTS_DIR,
    GateError,
    GateReport,
    MetricResult,
    academic_cases_present,
    format_report,
    load_records,
    resolve_corpus_pin,
    resolve_trusted,
    write_report,
)
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient

# Every gate this package ships, dispatched by its CLI name (`axial gate run
# <name>`). Each runner shares the exact same call shape -- `(records, *,
# client, vault_dir, corpus_pin, trusted, config_path) -> GateReport` -- so a
# later slice adds a gate here without touching the CLI's dispatch logic.
GATE_RUNNERS = {
    ATTRIBUTION_FIDELITY_GATE_NAME: run_attribution_fidelity_gate,
    GROUNDING_GATE_NAME: run_grounding_gate,
}


class UnknownGateError(GateError):
    """Raised when `run_gate` is asked for a gate name not in `GATE_RUNNERS`."""

    def __init__(self, gate: str):
        self.gate = gate
        super().__init__(f"unknown gate {gate!r}; expected one of {sorted(GATE_RUNNERS)!r}")


def run_gate(
    gate: str,
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Dispatch to `gate`'s runner in `GATE_RUNNERS`. Raises
    `UnknownGateError` for an unregistered name."""
    runner = GATE_RUNNERS.get(gate)
    if runner is None:
        raise UnknownGateError(gate)
    return runner(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=corpus_pin,
        trusted=trusted,
        config_path=config_path,
    )


__all__ = [
    "ATTRIBUTION_FIDELITY_GATE_NAME",
    "GROUNDING_GATE_NAME",
    "GATE_RUNNERS",
    "CASES_DIR",
    "REPORTS_DIR",
    "GateError",
    "GateReport",
    "MetricResult",
    "GroundingCheckFailedError",
    "GroundingGateError",
    "SelfGradingError",
    "UnresolvableGroundsError",
    "UnknownGateError",
    "academic_cases_present",
    "format_report",
    "load_records",
    "resolve_corpus_pin",
    "resolve_trusted",
    "run_attribution_fidelity_gate",
    "run_gate",
    "run_grounding_gate",
    "write_report",
]
