"""Acceptance test for issue #787 slice 03: the reader-facing paper cites
and lists its sources in APA.

Boundary: the same two render functions the CLI's `axial paper draft`
already writes to disk (`axial.paper.reader.render_reader_paper` for the
markdown a reader gets, `axial.paper.render.render_paper` for the audit
copy) -- no model call anywhere in this slice, so exercising them directly
over a persisted-record shape is the whole integration.

The record mixes exactly the shapes measured across the real 35
`data/source_meta/` records (README's own fixture list): natural order,
already-inverted order, two people in one string, a diacritic, and an
absent date.
"""

from __future__ import annotations

from typing import Any

from axial.paper.reader import render_reader_paper
from axial.paper.render import render_paper

_VIGNAL = {  # natural order
    "source_id": "vignal-2021",
    "author": "Leila Vignal ;",
    "title": "War-Torn",
    "date": "2021",
    "chapter": None,
    "section": "Fragmenting space",
}
_MANN_NATURAL = {  # natural order
    "source_id": "mann-2013",
    "author": "Michael Mann",
    "title": "The Sources of Social Power, Volume 4",
    "date": "2013",
    "chapter": None,
    "section": None,
}
_MANN_INVERTED = {  # the same author, already inverted -- measured: two of
    # Michael Mann's four real records print each way
    "source_id": "mann-2012",
    "author": "Mann, Michael",
    "title": "The Sources of Social Power, Volume 3",
    "date": "2012",
    "chapter": None,
    "section": None,
}
_MALESEVIC = {  # diacritic
    "source_id": "malesevic-2010",
    "author": "Malešević, Siniša",
    "title": "The Sociology of War and Violence",
    "date": "2010",
    "chapter": None,
    "section": None,
}
_HALL_SCHROEDER = {  # two people in one string, no resolved date
    "source_id": "hall-2006",
    "author": "John A. Hall and Ralph Schroeder",
    "title": "An Anatomy of Power",
    "date": None,
    "chapter": None,
    "section": None,
}


def _record() -> dict[str, Any]:
    return {
        "paper_brief_id": "p787",
        "paper_brief": {"thesis": "Did the state precede the war?", "title": None},
        "plan": {
            "thesis_statement": "The state made the war.",
            "sections": [{"section_id": "s1", "heading": "The argument", "role": "body"}],
        },
        "drafts": [
            {
                "section_id": "s1",
                "prose": (
                    "The state made the war [pc-001][pc-002]. Power is infrastructural "
                    "[pc-003]. The corpus disagrees [pc-004]."
                ),
            }
        ],
        "claims": [
            {
                "paper_claim_id": "pc-001",
                "kind": "a",
                "confidence": "high",
                "source_ids": ["vignal-2021"],
                "grounds": [{"ref_type": "chunk", "ref_id": "vignal-2021_1", "citation": _VIGNAL}],
            },
            {
                "paper_claim_id": "pc-002",
                "kind": "a",
                "confidence": "high",
                "source_ids": ["mann-2013"],
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "mann-2013_1", "citation": _MANN_NATURAL}
                ],
            },
            {
                "paper_claim_id": "pc-003",
                "kind": "b",
                "confidence": "medium",
                "source_ids": ["mann-2012"],
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "mann-2012_1", "citation": _MANN_INVERTED}
                ],
            },
            {
                "paper_claim_id": "pc-004",
                "kind": "b",
                "confidence": "low",
                "source_ids": ["hall-2006"],
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "hall-2006_1", "citation": _HALL_SCHROEDER}
                ],
            },
        ],
        "counter_position": {"present": False, "failed": False, "corpus_one_sided": True,
                              "one_sided_reason": "no dissent recorded"},
        "coverage_map": {},
        "confidence": {"overall_band": "medium", "rationale": "because"},
        "shape": {"band": "strong", "defects": [], "title": None},
        "bibliography": [
            {
                "source_id": "vignal-2021",
                "author": {"value": "Leila Vignal ;", "provenance": "embedded metadata"},
                "title": {"value": "War-Torn", "provenance": "embedded metadata"},
                "date": {"value": "2021", "provenance": "title page"},
                "publisher": {"value": "C. Hurst", "provenance": "open_library"},
            },
            {
                "source_id": "mann-2013",
                "author": {"value": "Michael Mann", "provenance": "embedded metadata"},
                "title": {"value": "The Sources of Social Power, Volume 4", "provenance": "embedded metadata"},
                "date": {"value": "2013", "provenance": "title page"},
                "publisher": {"value": "Cambridge University Press", "provenance": "open_library"},
            },
            {
                "source_id": "mann-2012",
                "author": {"value": "Mann, Michael", "provenance": "embedded metadata"},
                "title": {"value": "The Sources of Social Power, Volume 3", "provenance": "embedded metadata"},
                "date": {"value": "2012", "provenance": "title page"},
                "publisher": {"value": "Cambridge University Press", "provenance": "open_library"},
            },
            {
                "source_id": "malesevic-2010",
                "author": {"value": "Malešević, Siniša", "provenance": "embedded metadata"},
                "title": {"value": "The Sociology of War and Violence", "provenance": "embedded metadata"},
                "date": {"value": "2010", "provenance": "title page"},
                "publisher": {"value": "Polity", "provenance": "open_library"},
            },
            {
                "source_id": "hall-2006",
                "author": {"value": "John A. Hall and Ralph Schroeder", "provenance": "embedded metadata"},
                "title": {"value": "An Anatomy of Power", "provenance": "embedded metadata"},
                "date": {"absent": "not_attempted"},
                "publisher": {"value": "Cambridge University Press", "provenance": "open_library"},
            },
        ],
    }


