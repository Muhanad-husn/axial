"""Merge on exact equality after normalization -- nothing else.

The family has no thresholds and no scores. Every resolver here folds each
surface form to a normal form and groups the members that land on the same
one, so merging is transitive within a cluster by construction. The rungs
differ only in how much of a surface form the normal form is allowed to
forget, from case and whitespace up to the citation apparatus that dominates
this corpus (`Barnard` / `Barnard (2003)`).

The citation rungs are the point of the family, and none of them is "strip the
year". Naive year-stripping fuses `O'Rourke & Williamson, 1999` with `O'Rourke
& Williamson, 2002` -- different works by the same authors, the exact failure
PR #441 rejected `reasoning: false` for. So the year is extracted *apart* from
the stem and then has to agree. Two ways of saying "agree" are built here,
because the corpus settles between them:

  * `citation` treats an absent year as compatible with a present one, and
    only refuses when a stem carries two different years. This is the reading
    the pass's own examples suggest -- `Barnard` really did fold into
    `Barnard (2003)`.
  * `citation_strict` requires the year sets to be equal, so a bare surname
    never joins a dated work.

The second wins, and not by a little: over the whole log, a bare stem next to
a dated one is merged 1,019 times and refused 1,722 times -- a coin flip
leaning against, and moving it costs 18 points of pair precision to buy 6 of
recall. Two forms of the SAME dated work (`Joshi (2002)` / `Joshi 2002`) merge
86% of the time, and two undated forms of one stem 82%; the ambiguity lives
entirely in the bare-against-dated case, so that is the one edge the strict
rule declines to draw.

Two smaller findings the code encodes rather than argues:

  * `et al.` stays in the stem. It is not apparatus, it is part of the author
    list: `Bordo` and `Bordo et al.` are different bylines, and the log says
    so. Stripping it costs precision.
  * Case is never folded above rung 1. The live pass merged a pure case
    variant ZERO times in 18,873 clusters and split one 1,568 times, which is
    not a judgment: in 1,442 of those clusters the model answered with only
    one of the two spellings -- it deduplicated them as the same string -- and
    the harness's closure rule turned the surface it never mentioned into a
    singleton. Against this gold, casefolding is therefore pure precision
    loss, and rung 1 measures exactly that.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from unidecode import unidecode

from experiments.mechanical_merge.harness import Partition

# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def _group(members: tuple[str, ...], key_of) -> Partition:
    """Partition `members` by normal form. A form that normalizes to nothing
    keeps its raw string as its key, so an all-punctuation surface never drags
    every other empty one into a block with it."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for member in members:
        buckets[key_of(member) or f"\0{member}"].append(member)
    return frozenset(frozenset(block) for block in buckets.values())


# ---------------------------------------------------------------------------
# Normalization steps, each the increment one rung adds
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")
_AMPERSAND = re.compile(r"\s*&\s*")
_PUNCTUATION = re.compile(r"[^\w\s]+")

# Every unicode dash and every unicode apostrophe this corpus can carry, onto
# the ascii one. Kept explicit rather than derived from a unicode category
# because `-` and `'` are the only characters whose variants ever mean the
# same thing inside a name.
_TYPOGRAPHY = str.maketrans(
    {ch: "-" for ch in "‐‑‒–—―−"} | {ch: "'" for ch in "‘’ʻʼʿ`´′"} | {ch: '"' for ch in "“”″"}
)

_QUOTE_PAIRS = {'"': '"', "'": "'", "«": "»"}


def _collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _unquote(text: str) -> str:
    """Drop matched quotes around the whole form, however many layers deep.
    Titles in this inventory arrive both bare and quoted, sometimes twice."""
    while len(text) > 1 and _QUOTE_PAIRS.get(text[0]) == text[-1]:
        text = text[1:-1].strip()
    return text


def _punctuation_and_quotes(text: str) -> str:
    """Unicode punctuation onto ascii, wrapping quotes off, `&` for `and`."""
    text = _unquote(_collapse(unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY)))
    return _collapse(_AMPERSAND.sub(" and ", text))


