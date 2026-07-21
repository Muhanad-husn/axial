"""Outer acceptance test for issue #285, slice 02 (intake-metadata):
the persisted source-metadata record (PRD §7.12/§7.13, §8 P0-1c/P0-1d).

Given a source file processed through intake, with its holdings flag
      decided (slice 01, #284)
When  intake runs before any extraction
Then  a JSON record exists at `data/source_meta/<source_id>.json`, keyed by
      the same source_id the tree/envelope/chunk use
And   it carries the physical page count (where the format exposes one),
      the full sha256 file hash, and the §7.11 holdings flag in full or an
      explicit no-flag
And   it carries author, title and date, each as a value-with-provenance,
      `unavailable`, or `not_attempted`, never the filename slug
And   it contains no source text and no verbatim title-page or contents
      transcription
And   regenerating (or deleting and regenerating) the source's envelope
      leaves the record byte-unchanged
And   the holdings flag is readable from the record after intake without
      re-running the holdings check

See specs/PRODUCT.md §7.12 (persisted source-metadata record), §7.13
(bibliographic metadata read at intake), and §8 P0-1c/P0-1d for the source
of truth.

Seam decisions
-----------------------------------------------------------------------
1. Fixture PDFs are hand-built in-module by a minimal from-scratch writer
   (`_make_pdf`, extended from `test_holdings_model_adjudicated.py`'s own
   with an optional `/Info` metadata dictionary), under pytest's `tmp_path`.
   `reportlab` is not a project dependency (only an ephemeral fixture-
   authoring tool for the committed `tests/fixtures/intake/*` binaries) and
   no binary fixture with a hand-authored title/copyright block is
   committed here (repo policy forbids committing source text; DEC-23).
2. `axial.intake.intake()` is called directly (not through the CLI): the
   record's fields need structured assertions a CLI text scrape cannot
   give, mirroring test_holdings_model_adjudicated.py's own seam decision 2.
3. Every test passes an explicit `source_meta_dir` (a `tmp_path` subdirectory)
   to `intake()`, so this file never reads or writes the real repo's
   `data/source_meta/` -- fully hermetic, no reliance on tests/conftest.py's
   shared-state snapshot/restore fixture (that fixture still protects the
   *other*, pre-existing tests that call `intake()`/`extract()` without an
   explicit override; see its own updated docstring).
4. The "survives envelope regeneration" test drives `axial.envelope.run_envelope`
   in-process with an injected stub client and an explicit `envelopes_dir`,
   and pre-places a minimal tree dict at a `tmp_path`-redirected
   `axial.extract.TREES_DIR` so `extract()`'s internal cache check short-
   circuits before ever invoking real docling (mirroring
   tests/ingestion/test_envelope.py's own pre-placed-tree convention) --
   and also redirects `axial.intake.SOURCE_META_DIR` so `extract()`'s own
   internal, client-less `intake()` call (real production wiring: every
   `extract()` call validates via `intake()` first) never touches this
   test's own explicit record either.
"""

from __future__ import annotations

import builtins
import json
import pathlib
from pathlib import Path

import axial.extract as extract_mod
import axial.intake as intake_mod
from axial.envelope import compute_source_id, run_envelope
from axial.intake import intake

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXISTING_TEXT_DOCX = REPO_ROOT / "tests" / "fixtures" / "intake" / "text.docx"


# =============================================================================
# Recorded/stub LLM clients (no network)
# =============================================================================


class _RecordedHoldingsClient:
    """Replays one recorded holdings verdict -- and, optionally, a title-page
    bibliographic reading (issue #285: the same combined call now covers
    both) -- and counts calls."""

    def __init__(
        self,
        verdict: str,
        reason: str = "stub reason for the record test",
        *,
        title_page_title: str | None = None,
        title_page_author: str | None = None,
        title_page_date: str | None = None,
        author_metadata_matches: bool | None = None,
        title_metadata_matches: bool | None = None,
    ):
        self._response = json.dumps(
            {
                "document_kind": "book",
                "claimed_extent": "300 pages",
                "claimed_extent_stated_by": "printed contents page",
                "verdict": verdict,
                "reason": reason,
                "title_page_title": title_page_title,
                "title_page_author": title_page_author,
                "title_page_date": title_page_date,
                "author_metadata_matches": author_metadata_matches,
                "title_metadata_matches": title_metadata_matches,
            }
        )
        self.calls = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls += 1
        return self._response


