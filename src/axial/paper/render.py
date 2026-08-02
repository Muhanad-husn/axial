"""Stage 5: rendering the paper (specs/PHASE-C.md §7.10, §8 P0-7).

Plain markdown, rendered deterministically from the record: the same record
renders the same markdown, byte for byte. No model call, no clock, no
randomness, nothing read from disk.

Contents in order: title, thesis statement, the plan's sections in plan order
with their prose and in-text markers, the counter-position (or the one-sided
disclosure), the confidence and coverage disclosure, the shape-check block
(§7.16, issue #578 -- the band and, below `strong`, the named defects), the
citation table, and the bibliography.

Two rules carried from the layer beneath, restated because they bind on this
artifact.

- **Every confidence band renders next to the counts that justify it.** A band
  rendered bare is a rendering failure -- it is the manufactured-precision
  failure in another costume.
- **Claim kind is legible.** Every citation-table entry carries its claim's
  kind, so a reader can see which claims a source made and which the tool
  made. In the prose the seam is carried by voice, not by marker clutter.

What this deliberately does NOT render is the engine's own telemetry. Source
usage ratios, evidence shares and retrieval counts belong to `examine`, where
an operator wants them; a reader who asked a question should never meet
`usage_ratio=22.954545454545453` under the answer. That is the whole
complaint the 2026-08-01 ruling was filed on (§0).

Venue, length and house style are Phase D (§3).
"""

from __future__ import annotations

from typing import Any

from axial.paper.biblio import BIB_FIELDS, format_field

# Rendered beside a band so it is never shown alone (§7.10).
_BAND_NOTE = "band shown with the coverage counts that justify it"


def _title(record: dict[str, Any]) -> str:
    brief = record.get("paper_brief") or {}
    return str(brief.get("title") or brief.get("thesis") or "Untitled paper")


def _sections(record: dict[str, Any]) -> list[dict[str, Any]]:
    plan = record.get("plan") or {}
    return [section for section in (plan.get("sections") or []) if isinstance(section, dict)]


def _prose_by_section(record: dict[str, Any]) -> dict[str, str]:
    return {
        str(entry.get("section_id")): str(entry.get("prose") or "")
        for entry in (record.get("drafts") or [])
        if isinstance(entry, dict)
    }


def _render_counter_position(record: dict[str, Any]) -> list[str]:
    """The counter-position, the one-sided disclosure, or the failure.

    Three states, never two (§7.3, PR #558), and they render in two different
    places. When a counter-position is **present** it has a planned section
    with drafted prose, and that section renders in plan order like any other;
    emitting a second block from `stance` here would replace the drafter's
    argued prose with a one-line summary of it. The other two states have no
    section to render -- §7.2's guard only permits a plan without a
    counter-position section when the corpus is disclosed one-sided -- so they
    render here or nowhere.

    A failed section renders as a failure in plain words: it is a run that
    died, and letting it read as "the corpus has one side" would turn a bug
    into a finding about the world."""
    counter_position = record.get("counter_position")
    if not isinstance(counter_position, dict):
        return []
    if counter_position.get("present") and not counter_position.get("failed"):
        return []

    lines = ["## The opposing position", ""]
    if counter_position.get("failed"):
        reason = counter_position.get("failure_reason") or "no reason was recorded"
        lines.append(
            f"**This section failed to generate.** {reason}. This is a failure of "
            f"this run, and says nothing about whether the corpus holds an opposing "
            f"position."
        )
    elif counter_position.get("corpus_one_sided") is True:
        reason = counter_position.get("one_sided_reason") or "no reason was recorded"
        lines.append(f"**The source analyses report the corpus is one-sided here.** {reason}")
    else:
        lines.append("No opposing position was recorded.")
    lines.append("")
    return lines


def _render_coverage(record: dict[str, Any]) -> list[str]:
    """Confidence next to the counts behind it (§7.10), and the coverage map
    unioned from the named source records (§7.11)."""
    confidence = record.get("confidence") or {}
    coverage_map = record.get("coverage_map") or {}

    lines = [
        "## Confidence and coverage",
        "",
        f"**Overall confidence:** {confidence.get('overall_band')} ({_BAND_NOTE}).",
        "",
        str(confidence.get("rationale") or ""),
        "",
    ]
    if coverage_map:
        lines.extend(
            [
                "| name | corpus notes | cited claims | coverage |",
                "|---|---:|---:|---|",
            ]
        )
        for name, entry in sorted(coverage_map.items()):
            corpus = entry.get("corpus_note_count")
            corpus_text = "not in the index" if corpus is None else str(corpus)
            lines.append(
                f"| {name} | {corpus_text} | {entry.get('cited_claim_count')} "
                f"| {entry.get('coverage_band')} |"
            )
        lines.append("")
    return lines


