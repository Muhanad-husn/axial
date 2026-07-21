"""Outer acceptance test for issue #284: the model-adjudicated
holdings-completeness check (PRD §7.11, §8 P0-1b).

Given the corpus-shaped holdings fixtures and a recorded LLM client for the
      holdings pass
When  the holdings check runs at intake on each source
Then  it flags exactly the two partial holdings and no others (2 true
      positives, 0 false positives, 0 false negatives)
And   each flag records the concluded document kind, the claimed extent with
      what stated it, the observed physical page count, and the model's
      stated reason -- never a bare boolean, and no source text
And   a complete research paper carrying no contents page passes with no flag
And   on the `tilly` source, whose contents heading extracts as
      `viii Contents`, the text handed to the model carries the heading
      without the folio
And   a flagged source still completes intake and is returned exactly as an
      unflagged source, reading neither the structural tree nor the envelope

What this test does and does not pin
-----------------------------------------------------------------------
The recorded answers below are **real model outputs**, captured verbatim
from the #284 measurement run over `data/sources/`. Replaying them here
pins the machinery around the judgment: the deterministic cleaning, the
single holdings-pass call, the flag shape, the DEC-23 no-source-text rule,
and the flag-only discipline. It does not pin the judgment itself -- a
corpus-facing model call is measured on the real corpus, and that
measurement (2 TP, 0 FP, 0 FN over the 30 sources plus the two
reconstructed truncations) is recorded in the PR, not asserted here.

Seam decisions
-----------------------------------------------------------------------
1. Fixture PDFs are hand-built in-module by a minimal from-scratch writer
   (`_make_pdf`), under pytest's `tmp_path`. `reportlab` is an ephemeral
   fixture-authoring tool in this repo, not a test-time dependency, and no
   binary fixture is committed (repo policy forbids committing source text;
   DEC-23). Carried over unchanged from the retired
   test_holdings_completeness_probe.py, which built its fixtures the same
   way.
2. `axial.intake.intake()` is called directly (not through the CLI): the
   flag's recorded values need structured assertions a CLI text scrape
   cannot give, and the check has no CLI surface of its own in this slice.
3. The LLM client is injected per source (`intake(path, client=...)`), so
   the test never touches the network and never depends on provider
   configuration.
"""

from __future__ import annotations

import builtins
import json
import pathlib
from pathlib import Path

import pytest

from axial.intake import intake
from axial.llm import HOLDINGS_PASS_NAME

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXISTING_TEXT_DOCX = REPO_ROOT / "tests" / "fixtures" / "intake" / "text.docx"


# =============================================================================
# Recorded model answers (verbatim from the #284 corpus measurement)
# =============================================================================

RECORDED_TRUNCATED_VOLUME = json.dumps(
    {
        "document_kind": "book",
        "claimed_extent": "816 pages",
        "claimed_extent_stated_by": "printed contents page",
        "verdict": "partial",
        "reason": (
            "The contents page claims 816 pages, but the file has only 85 pages "
            "and ends mid-sentence, far short of that extent."
        ),
    }
)

RECORDED_FRAGMENT = json.dumps(
    {
        "document_kind": "fragment",
        "claimed_extent": None,
        "claimed_extent_stated_by": None,
        "verdict": "partial",
        "reason": (
            "The file contains only the first 20 pages of a book, stopping "
            "mid-introduction with no conclusion or end matter."
        ),
    }
)

RECORDED_COMPLETE_BOOK = json.dumps(
    {
        "document_kind": "book",
        "claimed_extent": "411 pages",
        "claimed_extent_stated_by": "printed contents page",
        "verdict": "complete",
        "reason": "The file runs past the last page the contents states and ends with an index.",
    }
)

RECORDED_COMPLETE_PAPER = json.dumps(
    {
        "document_kind": "research_paper",
        "claimed_extent": None,
        "claimed_extent_stated_by": None,
        "verdict": "complete",
        "reason": "A journal article with an abstract and a full reference list; papers carry no contents page.",
    }
)


class _RecordedClient:
    """Replays one recorded answer and records every call it received."""

    def __init__(self, response: str):
        self._response = response
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append((prompt, pass_name))
        return self._response


# =============================================================================
# Minimal from-scratch PDF writer (see Seam decision 1)
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


def _make_pdf(pages_lines: list[list[str]]) -> bytes:
    """Build a minimal, valid, born-digital PDF: one page per element of
    `pages_lines`. `len(pages_lines)` IS the resulting `pypdf` page count."""
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
    buf.extend(
        f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode(
            "ascii"
        )
    )
    return bytes(buf)


