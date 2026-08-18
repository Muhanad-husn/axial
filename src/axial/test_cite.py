"""How a citation reads on a page (`axial.cite`, issue #783/#786).

One formatter, two forms, and one rule that matters more than either: a
ground that did not resolve renders its raw pointer rather than vanishing.
"""

from __future__ import annotations

from axial.cite import (
    SHORT,
    author_surname,
    citation_summary,
    clean_author,
    format_bibliography_entry,
    format_citation,
)

_VIGNAL = {
    "source_id": "vignal-2021-c7005c2bf8ef",
    "author": "Leila Vignal ;",
    "title": "War-Torn",
    "date": "2021",
    "chapter": "ANATOMY OF A CONFLICT FROM REVOLUTION TO WAR",
    "section": "Fragmenting space and society",
}


def test_the_full_form_names_the_author_the_year_and_the_locator():
    assert format_citation(_VIGNAL) == (
        "Leila Vignal (2021), ANATOMY OF A CONFLICT FROM REVOLUTION TO WAR, "
        "Fragmenting space and society"
    )


def test_the_short_form_is_the_surname_and_the_year_only():
    """An in-text citation names the book, not the passage: the store's
    `chapter` is a full heading, and a heading inside a parenthesis
    mid-sentence is not a citation a reader can use. APA puts a comma
    between the two."""
    assert format_citation(_VIGNAL, form=SHORT) == "Vignal, 2021"


def test_a_trailing_separator_and_a_role_suffix_are_stripped_for_display():
    assert clean_author("Leila Vignal ;") == "Leila Vignal"
    assert clean_author("Kristen Kao (Editor)") == "Kristen Kao"
    assert author_surname("Beshara, Adel;") == "Beshara"
    assert author_surname("Uğur Ümit Üngör") == "Üngör"


def test_a_citation_with_no_author_falls_back_to_its_source_id():
    citation = {"source_id": "tilly-1978", "author": None, "date": None}
    assert format_citation(citation) == "tilly-1978"


def test_a_citation_block_that_is_not_one_renders_nothing():
    assert format_citation(None) is None
    assert format_citation({}) is None


def test_an_unresolved_ground_renders_its_raw_pointer():
    """#786's own bar: an unresolvable citation reads as unresolvable, never
    as absent."""
    grounds = [{"ref_type": "chunk", "ref_id": "alpha-1999_1_intro_001"}]
    assert citation_summary(grounds) == "chunk:alpha-1999_1_intro_001"


def test_two_passages_from_one_book_are_one_in_text_citation():
    grounds = [
        {"ref_type": "chunk", "ref_id": "a", "citation": _VIGNAL},
        {"ref_type": "chunk", "ref_id": "b", "citation": dict(_VIGNAL, section="Conclusion")},
    ]
    assert citation_summary(grounds, form=SHORT) == "Vignal, 2021"


def test_empty_grounds_say_so_rather_than_rendering_blank():
    assert citation_summary([]) == "no supporting passage"


def test_a_bibliography_entry_carries_no_provenance_tag():
    entry = {
        "source_id": "vignal-2021-c7005c2bf8ef",
        "author": {"value": "Leila Vignal ;", "provenance": "embedded metadata"},
        "title": {"value": "War-Torn", "provenance": "embedded metadata"},
        "date": {"value": "2021", "provenance": "title page"},
        "publisher": {"value": "C. Hurst and Company", "provenance": "open_library"},
    }
    assert format_bibliography_entry(entry) == (
        "Vignal, L. (2021). *War-Torn*. C. Hurst and Company."
    )


def test_a_bibliography_entry_omits_what_did_not_resolve():
    """A resolved author with everything else absent still names its own
    absent date `(n.d.)` -- APA's word for it, not an omission (issue
    #787)."""
    entry = {
        "source_id": "tilly-1978-aaaa",
        "author": {"value": "Charles Tilly", "provenance": "title page"},
        "title": {"absent": "unavailable"},
        "date": {"absent": "not_attempted"},
        "publisher": {"absent": "unavailable"},
    }
    assert format_bibliography_entry(entry) == "Tilly, C. (n.d.)."


def test_an_all_caps_author_is_cased_but_a_mixed_case_one_is_untouched():
    """Some sources record `STATHIS N. KALYVAS`; `(KALYVAS 2006)` shouts at
    a reader mid-sentence. A name carrying any lowercase letter is left
    exactly as the source recorded it."""
    assert clean_author("STATHIS N. KALYVAS") == "Stathis N. Kalyvas"
    assert clean_author("Uğur Ümit Üngör") == "Uğur Ümit Üngör"
