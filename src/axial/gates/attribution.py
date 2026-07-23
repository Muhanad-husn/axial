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
  phrased as a source assertion. Reuses the SAME (b)-seam judged check
  `validate_attribution` already runs (its own `pass_name`/same-model guard
  included) rather than inventing a second judge seam -- zero model calls
  when no record carries a kind-"b" claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.gates.harness import GateReport, MetricResult, build_metric_result
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.validators.attribution import (
    REASON_B_SEAM_VOICED_AS_SOURCE,
    _check_grounds,
    _check_kind,
    _claim_id_of,
    validate_attribution,
)

GATE_NAME = "attribution-fidelity"


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


def _mechanically_valid_b_claim(claim: dict[str, Any], *, vault_dir: Path | None) -> bool:
    """Whether `claim` is kind-"b" AND passed both mechanical checks -- the
    exact predicate `validate_attribution` uses to decide which claims reach
    its own (b)-seam check, recomputed here so this gate can independently
    size the `b_seam_mislabel_rate` denominator without reaching into that
    function's internals."""
    if claim.get("kind") != "b":
        return False
    if _check_kind(claim, "") is not None:
        return False
    return _check_grounds(claim, "", "b", vault_dir=vault_dir) is None


def _score_b_seam_mislabel_rate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None,
    config_path: Path,
) -> MetricResult:
    """The judged (b)-seam mislabel rate: reuses `validate_attribution`
    (issue #258) per record -- its own same-model guard and its own
    zero-model-calls-when-no-(b)-claims rule apply unchanged. The
    denominator is every kind-"b" claim that reached the (b)-seam stage
    (mechanically valid); the numerator is how many of those the check
    flagged as voiced-as-a-source."""
    denominator = 0
    flagged_claim_ids: list[str] = []
    for record in records:
        claims = record.get("claims") or []
        denominator += sum(
            1 for claim in claims if _mechanically_valid_b_claim(claim, vault_dir=vault_dir)
        )
        report = validate_attribution(record, client=client, vault_dir=vault_dir)
        flagged_claim_ids.extend(
            failure.claim_id
            for failure in report.failures
            if failure.reason == REASON_B_SEAM_VOICED_AS_SOURCE
        )

    return build_metric_result(
        "b_seam_mislabel_rate",
        numerator=len(flagged_claim_ids),
        denominator=denominator,
        config_path=config_path,
        detail={"flagged_claim_ids": flagged_claim_ids} if flagged_claim_ids else {},
        empty_denominator_fails=False,
    )


def run_attribution_fidelity_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Score both attribution-fidelity metrics over `records` and return the
    gate's `GateReport`. `client` is only ever called when at least one
    record carries a mechanically-valid kind-"b" claim (the (b)-seam check's
    own contract, unchanged)."""
    claims = _iter_claims(records)
    completeness = _score_completeness(claims, vault_dir=vault_dir, config_path=config_path)
    b_seam = _score_b_seam_mislabel_rate(
        records, client=client, vault_dir=vault_dir, config_path=config_path
    )
    return GateReport(
        gate=GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[completeness, b_seam],
    )
