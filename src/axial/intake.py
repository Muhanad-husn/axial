"""Corpus intake: extension gate + text-layer probe (PRD §5 stage 1, §8 P0-1).

Accepts only `.pdf` and `.docx`. Rejects everything else with a clear,
typed, logged reason. Verifies a real text layer exists before anything
downstream runs -- a scanned/image-only PDF is rejected, never silently
passed through an OCR path (there is none in this slice).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

# =============================================================================
# Holdings-completeness probe tunables (§7.11, §8 P0-1b). Stated tunables,
# not hardcoded magic numbers, in the spirit of the chunk band (§7.7) and the
# low-alpha threshold (§7.8) -- named so they can be revisited as the corpus
# grows, without hunting for literals scattered through the code.
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

# The minimum fraction of non-blank lines in Signal B's tail window that
# must look like bibliography/index entries (inverted author-name citations
# or index term-plus-page-list lines) for the source to count as carrying
# back matter. §7.11 pins this by observable rather than a measured corpus
# value: "bayat" and "heydemann-war" (real sources whose reference-
# list/index tails a heading-regex test misses, §7.11's own named false-
# positive guard) must test as HAVING back matter, and a true orphan
# fragment (an ordinary-prose tail with no bibliographic apparatus at all)
# must not. A genuine bibliography or index page is overwhelmingly composed
# of entry-shaped lines once page headers/footers and blank lines are
# filtered out (density well above half in practice); an ordinary prose
# tail that merely cites a source in passing produces close to none. 0.3
# is set well below the former and well above the latter, leaving margin on
# both sides for the kind of extraction noise (stray headers, partial
# entries, OCR line-breaks) real back-matter pages carry, in the same
# wide-margin spirit as `cover_floor`'s own tuning.
BACKMATTER_ENTRY_DENSITY = 0.3

_CONTENTS_HEADINGS = frozenset({"contents", "table of contents"})

# An entry-shaped contents-page line: title text, then a leader (a dot-leader
# run of 2+ periods, or a run of 3+ spaces -- either separates title from
# page number in a printed TOC), then a trailing whole number and nothing
# else. Deliberately strict: an ordinary prose line -- single-spaced words,
# no dot leader, even one ending in a bare number like a year -- never
# matches, because there is no leader run anywhere in it for the regex to
# anchor on (§7.11: "matched strictly enough that prose lines and bare years
# are not read as entries").
_TOC_ENTRY_LINE_RE = re.compile(r"^(?P<title>\S.*?)(?:\.{2,}|\s{3,})\s*(?P<number>\d+)$")

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


def _extract_entry_reference(line: str) -> int | None:
    """The trailing whole number on an entry-shaped contents-page `line`
    (title text, a dot-leader or wide-space run, then the number), or
    `None` when `line` does not match that shape -- an ordinary prose line,
    a bare year with no leader, or a garbled/non-numeric trailing token
    (§7.11)."""
    match = _TOC_ENTRY_LINE_RE.match(line.strip())
    if match is None:
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


def _is_backmatter_entry_line(line: str) -> bool:
    """True when `line` is shaped like a bibliography/reference-list entry
    (an inverted author name, e.g. "Bayat, A. ...") or an index entry (a
    term followed by a page-number list). Content-based, never a heading
    match (§7.11)."""
    stripped = line.strip()
    if not stripped:
        return False
    if _INVERTED_AUTHOR_NAME_RE.search(stripped):
        return True
    return bool(_INDEX_ENTRY_LINE_RE.match(stripped))


def _backmatter_density(page_texts: list[str]) -> float:
    """The measured density (§7.11) of bibliography/index-entry-shaped
    lines across the tail window: the last `TAIL_WINDOW_FRACTION` of
    `page_texts` by physical page count (at least one page). `0.0` when the
    window carries no non-blank lines at all."""
    physical_pages = len(page_texts)
    window_size = max(1, round(physical_pages * TAIL_WINDOW_FRACTION))
    window_pages = page_texts[-window_size:]
    lines = [line for page_text in window_pages for line in page_text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    matches = sum(1 for line in lines if _is_backmatter_entry_line(line))
    return matches / len(lines)


def _holdings_completeness_probe(page_texts: list[str]) -> dict | None:
    """Run the deterministic holdings-completeness probe (§7.11, §8 P0-1b)
    over `page_texts` (one raw text-layer string per physical page, in
    reading order). Signal A runs first; only a source on which it returns
    no reading falls through to Signal B. Returns the fired flag dict, or
    `None` when neither signal fires."""
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


class IntakeError(Exception):
    """Base class for all intake errors."""


class UnsupportedExtensionError(IntakeError):
    """Raised when a file's extension is not among SUPPORTED_EXTENSIONS."""

    def __init__(self, path: Path):
        self.path = path
        self.extension = path.suffix
        super().__init__(
            f"unsupported file extension {self.extension!r} for {path}; "
            f"expected one of {sorted(SUPPORTED_EXTENSIONS)}"
        )


