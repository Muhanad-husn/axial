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

Every successful intake also writes the persisted source-metadata record
(§7.12/§7.13, §8 P0-1c/P0-1d) to `data/source_meta/<source_id>.json`,
before any extraction runs: the physical page count, the full sha256 file
hash, the §7.11 holdings flag in full (or an explicit no-flag), and
author/title/date read from the PDF's own embedded metadata and title page
(never the filename). This is model-free -- it reads facts already in hand
from the P0-1 text layer plus pypdf/python-docx's own document-info
readers, no new heavy extractor and no second LLM call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from pypdf import PdfReader

from axial.holdings import probe as _holdings_probe
from axial.llm import LLMClient

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

# Persisted source-metadata record (PRD §7.12, §8 P0-1c): one JSON per
# source in data/source_meta/, keyed by the same deterministic source_id
# the tree/envelope/chunk artifacts use. A plain, cwd-relative path with no
# config-file override, mirroring `axial.extract.TREES_DIR`'s own
# convention (unlike `axial.envelope.ENVELOPES_DIR`, which config can
# redirect -- no caller of this module needs that yet, §7.12 names the path
# directly).
SOURCE_META_DIR = Path("data/source_meta")

# The three §7.13 field states for author/title/date, distinguishable on
# read: a value carries `{"value": ..., "provenance": ...}`; the other two
# states are these literal sentinel strings -- "unavailable" (a read was
# attempted and nothing recoverable was found) versus "not_attempted" (no
# mechanism exists for this field/format combination in this slice, e.g. a
# DOCX's publication date). Never conflated: a consumer checks which of the
# three shapes it got before reading `value`.
UNAVAILABLE = "unavailable"
NOT_ATTEMPTED = "not_attempted"

PROVENANCE_EMBEDDED_METADATA = "embedded metadata"
PROVENANCE_TITLE_PAGE = "title page"

# A publication year stated near a copyright/publication marker on the
# title page (§7.13) -- the only source `date` ever reads from, because a
# PDF's own embedded CreationDate/ModDate measure when the *file* was
# produced, not when the *work* was published, and are never a valid `date`
# provenance (§7.13: "a file-creation date that is not the publication
# date"). Bounded to a plausible four-digit year (1400-2099) within 20
# non-digit characters of the marker, so an unrelated nearby number doesn't
# match.
_COPYRIGHT_YEAR_RE = re.compile(
    r"(?:©|copyright|first published|published)\D{0,20}?(1[4-9]\d{2}|20\d{2})",
    re.IGNORECASE,
)

# Sanity bound on the title-page fallback's candidate title line (§7.13):
# large enough for a real (if long) book title, small enough that a
# full paragraph mistaken for a title line is rejected rather than stored.
_MAX_TITLE_LINE_CHARS = 200


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


# =============================================================================
# Source-metadata record (PRD §7.12/§7.13, §8 P0-1c/P0-1d)
# =============================================================================


def source_meta_path(source_id: str, source_meta_dir: Path = SOURCE_META_DIR) -> Path:
    """The write-once-per-intake path for `source_id`'s source-metadata
    record JSON (mirrors `axial.extract.tree_path`/`axial.envelope.envelope_path`)."""
    return source_meta_dir / f"{source_id}.json"


def _clean(value: str | None) -> str | None:
    """`value` with internal whitespace collapsed and edges stripped, or
    `None` for an absent/blank input -- shared normalization for both the
    junk-metadata comparison and the recorded value itself."""
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _plausible_metadata_value(value: str | None, *junk: str | None) -> str | None:
    """`value`, cleaned, when it is a real bibliographic value -- non-empty
    and not equal (case/whitespace-insensitive) to any of `junk`, the
    document's own producer/creator strings that a PDF writer sometimes
    reuses to auto-fill the author field (§7.13: "a producer string as
    author ... is recorded as unavailable, not passed through"). Returns
    `None` for an empty, whitespace-only, or junk-matching input."""
    cleaned = _clean(value)
    if cleaned is None:
        return None
    normalized = cleaned.casefold()
    for candidate in junk:
        cleaned_candidate = _clean(candidate)
        if cleaned_candidate is not None and normalized == cleaned_candidate.casefold():
            return None
    return cleaned


