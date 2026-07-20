"""Inner unit tests for the axial intake module (issue #13, slice 01)."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "intake"

TEXT_LAYER_PDF = FIXTURES_DIR / "text_layer.pdf"
NO_TEXT_LAYER_PDF = FIXTURES_DIR / "no_text_layer.pdf"
TEXT_DOCX = FIXTURES_DIR / "text.docx"
UNSUPPORTED_TXT = FIXTURES_DIR / "unsupported.txt"
UNSUPPORTED_PNG = FIXTURES_DIR / "unsupported.png"


def test_check_extension_accepts_pdf_case_insensitively():
    from axial.intake import check_extension

    check_extension(Path("some/file.PDF"))
    check_extension(Path("some/file.pdf"))


def test_check_extension_accepts_docx_case_insensitively():
    from axial.intake import check_extension

    check_extension(Path("some/file.DOCX"))
    check_extension(Path("some/file.docx"))


def test_check_extension_rejects_unsupported_extension_naming_it():
    from axial.intake import IntakeError, check_extension

    with pytest.raises(IntakeError) as exc_info:
        check_extension(Path("some/file.txt"))

    assert ".txt" in str(exc_info.value)


def test_has_text_layer_true_for_text_pdf():
    from axial.intake import has_text_layer

    assert has_text_layer(TEXT_LAYER_PDF, "pdf") is True


def test_has_text_layer_false_for_no_text_pdf():
    from axial.intake import has_text_layer

    assert has_text_layer(NO_TEXT_LAYER_PDF, "pdf") is False


def test_has_text_layer_true_for_docx_with_body_text():
    from axial.intake import has_text_layer

    assert has_text_layer(TEXT_DOCX, "docx") is True


def test_intake_missing_path_raises_intake_error():
    from axial.intake import IntakeError, intake

    with pytest.raises(IntakeError):
        intake(FIXTURES_DIR / "no-such-file.pdf")


def test_intake_returns_source_metadata_stub_for_text_pdf():
    from axial.intake import intake

    source = intake(TEXT_LAYER_PDF)

    assert source.path == TEXT_LAYER_PDF
    assert source.format == "pdf"
    assert source.text_layer_ok is True


def test_intake_returns_source_metadata_stub_for_text_docx():
    from axial.intake import intake

    source = intake(TEXT_DOCX)

    assert source.path == TEXT_DOCX
    assert source.format == "docx"
    assert source.text_layer_ok is True


def test_intake_rejects_no_text_layer_pdf():
    from axial.intake import IntakeError, intake

    with pytest.raises(IntakeError) as exc_info:
        intake(NO_TEXT_LAYER_PDF)

    message = str(exc_info.value).lower()
    assert "text layer" in message or "no text" in message


def test_intake_rejects_unsupported_extension():
    from axial.intake import IntakeError, intake

    with pytest.raises(IntakeError) as exc_info:
        intake(UNSUPPORTED_PNG)

    assert ".png" in str(exc_info.value)


# =============================================================================
# Holdings-completeness probe (issue #268 slice 1, §7.11 / §8 P0-1b) -- inner
# unit cycles beneath the locked outer contract in
# tests/ingestion/test_holdings_completeness_probe.py.
# =============================================================================


def test_is_contents_heading_matches_after_lowercase_and_whitespace_collapse():
    from axial.intake import _is_contents_heading

    assert _is_contents_heading("Contents") is True
    assert _is_contents_heading("  CONTENTS  ") is True
    assert _is_contents_heading("Table   of    Contents") is True
    assert _is_contents_heading("table of contents") is True


def test_is_contents_heading_rejects_ordinary_prose():
    from axial.intake import _is_contents_heading

    assert _is_contents_heading("This chapter discusses the contents of the archive.") is False
    assert _is_contents_heading("Chapter One") is False
    assert _is_contents_heading("") is False


def test_extract_entry_reference_reads_trailing_number_past_dot_leader():
    from axial.intake import _extract_entry_reference

    assert _extract_entry_reference("Chapter One .......... 1") == 1
    assert _extract_entry_reference("Chapter Two .......... 25") == 25
    assert _extract_entry_reference("Index .................................. 11") == 11


def test_extract_entry_reference_rejects_decoy_bare_year_with_no_dot_leader():
    from axial.intake import _extract_entry_reference

    assert _extract_entry_reference("This edition was substantially revised in 1975") is None


def test_extract_entry_reference_rejects_garbled_trailing_tokens():
    from axial.intake import _extract_entry_reference

    assert _extract_entry_reference("Chapter One .......................... l0l") is None
    assert _extract_entry_reference("Chapter Two .......................... 4O") is None
    assert _extract_entry_reference("Chapter Three ......................... ??") is None
    assert _extract_entry_reference("Appendix .............................. ~~~") is None


def test_signal_a_reading_finds_max_reference_on_contents_page():
    from axial.intake import _signal_a_reading

    page_texts = [
        "Contents\nChapter One .......... 1\nChapter Two .......... 25\n"
        "Chapter Three .......... 60",
        "filler page one",
        "filler page two",
    ]
    assert _signal_a_reading(page_texts) == 60


def test_signal_a_reading_stops_contents_region_when_a_page_yields_no_entries():
    from axial.intake import _signal_a_reading

    page_texts = [
        "Contents\nIntroduction .......... 1",
        "This is ordinary body prose with no entries at all.",
        "Chapter Nine .......... 900",  # unreachable: region already closed
    ]
    assert _signal_a_reading(page_texts) == 1


def test_signal_a_reading_is_none_when_no_contents_heading_found():
    from axial.intake import _signal_a_reading

    page_texts = ["just some prose", "more prose", "even more prose"]
    assert _signal_a_reading(page_texts) is None


def test_signal_a_reading_is_none_when_contents_page_has_no_readable_entries():
    from axial.intake import _signal_a_reading

    page_texts = [
        "Contents\nChapter One .......... l0l\nChapter Two .......... 4O\n"
        "Chapter Three ......... ??\nAppendix .............. ~~~"
    ]
    assert _signal_a_reading(page_texts) is None


def test_signal_a_reading_only_searches_first_contents_search_pages():
    from axial.intake import CONTENTS_SEARCH_PAGES, _signal_a_reading

    page_texts = ["filler"] * CONTENTS_SEARCH_PAGES + ["Contents\nChapter One .... 1"]
    assert _signal_a_reading(page_texts) is None


def test_backmatter_density_is_zero_for_ordinary_prose_tail():
    from axial.intake import _backmatter_density

    page_texts = [f"This is ordinary body prose on page {i}." for i in range(6)]
    assert _backmatter_density(page_texts) == 0.0


def test_backmatter_density_is_high_for_bibliography_and_index_tail():
    from axial.intake import _backmatter_density

    page_texts = [f"This is ordinary body prose on page {i}." for i in range(6)] + [
        "Bayat, A. (2010) Life as Politics. Stanford University Press.\n"
        "Heydemann, S. (2013) Tracking the Arab Spring. Journal of Democracy 24.",
        "state formation, 12, 45, 88-91\ncivil society, 33, 67, 102",
    ]
    density = _backmatter_density(page_texts)
    assert density > 0.5, f"expected a dense bibliography/index tail, got density={density}"


def test_backmatter_density_recognizes_bayat_and_heydemann_shaped_entries():
    """The §7.11 false-positive guard: a heading-regex back-matter test
    reports both bayat and heydemann-war as lacking back matter; the
    content-based density test must not."""
    from axial.intake import BACKMATTER_ENTRY_DENSITY, _backmatter_density

    page_texts = ["filler prose page"] + [
        "Bayat, A. (2010) Life as Politics: How Ordinary People Change the "
        "Middle East. Stanford University Press.",
        "Heydemann, S. (2013) Tracking the Arab Spring: Syria and the Future "
        "of Authoritarianism. Journal of Democracy 24.",
        "Ismail, S. (2018) The Rule of Violence. Cambridge University Press.",
    ]
    assert _backmatter_density(page_texts) >= BACKMATTER_ENTRY_DENSITY


def test_holdings_completeness_probe_fires_signal_a_below_cover_floor():
    from axial.intake import COVER_FLOOR, _holdings_completeness_probe

    page_texts = [
        "Contents\nChapter One .......... 1\nChapter Two .......... 25\n"
        "Chapter Three .......... 60",
        "filler",
        "filler",
        "filler",
    ]
    flag = _holdings_completeness_probe(page_texts)
    assert flag == {
        "signal": "toc_page_extent",
        "cover": pytest.approx(4 / 60),
        "physical_pages": 4,
        "max_page_reference": 60,
        "threshold": COVER_FLOOR,
    }


def test_holdings_completeness_probe_none_when_signal_a_reading_is_healthy():
    from axial.intake import _holdings_completeness_probe

    page_texts = ["Contents\nChapter One .......... 1\nChapter Two .......... 2"] + ["filler"] * 2
    assert _holdings_completeness_probe(page_texts) is None


def test_holdings_completeness_probe_fires_signal_b_on_orphan_fragment():
    from axial.intake import ORPHAN_PAGE_CEILING, _holdings_completeness_probe

    page_texts = ["ordinary prose with no back matter and no contents page"] * 6
    flag = _holdings_completeness_probe(page_texts)
    assert flag is not None
    assert flag["signal"] == "orphan_fragment"
    assert flag["physical_pages"] == 6
    assert isinstance(flag["backmatter_density"], (int, float))
    assert flag["threshold"] == ORPHAN_PAGE_CEILING


def test_holdings_completeness_probe_none_when_signal_b_page_count_too_high():
    from axial.intake import ORPHAN_PAGE_CEILING, _holdings_completeness_probe

    page_texts = ["ordinary prose with no back matter and no contents page"] * (
        ORPHAN_PAGE_CEILING + 1
    )
    assert _holdings_completeness_probe(page_texts) is None


def test_holdings_completeness_probe_none_when_signal_b_has_back_matter():
    from axial.intake import _holdings_completeness_probe

    page_texts = ["ordinary prose with no contents page"] * 6 + [
        "Bayat, A. (2010) Life as Politics. Stanford University Press.\n"
        "Heydemann, S. (2013) Tracking the Arab Spring. Journal of Democracy 24.",
        "state formation, 12, 45, 88-91\ncivil society, 33, 67, 102",
    ]
    assert _holdings_completeness_probe(page_texts) is None


def test_pdf_page_texts_returns_one_string_per_physical_page():
    from axial.intake import _pdf_page_texts

    page_texts = _pdf_page_texts(TEXT_LAYER_PDF)

    assert isinstance(page_texts, list)
    assert len(page_texts) == 1
    assert "text layer" in page_texts[0].lower()


def test_source_defaults_holdings_flag_to_none():
    from axial.intake import Source

    source = Source(path=TEXT_LAYER_PDF, format="pdf", text_layer_ok=True)

    assert source.holdings_flag is None


def test_intake_populates_holdings_flag_for_pdf_source():
    from axial.intake import intake

    source = intake(TEXT_LAYER_PDF)

    assert source.format == "pdf"
    assert source.text_layer_ok is True
    # A one-page fixture with no contents page and no back matter is,
    # correctly, an orphan-fragment flag under §7.11 -- the flag-only
    # discipline means intake still succeeds regardless (asserted below).
    assert source.holdings_flag is not None
    assert source.holdings_flag["signal"] == "orphan_fragment"


def test_intake_never_computes_holdings_flag_for_docx_source():
    from axial.intake import intake

    source = intake(TEXT_DOCX)

    assert source.format == "docx"
    assert source.holdings_flag is None
