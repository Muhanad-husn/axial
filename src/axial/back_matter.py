"""Front/back-matter section classification, promoted to one shared home
(issue #661) from where it used to live split across two modules:
`axial.chunk`'s narrow vocabulary and `axial.gold`'s broader one.

**Two rules, deliberately kept as two, because they answer different
questions about the same section heading:**

- `is_chunk_pass_back_matter` (issue #113): governs whether a section is
  chunked and written as a vault note AT ALL. Conservative and exact-match
  only -- a false EXCLUDE here loses real content permanently, so anything
  merely similar to back matter (an appendix, an endnotes section, a
  preface) is deliberately KEPT.
- `is_evidence_back_matter` (issues #53, #113, #131, #134, #204): governs
  whether an already-written, already-interrogated note is citable
  EVIDENCE -- retrievable, assemblable, groundable for a claim -- never
  whether it gets written or interrogated in the first place. Broader on
  purpose: it also excludes endnotes, prefaces, acknowledgments and
  appendices, which the chunk-pass rule keeps. A false EXCLUDE here only
  costs a citable passage; a false INCLUDE grounds a claim on an
  acknowledgments page or a bibliography (issue #661's own defect).

Both rules are pure string classification over a section's own heading --
no vault read, no model call."""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# `is_chunk_pass_back_matter` (issue #113): the chunk-pass vocabulary.
# ---------------------------------------------------------------------------

# Clear non-content back-matter / boilerplate section titles that must never
# be chunked or written as vault notes (issue #113). Conservative + exact:
# only unambiguous titles match after normalization; endnotes ("Notes"),
# appendix, preface, and anything ambiguous are KEPT. OCR-mangled titles
# (e.g. tilly's index came through as the garbled section "lad ex") won't
# match here -- that residual is backstopped by the xref input guard (#111).
CHUNK_PASS_BACK_MATTER_TITLES = frozenset(
    {
        "index",
        "general index",
        "subject index",
        "name index",
        "author index",
        "index of names",
        "bibliography",
        "select bibliography",
        "references",
        "reference list",
        "works cited",
        "cited works",
        "table of contents",
        "contents",
        "copyright",
        "list of figures",
        "list of tables",
        "list of illustrations",
        "list of maps",
        "list of abbreviations",
    }
)


def _normalize_title(title: str) -> str:
    """Lowercase, collapse whitespace, strip surrounding punctuation -- the
    normalization both classifiers below share (issue #113)."""
    return re.sub(r"\s+", " ", (title or "").lower()).strip(" .:-–—")


def is_chunk_pass_back_matter(title: str) -> bool:
    """True if `title` is a clear non-content back-matter/boilerplate section
    (issue #113): an exact match, after normalization, against
    `CHUNK_PASS_BACK_MATTER_TITLES`. Conservative by design -- a title that
    is merely similar (an appendix, an endnotes section, a chapter) is KEPT,
    since a false keep is cheap while a false drop loses real content."""
    return _normalize_title(title) in CHUNK_PASS_BACK_MATTER_TITLES


# ---------------------------------------------------------------------------
# `is_evidence_back_matter` (issues #53, #113, #131, #134, #204): the
# broader gold-frame rule, also used as the evidence-retrieval filter
# (issue #661).
# ---------------------------------------------------------------------------

# Non-substantive front/back-matter titles excluded from citable evidence,
# on top of the chunk-pass vocabulary (`CHUNK_PASS_BACK_MATTER_TITLES`,
# issue #113). #53 excludes a BROADER set than the chunk filter: the chunk
# filter deliberately keeps endnotes/appendix/preface (a false drop there
# loses real content before chunking), but this frame excludes them -- they
# are not substantive argument to be labeled, retrieved or cited.
EVIDENCE_EXTRA_BACK_MATTER = frozenset(
    {
        "notes",
        "endnotes",
        "end notes",
        "footnotes",
        "notes and references",
        "preface",
        "foreword",
        "acknowledgements",
        "acknowledgments",
        "dedication",
        "epigraph",
        "about the author",
        "about the authors",
        "notes on contributors",
        "glossary",
        "abbreviations",
        "chronology",
        "front matter",
        "back matter",
        "title page",
        "half title",
        "contributors",
    }
)

