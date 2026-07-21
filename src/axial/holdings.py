"""Holdings-completeness check and title-page bibliographic read (PRD §7.11,
§7.13, §8 P0-1b/P0-1d).

A **partial holding** is a source file that carries only part of the work
it names: one volume of a multi-volume set, a truncated scan, an extract
circulated as if it were the whole book. This module cleans the raw text
layer `axial.intake` already extracts and hands it to **one** model call
that judges, in a single pass, what kind of document this is, what extent
it claims for itself, and whether the file covers that extent -- and, in
the same pass (issue #285), what the document's own title page states as
its title/author/publication year, and whether the file's *embedded*
metadata plausibly names the same document. `probe()` returns both halves
together (`holdings_flag`, `title_page`) rather than paying for a second
model call over the same front matter: `axial.intake` owns the three-state
field policy (embedded metadata, `unavailable`, `not_attempted`) that turns
the raw `title_page` reading into a recorded field.

`intake()` attaches `holdings_flag` (or `None`) to the `Source` it
produces. It never rejects: this is a flag-only signal for an operator to
judge, not an intake gate.

Deterministic first, model second (§7.11):

- the **physical page count** comes from the file, never from the model;
- **running headers/footers are stripped** before any text is read for
  judgment, so `tilly`'s contents heading -- which extracts as
  `viii Contents`, a folio stitched to the running head -- reaches the
  model as `Contents`. The **opening pages are shown a second time as
  printed** (§7.13, issue #316), because a book whose title runs as its
  own header loses that title off its own title page to the strip.

The earlier deterministic two-signal design (a printed-contents page-extent
ratio with a back-matter-density fallback) was measured and removed in
#284: a research paper legitimately has no contents page, and no threshold
separates a complete paper from a truncated book. §7.11 records the full
measurement; do not rebuild it.
"""

from __future__ import annotations

import re
import sys
from typing import Any

import httpx

from axial.llm import HOLDINGS_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json

# =============================================================================
# Stated tunables (§7.11: "at most a small number ... plausibly the size of
# the front-matter window and the size of the tail window", values set by
# measurement over the 30-source corpus, not asserted).
# =============================================================================

# Leading physical pages handed to the model. Measured over the corpus: the
# printed contents page starts at page index 3-8 and can span 5 pages
# (`batatu`), and a volume/part statement lives on the title page; 20 pages
# covers every corpus source's front matter with margin.
FRONT_MATTER_PAGES = 20

# Trailing physical pages handed to the model. The tail is what separates a
# complete short work (ends with a reference list / index) from a fragment
# that breaks off mid-argument.
TAIL_PAGES = 3

# Leading pages shown to the model a second time, exactly as extracted, in
# addition to the cleaned windows below. The half title, title page and
# copyright page live here. The running-furniture strip deletes a book's main
# title from its own title page whenever that title also runs as a header --
# measured over the corpus on 7 of the 30 sources, and on `ugur-paramilitarism`
# and `chouliaraki` the printed main title then reached the model on no page at
# all, so the read could only ever return the subtitle (issue #316).
AS_PRINTED_PAGES = 4

# How many sampled pages a head/foot line must recur on before it counts as
# running furniture (a running head, running title, or top-of-page folio)
# rather than content. A real running head repeats on every page of a
# section -- dozens; a heading that happens to repeat twice (`tilly`'s
# two-page contents) is content and must survive.
RUNNING_FURNITURE_MIN_PAGES = 3

DOCUMENT_KINDS = frozenset({"book", "research_paper", "chapter_offprint", "fragment"})

# A page-number token: a 1-4 digit arabic number, or a roman numeral.
_FOLIO_RE = re.compile(r"(?:\d{1,4}|[ivxlcdm]{1,7})", re.IGNORECASE)
_LEADING_FOLIO_RE = re.compile(rf"^{_FOLIO_RE.pattern}\s+(?=\S)", re.IGNORECASE)
_WHOLE_FOLIO_RE = re.compile(rf"^{_FOLIO_RE.pattern}$", re.IGNORECASE)


