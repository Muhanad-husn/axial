"""Outer acceptance test for issue #268, slice 1 (the deterministic
holdings-completeness probe).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Spec: `specs/PRODUCT.md` §7.11 ("Holdings-completeness probe") and §8 P0-1b
for the source of truth. See also issue #268's pinned measurement-pass
comment for the numbers this test's fixtures are scaled proxies of (Mann
vol. 2 at COVER 0.10 against a lowest-complete-work floor of 1.03; Ungor as
the sole orphan-fragment true positive; bayat/heydemann-war as the
heading-regex false-positive guard for Signal B's back-matter test).

Given a source PDF whose printed contents page references a page well beyond
      the file's own physical page count
When  the source is ingested
Then  it is flagged as a suspected partial holding, the signal that fired is
      named `toc_page_extent`, and the flag carries the measured COVER ratio
      plus its inputs (physical page count, max page reference) and the
      threshold in force

Given a source PDF with no printed contents page, fewer than 120 physical
      pages, and no bibliography/index back matter in its tail
When  the source is ingested
Then  it is flagged with the `orphan_fragment` signal named, carrying the
      physical page count, the measured tail back-matter density, and the
      threshold in force

Given a source PDF containing a complete work (its contents page's own
      numbers fully accounted for, plus a decoy prose line that ends in a
      bare year with no dot leader)
When  the source is ingested
Then  no partial-holding flag is raised -- the decoy is not misread as an
      entry, and a healthy source's COVER lands comfortably above 1.0

Given a short source PDF with no contents page whose tail carries genuine
      reference-list and index back matter (the bayat/heydemann-war
      false-positive case a heading-regex test gets wrong)
When  the source is ingested
Then  no partial-holding flag is raised -- the content-based back-matter
      test recognizes it

Given a source PDF whose contents page exists but whose page-reference
      numbers are garbled/unreadable, and whose physical page count sits
      above the orphan-fragment ceiling regardless
When  the source is ingested
Then  no partial-holding flag is raised -- garbling degrades Signal A to "no
      reading" rather than a false fire, and the large page count keeps
      Signal B from ever being reachable, isolating the safe-direction
      property from Signal B's own (separately tuned) back-matter threshold

Given a DOCX source (no computable physical page count)
When  the source is ingested
Then  no reading is produced and no flag is raised

Given a source that fires a signal
When  the source is ingested
Then  intake still succeeds (no exception, `text_layer_ok` stays True) and
      the source proceeds exactly as an unflagged source would -- flag-only,
      never a reject

Expected new public surface this test locks the implementer to (none of it
exists yet):

- `axial.intake.Source` gains a new field, `holdings_flag: dict | None`
  (default `None`), populated by `intake()` for every accepted **PDF**
  source (never for DOCX, which has no computable physical page count).
- When a signal fires, `holdings_flag` is a `dict` carrying at least:
    - `"signal"`: the literal string `"toc_page_extent"` or
      `"orphan_fragment"` (§7.11's own vocabulary, not test-author-invented).
    - `"threshold"`: the numeric threshold in force -- `cover_floor`
      (currently 0.5) for `toc_page_extent`; `orphan_page_ceiling`
      (currently 120) for `orphan_fragment`.
    - For `toc_page_extent`: `"cover"` (the computed COVER ratio, float),
      `"physical_pages"` (int), `"max_page_reference"` (int).
    - For `orphan_fragment`: `"physical_pages"` (int), `"backmatter_density"`
      (the measured tail back-matter entry density, numeric).
  When neither signal fires, `holdings_flag` is `None`.

Seam decisions
-----------------------------------------------------------------------
1. Every fixture is a **hand-built, minimal, valid PDF** assembled directly
   in this module by a small from-scratch writer (`_make_pdf`), not
   `reportlab`. `reportlab` is an ephemeral fixture-authoring tool elsewhere
   in this repo (see `tests/fixtures/intake/_generate.py`'s own docstring --
   `uv run --with reportlab ...`), not a project or test-time dependency; it
   is not importable under a plain `uv run pytest`. `_make_pdf` needs only
   `pypdf` (an existing real dependency) to read back what it writes, and
   nothing beyond the standard library to write it: one Catalog, one Pages
   tree, one base-14 Helvetica font, N page objects each with its own
   `BT ... Tj ... ET` content stream, and a plain (uncompressed) xref table.
   Verified directly against `pypdf.PdfReader` before being trusted here.
2. Every fixture PDF is built fresh under pytest's own `tmp_path` -- no
   binary fixture is committed for this test (repo policy forbids
   committing source books or verbatim text; all of `data/` is gitignored,
   DEC-23). Page counts are small scaled proxies of the real corpus
   measurements in the issue's pinned comment, not attempts to reproduce
   real book length.
3. The one exception is the DOCX case, which reuses the already-committed,
   already-reviewed `tests/fixtures/intake/text.docx` (issue #13) rather
   than duplicating a second synthetic DOCX builder for a fixture that
   already exists and is trivial (no page count is involved at all).
4. `axial.intake.intake()` is called directly at the Python level (not
   through the CLI subprocess, unlike `test_intake.py`) -- this slice's own
   scope is "computes a verdict and returns it on the `Source` object intake
   already produces" (not any new CLI surface), and the flag's measured
   values need structured (dict) assertions a CLI-text scrape can't give.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.intake import intake

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXISTING_TEXT_DOCX = REPO_ROOT / "tests" / "fixtures" / "intake" / "text.docx"


# =============================================================================
# Minimal from-scratch PDF writer (see Seam decision 1 above)
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
    `pages_lines`, each rendered as its own `BT/Tj/ET` text block in base-14
    Helvetica. `len(pages_lines)` IS the resulting `pypdf` page count."""
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


