"""Stage-6 deterministic markdown answer rendering (specs/PHASE-B.md §7.10,
§8 P0-8, issue #261).

`render_markdown` is a pure function: an already-assembled §7.3 analysis
record (`axial.answer.record.build_record`'s own output, or the same shape
loaded back from `data/analyses/<brief_id>.json`) goes in, a markdown string
comes out. It reads ONLY the record -- no model call, no vault read, no
clock -- and is written alongside the JSON by `axial brief run` (§7.10).

Determinism is the property this module exists to hold (§7.10: "the same
record renders the same markdown"). Two things make that true regardless of
how the record dict was built or round-tripped through JSON:

- **Claims render in the record's own `claims` order.** No re-sorting, no
  set iteration -- the plan's own inner-loop rule.
- **Every other multi-entry section (`coverage_map`'s names,
  `source_usage`'s sources) is sorted explicitly by this module**, rather
  than trusting insertion order, so a record assembled by a different code
  path (or hand-built by a test) still renders the same way.

On a `refuse` disposition (§7.2) the answer states the refusal and its
reason and omits the claims section entirely (§7.10) -- every other section
(counter-position, coverage map, confidence, source usage) still renders
whatever the record carries, since none of those fields is itself claims.

Out of scope (issue #261's own "do NOT build" list): computing the
counter-position/coverage_map/confidence/source_usage CONTENT (this module
only presents what `analysis-validators`/`compute_source_usage` already
computed), any venue/length/style adaptation (Phase D), and any output
format other than markdown.
"""

from __future__ import annotations

import json
from typing import Any

# Imported as a module, not by-name (mirrors `axial.vault`'s own
# `SOURCE_META_DIR` resolution): `axial.conftest`'s autouse isolation
# fixture monkeypatches `axial.intake.SOURCE_META_DIR` per test, and a
# `from axial.intake import SOURCE_META_DIR` binding here would capture the
# real, un-isolated path at import time instead.
from axial import intake as _intake
from axial.validators.coverage import NOT_MEASURED_BAND, confidence_ceiling_for_claim

# The §7.4 claim-kind marker vocabulary this module renders -- stable and
# documented, per the plan's own inner-loop rule ("distinguishable in the
# output by a stable, documented marker").
_KIND_MARKERS = {"a": "(a)", "b": "(b)", "c": "(c)"}


def _render_header(record: dict[str, Any]) -> list[str]:
    brief = record.get("brief") or {}
    interrogation = record.get("interrogation") or {}
    lines = [
        f"# Analysis answer: {record.get('brief_id', '')}",
        "",
        f"**Case:** {brief.get('case', '')}",
        f"**Request:** {brief.get('request', '')}",
        f"**Lens:** {record.get('lens') or '(none)'}",
        f"**Disposition:** {interrogation.get('disposition', '')}",
    ]
    return lines


def _render_refusal(record: dict[str, Any]) -> list[str]:
    interrogation = record.get("interrogation") or {}
    refusal = interrogation.get("refusal") or {}
    reason = refusal.get("reason", "(no reason recorded)")
    return ["", "## Refusal", "", f"The corpus does not support this request: {reason}"]


def _render_grounds(grounds: list[dict[str, Any]]) -> str | None:
    if not grounds:
        return None
    refs = ", ".join(f"{g.get('ref_type')}:{g.get('ref_id')}" for g in grounds)
    return f"  grounds: {refs}"


def _render_confidence_for_claim(claim: dict[str, Any], coverage_map: dict[str, Any]) -> str:
    """One claim's `[confidence: ...]` tag (issue #550): the EFFECTIVE band
    (`confidence_ceiling_for_claim`), clamped down to the coverage of the
    names this claim's own grounds notes carry when the model's emitted band
    exceeds it. Nothing is silently rewritten -- the emitted band still
    appears alongside the ceiling whenever it was clamped, so a reader sees
    both what the model asked for and what the answer actually prints."""
    ceiling = confidence_ceiling_for_claim(claim, coverage_map)
    if not ceiling.clamped:
        return f"confidence: {ceiling.effective_band}"
    return (
        f"confidence: {ceiling.effective_band} (model emitted {ceiling.emitted!r}, "
        f"capped by this claim's own coverage ceiling {ceiling.ceiling!r})"
    )