def _write_pdf(tmp_path: Path, name: str, pages_lines: list[list[str]]) -> Path:
    path = tmp_path / name
    path.write_bytes(_make_pdf(pages_lines))
    return path


# =============================================================================
# Corpus-shaped fixtures
# =============================================================================


def _body(index: int) -> list[str]:
    return [f"Ordinary body prose on page {index}, discussing the case in general terms."]


# A truncated volume of a multi-volume set: its printed contents page states
# an extent the file cannot cover (a scaled proxy of Mann vol. 2).
TRUNCATED_VOLUME = [
    ["Contents", "Chapter One 1", "Chapter Two 250", "Chapter Three 816"],
] + [_body(i) for i in range(1, 6)]

# A chapter circulated as if it were the book: no title page, no contents,
# breaks off mid-argument with no back matter (a proxy of Ungor).
CHAPTER_FRAGMENT = [_body(i) for i in range(4)]

# A complete book: contents accounted for, index at the end.
COMPLETE_BOOK = (
    [["Contents", "Introduction 1", "Chapter One 3", "Index 11"]]
    + [_body(i) for i in range(1, 11)]
    + [["Index", "state formation, 12, 45, 88-91", "civil society, 33, 67, 102"]]
)

# A complete research paper: no contents page at all, abstract and full
# reference list. This is the distinction that forces model adjudication.
RESEARCH_PAPER = (
    [["State legitimacy and capacity in the Syrian conflict", "Abstract", "This article argues."]]
    + [_body(i) for i in range(1, 7)]
    + [["References", "Bayat, A. (2010) Life as Politics. Stanford University Press."]]
)

# The `tilly` case: a running head stitched to its folio by text extraction.
TILLY_FOLIOS = [
    ["vi Preface", "My friends will recognize this book for what it is."],
    ["vii Preface", "Several sections first took shape as memoranda."],
    ["viii Contents", "1 INTRODUCTION 1", "2 THEORIES OF COLLECTIVE ACTION 12"],
    ["ix Contents", "3 INTERESTS, ORGANIZATION AND MOBILIZATION 52"],
] + [[f"{i} Chapter One", f"body prose on page {i}"] for i in range(10, 14)]


CORPUS = [
    ("truncated_volume.pdf", TRUNCATED_VOLUME, RECORDED_TRUNCATED_VOLUME, True),
    ("chapter_fragment.pdf", CHAPTER_FRAGMENT, RECORDED_FRAGMENT, True),
    ("complete_book.pdf", COMPLETE_BOOK, RECORDED_COMPLETE_BOOK, False),
    ("research_paper.pdf", RESEARCH_PAPER, RECORDED_COMPLETE_PAPER, False),
    ("tilly_folios.pdf", TILLY_FOLIOS, RECORDED_COMPLETE_BOOK, False),
]


# =============================================================================
# Tests
# =============================================================================


def test_flags_exactly_the_partial_holdings_and_no_others(tmp_path):
    flagged = []
    for name, pages, recorded, _ in CORPUS:
        path = _write_pdf(tmp_path, name, pages)
        source = intake(path, client=_RecordedClient(recorded))
        if source.holdings_flag is not None:
            flagged.append(name)

    assert flagged == ["truncated_volume.pdf", "chapter_fragment.pdf"], (
        "expected exactly the two partial holdings to be flagged -- 2 true "
        f"positives, 0 false positives, 0 false negatives -- got {flagged}"
    )


def test_a_flag_records_its_measurement_never_a_bare_boolean(tmp_path):
    path = _write_pdf(tmp_path, "truncated_volume.pdf", TRUNCATED_VOLUME)

    flag = intake(path, client=_RecordedClient(RECORDED_TRUNCATED_VOLUME)).holdings_flag

    assert flag["source"] == "truncated_volume.pdf"
    assert flag["document_kind"] == "book"
    assert flag["claimed_extent"] == "816 pages"
    assert flag["claimed_extent_stated_by"] == "printed contents page"
    assert flag["observed_pages"] == len(TRUNCATED_VOLUME)
    assert "816" in flag["reason"] and len(flag["reason"]) > 20


def test_a_flag_carries_no_source_text(tmp_path):
    """DEC-23: values and short reasons only -- no transcription of the
    title page or the contents page."""
    path = _write_pdf(tmp_path, "truncated_volume.pdf", TRUNCATED_VOLUME)

    flag = intake(path, client=_RecordedClient(RECORDED_TRUNCATED_VOLUME)).holdings_flag

    serialized = json.dumps(flag)
    for line in [line for page in TRUNCATED_VOLUME for line in page]:
        assert line not in serialized, f"flag carries verbatim source text: {line!r}"


