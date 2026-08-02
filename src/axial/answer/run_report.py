"""The per-run report (specs/PHASE-B.md §7.15, §8 P0-14, issue #491): one
report per brief run at `data/runs/<brief_id>.json`, keyed on `brief_id` and
`corpus_pin` so runs join across a set.

A separate artifact rather than a field, because §7.3's record shape is
locked and the report is a derived view. A record is the audit surface; a
report is what a run's numbers are read off. **Nothing gates on it.**

Computed, not measured twice
----------------------------------------------------------------------
Every figure here is derived from the persisted record except **per-pass
wall clock**, which only the running process holds. `PassClock` captures it
(`run_brief` times each stage as it drives it) and the run TOTAL is the sum
of those per-pass figures -- never a second stopwatch around the whole run,
which would silently absorb vault I/O and disagree with its own parts.
`axial brief sweep` already times each `(brief, draw)` pair
(`DrawOutcome.latency_seconds`); with per-pass figures on the report that
number becomes a cross-check on their sum rather than a competing source of
truth.

Zero model calls, except the two judged accuracy numbers
----------------------------------------------------------------------
The operational and response-quality sets, and both MECHANICAL accuracy
numbers, are pure arithmetic over the record plus deterministic vault reads.
The two JUDGED numbers (§10.0) each run under their own pass name and never
as the generating model: `grounding_support_rate` reuses the rung-3
grounding gate wholesale, and `instant_dismissal_violations` runs
`axial.answer.dismissal`. Both are reported as **not-scored with a stated
reason** when no judge client is supplied -- never as a 0 that reads like a
measurement, and never as a silent pass. That is the same three-state
discipline §10 states for a gate metric, applied to a report that gates
nothing.

The four accuracy numbers are reported separately and are never summed,
averaged or headlined as one figure (§10.0, D8).

The headline is the cross-source rate (D9)
----------------------------------------------------------------------
The share of (b) claims whose grounds span two or more distinct
`source_id`s. Phase A v1's whole premise is cross-book meeting points, and a
(b) claim grounded in one book has produced no synthesis however completely
it is attributed. Every other metric here can look healthy on a
well-attributed single-book summary.
"""

from __future__ import annotations

import json
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from axial.answer.dismissal import DismissalJudgeError, judge_instant_dismissal
from axial.answer.render import render_markdown
from axial.answer.source_usage import full_name_page, source_ids_for_grounds
from axial.eval.cases import load_case
from axial.eval.classification import SourceClassification, load_classification
from axial.gates.grounding import GroundingGateError, run_grounding_gate
from axial.llm import LLMClient
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_runs_dir
from axial.query.reader import source_id_from_chunk_id
from axial.retrieve.tools import TOOL_REGISTRY
from axial.validators.attribution import _check_grounds, _check_kind, _claim_id_of

CLAIM_KINDS = ("a", "b", "c")

# The report's own not-scored reasons, stated rather than left to a bare
# `null` a reader has to guess at.
NO_JUDGE_CLIENT_REASON = (
    "not scored: a judged measure (§10.0) needs a judge client running under "
    "its own pass name; the report itself makes no model call"
)
NO_CASE_REASON = "not scored: no sim case file (§9.3) is joined to this run"
NO_CLASSIFICATION_REASON = (
    "not scored: no source classification (evals/sources/classification.json, issue #563)"
)
NO_GROUNDS_REASON = "not scored: this run produced no ground citation"
NO_BASELINE_REASON = (
    "not scored: evals/sources/classification.json carries no note_weighted_baseline "
    "(issue #563 follow-up) -- a source-count share is not reported in its place, "
    "since it is a different, unreliable quantity"
)


