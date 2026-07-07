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
