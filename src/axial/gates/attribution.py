"""The attribution-fidelity rung-3 gate (issue #262, specs/PHASE-B.md §10,
charter Principle II).

Two metrics, scored over every claim across a directory of analysis records
(`axial.gates.harness.load_records`):

- `attribution_completeness` -- the hard, 100% mechanical gate: the share of
  claims carrying a valid `kind` AND resolvable (a)/(b) grounds. Reuses
  `axial.validators.attribution`'s own kind/grounds checks (issue #258)
  rather than re-implementing grounds resolution -- the plan's own
  dependency note ("it reuses the check rather than re-implementing it").
  An empty overall claim set reports `passed: False` with a named reason,
  never a vacuous 1.00.
- `b_seam_mislabel_rate` -- the judged half: the share of kind-"b" claims
  (that already passed the mechanical checks) an independent model finds
  phrased as a source assertion. Reuses the SAME (b)/(c)-seam judged check
  `validate_attribution` already runs (its own `pass_name`/same-model guard
  included) rather than inventing a second judge seam -- zero model calls
  when no record carries a kind-"b" claim AND no record carries a kind-"c"
  claim.
- `c_seam_mislabel_rate` (issue #589) -- the same judge's second question:
  the share of kind-"c" claims (this analysis's own verdict, mechanically
  valid per §7.4 -- a `c` claim needs no grounds) whose text credits a
  source with the verdict rather than the analysis's own judgment. Reported
  as its OWN metric, never folded into `b_seam_mislabel_rate` -- a joint
  rate would hide which channel leaks. Same 0.05 threshold, same `lte`
  comparison (specs/PHASE-B.md §10.1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dataclasses import replace

from axial.gates.harness import GateReport, MetricResult, build_metric_result
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.validators.attribution import (
    REASON_B_SEAM_VOICED_AS_SOURCE,
    REASON_C_SEAM_VOICED_AS_SOURCE,
    _check_grounds,
    _check_kind,
    _claim_id_of,
    validate_attribution,
)

GATE_NAME = "attribution-fidelity"

# The paper-side gate name (specs/PHASE-C.md §10.1, §7.4, §8 P0-9, issue
# #608): a SEPARATE CLI entry from GATE_NAME above, dispatched to `axial.
# gates.harness.load_paper_records` rather than `load_records` -- see
# `_gate_run`'s per-gate loader dispatch in `axial.cli`. `run_attribution_
# fidelity_gate`'s CHECK LOGIC is reused WHOLESALE for it (specs/PHASE-C.md
# §10.1: "the (b)-seam gate reuses ... attribution.py's judged check
# wholesale"), including its unchanged self-grading guard anchored to
# `SYNTHESIZE_PASS_NAME` -- no re-anchor to `PAPER_DRAFT_PASS_NAME` here,
# unlike the paper-side grounding gate, per that same spec note.
# `_claim_id_of` now falls back to `paper_claim_id` before the positional
# placeholder (issue #608), so a flagged paper claim is still nameable.
PAPER_GATE_NAME = "paper-attribution-fidelity"


def _iter_claims(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every claim across every record, in record order. A `refuse`
    disposition record carries an empty `claims` list (§7.2) and
    contributes none -- there is nothing to check (mirrors
    `validate_attribution`'s own vacuous-pass rule)."""
    claims: list[dict[str, Any]] = []
    for record in records:
        claims.extend(record.get("claims") or [])
    return claims


def _score_completeness(
    claims: list[dict[str, Any]], *, vault_dir: Path | None, config_path: Path
) -> MetricResult:
    """Mechanical only -- kind + grounds, never the (b)-seam model check --
    reusing `axial.validators.attribution`'s own private check functions so
    this gate never re-implements grounds resolution."""
    failing_claim_ids: list[str] = []
    for index, claim in enumerate(claims, start=1):
        claim_id = _claim_id_of(claim, index)
        kind_failure = _check_kind(claim, claim_id)
        if kind_failure is not None:
            failing_claim_ids.append(claim_id)
            continue
        grounds_failure = _check_grounds(claim, claim_id, claim["kind"], vault_dir=vault_dir)
        if grounds_failure is not None:
            failing_claim_ids.append(claim_id)

    total = len(claims)
    complete = total - len(failing_claim_ids)
    return build_metric_result(
        "attribution_completeness",
        numerator=complete,
        denominator=total,
        config_path=config_path,
        detail={"failing_claim_ids": failing_claim_ids} if failing_claim_ids else {},
        empty_denominator_fails=True,
    )