def _page_lines(page_text: str) -> list[str]:
    return [line for line in (raw.strip() for raw in page_text.splitlines()) if line]


def _signature(line: str) -> str:
    """A running-furniture signature: the line with digits removed, cased
    down and whitespace-collapsed, so `vi Preface` and `viii Preface` are
    one signature."""
    return " ".join(re.sub(r"\d+", "", line).split()).casefold()


def _uses_top_folios(pages: list[list[str]]) -> bool:
    """True when the document prints page numbers at the top of its pages --
    measured, not assumed: at least `RUNNING_FURNITURE_MIN_PAGES` of the
    sampled pages open with a page-number token followed by more text.

    Gating the leading-folio strip on this keeps it off documents that do
    not number pages at the top, where a first line opening with a number
    ("1978 was a turning point ...") is ordinary prose, not furniture."""
    hits = sum(1 for lines in pages if lines and _LEADING_FOLIO_RE.match(lines[0]))
    return hits >= RUNNING_FURNITURE_MIN_PAGES


def strip_running_furniture(page_texts: list[str]) -> list[str]:
    """Remove running headers, running titles and page-number folios from
    `page_texts` (§7.11, a stated requirement of the check).

    Three deterministic removals, all confined to each page's first and last
    line -- where page furniture lives -- so a contents entry in the body of
    a page is never touched:

    - a first/last line that is nothing but a page number is dropped;
    - a first/last line whose signature recurs across
      `RUNNING_FURNITURE_MIN_PAGES` or more pages is dropped (a running head);
    - when the document numbers pages at the top, a leading page-number
      token is stripped off the first line, leaving the text beside it --
      this is what turns `viii Contents` into `Contents`.
    """
    pages = [_page_lines(text) for text in page_texts]

    counts: dict[str, int] = {}
    for lines in pages:
        for line in set(lines[:1] + lines[-1:]):
            counts[_signature(line)] = counts.get(_signature(line), 0) + 1

    top_folios = _uses_top_folios(pages)

    cleaned: list[str] = []
    for lines in pages:
        if not lines:
            cleaned.append("")
            continue
        out = list(lines)
        edges = [0, len(out) - 1] if len(out) > 1 else [0]
        for index in edges:
            line = out[index]
            if _WHOLE_FOLIO_RE.match(line):
                out[index] = ""
                continue
            if counts.get(_signature(line), 0) >= RUNNING_FURNITURE_MIN_PAGES:
                out[index] = ""
                continue
            if index == 0 and top_folios:
                out[index] = _LEADING_FOLIO_RE.sub("", line)
        cleaned.append("\n".join(line for line in out if line))
    return cleaned


def _window(page_texts: list[str]) -> tuple[list[str], list[str]]:
    """The front-matter and tail windows handed to the model. A document
    shorter than both windows together yields its whole text as front
    matter and an empty tail (never the same page twice)."""
    front = page_texts[:FRONT_MATTER_PAGES]
    tail = page_texts[max(len(front), len(page_texts) - TAIL_PAGES) :]
    return front, tail


def _as_printed(page_texts: list[str]) -> str:
    """The first `AS_PRINTED_PAGES` pages that carry text, rendered exactly
    as extracted -- no furniture stripping (§7.13, issue #316).

    The strip is right for the holdings judgment and wrong for the
    bibliographic read: a title that runs as a header recurs often enough to
    be counted as furniture, and is then removed from the title page itself.
    Blank pages are skipped rather than counted, since a half title is
    routinely followed by a blank leaf."""
    blocks: list[str] = []
    for index, text in enumerate(page_texts):
        if not text.strip():
            continue
        blocks.append(f"[page {index + 1}]\n{text.strip()}")
        if len(blocks) >= AS_PRINTED_PAGES:
            break
    return "\n\n".join(blocks)


def _render(pages: list[str], first_index: int) -> str:
    blocks = []
    for offset, text in enumerate(pages):
        if text.strip():
            blocks.append(f"[page {first_index + offset + 1}]\n{text.strip()}")
    return "\n\n".join(blocks)