def _write_pdf_fixture(tmp_path: Path, name: str, pages_lines: list[list[str]]) -> Path:
    path = tmp_path / name
    path.write_bytes(_make_pdf(pages_lines))
    return path


# =============================================================================
# Fixture content
# =============================================================================


def _filler_page(page_index: int) -> list[str]:
    return [
        f"This is ordinary body prose on page {page_index} of the synthetic "
        f"fixture, discussing the case in general terms and citing nothing."
    ]


# --- Scenario 1: truncated work, readable contents page (Signal A fires) ---
# physical_pages=4, max_page_reference=60 -> COVER = 4/60 ~= 0.0667, well
# below cover_floor (0.5) -- a scaled proxy of the real Mann-v2 measurement
# (85 physical pages, tocMax 816, COVER 0.10).
_TRUNCATED_TOC_PAGE_0 = [
    "Contents",
    "Chapter One .......... 1",
    "Chapter Two .......... 25",
    "Chapter Three .......... 60",
]
TRUNCATED_WITH_TOC_PAGES = [_TRUNCATED_TOC_PAGE_0] + [_filler_page(i) for i in range(1, 4)]
_TRUNCATED_EXPECTED_COVER = 4 / 60
_TRUNCATED_EXPECTED_MAX_REF = 60
_TRUNCATED_EXPECTED_PAGES = 4

# --- Scenario 2: complete work, decoy bare-year line (Signal A must not
# fire; also stands in for "a healthy source raises no flag") ---
# physical_pages=12, TRUE max_page_reference=11 -> COVER ~= 1.09, above 1.0
# and well clear of cover_floor. The decoy line ends in a bare 4-digit year
# with NO dot leader and is not chapter/title-shaped -- a naive "line ends
# in digits" matcher would misread it as an entry with page reference 1975,
# collapsing COVER to ~0.006 and firing falsely. §7.11 names exactly this
# risk ("a stray large integer captured as an entry reference ... strict
# entry-shape matching is what holds it off").
COMPLETE_WORK_PAGE_0 = [
    "Contents",
    "Introduction .......................... 1",
    "Chapter One: Origins .................. 3",
    "Chapter Two: Consolidation ............ 5",
    "This edition was substantially revised in 1975",
    "Chapter Three: Aftermath .............. 7",
    "Conclusion ............................ 9",
    "Index .................................. 11",
]
COMPLETE_WORK_PAGES = [COMPLETE_WORK_PAGE_0] + [_filler_page(i) for i in range(1, 12)]

