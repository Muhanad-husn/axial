"""Inner unit tests for `axial.identifiers` (issue #326, §7.12/§7.13).

Ports the exploration spike's own self-test assertions
(`plans/book-metadata-open-library/spike/phase0_scan.py`'s `selftest()`,
recovered via `git show 4cf92b3:...`) onto the shipped module -- the
regex/checksum logic is unchanged, so these pin the port rather than
re-deriving the design."""

from __future__ import annotations

from axial.identifiers import capture, find_dois, find_isbns, valid_isbn10, valid_isbn13


class TestChecksumValidation:
    def test_a_real_isbn13_validates(self):
        assert valid_isbn13("9780262033848") is True

    def test_a_real_isbn10_validates(self):
        assert valid_isbn10("0262033844") is True

    def test_an_isbn10_ending_in_x_validates(self):
        assert valid_isbn10("020161622X") is True

    def test_a_corrupted_isbn13_check_digit_fails(self):
        assert valid_isbn13("9780262033849") is False

    def test_a_corrupted_isbn10_check_digit_fails(self):
        assert valid_isbn10("0262033845") is False

    def test_a_non_x_letter_in_the_check_position_is_not_valid(self):
        assert valid_isbn10("020161622Y") is False


class TestFindIsbns:
    def test_a_hyphenated_labelled_line_is_captured_and_normalized(self):
        text = "ISBN: 978-0-262-03384-8\nAll rights reserved."

        assert find_isbns(text) == {"9780262033848"}

    def test_a_bare_ean13_run_is_captured_with_no_isbn_word_nearby(self):
        assert find_isbns("9780262033848") == {"9780262033848"}

    def test_a_mistyped_isbn_failing_its_own_checksum_is_dropped(self):
        """A false win here would be worse than dropping it -- the lookup
        would either 404 or resolve to the wrong book entirely."""
        assert find_isbns("ISBN 978-0-262-03384-7") == set()

    def test_an_all_same_digit_placeholder_is_rejected_despite_passing_checksum(self):
        assert find_isbns("ISBN: 0-000-00000-0") == set()

    def test_no_identifier_in_text_returns_empty_not_an_exception(self):
        assert find_isbns("no identifier here, just ordinary prose") == set()

    def test_an_isbn10_labelled_line_is_captured(self):
        assert find_isbns("ISBN-10: 0-262-03384-4") == {"0262033844"}

    def test_extraction_noise_spacing_and_a_mid_identifier_line_break_still_captures(self):
        """A real `pypdf` extract routinely breaks a long digit run across a
        line, and leaves irregular spacing around the label -- neither
        should defeat capture."""
        noisy = "ISBN:  978-0-262-\n03384-8\n"

        assert find_isbns(noisy) == {"9780262033848"}


class TestFindDois:
    def test_trailing_sentence_punctuation_is_stripped(self):
        text = "See https://doi.org/10.1145/3292500.3330701."

        assert find_dois(text) == {"10.1145/3292500.3330701"}

    def test_no_doi_in_text_returns_empty(self):
        assert find_dois("no identifier here") == set()

    def test_front_matter_with_both_an_isbn_and_a_doi_returns_both(self):
        text = "ISBN: 978-0-262-03384-8\nhttps://doi.org/10.1145/3292500.3330701"

        assert find_isbns(text) == {"9780262033848"}
        assert find_dois(text) == {"10.1145/3292500.3330701"}


class TestCapture:
    def test_prefers_an_isbn_over_a_doi_when_both_are_present(self):
        text = "ISBN: 978-0-262-03384-8\nhttps://doi.org/10.1145/3292500.3330701"

        assert capture(text) == {"type": "isbn", "value": "9780262033848"}

    def test_falls_back_to_a_doi_when_no_isbn_is_present(self):
        text = "https://doi.org/10.1145/3292500.3330701"

        assert capture(text) == {"type": "doi", "value": "10.1145/3292500.3330701"}

    def test_returns_none_when_neither_is_present(self):
        assert capture("ordinary body prose discussing the case in general terms") is None


class TestCaptureMultipleCandidates:
    """Founder decision (post-review of #326, refined a second time after
    real-corpus measurement showed treating every multi-ISBN capture as
    ambiguous cost 93%->37% coverage): `capture()` itself only reports that
    more than one distinct candidate was found -- it does not decide
    whether they describe the same work (harmless, e.g. hardcover/paperback
    ISBNs) or genuinely different works (e.g. `mann-sources-of-social-
    power-v1`/`v3`/`v4`'s shared series ISBN `9781107028654` alongside
    their own volume-specific one). That decision needs a resolve-and-
    compare step (`axial.intake._merge_identifier_fields`), which this pure
    module does not perform."""

    TWO_VALID_ISBNS = (
        "ISBN: 978-0-262-03384-8\nAlso available in this series:\nISBN: 978-0-198-82524-1\n"
    )

    def test_more_than_one_distinct_valid_isbn_reports_every_candidate(self):
        result = capture(self.TWO_VALID_ISBNS)

        assert result == {
            "type": "isbn",
            "value": None,
            "candidates": ["9780198825241", "9780262033848"],
        }

    def test_a_repeated_identical_isbn_is_not_multiple(self):
        """The same ISBN printed twice (e.g. once on the title page, once
        on the copyright page) is one identifier, not two candidates."""
        text = "ISBN: 978-0-262-03384-8\n...\nISBN 9780262033848 (print)"

        assert capture(text) == {"type": "isbn", "value": "9780262033848"}

    def test_multiple_isbns_win_over_a_doi_found_on_the_same_page(self):
        """ISBN precedence still applies to a multi-candidate capture -- a
        confusing ISBN block does not fall through to a DOI found
        elsewhere on the page."""
        text = self.TWO_VALID_ISBNS + "https://doi.org/10.1145/3292500.3330701"

        result = capture(text)

        assert result["type"] == "isbn"
        assert result["value"] is None

    def test_more_than_one_distinct_valid_doi_reports_every_candidate(self):
        text = "https://doi.org/10.1145/3292500.3330701\nhttps://doi.org/10.1007/s11186-025-09677-5"

        result = capture(text)

        assert result == {
            "type": "doi",
            "value": None,
            "candidates": ["10.1007/s11186-025-09677-5", "10.1145/3292500.3330701"],
        }