# Vocabulary-specific suffix words (#204): a title where a qualifier PRECEDES
# a bare back-matter vocab term ("Selected Bibliography", "General Secondary
# Sources") is still back-matter even though it fails the exact/prefix rules
# above. Deliberately narrow -- these two terms are specific enough that an
# `endswith` match never catches an ordinary chapter title ("1984 Reforms"
# does not end in either), and matching on the suffix alone (rather than
# requiring the page/roman-numeral prefix to be stripped first) already
# covers the page-number-prefixed case ("3 General Secondary Sources") since
# a leading digit token cannot affect a suffix comparison.
EVIDENCE_BACK_MATTER_SUFFIX_WORDS = (
    "bibliography",
    "secondary sources",
)

_ROMAN_NUMERAL_PREFIX = re.compile(r"^[ivxlcdm]+\.?\s+")

# A leading, purely-numeric page-number token ("154 Notes", "12 Bibliography")
# -- issue #134 gap 1. Stripped before the vocabulary check so page-stamped
# back-matter titles match the same way their bare form does; deliberately
# narrow (digits only, no letters) so an ordinary title that merely starts
# with a year or number ("1984 Reforms") is untouched once its remainder
# fails the vocabulary check.
_PAGE_NUMBER_PREFIX = re.compile(r"^\d+\s+")

# References-family words: when a title's leading roman-numeral ordinal is
# stripped (e.g. "V. Articles and Periodicals" -> "articles and periodicals"),
# the remainder is back-matter only if it names a references/bibliography
# subsection. Deliberately narrow -- an ordinary chapter title that happens to
# start with a roman numeral ("I. The Origins of the State") must NOT match.
_ROMAN_PREFIXED_BACK_MATTER_WORDS = (
    "bibliography",
    "references",
    "articles and periodicals",
    "books",
    "books and articles",
    "primary sources",
    "secondary sources",
    "unpublished sources",
    "archival sources",
    "newspapers and periodicals",
)


def is_evidence_back_matter(section: str) -> bool:
    """True if `section` is non-substantive front/back-matter that must be
    excluded from citable evidence -- the gold sampling frame (#53, #131)
    and, since issue #661, the retrieval/evidence-assembly layer. Reuses the
    chunk-pass vocabulary (`CHUNK_PASS_BACK_MATTER_TITLES`) and broadens it
    with the evidence-frame extras plus:
      - an `appendix`/`annex` prefix match (`Appendix A`, `Annex I`);
      - a `notes to page(s) ...` / `note to page ...` prefix match (endnote
        sections titled with a page range, issue #131 false-negative 1);
      - a roman-numeral-ordinal-prefixed references/bibliography subsection
        (`V. Articles and Periodicals`, issue #131 false-negative 2) -- the
        ordinal is stripped and the remainder checked against a narrow
        references-family vocabulary, so an ordinary chapter title that
        merely starts with a roman numeral is never dropped;
      - a leading page-number token before an otherwise-recognized
        back-matter title (`154 Notes`, issue #134 gap 1) -- the numeric
        token is stripped and the remainder re-run through this same
        function, so a title that merely starts with a number but isn't
        otherwise back-matter (`1984 Reforms`) is never dropped;
      - a qualifier preceding a bare references/bibliography vocab term
        (`Selected Bibliography`, `3 General Secondary Sources`, issue #204)
        -- the normalized title's SUFFIX is checked against a narrow
        references-family word list, so ordinary chapter titles are
        untouched while page-prefixed or qualified bibliography/secondary-
        sources sections are still caught."""
    normalized = _normalize_title(section)
    if normalized in CHUNK_PASS_BACK_MATTER_TITLES or normalized in EVIDENCE_EXTRA_BACK_MATTER:
        return True
    if normalized.startswith("appendix") or normalized.startswith("annex"):
        return True
    if normalized.startswith("notes to page") or normalized.startswith("note to page"):
        return True
    stripped = _ROMAN_NUMERAL_PREFIX.sub("", normalized, count=1)
    if stripped != normalized and stripped in _ROMAN_PREFIXED_BACK_MATTER_WORDS:
        return True
    if any(normalized.endswith(word) for word in EVIDENCE_BACK_MATTER_SUFFIX_WORDS):
        return True
    page_stripped = _PAGE_NUMBER_PREFIX.sub("", normalized, count=1)
    if page_stripped != normalized and is_evidence_back_matter(page_stripped):
        return True
    return False