# --- Scenario 3: orphan fragment, no contents page, no back matter (Signal
# B fires) --- physical_pages=6, well under orphan_page_ceiling (120); a
# scaled proxy of Ungor (20pp, 0 refs, no title/contents page at all).
ORPHAN_FRAGMENT_PAGES = [_filler_page(i) for i in range(0, 6)]
_ORPHAN_EXPECTED_PAGES = 6

# --- Scenario 4: short paper, no contents page, but genuine back matter in
# its tail (Signal B must NOT fire -- the bayat/heydemann-war false-positive
# guard the spec names explicitly: a heading-regex back-matter test gets
# both of these wrong; a content-based one does not). Back matter is
# concentrated in the LAST two of eight pages so it dominates whatever
# window "the final ~10% of the text layer" resolves to, regardless of the
# still-unset backmatter_entry_density tuning.
_BACKMATTER_INVERTED_AUTHOR_ENTRIES = [
    "Bayat, A. (2010) Life as Politics: How Ordinary People Change the "
    "Middle East. Stanford University Press.",
    "Heydemann, S. (2013) Tracking the Arab Spring: Syria and the Future "
    "of Authoritarianism. Journal of Democracy 24.",
    "Ismail, S. (2018) The Rule of Violence: Subjectivity, Memory and "
    "Government in Syria. Cambridge University Press.",
    "Wedeen, L. (1999) Ambiguities of Domination: Politics, Rhetoric, and "
    "Symbols in Contemporary Syria. University of Chicago Press.",
    "Wickham, C. (2013) The Muslim Brotherhood: Evolution of an Islamist "
    "Movement. Princeton University Press.",
]
_BACKMATTER_INDEX_ENTRIES = [
    "state formation, 12, 45, 88-91",
    "civil society, 33, 67, 102",
    "authoritarian resilience, 8, 19, 140-142",
    "informal politics, 21, 56, 77-80",
    "street politics, 5, 44, 99",
]
SHORT_PAPER_WITH_BACKMATTER_PAGES = [_filler_page(i) for i in range(0, 6)] + [
    _BACKMATTER_INVERTED_AUTHOR_ENTRIES,
    _BACKMATTER_INDEX_ENTRIES,
]

# --- Scenario 5: contents page exists but its page-reference numbers are
# garbled/unreadable (Signal A must degrade to "no reading", never a false
# fire). Physical page count (150) sits well above orphan_page_ceiling
# (120) so Signal B is structurally unreachable regardless of how the
# back-matter density threshold ends up tuned -- isolating the property
# under test (Signal A's safe direction on OCR) from Signal B's own,
# separately-tuned threshold.
GARBLED_TOC_PAGE_0 = [
    "Contents",
    "Chapter One .......................... l0l",
    "Chapter Two .......................... 4O",
    "Chapter Three ......................... ??",
    "Appendix .............................. ~~~",
]
GARBLED_TOC_NUMBERS_PAGES = [GARBLED_TOC_PAGE_0] + [_filler_page(i) for i in range(1, 150)]

assert len(TRUNCATED_WITH_TOC_PAGES) == _TRUNCATED_EXPECTED_PAGES, "internal fixture bug"
assert len(COMPLETE_WORK_PAGES) == 12, "internal fixture bug"
assert len(ORPHAN_FRAGMENT_PAGES) == _ORPHAN_EXPECTED_PAGES, "internal fixture bug"
assert len(SHORT_PAPER_WITH_BACKMATTER_PAGES) == 8, "internal fixture bug"
assert len(GARBLED_TOC_NUMBERS_PAGES) == 150, "internal fixture bug"


