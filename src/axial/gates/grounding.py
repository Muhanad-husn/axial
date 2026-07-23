"""The grounding rung-3 gate (issue #262, specs/PHASE-B.md §10, charter
Principle I).

Metric `grounding_support_rate` = the share of kind-"a" claims whose cited
grounds **substantively support** the claim's text, judged by an
**independent model anchored to the resolved chunk/artifact text** -- one
judge call per claim, never the generating (synthesis) model. The judge runs
under its own `pass_name` (`axial.llm.GROUNDING_PASS_NAME`) and this module
errors loudly, before any judge call, if that pass resolves to the same
model as the synthesis pass (`axial.llm.SYNTHESIZE_PASS_NAME`) -- mirrors
`axial.validators.attribution`'s own same-model guard for the (b)-seam
check, applied here to a second independent-judge seam.

An unresolvable grounds pointer on an "a" claim is a **gate error**, never
silently judged "does not support" -- a broken pointer is an attribution-
fidelity concern (that gate already catches it), not evidence against
grounding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from axial.gates.harness import GateReport, build_metric_result
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    GROUNDING_PASS_NAME,
    SYNTHESIZE_PASS_NAME,
    LLMClient,
    LLMError,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    get_artifact,
    get_chunk,
)

GATE_NAME = "grounding"

_SUPPORTS = "supports"
_DOES_NOT_SUPPORT = "does_not_support"
_VERDICTS = frozenset({_SUPPORTS, _DOES_NOT_SUPPORT})


class GroundingGateError(Exception):
    """Base class for all grounding-gate errors."""


class UnresolvableGroundsError(GroundingGateError):
    """Raised when a kind-"a" claim's grounds pointer does not resolve
    against the vault -- a gate error, never a "does not support"
    judgement (module docstring): grounds resolution is attribution-
    fidelity's job, already caught there."""

    def __init__(self, claim_id: str, detail: str):
        self.claim_id = claim_id
        self.detail = detail
        super().__init__(f"claim {claim_id!r}: unresolvable grounds -- {detail}")


class SelfGradingError(GroundingGateError):
    """Raised when the grounding judge's configured pass resolves to the
    SAME model as the synthesis pass -- the generating model must never
    grade its own output (§10, charter §2). Raised before any judge call is
    made; zero calls are made when this fires."""

    def __init__(self, judge_pass_name: str, model: str):
        self.judge_pass_name = judge_pass_name
        self.model = model
        super().__init__(
            f"the grounding judge (pass_name={judge_pass_name!r}) resolves to model "
            f"{model!r}, the SAME model as the synthesis pass "
            f"(pass_name={SYNTHESIZE_PASS_NAME!r}) -- self-grading: configure "
            "model_by_pass so the judge runs under a different model, from a "
            "different model family, than the pass that generated the claims "
            "it is judging"
        )


class GroundingCheckFailedError(GroundingGateError):
    """Raised when the judge's own call fails (transport error, or a
    response that never parsed to a valid verdict)."""


def _resolve_grounds_text(claim: dict[str, Any], claim_id: str, *, vault_dir: Path | None) -> str:
    """The resolved text every one of `claim`'s grounds pointers anchors
    to, concatenated in order: a `chunk` ref's `chunk_text`, an `artifact`
    ref's caption (falling back to its role when it carries none). Raises
    `UnresolvableGroundsError` on the first pointer that fails to resolve or
    names an unknown `ref_type` -- never silently judged."""
    texts: list[str] = []
    for entry in claim.get("grounds") or []:
        ref_type = entry.get("ref_type") if isinstance(entry, dict) else None
        ref_id = entry.get("ref_id") if isinstance(entry, dict) else None
        if ref_type == "chunk":
            try:
                texts.append(get_chunk(ref_id, vault_dir=vault_dir).chunk_text)
            except ChunkNotFoundError as exc:
                raise UnresolvableGroundsError(claim_id, str(exc)) from exc
        elif ref_type == "artifact":
            try:
                artifact = get_artifact(ref_id, vault_dir=vault_dir)
            except ArtifactNotFoundError as exc:
                raise UnresolvableGroundsError(claim_id, str(exc)) from exc
            texts.append(artifact.caption or artifact.artifact_role)
        else:
            raise UnresolvableGroundsError(
                claim_id, f"grounds entry has unknown ref_type {ref_type!r}"
            )
    return "\n---\n".join(texts)


def _compose_judge_prompt(claim_text: str, grounds_text: str) -> str:
    return f"""You are the independent grounding judge of an analysis engine's rung-3 eval gate (specs/PHASE-B.md §10). You are NOT the model that generated this claim -- you are judging its evidence.

Claim:
"{claim_text}"

Cited grounds (the resolved chunk/artifact text the claim points at):
"{grounds_text}"

Decide: does the cited grounds text SUBSTANTIVELY SUPPORT the claim's text? Judge only what the grounds text actually says, not what the claim wishes it said.

Return ONLY this JSON object, no prose and no code fence:
{{"verdict": "supports"}} or {{"verdict": "does_not_support"}}"""


def _parse_judge_response(raw: str, claim_id: str) -> str:
    data = parse_model_json(raw)
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict not in _VERDICTS:
        raise GroundingCheckFailedError(
            f"claim {claim_id!r}: grounding judge response carries no valid "
            f"'verdict' in {sorted(_VERDICTS)!r}: {data!r}"
        )
    return verdict


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
        raise GroundingCheckFailedError(
            f"claim {claim_id!r}: grounding judge call failed: {exc}"
        ) from exc
    return _parse_judge_response(raw, claim_id)


def _iter_a_claims(records: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Every kind-"a" claim across every record, paired with a best-effort
    claim_id (falling back to a positional placeholder, mirroring
    `axial.validators.attribution._claim_id_of`) -- (b)/(c) claims are
    excluded from the denominator entirely (§10: "computed over (a) claims
    only")."""
    claims: list[tuple[str, dict[str, Any]]] = []
    index = 0
    for record in records:
        for claim in record.get("claims") or []:
            index += 1
            if claim.get("kind") != "a":
                continue
            claim_id = claim.get("claim_id") or f"<claim #{index}>"
            claims.append((claim_id, claim))
    return claims


def run_grounding_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    judge_pass_name: str = GROUNDING_PASS_NAME,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Score `grounding_support_rate` over every kind-"a" claim in
    `records`. Raises `SelfGradingError` before any judge call is made when
    `judge_pass_name` resolves to the same model as `SYNTHESIZE_PASS_NAME`;
    raises `UnresolvableGroundsError` when an "a" claim's grounds pointer
    does not resolve; raises `GroundingCheckFailedError` when the judge's
    own call or response fails."""
    a_claims = _iter_a_claims(records)

    if a_claims:
        synthesis_model = client.model_for_pass(SYNTHESIZE_PASS_NAME)
        judge_model = client.model_for_pass(judge_pass_name)
        if judge_model == synthesis_model:
            raise SelfGradingError(judge_pass_name, judge_model)

    supported = 0
    for claim_id, claim in a_claims:
        grounds_text = _resolve_grounds_text(claim, claim_id, vault_dir=vault_dir)
        verdict = _judge_claim(
            claim.get("text", ""),
            grounds_text,
            claim_id,
            client=client,
            judge_pass_name=judge_pass_name,
        )
        if verdict == _SUPPORTS:
            supported += 1

    metric = build_metric_result(
        "grounding_support_rate",
        numerator=supported,
        denominator=len(a_claims),
        config_path=config_path,
        empty_denominator_fails=True,
    )
    return GateReport(
        gate=GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[metric],
    )