def _title_page_title(first_page_text: str) -> str | None:
    """The title page's own first substantive line, when the page carries
    one -- the deterministic fallback for `title` when embedded metadata
    carries none (§7.13). Bounded to the page's very first non-blank line
    within a sane length: a real title page opens with the title, and
    scanning further risks picking up a subtitle, author line, or publisher
    boilerplate instead -- a body paragraph mistaken for a title line is
    rejected on length rather than stored."""
    for line in first_page_text.splitlines():
        candidate = _clean(line)
        if candidate is None:
            continue
        return candidate if 2 <= len(candidate) <= _MAX_TITLE_LINE_CHARS else None
    return None


def _title_page_date(first_page_text: str) -> str | None:
    """A publication year read off the title page's own copyright/
    publication line (`_COPYRIGHT_YEAR_RE`), or `None` when the page states
    none -- the only mechanism `date` ever reads from (see that pattern's
    own docstring for why embedded file-creation dates are never used)."""
    match = _COPYRIGHT_YEAR_RE.search(first_page_text)
    return match.group(1) if match else None


def _bibliographic_field(value: str | None, provenance: str) -> dict[str, str] | str:
    """The §7.13 field shape for a resolved `value`: `{"value", "provenance"}`
    when a real value was found, else the `UNAVAILABLE` sentinel -- the read
    was attempted (this function is only ever called after an attempt), and
    nothing recoverable was found."""
    return {"value": value, "provenance": provenance} if value else UNAVAILABLE


def read_bibliographic_fields(
    fmt: str, path: Path, page_texts: list[str]
) -> dict[str, dict[str, str] | str]:
    """Read author/title/date at intake (§7.13): the PDF's own embedded
    document metadata first, then -- for a PDF's `title`/`date` only -- the
    title page's own text already in hand from the P0-1 read
    (`page_texts[0]`). Never the filename. A DOCX exposes no title-page
    equivalent to a physical first page and no valid `date` provenance at
    all in this slice (its own `created`/`modified` properties are file
    timestamps, not a publication date, exactly like a PDF's CreationDate) --
    its `date` is `NOT_ATTEMPTED` rather than a guessed `UNAVAILABLE`,
    naming plainly that no mechanism was even tried."""
    if fmt == "pdf":
        info = PdfReader(str(path)).metadata
        author_meta = info.author if info else None
        title_meta = info.title if info else None
        junk = (info.producer if info else None, info.creator if info else None)

        author = _plausible_metadata_value(author_meta, *junk)
        title = _plausible_metadata_value(title_meta, *junk)

        first_page = page_texts[0] if page_texts else ""
        if title is not None:
            title_provenance = PROVENANCE_EMBEDDED_METADATA
        else:
            title = _title_page_title(first_page)
            title_provenance = PROVENANCE_TITLE_PAGE

        date = _title_page_date(first_page)

        return {
            "author": _bibliographic_field(author, PROVENANCE_EMBEDDED_METADATA),
            "title": _bibliographic_field(title, title_provenance),
            "date": _bibliographic_field(date, PROVENANCE_TITLE_PAGE),
        }

    if fmt == "docx":
        props = Document(str(path)).core_properties
        author = _plausible_metadata_value(props.author)
        title = _plausible_metadata_value(props.title)
        return {
            "author": _bibliographic_field(author, PROVENANCE_EMBEDDED_METADATA),
            "title": _bibliographic_field(title, PROVENANCE_EMBEDDED_METADATA),
            "date": NOT_ATTEMPTED,
        }

    raise ValueError(f"unknown format {fmt!r}")  # pragma: no cover - guarded by check_extension


