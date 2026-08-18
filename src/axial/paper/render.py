"""Stage 5: rendering the paper (specs/PHASE-C.md §7.10, §8 P0-7).

Plain markdown, rendered deterministically from the record: the same record
renders the same markdown, byte for byte. No model call, no clock, no
randomness, nothing read from disk.

Contents in order: title, thesis statement, the abstract (§7.18, issue #787),
the plan's sections in plan order
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

import re
from typing import Any

from axial.paper.biblio import BIB_FIELDS, format_field

# Rendered beside a band so it is never shown alone (§7.10).
_BAND_NOTE = "band shown with the coverage counts that justify it"


def paper_title(record: dict[str, Any]) -> str:
    """The rendered `#` title (§7.10). Precedence, highest first: a human-
    supplied `title` in the paper brief (an explicit override always wins),
    the §7.16 shape check's own title of the finished paper, the plan's
    thesis statement, the brief's raw thesis, and finally a placeholder. The
    shape check's title is `None` on any record written before issue #717 or
    when the judge's response carried no usable one, so this falls straight
    through to the thesis on old records -- no record needs to be
    re-rendered for this to stay deterministic."""
    brief = record.get("paper_brief") or {}
    shape = record.get("shape") or {}
    plan = record.get("plan") or {}
    return str(
        brief.get("title")
        or shape.get("title")
        or plan.get("thesis_statement")
        or brief.get("thesis")
        or "Untitled paper"
    )


def abstract_lines(record: dict[str, Any]) -> list[str]:
    """The §7.18 abstract block, or nothing at all.

    Emitted VERBATIM, never through `axial.paper.reader.replace_markers`: the
    abstract is the one block of the paper the prompt forbids markers and
    citations in, and a stray `[pc-001]` that slipped through must stay
    visible rather than be silently promoted to a citation. Absent, null or
    blank yields no lines, so a record written before this issue -- which is
    every record in `data/papers/` -- renders exactly as it did before it.

    Both renders share this function because both render the same record and
    the abstract is not audit material; the shape band and the citation table
    are what the audit render adds."""
    abstract = record.get("abstract")
    if not isinstance(abstract, str) or not abstract.strip():
        return []
    return ["## Abstract", "", abstract.strip(), ""]


def plan_sections(record: dict[str, Any]) -> list[dict[str, Any]]:
    plan = record.get("plan") or {}
    return [section for section in (plan.get("sections") or []) if isinstance(section, dict)]


_LEADING_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s+)(.*\S)\s*\n?")


def drop_restated_heading(prose: str, heading: Any) -> str:
    """Strip a leading markdown heading line from `prose` when it merely
    restates the section's own heading the renderer is about to emit.

    The drafting model sometimes opens a section's prose with its own
    `## <heading>` line, duplicating the one `render_paper` prepends. Only a
    heading that normalises (whitespace, case) to the same text as the
    section's own heading is stripped; a prose that opens with a *different*
    heading is left untouched.
    """
    match = _LEADING_HEADING_RE.match(prose)
    if not match:
        return prose
    found = " ".join(match.group(1).split()).casefold()
    expected = " ".join(str(heading or "").split()).casefold()
    if not expected or found != expected:
        return prose
    rest = prose[match.end() :]
    return rest.lstrip("\n")


def prose_by_section(record: dict[str, Any]) -> dict[str, str]:
    return {
        str(entry.get("section_id")): str(entry.get("prose") or "")
        for entry in (record.get("drafts") or [])
        if isinstance(entry, dict)
    }


def counter_position_lines(record: dict[str, Any]) -> list[str]:
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
    without the counts behind it (§7.10). `repetition` (issue #700) is the
    mechanical cross-section verbatim-overlap figure -- rendered whenever
    present, never gating."""
    shape = record.get("shape")
    if not isinstance(shape, dict):
        return []

    lines = [
        "## Shape check",
        "",
        f"**Band:** {shape.get('band')}.",
        "",
    ]
    repetition = shape.get("repetition")
    if isinstance(repetition, dict):
        lines.append(f"**Cross-section repetition:** {repetition.get('fraction'):.2%}.")
        lines.append("")
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
    prose = prose_by_section(record)

    lines = [f"# {paper_title(record)}", ""]

    thesis_statement = plan.get("thesis_statement")
    if thesis_statement:
        lines.extend([str(thesis_statement), ""])

    lines.extend(abstract_lines(record))

    for section in plan_sections(record):
        heading = section.get("heading")
        lines.append(f"## {heading}")
        lines.append("")
        section_prose = prose.get(str(section.get("section_id")), "")
        lines.append(drop_restated_heading(section_prose, heading))
        lines.append("")

    lines.extend(counter_position_lines(record))
    lines.extend(_render_coverage(record))
    lines.extend(_render_shape(record))
    lines.extend(_render_citation_table(record))
    lines.extend(_render_bibliography(record))

    return "\n".join(lines).rstrip() + "\n"