class PassClock:
    """Per-pass wall clock -- the one figure §7.15 says the record cannot
    supply, because only the running process holds it.

    Accumulates seconds per pass name, so a pass entered twice (a retrieval
    loop's turns are one pass, not many) sums rather than overwrites. Uses
    `time.monotonic`, never the wall calendar, so a clock adjustment mid-run
    cannot produce a negative elapsed time."""

    def __init__(self) -> None:
        self._seconds: dict[str, float] = {}

    @contextmanager
    def time(self, pass_name: str) -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
        finally:
            self._seconds[pass_name] = self._seconds.get(pass_name, 0.0) + (
                time.monotonic() - start
            )

    def seconds_by_pass(self) -> dict[str, float]:
        return dict(self._seconds)


# ---------------------------------------------------------------------------
# Operational
# ---------------------------------------------------------------------------


def _evidence_figures(evidence: dict[str, Any]) -> dict[str, Any]:
    """The record's own `evidence` field (§7.3, issue #545), carried
    through with the arithmetic a reader would otherwise do by hand:
    `dropped_count` (assembled minus composed) and `composed_share`
    (composed / assembled, `None` when nothing was assembled -- a `refuse`
    disposition, or a run whose retrieval reached nothing -- rather than a
    division by zero).

    Replaying seven persisted smoke runs, 506 notes were assembled and 146
    reached a model -- 360 were paid for and read by nothing, and this is
    the figure that makes the next run comparable to those seven. Operator-
    facing only, same as the rest of this report: nothing here reaches a
    prompt."""
    assembled = int(evidence.get("assembled_count") or 0)
    composed = int(evidence.get("composed_count") or 0)
    return {
        "assembled_count": assembled,
        "composed_count": composed,
        "dropped_count": assembled - composed,
        "composed_share": (composed / assembled) if assembled else None,
    }


def _latency(latency_by_pass: dict[str, float], model_by_pass: dict[str, Any]) -> dict[str, Any]:
    """One elapsed figure per pass `model_by_pass` names (P0-14's own
    observable), plus their sum as the total. A pass that ran but was never
    timed reports `0.0` rather than being dropped, so the key set always
    matches `model_by_pass`; a timed pass that `model_by_pass` does not name
    is not a pass this run made and is left out."""
    by_pass = {name: float(latency_by_pass.get(name, 0.0)) for name in sorted(model_by_pass)}
    return {"by_pass": by_pass, "total": sum(by_pass.values())}


def _trajectory_figures(trajectory: list[dict[str, Any]]) -> dict[str, int]:
    """Step count, tool calls, rejected tool calls, and the convergence
    signal §7.6 does not carry.

    `rejected_tool_calls` counts entries naming a tool the registry does not
    hold -- a call the dispatcher deliberately refused before it ever
    reached the vault. It is a LOWER bound on failed calls and says so: the
    §7.6 entry (`{step, tool, args, result_ids, result_count}`, plus `total`/
    `detail` since issue #493) still carries no error field, so a registered
    tool rejected for malformed args is indistinguishable here from a valid
    call that legitimately returned nothing. `empty_result_calls` is the
    honest superset those land in.

    `turns_without_new_evidence` is #505's convergence signal: a turn that
    re-fetches only already-seen ids changes nothing downstream, because
    `assemble_evidence_ids` dedupes and the model's own reasoning text is
    never persisted. Counted per ENTRY, which is per CALL -- a batched
    `get_chunk` (issue #542) returns several ids in one entry and counts as
    one turn, adding new evidence if any one of them is new. Counted only
    over turns
    that could have added evidence at all (`returns_chunk_ids`), so a
    resolution call like `find_names` -- which never yields evidence by
    construction -- is not miscounted as a wasted turn."""
    seen: set[str] = set()
    tool_calls = 0
    rejected = 0
    empty = 0
    evidence_calls = 0
    without_new_evidence = 0

    for entry in trajectory:
        if not isinstance(entry, dict):
            continue
        tool_calls += 1
        tool = entry.get("tool")
        spec = TOOL_REGISTRY.get(tool) if isinstance(tool, str) else None
        if spec is None:
            rejected += 1
        if not (entry.get("result_count") or 0):
            empty += 1
        if spec is None or not spec.returns_chunk_ids:
            continue
        evidence_calls += 1
        ids = {i for i in (entry.get("result_ids") or []) if isinstance(i, str)}
        if not (ids - seen):
            without_new_evidence += 1
        seen |= ids

    return {
        "steps": tool_calls,
        "tool_calls": tool_calls,
        "rejected_tool_calls": rejected,
        "empty_result_calls": empty,
        "evidence_tool_calls": evidence_calls,
        "turns_without_new_evidence": without_new_evidence,
    }


