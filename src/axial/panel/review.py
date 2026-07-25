"""Reviewer dispatch, verdict parsing and panel aggregation (issue #385,
specs/PHASE-B.md §9.4 properties 3, 4 and 5).

One panel run scores one packet with N >= 3 independent reviewers. Each sees
the same packet and none sees another's verdict, so the disagreement between
them is real signal about how stable the judgement is.

**The spread is the error bar, and a mean without one is not reportable.**
Three reviewers splitting weak/adequate/strong and three agreeing on
adequate are different results and must never render identically, so
`DimensionSummary` carries every band alongside the aggregate.

**Dispatch is through `complete_json`** -- the plain completion seam, which
takes no `tools` argument. That is the tool half of the seal (property 2):
the reviewer is not *told* to avoid the repo, it is structurally incapable
of reaching it. Never route a reviewer through `complete_with_tools`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from axial.llm import (
    PANEL_REVIEW_PASS_NAME,
    SYNTHESIZE_PASS_NAME,
    LLMClient,
    LLMError,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.panel.packet import ReviewPacket, assert_sealed
from axial.panel.vendor import guard_distinct_vendor

# §9.4 property 5: eval #1's three dimensions, scored separately. Free prose
# is unparseable, unaggregable, and invites exactly the fluency this phase
# distrusts.
DIMENSIONS: tuple[str, ...] = ("factual_correctness", "citation_grounding", "completeness")

# Ordinal, not numeric. A numeric reviewer score would manufacture precision
# the judgement does not carry -- the same reason §7.4's confidence
# vocabulary is three bands rather than a probability.
BANDS: tuple[str, ...] = ("weak", "adequate", "strong")
_BAND_RANK = {band: rank for rank, band in enumerate(BANDS)}

# The defect vocabulary. Closed rather than free-text because the positive
# control (axial.panel.control) plants defects of exactly these kinds and
# has to check the panel named them -- an open vocabulary would make
# "did it catch the plant" a string-matching guess.
DEFECT_KINDS: tuple[str, ...] = (
    "mis_grounded",
    "strawman_counter_position",
    "overconfident",
    "other",
)

# N >= 3 (property 4). Three is the floor, not a target: two reviewers
# cannot produce a meaningful spread.
MIN_REVIEWERS = 3


class PanelError(Exception):
    """Base class for panel-run failures."""


class TooFewReviewersError(PanelError):
    """Raised when a panel is configured with fewer than three reviewers."""

    def __init__(self, n: int):
        self.n = n
        super().__init__(
            f"a panel needs at least {MIN_REVIEWERS} reviewers to produce a "
            f"spread; got {n} (§9.4 property 4)"
        )


class ReviewerCallFailedError(PanelError):
    """Raised when a reviewer's call fails, or its response never parses to
    the structured shape. Never a silently imputed score (property 5)."""


def reviewer_pass_name(index: int) -> str:
    """Pass name for reviewer `index` (1-based), routable through the
    existing `model_by_pass` config seam."""
    return f"{PANEL_REVIEW_PASS_NAME}.{index}"


@dataclass(frozen=True)
class Defect:
    claim_id: str
    kind: str
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "kind": self.kind, "note": self.note}


@dataclass(frozen=True)
class ReviewerVerdict:
    """One reviewer's whole answer, kept verbatim in the report: an
    aggregate that hides who said what cannot be audited."""

    model: str
    vendor: str
    bands: dict[str, str]
    defects: list[Defect] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "vendor": self.vendor,
            "bands": dict(self.bands),
            "defects": [defect.to_json() for defect in self.defects],
        }


@dataclass(frozen=True)
class DimensionSummary:
    """One dimension across the panel. `spread` is the ordinal distance
    between the highest and lowest band any reviewer gave: 0 is unanimity,
    2 is total disagreement."""

    dimension: str
    bands: list[str]
    aggregate: str
    spread: int

    def to_json(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "bands": list(self.bands),
            "aggregate": self.aggregate,
            "spread": self.spread,
        }


@dataclass(frozen=True)
class PanelReport:
    """A panel run's whole result. `trusted` is false unless a positive
    control passed against this same panel configuration (property 6) --
    the harness never reports a trusted number on its own say-so."""

    brief_id: str
    corpus_pin: str | None
    reviewers: list[ReviewerVerdict]
    dimensions: list[DimensionSummary]
    trusted: bool
    frame: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "brief_id": self.brief_id,
            "corpus_pin": self.corpus_pin,
            "trusted": self.trusted,
            "referee": "model panel (specs/PHASE-B.md §9.4) -- never a human expert",
            "n_reviewers": len(self.reviewers),
            "vendors": sorted({r.vendor for r in self.reviewers}),
            "frame": dict(self.frame),
            "dimensions": [d.to_json() for d in self.dimensions],
            "reviewers": [r.to_json() for r in self.reviewers],
        }


def _compose_reviewer_prompt(packet: ReviewPacket) -> str:
    return f"""You are an independent peer reviewer. You are reading a submitted analysis and the evidence it cites, and nothing else. You did not write it, you have no access to how it was produced, and you must judge only what is in front of you.

{packet.prompt_body}

Judge the submission on three dimensions, each as one of "weak", "adequate", or "strong":

- factual_correctness: are the substantive assertions right?
- citation_grounding: does each claim actually rest on the evidence it cites?
- completeness: does it answer the question it set itself, including the strongest opposing position?

Then list every defect you find. Each defect names the claim it attaches to, and a kind from exactly this list:

