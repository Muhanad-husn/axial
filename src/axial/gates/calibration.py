"""The calibration rung-3 gate (issue #263, specs/PHASE-B.md §10 / §7.4,
charter Principle V).

**Calibration is measured band-wise, not as an error over a continuous
score.** This was a live spec Open Question when this slice's own plan was
written, but it is already founder-adjudicated on `main`
(specs/PHASE-B.md §10, "spec(phase-b): v1.1 -- confidence bands, band-wise
calibration, source-usage disclosure", 2026-07-20): expected calibration
error and Brier score both presuppose a numeric confidence the three-band
vocabulary (§7.4) deliberately does not produce, so the spec calls them
"inapplicable... not merely unchosen." This module implements exactly the
settled metric -- there is no second metric to make swappable, so no
`calibration.metric` config seam is built (an abstraction with one
implementation is the tripwire, not the fix).

The one metric, `band_reliability`: for each of `high`/`medium`/`low`, the
observed judged-correctness rate of the claims disclosed in that band,
compared against the band's stated target rate (§7.4: `high` >= 0.85,
`medium` 0.60-0.85, `low` < 0.60) within a tunable tolerance, plus the
strict-ordering requirement (observed_high > observed_medium > observed_low,
over whichever bands carry data). Both the per-band target rates and the
minimum sample size per band are stated TENTATIVE in §7.4/§10, tuned on the
first judged runs -- that remaining tunability is recorded on every report's
`note`, distinct from the (already settled) metric-choice question.

`calibration.band_targets` (config/pipeline.yaml) is the tunable seam for
the three per-band target rates, mirroring `coverage_bands`'s own
config-first/code-fallback convention (src/axial/validators/coverage.py).
The band-reliability tolerance itself is the harness's own
`gates.band_reliability` threshold (default 0.15).

The judge (`judged correctness` per claim) is an independent model call,
anchored to the claim text and its resolved grounds text, run under its own
`pass_name` (`CALIBRATION_PASS_NAME`) and guarded against self-grading
exactly like the grounding gate (src/axial/gates/grounding.py) -- reuses
that module's own grounds-resolution helper rather than re-deriving it. An
unresolvable grounds pointer is a gate error there and stays one here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from axial.gates.grounding import _resolve_grounds_text
from axial.gates.harness import GateReport, MetricResult, resolve_threshold
from axial.llm import (
    CALIBRATION_PASS_NAME,
    DEFAULT_PIPELINE_CONFIG_PATH,
    SYNTHESIZE_PASS_NAME,
    LLMClient,
    LLMError,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json

GATE_NAME = "calibration"
METRIC_NAME = "band_reliability"

# The §7.4 three-band confidence vocabulary, in high-to-low order (the order
# the strict-ordering check compares against).
CONFIDENCE_BANDS = ("high", "medium", "low")

# §7.4's stated TENTATIVE band targets: `high` >= 0.85, `low` < 0.60,
# `medium` the 0.60-0.85 range's midpoint -- the code-level fallback used
# only when `config/pipeline.yaml` (or its `calibration.band_targets` key)
# is absent, mirroring every other per-check tunable in this codebase.
DEFAULT_BAND_TARGETS: dict[str, float] = {"high": 0.85, "medium": 0.725, "low": 0.60}

_CORRECT = "correct"
_INCORRECT = "incorrect"
_VERDICTS = frozenset({_CORRECT, _INCORRECT})

_TENTATIVE_NOTE = (
    "band targets and the minimum sample size per band are TENTATIVE "
    "starting hypotheses (specs/PHASE-B.md §7.4), tuned on the first judged "
    "runs. The band-wise metric CHOICE itself is already settled "
    "(specs/PHASE-B.md §10 v1.1): ECE/Brier are inapplicable, not merely "
    "unchosen, because the three-band vocabulary carries no numeric "
    "confidence to score them against."
)


class CalibrationGateError(Exception):
    """Base class for all calibration-gate errors."""


class InvalidConfidenceBandError(CalibrationGateError):
    """Raised when a claim's `confidence` is not one of the three §7.4
    bands -- a gate error, never a silently-imputed band."""

    def __init__(self, claim_id: str, confidence: Any):
        self.claim_id = claim_id
        self.confidence = confidence
        super().__init__(
            f"claim {claim_id!r}: confidence {confidence!r} is not one of "
            f"{CONFIDENCE_BANDS!r} -- the calibration gate never imputes a band"
        )


class SelfGradingError(CalibrationGateError):
    """Raised when the calibration judge's configured pass resolves to the
    SAME model as the synthesis pass -- the generating model must never
    grade its own output (§10, charter §2). Raised before any judge call is
    made; zero calls are made when this fires."""

    def __init__(self, judge_pass_name: str, model: str):
        self.judge_pass_name = judge_pass_name
        self.model = model
        super().__init__(
            f"the calibration judge (pass_name={judge_pass_name!r}) resolves to "
            f"model {model!r}, the SAME model as the synthesis pass "
            f"(pass_name={SYNTHESIZE_PASS_NAME!r}) -- self-grading: configure "
            "model_by_pass so the judge runs under a different model, from a "
            "different model family, than the pass that generated the claims "
            "it is judging"
        )


class CalibrationCheckFailedError(CalibrationGateError):
    """Raised when the judge's own call fails (transport error, or a
    response that never parsed to a valid verdict)."""


def _resolve_band_targets(config_path: Path) -> dict[str, float]:
    """Read `calibration.band_targets.{high,medium,low}` from
    `config/pipeline.yaml`, falling back to `DEFAULT_BAND_TARGETS` when the
    file or a key is absent -- a config change, never a code change, tunes
    the target rates (mirrors `coverage.py`'s `_resolve_coverage_bands`)."""
    if not config_path.is_file():
        return dict(DEFAULT_BAND_TARGETS)
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    calibration_config = document.get("calibration") or {}
    targets = calibration_config.get("band_targets") or {}
    return {band: float(targets.get(band, DEFAULT_BAND_TARGETS[band])) for band in CONFIDENCE_BANDS}


def _iter_claims(records: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Every claim across every record, paired with a best-effort claim_id
    (mirrors `axial.gates.grounding._iter_a_claims`, unfiltered by kind --
    §7.4's confidence field applies to every claim, not just kind "a")."""
    claims: list[tuple[str, dict[str, Any]]] = []
    index = 0
    for record in records:
        for claim in record.get("claims") or []:
            index += 1
            claim_id = claim.get("claim_id") or f"<claim #{index}>"
            claims.append((claim_id, claim))
    return claims


def _compose_judge_prompt(claim_text: str, grounds_text: str) -> str:
    return f"""You are the independent calibration judge of an analysis engine's rung-3 eval gate (specs/PHASE-B.md §10). You are NOT the model that generated this claim -- you are judging whether it holds up.

Claim:
"{claim_text}"

Cited grounds (the resolved chunk/artifact text the claim points at; empty if none was cited):
"{grounds_text}"

Decide: is this claim CORRECT, given the cited grounds (or, where none were cited, on its own stated merits)?

Return ONLY this JSON object, no prose and no code fence:
{{"verdict": "correct"}} or {{"verdict": "incorrect"}}"""


def _judge_claim(
    claim_text: str,
    grounds_text: str,
    claim_id: str,
    *,
    client: LLMClient,
    judge_pass_name: str,
) -> str:
    prompt = _compose_judge_prompt(claim_text, grounds_text)
    try:
        raw = complete_json(client, prompt, pass_name=judge_pass_name)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise CalibrationCheckFailedError(
            f"claim {claim_id!r}: calibration judge call failed: {exc}"
        ) from exc
    data = parse_model_json(raw)
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict not in _VERDICTS:
        raise CalibrationCheckFailedError(
            f"claim {claim_id!r}: calibration judge response carries no valid "
            f"'verdict' in {sorted(_VERDICTS)!r}: {data!r}"
        )
    return verdict


def run_calibration_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    judge_pass_name: str = CALIBRATION_PASS_NAME,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Score `band_reliability` over every claim in `records`. Raises
    `SelfGradingError` before any judge call is made when `judge_pass_name`
    resolves to the same model as `SYNTHESIZE_PASS_NAME`; raises
    `InvalidConfidenceBandError` when a claim's `confidence` is not one of
    the three §7.4 bands; raises `UnresolvableGroundsError`
    (`axial.gates.grounding`) when a grounds pointer does not resolve."""
    claims = _iter_claims(records)

    if claims:
        synthesis_model = client.model_for_pass(SYNTHESIZE_PASS_NAME)
        judge_model = client.model_for_pass(judge_pass_name)
        if judge_model == synthesis_model:
            raise SelfGradingError(judge_pass_name, judge_model)

    verdicts_by_band: dict[str, list[str]] = {band: [] for band in CONFIDENCE_BANDS}
    for claim_id, claim in claims:
        confidence = claim.get("confidence")
        if confidence not in CONFIDENCE_BANDS:
            raise InvalidConfidenceBandError(claim_id, confidence)
        grounds_text = _resolve_grounds_text(claim, claim_id, vault_dir=vault_dir)
        verdict = _judge_claim(
            claim.get("text", ""),
            grounds_text,
            claim_id,
            client=client,
            judge_pass_name=judge_pass_name,
        )
        verdicts_by_band[confidence].append(verdict)

    targets = _resolve_band_targets(config_path)
    threshold = resolve_threshold(METRIC_NAME, config_path)

    bands_detail: dict[str, dict[str, Any]] = {}
    observed_by_band: dict[str, float] = {}
    deviations: list[float] = []
    for band in CONFIDENCE_BANDS:
        verdicts = verdicts_by_band[band]
        n = len(verdicts)
        target = targets[band]
        observed = sum(1 for v in verdicts if v == _CORRECT) / n if n else None
        if observed is not None:
            observed_by_band[band] = observed
            deviations.append(abs(observed - target))
        bands_detail[band] = {"observed": observed, "target": target, "n": n}

    # Compares CONSECUTIVE present bands in the filtered sequence, not
    # consecutive slots in CONFIDENCE_BANDS -- comparing only adjacent named
    # slots would miss a real inversion (e.g. `low` observed above `high`)
    # whenever `medium` carries no data, since neither adjacent pair
    # (high, medium) or (medium, low) would include that comparison at all.
    present_observed = [
        observed_by_band[band] for band in CONFIDENCE_BANDS if band in observed_by_band
    ]
    strictly_ordered = all(a > b for a, b in zip(present_observed, present_observed[1:]))

    detail = {"bands": bands_detail, "strictly_ordered": strictly_ordered, "note": _TENTATIVE_NOTE}

    if not deviations:
        metric = MetricResult(
            metric=METRIC_NAME,
            value=None,
            threshold=threshold,
            comparison="lte",
            passed=False,
            n=0,
            detail={**detail, "reason": "no claims found to evaluate"},
        )
    else:
        value = max(deviations)
        metric = MetricResult(
            metric=METRIC_NAME,
            value=value,
            threshold=threshold,
            comparison="lte",
            passed=value <= threshold and strictly_ordered,
            n=len(claims),
            detail=detail,
        )

    return GateReport(gate=GATE_NAME, corpus_pin=corpus_pin, trusted=trusted, metrics=[metric])