def _cost_figures(cost: dict[str, Any]) -> dict[str, Any]:
    """§7.14's `cost` field with a token total folded in -- the dollars and
    tokens §7.15 asks for, per pass and total. `total_usd` is carried
    through exactly as the record holds it (`null` when no pass priced),
    never coerced to 0."""
    by_pass = cost.get("by_pass") or {}
    total_tokens = sum(int(entry.get("total_tokens") or 0) for entry in by_pass.values())
    return {"by_pass": by_pass, "total_tokens": total_tokens, "total_usd": cost.get("total_usd")}


# ---------------------------------------------------------------------------
# Accuracy (§10.0 -- four measures, reported separately, never summed)
# ---------------------------------------------------------------------------


def _attribution_completeness(
    claims: list[dict[str, Any]], *, vault_dir: Path | None
) -> dict[str, Any]:
    """The mechanical hard-gate measure: the share of claims carrying a
    valid `kind` AND resolvable (a)/(b) grounds. Reuses
    `axial.validators.attribution`'s own kind/grounds checks rather than
    re-implementing grounds resolution, the same way
    `axial.gates.attribution` does. An empty claim set (a `refuse`
    disposition) reports `null`, never a vacuous 1.0."""
    failing: list[str] = []
    for index, claim in enumerate(claims, start=1):
        claim_id = _claim_id_of(claim, index)
        if _check_kind(claim, claim_id) is not None:
            failing.append(claim_id)
            continue
        if _check_grounds(claim, claim_id, claim["kind"], vault_dir=vault_dir) is not None:
            failing.append(claim_id)
    total = len(claims)
    complete = total - len(failing)
    return {
        "value": (complete / total) if total else None,
        "numerator": complete,
        "denominator": total,
        "failing_claim_ids": failing,
        **({} if total else {"reason": "not scored: this run produced no claim"}),
    }


def _retrieval_hit(
    grounds_source_ids: set[str],
    *,
    case_id: str | None,
    cases_dir: Path | None,
) -> dict[str, Any]:
    """The phase's one mechanical accuracy oracle (§9.3, §10.0, issue #560):
    the share of the case's `required_citation_legs` this run's grounds
    reached. A leg is reached when the grounds cite ANY source in its
    `any_of` -- a flat AND list of ids cannot express "this leg is satisfied
    by any book that carries it", so the unit is the leg, not the id. The
    older flat `required_citation_source_ids` is read by `load_case` as one
    leg per id, so a case that has not been re-authored scores exactly as it
    always did.

    Reports not-scored with a reason when no case is joined to the run or
    the case names no legs -- a brief without a case has no oracle, which is
    a fact about the input, not a score of 0. Names the **unreached legs by
    name**, since which demand an answer did not reach is the point of the
    oracle."""
    if case_id is None:
        return {"value": None, "reason": NO_CASE_REASON}
    case = load_case(case_id, cases_dir=cases_dir)
    if case is None:
        return {
            "value": None,
            "case_id": case_id,
            "reason": f"not scored: no case file for case_id {case_id!r} (§9.3)",
        }
    legs = case.required_citation_legs
    if not legs:
        return {
            "value": None,
            "case_id": case.case_id,
            "reason": f"not scored: case {case.case_id!r} names no required_citation_legs",
        }
    reached_legs = [leg.leg for leg in legs if grounds_source_ids.intersection(leg.any_of)]
    missed_legs = [leg.leg for leg in legs if not grounds_source_ids.intersection(leg.any_of)]
    return {
        "value": len(reached_legs) / len(legs),
        "numerator": len(reached_legs),
        "denominator": len(legs),
        "case_id": case.case_id,
        "required_legs": [{"leg": leg.leg, "any_of": list(leg.any_of)} for leg in legs],
        "reached_legs": reached_legs,
        "missed_legs": missed_legs,
    }


