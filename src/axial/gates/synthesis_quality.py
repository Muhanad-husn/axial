"""The synthesis-quality rung-3 gate (issue #263, specs/PHASE-B.md §10,
charter Principle IV).

Two metrics, scored per analysis record by reusing
`axial.validators.counter_position.validate_counter_position` (issue #259)
wholesale -- contested detection and the presence-or-disclosure check are
not re-derived here:

- `counter_position_presence_rate` -- the share of the CONTESTED-brief
  subset (the same §7.8 contested predicate `validate_counter_position`
  itself computes) that is present-or-disclosed. An uncontested record is
  excluded from the denominator entirely, never counted as a pass; a record
  set with zero contested records reports `n: 0` and **not-scoreable**
  (issue #401) -- never a vacuous pass, and never the hard-gate "no claims
  found to evaluate" failure either, since the records here may well carry
  claims (the empty thing is the contested subset, not the claim set).
- `steelman_quality` -- the share of records carrying a counter-position
  that is genuinely present-with-grounds (regardless of contested-ness,
  mirroring `validate_counter_position`'s own rule) whose bounded
  steelman-quality check verdicts "steelman" rather than "strawman".
  `validate_counter_position` already runs this check anchored to the
  counter-position's own `grounds` text, under `COUNTER_POSITION_PASS_NAME`
  (distinct from `SYNTHESIZE_PASS_NAME`), guarded against self-grading --
  this gate reuses that verdict as its operationalization of "the eval #1
  rubric bar" (§10). Authoring a written rubric checklist is explicitly out
  of this slice's scope (issue #263: "the rubric is the Academic's and
  swaps in without a code change"); a steelman/strawman verdict against the
  cited grounds is the closest existing quality bar to reuse rather than
  invent a second judge seam ahead of the rubric landing. A record set with
  zero present-with-grounds counter-positions reports `n: 0` and
  **not-scoreable** (issue #401), not the vacuous `passed: true` this used
  to report -- a gate that passes on zero observations reads as a green
  light for a check that never ran.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.gates.harness import (
    GateReport,
    build_metric_result,
    not_scoreable_metric,
)
from axial.llm import COUNTER_POSITION_PASS_NAME, DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.validators.counter_position import (
    REASON_CONTESTED_WITHOUT_COUNTER_POSITION,
    VERDICT_STEELMAN,
    validate_counter_position,
)

GATE_NAME = "synthesis-quality"


def _record_id(record: dict[str, Any], index: int) -> str:
    """Best-effort record identifier for the presence-rate failure detail,
    mirroring `axial.validators.attribution._claim_id_of`'s own positional
    fallback."""
    brief_id = record.get("brief_id")
    return brief_id if isinstance(brief_id, str) and brief_id else f"<record #{index}>"


def run_synthesis_quality_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    steelman_pass_name: str = COUNTER_POSITION_PASS_NAME,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Score both synthesis-quality metrics over `records`. Calls
    `validate_counter_position` exactly once per record -- its own
    `CounterPositionValidatorError` subclasses (same-model guard, judge-call
    failure) propagate unchanged, so this gate never swallows them."""
    contested_total = 0
    present_or_disclosed = 0
    failing_brief_ids: list[str] = []

    steelman_ran = 0
    steelman_passed = 0

    for index, record in enumerate(records, start=1):
        report = validate_counter_position(
            record,
            client=client,
            vault_dir=vault_dir,
            config_path=config_path,
            steelman_pass_name=steelman_pass_name,
        )

        if report.contested.contested:
            contested_total += 1
            blocked = any(
                failure.reason == REASON_CONTESTED_WITHOUT_COUNTER_POSITION
                for failure in report.failures
            )
            if blocked:
                failing_brief_ids.append(_record_id(record, index))
            else:
                present_or_disclosed += 1

        if report.steelman.ran:
            steelman_ran += 1
            if report.steelman.verdict == VERDICT_STEELMAN:
                steelman_passed += 1

    # `contested_total == 0` means every record was uncontested -- the
    # CONTESTED subset itself is empty, never that no claims were found
    # (issue #401: the metric was previously built through
    # `build_metric_result`'s hard-gate `empty_denominator_fails=True`
    # branch, which reports "no claims found to evaluate" -- wrong on
    # records that plainly carry claims, e.g. P1-03's 5 and P2-01's 1). A
    # sample of zero contested records is not-scoreable, not a failure: there
    # is nothing here to judge present-or-disclosed either way.
    if contested_total == 0:
        presence = not_scoreable_metric(
            "counter_position_presence_rate",
            reason="no contested subset to evaluate (records carry claims, but none are contested)",
            config_path=config_path,
        )
    else:
        presence = build_metric_result(
            "counter_position_presence_rate",
            numerator=present_or_disclosed,
            denominator=contested_total,
            config_path=config_path,
            detail={"failing_brief_ids": failing_brief_ids} if failing_brief_ids else {},
            empty_denominator_fails=True,
        )
    # A corpus where every counter-position happens to be a one-sided
    # disclosure rather than a present stance has nothing for the steelman
    # check to judge -- not-scoreable (issue #401), not the vacuous
    # `passed: true` this used to report (30/30 briefs "passing" a check
    # that never ran, reading as a green light on a summary table).
    if steelman_ran == 0:
        steelman = not_scoreable_metric(
            "steelman_quality",
            reason="no present-with-grounds counter-position to judge",
            config_path=config_path,
        )
    else:
        steelman = build_metric_result(
            "steelman_quality",
            numerator=steelman_passed,
            denominator=steelman_ran,
            config_path=config_path,
            empty_denominator_fails=True,
        )
    return GateReport(
        gate=GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[presence, steelman],
    )