def _render_claims(claims: list[dict[str, Any]], coverage_map: dict[str, Any]) -> list[str]:
    lines = ["", "## Claims", ""]
    if not claims:
        lines.append("(none)")
        return lines
    for claim in claims:
        kind = claim.get("kind")
        marker = _KIND_MARKERS.get(kind, f"({kind})")
        confidence_text = _render_confidence_for_claim(claim, coverage_map)
        lines.append(f"- {marker} {claim.get('text', '')} [{confidence_text}]")
        grounds_line = _render_grounds(claim.get("grounds") or [])
        if grounds_line is not None:
            lines.append(grounds_line)
    return lines


def _render_counter_position(counter_position: dict[str, Any]) -> list[str]:
    lines = ["", "## Counter-position", ""]
    if counter_position.get("failed"):
        # Issue #558: generation was attempted and raised. Rendered
        # distinctly from both legitimate outcomes below -- never as
        # "(none disclosed)", which would read as an uncontested brief with
        # nothing to say, and never as one-sided, which would misattribute a
        # bug to a finding about the corpus.
        reason = counter_position.get("failure_reason") or ""
        lines.append(f"**Counter-position generation FAILED:** {reason}")
    elif counter_position.get("present"):
        stance = counter_position.get("stance") or ""
        lines.append(f"**Stance:** {stance}")
        grounds_line = _render_grounds(counter_position.get("grounds") or [])
        lines.append(grounds_line if grounds_line is not None else "  grounds: (none)")
    elif counter_position.get("corpus_one_sided"):
        reason = counter_position.get("one_sided_reason") or ""
        lines.append(f"**Corpus is one-sided:** {reason}")
    else:
        lines.append("(none disclosed)")
    return lines