def _grounding_support_rate(
    record: dict[str, Any],
    *,
    client: LLMClient | None,
    vault_dir: Path | None,
    config_path: Path,
) -> dict[str, Any]:
    """The judged support rate on (a) claims (§10.0), reusing the rung-3
    grounding gate wholesale -- its judge pass, its self-grading guard and
    its per-claim call shape, never a second judge seam. A gate error is
    reported as not-scored naming the error rather than crashing the report:
    the report gates nothing, so it must not be the thing that fails a
    run."""
    if client is None:
        return {"value": None, "reason": NO_JUDGE_CLIENT_REASON}
    try:
        gate_report = run_grounding_gate(
            [record],
            client=client,
            vault_dir=vault_dir,
            corpus_pin=record.get("corpus_pin"),
            trusted=False,
            config_path=config_path,
        )
    except GroundingGateError as exc:
        return {"value": None, "reason": f"not scored: grounding judge failed: {exc}"}
    metric = gate_report.metrics[0]
    return {"value": metric.value, "denominator": metric.n}


def _instant_dismissal_violations(
    record: dict[str, Any],
    *,
    client: LLMClient | None,
    case_id: str | None,
    cases_dir: Path | None,
) -> dict[str, Any]:
    """The judged measure §9.3 called out as authored, non-empty on all 21
    cases and read by nothing: did the answer do a thing the case declares
    disqualifying on sight. Reported as a violation COUNT and rate, never
    inverted into a score."""
    if client is None:
        return {"value": None, "reason": NO_JUDGE_CLIENT_REASON}
    if case_id is None:
        return {"value": None, "reason": NO_CASE_REASON}
    case = load_case(case_id, cases_dir=cases_dir)
    if case is None or not case.instant_dismissal_criteria:
        return {
            "value": None,
            "case_id": case_id,
            "reason": f"not scored: case {case_id!r} states no instant_dismissal_criteria",
        }
    try:
        result = judge_instant_dismissal(record, case.instant_dismissal_criteria, client=client)
    except DismissalJudgeError as exc:
        return {"value": None, "case_id": case_id, "reason": f"not scored: {exc}"}
    return {
        "value": result.rate,
        "violations": result.violations,
        "criteria_count": result.criteria_count,
        "violated_criteria": result.violated_criteria,
        "case_id": case.case_id,
    }


# ---------------------------------------------------------------------------
# Response quality
# ---------------------------------------------------------------------------


def _concentration(shares: list[float]) -> dict[str, Any]:
    """Top-1 share and HHI over the per-source evidence shares (§7.13) --
    one number for the well-attributed monoculture §7.13 exists to detect.
    HHI is the sum of squared shares on the 0-1 scale, so a single-source
    run reads 1.0 and an evenly-spread N-source run reads 1/N."""
    if not shares:
        return {"top_1_share": None, "hhi": None}
    return {"top_1_share": max(shares), "hhi": sum(share * share for share in shares)}


