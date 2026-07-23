"""Rung-3 eval gates: pass/fail harnesses scoring an analysis engine's
attribution fidelity, grounding, synthesis quality, calibration, and
adversarial-brief red-teaming (specs/PHASE-B.md §10, §8 P0-12, issues #262,
#263, #264).

Slice 01 shipped the common gate shape (`axial.gates.harness`) plus two
gates: `attribution-fidelity` (`axial.gates.attribution`) and `grounding`
(`axial.gates.grounding`). Slice 02 (issue #263) adds `synthesis-quality`
(`axial.gates.synthesis_quality`) and `calibration`
(`axial.gates.calibration`). Slice 03 (issue #264) adds `adversarial`
(`axial.gates.adversarial`) into `GATE_RUNNERS` without reshaping this
package -- see plans/rung3-gates/README.md. Unlike the others, the
adversarial gate's `records` argument is a `list[SeededBrief]` (loaded via
`axial.gates.adversarial.load_seeded_briefs` from a directory of seeded YAML
briefs, not `load_records`'s JSON analysis records) -- the CLI's `_gate_run`
picks the right loader per gate name; this module's shared dispatch shape is
unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.gates.adversarial import GATE_NAME as ADVERSARIAL_GATE_NAME
from axial.gates.adversarial import (
    AdversarialGateError,
    InvalidExpectedDispositionError,
    InvalidSeededKindError,
    MalformedSeededBlockError,
    MissingSeededBlockError,
    PremiseMatchCheckFailedError,
    SeededBrief,
)
from axial.gates.adversarial import SelfGradingError as AdversarialSelfGradingError
from axial.gates.adversarial import load_seeded_briefs, run_adversarial_gate
from axial.gates.attribution import GATE_NAME as ATTRIBUTION_FIDELITY_GATE_NAME
from axial.gates.attribution import run_attribution_fidelity_gate
from axial.gates.calibration import GATE_NAME as CALIBRATION_GATE_NAME
from axial.gates.calibration import (
    CalibrationCheckFailedError,
    CalibrationGateError,
    InvalidConfidenceBandError,
)
from axial.gates.calibration import SelfGradingError as CalibrationSelfGradingError
from axial.gates.calibration import run_calibration_gate
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
from axial.gates.synthesis_quality import GATE_NAME as SYNTHESIS_QUALITY_GATE_NAME
from axial.gates.synthesis_quality import run_synthesis_quality_gate
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient

# Every gate this package ships, dispatched by its CLI name (`axial gate run
# <name>`). Each runner shares the exact same call shape -- `(records, *,
# client, vault_dir, corpus_pin, trusted, config_path) -> GateReport` -- so a
# later slice adds a gate here without touching the CLI's dispatch logic.
GATE_RUNNERS = {
    ATTRIBUTION_FIDELITY_GATE_NAME: run_attribution_fidelity_gate,
    GROUNDING_GATE_NAME: run_grounding_gate,
    SYNTHESIS_QUALITY_GATE_NAME: run_synthesis_quality_gate,
    CALIBRATION_GATE_NAME: run_calibration_gate,
    ADVERSARIAL_GATE_NAME: run_adversarial_gate,
}


class UnknownGateError(GateError):
    """Raised when `run_gate` is asked for a gate name not in `GATE_RUNNERS`."""

    def __init__(self, gate: str):
        self.gate = gate
        super().__init__(f"unknown gate {gate!r}; expected one of {sorted(GATE_RUNNERS)!r}")


def run_gate(
    gate: str,
    records: list[Any],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Dispatch to `gate`'s runner in `GATE_RUNNERS`. Raises
    `UnknownGateError` for an unregistered name. `records` is a
    `list[dict[str, Any]]` for `attribution-fidelity`/`grounding` (analysis
    records) or a `list[SeededBrief]` for `adversarial` (module docstring) --
    whichever loader the caller used to build it."""
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
    "ADVERSARIAL_GATE_NAME",
    "ATTRIBUTION_FIDELITY_GATE_NAME",
    "GROUNDING_GATE_NAME",
    "SYNTHESIS_QUALITY_GATE_NAME",
    "CALIBRATION_GATE_NAME",
    "GATE_RUNNERS",
    "CASES_DIR",
    "REPORTS_DIR",
    "CalibrationCheckFailedError",
    "CalibrationGateError",
    "CalibrationSelfGradingError",
    "AdversarialGateError",
    "AdversarialSelfGradingError",
    "GateError",
    "GateReport",
    "InvalidConfidenceBandError",
    "MetricResult",
    "GroundingCheckFailedError",
    "GroundingGateError",
    "InvalidExpectedDispositionError",
    "InvalidSeededKindError",
    "MalformedSeededBlockError",
    "MissingSeededBlockError",
    "PremiseMatchCheckFailedError",
    "SeededBrief",
    "SelfGradingError",
    "UnresolvableGroundsError",
    "UnknownGateError",
    "academic_cases_present",
    "format_report",
    "load_records",
    "load_seeded_briefs",
    "resolve_corpus_pin",
    "resolve_trusted",
    "run_adversarial_gate",
    "run_attribution_fidelity_gate",
    "run_calibration_gate",
    "run_gate",
    "run_grounding_gate",
    "run_synthesis_quality_gate",
    "write_report",
]
