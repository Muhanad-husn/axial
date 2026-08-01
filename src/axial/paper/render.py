"""Stage 5: rendering the paper (specs/PHASE-C.md §7.10, §8 P0-7).

Plain markdown, rendered deterministically from the record: the same record
renders the same markdown, byte for byte. No model call, no clock, no
randomness, nothing read from disk.

Contents in order: title, thesis statement, the plan's sections in plan order
with their prose and in-text markers, the counter-position (or the one-sided
disclosure), the exact-match opposition check (issue #570), the confidence
and coverage disclosure, the citation table, and the bibliography.

**The opposition check is a reader disclosure, not engine telemetry** (the
"does NOT render" rule below). #570 rule 3 requires both the record and the
rendered paper to be able to say "gap found: 12 notes; 9 repaired" -- never a
clean zero presented as though retrieval got it right the first time -- and
requires the scope note to travel with the number: the check only counts
opposition whose target text exactly matches a name page, which is measured
at 4.7% of the corpus's recorded `arguing_against` targets (2026-08-01), so
the count is a floor, not the opposition that exists.

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
    as a UNION of two labelled scopes (§7.11's founder amendment, issue
    #570): "carried" from the named source records, unchanged; "earned" by
    the opposition-repair pass's own retrieval, computed natively over its
    own trajectory. The two are never merged into one unlabelled row -- a
    reader must be able to tell which coverage the paper inherited and which
    it earned itself."""
    confidence = record.get("confidence") or {}
    carried = record.get("coverage_map") or {}
    earned = record.get("coverage_map_earned") or {}

    lines = [
        "## Confidence and coverage",
        "",
        f"**Overall confidence:** {confidence.get('overall_band')} ({_BAND_NOTE}).",
        "",
        str(confidence.get("rationale") or ""),
        "",
    ]
    if carried or earned:
        lines.extend(
            [
                "| name | scope | corpus notes | cited claims | coverage |",
                "|---|---|---:|---:|---|",
            ]
        )
        for scope, coverage_map in (("carried", carried), ("earned", earned)):
            for name, entry in sorted(coverage_map.items()):
                corpus = entry.get("corpus_note_count")
                corpus_text = "not in the index" if corpus is None else str(corpus)
                lines.append(
                    f"| {name} | {scope} | {corpus_text} | {entry.get('cited_claim_count')} "
                    f"| {entry.get('coverage_band')} |"
                )
        lines.append("")
    return lines


def _render_opposition_gap(record: dict[str, Any]) -> list[str]:
    """The exact-match opposition check this paper ran before drafting
    (issue #570): what it found unread, what it repaired, and the scope note
    -- carrying the measured 4.7% join recall -- that keeps a zero from being
    misread as "the corpus has no counter-argument" and keeps the whole
    count from being misread as "the opposition that exists" rather than a
    floor. Renders nothing when the check never ran (an older record, or a
    hand-built fixture)."""
    gap = record.get("exact_match_opposition_gap")
    if not isinstance(gap, dict):
        return []

    names_checked = gap.get("names_checked") or []
    lines = [
        "## Opposition check (exact-match join)",
        "",
        f"*{gap.get('scope_note') or ''}*",
        "",
        f"Checked {len(names_checked)} name(s) this paper's claims touch for opposition "
        f"none of the source analyses had already read. Found **{gap.get('gap_found', 0)}** "
        f"such note(s); repaired **{gap.get('gap_repaired', 0)}** into new grounded claims "
        f"({gap.get('skipped_abstentions', 0)} skipped for carrying no stated claim). "
        f"Restricted to what this paper actually cites: **{gap.get('gap_found_cited_scope', 0)}** "
        f"of the notes found, **{gap.get('gap_repaired_cited', 0)}** of the repaired claims.",
        "",
    ]
    by_name = gap.get("by_name") or {}
    if by_name:
        lines.extend(
            [
                "| name | gap found | gap repaired | already read | total edges |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for name, counts in sorted(by_name.items()):
            lines.append(
                f"| {name} | {counts.get('gap_found', 0)} | {counts.get('gap_repaired', 0)} "
                f"| {counts.get('already_read', 0)} | {counts.get('total_opposition_edges', 0)} |"
            )
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
        kind_text = f"{kind} (carried)" if origin else f"{kind} (this paper's)"
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
    lines.extend(_render_opposition_gap(record))
    lines.extend(_render_coverage(record))
    lines.extend(_render_citation_table(record))
    lines.extend(_render_bibliography(record))

    return "\n".join(lines).rstrip() + "\n"
