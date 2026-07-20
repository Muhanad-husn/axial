"""Holdings-completeness probe (issue #268, PRD §7.11, §8 P0-1b).

A **partial holding** is a source file that carries only part of the work
it names: one volume of a multi-volume set, a truncated scan, an extract
circulated as if it were the whole book. This module runs a deterministic
check -- zero model, embedding, and network calls -- over the raw text
layer `axial.intake` already extracts, and returns a flag (or `None`) that
`intake()` attaches to the `Source` it produces. It never rejects: this is
a flag-only signal for an operator to judge, not an intake gate.

Two signals run, in order (`probe`, below). Signal A (printed-TOC page
extent) is preferred; Signal B (orphan fragment) covers only the sources on
which Signal A has no reading. See each signal's own functions for the
detail; the six tunables below are the corpus-tuned cutoffs, kept named and
commented (in the spirit of the chunk band, §7.7, and the low-alpha
threshold, §7.8) rather than scattered as magic literals.
"""

from __future__ import annotations

import re

# =============================================================================
# Tunables. Stated tunables, not hardcoded magic numbers -- named so they can
# be revisited as the corpus grows, without hunting for literals scattered
# through the code.
# =============================================================================

# Signal A (printed-TOC page extent) fires when COVER = physical page count /
# max contents-page reference falls below this floor. Proven by inspection
# over the 30-source corpus (issue #268's pinned measurement-pass comment):
# the one known truncated source (Mann, vol. 2) scores 0.10; the lowest-
# scoring complete work scores 1.03 -- 0.5 sits inside that ~9.9x gap with
# wide margin on both sides.
COVER_FLOOR = 0.5

# Signal B (orphan fragment) requires the physical page count to sit below
# this ceiling. A paper/chapter offprint/fragment is short; a full book
# with no contents page found is not. Proven by inspection over the 30-source
# corpus (the sole orphan-fragment true positive, Ungor, is 20pp).
ORPHAN_PAGE_CEILING = 120

# How many leading physical pages of the raw text layer are scanned, in
# order, for a contents heading line before Signal A gives up and reports
# no reading.
CONTENTS_SEARCH_PAGES = 30

# How many pages, starting at the located contents heading, the contents
# region can span: the heading's own page, plus following pages while they
# keep yielding entry-shaped lines, bounded here.
CONTENTS_SPAN_PAGES = 3

# The fraction of the source's tail (by physical page count) Signal B's
# back-matter test measures over, e.g. the final 10% of an 80-page source is
# its last 8 pages.
TAIL_WINDOW_FRACTION = 0.10

# The minimum rate of bibliography/index-entry SIGNALS (inverted
# author-name citations, or index term-plus-page-list lines) per 100 words
# of Signal B's tail window, for the source to count as carrying back
# matter. §7.11 pins this by observable rather than a pre-existing measured
# corpus value: "bayat" and "heydemann-war" (real sources whose reference-
# list/index tails a heading-regex test misses, §7.11's own named false-
# positive guard) must test as HAVING back matter, and a true orphan
# fragment (an ordinary-prose tail with no bibliographic apparatus at all)
# must not.
#
# This is a RATE over text volume (words), not a fraction of matching LINES
# over total lines, deliberately: measured against the real 30-source corpus
# (issue #268 review, F2), a genuine bibliography entry routinely wraps
# across several extracted lines and only its first line carries the
# "Lastname, F." shape (e.g. `state-legitimacy`'s tail: an author/year/title
# line, then "Stanford University Press.", then a journal citation split
# over 2-3 more lines) -- a per-LINE fraction is diluted by exactly those
# continuation lines until it reads as "no back matter" even on a real
# bibliography, which is precisely the heading-regex failure mode §7.11
# rejects (measured: `heydemann-war` scored 0.059 under a per-line fraction,
# well under any sane threshold). A per-100-words rate is immune to how many
# lines a citation happens to wrap across, since the denominator is text
# volume, not line count.
#
# Measured over the real corpus's 7 no-contents-page sources (data/_scratch,
# not committed): the true orphan fragment (Ungor) scores 0.0 signals/100w;
# every source with genuine back matter -- including the two named false-
# positive guards -- scores at or above `heydemann-war`'s 2.76 (its
# contributor-bio-heavy back matter is the corpus's sparsest legitimate
# case; `bayat` scores 10.32, `do-civil-wars` 3.36, `state-legitimacy`
# 4.31). 1.0 sits with wide margin on both sides of that (0.0, 2.76] gap.
BACKMATTER_ENTRY_DENSITY = 1.0

