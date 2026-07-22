"""ISBN/DOI capture and checksum validation (PRD §7.12/§7.13, issue #326).

Pure, no network, no I/O -- this module only reads text already extracted by
`axial.intake` (`_pdf_page_texts`) and returns the checksum-valid identifiers
it finds. It ports the exploration spike's already-measured regex/checksum
logic unchanged (`plans/book-metadata-open-library/spike/phase0_scan.py`,
`FINDINGS.md`: 93% coverage, 100% resolution over the real 30-source corpus)
rather than reinventing it.

Capture is deliberately generous -- a labelled ISBN line, a bare EAN-13 run,
a DOI shape -- and the check digit is the precision filter: a mistyped or
corrupted identifier is dropped, never returned as if valid. An all-same-
digit placeholder (`0-000-00000-0`) passes the checksum arithmetic but is
never a real ISBN -- a copyright-page fill-in -- and is rejected too.

**Ambiguous capture abstains (founder decision, post-review of #326).** A
multi-volume work's front matter routinely lists several of its own
edition's/series' ISBNs in one "also available" block -- measured on the
real corpus, `mann-sources-of-social-power-v1`/`v3`/`v4` all carry the
*identical* ISBN `9781107028654` alongside their own volume-specific one.
An author-overlap guard cannot separate same-author volumes by author, so
when more than one distinct checksum-valid identifier of the winning type
is found, `capture()` abstains rather than guessing one: no lookup is
attempted for that source, and the candidates are kept for audit only. See
`capture()`'s own docstring for the exact shape.
"""

from __future__ import annotations

import re
from typing import Any

# --- Identifier capture -----------------------------------------------------
# Capture generously, then let the check digit be the precision filter.

# ISBN: the word "isbn" (optional 10/13) then a hyphen/space-broken digit run.
# Tolerant of extraction noise -- spacing, a mid-identifier line break.
_ISBN_LABELLED_RE = re.compile(
    r"isbn(?:\s*-?\s*1[03])?\s*[:\s]\s*([0-9][0-9Xx \-‐–\n]{8,20}[0-9Xx])",
    re.IGNORECASE,
)
# Bare EAN-13 book ISBN (978/979 prefix) even with no "isbn" word nearby.
_ISBN_BARE13_RE = re.compile(r"\b(97[89][0-9 \-‐–\n]{9,18}[0-9])\b")

# DOI: the standard 10.<registrant>/<suffix> shape.
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", re.IGNORECASE)
_DOI_TRAILING_JUNK = ".,;:)]}>\"'"


def _normalise_isbn(raw: str) -> str:
    return re.sub(r"[^0-9Xx]", "", raw).upper()


def _is_placeholder(digits_only: str) -> bool:
    """All-same-digit runs (e.g. `0000000000`) pass the checksum but are
    never a real ISBN -- a copyright-page fill-in. Drop them; a lookup would
    404 anyway."""
    digits = [c for c in digits_only if c.isdigit()]
    return len(set(digits)) <= 1


def valid_isbn10(s: str) -> bool:
    """True when `s` is a 10-character digit run (optionally ending in `X`)
    whose ISBN-10 check digit is correct."""
    if len(s) != 10:
        return False
    total = 0
    for i, ch in enumerate(s):
        if ch == "X":
            if i != 9:
                return False
            v = 10
        elif ch.isdigit():
            v = int(ch)
        else:
            return False
        total += (10 - i) * v
    return total % 11 == 0


def valid_isbn13(s: str) -> bool:
    """True when `s` is a 13-digit run whose ISBN-13 (EAN) check digit is
    correct."""
    if len(s) != 13 or not s.isdigit():
        return False
    total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(s))
    return total % 10 == 0


def find_isbns(text: str) -> set[str]:
    """Every checksum-valid ISBN-10/ISBN-13 in `text`, normalized to a bare
    digit (+`X`) string with no hyphens/spaces. A corrupted check digit or an
    all-same-digit placeholder is dropped, not returned."""
    found: set[str] = set()
    for m in _ISBN_LABELLED_RE.finditer(text):
        n = _normalise_isbn(m.group(1))
        if (valid_isbn13(n) or valid_isbn10(n)) and not _is_placeholder(n):
            found.add(n)
    for m in _ISBN_BARE13_RE.finditer(text):
        n = _normalise_isbn(m.group(1))
        if valid_isbn13(n) and not _is_placeholder(n):
            found.add(n)
    return found


def find_dois(text: str) -> set[str]:
    """Every syntactically valid DOI in `text`, trailing sentence punctuation
    stripped, lower-cased (DOI resolution is case-insensitive)."""
    found: set[str] = set()
    for m in _DOI_RE.finditer(text):
        doi = m.group(1).rstrip(_DOI_TRAILING_JUNK)
        if "/" in doi[3:]:  # a suffix after the "10.xxxx/" prefix
            found.add(doi.lower())
    return found


def capture(text: str) -> dict[str, Any] | None:
    """The identifier this slice's merge step reads, in one of three shapes:

    - `None` -- `text` carries neither an ISBN nor a DOI;
    - `{"type": "isbn"|"doi", "value": <normalized>}` -- exactly one distinct
      identifier of the winning type was found;
    - `{"type": "isbn"|"doi", "value": None, "abstained": True, "candidates":
      [...]}` -- **more than one distinct identifier of the winning type was
      found**, e.g. a multi-volume work's copyright page listing an "also
      available in this series" block of several ISBNs. There is no
      principled way to pick a winner among several genuinely different
      identifiers, so the caller must not use any of them for a lookup;
      `candidates` (sorted, for determinism) is kept for audit, mirroring
      the vote-abstention shape §7.14 already uses for "the draws disagree,
      not a value" (`{primary: null, abstained: true, draws: [...]}`) rather
      than inventing a new sentinel vocabulary.

    An ISBN wins over a DOI when both are present (the spike's own
    precedence -- Open Library resolves against a metadata-richer record
    than Crossref's works endpoint); this precedence applies even when the
    ISBNs found are ambiguous -- a confusing ISBN block does not fall
    through to a DOI found elsewhere on the same page."""
    isbns = sorted(find_isbns(text))
    if len(isbns) > 1:
        return {"type": "isbn", "value": None, "abstained": True, "candidates": isbns}
    if isbns:
        return {"type": "isbn", "value": isbns[0]}
    dois = sorted(find_dois(text))
    if len(dois) > 1:
        return {"type": "doi", "value": None, "abstained": True, "candidates": dois}
    if dois:
        return {"type": "doi", "value": dois[0]}
    return None