def _typography(text: str) -> str:
    return _punctuation_and_quotes(text).casefold()


def _ascii(text: str) -> str:
    return _typography(unidecode(text))


def _depunctuated(text: str) -> str:
    return _collapse(_PUNCTUATION.sub(" ", _ascii(text)))


def _alphanumeric(text: str) -> str:
    """Also blind to where the spaces and hyphens fall: `Phelps-Brown`,
    `Phelps Brown` and `PhelpsBrown` are one form."""
    return _WHITESPACE.sub("", _depunctuated(text))


def _alphanumeric_cased(text: str) -> str:
    """`_alphanumeric` with the capitalization left standing."""
    folded = _punctuation_and_quotes(unidecode(text))
    return _WHITESPACE.sub("", _PUNCTUATION.sub(" ", folded))


# ---------------------------------------------------------------------------
# Citation apparatus
# ---------------------------------------------------------------------------

_YEAR = r"(?:1[0-9]{3}|20[0-9]{2})[a-z]?"
_LOCATOR = r"[0-9]+(?:\s*[-–]\s*[0-9]+)?|[ivxlc]+"

# One trailing citation token. Applied from the right, repeatedly: the tail of
# `Rodgers, 1998: chaps. 6, 7` comes off in three bites. Only ever a SUFFIX --
# a year inside the name itself (`1992-1995 Bosnian war`, `railroad strike of
# 1877`) is part of what is being named and is never touched.
_TAIL = re.compile(
    r"(?:"
    rf"[\s.,;:]*[(\[]\s*{_YEAR}(?:\s*[,;/&\-–]\s*{_YEAR})*\s*[)\]]"
    rf"|[\s.,;:]+{_YEAR}(?:\s*[,;/&\-–]\s*{_YEAR})*"
    r"|[\s.,;:]*\b(?:ibid|n\.d|forthcoming)\.?"
    rf"|[\s,;:]*\b(?:pp?|chaps?|vols?)\.?\s*(?:{_LOCATOR})(?:\s*,\s*(?:{_LOCATOR}))*"
    rf"|\s*:\s*(?:{_LOCATOR})(?:\s*,\s*(?:{_LOCATOR}))*"
    r"|[\s.,;:]+"
    r")$",
    re.IGNORECASE,
)
_YEAR_IN_TAIL = re.compile(_YEAR)
_LOCATOR_IN_TAIL = re.compile(rf"(?::\s*|\b(?:pp?|chaps?|vols?)\.?\s*)({_LOCATOR})", re.IGNORECASE)


@dataclass(frozen=True)
class _Citation:
    """One surface form read as `stem + apparatus`."""

    surface: str
    years: frozenset[str]
    locators: frozenset[str]


def _split_citation(surface: str) -> tuple[str, _Citation]:
    """`(stem, apparatus)`. Years and page locators come only from the tail
    that was stripped, so a name that is *about* a year keeps it in the stem.
    `1959a` and `1959` stay distinct years -- the letter is there precisely to
    tell two works apart."""
    stem, years, locators = surface, [], []
    while True:
        match = _TAIL.search(stem)
        if not match or match.start() == 0:
            break
        tail = match.group(0)
        years.extend(_YEAR_IN_TAIL.findall(tail))
        locators.extend(_LOCATOR_IN_TAIL.findall(tail))
        stem = stem[: match.start()]
    return stem, _Citation(surface, frozenset(years), frozenset(locators) - frozenset(years))


def _by_stem(members: tuple[str, ...], normalize) -> dict[str, list[_Citation]]:
    grouped: dict[str, list[_Citation]] = defaultdict(list)
    for member in members:
        stem, citation = _split_citation(member)
        grouped[normalize(stem) or f"\0{member}"].append(citation)
    return grouped


def _split_by(entries: list[_Citation], field: str, strict: bool) -> list[list[_Citation]]:
    """Divide one block by an apparatus field. `strict` decides what an ABSENT
    value means: its own block, or compatible with the one value present."""
    present = {getattr(entry, field) for entry in entries if getattr(entry, field)}
    if not strict and len(present) <= 1:
        return [entries]
    divided: dict[frozenset[str], list[_Citation]] = defaultdict(list)
    for entry in entries:
        divided[getattr(entry, field)].append(entry)
    return list(divided.values())


