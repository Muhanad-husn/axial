"""The reader-facing answer (issue #783).

`axial.answer.render.render_markdown` is the audit rendering -- claims keyed
by chunk id, usage ratios to three decimal places, a coverage map -- and it
stays exactly as it is: the sealed peer-review packet and
`judge_instant_dismissal` both read it. This module renders the same record
for the person who asked the question.

**What it emits:** the case and the question, the answer's claims each carrying the
evidence marker that says how far it runs past the books, a citation naming
the book and chapter behind it, the opposing position, and a bibliography of
the sources actually cited. No chunk id, no ratio, no coverage table, no
cost, no model name.

**The markers are the honesty layer, not decoration.** `stated`,
`concluded` and `runs past the books` are the same three words the web
client prints (`web/src/lib/paper.ts`'s own legend), and they are the only
thing standing between a reader and a claim the tool made being read as a
claim a source made.

An `ask` answer is still a list of claims here, because that is all the ask
path produces today; issue #784 is what turns it into an argued essay. This
module's job is that the list arrives without the telemetry.

Purity: reads only `record`. Citations are resolved into it beforehand by
`axial.query.citations.resolve_record_citations` (the same step the served
record already runs), and a record rendered without that step still renders
-- citing the raw pointer, visibly.
"""

from __future__ import annotations

from typing import Any

from axial.cite import SHORT, citation_summary, clean_author

# The same three words the web client's legend prints for the §7.4 claim
# kinds -- one vocabulary, both surfaces.
_MARKERS = {
    "a": "stated",
    "b": "concluded",
    "c": "runs past the books",
}


def _header_lines(record: dict[str, Any]) -> list[str]:
    """The document's own opening: the case as the title, the question as a
    line under it. The question is NOT the title -- a real request runs to a
    paragraph (`data/analyses/080d9e472fc56a34.json`'s is 300 characters),
    and a 300-character `#` heading is not a title. Nothing is truncated to
    make one."""
    brief = record.get("brief") or {}
    case = str(brief.get("case") or "").strip()
    request = str(brief.get("request") or "").strip()
    title = case or request or str(record.get("brief_id") or "Answer")
    lines = [f"# {title}", ""]
    if request and title != request:
        lines.extend([f"**The question:** {request}", ""])
    return lines


def _refusal_lines(record: dict[str, Any]) -> list[str]:
    interrogation = record.get("interrogation") or {}
    refusal = interrogation.get("refusal") or {}
    reason = refusal.get("reason") or "no reason was recorded"
    return [
        "## No answer from this corpus",
        "",
        f"The corpus does not support this request: {reason}",
        "",
    ]


def _quote_lines(grounds: Any) -> list[str]:
    """Every quoted passage the grounds carry, as a blockquote under the
    claim it supports (issue #732, kept through the #783 split). A record
    resolved in `locator` mode carries none, so this renders nothing there
    -- by construction, not by a branch on the mode."""
    if not isinstance(grounds, list):
        return []
    lines: list[str] = []
    for ground in grounds:
        if not isinstance(ground, dict):
            continue
        citation = ground.get("citation")
        quote = citation.get("quote") if isinstance(citation, dict) else None
        if not isinstance(quote, str) or not quote:
            continue
        lines.append("")
        lines.append(f"  > {quote}")
    return lines


def _claim_lines(claims: list[dict[str, Any]]) -> list[str]:
    lines = ["## Answer", ""]
    if not claims:
        lines.extend(["(no claims)", ""])
        return lines
    for claim in claims:
        kind = claim.get("kind")
        marker = _MARKERS.get(kind, str(kind or "unlabeled"))
        text = str(claim.get("text") or "")
        grounds = claim.get("grounds")
        citation = citation_summary(grounds, form=SHORT)
        lines.append(f"- **[{marker}]** {text} ({citation})")
        lines.extend(_quote_lines(grounds))
    lines.append("")
    return lines


def _counter_position_lines(counter_position: dict[str, Any]) -> list[str]:
    lines = ["## The opposing position", ""]
    if counter_position.get("failed"):
        reason = counter_position.get("failure_reason") or "no reason was recorded"
        lines.append(
            f"**This section failed to generate.** {reason}. This is a failure of this "
            f"run, and says nothing about whether the corpus holds an opposing position."
        )
    elif counter_position.get("present"):
        stance = str(counter_position.get("stance") or "")
        grounds = counter_position.get("grounds")
        citation = citation_summary(grounds, form=SHORT)
        lines.append(f"{stance} ({citation})")
        lines.extend(_quote_lines(grounds))
    elif counter_position.get("corpus_one_sided"):
        reason = counter_position.get("one_sided_reason") or "no reason was recorded"
        lines.append(f"**The corpus is one-sided here.** {reason}")
    else:
        lines.append("No opposing position was recorded.")
    lines.append("")
    return lines


def _bibliography_lines(record: dict[str, Any]) -> list[str]:
    """Every source the answer actually cites, read off the citations
    already resolved into the grounds -- never the source id parsed out of a
    chunk id, and never a source that resolved no metadata at all, which
    would print as a bare id in a bibliography."""
    entries: dict[str, str] = {}
    grounds_lists = [claim.get("grounds") for claim in (record.get("claims") or [])]
    counter_position = record.get("counter_position")
    if isinstance(counter_position, dict):
        grounds_lists.append(counter_position.get("grounds"))

    for grounds in grounds_lists:
        if not isinstance(grounds, list):
            continue
        for ground in grounds:
            if not isinstance(ground, dict):
                continue
            citation = ground.get("citation")
            if not isinstance(citation, dict):
                continue
            source_id = str(citation.get("source_id") or "")
            if not source_id or source_id in entries:
                continue
            author = clean_author(citation.get("author"))
            title = str(citation.get("title") or "").strip()
            date = str(citation.get("date") or "").strip()
            head = ". ".join(part for part in (author, title) if part)
            if not head:
                continue
            entries[source_id] = f"{head}. {date}." if date else f"{head}."

    if not entries:
        return []
    lines = ["## Bibliography", ""]
    lines.extend(f"- {entries[source_id]}" for source_id in sorted(entries))
    lines.append("")
    return lines


def render_reader_answer(record: dict[str, Any]) -> str:
    """The answer as the person who asked it gets it. Deterministic given
    the record alone."""
    interrogation = record.get("interrogation") or {}
    lines = _header_lines(record)

    if interrogation.get("disposition") == "refuse":
        lines.extend(_refusal_lines(record))
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(_claim_lines(record.get("claims") or []))
    counter_position = record.get("counter_position")
    if isinstance(counter_position, dict):
        lines.extend(_counter_position_lines(counter_position))
    lines.extend(_bibliography_lines(record))

    return "\n".join(lines).rstrip() + "\n"