_CONTENTS_HEADINGS = frozenset({"contents", "table of contents"})

# An entry-shaped contents-page line: title text ending in a letter, a
# period, or a close-paren, then whitespace, then a trailing 1-4 digit whole
# number and nothing else. A real dot-leader run's own last character is a
# period, so this shape covers it too, but does NOT require it -- measured
# against the real 30-source corpus (issue #268 review, F1), a printed dot
# leader does not survive `pypdf` text extraction: the visual gap collapses
# to a single space (e.g. "6 Auctoritas and Potestas 74"), and requiring a
# literal leader run left Signal A a reading on only 4/30 real sources
# instead of the spec's measured 21/30.
_TOC_ENTRY_LINE_RE = re.compile(r"^(?P<title>\S.*?[A-Za-z.)])\s+(?P<number>\d{1,4})$")

# A structural entry-shape match alone is not strict enough once the leader
# requirement is dropped: it also matches an ordinary prose sentence that
# happens to end in a bare number, e.g. the locked outer test's decoy line
# ("This edition was substantially revised in 1975"). The semantic filter
# that holds that off without reintroducing the leader requirement: reject
# a match whose title's own LAST WORD is a common short function word. A
# genuine entry title ends in the substantive noun/name being indexed
# ("Empire", "Potestas", "Puzzles", "Index", "Conclusion" ...); the decoy's
# number is incidental to an ordinary sentence, and it is exactly this
# family of word ("...revised IN 1975") that precedes it.
_ENTRY_TRAILING_STOPWORDS = frozenset(
    "a an the of in on at by to for from with and or as is was were be "
    "been but that this these those into onto over under since during "
    "after before than then so".split()
)

# An inverted author-name citation entry, e.g. "Bayat, A." or "Heydemann, S.":
# a capitalized surname, a comma, then a capitalized initial/given-name
# token. Narrow by construction (mirrors the family of signal
# `axial.router`'s content-apparatus arm uses per block, §7.8) so an
# ordinary sentence's incidental comma never matches.
_INVERTED_AUTHOR_NAME_RE = re.compile(r"[A-Z][a-z]+,\s+[A-Z]")

# An index entry: a term followed by a comma-separated list of page numbers
# (optionally hyphenated ranges), and nothing else on the line -- e.g.
# "state formation, 12, 45, 88-91".
_INDEX_ENTRY_LINE_RE = re.compile(r"^.+?,\s*\d+(?:[-–]\d+)?(?:,\s*\d+(?:[-–]\d+)?)*\s*$")


def _is_contents_heading(line: str) -> bool:
    """True when `line`, lowercased with internal whitespace collapsed, reads
    exactly `contents` or `table of contents` (§7.11)."""
    normalized = " ".join(line.strip().split()).lower()
    return normalized in _CONTENTS_HEADINGS


def _entry_title_last_word(title: str) -> str:
    """The title's own last word, letters only, lowercased -- what
    `_extract_entry_reference`'s stopword filter tests."""
    return re.sub(r"[^A-Za-z]", "", title.rsplit(None, 1)[-1]).lower()


def _extract_entry_reference(line: str) -> int | None:
    """The trailing whole number on an entry-shaped contents-page `line`
    (title text ending in a letter/period/close-paren, whitespace, then a
    1-4 digit number), or `None` when `line` does not match that shape --
    an ordinary prose line, a bare year whose title ends in a function word,
    or a garbled/non-numeric trailing token (§7.11)."""
    match = _TOC_ENTRY_LINE_RE.match(line.strip())
    if match is None:
        return None
    if _entry_title_last_word(match.group("title")) in _ENTRY_TRAILING_STOPWORDS:
        return None
    return int(match.group("number"))