# =============================================================================
# Tests
# =============================================================================


def test_signal_a_fires_on_truncated_source_with_readable_contents_page(tmp_path):
    path = _write_pdf_fixture(tmp_path, "truncated_with_toc.pdf", TRUNCATED_WITH_TOC_PAGES)

    source = intake(path)

    flag = source.holdings_flag
    assert flag is not None, (
        f"expected a holdings-completeness flag for a source whose printed "
        f"contents page claims {_TRUNCATED_EXPECTED_MAX_REF} pages against "
        f"only {_TRUNCATED_EXPECTED_PAGES} physical pages (COVER "
        f"~{_TRUNCATED_EXPECTED_COVER:.3f}, well below cover_floor), got None"
    )
    assert flag["signal"] == "toc_page_extent", (
        f"expected the fired signal to be named 'toc_page_extent', got {flag!r}"
    )
    assert flag["cover"] == pytest.approx(_TRUNCATED_EXPECTED_COVER, abs=0.01), (
        f"expected the recorded COVER ratio to be the physical page count "
        f"({_TRUNCATED_EXPECTED_PAGES}) divided by the max contents-page "
        f"reference ({_TRUNCATED_EXPECTED_MAX_REF}), got {flag!r}"
    )
    assert flag["physical_pages"] == _TRUNCATED_EXPECTED_PAGES, (
        f"expected the flag to carry the physical page count as one of "
        f"COVER's own inputs (§7.11), got {flag!r}"
    )
    assert flag["max_page_reference"] == _TRUNCATED_EXPECTED_MAX_REF, (
        f"expected the flag to carry the recovered max contents-page "
        f"reference as one of COVER's own inputs, got {flag!r}"
    )
    assert flag["threshold"] == pytest.approx(0.5), (
        f"expected the flag to carry the cover_floor threshold in force "
        f"(currently 0.5 per §7.11/§8 P0-1b), got {flag!r}"
    )


def test_signal_a_does_not_fire_on_complete_work_with_decoy_bare_year_line(tmp_path):
    path = _write_pdf_fixture(tmp_path, "complete_work.pdf", COMPLETE_WORK_PAGES)

    source = intake(path)

    assert source.holdings_flag is None, (
        f"expected NO holdings-completeness flag for a complete work whose "
        f"contents page's true max reference (11) against its own physical "
        f"page count (12) yields COVER ~1.09, above 1.0 and healthy -- a "
        f"decoy prose line ending in a bare year ('...revised in 1975', no "
        f"dot leader, not title-shaped) must NOT be misread as an entry and "
        f"drag COVER down, but got {source.holdings_flag!r}"
    )


def test_signal_b_fires_on_orphan_fragment_with_no_contents_page_and_no_back_matter(tmp_path):
    path = _write_pdf_fixture(tmp_path, "orphan_fragment.pdf", ORPHAN_FRAGMENT_PAGES)

    source = intake(path)

    flag = source.holdings_flag
    assert flag is not None, (
        f"expected a holdings-completeness flag for a {_ORPHAN_EXPECTED_PAGES}"
        f"-page source with no printed contents page and no bibliography/"
        f"index back matter in its tail (a scaled proxy of the Ungor "
        f"orphan-fragment case), got None"
    )
    assert flag["signal"] == "orphan_fragment", (
        f"expected the fired signal to be named 'orphan_fragment', got {flag!r}"
    )
    assert flag["physical_pages"] == _ORPHAN_EXPECTED_PAGES, (
        f"expected the flag to carry the physical page count, got {flag!r}"
    )
    assert isinstance(flag.get("backmatter_density"), (int, float)), (
        f"expected the flag to carry the measured tail back-matter entry "
        f"density (§7.11: 'for Signal B the page count and the measured "
        f"tail back-matter density'), got {flag!r}"
    )
    assert flag["threshold"] == pytest.approx(120), (
        f"expected the flag to carry the orphan_page_ceiling threshold in "
        f"force (currently 120 per §7.11/§8 P0-1b), got {flag!r}"
    )


