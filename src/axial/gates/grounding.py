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
grounding. Same for a (b) claim judged by `run_grounding_gate` (Phase B,
reported-only). `run_paper_grounding_gate` (below) is the one exception,
since issue #627: it folds an unresolvable pointer on a paper's own new (b)
claim into `contradicted_claim_ids` instead, so one paper record whose
grounds have gone stale fails on its own metric rather than aborting every
other record `--records` was pointed at.

**`b_claim_contradiction_rate` (issue #550) is a SEPARATE, reported-only
number, never folded into `grounding_support_rate`.** 33 of 112 claims
(29%) across the six smoke-v4 records are kind-"b" -- a cross-source
inference -- and not one was ever grounding-judged: the sharpest defect the
sealed peer-review pass found was exactly a (b) claim whose cited passage
opens "Contrary to Mann's assertion...", the opposite of what the claim
says. "Does this passage assert the claim" is the wrong bar for an
inference, which by definition may not be asserted by any single source; the
bar here is "does any cited passage CONTRADICT it". Reported via
`GateReport.reported` (`axial.gates.harness`), never `metrics`: no baseline
distribution has ever been observed, so no threshold is asserted, and this
number can never fail the gate or block release -- exactly the discipline
§10.0 already states for source usage, the cross-source rate and
instant-dismissal violations.

**P2-4 re-bar (issue #607, specs/PHASE-C.md §8 P0-9).** The metric above
read 0.0000 on both sealed review rounds, including the "Contrary to Mann's
assertion..." record it exists to catch. What that passage contradicts is
the claim's own crediting of a scholar -- not the claim's proposition, which
the judge WAS shown and which the passage does not contradict on its own
terms. The note that carries the passage states this opposition itself, in
its own `arguing_against` answer (§7.15), which the judge was never shown.
`_resolve_grounds_arguing_against` below reads it off every chunk-typed
grounds note (an abstention, or an artifact ref which carries no
interrogation answers, contributes nothing) and the judge prompt now shows
it alongside the grounds text -- no other change to the metric's shape,
denominator, or reported-only status.

**`run_paper_grounding_gate` (specs/PHASE-C.md §10.1, §8 P0-9) is Phase C's
own GATED use of this judge**, scored only over a paper record's NEW (b)
claims (`origin is None`, §7.4) -- a carried (b) claim already passed
whatever Phase B did or did not gate it on, and Phase C's new (b) claims are
the entire contribution this phase adds (§2 goal 2). It reuses every private
helper below (`_resolve_grounds_text`, `_resolve_grounds_arguing_against`,
`_judge_b_claim`) unchanged; the only new work is the (b)-claim selector and
turning the contradiction rate into a GATED, inverted
`b_claim_noncontradiction_rate` (numerator = claims NOT contradicted) at a
distinct metric name from the reported-only `b_claim_contradiction_rate`
above, precisely so the two never share one config-tunable threshold. Its
self-grading guard is re-anchored to `PAPER_DRAFT_PASS_NAME` rather than
`SYNTHESIZE_PASS_NAME` (specs/PHASE-C.md §10.1: "its guard re-anchored to
Phase C's drafting pass"), since Phase C's generating pass is drafting, not
Phase-B synthesis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from axial.gates.harness import GateReport, build_metric_result, not_scoreable_metric
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    GROUNDING_PASS_NAME,
    PAPER_DRAFT_PASS_NAME,
    SYNTHESIZE_PASS_NAME,
    LLMClient,
    LLMError,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.query.names import as_string_list
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    get_artifact,
    get_chunk,
    is_abstention,
)

GATE_NAME = "grounding"

# The paper-side gate name (specs/PHASE-C.md §10.1, §8 P0-9): a SEPARATE
# CLI entry from GATE_NAME above, dispatched to `axial.gates.harness.
# load_paper_records` rather than `load_records` -- see `_gate_run`'s
# per-gate loader dispatch in `axial.cli`. Reuses this module's judge
# wholesale; only the (b)-claim selector and the gated metric are new
# (module docstring).
PAPER_GATE_NAME = "paper-grounding"

_SUPPORTS = "supports"
_DOES_NOT_SUPPORT = "does_not_support"
_VERDICTS = frozenset({_SUPPORTS, _DOES_NOT_SUPPORT})

_CONTRADICTS = "contradicts"
_DOES_NOT_CONTRADICT = "does_not_contradict"
_CONTRADICTION_VERDICTS = frozenset({_CONTRADICTS, _DOES_NOT_CONTRADICT})


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
    SAME model as the generating pass -- the generating model must never
    grade its own output (§10, charter §2). Raised before any judge call is
    made; zero calls are made when this fires.

    `generating_pass_name` defaults to `SYNTHESIZE_PASS_NAME` (Phase B,
    `run_grounding_gate`'s own anchor); `run_paper_grounding_gate` passes
    `PAPER_DRAFT_PASS_NAME` instead, re-anchoring the guard to Phase C's own
    generating pass (specs/PHASE-C.md §10.1: "its guard re-anchored to Phase
    C's drafting pass") -- the guard's LOGIC is identical, only which pass
    counts as "the generating one" changes."""

    def __init__(
        self,
        judge_pass_name: str,
        model: str,
        *,
        generating_pass_name: str = SYNTHESIZE_PASS_NAME,
    ):
        self.judge_pass_name = judge_pass_name
        self.model = model
        self.generating_pass_name = generating_pass_name
        super().__init__(
            f"the grounding judge (pass_name={judge_pass_name!r}) resolves to model "
            f"{model!r}, the SAME model as the generating pass "
            f"(pass_name={generating_pass_name!r}) -- self-grading: configure "
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
    ref's caption (falling back to its own id when it carries none --
    `artifact_role` is retired, issue #429, and usually absent now). Raises
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
            texts.append(artifact.caption or artifact.artifact_id)
        else:
            raise UnresolvableGroundsError(
                claim_id, f"grounds entry has unknown ref_type {ref_type!r}"
            )
    return "\n---\n".join(texts)


def _resolve_grounds_arguing_against(
    claim: dict[str, Any], claim_id: str, *, vault_dir: Path | None
) -> str:
    """The (b)-claim re-bar (issue #607, module docstring): every chunk-typed
    grounds note's own `arguing_against` answer (§7.15), concatenated in
    citation order -- what the CITED PASSAGE ITSELF says it argues against,
    which is what a (b) claim's "Contrary to Mann's assertion..." defect
    actually contradicts (the claim's crediting of a scholar, not its bare
    proposition).

    An abstention (`is_abstention`) contributes nothing, exactly as
    `axial.validators.counter_position._opposition_surfaces` already treats
    it. An artifact-typed grounds entry contributes nothing either -- an
    artifact note carries no interrogation answers. Never raises on an
    unresolvable pointer: `_resolve_grounds_text` above already raised
    `UnresolvableGroundsError` for the same claim before this is ever
    called, so every chunk here is expected to resolve."""
    surfaces: list[str] = []
    for entry in claim.get("grounds") or []:
        if not isinstance(entry, dict) or entry.get("ref_type") != "chunk":
            continue
        ref_id = entry.get("ref_id")
        try:
            note = get_chunk(ref_id, vault_dir=vault_dir)
        except ChunkNotFoundError as exc:
            raise UnresolvableGroundsError(claim_id, str(exc)) from exc
        if is_abstention(note.arguing_against):
            continue
        surfaces.extend(as_string_list(note.arguing_against))
    return "; ".join(surfaces)


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


def _compose_b_claim_judge_prompt(
    claim_text: str, grounds_text: str, arguing_against_text: str
) -> str:
    """The (b)-claim bar, deliberately different from `_compose_judge_prompt`
    above (issue #550): a (b) claim is the tool's OWN cross-source inference
    (§7.4), so "does a single cited passage assert this" is the wrong
    question -- an inference may be true without any one source stating it.
    The question this judge answers instead is whether any cited passage
    CONTRADICTS the claim, which is what a broken (b) claim actually looks
    like (the sharpest smoke-v4 defect: a claim's own cited passage opens
    "Contrary to Mann's assertion...", the opposite of what the claim says).

    **The re-bar (issue #607).** That defect's own passage does not
    contradict the claim's bare proposition -- what it contradicts is the
    claim's crediting of a scholar, which `grounds_text` alone never states,
    because it is the cited note's OWN `arguing_against` answer that states
    it. `arguing_against_text` shows the judge that field directly, framed as
    what the passage itself says it argues against, so a claim that credits
    the wrong side of a stated opposition is now visible to the question
    being asked."""
    arguing_against_block = (
        arguing_against_text.strip() or "(none of the cited notes recorded an opposing position)"
    )
    return f"""You are the independent grounding judge of an analysis engine's rung-3 eval gate (specs/PHASE-B.md §10). You are NOT the model that generated this claim -- you are judging its evidence.

This is a kind-"b" claim: a cross-source INFERENCE the tool drew across two or more sources, not a single source's own assertion. The bar for an inference is not whether a cited passage asserts it outright -- it may not, and still be a sound inference -- but whether any cited passage CONTRADICTS it.

Claim (the tool's own inference):
"{claim_text}"

Cited grounds (the resolved chunk/artifact text the claim points at):
"{grounds_text}"

What the cited passage(s) themselves say they argue against (each note's own recorded opposition, if any):
"{arguing_against_block}"

Decide: does any part of the cited grounds text, OR the opposition it itself records above, CONTRADICT the claim -- state or clearly imply the opposite of what the claim asserts, or credit the claim's position to the wrong side of a stated disagreement? Judge only what the grounds text and its recorded opposition actually say, not whether it goes as far as the claim on its own.

Return ONLY this JSON object, no prose and no code fence:
{{"verdict": "contradicts"}} or {{"verdict": "does_not_contradict"}}"""


def _parse_b_claim_judge_response(raw: str, claim_id: str) -> str:
    data = parse_model_json(raw)
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict not in _CONTRADICTION_VERDICTS:
        raise GroundingCheckFailedError(
            f"claim {claim_id!r}: (b)-claim contradiction judge response carries no valid "
            f"'verdict' in {sorted(_CONTRADICTION_VERDICTS)!r}: {data!r}"
        )
    return verdict


def _judge_b_claim(
    claim_text: str,
    grounds_text: str,
    arguing_against_text: str,
    claim_id: str,
    *,
    client: LLMClient,
    judge_pass_name: str,
) -> str:
    prompt = _compose_b_claim_judge_prompt(claim_text, grounds_text, arguing_against_text)
    try:
        raw = complete_json(client, prompt, pass_name=judge_pass_name)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise GroundingCheckFailedError(
            f"claim {claim_id!r}: (b)-claim contradiction judge call failed: {exc}"
        ) from exc
    return _parse_b_claim_judge_response(raw, claim_id)


def _iter_claims_of_kind(
    records: list[dict[str, Any]], kind: str
) -> list[tuple[str, dict[str, Any]]]:
    """Every claim of `kind` across every record, paired with a best-effort
    claim_id (falling back to a positional placeholder, mirroring
    `axial.validators.attribution._claim_id_of`). The shared walk behind
    both `_iter_a_claims` (§10: "computed over (a) claims only") and the
    (b)-claim contradiction check's own denominator (issue #550) -- one
    index counter across BOTH kinds, so a claim_id fallback never collides
    between the two even when a record mixes them."""
    claims: list[tuple[str, dict[str, Any]]] = []
    index = 0
    for record in records:
        for claim in record.get("claims") or []:
            index += 1
            if claim.get("kind") != kind:
                continue
            claim_id = claim.get("claim_id") or f"<claim #{index}>"
            claims.append((claim_id, claim))
    return claims


def _iter_a_claims(records: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Every kind-"a" claim across every record -- (b)/(c) claims are
    excluded from `grounding_support_rate`'s denominator entirely (§10:
    "computed over (a) claims only")."""
    return _iter_claims_of_kind(records, "a")


def _iter_b_claims(records: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Every kind-"b" claim across every record -- the (b)-claim
    contradiction check's own denominator (issue #550), kept separate from
    `grounding_support_rate` because the two ask different questions and
    must never average together."""
    return _iter_claims_of_kind(records, "b")


def _iter_new_b_claims(records: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Every kind-"b" claim across every record whose `origin` is `None` --
    a Phase-C NEW (b) claim (specs/PHASE-C.md §7.4), Phase C's own
    contribution, as opposed to a Phase-B (b) claim merely carried through
    with its `origin` naming the analysis record it came from. This is
    `run_paper_grounding_gate`'s own denominator (§10.1, §8 P0-9): a carried
    (b) claim already went through whatever Phase B did or did not gate it
    on, so re-litigating it here would double-count rather than measure the
    thing this phase adds. Falls back to `paper_claim_id` (the paper
    record's own claim-id field, §7.4) before `claim_id`, since a paper
    claim never carries the latter."""
    claims: list[tuple[str, dict[str, Any]]] = []
    index = 0
    for record in records:
        for claim in record.get("claims") or []:
            index += 1
            if claim.get("kind") != "b" or claim.get("origin") is not None:
                continue
            claim_id = claim.get("paper_claim_id") or claim.get("claim_id") or f"<claim #{index}>"
            claims.append((claim_id, claim))
    return claims


def _b_claim_contradiction_rate(
    b_claims: list[tuple[str, dict[str, Any]]],
    *,
    client: LLMClient,
    vault_dir: Path | None,
    judge_pass_name: str,
) -> dict[str, Any]:
    """The reported-only (b)-claim measure (issue #550, module docstring):
    the share of kind-"b" claims where SOME cited passage contradicts the
    claim. Raises `UnresolvableGroundsError`/`GroundingCheckFailedError`
    exactly like the (a)-claim judge -- a broken pointer or a failed judge
    call is a gate error here too, never silently swallowed into a
    "does_not_contradict" verdict."""
    contradicted, _contradicted_ids = _judge_b_claims(
        b_claims, client=client, vault_dir=vault_dir, judge_pass_name=judge_pass_name
    )

    denominator = len(b_claims)
    return {
        "value": (len(contradicted) / denominator) if denominator else None,
        "numerator": len(contradicted),
        "denominator": denominator,
        "contradicted_claim_ids": contradicted,
        **({} if denominator else {"reason": "no (b) claims found to evaluate"}),
    }


def _judge_b_claims(
    b_claims: list[tuple[str, dict[str, Any]]],
    *,
    client: LLMClient,
    vault_dir: Path | None,
    judge_pass_name: str,
    fail_unresolvable_claims: bool = False,
) -> tuple[list[str], list[str]]:
    """Judge every claim in `b_claims`, re-barred (issue #607): each judge
    call is shown both the resolved grounds text and the grounds notes' own
    `arguing_against` answers. Returns `(contradicted_claim_ids,
    all_claim_ids)` -- the shared walk behind both the reported-only
    `_b_claim_contradiction_rate` above and the gated
    `run_paper_grounding_gate` below, so the re-bar is one code path, never
    two judge calls per claim.

    Raises `UnresolvableGroundsError` on the first claim whose grounds do
    not resolve, UNLESS `fail_unresolvable_claims` is set (issue #627). Phase
    B's `_b_claim_contradiction_rate` above never sets it: an unresolvable
    pointer reaching this judge means a record skipped attribution-fidelity's
    own grounds check first, a gate error there (module docstring).
    `run_paper_grounding_gate` DOES set it: a directory of real paper records
    can hold one whose (b)-claim grounds no longer resolve (the corpus moved
    on since the paper was drafted), and that record must fail on its own
    metric rather than abort every other record `--records` was pointed at.
    With it set, an unresolvable claim is folded into `contradicted_claim_ids`
    without a judge call -- a ceiling this gate cannot verify is the
    conservative, non-passing reading, never silently dropped."""
    contradicted: list[str] = []
    all_ids: list[str] = []
    for claim_id, claim in b_claims:
        all_ids.append(claim_id)
        try:
            grounds_text = _resolve_grounds_text(claim, claim_id, vault_dir=vault_dir)
            arguing_against_text = _resolve_grounds_arguing_against(
                claim, claim_id, vault_dir=vault_dir
            )
        except UnresolvableGroundsError:
            if not fail_unresolvable_claims:
                raise
            contradicted.append(claim_id)
            continue
        verdict = _judge_b_claim(
            claim.get("text", ""),
            grounds_text,
            arguing_against_text,
            claim_id,
            client=client,
            judge_pass_name=judge_pass_name,
        )
        if verdict == _CONTRADICTS:
            contradicted.append(claim_id)
    return contradicted, all_ids


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
    `records`, plus the reported-only `b_claim_contradiction_rate` (issue
    #550, module docstring) over every kind-"b" claim -- a separate number,
    never averaged into the (a)-claim rate and never gating release (`
    GateReport.reported`, not `metrics`). Raises `SelfGradingError` before
    any judge call is made when `judge_pass_name` resolves to the same model
    as `SYNTHESIZE_PASS_NAME` (checked once, since both measures share the
    one judge pass); raises `UnresolvableGroundsError` when a claim's
    grounds pointer does not resolve; raises `GroundingCheckFailedError`
    when the judge's own call or response fails."""
    a_claims = _iter_a_claims(records)
    b_claims = _iter_b_claims(records)

    if a_claims or b_claims:
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
    reported = {
        "b_claim_contradiction_rate": _b_claim_contradiction_rate(
            b_claims, client=client, vault_dir=vault_dir, judge_pass_name=judge_pass_name
        )
    }
    return GateReport(
        gate=GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[metric],
        reported=reported,
    )


def run_paper_grounding_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    judge_pass_name: str = GROUNDING_PASS_NAME,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> GateReport:
    """Phase C's own GATED use of the (b)-claim judge (specs/PHASE-C.md
    §10.1, §8 P0-9), scored over `records` (Phase-C paper records,
    `axial.gates.harness.load_paper_records`) -- `PAPER_GATE_NAME`'s own
    runner, registered separately from `run_grounding_gate` above.

    Denominator is `_iter_new_b_claims`: a paper's NEW (b) claims only
    (`origin is None`, §7.4) -- Phase C's own contribution, not a carried
    (b) claim Phase B already produced. `b_claim_noncontradiction_rate` is
    the INVERSE of the reported-only `b_claim_contradiction_rate` above (the
    share of new (b) claims NOT contradicted), gated at its own metric name
    so it never shares a config-tunable threshold with the always-reported
    Phase-B number. Zero new (b) claims is a legitimate, common state (a
    single-source-record paper produces none) and is reported
    not-scoreable, never a vacuous fail -- an inverted rate's vacuous value
    (`0.0`) would otherwise read as "0% non-contradicted", the opposite of
    what an empty population means.

    The self-grading guard is re-anchored to `PAPER_DRAFT_PASS_NAME`
    (`SelfGradingError`'s own `generating_pass_name`), since Phase C's
    generating pass is drafting, never Phase-B's `SYNTHESIZE_PASS_NAME`.

    Never raises `UnresolvableGroundsError` (issue #627): a new (b) claim
    whose grounds no longer resolve is folded into `contradicted_claim_ids`
    instead, so one paper record with a stale grounds pointer fails on its
    own metric without stopping every other record in `records` from being
    scored (`_judge_b_claims`'s own `fail_unresolvable_claims` docstring)."""
    new_b_claims = _iter_new_b_claims(records)

    if new_b_claims:
        drafting_model = client.model_for_pass(PAPER_DRAFT_PASS_NAME)
        judge_model = client.model_for_pass(judge_pass_name)
        if judge_model == drafting_model:
            raise SelfGradingError(
                judge_pass_name, judge_model, generating_pass_name=PAPER_DRAFT_PASS_NAME
            )

    if not new_b_claims:
        metric = not_scoreable_metric(
            "b_claim_noncontradiction_rate",
            reason="no new (b) claims found to evaluate",
            config_path=config_path,
        )
    else:
        contradicted_ids, all_ids = _judge_b_claims(
            new_b_claims,
            client=client,
            vault_dir=vault_dir,
            judge_pass_name=judge_pass_name,
            fail_unresolvable_claims=True,
        )
        metric = build_metric_result(
            "b_claim_noncontradiction_rate",
            numerator=len(all_ids) - len(contradicted_ids),
            denominator=len(all_ids),
            config_path=config_path,
            detail={"contradicted_claim_ids": contradicted_ids} if contradicted_ids else {},
            empty_denominator_fails=True,
        )

    return GateReport(
        gate=PAPER_GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[metric],
    )