- "mis_grounded": the cited evidence does not support the claim
- "strawman_counter_position": the opposing position is stated in a weakened form, or rests on evidence that does not oppose anything
- "overconfident": the claim asserts more certainty than its evidence carries
- "other": anything else, described in the note

Be exacting. A submission that reads fluently can still be wrong, and confident prose is not evidence.

Return ONLY this JSON object, no prose and no code fence:
{{"factual_correctness": "...", "citation_grounding": "...", "completeness": "...", "defects": [{{"claim_id": "...", "kind": "...", "note": "..."}}]}}"""


def _parse_verdict(raw: str, *, model: str, vendor: str) -> ReviewerVerdict:
    data = parse_model_json(raw)
    if not isinstance(data, dict):
        raise ReviewerCallFailedError(
            f"reviewer {model!r} returned {type(data).__name__}, not an object"
        )

    bands: dict[str, str] = {}
    for dimension in DIMENSIONS:
        band = data.get(dimension)
        if band not in _BAND_RANK:
            raise ReviewerCallFailedError(
                f"reviewer {model!r} returned no valid {dimension!r} band in "
                f"{list(BANDS)!r}: {band!r}"
            )
        bands[dimension] = band

    defects: list[Defect] = []
    for entry in data.get("defects") or []:
        if not isinstance(entry, dict):
            raise ReviewerCallFailedError(
                f"reviewer {model!r} returned a non-object defect: {entry!r}"
            )
        kind = entry.get("kind")
        if kind not in DEFECT_KINDS:
            raise ReviewerCallFailedError(
                f"reviewer {model!r} returned defect kind {kind!r}, not one of {list(DEFECT_KINDS)!r}"
            )
        defects.append(
            Defect(
                claim_id=str(entry.get("claim_id") or ""),
                kind=kind,
                note=str(entry.get("note") or ""),
            )
        )

    return ReviewerVerdict(model=model, vendor=vendor, bands=bands, defects=defects)


def _summarize(verdicts: list[ReviewerVerdict]) -> list[DimensionSummary]:
    summaries = []
    for dimension in DIMENSIONS:
        bands = [verdict.bands[dimension] for verdict in verdicts]
        ranks = [_BAND_RANK[band] for band in bands]
        # The aggregate is the median rank, floored on an even split. A mean
        # of ordinal bands would invent a value the vocabulary does not have.
        aggregate = BANDS[sorted(ranks)[(len(ranks) - 1) // 2]]
        summaries.append(
            DimensionSummary(
                dimension=dimension,
                bands=bands,
                aggregate=aggregate,
                spread=max(ranks) - min(ranks),
            )
        )
    return summaries


def review_packet(
    packet: ReviewPacket,
    *,
    client: LLMClient,
    n_reviewers: int = MIN_REVIEWERS,
    trusted: bool = False,
    frame: dict[str, Any] | None = None,
) -> PanelReport:
    """Dispatch `n_reviewers` independent reviewers over `packet` and
    aggregate their verdicts.

    Every guard fires BEFORE any reviewer call: too few reviewers, a seal
    breach, an undeclared vendor, or a reviewer sharing the generating
    model's training lab. `trusted` is supplied by the caller and is false
    unless a positive control passed against this same configuration
    (property 6) -- this function never decides it is trustworthy.
    """
    if n_reviewers < MIN_REVIEWERS:
        raise TooFewReviewersError(n_reviewers)

    assert_sealed(packet)

    generating_model = client.model_for_pass(SYNTHESIZE_PASS_NAME)
    reviewers: list[tuple[str, str, str]] = []
    for index in range(1, n_reviewers + 1):
        pass_name = reviewer_pass_name(index)
        model = client.model_for_pass(pass_name)
        vendor = guard_distinct_vendor(reviewer_model=model, generating_model=generating_model)
        reviewers.append((pass_name, model, vendor))

    prompt = _compose_reviewer_prompt(packet)
    verdicts: list[ReviewerVerdict] = []
    for pass_name, model, vendor in reviewers:
        try:
            raw = complete_json(client, prompt, pass_name=pass_name)
        except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
            raise ReviewerCallFailedError(f"reviewer {model!r} call failed: {exc}") from exc
        verdicts.append(_parse_verdict(raw, model=model, vendor=vendor))

    return PanelReport(
        brief_id=packet.brief_id,
        corpus_pin=packet.corpus_pin,
        reviewers=verdicts,
        dimensions=_summarize(verdicts),
        trusted=trusted,
        frame=dict(frame or {}),
    )


def format_panel_report(report: PanelReport) -> str:
    """Human-readable rendering. Always names the referee and the frame: a
    panel number reported without them is invalid (§9.2)."""
    lines = [f"panel: {report.brief_id}"]
    for dimension in report.dimensions:
        lines.append(
            f"  {dimension.dimension}: {dimension.aggregate} "
            f"(spread={dimension.spread}, bands={'/'.join(dimension.bands)})"
        )
    defect_count = sum(len(reviewer.defects) for reviewer in report.reviewers)
    lines.append(f"defects named: {defect_count}")
    lines.append(
        f"reviewers: {len(report.reviewers)} from vendors {sorted({r.vendor for r in report.reviewers})}"
    )
    lines.append(f"corpus_pin: {report.corpus_pin}")
    for key, value in sorted(report.frame.items()):
        lines.append(f"frame.{key}: {value}")
    lines.append(f"trusted: {report.trusted}")
    lines.append("referee: model panel (specs/PHASE-B.md §9.4) -- NOT human expert judgement")
    return "\n".join(lines)
