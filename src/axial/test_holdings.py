"""Inner unit tests for the holdings-completeness probe (issue #268 slice 1,
§7.11 / §8 P0-1b) -- beneath the locked outer contract in
tests/ingestion/test_holdings_completeness_probe.py."""

import pytest


def test_is_contents_heading_matches_after_lowercase_and_whitespace_collapse():
    from axial.holdings import _is_contents_heading

    assert _is_contents_heading("Contents") is True
    assert _is_contents_heading("  CONTENTS  ") is True
    assert _is_contents_heading("Table   of    Contents") is True
    assert _is_contents_heading("table of contents") is True


def test_is_contents_heading_rejects_ordinary_prose():
    from axial.holdings import _is_contents_heading

    assert _is_contents_heading("This chapter discusses the contents of the archive.") is False
    assert _is_contents_heading("Chapter One") is False
    assert _is_contents_heading("") is False


def test_extract_entry_reference_reads_trailing_number_past_dot_leader():
    from axial.holdings import _extract_entry_reference

    assert _extract_entry_reference("Chapter One .......... 1") == 1
    assert _extract_entry_reference("Chapter Two .......... 25") == 25
    assert _extract_entry_reference("Index .................................. 11") == 11


def test_extract_entry_reference_rejects_decoy_bare_year_with_no_dot_leader():
    from axial.holdings import _extract_entry_reference

    assert _extract_entry_reference("This edition was substantially revised in 1975") is None


def test_extract_entry_reference_rejects_garbled_trailing_tokens():
    from axial.holdings import _extract_entry_reference

    assert _extract_entry_reference("Chapter One .......................... l0l") is None
    assert _extract_entry_reference("Chapter Two .......................... 4O") is None
    assert _extract_entry_reference("Chapter Three ......................... ??") is None
    assert _extract_entry_reference("Appendix .............................. ~~~") is None


def test_extract_entry_reference_reads_real_pypdf_shaped_entries_no_dot_leader():
    """Dot leaders do not survive real `pypdf` text extraction -- the gap
    collapses to a single space (issue #268 review, F1). Shapes below are
    drawn from the real 30-source corpus (mann-v3, agamben, kalyvas)."""
    from axial.holdings import _extract_entry_reference

    assert (
        _extract_entry_reference("2 Globalization imperially fractured: The British Empire 17")
        == 17
    )
    assert _extract_entry_reference("6 Auctoritas and Potestas 74") == 74
    assert _extract_entry_reference("I.1. Four Puzzles 1") == 1
    assert _extract_entry_reference("Index 505") == 505
    assert _extract_entry_reference("Bibliography 467") == 467


def test_extract_entry_reference_rejects_trailing_stopword_before_number():
    """The single-space shape alone can't tell a real entry from a prose
    sentence that happens to end in a number (the locked outer test's decoy:
    '...revised in 1975'). The last word of the title before the leader is
    the filter: a genuine entry title ends in the substantive noun/name
    being indexed, never a bare function word like 'in'."""
    from axial.holdings import _extract_entry_reference

    assert _extract_entry_reference("This edition was substantially revised in 1975") is None
    assert _extract_entry_reference("A survey of the archive from 1975") is None
    assert _extract_entry_reference("The committee met on 12") is None


def test_signal_a_reading_finds_max_reference_on_contents_page():
    from axial.holdings import _signal_a_reading

    page_texts = [
        "Contents\nChapter One .......... 1\nChapter Two .......... 25\n"
        "Chapter Three .......... 60",
        "filler page one",
        "filler page two",
    ]
    assert _signal_a_reading(page_texts) == 60


def test_signal_a_reading_stops_contents_region_when_a_page_yields_no_entries():
    from axial.holdings import _signal_a_reading

    page_texts = [
        "Contents\nIntroduction .......... 1",
        "This is ordinary body prose with no entries at all.",
        "Chapter Nine .......... 900",  # unreachable: region already closed
    ]
    assert _signal_a_reading(page_texts) == 1


