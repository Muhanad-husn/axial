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
# Holdings-completeness probe wiring (issue #268 slice 1, §7.11 / §8 P0-1b):
# how `intake()` attaches `Source.holdings_flag`. The probe's own signal
# logic and tunables live in `axial.holdings` and are tested in
# `test_holdings.py`; this is beneath the locked outer contract in
# tests/ingestion/test_holdings_completeness_probe.py.
# =============================================================================


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


def test_intake_makes_no_network_calls(monkeypatch):
    """Determinism guard (issue #268 review F5): §7.11/§8 P0-1b requires
    the holdings-completeness probe to make zero model, embedding, and
    network calls. It holds structurally today (the probe only ever reads
    `page_texts` already in hand), but nothing asserted that -- so a later
    edit that reached for a network call during intake would regress
    silently. Cheap enforcement: block socket connection attempts for the
    duration of `intake()` and assert it still completes."""
    import socket

    from axial.intake import intake

    def _blocked(*args, **kwargs):
        raise AssertionError("intake() attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    source = intake(TEXT_LAYER_PDF)

    assert source.text_layer_ok is True
