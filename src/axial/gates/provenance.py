"""The provenance-integrity rung-3 gate (specs/PHASE-C.md §10.1, §7.4, §8
P0-8; issue #606, B1 of #605).

Two metrics, both **mechanical, zero model calls**, scored over a directory
of Phase-C **paper** records (`axial.gates.harness.load_paper_records`) --
this gate never reads a Phase-B analysis record's own claims directly, only
the paper record's own `citations`/`claims` and, for a carried claim's
ceiling, the ORIGIN analysis record its `origin` names.

- `provenance_completeness` -- the share of citation markers (`citations`,
  §7.5) that resolve to a claim in the record's own `claims` list whose
  every grounds pointer resolves to a real vault id (`get_chunk`/
  `get_artifact`). A dangling marker or an unresolvable grounds pointer is
  never a gate ERROR here (contrast `axial.gates.grounding`, where an
  unresolvable (a)-claim grounds pointer aborts the run): P0-8's own
  observable is that such a record "fails outright" on the METRIC, at
  threshold 1.00 -- one bad marker moves the value below 1.00 rather than
  raising.
- `confidence_upgrade_count` -- the number of claims violating the §7.4
  confidence ceiling: a carried claim whose disclosed band exceeds its
  origin's CLAMPED band (`axial.paper.coverage.clamped_band_for`, issue
  #550), or a new (b)/(c) claim whose band exceeds the minimum clamped band
  among its `derived_from` claims. Threshold 0, hard. `axial.paper.claims.
  assert_ceilings` already enforces this identical rule at assembly time,
  but raises on the FIRST violation and stops -- exactly right for a run
  that must not proceed on a bad draft, exactly wrong for a gate that must
  report every violator in one pass. This module reuses `clamped_band_for`
  (the one shared source of truth for what a clamped band IS) but reimplements
  the walk, deliberately: collecting rather than raising is not a variant this
  module's own raise-fast contract should grow a flag for (mirrors
  `axial.paper.coverage`'s own choice to keep a duplicate, tiny `_BAND_RANK`
  local rather than reach into `axial.validators.coverage`'s private one).
  A carried claim whose origin cannot be resolved at all -- the source
  analysis is missing, or was regenerated and no longer carries the claim id
  -- is itself one more violation, caught by `_ceiling_violations` (issue
  #627), never a raise that aborts every other record `--records` was
  pointed at: a directory of real papers WILL hold one whose source analysis
  has since moved on, and that one paper failing outright is correct; the
  rest of the batch scoring cleanly is the fix.

**No panel field, no panel-derived trust condition, anywhere in this module**
(§10.1's own note, P0-8's fourth observable): the report is producible, and
passable, with zero reviewers configured, because this gate never constructs
one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axial.gates.harness import (
    GateReport,
    MetricResult,
    build_metric_result,
    compare,
    resolve_threshold,
)
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.paper.coverage import clamped_band_for
from axial.paths import default_analyses_dir
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    get_artifact,
    get_chunk,
)

GATE_NAME = "provenance-integrity"

# Bands ordered `low < medium < high` (§7.4). Deliberately a local literal,
# not imported from `axial.paper.claims` or `axial.paper.coverage`: this
# gate depends only on `axial.paper.coverage.clamped_band_for`, and a third
# tiny copy of a three-entry ordinal is cheaper than widening either
# module's surface for it (the same call `axial.paper.coverage` itself
# already made about not reaching into `axial.validators.coverage`'s own
# private rank map).
_BAND_RANK = {"low": 0, "medium": 1, "high": 2}


class ProvenanceGateError(Exception):
    """Base class for all provenance-integrity-gate errors."""


class UnresolvableOriginRecordError(ProvenanceGateError):
    """Raised internally when a carried claim's `origin.brief_id` names an
    analysis record that cannot be loaded from `analyses_dir` -- caught by
    `_ceiling_violations` (issue #627) and folded into a `confidence_upgrade_
    count` violation for that one claim, never left to propagate: a
    confidence ceiling this gate cannot verify must drag the metric down for
    the record that carries it, not abort every other record in the same
    `--records` directory. Still raised (not silently swallowed) so the
    catch site is the one place, and the one documented place, that decides
    what an unresolvable origin means."""

    def __init__(self, brief_id: str, path: Path):
        self.brief_id = brief_id
        self.path = path
        super().__init__(
            f"carried claim names origin analysis {brief_id!r}, but no record exists at "
            f"{path} -- the provenance-integrity gate cannot verify a confidence ceiling "
            f"against a source record it cannot read"
        )


class UnresolvableOriginClaimError(ProvenanceGateError):
    """Raised internally when a carried claim's `origin.claim_id` is not
    present in the origin analysis record's own `claims` list -- e.g. the
    source analysis was regenerated against a newer corpus and no longer
    carries the claim id a still-published paper names. Caught the same way
    as `UnresolvableOriginRecordError` above (issue #627): folded into a
    `confidence_upgrade_count` violation for that claim, batch continues."""

    def __init__(self, paper_claim_id: str, brief_id: str, claim_id: str):
        self.paper_claim_id = paper_claim_id
        self.brief_id = brief_id
        self.claim_id = claim_id
        super().__init__(
            f"paper claim {paper_claim_id!r} names origin ({brief_id!r}, {claim_id!r}), "
            f"which is not present in that analysis record's own claims"
        )


def _claim_grounds_resolve(claim: dict[str, Any], *, vault_dir: Path | None) -> bool:
    """Whether every one of `claim`'s grounds pointers resolves to a real
    vault id. An empty grounds list resolves vacuously (nothing to fail),
    mirroring `build_metric_result`'s own vacuous-but-honest convention for
    "nothing to check" states elsewhere in this harness."""
    for entry in claim.get("grounds") or []:
        if not isinstance(entry, dict):
            return False
        ref_type = entry.get("ref_type")
        ref_id = entry.get("ref_id")
        if ref_type == "chunk":
            try:
                get_chunk(ref_id, vault_dir=vault_dir)
            except ChunkNotFoundError:
                return False
        elif ref_type == "artifact":
            try:
                get_artifact(ref_id, vault_dir=vault_dir)
            except ArtifactNotFoundError:
                return False
        else:
            return False
    return True


def _score_provenance_completeness(
    records: list[dict[str, Any]], *, vault_dir: Path | None, config_path: Path
) -> MetricResult:
    """`provenance_completeness` (§10.1, §7.5): the share of citation-marker
    occurrences (`citations`, one entry per marker in document order) that
    name a real `paper_claim_id` in the SAME record's `claims`, whose
    grounds all resolve. The denominator is every citation occurrence across
    every record, not every distinct claim -- a marker cited three times
    that dangles is three failures, matching what a reader of the rendered
    paper actually hits three times."""
    total = 0
    resolved = 0
    dangling: list[str] = []
    for record in records:
        claims_by_id = {
            claim.get("paper_claim_id"): claim
            for claim in (record.get("claims") or [])
            if isinstance(claim, dict)
        }
        for citation in record.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            total += 1
            paper_claim_id = citation.get("paper_claim_id")
            claim = claims_by_id.get(paper_claim_id)
            if claim is not None and _claim_grounds_resolve(claim, vault_dir=vault_dir):
                resolved += 1
            else:
                dangling.append(str(paper_claim_id))

    return build_metric_result(
        "provenance_completeness",
        numerator=resolved,
        denominator=total,
        config_path=config_path,
        detail={"dangling_paper_claim_ids": dangling} if dangling else {},
        empty_denominator_fails=True,
    )


def _min_band(derived_from: list[Any], by_id: dict[str, dict[str, Any]]) -> Any:
    """The lowest band among the claims a new (b)/(c) claim stands on --
    mirrors `axial.paper.claims._min_band` exactly (same rule, same
    conservative "low" fallback when nothing is rankable); duplicated here
    for the same reason `_BAND_RANK` above is (module docstring)."""
    bands = [
        band
        for parent_id in derived_from
        if (band := (by_id.get(parent_id) or {}).get("confidence")) in _BAND_RANK
    ]
    if not bands:
        return "low"
    return min(bands, key=lambda band: _BAND_RANK[band])


def _origin_claim(origin_record: dict[str, Any], claim_id: Any) -> dict[str, Any] | None:
    for claim in origin_record.get("claims") or []:
        if isinstance(claim, dict) and claim.get("claim_id") == claim_id:
            return claim
    return None


def _load_origin_record(brief_id: str, analyses_dir: Path) -> dict[str, Any]:
    path = Path(analyses_dir) / f"{brief_id}.json"
    if not path.is_file():
        raise UnresolvableOriginRecordError(brief_id, path)
    return json.loads(path.read_text(encoding="utf-8"))


def _ceiling_violations(
    record: dict[str, Any], *, analyses_dir: Path, origin_cache: dict[str, dict[str, Any]]
) -> list[str]:
    """Every `paper_claim_id` in `record` whose band violates the §7.4
    ceiling: a carried claim's band must equal its origin's CLAMPED band
    exactly (neither higher -- inflation -- nor lower -- its own
    dishonesty); a new (b)/(c) claim's band may not exceed the minimum
    clamped band among its `derived_from` claims. `origin_cache` is shared
    across every record this gate scores in one run, keyed by `brief_id`, so
    a paper brief naming the same source analysis more than once (or a
    records directory holding more than one paper drawn from it) loads that
    analysis record once.

    A carried claim whose origin cannot be resolved -- the analysis record is
    missing, or the analysis record loads but no longer carries the claim id
    (issue #627: a source analysis regenerated against a newer corpus drops
    the old claim ids a still-published paper still names) -- counts as a
    VIOLATION of this claim, never a raise that aborts every other record in
    the same batch: the ceiling this gate exists to check cannot be verified,
    which is exactly what `confidence_upgrade_count` (a hard, threshold-0
    count) must reflect. `run_provenance_gate`'s caller sees one more
    genuinely-failing paper, not a report it never got at all."""
    claims = record.get("claims") or []
    by_id = {claim.get("paper_claim_id"): claim for claim in claims if isinstance(claim, dict)}
    violations: list[str] = []

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        paper_claim_id = str(claim.get("paper_claim_id"))
        band = claim.get("confidence")
        origin = claim.get("origin")

        if isinstance(origin, dict) and origin.get("brief_id"):
            brief_id = str(origin["brief_id"])
            claim_id = origin.get("claim_id")
            try:
                if brief_id not in origin_cache:
                    origin_cache[brief_id] = _load_origin_record(brief_id, analyses_dir)
                origin_record = origin_cache[brief_id]
                origin_claim = _origin_claim(origin_record, claim_id)
                if origin_claim is None:
                    raise UnresolvableOriginClaimError(paper_claim_id, brief_id, str(claim_id))
            except (UnresolvableOriginRecordError, UnresolvableOriginClaimError):
                violations.append(paper_claim_id)
                continue
            expected = clamped_band_for(origin_claim, origin_record.get("coverage_map") or {})
            if band != expected:
                violations.append(paper_claim_id)
            continue

        ceiling = _min_band(list(claim.get("derived_from") or []), by_id)
        if band in _BAND_RANK and ceiling in _BAND_RANK and _BAND_RANK[band] > _BAND_RANK[ceiling]:
            violations.append(paper_claim_id)

    return violations


def _score_confidence_upgrade_count(
    records: list[dict[str, Any]], *, analyses_dir: Path, config_path: Path
) -> MetricResult:
    """`confidence_upgrade_count` (§10.1, §7.4): a raw COUNT, not a rate --
    zero claims to check is a real, legitimate zero, never not-scoreable, so
    this builds its `MetricResult` directly rather than through
    `build_metric_result` (which always produces a `numerator/denominator`
    rate)."""
    threshold = resolve_threshold("confidence_upgrade_count", config_path)
    origin_cache: dict[str, dict[str, Any]] = {}
    total_claims = 0
    all_violations: list[str] = []
    for record in records:
        claims = record.get("claims") or []
        total_claims += len(claims)
        all_violations.extend(
            _ceiling_violations(record, analyses_dir=analyses_dir, origin_cache=origin_cache)
        )

    value = float(len(all_violations))
    return MetricResult(
        metric="confidence_upgrade_count",
        value=value,
        threshold=threshold,
        comparison="lte",
        passed=compare(value, threshold, "lte"),
        n=total_claims,
        detail={"violating_paper_claim_ids": all_violations} if all_violations else {},
    )


def run_provenance_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    analyses_dir: Path | None = None,
) -> GateReport:
    """Score both provenance-integrity metrics over `records` (Phase-C paper
    records, `axial.gates.harness.load_paper_records`). `client` is accepted
    only to match `axial.gates.run_gate`'s shared per-gate dispatch
    signature -- it is never called: both metrics are zero-model-call and
    mechanical (§8 P0-8). Never raises `UnresolvableOriginRecordError`/
    `UnresolvableOriginClaimError` (issue #627): a carried claim whose own
    origin cannot be resolved counts as a `confidence_upgrade_count`
    violation for that claim instead, so one record with a dangling origin
    fails on its own metrics without stopping every other record in
    `records` from being scored.

    Carries no panel field and no panel-derived trust condition (§10.1):
    `trusted` here resolves exactly as every other rung-3 gate's does, from
    the corpus pin alone (`axial.gates.harness.resolve_trusted`)."""
    del client
    resolved_analyses_dir = analyses_dir if analyses_dir is not None else default_analyses_dir()
    completeness = _score_provenance_completeness(
        records, vault_dir=vault_dir, config_path=config_path
    )
    upgrades = _score_confidence_upgrade_count(
        records, analyses_dir=resolved_analyses_dir, config_path=config_path
    )
    return GateReport(
        gate=GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[completeness, upgrades],
    )
