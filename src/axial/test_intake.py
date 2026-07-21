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
# Holdings-completeness check wiring (issue #284, §7.11 / §8 P0-1b): how
# `intake()` attaches `Source.holdings_flag`. The check's own cleaning,
# prompt and flag shape live in `axial.holdings` and are tested in
# `test_holdings.py`.
# =============================================================================


class _StubHoldingsClient:
    def __init__(self, verdict: str = "complete"):
        self.verdict = verdict
        self.calls = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        import json

        self.calls += 1
        return json.dumps(
            {
                "document_kind": "book",
                "claimed_extent": None,
                "claimed_extent_stated_by": None,
                "verdict": self.verdict,
                "reason": "stub",
            }
        )


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

    client = _StubHoldingsClient(verdict="partial")

    source = intake(TEXT_LAYER_PDF, client=client)

    assert source.format == "pdf"
    assert source.text_layer_ok is True
    assert client.calls == 1
    assert source.holdings_flag["source"] == TEXT_LAYER_PDF.name
    assert source.holdings_flag["observed_pages"] == 1


def test_intake_checks_a_docx_source_too_with_no_page_count():
    """§7.11 retires the blanket DOCX exemption: the check runs, and the
    absent page count is unobtainable evidence, not a flag."""
    from axial.intake import intake

    client = _StubHoldingsClient()

    source = intake(TEXT_DOCX, client=client)

    assert source.format == "docx"
    assert client.calls == 1
    assert source.holdings_flag is None


def test_intake_without_a_client_makes_no_model_call_and_raises_no_flag():
    """The judgment is a model call, so it runs only for a caller that
    supplies a client -- `extract()` validates a file without paying for a
    judgment it never reads."""
    from axial.intake import intake

    source = intake(TEXT_LAYER_PDF)

    assert source.text_layer_ok is True
    assert source.holdings_flag is None


# =============================================================================
# Persisted source-metadata record (issue #285, §7.12/§7.13, §8 P0-1c/P0-1d).
# Outer, end-to-end coverage lives in
# tests/ingestion/test_source_metadata_record.py; these are pure/unit-level
# checks of the individual helpers plus a couple of shape-level integration
# checks against the existing shared fixtures. `axial.intake.SOURCE_META_DIR`
# is redirected to an isolated tmp dir for every test in this file by the
# autouse `_isolate_checkpoint_dirs` fixture in src/axial/conftest.py, so a
# call to `intake()` below with no explicit `source_meta_dir` never touches
# the real repo's `data/source_meta/`.
# =============================================================================


def test_source_meta_path_is_keyed_by_source_id_under_the_given_dir(tmp_path):
    from axial.intake import source_meta_path

    path = source_meta_path("some-source-abc123456789", tmp_path)

    assert path == tmp_path / "some-source-abc123456789.json"


class TestPlausibleMetadataValue:
    def test_passes_through_a_real_value(self):
        from axial.intake import _plausible_metadata_value

        assert _plausible_metadata_value("Jane Q. Historian", "pdfTeX", "LaTeX") == (
            "Jane Q. Historian"
        )

    def test_rejects_empty_and_whitespace_only(self):
        from axial.intake import _plausible_metadata_value

        assert _plausible_metadata_value("") is None
        assert _plausible_metadata_value("   ") is None
        assert _plausible_metadata_value(None) is None

    def test_rejects_a_value_equal_to_a_junk_candidate_case_and_whitespace_insensitively(self):
        from axial.intake import _plausible_metadata_value

        assert _plausible_metadata_value("Adobe Acrobat Pro DC", "Adobe Acrobat Pro DC") is None
        assert (
            _plausible_metadata_value("  adobe   acrobat pro dc  ", "Adobe Acrobat Pro DC") is None
        )

    def test_only_rejects_an_exact_junk_match_not_a_mere_substring(self):
        from axial.intake import _plausible_metadata_value

        # A real author whose name happens to contain a producer-ish
        # substring must still pass through -- the comparison is exact,
        # never a substring/fuzzy match.
        assert _plausible_metadata_value("Adobe Acrobat Historian", "Adobe Acrobat Pro DC") == (
            "Adobe Acrobat Historian"
        )


