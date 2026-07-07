"""Outer acceptance test for issue #13, slice 01 (intake).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a born-digital fixture PDF with a text layer and a fixture DOCX with
      text
When  the user runs `axial intake <fixture>`
Then  it exits 0 and emits a source-metadata stub naming the file and
      detected format
And   against an image-only/no-text-layer PDF it exits nonzero with a
      message stating no text layer was found
And   against an unsupported file (e.g. .txt/.png) it exits nonzero naming
      the rejected extension

See specs/PRODUCT.md §5 stage 1 (intake: verify a real text layer exists;
reject scanned / no-text-layer files with a clear, logged message; no OCR
path) and §8 P0-1 (accepts .pdf/.docx, rejects everything else with a
logged reason; detects absence of a text layer and rejects with a clear
message; a scanned PDF is rejected and never silently passed downstream)
for the source of truth.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "intake"

TEXT_LAYER_PDF = FIXTURES_DIR / "text_layer.pdf"
NO_TEXT_LAYER_PDF = FIXTURES_DIR / "no_text_layer.pdf"
TEXT_DOCX = FIXTURES_DIR / "text.docx"
UNSUPPORTED_TXT = FIXTURES_DIR / "unsupported.txt"
UNSUPPORTED_PNG = FIXTURES_DIR / "unsupported.png"

# argparse's fallback error for an as-yet-nonexistent `intake` subcommand,
# e.g. "axial: error: argument command: invalid choice: 'intake' (choose
# from 'schema')". Any of these substrings appearing in the combined output
# means intake logic was never actually exercised -- the process failed
# before real intake code ran, not because of a text-layer/extension
# decision. Reject that generic failure mode explicitly so this test can
# only pass once real intake behavior exists.
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_intake(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "axial", "intake", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `intake` error path, not an argparse fallback "
            f"(found {marker!r}) -- this means the `intake` subcommand does "
            f"not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def test_intake_accepts_born_digital_pdf_with_text_layer():
    result = _run_intake(str(TEXT_LAYER_PDF))

    assert result.returncode == 0, (
        f"expected exit code 0 for a born-digital PDF with a text layer, "
        f"got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    combined = result.stdout + result.stderr
    assert TEXT_LAYER_PDF.name in combined, (
        f"expected the source-metadata stub to name the file "
        f"{TEXT_LAYER_PDF.name!r}, got:\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert "pdf" in combined.lower(), (
        f"expected the source-metadata stub to name the detected format "
        f"('pdf'), got:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_intake_accepts_docx_with_text():
    result = _run_intake(str(TEXT_DOCX))

    assert result.returncode == 0, (
        f"expected exit code 0 for a DOCX with real body text, "
        f"got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    combined = result.stdout + result.stderr
    assert TEXT_DOCX.name in combined, (
        f"expected the source-metadata stub to name the file "
        f"{TEXT_DOCX.name!r}, got:\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )
    assert "docx" in combined.lower(), (
        f"expected the source-metadata stub to name the detected format "
        f"('docx'), got:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_intake_rejects_image_only_pdf_with_no_text_layer():
    result = _run_intake(str(NO_TEXT_LAYER_PDF))

    assert result.returncode != 0, (
        f"expected nonzero exit code for an image-only/no-text-layer PDF, "
        f"got 0\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined = (result.stdout + result.stderr).lower()
    assert "text layer" in combined or "no text" in combined, (
        f"expected a message stating no text layer was found, got:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_intake_rejects_unsupported_txt_extension():
    result = _run_intake(str(UNSUPPORTED_TXT))

    assert result.returncode != 0, (
        f"expected nonzero exit code for an unsupported .txt file, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined = result.stdout + result.stderr
    assert ".txt" in combined, (
        f"expected the error message to name the rejected extension "
        f"('.txt'), got:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_intake_rejects_unsupported_png_extension():
    result = _run_intake(str(UNSUPPORTED_PNG))

    assert result.returncode != 0, (
        f"expected nonzero exit code for an unsupported .png file, got 0\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    _assert_not_argparse_fallback(result)

    combined = result.stdout + result.stderr
    assert ".png" in combined, (
        f"expected the error message to name the rejected extension "
        f"('.png'), got:\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