def _embedded_metadata_claim(embedded_author: str | None, embedded_title: str | None) -> str:
    """The prompt line stating what the file's *embedded* metadata claims
    (or that it claims nothing), for the model to cross-check against what
    it reads on the actual title page (§7.13, issue #285 finding 2: recycled
    embedded metadata describing an unrelated book)."""
    claims = []
    if embedded_author:
        claims.append(f'- Author: "{embedded_author}"')
    if embedded_title:
        claims.append(f'- Title: "{embedded_title}"')
    if not claims:
        return "The file's own embedded metadata states no author and no title."
    return "The file's own embedded metadata claims:\n" + "\n".join(claims)


def compose_prompt(
    page_texts: list[str],
    physical_pages: int | None,
    *,
    embedded_author: str | None = None,
    embedded_title: str | None = None,
) -> str:
    """Assemble the single combined prompt: window `page_texts` down to the
    front matter and the tail, strip running furniture from those pages,
    and render them with their physical page numbers. The opening pages are
    ALSO rendered as printed, unstripped (`_as_printed`, issue #316): the
    strip serves the holdings judgment and starves the title-page read,
    which needs the title page as the book prints it.

    The model is asked for one judgment covering document kind, claimed
    extent and coverage together (§7.11), and is told to answer "complete"
    whenever the evidence is absent or ambiguous -- the 0-false-positive
    bar is the contract, and an unread document must not become a flag.

    In the same call (§7.13, issue #285), it is also asked to read the
    title page's own stated title/author/publication year, and to judge
    whether `embedded_author`/`embedded_title` (the file's *embedded*
    metadata, when any was found) plausibly names this same document --
    the cross-check that catches recycled/unrelated embedded metadata.
    """
    front, tail = _window(page_texts)
    cleaned = strip_running_furniture(front + tail)
    front, tail = cleaned[: len(front)], cleaned[len(front) :]
    extent = (
        f"{physical_pages} pages"
        if physical_pages is not None
        else "unknown (this file format exposes no page count)"
    )
    sections = [
        f"=== OPENING PAGES, AS PRINTED (nothing stripped) ===\n{_as_printed(page_texts)}",
        f"=== FRONT MATTER ===\n{_render(front, 0)}",
    ]
    if tail:
        sections.append(f"=== FINAL PAGES ===\n{_render(tail, len(page_texts) - len(tail))}")

    embedded_claim = _embedded_metadata_claim(embedded_author, embedded_title)

    return f"""You are checking whether a source file carries the complete work it names, or only part of it (one volume of a set, a truncated scan, a single chapter circulated as if it were the book) -- and separately reading its bibliographic identity off its own title page.

Physical extent of the file: {extent}.

Below are two EXCERPTS from the file, labelled with their physical page numbers: its opening pages, and its final pages. The pages between the two excerpts are present in the file and are simply not shown to you here. Running headers, running titles and page-number folios have been stripped.

{"\n\n".join(sections)}

{embedded_claim}

=== YOUR JUDGMENT ===

Decide these together, from the supplied text and the physical extent only. Do not use outside knowledge of this work.

1. What kind of document this is: "book", "research_paper", "chapter_offprint", or "fragment".
2. What extent the document claims for itself, if it states one: the last page number in a printed table of contents, a title page naming a volume of a set, a stated page range. Give a short value ("816 pages", "volume 2 of 4", "pp. 45-72") and what stated it ("printed contents page", "title page"). Use null for both when the document states no extent.
3. Whether the file covers that claimed extent.
4. What the document's own title page / front matter states -- NOT the embedded metadata claim above -- as its title, its author(s), and its publication year (typically next to a copyright or "first published" marker). A title page routinely prints ONE title across two lines, a main title above its subtitle, with no punctuation joining them; read those lines together as a single title, main title first, joined with ": ". Answering with the subtitle alone, or with the main title alone, is wrong. Do not sweep in the neighbouring lines that are not part of the title: the author, a series name, the publisher, an edition or volume statement. Use null for any of these the front matter itself does not state. Never invent a value the front matter does not carry, and never copy this answer from the embedded metadata claim above.
5. Whether the embedded metadata claim above plausibly describes THIS document: does its stated Author name a real author of this work, and does its stated Title name this work? A wrong or unrelated author/title -- metadata recycled from a different file during conversion -- answers false. Use null for a field the embedded metadata claimed nothing for (there is nothing to judge).

Rules:
- The unshown middle of the file is omitted from this prompt, NOT missing from the file. Never treat that gap as evidence of truncation.
- A research paper, a book chapter and an essay normally have NO table of contents. A missing table of contents is not evidence of truncation.
- The physical page count normally EXCEEDS the last printed page number, because front matter is numbered separately. A small shortfall is normal. Only a file that runs to a small fraction of what it claims is truncated.
- Answer "partial" only on positive evidence in the text: a claimed extent the file plainly cannot cover, front matter naming a volume or part the file does not contain, or a work that breaks off mid-argument with no ending, no conclusion and no reference apparatus.
- When the evidence is absent, weak, or ambiguous, answer "complete".

Return ONLY this JSON object, no prose and no code fence:
{{"document_kind": "book|research_paper|chapter_offprint|fragment", "claimed_extent": "<short value or null>", "claimed_extent_stated_by": "<what stated it, or null>", "verdict": "complete|partial", "reason": "<one or two short sentences, no quoted source text>", "title_page_title": "<the full title stated on the title page -- main title and subtitle together -- or null>", "title_page_author": "<author(s) stated on the title page, or null>", "title_page_date": "<publication year stated on the title page, or null>", "author_metadata_matches": true|false|null, "title_metadata_matches": true|false|null}}"""