class MissingSourceFileError(IntakeError):
    """Raised when the input path does not exist or is not a file."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"missing or unreadable source file: {path}")


class NoTextLayerError(IntakeError):
    """Raised when a source has no extractable text layer."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no text layer found in {path}; scanned/image-only sources are rejected "
            "(no OCR path in this slice)"
        )


@dataclass
class Source:
    """Source-metadata stub returned on successful intake.

    `holdings_flag` (§7.11, §8 P0-1b) is populated for every accepted PDF
    source by the deterministic holdings-completeness probe: `None` when
    neither signal fires, otherwise a dict naming which signal fired
    (`"toc_page_extent"` or `"orphan_fragment"`) and carrying the measured
    value that fired it plus the threshold in force. Never computed for a
    DOCX source (no computable physical page count). Flag-only: a fired
    flag never blocks intake or alters anything else on this object.
    """

    path: Path
    format: str
    text_layer_ok: bool
    holdings_flag: dict | None = None


def check_extension(path: Path) -> str:
    """Validate `path`'s extension and return the detected format ('pdf'/'docx')."""
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedExtensionError(path)
    return extension.lstrip(".")


def _pdf_page_texts(path: Path) -> list[str]:
    """One raw text-layer string per physical page of `path`, in reading
    order -- the per-page granularity the holdings-completeness probe needs
    (§7.11) and that a single concatenated string discards."""
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def _extract_pdf_text(path: Path) -> str:
    return "".join(_pdf_page_texts(path))


def _extract_docx_text(path: Path) -> str:
    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text_layer(path: Path, fmt: str) -> str:
    """Extract `path`'s raw text layer (`fmt`: 'pdf' or 'docx'). Shared by
    `has_text_layer`'s presence check and by any downstream bounded text
    probe that needs actual text content, not just a boolean -- e.g.
    `axial.drive`'s English-only language-gate probe (issue #239, P0-11c),
    which reuses this rather than reimplementing pdf/docx text extraction."""
    if fmt == "pdf":
        return _extract_pdf_text(path)
    if fmt == "docx":
        return _extract_docx_text(path)
    raise ValueError(f"unknown format {fmt!r}")  # pragma: no cover - guarded by check_extension


def has_text_layer(path: Path, fmt: str) -> bool:
    """Probe `path` (of detected format `fmt`, 'pdf' or 'docx') for real body text."""
    return bool(extract_text_layer(path, fmt).strip())


def intake(path: str | Path) -> Source:
    """Run intake on `path`: validate extension, verify a text layer, run
    the holdings-completeness probe (PDF only, §7.11/§8 P0-1b), and return
    metadata. A fired probe signal is flag-only -- it never raises, never
    rejects, and the source still completes intake exactly as an unflagged
    one would."""
    path = Path(path)

    if not path.is_file():
        raise MissingSourceFileError(path)

    fmt = check_extension(path)

    if fmt == "pdf":
        page_texts = _pdf_page_texts(path)
        if not "".join(page_texts).strip():
            raise NoTextLayerError(path)
        holdings_flag = _holdings_completeness_probe(page_texts)
    else:
        if not has_text_layer(path, fmt):
            raise NoTextLayerError(path)
        holdings_flag = None

    return Source(path=path, format=fmt, text_layer_ok=True, holdings_flag=holdings_flag)
