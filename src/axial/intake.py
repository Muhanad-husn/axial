"""Corpus intake: extension gate + text-layer probe (PRD §5 stage 1, §8 P0-1).

Accepts only `.pdf` and `.docx`. Rejects everything else with a clear,
typed, logged reason. Verifies a real text layer exists before anything
downstream runs -- a scanned/image-only PDF is rejected, never silently
passed through an OCR path (there is none in this slice).

Given an LLM client, intake also runs the holdings-completeness check
(§7.11, §8 P0-1b) over the same text layer, via `axial.holdings`, which
owns the check's own cleaning, prompt and flag shape -- this module's job
is only to build `page_texts`, supply the physical page count, and attach
the resulting flag to `Source`. The check is a model call, so it runs only
for a caller that supplies a client: `extract()` calls `intake()` purely to
validate a file and never pays for a judgment it does not read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from axial.holdings import probe as _holdings_probe
from axial.llm import LLMClient

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


class IntakeError(Exception):
    """Base class for all intake errors."""


class UnsupportedExtensionError(IntakeError):
    """Raised when a file's extension is not among SUPPORTED_EXTENSIONS."""

    def __init__(self, path: Path):
        self.path = path
        self.extension = path.suffix
        super().__init__(
            f"unsupported file extension {self.extension!r} for {path}; "
            f"expected one of {sorted(SUPPORTED_EXTENSIONS)}"
        )


class MissingSourceFileError(IntakeError):
    """Raised when the input path does not exist or is not a file."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"missing or unreadable source file: {path}")


class NoTextLayerError(IntakeError):
    """Raised when a source has no extractable text layer."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no text layer found in {path}; scanned/image-only sources are rejected "
            "(no OCR path in this slice)"
        )


@dataclass
class Source:
    """Source-metadata stub returned on successful intake.

    `holdings_flag` (§7.11, §8 P0-1b) is the holdings-completeness check's
    result: `None` for a source judged complete (and for a caller that
    supplied no client, since the judgment is a model call), otherwise a
    dict recording its measurement -- the source, the concluded document
    kind, the claimed extent and what stated it, the observed page count,
    and the model's stated reason. Never a bare boolean, and never any
    source text (DEC-23). Flag-only: a raised flag never blocks intake or
    alters anything else on this object.
    """

    path: Path
    format: str
    text_layer_ok: bool
    holdings_flag: dict | None = None


def check_extension(path: Path) -> str:
    """Validate `path`'s extension and return the detected format ('pdf'/'docx')."""
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedExtensionError(path)
    return extension.lstrip(".")


def _pdf_page_texts(path: Path) -> list[str]:
    """One raw text-layer string per physical page of `path`, in reading
    order -- the per-page granularity the holdings-completeness probe needs
    (§7.11) and that a single concatenated string discards."""
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def _extract_pdf_text(path: Path) -> str:
    return "".join(_pdf_page_texts(path))


def _extract_docx_text(path: Path) -> str:
    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text_layer(path: Path, fmt: str) -> str:
    """Extract `path`'s raw text layer (`fmt`: 'pdf' or 'docx'). Shared by
    `has_text_layer`'s presence check and by any downstream bounded text
    probe that needs actual text content, not just a boolean -- e.g.
    `axial.drive`'s English-only language-gate probe (issue #239, P0-11c),
    which reuses this rather than reimplementing pdf/docx text extraction."""
    if fmt == "pdf":
        return _extract_pdf_text(path)
    if fmt == "docx":
        return _extract_docx_text(path)
    raise ValueError(f"unknown format {fmt!r}")  # pragma: no cover - guarded by check_extension


def has_text_layer(path: Path, fmt: str) -> bool:
    """Probe `path` (of detected format `fmt`, 'pdf' or 'docx') for real body text."""
    return bool(extract_text_layer(path, fmt).strip())


def intake(path: str | Path, *, client: LLMClient | None = None) -> Source:
    """Run intake on `path`: validate extension, verify a text layer, and --
    when `client` is given -- run the holdings-completeness check
    (§7.11/§8 P0-1b) and attach its flag. A raised flag is flag-only: it
    never raises, never rejects, and the source still completes intake
    exactly as an unflagged one would.

    A DOCX is checked too (the earlier blanket DOCX exemption is retired,
    §7.11); it exposes no physical page count, which the check handles as
    unobtainable evidence rather than as damning."""
    path = Path(path)

    if not path.is_file():
        raise MissingSourceFileError(path)

    fmt = check_extension(path)

    if fmt == "pdf":
        page_texts = _pdf_page_texts(path)
        if not "".join(page_texts).strip():
            raise NoTextLayerError(path)
        physical_pages: int | None = len(page_texts)
    else:
        text = extract_text_layer(path, fmt)
        if not text.strip():
            raise NoTextLayerError(path)
        page_texts = [text]
        physical_pages = None

    holdings_flag = (
        None
        if client is None
        else _holdings_probe(
            page_texts,
            client=client,
            physical_pages=physical_pages,
            source_name=path.name,
        )
    )

    return Source(path=path, format=fmt, text_layer_ok=True, holdings_flag=holdings_flag)
