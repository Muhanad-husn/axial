"""Unit tests for the promoted back-matter classifiers (issue #661).

`is_evidence_back_matter`'s full behavior is already pinned exhaustively by
`test_gold.py::TestIsBackMatter` (re-exported as `axial.gold._is_back_matter`,
byte-identical) and `is_chunk_pass_back_matter`'s by the chunking acceptance
tests that exercise `_section_nodes` filtering. This file pins the two
classifiers directly, side by side, so the DIFFERENCE between them --
the reason issue #661 keeps two rules rather than widening one -- has its
own test."""

from __future__ import annotations

import pytest

from axial.back_matter import is_chunk_pass_back_matter, is_evidence_back_matter


@pytest.mark.parametrize(
    "section",
    ["Index", "Bibliography", "References", "Table of Contents", "  BIBLIOGRAPHY.  "],
)
def test_chunk_pass_excludes_the_unambiguous_titles(section):
    assert is_chunk_pass_back_matter(section) is True


@pytest.mark.parametrize(
    "section",
    ["Notes", "Acknowledgments", "Preface", "Appendix A", "Conclusion", "Introduction"],
)
def test_chunk_pass_keeps_everything_merely_similar(section):
    """The chunk pass is deliberately conservative: a false EXCLUDE here
    loses real content before it is ever chunked, so endnotes, prefaces,
    acknowledgments and appendices are all kept -- these are exactly the
    section headings `is_evidence_back_matter` below excludes instead."""
    assert is_chunk_pass_back_matter(section) is False


@pytest.mark.parametrize(
    "section",
    [
        "Notes",
        "Acknowledgments",
        "Acknowledgements",
        "Preface",
        "Appendix A",
        "Bibliography",
        "Index",
    ],
)
def test_evidence_back_matter_is_the_broader_rule(section):
    """Every one of these sits on the chunk-pass's KEEP side -- a note for
    each of them is written and interrogated -- but none of them is citable
    evidence. This is the two-rule design issue #661 states explicitly: a
    false exclude on the chunk pass loses a passage forever, while a false
    exclude here only costs a citable passage the corpus never lost."""
    assert is_evidence_back_matter(section) is True


@pytest.mark.parametrize("section", ["Introduction", "Conclusion", "The Long March"])
def test_evidence_back_matter_keeps_ordinary_argument_sections(section):
    assert is_evidence_back_matter(section) is False


def test_empty_or_missing_section_is_not_back_matter_by_either_rule():
    """A note with no section heading at all is not thereby back matter --
    both classifiers only ever EXCLUDE on a positive match against their own
    vocabulary, never on the absence of a heading."""
    assert is_chunk_pass_back_matter("") is False
    assert is_evidence_back_matter("") is False