def test_signal_b_does_not_fire_on_short_paper_with_content_based_back_matter(tmp_path):
    """The bayat/heydemann-war guard §7.11 names explicitly: a
    heading-regex back-matter test reports both as lacking back matter and
    fires falsely; a content-based one over the tail must not."""
    path = _write_pdf_fixture(
        tmp_path, "short_paper_with_backmatter.pdf", SHORT_PAPER_WITH_BACKMATTER_PAGES
    )

    source = intake(path)

    assert source.holdings_flag is None, (
        f"expected NO holdings-completeness flag for a short (8-page), "
        f"contents-page-less source whose tail carries genuine reference-"
        f"list and index back matter -- this is the bayat/heydemann-war "
        f"false-positive case §7.11 calls out by name ('a heading-regex "
        f"test was tried and rejected: it reports no back matter for "
        f"bayat and heydemann-war, both of which do carry it'); the "
        f"content-based tail test must recognize it and not fire, but got "
        f"{source.holdings_flag!r}"
    )


def test_signal_a_degrades_safely_on_garbled_contents_page_numbers(tmp_path):
    """§7.11: garbled/missed page numbers must shrink the recovered
    reference set (toward 'no reading'), never produce a false fire --
    'a scan therefore yields a false negative, never a false alarm.'"""
    path = _write_pdf_fixture(tmp_path, "garbled_toc_numbers.pdf", GARBLED_TOC_NUMBERS_PAGES)

    source = intake(path)

    assert source.holdings_flag is None, (
        f"expected NO holdings-completeness flag for a source whose "
        f"printed contents page exists but whose page-reference numbers "
        f"are garbled/unreadable ('l0l', '4O', '??', '~~~' -- none a clean "
        f"trailing whole number) -- this is the safe-direction-degradation "
        f"property that makes Signal A safe on OCR, but got "
        f"{source.holdings_flag!r}"
    )


def test_docx_source_returns_no_reading_and_no_flag():
    assert EXISTING_TEXT_DOCX.exists(), (
        f"expected the existing committed DOCX fixture at "
        f"{EXISTING_TEXT_DOCX} (from issue #13's intake acceptance test) "
        f"to still be present"
    )

    source = intake(EXISTING_TEXT_DOCX)

    assert source.format == "docx"
    assert source.holdings_flag is None, (
        f"expected a DOCX source (no computable physical page count) to "
        f"produce no reading and raise no flag (§7.11/§8 P0-1b: 'A DOCX "
        f"source has no computable physical page count: the probe returns "
        f"no reading for it and raises no flag'), got "
        f"{source.holdings_flag!r}"
    )


def test_flagged_source_still_completes_intake_successfully_and_is_not_rejected(tmp_path):
    """§7.11: 'flag-only, never a reject.' A fired signal must never halt
    intake, raise, or alter what the caller gets back -- the source
    proceeds exactly as an unflagged one does. Calling `intake()` here
    without wrapping it in `pytest.raises` IS the assertion: any exception
    at all (an `IntakeError` or otherwise) fails this test."""
    path = _write_pdf_fixture(tmp_path, "truncated_with_toc.pdf", TRUNCATED_WITH_TOC_PAGES)

    source = intake(path)

    assert source.holdings_flag is not None, (
        "internal fixture bug: this scenario is only meaningful if the "
        "signal actually fired -- see "
        "test_signal_a_fires_on_truncated_source_with_readable_contents_page "
        "for the full assertion on the flag's own contents"
    )
    assert source.format == "pdf"
    assert source.text_layer_ok is True, (
        f"expected a flagged source to still pass P0-1's text-layer check "
        f"and complete intake unchanged, got text_layer_ok="
        f"{source.text_layer_ok!r}"
    )