def _render_shape(record: dict[str, Any]) -> list[str]:
    """The §7.16 shape-check block (issue #578): the band the check returned
    and, whenever it is not `strong`, the named defects that justify it. This
    check reports and never blocks -- a `weak` band still renders here, next
    to what it says is wrong, exactly like a confidence band never renders
    without the counts behind it (§7.10)."""
    shape = record.get("shape")
    if not isinstance(shape, dict):
        return []

    lines = [
        "## Shape check",
        "",
        f"**Band:** {shape.get('band')}.",
        "",
    ]
    defects = shape.get("defects") or []
    if defects:
        lines.append("| section | defect |")
        lines.append("|---|---|")
        for defect in defects:
            lines.append(f"| {defect.get('section_id')} | {defect.get('note')} |")
        lines.append("")
    return lines


def _bib_label(entry: dict[str, Any]) -> str:
    author = (entry.get("author") or {}).get("value")
    date = (entry.get("date") or {}).get("value")
    if author and date:
        return f"{author} ({date})"
    if author:
        return str(author)
    return str(entry.get("source_id"))


def _render_citation_table(record: dict[str, Any]) -> list[str]:
    """The chain made readable: claim id, kind, band, grounds, source (§7.5).

    This is what makes `claim_id -> chunk_id -> source` visible on the page
    rather than merely computable from the record."""
    claims = record.get("claims") or []
    if not claims:
        return []

    by_source = {
        entry.get("source_id"): _bib_label(entry)
        for entry in (record.get("bibliography") or [])
        if isinstance(entry, dict)
    }

    lines = [
        "## Citations",
        "",
        "| id | kind | confidence | grounds | source |",
        "|---|---|---|---|---|",
    ]
    for claim in claims:
        grounds = claim.get("grounds") or []
        ground_ids = ", ".join(str(ground.get("ref_id")) for ground in grounds) or "-"
        sources = sorted(
            {by_source.get(source_id, source_id) for source_id in (claim.get("source_ids") or [])}
        )
        origin = claim.get("origin")
        kind = claim.get("kind")
        if origin:
            kind_text = f"{kind} (carried)"
        elif kind == "c":
            kind_text = f"{kind} (this paper's verdict)"
        else:
            kind_text = f"{kind} (this paper's inference)"
        lines.append(
            f"| {claim.get('paper_claim_id')} | {kind_text} | "
            f"{claim.get('confidence')} | {ground_ids} | {'; '.join(sources) or '-'} |"
        )
    lines.append("")
    return lines


def _render_bibliography(record: dict[str, Any]) -> list[str]:
    entries = record.get("bibliography") or []
    if not entries:
        return []
    lines = ["## Bibliography", ""]
    for entry in entries:
        fields = "; ".join(
            f"{field}: {format_field(entry.get(field) or {})}" for field in BIB_FIELDS
        )
        lines.append(f"- **{entry.get('source_id')}** — {fields}")
    lines.append("")
    return lines


def render_paper(record: dict[str, Any]) -> str:
    """The §7.10 rendered paper. Deterministic given the record alone."""
    plan = record.get("plan") or {}
    prose = _prose_by_section(record)

    lines = [f"# {_title(record)}", ""]

    thesis_statement = plan.get("thesis_statement")
    if thesis_statement:
        lines.extend([str(thesis_statement), ""])

    for section in _sections(record):
        lines.append(f"## {section.get('heading')}")
        lines.append("")
        lines.append(prose.get(str(section.get("section_id")), ""))
        lines.append("")

    lines.extend(_render_counter_position(record))
    lines.extend(_render_coverage(record))
    lines.extend(_render_shape(record))
    lines.extend(_render_citation_table(record))
    lines.extend(_render_bibliography(record))

    return "\n".join(lines).rstrip() + "\n"
