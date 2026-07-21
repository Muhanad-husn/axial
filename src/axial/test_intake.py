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
