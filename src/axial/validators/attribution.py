"""Stage-5 attribution validator (specs/PHASE-B.md §7.9, §5 stage 5, issue
#258).

Reads a persisted §7.3 analysis record and reports pass/fail, never editing
it (README.md's own out-of-scope note: "it never edits the record,
re-prompts the synthesis, or drops an offending claim"). Two mechanical
checks and one bounded, independent model check, run in that order per
claim:

1. **Kind check.** Every claim's `kind` must be one of `{a, b, c}` (§7.4).
   Absent/null/blank/out-of-vocabulary all fail `missing_kind`.
2. **Grounds check.** Every `a`/`b` claim must carry non-empty `grounds`
   (`empty_grounds` otherwise), and every grounds entry must resolve to a
   real vault id through the query API -- `ref_type: chunk` via
   `axial.query.reader.get_chunk`, `ref_type: artifact` via `get_artifact`
   (`unresolvable_grounds` for a miss or an unknown `ref_type`). A `c` claim
   is never grounds-checked (§7.4: "may carry partial or empty grounds").
3. **(b)-seam honesty check.** One bounded model call, over every `kind: b`
   claim that passed 1-2, asks an INDEPENDENT model (never the generating
   one) whether the claim's text reads as a source assertion rather than
   the tool's own cross-source inference (§7.9). Skipped entirely -- zero
   model calls -- when the record carries no `b` claim. Runs under
   `ATTRIBUTION_PASS_NAME`, a `pass_name` distinct from
   `SYNTHESIZE_PASS_NAME`; `model_by_pass` MUST resolve the two to different
   models, or `SamePassModelError` raises before any call is made (the
   generating model must never grade its own attribution).

A record with `disposition: refuse` carries an empty `claims` list (§7.2)
and passes vacuously -- there is nothing to check.

Out of scope for this slice (plans/analysis-validators/01-attribution-
validator.md, README.md): the grounding check (does a cited chunk
substantively SUPPORT its claim's text -- a rung-3 gate, not a per-run
mechanical blocker), counter-position and coverage/confidence validation
(slices 02/03), and any repair behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from axial.llm import ATTRIBUTION_PASS_NAME, SYNTHESIZE_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    get_artifact,
    get_chunk,
)

# The §7.4 claim-kind vocabulary -- closed, not open text.
CLAIM_KINDS = frozenset({"a", "b", "c"})

# Kinds whose `grounds` must be non-empty and resolve (§7.4).
_GROUNDED_KINDS = frozenset({"a", "b"})

# The §7.5 ref_type vocabulary a grounds entry may point at.
_REF_TYPES = frozenset({"chunk", "artifact"})

# The closed reason vocabulary this validator ever reports -- a fixed,
# small set (one per check, plus the bounded model check), never open text,
# so a caller can dispatch on `reason` without string-matching `detail`.
REASON_MISSING_KIND = "missing_kind"
REASON_EMPTY_GROUNDS = "empty_grounds"
REASON_UNRESOLVABLE_GROUNDS = "unresolvable_grounds"
REASON_B_SEAM_VOICED_AS_SOURCE = "b_seam_voiced_as_source"


class AttributionValidatorError(Exception):
    """Base class for all attribution-validator errors."""


class AttributionCheckFailedError(AttributionValidatorError):
    """Raised when the bounded (b)-seam model call itself fails: a
    transport error, or a response that never parsed as usable JSON within
    `complete_json`'s bounded re-ask budget."""


class SamePassModelError(AttributionValidatorError):
    """Raised when `b_seam_pass_name` resolves (via `client.model_for_pass`)
    to the same model as `SYNTHESIZE_PASS_NAME` -- the one configuration
    mistake this validator refuses to run under, since the whole point of
    the (b)-seam check is that the generating model never grades its own
    attribution (§7.9, charter §2). Raised before any model call is made."""

    def __init__(self, pass_name: str, model: str):
        self.pass_name = pass_name
        self.model = model
        super().__init__(
            f"the (b)-seam check (pass_name={pass_name!r}) resolves to model "
            f"{model!r}, the SAME model as the synthesis pass "
            f"(pass_name={SYNTHESIZE_PASS_NAME!r}) -- configure model_by_pass "
            "so the (b)-seam check runs under a different model family than "
            "the pass that generated the claims it checks"
        )