class _StubEnvelopeClient:
    """A minimal, always-valid canned envelope response -- the tree content
    is irrelevant here since this file's only interest is whether the
    source-metadata record is disturbed by an envelope run, never the
    envelope's own content (that is tests/ingestion/test_envelope.py's
    contract)."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        return json.dumps(
            {
                "thesis": "A stated thesis, only present so the envelope pass validates.",
                "toc": [{"title": "Chapter One", "children": []}],
                "scope": "A stated scope.",
                "stated_argument": "The argument as restated.",
            }
        )


# =============================================================================
# Minimal from-scratch PDF writer, extended with an optional /Info dict
# (see Seam decision 1) -- adapted from test_holdings_model_adjudicated.py's
# own `_make_pdf`/`_write_pdf`/`_content_stream_for_page`/`_escape_pdf_text`.
# =============================================================================


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream_for_page(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 10 Tf", "72 750 Td"]
    for index, line in enumerate(lines):
        if index > 0:
            parts.append("0 -14 Td")
        parts.append(f"({_escape_pdf_text(line)}) Tj")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1")
    header = f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
    return header + stream + b"\nendstream"


def _info_dict_bytes(info: dict[str, str]) -> bytes:
    parts = " ".join(f"/{key} ({_escape_pdf_text(value)})" for key, value in info.items())
    return f"<< {parts} >>".encode("latin-1")


def _make_pdf(pages_lines: list[list[str]], info: dict[str, str] | None = None) -> bytes:
    """Build a minimal, valid, born-digital PDF: one page per element of
    `pages_lines`, optionally carrying an `/Info` document-metadata
    dictionary (`info`, e.g. `{"Author": ..., "Title": ..., "Producer": ...}`)."""
    n = len(pages_lines)
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{4 + i} 0 R' for i in range(n))}] "
        f"/Count {n} >>".encode("ascii"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, lines in enumerate(pages_lines):
        page_obj_num = 4 + i
        content_obj_num = 4 + n + i
        objects[page_obj_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_obj_num} 0 R >>"
        ).encode("ascii")
        objects[content_obj_num] = _content_stream_for_page(lines)

    max_obj = 3 + 2 * n
    info_obj_num = None
    if info:
        max_obj += 1
        info_obj_num = max_obj
        objects[info_obj_num] = _info_dict_bytes(info)

    buf = bytearray(header)
    offsets: dict[int, int] = {}
    for obj_num in range(1, max_obj + 1):
        offsets[obj_num] = len(buf)
        buf.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        buf.extend(objects[obj_num])
        buf.extend(b"\nendobj\n")

    xref_offset = len(buf)
    buf.extend(f"xref\n0 {max_obj + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for obj_num in range(1, max_obj + 1):
        buf.extend(f"{offsets[obj_num]:010d} 00000 n \n".encode("ascii"))
    trailer = f"<< /Size {max_obj + 1} /Root 1 0 R"
    if info_obj_num is not None:
        trailer += f" /Info {info_obj_num} 0 R"
    trailer += " >>"
    buf.extend(f"trailer\n{trailer}\nstartxref\n{xref_offset}\n%%EOF".encode("ascii"))
    return bytes(buf)


def _write_pdf(
    tmp_path: Path, name: str, pages_lines: list[list[str]], info: dict[str, str] | None = None
) -> Path:
    path = tmp_path / name
    path.write_bytes(_make_pdf(pages_lines, info=info))
    return path


def _body(index: int) -> list[str]:
    return [f"Ordinary body prose on page {index}, discussing the case in general terms."]


# =============================================================================
# Corpus-shaped fixtures
# =============================================================================

# A real, LaTeX-typeset book: distinct author/title, unambiguous producer
# so the junk filter never touches it.
REAL_METADATA_BOOK = [
    ["State Legitimacy and Civil Conflict", "An Institutional History", "1985"],
] + [_body(i) for i in range(1, 4)]

REAL_METADATA_INFO = {
    "Author": "Jane Q. Historian",
    "Title": "State Legitimacy and Civil Conflict",
    "Producer": "pdfTeX-1.40.21",
    "Creator": "LaTeX with hyperref package",
}

# No embedded title/author at all -- the title-page fallback must carry the
# whole read. The first line is the printed title; a later line states the
# publication year next to a copyright marker.
TITLE_PAGE_ONLY_BOOK = [
    [
        "The Long Road to Damascus",
        "A Political History",
        "Copyright © 1971 by the University Press",
    ],
    [
        "A long, ordinary paragraph of body prose that must never leak "
        "verbatim into the source-metadata record (DEC-23)."
    ],
]

# A producer string reused as the author -- must be filtered to unavailable,
# never passed through.
PRODUCER_AS_AUTHOR_INFO = {
    "Author": "Adobe Acrobat Pro DC 22.1",
    "Producer": "Adobe Acrobat Pro DC 22.1",
    "Creator": "Adobe Acrobat Pro DC 22.1",
    "Title": "A Perfectly Fine Title",
    "CreationDate": "D:20220101000000",
}

NO_COPYRIGHT_LINE_BOOK = [["A Perfectly Fine Title", "Some front matter with no year stated."]]

# Embedded metadata naming an entirely different, unrelated book -- the
# recycled-metadata pattern behind issue #285 finding 2
# (`heydemann-war-institutions-social-change`): the file's own front matter
# (TITLE_PAGE_ONLY_BOOK) states one book; its embedded metadata claims
# another.
RECYCLED_METADATA_INFO = {
    "Author": "Michael Hanby",
    "Title": "Augustine and Modernity",
    "Producer": "pdfTeX-1.40.21",
    "Creator": "LaTeX with hyperref package",
}


# =============================================================================
# Tests
# =============================================================================


def test_record_written_before_extraction_keyed_by_source_id(tmp_path):
    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"

    intake(path, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record_path = meta_dir / f"{source_id}.json"
    assert record_path.exists(), "expected the source-metadata record to exist after intake"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["source_id"] == source_id


def test_record_is_written_without_a_tree_or_envelope_file_existing(tmp_path, monkeypatch):
    """§7.12: the record is written before extraction -- no tree file, and
    no envelope file, needs to exist for it to be written (mirrors
    test_holdings_model_adjudicated.py's identical guard for the flag
    itself)."""
    forbidden = ("data/trees", "data\\trees", "data/envelopes", "data\\envelopes")
    real_open, real_path_open = builtins.open, pathlib.Path.open

    def _guard(name: object) -> None:
        text = str(name)
        for fragment in forbidden:
            assert fragment not in text, f"writing the source-metadata record opened {text!r}"

    def _checked_open(file, *args, **kwargs):
        _guard(file)
        return real_open(file, *args, **kwargs)

    def _checked_path_open(self, *args, **kwargs):
        _guard(self)
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _checked_open)
    monkeypatch.setattr(pathlib.Path, "open", _checked_path_open)

    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"

    intake(path, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    assert (meta_dir / f"{source_id}.json").exists()


def test_record_carries_page_count_hash_and_holdings_flag_in_full(tmp_path):
    from axial.envelope import content_digest

    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(verdict="partial")

    intake(path, client=client, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["physical_page_count"] == len(REAL_METADATA_BOOK)
    assert record["file_hash"] == content_digest(path)
    flag = record["holdings_flag"]
    assert flag["document_kind"] == "book"
    assert flag["claimed_extent"] == "300 pages"
    assert flag["claimed_extent_stated_by"] == "printed contents page"
    assert flag["observed_pages"] == len(REAL_METADATA_BOOK)
    assert "stub reason" in flag["reason"]


def test_a_complete_source_stores_an_explicit_no_flag_not_an_absent_key(tmp_path):
    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(verdict="complete")

    intake(path, client=client, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    raw_text = (meta_dir / f"{source_id}.json").read_text(encoding="utf-8")
    record = json.loads(raw_text)

    assert "holdings_flag" in record, "expected an explicit key, not an absent one"
    assert record["holdings_flag"] is None
    assert '"holdings_flag": null' in raw_text


def test_the_holdings_flag_is_readable_after_intake_without_rerunning_the_check(tmp_path):
    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(verdict="partial")

    intake(path, client=client, source_meta_dir=meta_dir)
    assert client.calls == 1

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    # Read the flag straight off the persisted record -- no client, no
    # re-running the check.
    assert record["holdings_flag"]["document_kind"] == "book"
    assert client.calls == 1


def test_docx_page_count_is_explicitly_absent_not_a_numeric_zero(tmp_path):
    meta_dir = tmp_path / "source_meta"

    intake(EXISTING_TEXT_DOCX, source_meta_dir=meta_dir)

    source_id = compute_source_id(EXISTING_TEXT_DOCX)
    raw_text = (meta_dir / f"{source_id}.json").read_text(encoding="utf-8")
    record = json.loads(raw_text)

    assert "physical_page_count" in record
    assert record["physical_page_count"] is None
    assert record["physical_page_count"] != 0
    assert '"physical_page_count": null' in raw_text


def test_bibliographic_fields_read_from_embedded_metadata(tmp_path):
    path = _write_pdf(
        tmp_path, "unrelated_filename_slug.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO
    )
    meta_dir = tmp_path / "source_meta"

    intake(path, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["author"] == {"value": "Jane Q. Historian", "provenance": "embedded metadata"}
    assert record["title"] == {
        "value": "State Legitimacy and Civil Conflict",
        "provenance": "embedded metadata",
    }
    # The filename is never a source (§7.13): the printed title survives
    # even though the filename slug names something else entirely.
    assert "unrelated_filename_slug" not in json.dumps(record["title"])


def test_title_page_fallback_and_date_and_filename_never_a_source(tmp_path):
    """The title-page fallback (issue #285) is now the model's own reading
    of the front matter, reusing the holdings check's one combined call --
    replacing the retired first-non-blank-line/copyright-regex heuristic
    (#268's own pattern, measured right in only 2 of 13 real cases). A
    client is required to produce it, exactly like the holdings flag
    itself; a client-less call is covered separately below
    (`test_bibliographic_fields_read_from_embedded_metadata` and
    `test_client_less_call_never_produces_a_title_page_reading`)."""
    path = _write_pdf(tmp_path, "totally_different_name.pdf", TITLE_PAGE_ONLY_BOOK)
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(
        verdict="complete",
        title_page_title="The Long Road to Damascus",
        title_page_date="1971",
    )

    intake(path, client=client, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["title"] == {
        "value": "The Long Road to Damascus",
        "provenance": "title page",
    }
    assert record["date"] == {"value": "1971", "provenance": "title page"}
    # No embedded author anywhere, and the model's title-page read named
    # none either -- attempted, nothing recoverable.
    assert record["author"] == "unavailable"
    assert "totally_different_name" not in json.dumps(record["title"])


def test_client_less_call_never_produces_a_title_page_reading(tmp_path):
    """The title-page read is a model call and runs only for a caller that
    supplies a client, mirroring `holdings_flag` -- a client-less call
    (every `extract()` validation call) must not fabricate a "title page"
    provenance value it never actually read."""
    path = _write_pdf(tmp_path, "totally_different_name.pdf", TITLE_PAGE_ONLY_BOOK)
    meta_dir = tmp_path / "source_meta"

    intake(path, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["title"] == "unavailable"
    assert record["date"] == "unavailable"


def test_embedded_metadata_naming_a_different_book_is_recorded_as_unavailable(tmp_path):
    """Issue #285 finding 2, the required outcome: recycled embedded
    metadata for an unrelated book is never recorded as a value with
    provenance -- only a model that reads the title page can notice the
    mismatch, so the cross-check is what makes this fixable at all."""
    path = _write_pdf(
        tmp_path,
        "heydemann-war-institutions-social-change.pdf",
        TITLE_PAGE_ONLY_BOOK,
        info=RECYCLED_METADATA_INFO,
    )
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(
        verdict="complete",
        title_page_title="The Long Road to Damascus",
        author_metadata_matches=False,
        title_metadata_matches=False,
    )

    intake(path, client=client, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["author"] == "unavailable"
    assert record["title"] == "unavailable"
    serialized = json.dumps(record)
    assert "Michael Hanby" not in serialized
    assert "Augustine and Modernity" not in serialized


def test_embedded_metadata_confirmed_by_the_title_page_still_stands(tmp_path):
    """The cross-check is additive, not a new way to lose a previously-
    working answer: embedded metadata the model reads and confirms is
    recorded exactly as before the check existed."""
    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(
        verdict="complete",
        title_page_author="Jane Q. Historian",
        title_page_title="State Legitimacy and Civil Conflict",
        author_metadata_matches=True,
        title_metadata_matches=True,
    )

    intake(path, client=client, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["author"] == {"value": "Jane Q. Historian", "provenance": "embedded metadata"}
    assert record["title"] == {
        "value": "State Legitimacy and Civil Conflict",
        "provenance": "embedded metadata",
    }


def test_junk_embedded_metadata_is_recorded_as_unavailable_not_passed_through(tmp_path):
    path = _write_pdf(tmp_path, "book.pdf", NO_COPYRIGHT_LINE_BOOK, info=PRODUCER_AS_AUTHOR_INFO)
    meta_dir = tmp_path / "source_meta"

    intake(path, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    # Author == Producer == Creator: a producer string reused as the
    # author, never passed through as a value.
    assert record["author"] == "unavailable"
    # The plausible, distinct Title still comes through.
    assert record["title"] == {"value": "A Perfectly Fine Title", "provenance": "embedded metadata"}
    # The embedded CreationDate is a file-creation timestamp, never a valid
    # `date` provenance -- it must never leak through as the recorded date,
    # and with no copyright line on the page, the title-page read finds
    # nothing either.
    assert record["date"] == "unavailable"
    assert "20220101" not in json.dumps(record)


def test_empty_embedded_author_is_recorded_as_unavailable(tmp_path):
    info = {"Author": "", "Title": "A Title That Exists", "Producer": "Some PDF Tool"}
    path = _write_pdf(tmp_path, "book.pdf", NO_COPYRIGHT_LINE_BOOK, info=info)
    meta_dir = tmp_path / "source_meta"

    intake(path, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["author"] == "unavailable"
    assert record["title"]["value"] == "A Title That Exists"


def test_docx_bibliographic_fields_from_core_properties_and_date_not_attempted(tmp_path):
    from docx import Document

    docx_path = tmp_path / "real_metadata.docx"
    document = Document()
    document.add_paragraph("Axial intake fixture: this DOCX has real body text.")
    document.core_properties.author = "Jane Q. Historian"
    document.core_properties.title = "A Real Docx Title"
    document.save(str(docx_path))

    meta_dir = tmp_path / "source_meta"
    intake(docx_path, source_meta_dir=meta_dir)

    source_id = compute_source_id(docx_path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))

    assert record["author"] == {"value": "Jane Q. Historian", "provenance": "embedded metadata"}
    assert record["title"] == {"value": "A Real Docx Title", "provenance": "embedded metadata"}
    # No mechanism exists for a DOCX's publication date in this slice
    # (its own `created`/`modified` properties are file timestamps, exactly
    # like a PDF's CreationDate) -- distinguishable from "unavailable".
    assert record["date"] == "not_attempted"


def test_record_contains_no_source_text_or_verbatim_body_prose(tmp_path):
    path = _write_pdf(tmp_path, "book.pdf", TITLE_PAGE_ONLY_BOOK)
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(
        verdict="partial", reason="A short, non-quoting reason for the flag."
    )

    intake(path, client=client, source_meta_dir=meta_dir)

    source_id = compute_source_id(path)
    serialized = (meta_dir / f"{source_id}.json").read_text(encoding="utf-8")

    body_line = (
        "A long, ordinary paragraph of body prose that must never leak "
        "verbatim into the source-metadata record (DEC-23)."
    )
    assert body_line not in serialized


def test_rerunning_intake_on_unchanged_bytes_overwrites_with_equivalent_content(tmp_path):
    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"
    client = _RecordedHoldingsClient(verdict="complete")

    intake(path, client=client, source_meta_dir=meta_dir)
    source_id = compute_source_id(path)
    record_path = meta_dir / f"{source_id}.json"
    first_bytes = record_path.read_bytes()

    intake(path, client=_RecordedHoldingsClient(verdict="complete"), source_meta_dir=meta_dir)
    second_bytes = record_path.read_bytes()

    assert first_bytes == second_bytes


def test_an_edited_source_gets_its_own_record_never_inheriting_a_stale_one(tmp_path):
    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"
    original_id = compute_source_id(path)

    intake(path, client=_RecordedHoldingsClient(verdict="partial"), source_meta_dir=meta_dir)
    original_record_path = meta_dir / f"{original_id}.json"
    assert original_record_path.exists()

    edited_pages = REAL_METADATA_BOOK + [_body(99)]
    path.write_bytes(_make_pdf(edited_pages, info=REAL_METADATA_INFO))
    edited_id = compute_source_id(path)
    assert edited_id != original_id

    intake(path, source_meta_dir=meta_dir)

    # The stale record from before the edit is untouched -- its own
    # holdings flag is not silently inherited by the new source_id.
    assert original_record_path.exists()
    original_record = json.loads(original_record_path.read_text(encoding="utf-8"))
    assert original_record["holdings_flag"]["document_kind"] == "book"

    new_record = json.loads((meta_dir / f"{edited_id}.json").read_text(encoding="utf-8"))
    assert new_record["holdings_flag"] is None


def test_holdings_flag_survives_a_later_client_less_intake_call(tmp_path):
    """Real production wiring: `extract()` (and therefore every
    envelope/chunk/tag pass built on it) revalidates via a client-less
    `intake()` call on every invocation. That call must never silently wipe
    an already-recorded holdings flag (§7.12: "does not lose ... the
    holdings flag")."""
    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"

    intake(path, client=_RecordedHoldingsClient(verdict="partial"), source_meta_dir=meta_dir)

    # A later, client-less call (mirroring extract()'s own internal
    # validation-only intake() call) must not erase the flag on disk, even
    # though ITS OWN returned Source.holdings_flag is None (unchanged
    # contract for that call).
    later_source = intake(path, source_meta_dir=meta_dir)
    assert later_source.holdings_flag is None

    source_id = compute_source_id(path)
    record = json.loads((meta_dir / f"{source_id}.json").read_text(encoding="utf-8"))
    assert record["holdings_flag"] is not None
    assert record["holdings_flag"]["document_kind"] == "book"


def test_record_survives_envelope_regeneration_byte_unchanged(tmp_path, monkeypatch):
    """§7.12/P0-1c's own stated observable: regenerating -- or deleting and
    regenerating -- the source's envelope leaves the source-metadata record
    byte-unchanged."""
    # Full hermeticity (Seam decision 4): redirect both the tree cache and
    # intake's OWN default source_meta directory (the one extract()'s
    # internal, client-less intake() call writes into) away from the real
    # repo `data/` tree.
    monkeypatch.setattr(extract_mod, "TREES_DIR", tmp_path / "trees")
    monkeypatch.setattr(intake_mod, "SOURCE_META_DIR", tmp_path / "default_source_meta")

    path = _write_pdf(tmp_path, "book.pdf", REAL_METADATA_BOOK, info=REAL_METADATA_INFO)
    meta_dir = tmp_path / "source_meta"
    source_id = compute_source_id(path)

    intake(path, client=_RecordedHoldingsClient(verdict="partial"), source_meta_dir=meta_dir)
    record_path = meta_dir / f"{source_id}.json"
    original_bytes = record_path.read_bytes()

    # Pre-place a minimal tree so extract()'s cache check short-circuits
    # before ever invoking real docling (mirrors
    # tests/ingestion/test_envelope.py's own pre-placed-tree convention).
    tree_path = tmp_path / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps({"children": []}), encoding="utf-8")

    envelopes_dir = tmp_path / "envelopes"
    run_envelope(path, client=_StubEnvelopeClient(), envelopes_dir=envelopes_dir)

    assert record_path.read_bytes() == original_bytes

    # Delete and regenerate.
    (envelopes_dir / f"{source_id}.json").unlink()
    run_envelope(path, client=_StubEnvelopeClient(), envelopes_dir=envelopes_dir)

    assert record_path.read_bytes() == original_bytes