def test_signal_a_reading_stops_contents_region_at_the_span_bound_even_when_pages_keep_yielding_entries():
    """The entry-exhaustion exit above isn't the only stop condition
    (issue #268 review F4): the region is ALSO bounded at
    `CONTENTS_SPAN_PAGES` pages even when every following page keeps
    yielding entries. A 4th page with a much larger reference must never
    be counted once the bound is reached -- pinned with a literal, not
    scaled off the constant, so a mutation to it (e.g. `CONTENTS_SPAN_PAGES
    = 999`) is actually caught."""
    from axial.holdings import CONTENTS_SPAN_PAGES, _signal_a_reading

    assert CONTENTS_SPAN_PAGES == 3, (
        "this test pins the region bound with a literal page count; update "
        "it if CONTENTS_SPAN_PAGES is deliberately retuned"
    )
    page_texts = [
        "Contents\nChapter One .......... 1",
        "Chapter Two .......... 2",
        "Chapter Three .......... 3",
        "Chapter Four .......... 999",  # 4th page: still entry-shaped, still excluded
    ]
    assert _signal_a_reading(page_texts) == 3


def test_signal_a_reading_is_none_when_no_contents_heading_found():
    from axial.holdings import _signal_a_reading

    page_texts = ["just some prose", "more prose", "even more prose"]
    assert _signal_a_reading(page_texts) is None


def test_signal_a_reading_is_none_when_contents_page_has_no_readable_entries():
    from axial.holdings import _signal_a_reading

    page_texts = [
        "Contents\nChapter One .......... l0l\nChapter Two .......... 4O\n"
        "Chapter Three ......... ??\nAppendix .............. ~~~"
    ]
    assert _signal_a_reading(page_texts) is None


def test_signal_a_reading_finds_contents_heading_within_the_search_window():
    """Pins `CONTENTS_SEARCH_PAGES`'s current value (30) with a literal
    page count, not by scaling the fixture off the constant itself (issue
    #268 review F3): a fixture built as `["filler"] * CONTENTS_SEARCH_PAGES
    + [...]` passes for ANY value of the constant -- it is mutation-blind.
    A literal boundary actually exercises it."""
    from axial.holdings import CONTENTS_SEARCH_PAGES, _signal_a_reading

    assert CONTENTS_SEARCH_PAGES == 30, (
        "this test pins the search window with literal page counts; update "
        "them if CONTENTS_SEARCH_PAGES is deliberately retuned"
    )
    page_texts = ["filler"] * 29 + ["Contents\nChapter One .... 1"]
    assert _signal_a_reading(page_texts) == 1


def test_signal_a_reading_does_not_search_past_the_search_window():
    from axial.holdings import CONTENTS_SEARCH_PAGES, _signal_a_reading

    assert CONTENTS_SEARCH_PAGES == 30, (
        "this test pins the search window with literal page counts; update "
        "them if CONTENTS_SEARCH_PAGES is deliberately retuned"
    )
    page_texts = ["filler"] * 30 + ["Contents\nChapter One .... 1"]
    assert _signal_a_reading(page_texts) is None


def test_backmatter_density_is_zero_for_ordinary_prose_tail():
    from axial.holdings import _backmatter_density

    page_texts = [f"This is ordinary body prose on page {i}." for i in range(6)]
    assert _backmatter_density(page_texts) == 0.0


def test_backmatter_density_is_high_for_bibliography_and_index_tail():
    from axial.holdings import BACKMATTER_ENTRY_DENSITY, _backmatter_density

    page_texts = [f"This is ordinary body prose on page {i}." for i in range(6)] + [
        "Bayat, A. (2010) Life as Politics. Stanford University Press.\n"
        "Heydemann, S. (2013) Tracking the Arab Spring. Journal of Democracy 24.",
        "state formation, 12, 45, 88-91\ncivil society, 33, 67, 102",
    ]
    density = _backmatter_density(page_texts)
    assert density >= BACKMATTER_ENTRY_DENSITY, (
        f"expected a dense bibliography/index tail, got density={density}"
    )