def _find_contents_region(page_texts: list[str]) -> list[str] | None:
    """Locate the contents region (§7.11): scan the first
    `CONTENTS_SEARCH_PAGES` of `page_texts`, in order, for the first page
    carrying a contents heading line; the region is that page plus following
    pages while they keep yielding at least one entry-shaped line, bounded
    at `CONTENTS_SPAN_PAGES` pages total. Returns `None` when no contents
    heading is found within the search window."""
    search_limit = min(len(page_texts), CONTENTS_SEARCH_PAGES)
    heading_index = None
    for index in range(search_limit):
        if any(_is_contents_heading(line) for line in page_texts[index].splitlines()):
            heading_index = index
            break
    if heading_index is None:
        return None

    region = [page_texts[heading_index]]
    next_index = heading_index + 1
    while len(region) < CONTENTS_SPAN_PAGES and next_index < len(page_texts):
        page_text = page_texts[next_index]
        has_entry = any(
            _extract_entry_reference(line) is not None for line in page_text.splitlines()
        )
        if not has_entry:
            break
        region.append(page_text)
        next_index += 1
    return region


def _signal_a_reading(page_texts: list[str]) -> int | None:
    """Signal A's own reading (§7.11): the maximum entry page reference
    found in the contents region, or `None` when no contents page is
    located or the region yields no readable entry reference at all --
    "no reading", handed off to Signal B rather than a false fire."""
    region = _find_contents_region(page_texts)
    if region is None:
        return None
    references = [
        ref
        for page_text in region
        for line in page_text.splitlines()
        if (ref := _extract_entry_reference(line)) is not None
    ]
    if not references:
        return None
    return max(references)


def _is_index_entry_line(line: str) -> bool:
    """True when `line` is shaped like an index entry: a term followed by a
    page-number list. Content-based, never a heading match (§7.11)."""
    stripped = line.strip()
    return bool(stripped) and bool(_INDEX_ENTRY_LINE_RE.match(stripped))


def _backmatter_density(page_texts: list[str]) -> float:
    """The measured RATE (§7.11) of bibliography/index-entry signals --
    inverted author-name citations and index term-plus-page-list lines --
    per 100 words across the tail window: the last `TAIL_WINDOW_FRACTION` of
    `page_texts` by physical page count (at least one page).

    A rate over text volume, not a fraction of matching LINES over total
    lines: the inverted-author-name signal is counted over the window's
    joined text (so a citation wrapped across several extracted lines is
    still one signal, found wherever it falls), and the denominator is word
    count, not line count -- immune to how many lines a wrapped citation
    happens to span, unlike a per-line fraction (see `BACKMATTER_ENTRY_
    DENSITY`'s own comment for the real-corpus case this fixes). `0.0` when
    the window carries no words at all."""
    physical_pages = len(page_texts)
    window_size = max(1, round(physical_pages * TAIL_WINDOW_FRACTION))
    window_pages = page_texts[-window_size:]
    lines = [
        line.strip()
        for page_text in window_pages
        for line in page_text.splitlines()
        if line.strip()
    ]
    if not lines:
        return 0.0
    joined = " ".join(lines)
    word_count = len(joined.split())
    if word_count == 0:
        return 0.0
    author_signals = len(_INVERTED_AUTHOR_NAME_RE.findall(joined))
    index_signals = sum(1 for line in lines if _is_index_entry_line(line))
    return (author_signals + index_signals) / word_count * 100


def probe(page_texts: list[str]) -> dict | None:
    """Run the deterministic holdings-completeness probe (§7.11, §8 P0-1b)
    over `page_texts` (one raw text-layer string per physical page, in
    reading order -- `axial.intake._pdf_page_texts`'s own shape). Signal A
    runs first; only a source on which it returns no reading falls through
    to Signal B. Returns the fired flag dict, or `None` when neither signal
    fires. Zero model, embedding, or network calls: this function only ever
    reads the `page_texts` already in hand."""
    physical_pages = len(page_texts)

    max_reference = _signal_a_reading(page_texts)
    if max_reference is not None:
        cover = physical_pages / max_reference
        if cover < COVER_FLOOR:
            return {
                "signal": "toc_page_extent",
                "cover": cover,
                "physical_pages": physical_pages,
                "max_page_reference": max_reference,
                "threshold": COVER_FLOOR,
            }
        return None

    if physical_pages >= ORPHAN_PAGE_CEILING:
        return None

    density = _backmatter_density(page_texts)
    if density >= BACKMATTER_ENTRY_DENSITY:
        return None

    return {
        "signal": "orphan_fragment",
        "physical_pages": physical_pages,
        "backmatter_density": density,
        "threshold": ORPHAN_PAGE_CEILING,
    }