@dataclass(frozen=True)
class AttributionFailure:
    """One failed check against one claim: which claim, which of the fixed
    reasons above, and a human-readable detail naming what went wrong."""

    claim_id: str
    reason: str
    detail: str


@dataclass(frozen=True)
class AttributionReport:
    """The validator's whole verdict: `passed` is `True` only when
    `failures` is empty. A failure blocks release (§7.9)."""

    passed: bool
    failures: list[AttributionFailure]


def _claim_id_of(claim: Any, index: int) -> str:
    """A best-effort claim_id for reporting even when the field itself is
    absent -- this validator's own job is checking `kind`/`grounds`, not
    `claim_id` presence, so a missing id must never crash the report."""
    if isinstance(claim, dict):
        claim_id = claim.get("claim_id")
        if isinstance(claim_id, str) and claim_id.strip():
            return claim_id
    return f"<claim #{index}>"


def _check_kind(claim: dict[str, Any], claim_id: str) -> AttributionFailure | None:
    kind = claim.get("kind")
    if kind not in CLAIM_KINDS:
        return AttributionFailure(
            claim_id=claim_id,
            reason=REASON_MISSING_KIND,
            detail=f"kind is {kind!r}, expected one of {sorted(CLAIM_KINDS)!r}",
        )
    return None


def _check_grounds(
    claim: dict[str, Any], claim_id: str, kind: str, *, vault_dir: Path | None
) -> AttributionFailure | None:
    """Grounds-presence then grounds-resolution, for `a`/`b` claims only --
    a `c` claim is never checked (§7.4: may carry partial/empty grounds)."""
    if kind not in _GROUNDED_KINDS:
        return None

    raw_grounds = claim.get("grounds")
    if not isinstance(raw_grounds, list) or not raw_grounds:
        return AttributionFailure(
            claim_id=claim_id,
            reason=REASON_EMPTY_GROUNDS,
            detail=f"kind {kind!r} claim carries empty/absent grounds",
        )

    unresolved: list[str] = []
    for entry in raw_grounds:
        if not isinstance(entry, dict):
            unresolved.append(f"malformed grounds entry: {entry!r}")
            continue
        ref_type = entry.get("ref_type")
        ref_id = entry.get("ref_id")
        if ref_type == "chunk":
            try:
                get_chunk(ref_id, vault_dir=vault_dir)
            except ChunkNotFoundError:
                unresolved.append(f"chunk {ref_id!r} not found in the vault")
        elif ref_type == "artifact":
            try:
                get_artifact(ref_id, vault_dir=vault_dir)
            except ArtifactNotFoundError:
                unresolved.append(f"artifact {ref_id!r} not found in the vault")
        else:
            unresolved.append(
                f"grounds entry has ref_type {ref_type!r}, expected one of {sorted(_REF_TYPES)!r}"
            )

    if unresolved:
        return AttributionFailure(
            claim_id=claim_id,
            reason=REASON_UNRESOLVABLE_GROUNDS,
            detail="; ".join(unresolved),
        )
    return None


def _compose_b_seam_prompt(claims_b: list[dict[str, Any]]) -> str:
    """Assemble the bounded (b)-seam check prompt: every kind-`b` claim's
    `claim_id`/text, asking an independent model whether any reads as a
    single source's assertion rather than the tool's own cross-source
    inference. One call for the whole batch -- "bounded" per §7.9, not
    one call per claim."""
    lines = "\n".join(f'- claim_id={claim["claim_id"]}: "{claim["text"]}"' for claim in claims_b)
    return f"""You are the independent (b)-seam honesty check of an analysis engine's stage-5 attribution validator (specs/PHASE-B.md §7.9). You are NOT the model that generated these claims -- you are checking its work.

Every claim below is marked "b" (tool-infers-across-sources): it must be the SYSTEM's own inference drawn across multiple sources, and must NEVER read as though a single source directly asserted it.

Claims marked (b):
{lines}

For each claim, decide: does its TEXT read as a source assertion (as if one source said this) rather than as the tool's own cross-source inference? Flag only claims that fail this test.

Return ONLY this JSON object, no prose and no code fence:
{{"flagged_claim_ids": ["<claim_id>", ...]}}"""


