"""The reader-facing paper (issue #783, folding in #786).

`axial.paper.render.render_paper` renders the paper for an operator: the
prose, then a citation table keyed by chunk id, a coverage table, a shape
band and a bibliography carrying its own provenance tags. Every one of
those is an audit artifact, and the module's own docstring already names
the failure -- *"a reader who asked a question should never meet
`usage_ratio=22.954545454545453` under the answer"*. This module is the
other half of that split: what a reader gets.

**What it emits, and nothing else:** the title, the thesis statement, the
planned sections in plan order with their prose, the counter-position, and
a bibliography written the way a bibliography is written. No chunk id, no
coverage band, no shape check, no provenance tag.

**In-text markers become citations.** The drafter writes `[pc-001]` after
the sentence a claim supports; that is the paper's own claim id, as much a
database key on a page as a chunk id is. Each run of markers is replaced by
one parenthetical naming the sources behind it, APA-shaped -- `(Vignal,
2021; Bayat, 2017)`. A marker whose claim id is not in the record is left
exactly as it is: a visible unresolved reference beats a silently deleted
one.

The parenthetical names books, not passages (`axial.cite`'s short form),
so a claim resting on nine chunks of two books cites two. Nothing is
dropped from the record: the audit render still carries every ground.

Purity is the same contract `render_paper` holds: this reads only the
record and calls no model, no clock, no disk. The `citation` blocks it
formats are resolved into the record beforehand by
`axial.query.citations.resolve_record_citations`, exactly as the served
record already resolves them for the web client -- a record rendered
without that step still renders, citing whatever the grounds carry.
"""

from __future__ import annotations

import re
from typing import Any

from axial.cite import SHORT, format_bibliography_entry, format_citation
from axial.paper.render import (
    counter_position_lines,
    drop_restated_heading,
    paper_title,
    plan_sections,
    prose_by_section,
)

# One `[pc-001]` marker, and a run of them written back to back (the
# drafter emits `[pc-001][pc-002][pc-004]` for a sentence resting on three
# claims). Matched as a run so the run becomes ONE parenthetical.
_MARKER_RUN_RE = re.compile(r"(?:\[(?:pc-[0-9A-Za-z_-]+)\])+")
_MARKER_RE = re.compile(r"\[(pc-[0-9A-Za-z_-]+)\]")


def _citation_for_claim(claim: dict[str, Any]) -> str | None:
    """One claim rendered as an in-text citation: each source it rests on,
    named once, in the order its grounds appear. `None` when no ground
    resolved a citation at all -- the caller keeps the raw marker rather
    than printing an empty parenthesis.

    A claim resting on nine passages cites the books behind them, not the
    passages: `axial.cite`'s short form is author and year, so five chunks
    of one book collapse to one `Vignal 2021`. The audit render still
    carries all nine grounds."""
    rendered: list[str] = []
    for ground in claim.get("grounds") or []:
        if not isinstance(ground, dict):
            continue
        text = format_citation(ground.get("citation"), form=SHORT)
        if text is not None and text not in rendered:
            rendered.append(text)
    return "; ".join(rendered) or None


# What a claim with no grounds cites. A (c) claim runs past the books by
# definition (§7.4) -- it has nothing to cite and that is the finding, not a
# gap -- and the phrase is the web client's own legend text for the same
# kind, so the two surfaces say the same thing about the same claim.
_UNGROUNDED = {"c": "runs past the books"}
_UNGROUNDED_DEFAULT = "no supporting passage"


def _citations_by_claim_id(record: dict[str, Any]) -> dict[str, str]:
    citations: dict[str, str] = {}
    for claim in record.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("paper_claim_id") or "")
        if not claim_id:
            continue
        text = _citation_for_claim(claim)
        if text is not None:
            citations[claim_id] = text
        elif not (claim.get("grounds") or []):
            # No grounds at all: a state the record MEANT, not a citation
            # that failed to resolve. Left as a raw `[pc-029]` marker it
            # would read as a broken reference; the raw marker is reserved
            # for a claim id the record does not carry.
            citations[claim_id] = _UNGROUNDED.get(claim.get("kind"), _UNGROUNDED_DEFAULT)
    return citations


def replace_markers(prose: str, citations: dict[str, str]) -> str:
    """Every run of `[pc-...]` markers in `prose` replaced by one
    parenthetical citation. A run whose claim ids all failed to resolve is
    left untouched, markers and all."""

    def _replace(match: re.Match[str]) -> str:
        rendered: list[str] = []
        unresolved: list[str] = []
        for claim_id in _MARKER_RE.findall(match.group(0)):
            text = citations.get(claim_id)
            if text is None:
                unresolved.append(f"[{claim_id}]")
                continue
            for part in text.split("; "):
                if part not in rendered:
                    rendered.append(part)
        if not rendered:
            return match.group(0)
        return f"({'; '.join(rendered)})" + "".join(unresolved)

    return _MARKER_RUN_RE.sub(_replace, prose)


def _bibliography_lines(record: dict[str, Any]) -> list[str]:
    entries = record.get("bibliography") or []
    if not entries:
        return []
    lines = ["## Bibliography", ""]
    for entry in entries:
        lines.append(f"- {format_bibliography_entry(entry)}")
    lines.append("")
    return lines


def render_reader_paper(record: dict[str, Any]) -> str:
    """The paper as a reader gets it. Deterministic given the record alone,
    exactly like `render_paper`: the same record renders the same markdown,
    byte for byte."""
    plan = record.get("plan") or {}
    prose = prose_by_section(record)
    citations = _citations_by_claim_id(record)

    title = paper_title(record)
    lines = [f"# {title}", ""]

    # `paper_title` falls back to the plan's own `thesis_statement` when the
    # brief names no title (§7.1), and a paper drafted from an ask never
    # names one -- so without this the H1 and the first body line are the
    # identical sentence, on every answer an analyst reads (issue #784).
    thesis_statement = plan.get("thesis_statement")
    if thesis_statement and str(thesis_statement) != title:
        lines.extend([str(thesis_statement), ""])

    for section in plan_sections(record):
        heading = section.get("heading")
        lines.append(f"## {heading}")
        lines.append("")
        section_prose = prose.get(str(section.get("section_id")), "")
        lines.append(replace_markers(drop_restated_heading(section_prose, heading), citations))
        lines.append("")

    lines.extend(counter_position_lines(record))
    lines.extend(_bibliography_lines(record))

    return "\n".join(lines).rstrip() + "\n"