def test_backmatter_density_recognizes_bayat_and_heydemann_shaped_entries():
    """The §7.11 false-positive guard: a heading-regex back-matter test
    reports both bayat and heydemann-war as lacking back matter; the
    content-based density test must not."""
    from axial.holdings import BACKMATTER_ENTRY_DENSITY, _backmatter_density

    page_texts = ["filler prose page"] + [
        "Bayat, A. (2010) Life as Politics: How Ordinary People Change the "
        "Middle East. Stanford University Press.",
        "Heydemann, S. (2013) Tracking the Arab Spring: Syria and the Future "
        "of Authoritarianism. Journal of Democracy 24.",
        "Ismail, S. (2018) The Rule of Violence. Cambridge University Press.",
    ]
    assert _backmatter_density(page_texts) >= BACKMATTER_ENTRY_DENSITY


def test_backmatter_density_not_diluted_by_wrapped_continuation_lines():
    """Regression for issue #268 review F2: a genuine bibliography entry
    wraps across several extracted lines, and only the first carries the
    'Lastname, F.' shape (measured on the real corpus's `state-legitimacy`
    tail). A raw matching-lines-over-total-lines count is diluted below any
    sane threshold by the continuation lines; a signals-per-100-words rate
    is not, because the denominator is text volume, not line count."""
    from axial.holdings import BACKMATTER_ENTRY_DENSITY, _backmatter_density

    page_texts = ["filler prose page"] + [
        "Bayat, A. (2010) Life as Politics: How Ordinary\n"
        "People Change the Middle East in the New\n"
        "Century of Uprisings and Change.\n"
        "Stanford University Press.\n"
        "Heydemann, S. (2013) Tracking the Arab Spring:\n"
        "Syria and the Future of Authoritarianism in the\n"
        "Middle East and Beyond the Current Crisis.\n"
        "Journal of Democracy 24 (3), 251-272."
    ]
    density = _backmatter_density(page_texts)
    assert density >= BACKMATTER_ENTRY_DENSITY, (
        f"expected wrapped bibliography entries to still test as back "
        f"matter despite only 2 of 8 lines carrying the inverted-author-"
        f"name shape, got density={density}"
    )


def test_probe_fires_signal_a_below_cover_floor():
    from axial.holdings import COVER_FLOOR, probe

    page_texts = [
        "Contents\nChapter One .......... 1\nChapter Two .......... 25\n"
        "Chapter Three .......... 60",
        "filler",
        "filler",
        "filler",
    ]
    flag = probe(page_texts)
    assert flag == {
        "signal": "toc_page_extent",
        "cover": pytest.approx(4 / 60),
        "physical_pages": 4,
        "max_page_reference": 60,
        "threshold": COVER_FLOOR,
    }


def test_probe_none_when_signal_a_reading_is_healthy():
    from axial.holdings import probe

    page_texts = ["Contents\nChapter One .......... 1\nChapter Two .......... 2"] + ["filler"] * 2
    assert probe(page_texts) is None


def test_probe_fires_signal_b_on_orphan_fragment():
    from axial.holdings import ORPHAN_PAGE_CEILING, probe

    page_texts = ["ordinary prose with no back matter and no contents page"] * 6
    flag = probe(page_texts)
    assert flag is not None
    assert flag["signal"] == "orphan_fragment"
    assert flag["physical_pages"] == 6
    assert isinstance(flag["backmatter_density"], (int, float))
    assert flag["threshold"] == ORPHAN_PAGE_CEILING


def test_probe_none_when_signal_b_page_count_too_high():
    from axial.holdings import ORPHAN_PAGE_CEILING, probe

    page_texts = ["ordinary prose with no back matter and no contents page"] * (
        ORPHAN_PAGE_CEILING + 1
    )
    assert probe(page_texts) is None


def test_probe_none_when_signal_b_has_back_matter():
    from axial.holdings import probe

    page_texts = ["ordinary prose with no contents page"] * 6 + [
        "Bayat, A. (2010) Life as Politics. Stanford University Press.\n"
        "Heydemann, S. (2013) Tracking the Arab Spring. Journal of Democracy 24.",
        "state formation, 12, 45, 88-91\ncivil society, 33, 67, 102",
    ]
    assert probe(page_texts) is None