def _commentary_mix(
    sources: list[dict[str, Any]], *, classification: SourceClassification | None
) -> dict[str, Any]:
    """Issue #563: of this run's ground citations, the share drawn from a
    `commentary` source -- a book *about* another thinker's body of work
    (`hall-2006` on Michael Mann, `malesevic-2007` on Ernest Gellner) rather
    than one that states its own argument. A `commentary` volume answering a
    brief is a different kind of evidence than a primary text, and nothing
    else on this report can see the difference.

    Reuses `source_usage`'s own per-source `evidence_chunk_count` (§7.13,
    stage 6's distinct-grounds-pointer count) rather than re-walking claim
    grounds a second time -- this figure asks the same "how many of this
    run's ground citations" question `per_source_share` already answers, just
    folded over the classification's `commentary` subset instead of read one
    source at a time.

    Not a gate (§7.13/§10.0): disclosed and recorded from the first run,
    promoted only once the distribution has been inspected. Three-state,
    like the neighbouring §7.13 figures -- no classification file, or a run
    with no ground citation at all (`sources` empty, e.g. a `refuse`
    disposition), reports `value: None` with a stated reason, never a 0 that
    reads like a measurement. `baseline_share` -- the classification's own
    NOTE-WEIGHTED corpus-wide commentary share, read straight off committed,
    measured data (`axial.eval.classification`) -- travels alongside the
    run's share even when unscored, so the number the run's mix is being
    read against is never a second lookup away. The baseline carries its OWN
    three-state discipline, one level down: a classification file that
    carries no measured `note_weighted_baseline` reports `baseline_share:
    None` with its own `baseline_reason`, never a source-count share
    substituted in its place -- a wrong baseline read as right is worse than
    an absent one (issue #563 follow-up)."""
    if classification is None:
        return {"value": None, "reason": NO_CLASSIFICATION_REASON}

    baseline = classification.baseline_commentary_share
    baseline_fields: dict[str, Any] = {"baseline_share": baseline}
    if baseline is None:
        baseline_fields["baseline_reason"] = NO_BASELINE_REASON

    total = sum(int(entry.get("evidence_chunk_count") or 0) for entry in sources)
    if not total:
        return {"value": None, "reason": NO_GROUNDS_REASON, **baseline_fields}

    commentary_ids = classification.commentary_source_ids
    commentary_entries = [entry for entry in sources if entry.get("source_id") in commentary_ids]
    numerator = sum(int(entry.get("evidence_chunk_count") or 0) for entry in commentary_entries)
    return {
        "value": numerator / total,
        "numerator": numerator,
        "denominator": total,
        "commentary_source_ids": sorted(entry["source_id"] for entry in commentary_entries),
        **baseline_fields,
    }