def _partition(blocks: list[list[_Citation]]) -> Partition:
    return frozenset(frozenset(entry.surface for entry in block) for block in blocks)


def _citation_partition(members: tuple[str, ...], normalize) -> Partition:
    """Group by stem; a stem carrying two different years splits by year.

    A stem whose members carry at most one year is one block, so `Barnard`
    joins `Barnard (2003)`. A stem carrying two splits one block per year,
    with the undated forms in their own block -- which is what the live pass
    does with `Joshi` / `Joshi (2002)` / `Joshi 2002` / `Joshi 2003` /
    `Joshi 2003:xiii`: two dated blocks, and `Joshi` alone.
    """
    blocks: list[list[_Citation]] = []
    for entries in _by_stem(members, normalize).values():
        blocks.extend(_split_by(entries, "years", strict=False))
    return _partition(blocks)


def _citation_partition_strict(members: tuple[str, ...], normalize) -> Partition:
    """Group by stem AND by year set, always. An undated form is its own
    citation, never a dated one's alias."""
    blocks: list[list[_Citation]] = []
    for entries in _by_stem(members, normalize).values():
        blocks.extend(_split_by(entries, "years", strict=True))
    return _partition(blocks)


def _citation_partition_passage(members: tuple[str, ...], normalize) -> Partition:
    """Strict on the year, compatible on the page locator.

    The two dimensions are not the same question and the log answers them
    differently. A year names the work, so an undated form is a different
    reference: 1,019 merges against 1,722 refusals. A page names a passage
    inside one work, so `Langsam 1930` absorbs `Langsam 1930: 49` -- 128
    merges against 3 refusals -- but `Bix, 2001: 228-41` and `Bix, 2001:
    308-13` are two passages, and the log splits those 23 times to 15.
    """
    blocks: list[list[_Citation]] = []
    for entries in _by_stem(members, normalize).values():
        for by_year in _split_by(entries, "years", strict=True):
            blocks.extend(_split_by(by_year, "locators", strict=False))
    return _partition(blocks)


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def case_and_space(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 1: casefold, collapse whitespace."""
    return _group(members, lambda text: _collapse(text).casefold())


def typography(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 2: + unicode dashes and apostrophes, wrapping quotes, `&`/`and`."""
    return _group(members, _typography)


def ascii_fold(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 3: + strip diacritics."""
    return _group(members, _ascii)


def depunctuated(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 4: + drop all punctuation."""
    return _group(members, _depunctuated)


def alphanumeric(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 5: + ignore where spaces and hyphens fall."""
    return _group(members, _alphanumeric)


def citation(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 6: + citation apparatus, an absent year compatible with a present
    one."""
    return _citation_partition(members, _alphanumeric)


def citation_strict(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 7: the same, with year sets required to be equal."""
    return _citation_partition_strict(members, _alphanumeric)


def citation_cased(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 6 without the casefold, which rung 1 shows is a pure loss here."""
    return _citation_partition(members, _alphanumeric_cased)


def citation_cased_strict(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 7 without the casefold. Everything about a surface form is folded
    except its capitalization and its citation year, and the year has to
    match. The family's recommendation."""
    return _citation_partition_strict(members, _alphanumeric_cased)


def citation_cased_passage(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """Rung 8: `citation_cased_strict`, plus two different page ranges of one
    dated work kept apart. The family's recommendation."""
    return _citation_partition_passage(members, _alphanumeric_cased)


def citation_cased_strict_diacritics(
    members: tuple[str, ...], kinds: dict[str, str | None]
) -> Partition:
    """`citation_cased_strict` with diacritics kept, to price the one fold
    the brief flagged as risky (`Khalifé` and `Khalife` are two people)."""
    return _citation_partition_strict(
        members,
        lambda text: _WHITESPACE.sub("", _PUNCTUATION.sub(" ", _punctuation_and_quotes(text))),
    )
