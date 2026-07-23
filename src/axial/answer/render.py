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
- **Every other multi-entry section (`coverage_map`'s polities,
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

from typing import Any

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


def _render_claims(claims: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Claims", ""]
    if not claims:
        lines.append("(none)")
        return lines
    for claim in claims:
        kind = claim.get("kind")
        marker = _KIND_MARKERS.get(kind, f"({kind})")
        lines.append(f"- {marker} {claim.get('text', '')} [confidence: {claim.get('confidence')}]")
        grounds_line = _render_grounds(claim.get("grounds") or [])
        if grounds_line is not None:
            lines.append(grounds_line)
    return lines


def _render_counter_position(counter_position: dict[str, Any]) -> list[str]:
    lines = ["", "## Counter-position", ""]
    if counter_position.get("present"):
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
        lines.append("(none -- no polity touched by any claim)")
        return lines
    for polity in sorted(coverage_map):
        entry = coverage_map[polity]
        lines.append(
            f"- {polity}: corpus={entry.get('corpus_chunk_count')} "
            f"evidence={entry.get('evidence_chunk_count')} "
            f"band={entry.get('coverage_band')}"
        )
    return lines


def _render_confidence(confidence: dict[str, Any]) -> list[str]:
    lines = ["", "## Confidence", ""]
    lines.append(f"**Band:** {confidence.get('overall_band')}")
    lines.append(f"**Rationale:** {confidence.get('rationale')}")
    return lines


def _render_source_usage(source_usage: dict[str, Any]) -> list[str]:
    lines = ["", "## Source usage", ""]
    sources = source_usage.get("sources") or []
    if not sources:
        lines.append("(none)")
        return lines
    for entry in sorted(sources, key=lambda s: s.get("source_id", "")):
        lines.append(
            f"- {entry.get('source_id')}: evidence_share="
            f"{entry.get('evidence_share'):.3f} available_share="
            f"{entry.get('available_share'):.3f} usage_ratio={entry.get('usage_ratio')}"
        )
    return lines


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
        lines += _render_claims(record.get("claims") or [])
    lines += _render_counter_position(record.get("counter_position") or {})
    lines += _render_coverage_map(record.get("coverage_map") or {})
    lines += _render_confidence(record.get("confidence") or {})
    lines += _render_source_usage(record.get("source_usage") or {})

    return "\n".join(lines) + "\n"
