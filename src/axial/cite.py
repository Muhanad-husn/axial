"""How a citation reads on a page (issue #783, folding in #786; APA house
style, issue #787 slice 03).

One module, one answer to "what does a citation look like", for every
surface: the reader-facing markdown renders (`axial.paper.reader`,
`axial.answer.reader`), the served record (`axial.service.citation`
attaches the rendered string as `citation.display`) and the web client,
which formats nothing and prints what it is sent (`web/src/lib/paper.ts`).
Two implementations of this that can disagree about the same ground is the
defect #786 was filed on.

Pure: strings in, strings out. Resolution -- turning a `chunk` pointer into
`{source_id, author, title, date, chapter, section}` -- lives one layer
down in `axial.query.citations`, which reads the corpus store. This module
never reads anything.

**Two forms, both from the same fields.** `full` is the footer form and
carries whatever resolved: `Leila Vignal (2021), Anatomy of a conflict,
Fragmenting space and society`. `short` is the in-text form -- APA's
author-date parenthetical, surname and year with a comma between them:
`Vignal, 2021`. A date that did not resolve reads `n.d.`, APA's own word
for exactly that absence, never a blank.

Neither invents a page number -- there is none anywhere in this system
(`axial.query.store.note_locator`). And neither labels the locator `ch.`,
because the store's `chapter` is a chapter HEADING read from the source's
own table of contents ("ANATOMY OF A CONFLICT FROM REVOLUTION TO WAR"),
not a number: `ch. ANATOMY OF A CONFLICT...` reads as a defect. #786 filed
against `ch. 30`, which was read off a chunk id's section index rather than
off the store -- the id's number is not the book's chapter number.

The in-text form carries no locator for the same reason: an in-text
citation is where a reader is told which book, and a full chapter heading
inside a parenthesis in the middle of a sentence is not readable. The
locator is still one line away, in the full form.

**An unresolved citation reads as unresolved.** `format_citation` returns
`None` when it was handed nothing, and every caller falls back to the raw
`ref_type:ref_id` pointer rather than dropping the citation silently. A
reader seeing a raw pointer is being told the truth about that ground.
"""

from __future__ import annotations

import re
from typing import Any

# A trailing `;` or `,` on an author value read out of embedded metadata
# ("Leila Vignal ;"), and a role suffix the same field carries
# ("Kristen Kao (Editor)"). Stripped for display only -- the record's own
# value is never rewritten.
_AUTHOR_TRAILING_RE = re.compile(r"[\s;,]+$")
_AUTHOR_ROLE_RE = re.compile(r"\s*\([^)]*\)\s*$")

# A string naming more than one person -- `John A. Hall and Ralph
# Schroeder`, measured in 3 of 35 real `data/source_meta/` records -- has no
# single surname to invert. Checked as a whole word so a surname that
# happens to contain the letters (`Anderson`) is never mistaken for a join.
_MULTI_AUTHOR_RE = re.compile(r"\band\b", re.IGNORECASE)

FULL = "full"
SHORT = "short"


def clean_author(value: Any) -> str:
    """An author value as it should read on a page: trailing separators and
    a role suffix removed, and an all-caps name cased -- some sources record
    the author as `STATHIS N. KALYVAS`, and `(KALYVAS 2006)` shouts at a
    reader mid-sentence. Only a value with no lowercase letter at all is
    touched, so `Uğur Ümit Üngör` is left exactly as it is.

    A title or a chapter heading in caps is NOT softened this way: casing a
    sentence back down loses the proper nouns inside it, and a wrong title
    is worse than a loud one. `""` when there is no usable value."""
    if not isinstance(value, str):
        return ""
    text = _AUTHOR_ROLE_RE.sub("", value)
    text = _AUTHOR_TRAILING_RE.sub("", text).strip()
    if text and text == text.upper() and text != text.lower():
        text = text.title()
    return text


def author_surname(value: Any) -> str:
    """The surname to print in an in-text citation. `Beshara, Adel` ->
    `Beshara`; `Uğur Ümit Üngör` -> `Üngör`. A single-token value is
    returned whole, and an empty one stays empty -- the caller decides what
    to print instead."""
    text = clean_author(value)
    if not text:
        return ""
    if "," in text:
        return text.split(",", 1)[0].strip()
    return text.split()[-1]