def _mechanically_valid_claim(claim: dict[str, Any], kind: str, *, vault_dir: Path | None) -> bool:
    """Whether `claim` is the given `kind` AND passed the mechanical checks
    that gate -- the exact predicate `validate_attribution` uses to decide
    which claims reach the (b)/(c)-seam check, recomputed here so this gate
    can independently size each rate's denominator without reaching into
    that function's internals."""
    if claim.get("kind") != kind:
        return False
    if _check_kind(claim, "") is not None:
        return False
    return _check_grounds(claim, "", kind, vault_dir=vault_dir) is None


def _score_seam_mislabel_rates(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None,
    config_path: Path,
) -> tuple[MetricResult, MetricResult]:
    """The judged `b_seam_mislabel_rate` and `c_seam_mislabel_rate` (issue
    #589): reuses `validate_attribution` (issue #258) once PER RECORD --
    its own same-model guard, its own zero-model-calls-when-neither-kind
    rule, and its single combined (b)/(c)-seam call all apply unchanged, so
    scoring both rates here never doubles the model calls `validate_
    attribution` already makes. Each rate's denominator is every claim of
    its own kind that reached the seam stage (mechanically valid); each
    numerator is how many of those the check flagged as voiced-as-a-source.
    `b_seam_mislabel_rate` keeps its exact prior meaning and denominator --
    a record's kind-"c" claims never enter it, and vice versa."""
    b_denominator = 0
    c_denominator = 0
    flagged_b_claim_ids: list[str] = []
    flagged_c_claim_ids: list[str] = []
    for record in records:
        claims = record.get("claims") or []
        b_denominator += sum(
            1 for claim in claims if _mechanically_valid_claim(claim, "b", vault_dir=vault_dir)
        )
        c_denominator += sum(
            1 for claim in claims if _mechanically_valid_claim(claim, "c", vault_dir=vault_dir)
        )
        report = validate_attribution(record, client=client, vault_dir=vault_dir)
        flagged_b_claim_ids.extend(
            failure.claim_id
            for failure in report.failures
            if failure.reason == REASON_B_SEAM_VOICED_AS_SOURCE
        )
        flagged_c_claim_ids.extend(
            failure.claim_id
            for failure in report.failures
            if failure.reason == REASON_C_SEAM_VOICED_AS_SOURCE
        )

    b_seam = build_metric_result(
        "b_seam_mislabel_rate",
        numerator=len(flagged_b_claim_ids),
        denominator=b_denominator,
        config_path=config_path,
        detail={"flagged_claim_ids": flagged_b_claim_ids} if flagged_b_claim_ids else {},
        empty_denominator_fails=False,
    )
    c_seam = build_metric_result(
        "c_seam_mislabel_rate",
        numerator=len(flagged_c_claim_ids),
        denominator=c_denominator,
        config_path=config_path,
        detail={"flagged_claim_ids": flagged_c_claim_ids} if flagged_c_claim_ids else {},
        empty_denominator_fails=False,
    )
    return b_seam, c_seam


def run_attribution_fidelity_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Score all three attribution-fidelity metrics over `records` and
    return the gate's `GateReport`. `client` is only ever called when at
    least one record carries a mechanically-valid kind-"b" claim OR a
    mechanically-valid kind-"c" claim (the (b)/(c)-seam check's own
    contract, issue #589)."""
    claims = _iter_claims(records)
    completeness = _score_completeness(claims, vault_dir=vault_dir, config_path=config_path)
    b_seam, c_seam = _score_seam_mislabel_rates(
        records, client=client, vault_dir=vault_dir, config_path=config_path
    )
    return GateReport(
        gate=GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[completeness, b_seam, c_seam],
    )


def run_paper_attribution_fidelity_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """`PAPER_GATE_NAME`'s own `GATE_RUNNERS` entry (issue #608): identical
    to `run_attribution_fidelity_gate` in every respect but the report's own
    `gate` field. A thin wrapper, not a second implementation -- every check
    is `run_attribution_fidelity_gate`'s, called unchanged.

    Exists because `GateReport.gate` names the file `axial.gates.harness.
    write_report` writes to (`evals/reports/<gate>.json`): without this,
    `axial gate run paper-attribution-fidelity` would silently write
    `attribution-fidelity.json`, indistinguishable from -- and clobbering --
    a Phase-B run's own report, even though it was dispatched under a
    different CLI name and scored a different kind of record entirely."""
    report = run_attribution_fidelity_gate(
        records,
        client=client,
        vault_dir=vault_dir,
        corpus_pin=corpus_pin,
        trusted=trusted,
        config_path=config_path,
    )
    return replace(report, gate=PAPER_GATE_NAME)