def _reject_unusable_answer(raw: str) -> None:
    """Validator for `complete_json`'s bounded re-ask (issue #80's
    degenerate-content mechanism): the answer must be an object naming a
    verdict, and a "partial" verdict must carry a reason -- a flag whose
    stated reason is blank is a flag an operator cannot judge. Measured:
    one answer in eight came back with an empty reason."""
    answer = parse_model_json(raw)
    if not isinstance(answer, dict):
        raise ValueError(f"holdings answer was not a JSON object: {type(answer).__name__}")
    verdict = str(answer.get("verdict", "")).strip().lower()
    if verdict not in {"complete", "partial"}:
        raise ValueError(f"holdings answer named no verdict: {verdict!r}")
    if verdict == "partial" and not str(answer.get("reason", "")).strip():
        raise ValueError("holdings answer flagged a partial holding with no stated reason")


def _flag_from(
    verdict: dict[str, Any], source_name: str, physical_pages: int | None
) -> dict | None:
    """Build the §7.11 flag from the model's parsed answer, or `None` when
    it judged the holding complete.

    The flag records its measurement -- source, concluded kind, claimed
    extent and what stated it, observed page count, stated reason -- never a
    bare boolean, and carries values and short reasons only, no source text
    (DEC-23). An answer that is not a recognisable "partial" verdict is
    treated as complete: the bar is 0 false positives, so an unreadable
    answer must not become a flag.
    """
    if str(verdict.get("verdict", "")).strip().lower() != "partial":
        return None
    kind = str(verdict.get("document_kind", "")).strip().lower().replace(" ", "_")
    claimed = verdict.get("claimed_extent")
    stated_by = verdict.get("claimed_extent_stated_by")
    return {
        "source": source_name,
        "document_kind": kind if kind in DOCUMENT_KINDS else "unknown",
        "claimed_extent": str(claimed) if claimed else None,
        "claimed_extent_stated_by": str(stated_by) if stated_by else None,
        "observed_pages": physical_pages,
        "reason": str(verdict.get("reason", "")).strip(),
    }


def _empty_title_page() -> dict[str, Any]:
    """The title-page reading's own "nothing read" shape -- the default when
    no model call was made or the call/answer was unusable. Every key is
    `None`, distinguishable from a real (if negative) judgment."""
    return {
        "author": None,
        "title": None,
        "date": None,
        "author_matches_embedded": None,
        "title_matches_embedded": None,
    }