def apa_author(value: Any) -> str:
    """`value` as APA wants an author printed in the bibliography:
    `Surname, F. M.`

    The surname is picked exactly the way `author_surname` already picks it
    -- the text before a comma, or the last whitespace token -- so `Michael
    Mann` and `Mann, Michael` invert to the identical `Mann, M.` regardless
    of which order the title page printed. Nothing is folded to make that
    decision: a token's *position* in the string, not its letters, says
    where the surname is, so `Siniša Malešević` inverts to `Malešević, S.`
    with its diacritic intact in either metadata order.

    Where the string cannot be confidently inverted, it prints exactly as
    given -- `biblio.py`'s own never-guess rule. Two cases trigger it: a
    string naming more than one person (`John A. Hall and Ralph Schroeder`,
    measured in 3 of 35 real `data/source_meta/` records -- there is no
    single surname to invert to), and a single bare token (nothing to
    attach an initial to, and nothing gained by inverting it onto itself).
    """
    text = clean_author(value)
    if not text or _MULTI_AUTHOR_RE.search(text):
        return text
    if "," in text:
        surname, _, given = text.partition(",")
    else:
        tokens = text.split()
        if len(tokens) < 2:
            return text
        surname, given = tokens[-1], " ".join(tokens[:-1])
    surname = surname.strip()
    if not surname:
        return text
    initials = " ".join(f"{token[0].upper()}." for token in given.split() if token[:1].isalpha())
    return f"{surname}, {initials}" if initials else surname


def format_citation(citation: Any, *, form: str = FULL) -> str | None:
    """One resolved citation block rendered for a reader, or `None` when
    `citation` is not a resolved block at all.

    `full` names the author with the date in parentheses and appends
    whatever locator resolved; `short` is APA's own in-text shape, the
    surname and the year with a comma between them (`Vignal, 2021`) -- a
    date that did not resolve reads `n.d.` rather than dropping silently. A
    block that resolved no author falls back to its `source_id`, which is
    still a real answer to "which book"; one carrying nothing at all
    returns `None`."""
    if not isinstance(citation, dict):
        return None
    source_id = citation.get("source_id")
    author = clean_author(citation.get("author"))
    date = citation.get("date")
    date_text = str(date).strip() if date not in (None, "") else ""

    if form == SHORT:
        who = author_surname(author) or (str(source_id) if source_id else "")
        if not who:
            return None
        return f"{who}, {date_text or 'n.d.'}"

    who = author or (str(source_id) if source_id else "")
    if not who:
        return None
    parts = [f"{who} ({date_text})" if date_text else who]
    for field in ("chapter", "section"):
        value = citation.get(field)
        if value not in (None, ""):
            parts.append(str(value))
    return ", ".join(parts)


def _ground_citation(ground: Any, *, form: str) -> str:
    """One ground rendered: its formatted citation, or its raw pointer when
    nothing resolved (#786 -- an unresolvable citation reads as
    unresolvable, never as absent)."""
    if not isinstance(ground, dict):
        return str(ground)
    formatted = format_citation(ground.get("citation"), form=form)
    if formatted is not None:
        return formatted
    return f"{ground.get('ref_type')}:{ground.get('ref_id')}"


def citation_summary(grounds: Any, *, form: str = FULL) -> str:
    """Every ground of one claim, rendered and joined with `; `, in the
    record's own order and de-duplicated by rendered text -- two passages
    from one chapter of one book are one citation on the page, not two
    identical ones. `no supporting passage` for an empty grounds list, which
    is a correct thing to say about a (c) claim, not a missing value."""
    if not isinstance(grounds, list) or not grounds:
        return "no supporting passage"
    seen: list[str] = []
    for ground in grounds:
        text = _ground_citation(ground, form=form)
        if text not in seen:
            seen.append(text)
    return "; ".join(seen)


# ---------------------------------------------------------------------------
# The bibliography
# ---------------------------------------------------------------------------
#
# `axial.paper.biblio.format_field` renders a field WITH its provenance
# ("War-Torn (from embedded metadata)") and an absence in words -- correct
# for the audit render, where where-a-value-came-from is the point. A
# reader's bibliography states the four fields the way a bibliography states
# them and omits what did not resolve; the audit render still carries every
# provenance tag, so nothing is lost, only moved.


def format_bibliography_entry(entry: Any) -> str:
    """One `axial.paper.biblio` entry as an APA bibliography line:
    `Surname, F. M. (Year). *Title*. Publisher.` -- author inverted through
    `apa_author`, the year parenthesised and moved forward (`n.d.` when the
    date alone is absent, APA's own word for that §7.13 absence, never a
    blank and never a guess), the title italicised, and each part omitted
    when it did not resolve. The `source_id` stands alone when nothing
    resolved at all."""
    if not isinstance(entry, dict):
        return str(entry)

    def value(field: str) -> str:
        raw = entry.get(field)
        if not isinstance(raw, dict) or "absent" in raw:
            return ""
        return str(raw.get("value") or "").strip()

    author = apa_author(value("author"))
    title = value("title")
    publisher = value("publisher")
    date = value("date")

    if not (author or title or publisher or date):
        return str(entry.get("source_id") or "")

    # `author` already ends in a period when `apa_author` inverted it to
    # initials (`Vignal, L.`); an un-invertible name printed as given does
    # not, so it still needs one before the year.
    author_part = (author if author.endswith(".") else f"{author}.") if author else ""
    parts = [
        author_part,
        f"({date})." if date else "(n.d.).",
        f"*{title}*." if title else "",
        f"{publisher}." if publisher else "",
    ]
    return " ".join(part for part in parts if part)
