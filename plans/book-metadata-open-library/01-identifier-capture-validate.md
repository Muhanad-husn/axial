# Slice 01: Capture and checksum-validate an ISBN/DOI from a source's front matter

- **Feature:** book-metadata-open-library
- **Slice slug:** identifier-capture-validate
- **GitHub issue:** TBD
- **Branch:** feat/book-metadata-open-library/01-identifier-capture-validate
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes — first slice, no dependencies

## Goal — the minimum testable behaviour

A new pure module, `src/axial/identifiers.py`, that takes a source's
front-matter text and returns whichever of an ISBN (10 or 13) or a DOI it finds
that pass a **local check-digit / syntax test** — a corrupted or mistyped
identifier on the page is dropped, not returned as if valid. No network, no
file I/O beyond text already in hand. This ports the spike's proven capture
and validation logic (`plans/book-metadata-open-library/spike/phase0_scan.py`,
`phase0b_scan_pdfs.py`), which was self-tested and then run against the real
30-source corpus (93% coverage, see `FINDINGS.md`) — the regex and checksum
functions carry over essentially unchanged; this slice is about giving them a
permanent home and a proper inner-loop test suite, not inventing new logic.

The text this operates on is the **head of the source's own PDF text layer**
(the same `pypdf` read `intake.py` already performs for embedded-metadata —
see `_pdf_page_texts`, `intake.py:151`), not the docling structural tree. The
spike found `data/trees` is not reliably retained on disk once consumed
downstream, so depending on it here would be depending on an artifact that may
not exist when intake runs.

## INVEST check

- **Independent:** a standalone, side-effect-free module. Nothing else in the
  codebase calls it yet — this slice only proves the capture/validation logic
  in isolation.
- **Valuable:** it is the foundation the other two slices build on, and on its
  own it is a fully generalizable, tested primitive — the same function set the
  spike already validated by hand against the real corpus.
- **Small:** two regex families (ISBN, DOI) plus two checksum functions
  (ISBN-10, ISBN-13) plus a placeholder-rejection guard; no new dependency.
- **Testable:** pure functions over strings; the full inner-loop list below is
  runnable without any fixture beyond literal text.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given the text of a source's front matter (title page + copyright/ISBN block)
When  identifier capture runs over that text
Then  it returns every checksum-valid ISBN-10/ISBN-13 and syntactically valid DOI found
And   a corrupted check digit is rejected, not returned as if valid
And   an all-same-digit placeholder ISBN (e.g. "0-000-00000-0") is rejected even though it passes the checksum arithmetic
And   a source whose front matter carries neither yields no identifier — this is not an error condition
```

- **Boundary / endpoint:** `axial.identifiers.find_isbns(text)` and
  `axial.identifiers.find_dois(text)` — pure functions, no I/O.
- **Outer test type:** pytest integration test reading a small set of realistic
  front-matter fixture strings (and one real fixture PDF's extracted text, to
  prove the capture works against actual OCR/extraction noise, not only clean
  hand-written strings). No network.
- **Outer test file (planned):** `tests/ingestion/test_identifier_capture.py`
  — test-author, red, locked (DEC-1).

## Inner loop — initial unit test list

- [ ] a real ISBN-13 (e.g. a known-good example) validates; a real ISBN-10
      validates; an ISBN-10 ending in the `X` check character validates
- [ ] an ISBN-13 with a corrupted last digit fails validation; an ISBN-10 with
      a corrupted last digit fails; an `X` in any position other than the last
      of an ISBN-10 fails
- [ ] a hyphenated, labelled front-matter line (`"ISBN: 978-0-262-03384-8"`) is
      captured and normalized to digits-only
- [ ] a mistyped ISBN on the page (fails its own checksum) is dropped — never
      silently returned as a false win
- [ ] a bare 13-digit `978`/`979`-prefixed run with no `"ISBN"` word nearby is
      still captured
- [ ] an all-same-digit placeholder (e.g. a copyright-page fill-in
      `"0-000-00000-0"`) is rejected even though it passes the ISBN-10 checksum
      arithmetic
- [ ] a DOI (`10.xxxx/...`) is captured with trailing sentence punctuation
      (`.`, `)`, `"`) stripped
- [ ] text with no identifier of either kind returns an empty result, not an
      exception
- [ ] front matter carrying both an ISBN and a DOI (e.g. an open-access
      monograph) returns both; slice 03 decides caller policy on which to
      prefer, this slice only reports what it found
- [ ] a real extracted-PDF-text fixture (front matter with normal
      docling/pypdf extraction noise — inconsistent spacing, line breaks mid
      identifier) still captures the identifier correctly

## Out of scope for this slice (deferred)

- **The network lookup.** Slice 02 resolves a validated identifier against
  Open Library/Crossref; this slice only produces the identifier.
- **Wiring into `intake.py` / the persisted record.** Slice 03 calls this
  module and decides what to do with the result; this slice exposes the pure
  functions only.
- **Reading from `data/trees`.** Deliberately not built — see Goal above.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test
      GREEN.
- [ ] No network access anywhere in this slice's code or tests.
- [ ] Over-engineering tripwires checked: no new tunable constants beyond the
      identifier regexes themselves, which the spike already proved against
      the real corpus.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-22 planned, following the completed exploration spike (gate passed
  93% coverage / 100% resolution — see `FINDINGS.md`). No dependencies.
