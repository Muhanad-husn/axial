"""APA in-text citations and bibliography (`axial.cite`, issue #787 slice 03).

The house style is APA, applied everywhere the reader-facing render cites a
source. The one real risk is inverting a full name to `Surname, F. M.` --
`apa_author` picks the surname the same way `author_surname` already does
(the text before a comma, or the last whitespace token), so it never needs
to fold a diacritic to decide where the surname is; only a string naming
more than one person is genuinely unresolvable, and that prints as given
rather than guessed at.
"""

from __future__ import annotations

from axial.cite import SHORT, apa_author, format_bibliography_entry, format_citation


def test_in_text_short_form_puts_a_comma_before_the_year():
    citation = {"source_id": "bayat-2017", "author": "Asef Bayat", "date": "2017"}
    assert format_citation(citation, form=SHORT) == "Bayat, 2017"


def test_in_text_short_form_with_no_resolved_date_reads_n_d():
    citation = {"source_id": "bayat-2017", "author": "Asef Bayat", "date": None}
    assert format_citation(citation, form=SHORT) == "Bayat, n.d."


def test_natural_order_and_inverted_order_invert_to_the_same_string():
    assert apa_author("Michael Mann") == "Mann, M."
    assert apa_author("Mann, Michael") == "Mann, M."


def test_a_diacritic_survives_inversion_in_either_metadata_order():
    """`Siniša Malešević` -- the surname is picked by its position (the last
    whitespace token, exactly as `author_surname` already does), never by
    folding the string, so the printed surname keeps its diacritic."""
    assert apa_author("Siniša Malešević") == "Malešević, S."
    assert apa_author("Malešević, Siniša") == "Malešević, S."


def test_a_two_person_string_prints_as_given_rather_than_guessed_at():
    """`John A. Hall and Ralph Schroeder` (measured: 3 of 35 real
    `data/source_meta/` records join two people this way) has no single
    surname to invert to. `biblio.py`'s never-guess rule: print it exactly
    as the record carries it."""
    assert apa_author("John A. Hall and Ralph Schroeder") == "John A. Hall and Ralph Schroeder"


def test_all_caps_and_role_and_trailing_punctuation_are_still_cleaned_first():
    assert apa_author("STATHIS N. KALYVAS") == "Kalyvas, S. N."
    assert apa_author("Kristen Kao (Editor)") == "Kao, K."
    assert apa_author("Leila Vignal ;") == "Vignal, L."
    assert apa_author("Ayubi, Nazih N.;") == "Ayubi, N. N."


def test_a_trailing_period_after_a_full_given_name_does_not_break_the_initial():
    """`White, Benjamin Thomas.` -- a real record whose trailing period ends
    the whole name, not an initial. The initial is still just the first
    letter of the token, so the stray period costs nothing."""
    assert apa_author("White, Benjamin Thomas.") == "White, B. T."


def test_a_single_bare_name_has_no_surname_to_invert():
    assert apa_author("Voltaire") == "Voltaire"


def _entry(**fields):
    entry = {"source_id": "vignal-2021-c7005c2bf8ef"}
    for field, value in fields.items():
        entry[field] = {"value": value, "provenance": "embedded metadata"} if value else {"absent": "unavailable"}
    return entry


def test_a_fully_resolved_entry_reads_surname_initials_year_title_publisher():
    entry = _entry(
        author="Leila Vignal ;",
        title="War-Torn",
        date="2021",
        publisher="C. Hurst and Company",
    )
    assert format_bibliography_entry(entry) == (
        "Vignal, L. (2021). *War-Torn*. C. Hurst and Company."
    )


def test_a_two_person_author_is_not_inverted_in_the_bibliography_either():
    entry = _entry(
        author="John A. Hall and Ralph Schroeder",
        title="The Anatomy of Power",
        date="2006",
        publisher="Cambridge University Press",
    )
    assert format_bibliography_entry(entry) == (
        "John A. Hall and Ralph Schroeder. (2006). *The Anatomy of Power*. "
        "Cambridge University Press."
    )


def test_an_absent_date_renders_n_d_rather_than_a_blank_or_an_omission():
    entry = _entry(author="Charles Tilly", title=None, date=None, publisher=None)
    assert format_bibliography_entry(entry) == "Tilly, C. (n.d.)."


def test_an_absent_author_falls_back_without_inventing_one():
    entry = _entry(author=None, title="Some Title", date="2020", publisher=None)
    rendered = format_bibliography_entry(entry)
    assert "*Some Title*" in rendered
    assert "(2020)" in rendered
    # No author printed, and nothing invented in its place.
    assert not rendered.startswith("*")
    assert rendered == "(2020). *Some Title*."


def test_an_entry_resolving_nothing_at_all_falls_back_to_the_source_id():
    entry = {"source_id": "tilly-1978-aaaa"}
    for field in ("author", "title", "date", "publisher"):
        entry[field] = {"absent": "not_attempted"}
    assert format_bibliography_entry(entry) == "tilly-1978-aaaa"