class TestTitlePageTitle:
    def test_returns_the_first_substantive_line(self):
        from axial.intake import _title_page_title

        text = "\n\nThe Making of a Revolution\nA Study in Political Change\n"
        assert _title_page_title(text) == "The Making of a Revolution"

    def test_returns_none_for_blank_text(self):
        from axial.intake import _title_page_title

        assert _title_page_title("") is None
        assert _title_page_title("   \n\n  ") is None

    def test_rejects_an_overlong_line_as_not_a_title(self):
        from axial.intake import _MAX_TITLE_LINE_CHARS, _title_page_title

        text = ("x" * (_MAX_TITLE_LINE_CHARS + 1)) + "\nA Real Title\n"
        assert _title_page_title(text) is None


class TestTitlePageDate:
    def test_finds_a_year_near_a_copyright_marker(self):
        from axial.intake import _title_page_date

        assert _title_page_date("Copyright © 1978 by the University Press") == "1978"

    def test_finds_a_year_near_the_word_published(self):
        from axial.intake import _title_page_date

        assert _title_page_date("First published 1965 by Some Press") == "1965"

    def test_returns_none_when_no_marker_is_present(self):
        from axial.intake import _title_page_date

        # A bare four-digit number with no copyright/publication keyword
        # nearby is not evidence of a publication year.
        assert _title_page_date("Chapter Three, page 1978 of the manuscript") is None

    def test_returns_none_for_blank_text(self):
        from axial.intake import _title_page_date

        assert _title_page_date("") is None


class TestBibliographicField:
    def test_a_found_value_carries_its_provenance(self):
        from axial.intake import _bibliographic_field

        assert _bibliographic_field("Jane Q. Historian", "embedded metadata") == {
            "value": "Jane Q. Historian",
            "provenance": "embedded metadata",
        }

    def test_no_value_is_the_unavailable_sentinel(self):
        from axial.intake import UNAVAILABLE, _bibliographic_field

        assert _bibliographic_field(None, "embedded metadata") == UNAVAILABLE


class TestResolveHoldingsFlag:
    def test_a_supplied_client_always_wins_even_when_it_computed_none(self, tmp_path):
        from axial.intake import _resolve_holdings_flag

        meta_path = tmp_path / "some-id.json"
        meta_path.write_text('{"holdings_flag": {"document_kind": "book"}}', encoding="utf-8")

        resolved = _resolve_holdings_flag(None, object(), meta_path)

        assert resolved is None

    def test_no_client_and_no_existing_record_resolves_to_none(self, tmp_path):
        from axial.intake import _resolve_holdings_flag

        resolved = _resolve_holdings_flag(None, None, tmp_path / "absent.json")

        assert resolved is None

    def test_no_client_preserves_the_existing_records_flag(self, tmp_path):
        from axial.intake import _resolve_holdings_flag

        meta_path = tmp_path / "some-id.json"
        meta_path.write_text('{"holdings_flag": {"document_kind": "book"}}', encoding="utf-8")

        resolved = _resolve_holdings_flag(None, None, meta_path)

        assert resolved == {"document_kind": "book"}


def test_intake_writes_a_source_meta_record_for_a_pdf(tmp_path):
    import json

    from axial.envelope import compute_source_id
    from axial.intake import intake, source_meta_path

    intake(TEXT_LAYER_PDF, source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_LAYER_PDF), tmp_path)
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["source_id"] == compute_source_id(TEXT_LAYER_PDF)
    assert isinstance(record["physical_page_count"], int)
    assert "holdings_flag" in record
    for field in ("author", "title", "date"):
        assert field in record


def test_intake_writes_a_source_meta_record_for_a_docx_with_no_page_count(tmp_path):
    import json

    from axial.envelope import compute_source_id
    from axial.intake import NOT_ATTEMPTED, intake, source_meta_path

    intake(TEXT_DOCX, source_meta_dir=tmp_path)

    record_path = source_meta_path(compute_source_id(TEXT_DOCX), tmp_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["physical_page_count"] is None
    # No mechanism exists for a DOCX's publication date in this slice.
    assert record["date"] == NOT_ATTEMPTED


def test_intake_default_source_meta_dir_is_isolated_by_the_autouse_fixture(tmp_path):
    """Sanity check on this file's own isolation seam: `SOURCE_META_DIR` is
    redirected away from the real repo `data/source_meta/` for every test
    here, so a call with no explicit `source_meta_dir` still lands under an
    isolated tmp location, never the real cwd-relative default."""
    import axial.intake as intake_mod

    REPO_DEFAULT = Path("data/source_meta")
    assert intake_mod.SOURCE_META_DIR != REPO_DEFAULT