def _claim_mix(claims: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {kind: sum(1 for c in claims if c.get("kind") == kind) for kind in CLAIM_KINDS}
    total = len(claims)
    shares = {kind: (counts[kind] / total if total else None) for kind in CLAIM_KINDS}
    return {"counts": counts, "shares": shares}


def _cross_source_rate(claims: list[dict[str, Any]], *, vault_dir: Path | None) -> dict[str, Any]:
    """**The headline (D9).** The share of (b) claims whose grounds span two
    or more distinct `source_id`s. A run with no (b) claim at all reports
    `null` with a reason -- there is nothing to take a share of, and a
    vacuous 1.0 or 0.0 would read as a verdict on a question never asked."""
    b_claims = [claim for claim in claims if claim.get("kind") == "b"]
    if not b_claims:
        return {
            "value": None,
            "numerator": 0,
            "denominator": 0,
            "reason": "not scored: this run produced no (b) claim to take a share of",
        }
    spanning = sum(
        1 for claim in b_claims if len(source_ids_for_grounds(claim, vault_dir=vault_dir)) >= 2
    )
    return {
        "value": spanning / len(b_claims),
        "numerator": spanning,
        "denominator": len(b_claims),
    }


def _grounds_per_claim(claims: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [len(claim.get("grounds") or []) for claim in claims]
    if not counts:
        return {"mean": None, "median": None, "share_with_two_or_more": None}
    return {
        "mean": statistics.fmean(counts),
        "median": statistics.median(counts),
        "share_with_two_or_more": sum(1 for n in counts if n >= 2) / len(counts),
    }


def _grounds_ref_ids(claims: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Every distinct grounds pointer, split into (all ref_ids, chunk-only
    ref_ids). Chunk ids alone are what a name page's members can be
    intersected with; an artifact note is a member of no name page."""
    all_ids: set[str] = set()
    chunk_ids: set[str] = set()
    for claim in claims:
        for ground in claim.get("grounds") or []:
            if not isinstance(ground, dict):
                continue
            ref_id = ground.get("ref_id")
            if not isinstance(ref_id, str) or not ref_id:
                continue
            all_ids.add(ref_id)
            if ground.get("ref_type") == "chunk":
                chunk_ids.add(ref_id)
    return all_ids, chunk_ids


def _retrieval_precision(cited_ids: set[str], evidence: dict[str, Any]) -> dict[str, Any]:
    """Distinct notes cited over distinct notes **composed** into the
    synthesis prompt -- not assembled (issue #545's own correction, settled
    after a wrong number was published: 103 of 506 assembled reads as
    9.7%, but the synthesis model only ever saw 146 of those 506 -- the
    `evidence_char_budget` prefix `compose_prompt` actually walks -- and
    103 of 146 is 70.5%, the honest figure). Assembled-but-never-shown
    notes were paid for and read by no model; dividing by them understates
    precision by counting misses the model was never given a chance to
    make.

    `evidence` is the §7.3 record's own `evidence` field
    (`composed_count`, already computed by stage 4's `compose_prompt` walk
    -- see `_evidence_figures`). That field is **path-agnostic**: it is
    filled in identically whether stage 3 was the name-layer retrieval
    loop or the argument map (issue #572, PR 4 of 4), so this metric scores
    a map-retrieved run exactly as it scores a name-layer one, with no
    branch for either."""
    composed = int(evidence.get("composed_count") or 0)
    if not composed:
        return {
            "value": None,
            "cited_note_count": len(cited_ids),
            "composed_note_count": 0,
            "reason": "not scored: this run composed no note into the synthesis prompt",
        }
    return {
        "value": len(cited_ids) / composed,
        "cited_note_count": len(cited_ids),
        "composed_note_count": composed,
    }


def _name_pages_touched(claims: list[dict[str, Any]]) -> int:
    names: set[str] = set()
    for claim in claims:
        for name in claim.get("names_touched") or []:
            if isinstance(name, str) and name:
                names.add(name)
    return len(names)


def _name_reach_and_disagreement_reuse(
    record: dict[str, Any], grounds_chunk_ids: set[str], *, vault_dir: Path | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two figures off one pass over the §7.7 coverage-map names, since both
    need the same whole name pages.

    **name reach.** The number of distinct name pages the claims touch
    (`names_touched`, disclosed raw -- on the real corpus that is ~423 per
    evidence set, and that size is itself the signal), plus the share of the
    run's grounds notes that are members of a name the answer is ABOUT. The
    membership denominator is the §7.7 coverage scope rather than every
    mentioned name on purpose: 67.2% of live name pages touch exactly one
    note and 64.3% of the note-to-note joins come from twenty mostly-country
    names, so "a member of some name page" is true of nearly every note and
    would read high for trivial reasons.

    **disagreement reuse (D4).** Whether the run REACHED a note a Gather
    finding also cites -- never whether it repeated the finding, and never a
    quality verdict on the finding, which has never been scored."""
    coverage_map = record.get("coverage_map") or {}
    covered_members: set[str] = set()
    names_with_findings = 0
    finding_names_reached = 0

    for canonical in sorted(coverage_map):
        page = full_name_page(canonical, vault_dir=vault_dir)
        if page is None:
            continue
        members = {member.chunk_id for member in page.members}
        covered_members |= members
        if page.disagreement is not None:
            names_with_findings += 1
            if members & grounds_chunk_ids:
                finding_names_reached += 1

    in_scope = len(covered_members & grounds_chunk_ids)
    total_grounds = len(grounds_chunk_ids)
    name_reach = {
        "name_pages_touched": _name_pages_touched(record.get("claims") or []),
        "names_in_coverage_scope": len(coverage_map),
        "grounds_notes_in_a_covered_name": in_scope,
        "grounds_note_count": total_grounds,
        "share": (in_scope / total_grounds) if total_grounds else None,
    }
    disagreement_reuse = {
        "names_with_findings": names_with_findings,
        "names_whose_notes_were_reached": finding_names_reached,
        "reached": finding_names_reached > 0,
    }
    return name_reach, disagreement_reuse


def _coverage_bands(coverage_map: dict[str, Any]) -> dict[str, int]:
    bands = {"thin": 0, "moderate": 0, "dense": 0}
    for entry in coverage_map.values():
        band = entry.get("coverage_band") if isinstance(entry, dict) else None
        if band in bands:
            bands[band] += 1
    return bands


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def build_run_report(
    record: dict[str, Any],
    *,
    latency_by_pass: dict[str, float] | None = None,
    vault_dir: Path | None = None,
    case_id: str | None = None,
    cases_dir: Path | None = None,
    classification_path: Path | None = None,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, Any]:
    """The §7.15 run report for one persisted record.

    Deterministic: the same record and the same `latency_by_pass` always
    yield the same report. Makes ZERO model calls unless `client` is given,
    and even then only for the two judged accuracy numbers (§10.0), each
    under its own pass name and never the generating model.

    `classification_path` defaults to `evals/sources/classification.json`
    (`axial.eval.classification.default_classification_path`); a missing or
    unauthored file costs only the commentary-mix figure below (issue #563),
    reported not-scored, never a crash."""
    claims = record.get("claims") or []
    trajectory = record.get("trajectory") or []
    model_by_pass = record.get("model_by_pass") or {}
    source_usage = record.get("source_usage") or {}
    coverage_map = record.get("coverage_map") or {}
    evidence = record.get("evidence") or {}
    classification = load_classification(path=classification_path)

    cited_ids, grounds_chunk_ids = _grounds_ref_ids(claims)
    grounds_source_ids = {source_id_from_chunk_id(cid) for cid in grounds_chunk_ids}
    name_reach, disagreement_reuse = _name_reach_and_disagreement_reuse(
        record, grounds_chunk_ids, vault_dir=vault_dir
    )
    sources = source_usage.get("sources") or []

    return {
        "brief_id": record.get("brief_id"),
        "corpus_pin": record.get("corpus_pin"),
        "case_id": case_id,
        "operational": {
            "disposition": (record.get("interrogation") or {}).get("disposition"),
            "model_by_pass": model_by_pass,
            "cost": _cost_figures(record.get("cost") or {}),
            "latency_seconds": _latency(latency_by_pass or {}, model_by_pass),
            "trajectory": _trajectory_figures(trajectory),
            "evidence": _evidence_figures(evidence),
        },
        "accuracy": {
            "attribution_completeness": _attribution_completeness(claims, vault_dir=vault_dir),
            "retrieval_hit": _retrieval_hit(
                grounds_source_ids, case_id=case_id, cases_dir=cases_dir
            ),
            "grounding_support_rate": _grounding_support_rate(
                record, client=client, vault_dir=vault_dir, config_path=config_path
            ),
            "instant_dismissal_violations": _instant_dismissal_violations(
                record, client=client, case_id=case_id, cases_dir=cases_dir
            ),
        },
        "response_quality": {
            "sources_cited": len(sources),
            "per_source_share": {entry["source_id"]: entry["evidence_share"] for entry in sources},
            "concentration": _concentration([entry["evidence_share"] for entry in sources]),
            "usage_ratio": {entry["source_id"]: entry["usage_ratio"] for entry in sources},
            "commentary_mix": _commentary_mix(sources, classification=classification),
            "claim_mix": _claim_mix(claims),
            "cross_source_rate": _cross_source_rate(claims, vault_dir=vault_dir),
            "grounds_per_claim": _grounds_per_claim(claims),
            "retrieval_precision": _retrieval_precision(cited_ids, evidence),
            "name_reach": name_reach,
            "disagreement_reuse": disagreement_reuse,
            "coverage_bands": _coverage_bands(coverage_map),
            "answer_size": {
                "claim_count": len(claims),
                "rendered_word_count": len(render_markdown(record).split()),
            },
        },
    }


def persist_run_report(
    brief_id: str,
    report: dict[str, Any],
    *,
    runs_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> Path:
    """Write `report` to `<runs_dir>/<brief_id>.json` (§7.15), keyed
    deterministically on `brief_id` exactly like `persist_record` -- so
    re-running the same brief overwrites the same file rather than
    accumulating one per run."""
    if runs_dir is None:
        runs_dir = default_runs_dir(config_path)
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{brief_id}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def format_run_report(report: dict[str, Any]) -> str:
    """Render `report` as founder-facing text: the operational block, the
    four accuracy numbers named separately (never summed, §10.0), and the
    response-quality set with the cross-source rate called out as the
    headline."""
    operational = report.get("operational") or {}
    accuracy = report.get("accuracy") or {}
    quality = report.get("response_quality") or {}
    cost = operational.get("cost") or {}
    latency = operational.get("latency_seconds") or {}
    trajectory = operational.get("trajectory") or {}

    lines = [
        f"run report: brief_id={report.get('brief_id')} corpus_pin={report.get('corpus_pin')}",
        f"  disposition: {operational.get('disposition')}",
        f"  cost: total_usd={_fmt(cost.get('total_usd'))} total_tokens={cost.get('total_tokens')}",
        f"  wall clock: total={_fmt(latency.get('total'))}s",
    ]
    for pass_name, seconds in (latency.get("by_pass") or {}).items():
        entry = (cost.get("by_pass") or {}).get(pass_name) or {}
        lines.append(
            f"    {pass_name}: {_fmt(seconds)}s tokens={entry.get('total_tokens', 0)} "
            f"usd={_fmt(entry.get('usd'))}"
        )
    lines.append(
        f"  trajectory: steps={trajectory.get('steps')} "
        f"rejected={trajectory.get('rejected_tool_calls')} "
        f"turns_without_new_evidence={trajectory.get('turns_without_new_evidence')}"
    )
    evidence = operational.get("evidence") or {}
    lines.append(
        f"  evidence: assembled={evidence.get('assembled_count')} "
        f"composed={evidence.get('composed_count')} "
        f"composed_share={_fmt(evidence.get('composed_share'))}"
    )

    lines.append("  accuracy (four measures, never summed -- §10.0):")
    for name in (
        "attribution_completeness",
        "retrieval_hit",
        "grounding_support_rate",
        "instant_dismissal_violations",
    ):
        entry = accuracy.get(name) or {}
        reason = entry.get("reason")
        suffix = f" ({reason})" if entry.get("value") is None and reason else ""
        lines.append(f"    {name}: {_fmt(entry.get('value'))}{suffix}")

    cross_source = quality.get("cross_source_rate") or {}
    lines.append(
        f"  cross-source rate (headline, D9): {_fmt(cross_source.get('value'))} "
        f"over {cross_source.get('denominator')} (b) claim(s)"
    )
    concentration = quality.get("concentration") or {}
    lines.append(
        f"  sources cited: {quality.get('sources_cited')} "
        f"top_1_share={_fmt(concentration.get('top_1_share'))} "
        f"hhi={_fmt(concentration.get('hhi'))}"
    )
    lines.append(f"  claim mix: {(quality.get('claim_mix') or {}).get('counts')}")
    commentary = quality.get("commentary_mix") or {}
    commentary_reason = commentary.get("reason")
    commentary_suffix = (
        f" ({commentary_reason})" if commentary.get("value") is None and commentary_reason else ""
    )
    lines.append(
        f"  commentary mix (issue #563): {_fmt(commentary.get('value'))}{commentary_suffix} "
        f"vs. corpus baseline {_fmt(commentary.get('baseline_share'))}"
    )
    lines.append(f"  coverage bands: {quality.get('coverage_bands')}")
    return "\n".join(lines)