def test_every_in_text_citation_carries_a_comma_before_the_year():
    markdown = render_reader_paper(_record())

    assert "(Vignal, 2021; Mann, 2013)" in markdown
    assert "(Mann, 2012)" in markdown
    # The never-guess fallback is `biblio.py`'s own rule for the
    # bibliography's full name inversion; the in-text short form never
    # inverts anything, so a two-author source still cites its last
    # whitespace token here -- unchanged, out of this slice's scope.
    assert "(Schroeder, n.d.)" in markdown


def test_the_same_author_in_both_metadata_orders_renders_identically():
    markdown = render_reader_paper(_record())

    assert "- Mann, M. (2013). *The Sources of Social Power, Volume 4*. Cambridge University Press." in markdown
    assert "- Mann, M. (2012). *The Sources of Social Power, Volume 3*. Cambridge University Press." in markdown


def test_a_diacritic_survives_bibliography_inversion():
    markdown = render_reader_paper(_record())

    assert "- Malešević, S. (2010). *The Sociology of War and Violence*. Polity." in markdown


def test_a_two_person_string_prints_as_given_in_the_bibliography():
    markdown = render_reader_paper(_record())

    assert (
        "- John A. Hall and Ralph Schroeder. (n.d.). *An Anatomy of Power*. "
        "Cambridge University Press." in markdown
    )


def test_titles_are_italicised_in_the_bibliography():
    markdown = render_reader_paper(_record())

    assert "*War-Torn*" in markdown


def test_the_audit_render_stays_chicago_shaped_and_untouched():
    """The one negative acceptance clause: `render_paper` is an operator
    artifact and APA is a reader convention, so its bibliography line format
    -- the raw field value with its provenance tag, no italics, no name
    inversion -- must not move."""
    record = _record()
    markdown = render_paper(record)

    assert "## Bibliography" in markdown
    assert "author: Leila Vignal ; (from embedded metadata)" in markdown
    assert "*War-Torn*" not in markdown
    assert "(Vignal, 2021" not in markdown
    assert "Vignal, L." not in markdown