def _parse_b_seam_response(raw: str) -> list[str]:
    data = parse_model_json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("flagged_claim_ids"), list):
        raise AttributionCheckFailedError(
            f"(b)-seam response is missing a 'flagged_claim_ids' list: {data!r}"
        )
    return [str(claim_id) for claim_id in data["flagged_claim_ids"]]


def _run_b_seam_check(
    claims_b: list[dict[str, Any]],
    *,
    client: LLMClient,
    b_seam_pass_name: str,
) -> list[AttributionFailure]:
    """Run the bounded (b)-seam model call over `claims_b` (already `kind:
    b` claims that passed the mechanical checks). Zero model calls when
    `claims_b` is empty -- the caller only reaches here with a non-empty
    list. Raises `SamePassModelError` before calling the model at all when
    `b_seam_pass_name` resolves to the same model as the synthesis pass."""
    synthesis_model = client.model_for_pass(SYNTHESIZE_PASS_NAME)
    b_seam_model = client.model_for_pass(b_seam_pass_name)
    if b_seam_model == synthesis_model:
        raise SamePassModelError(b_seam_pass_name, b_seam_model)

    prompt = _compose_b_seam_prompt(claims_b)
    try:
        raw = complete_json(client, prompt, pass_name=b_seam_pass_name)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise AttributionCheckFailedError(f"(b)-seam check call failed: {exc}") from exc

    flagged_ids = set(_parse_b_seam_response(raw))
    valid_ids = {claim["claim_id"] for claim in claims_b}
    return [
        AttributionFailure(
            claim_id=claim_id,
            reason=REASON_B_SEAM_VOICED_AS_SOURCE,
            detail="the independent (b)-seam check found this claim's text reads as a "
            "source assertion, not a disclosed cross-source inference",
        )
        for claim_id in sorted(flagged_ids & valid_ids)
    ]


def validate_attribution(
    record: dict[str, Any],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    b_seam_pass_name: str = ATTRIBUTION_PASS_NAME,
) -> AttributionReport:
    """Validate every claim in `record["claims"]` (§7.3/§7.4): the kind
    check and grounds check run mechanically over every claim; the bounded
    (b)-seam check runs once over every `kind: b` claim that passed both
    (never over a claim already failing a mechanical check -- nothing more
    to learn from checking wording nobody can act on). An empty `claims`
    list (a `refuse` disposition, §7.2) passes vacuously.

    Never edits `record` -- returns a report, nothing more."""
    claims = record.get("claims") or []

    failures: list[AttributionFailure] = []
    claims_b: list[dict[str, Any]] = []

    for index, claim in enumerate(claims, start=1):
        claim_id = _claim_id_of(claim, index)

        kind_failure = _check_kind(claim, claim_id)
        if kind_failure is not None:
            failures.append(kind_failure)
            continue

        kind = claim["kind"]
        grounds_failure = _check_grounds(claim, claim_id, kind, vault_dir=vault_dir)
        if grounds_failure is not None:
            failures.append(grounds_failure)
            continue

        if kind == "b":
            claims_b.append({"claim_id": claim_id, "text": claim.get("text", "")})

    if claims_b:
        failures.extend(
            _run_b_seam_check(claims_b, client=client, b_seam_pass_name=b_seam_pass_name)
        )

    return AttributionReport(passed=not failures, failures=failures)


def format_attribution_report(report: AttributionReport) -> str:
    """Render `report` as human-readable text for the CLI (`axial brief
    validate`): a one-line verdict plus one line per failure, naming the
    claim_id and reason."""
    if report.passed:
        return "attribution validator: PASS (0 failures)"
    lines = [f"attribution validator: FAIL ({len(report.failures)} failure(s))"]
    for failure in report.failures:
        lines.append(f"  {failure.claim_id}: {failure.reason} -- {failure.detail}")
    return "\n".join(lines)