def _render_coverage_map(coverage_map: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["", "## Coverage map", ""]
    if not coverage_map:
        lines.append("(none -- no name both retrieved on and touched by a claim)")
        return lines
    for name in sorted(coverage_map):
        entry = coverage_map[name]
        lines.append(
            f"- {name}: corpus={entry.get('corpus_note_count')} "
            f"evidence={entry.get('evidence_note_count')} "
            f"band={entry.get('coverage_band')}"
        )
    return lines


def _render_confidence(confidence: dict[str, Any]) -> list[str]:
    lines = ["", "## Confidence", ""]
    band = confidence.get("overall_band")
    # `not_measured` (issue #584) is not a rung on the low/medium/high
    # ordinal -- rendered as a plain phrase so a reader does not parse it as
    # a fourth band on the same ladder, while the record's own field keeps
    # its underscore spelling for consumers that compare it verbatim.
    band_text = "not measured" if band == NOT_MEASURED_BAND else band
    lines.append(f"**Band:** {band_text}")
    lines.append(f"**Rationale:** {confidence.get('rationale')}")
    return lines


def _format_ratio(value: Any) -> str:
    """`value` at three decimal places, or the literal `null` (issue #584):
    `available_share` is `None` -- unknown, not a measured zero -- on a run
    that queried no name at all, and `f"{None:.3f}"` would raise rather than
    render."""
    return f"{value:.3f}" if isinstance(value, (int, float)) else "null"


def _render_source_usage(source_usage: dict[str, Any]) -> list[str]:
    lines = ["", "## Source usage", ""]
    sources = source_usage.get("sources") or []
    if not sources:
        lines.append("(none)")
        return lines
    for entry in sorted(sources, key=lambda s: s.get("source_id", "")):
        lines.append(
            f"- {entry.get('source_id')}: evidence_share="
            f"{_format_ratio(entry.get('evidence_share'))} available_share="
            f"{_format_ratio(entry.get('available_share'))} usage_ratio={entry.get('usage_ratio')}"
        )
    return lines


# ---------------------------------------------------------------------------
# The analyst-facing view (issue #535)
# ---------------------------------------------------------------------------
#
# `render_markdown` above is the §7.10 operator/audit rendering: claims keyed
# by `source_id`/`chunk_id`, ratios to three decimal places, a band with no
# plain-language gloss. `render_analyst_answer` is a second, additive view
# over the SAME two already-computed artifacts -- the persisted record and
# the §7.15 run report (`axial.answer.run_report.build_run_report`) -- for a
# reader who has not opened either JSON file and does not know what a
# `source_id` is. It reads every figure straight off `report` or `record`;
# it computes nothing a report field does not already state, so there is one
# set of numbers, never two that could disagree. Cost stays off this view
# entirely (never rendered here, in any form) -- it is an infrastructure
# fact for the operator (`format_run_report`'s own job), not a property of
# the answer.

_ANALYST_KIND_LABELS = {
    "a": "source-says",
    "b": "cross-source",
    "c": "analyst's judgment",
}


def _title_for_source(source_id: str, *, source_meta_dir: Any = None) -> str:
    """`source_id`'s bibliographic title, or an honest `untitled (<id>)`
    when no title was ever resolved -- never the id alone standing in for
    a title (issue #535's own acceptance). Mirrors the three-state
    contract `axial.paper.biblio._field` already applies to this same
    persisted record (a resolved `{value, provenance}`, the `unavailable`
    sentinel, or the `not_attempted` sentinel absent a read at all), rather
    than raising on a missing record the way `axial.vault.read_source_meta`
    does -- a write-path contract that is wrong for a read-only render: an
    answer that refuses to print because one cited source lacks metadata
    helps nobody."""
    meta_dir = source_meta_dir if source_meta_dir is not None else _intake.SOURCE_META_DIR
    path = _intake.source_meta_path(source_id, meta_dir)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    raw = record.get("title", _intake.NOT_ATTEMPTED) if isinstance(record, dict) else None
    title = raw.get("value") if isinstance(raw, dict) else raw
    if (
        isinstance(title, str)
        and title.strip()
        and title
        not in (
            _intake.UNAVAILABLE,
            _intake.NOT_ATTEMPTED,
        )
    ):
        return title
    return f"untitled ({source_id})"


def _render_analyst_header(record: dict[str, Any]) -> list[str]:
    brief = record.get("brief") or {}
    return [
        f"**Case:** {brief.get('case', '')}",
        f"**Question:** {brief.get('request', '')}",
    ]


def _render_analyst_claims(claims: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Answer", ""]
    if not claims:
        lines.append("(no claims)")
        return lines
    for claim in claims:
        label = _ANALYST_KIND_LABELS.get(claim.get("kind"), claim.get("kind") or "unlabeled")
        lines.append(f"- [{label}] {claim.get('text', '')}")
    return lines


def _render_books_drawn_on(quality: dict[str, Any], *, source_meta_dir: Any) -> list[str]:
    lines = ["", "## Which books it drew on", ""]
    shares = quality.get("per_source_share") or {}
    if not shares:
        lines.append("(none -- no source was cited)")
        return lines
    for source_id, share in sorted(shares.items(), key=lambda item: item[1], reverse=True):
        title = _title_for_source(source_id, source_meta_dir=source_meta_dir)
        lines.append(f"- {title}: {share:.0%} of the answer's citations")
    return lines


def _render_passages_read_and_used(
    operational: dict[str, Any], quality: dict[str, Any]
) -> list[str]:
    evidence = operational.get("evidence") or {}
    precision = quality.get("retrieval_precision") or {}
    assembled = evidence.get("assembled_count", 0)
    cited = precision.get("cited_note_count", 0)
    return [
        "",
        "## How much of the corpus it read",
        "",
        f"Read {assembled} passage(s) from the corpus; this answer actually cites {cited} of them.",
    ]


_ANALYST_BAND_WORDS = {"thin": "thin", "moderate": "moderate", "dense": "dense"}


def _render_name_coverage(coverage_map: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["", "## How well the corpus covers what it discusses", ""]
    if not coverage_map:
        lines.append("(no name was both retrieved on and touched by a claim)")
        return lines
    for name in sorted(coverage_map):
        entry = coverage_map[name]
        band_word = _ANALYST_BAND_WORDS.get(
            entry.get("coverage_band"), entry.get("coverage_band") or "unknown"
        )
        lines.append(
            f"- {name}: {band_word} coverage ({entry.get('evidence_note_count')} of "
            f"{entry.get('corpus_note_count')} corpus passage(s) on this name were used)"
        )
    return lines


def _render_analyst_confidence(confidence: dict[str, Any]) -> list[str]:
    # Reuses the same section `render_markdown` already renders -- band and
    # rationale are already plain language, and there is no second way to
    # compute either.
    return _render_confidence(confidence)


def _render_cross_book_headline(quality: dict[str, Any]) -> list[str]:
    lines = ["", "## How much of this is genuinely cross-book", ""]
    cross = quality.get("cross_source_rate") or {}
    value = cross.get("value")
    if value is None:
        reason = cross.get("reason", "not measured")
        lines.append(f"Not measured: {reason}")
        return lines
    lines.append(
        f"{value:.0%} of the claims that combine two or more sources actually did "
        f"({cross.get('numerator')} of {cross.get('denominator')}) -- the number that says "
        "whether this answer did the thing this product exists to do."
    )
    return lines


def render_analyst_answer(
    record: dict[str, Any],
    report: dict[str, Any],
    *,
    source_meta_dir: Any = None,
) -> str:
    """The analyst-facing rendering of one `axial ask` turn (issue #535):
    the answer printed where it was asked, then what stands behind it in
    plain language -- which books it drew on (by title), how many passages
    it read versus actually cites, how well the corpus covers each name it
    discusses, how confident it is and why, and the cross-book rate that
    says whether the answer did the thing this product exists to do.

    `record` is the persisted §7.3 record; `report` is the §7.15 run report
    built from it (`axial.answer.run_report.build_run_report`) -- every
    figure below is read from one of the two, never recomputed, so there is
    one set of numbers, not two that could disagree. Cost never appears
    here in any form (it is `format_run_report`'s own job, for the
    operator). `source_meta_dir` resolves each cited source to its title; a
    source with no metadata record, or whose title was never resolved, is
    named honestly as untitled rather than falling back to its id alone."""
    interrogation = record.get("interrogation") or {}
    disposition = interrogation.get("disposition")
    operational = report.get("operational") or {}
    quality = report.get("response_quality") or {}

    lines = _render_analyst_header(record)
    if disposition == "refuse":
        lines += _render_refusal(record)
        return "\n".join(lines) + "\n"

    lines += _render_analyst_claims(record.get("claims") or [])
    lines += _render_books_drawn_on(quality, source_meta_dir=source_meta_dir)
    lines += _render_passages_read_and_used(operational, quality)
    lines += _render_name_coverage(record.get("coverage_map") or {})
    lines += _render_analyst_confidence(record.get("confidence") or {})
    lines += _render_cross_book_headline(quality)
    return "\n".join(lines) + "\n"


def render_markdown(record: dict[str, Any]) -> str:
    """Render the §7.10 human-readable markdown answer from `record` (the
    §7.3 shape). Pure: reads only `record`, calls no model, touches no
    vault, no clock. Deterministic: the same record always renders the same
    string, byte for byte."""
    interrogation = record.get("interrogation") or {}
    disposition = interrogation.get("disposition")

    lines = _render_header(record)
    if disposition == "refuse":
        lines += _render_refusal(record)
    else:
        lines += _render_claims(record.get("claims") or [], record.get("coverage_map") or {})
    lines += _render_counter_position(record.get("counter_position") or {})
    lines += _render_coverage_map(record.get("coverage_map") or {})
    lines += _render_confidence(record.get("confidence") or {})
    lines += _render_source_usage(record.get("source_usage") or {})

    return "\n".join(lines) + "\n"