def _title_page_from(verdict: dict[str, Any]) -> dict[str, Any]:
    """The title-page half of the model's answer (§7.13, issue #285): its
    own stated title/author/publication year, and -- only when the prompt
    supplied an embedded-metadata claim to check -- whether that claim
    plausibly names this document.

    A match key is `None` when the model made no judgment (no embedded
    claim was given to compare, or the answer omitted/garbled the key):
    `axial.intake` treats that as "no evidence of a mismatch" and keeps
    trusting the embedded value exactly as it did before this check
    existed. Only an explicit `false` downgrades it -- the asymmetry that
    makes the cross-check additive rather than a new way to lose a
    previously-working answer.
    """

    def _text(key: str) -> str | None:
        value = verdict.get(key)
        text = str(value).strip() if value else ""
        return text or None

    def _match(key: str) -> bool | None:
        value = verdict.get(key)
        return value if isinstance(value, bool) else None

    return {
        "author": _text("title_page_author"),
        "title": _text("title_page_title"),
        "date": _text("title_page_date"),
        "author_matches_embedded": _match("author_metadata_matches"),
        "title_matches_embedded": _match("title_metadata_matches"),
    }


def probe(
    page_texts: list[str],
    *,
    client: LLMClient,
    physical_pages: int | None,
    source_name: str = "",
    embedded_author: str | None = None,
    embedded_title: str | None = None,
) -> dict[str, Any]:
    """Run the combined holdings-completeness + title-page bibliographic
    read (§7.11/§7.13, §8 P0-1b/P0-1d) over `page_texts` (one raw text-layer
    string per physical page, in reading order --
    `axial.intake._pdf_page_texts`'s own shape; a DOCX passes its whole text
    as a single element and `physical_pages=None`).

    Strips running furniture, then makes exactly ONE model call, on the
    holdings pass (reasoning ON, carried in `config/pipeline.yaml`, never
    hardcoded) -- covering both judgments together rather than paying for a
    second pass over the same front matter (issue #285). `embedded_author`/
    `embedded_title`, when given, are stated in the prompt as the file's own
    embedded-metadata claim for the model to cross-check against what it
    actually reads on the title page.

    Always returns a dict with three keys:
    - `"holdings_flag"`: the §7.11 flag dict for a holding judged partial,
      or `None` (unchanged shape/semantics from before this call carried a
      second purpose).
    - `"title_page"`: the §7.13 reading, see `_title_page_from`/
      `_empty_title_page`.
    - `"answered"`: whether a usable answer actually came back. `None`/no
      flag is not evidence that the judgment was made -- an empty text
      layer, a failed call, or an unreadable answer produces exactly the
      same "nothing read" shape as a document judged complete. The caller
      persisting the judgment (`axial.intake`, §7.12) needs to tell those
      apart, or a transient failure would be cached as a judgment and the
      source would never be checked again (issue #303).

    Reads neither `data/trees/` nor `data/envelopes/`. Never raises. A
    failed or unparseable model call degrades to "no flag, nothing read"
    with a warning on stderr: P0-1b forbids this check halting intake, and
    the 0-false-positive bar forbids guessing either half of the answer it
    could not read.
    """
    no_read = {"holdings_flag": None, "title_page": _empty_title_page(), "answered": False}
    if not any(text.strip() for text in page_texts):
        return no_read

    prompt = compose_prompt(
        page_texts,
        physical_pages,
        embedded_author=embedded_author,
        embedded_title=embedded_title,
    )
    try:
        raw = complete_json(
            client, prompt, pass_name=HOLDINGS_PASS_NAME, validate=_reject_unusable_answer
        )
        verdict = parse_model_json(raw)
    except (LLMError, httpx.HTTPError, ModelJsonError, ValueError) as exc:
        print(
            f"holdings/bibliographic check unavailable for {source_name or 'source'}: {exc}",
            file=sys.stderr,
        )
        return no_read

    if not isinstance(verdict, dict):
        return no_read
    return {
        "holdings_flag": _flag_from(verdict, source_name, physical_pages),
        "title_page": _title_page_from(verdict),
        "answered": True,
    }