def _resolve_holdings_flag(
    computed_flag: dict | None, client: LLMClient | None, meta_path: Path
) -> dict | None:
    """The `holdings_flag` value to WRITE into the record on this call --
    distinct from `Source.holdings_flag`, the per-call return value, which
    stays exactly `computed_flag` (unchanged contract, see `intake`'s own
    docstring).

    A caller that supplies no `client` never re-runs the holdings judgment
    (it is a paid model call, §7.11): `computed_flag` is unconditionally
    `None` then. Writing that `None` straight through would silently erase
    an already-recorded flag the next time any client-less caller
    re-validates the same source -- and `extract()` does exactly that on
    every call, including from inside envelope regeneration -- which is
    precisely the loss §7.12 rules out ("does not lose ... the holdings
    flag"). So a client-less call instead PRESERVES whatever `holdings_flag`
    the existing on-disk record already carries (`None` if there is no
    existing record, or none was ever raised). A call that DID supply a
    client always writes its own freshly computed answer, including `None`
    for a source freshly judged complete -- that is a real decision, not an
    absence of one, and must overwrite a stale flag from an earlier,
    now-superseded judgment."""
    if client is not None:
        return computed_flag
    if not meta_path.exists():
        return None
    try:
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return existing.get("holdings_flag") if isinstance(existing, dict) else None


def build_source_meta(
    source_id: str,
    path: Path,
    fmt: str,
    physical_pages: int | None,
    holdings_flag: dict | None,
    page_texts: list[str],
) -> dict[str, Any]:
    """Assemble the §7.12 source-metadata record: the full sha256 file hash,
    the physical page count (present for a PDF, an explicit `null` for a
    DOCX -- distinct from a numeric zero), the §7.11 holdings flag in full
    or an explicit no-flag, and the §7.13 bibliographic fields. Carries no
    source text (DEC-23): values and short reasons only."""
    from axial.envelope import content_digest  # local import: dodges the
    # envelope -> extract -> intake import cycle (mirrors extract.py's own
    # local `compute_source_id` import, same reason).

    record: dict[str, Any] = {
        "source_id": source_id,
        "file_hash": content_digest(path),
        "physical_page_count": physical_pages,
        "holdings_flag": holdings_flag,
    }
    record.update(read_bibliographic_fields(fmt, path, page_texts))
    return record


def write_source_meta(record: dict[str, Any], path: Path) -> None:
    """Write the source-metadata record JSON, creating parent directories as
    needed (mirrors `axial.envelope.write_envelope`'s own convention)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def intake(
    path: str | Path,
    *,
    client: LLMClient | None = None,
    source_meta_dir: Path | None = None,
) -> Source:
    """Run intake on `path`: validate extension, verify a text layer, and --
    when `client` is given -- run the holdings-completeness check
    (§7.11/§8 P0-1b) and attach its flag. A raised flag is flag-only: it
    never raises, never rejects, and the source still completes intake
    exactly as an unflagged one would.

    A DOCX is checked too (the earlier blanket DOCX exemption is retired,
    §7.11); it exposes no physical page count, which the check handles as
    unobtainable evidence rather than as damning.

    Every successful call also writes the persisted source-metadata record
    (§7.12/§7.13) to `<source_meta_dir>/<source_id>.json` -- `source_meta_dir`
    defaults to `SOURCE_META_DIR` -- before returning, so the record exists
    before any extraction runs. This is unconditional and does not depend on
    `client`: the page count, file hash, and bibliographic fields are
    model-free and always read; only `holdings_flag` depends on whether this
    call ran the judgment (see `_resolve_holdings_flag`)."""
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

    # §7.12/§7.13, §8 P0-1c/P0-1d: local import dodges the
    # envelope -> extract -> intake import cycle (see build_source_meta's
    # own docstring for the identical reasoning extract.py already follows).
    from axial.envelope import compute_source_id

    source_id = compute_source_id(path)
    meta_dir = source_meta_dir if source_meta_dir is not None else SOURCE_META_DIR
    meta_path = source_meta_path(source_id, meta_dir)
    written_flag = _resolve_holdings_flag(holdings_flag, client, meta_path)
    record = build_source_meta(source_id, path, fmt, physical_pages, written_flag, page_texts)
    write_source_meta(record, meta_path)

    return Source(path=path, format=fmt, text_layer_ok=True, holdings_flag=holdings_flag)