def test_a_research_paper_with_no_contents_page_is_not_flagged(tmp_path):
    """The distinction that forces model adjudication: a paper legitimately
    has no contents page, and no threshold separates it from a truncated
    book (§7.11)."""
    path = _write_pdf(tmp_path, "research_paper.pdf", RESEARCH_PAPER)

    source = intake(path, client=_RecordedClient(RECORDED_COMPLETE_PAPER))

    assert source.holdings_flag is None


def test_the_tilly_folio_is_stripped_before_the_model_reads_the_heading(tmp_path):
    """§7.11's stated observable: `tilly`'s contents heading extracts as
    `viii Contents`, and the folio must not survive into the model's
    input."""
    path = _write_pdf(tmp_path, "tilly_folios.pdf", TILLY_FOLIOS)
    client = _RecordedClient(RECORDED_COMPLETE_BOOK)

    intake(path, client=client)

    prompt = client.calls[0][0]
    assert "viii Contents" not in prompt
    assert "Contents" in prompt.splitlines()


def test_exactly_one_model_call_is_made_on_the_holdings_pass(tmp_path):
    path = _write_pdf(tmp_path, "complete_book.pdf", COMPLETE_BOOK)
    client = _RecordedClient(RECORDED_COMPLETE_BOOK)

    intake(path, client=client)

    assert len(client.calls) == 1
    assert client.calls[0][1] == HOLDINGS_PASS_NAME


def test_a_flagged_source_completes_intake_exactly_as_an_unflagged_one(tmp_path):
    """§7.11: flag-only, never a reject. Calling `intake()` here without
    wrapping it in `pytest.raises` IS half the assertion."""
    flagged_path = _write_pdf(tmp_path, "truncated_volume.pdf", TRUNCATED_VOLUME)
    clean_path = _write_pdf(tmp_path, "complete_book.pdf", COMPLETE_BOOK)

    flagged = intake(flagged_path, client=_RecordedClient(RECORDED_TRUNCATED_VOLUME))
    clean = intake(clean_path, client=_RecordedClient(RECORDED_COMPLETE_BOOK))

    assert flagged.holdings_flag is not None
    assert clean.holdings_flag is None
    assert (flagged.format, flagged.text_layer_ok) == (clean.format, clean.text_layer_ok)
    assert flagged.path == flagged_path


def test_the_check_reads_neither_the_tree_nor_the_envelope(tmp_path, monkeypatch):
    """§8 P0-1b: the check reads the raw text layer only -- no tree or
    envelope file is read, and none needs to exist, for it to run."""
    forbidden = ("data/trees", "data\\trees", "data/envelopes", "data\\envelopes")
    real_open, real_path_open = builtins.open, pathlib.Path.open

    def _guard(name: object) -> None:
        text = str(name)
        for fragment in forbidden:
            assert fragment not in text, f"the holdings check opened {text!r}"

    def _checked_open(file, *args, **kwargs):
        _guard(file)
        return real_open(file, *args, **kwargs)

    def _checked_path_open(self, *args, **kwargs):
        _guard(self)
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _checked_open)
    monkeypatch.setattr(pathlib.Path, "open", _checked_path_open)

    path = _write_pdf(tmp_path, "truncated_volume.pdf", TRUNCATED_VOLUME)
    source = intake(path, client=_RecordedClient(RECORDED_TRUNCATED_VOLUME))

    assert source.holdings_flag is not None


def test_a_docx_is_checked_and_is_not_flagged_for_missing_coverage_evidence():
    """§7.11 retires the blanket DOCX exemption: the check runs on a DOCX,
    which exposes no physical page count, and that absent evidence is
    unobtainable rather than damning."""
    assert EXISTING_TEXT_DOCX.exists()
    client = _RecordedClient(RECORDED_COMPLETE_PAPER)

    source = intake(EXISTING_TEXT_DOCX, client=client)

    assert source.format == "docx"
    assert len(client.calls) == 1
    assert "unknown" in client.calls[0][0]
    assert source.holdings_flag is None


@pytest.mark.parametrize("name,pages,recorded,expect_flag", CORPUS)
def test_every_fixture_source_completes_intake(tmp_path, name, pages, recorded, expect_flag):
    path = _write_pdf(tmp_path, name, pages)

    source = intake(path, client=_RecordedClient(recorded))

    assert source.text_layer_ok is True
    assert (source.holdings_flag is not None) is expect_flag
