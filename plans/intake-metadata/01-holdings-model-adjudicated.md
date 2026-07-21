# Slice 01: Holdings check — model-adjudicated rewrite, flag-only

- **Feature:** intake-metadata
- **Slice slug:** holdings-model-adjudicated
- **GitHub issue:** #284
- **Branch:** feat/intake-metadata/01-holdings-model-adjudicated
- **Project directory:** .
- **Status:** ✅ merged
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Replace `src/axial/holdings.py`'s retired deterministic design with the
model-adjudicated check §7.11 specifies. Deterministic pre-processing runs first:
read the physical page count from the file, and strip recurring running
headers/footers so a folio stitched to a heading (`viii Contents`) reaches the
model as `Contents`. Then **one** reasoning-ON model call over the cleaned front
matter (plus whatever tail the judgment needs) decides three things together —
the **document kind** (book / research paper / chapter offprint / fragment), the
**claimed extent** where the document states one, and **whether the file covers
that extent** given the page count. The check flags and reports only: a flagged
source still completes intake and proceeds through every later stage unchanged
(P0-1b). A source judged complete produces no flag. The bar is 0 false positives
over the 30-source corpus, flagging exactly the two known partial holdings.

## What is removed (the retired deterministic design)

All of it, named so it is not rebuilt:

- The six tunables: `COVER_FLOOR`, `ORPHAN_PAGE_CEILING`, `CONTENTS_SEARCH_PAGES`,
  `CONTENTS_SPAN_PAGES`, `TAIL_WINDOW_FRACTION`, `BACKMATTER_ENTRY_DENSITY`.
- Signal A (printed-TOC COVER ratio) and Signal B (back-matter density), with
  their regexes and the entry stoplist (`_ENTRY_TRAILING_STOPWORDS`,
  `_INVERTED_AUTHOR_NAME_RE`, `_INDEX_ENTRY_LINE_RE`, `_TOC_ENTRY_LINE_RE`).
- The deterministic two-signal `probe()` orchestration and every helper under it.
- The socket-patch determinism-guard test that asserts the probe makes zero
  network calls — the check now makes exactly one model call by design, so that
  guard is retired with the design it guarded (its replacement is the tree/
  envelope-untouched observability below, not a no-network assertion).

## What is kept / added

- **Deterministic physical page count**, read from the file (the only reliable
  measure of how far the file runs). Already available via `pypdf`; DOCX exposes
  none, and that absence is handled, not flagged (below).
- **Running header/footer stripping** — new. Lines recurring at the top/bottom of
  pages across the document (folios, running heads) are removed before any text
  is read for judgment. This is a §7.11 **requirement**: `tilly`'s heading
  extracts as `viii Contents`, and the folio must not survive into the model's
  input. The observable is exactly that source.
- **One reasoning-ON model call**, same per-pass profile as the envelope (§7.9):
  one call per source over front matter plus needed tail, reasoning carried in
  `config/pipeline.yaml` per pass, never hardcoded.
- **A flag that records its measurement** (never a bare boolean): the source; the
  concluded document kind; the claimed extent with what stated it; the observed
  extent (page count); and the model's stated reason. Values and short reasons
  only, no source text (DEC-23).

## INVEST check

- **Independent:** `holdings.py` is a self-contained module; `intake.py` calls
  `probe(page_texts)` and attaches the result to `Source`. The rewrite keeps that
  call seam (it may change the argument to also pass a page count / an LLM client),
  changing no other pass. Slice 02 consumes the flag shape but is a later slice.
- **Valuable:** turns a spec-divergent, measurably-broken check (1 false positive
  on `state-legitimacy`, contents reader locating 4/30 pages) into the
  model-adjudicated check the spec requires, at the strict 0-FP bar.
- **Small:** one module rewritten; one deterministic pre-process (header strip) +
  one model call + one flag shape. At most a small number of stated window-size
  tunables, values set by measurement, not asserted.
- **Testable:** run the check with a stub/recorded LLM client over corpus-shaped
  fixtures; assert the two partial holdings flag, the 28 complete sources do not,
  a research paper with no contents page passes clean, and the `tilly` folio is
  stripped before the model sees the heading.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given the 30-source corpus's holdings fixtures and a recorded/stub LLM client for the holdings pass
When  the holdings check runs at intake on each source
Then  it flags exactly the two known partial holdings and no others (2 true positives, 0 false positives, 0 false negatives)
And   each flag records the concluded document kind, the claimed extent with what stated it, the observed physical page count, and the model's stated reason — never a bare boolean, and no source text
And   a complete research paper carrying no contents page passes with no flag
And   on the `tilly` source, whose contents heading extracts as `viii Contents`, the text handed to the model carries the heading without the folio
And   a flagged source still completes intake and is returned exactly as an unflagged source, reading neither the structural tree nor the envelope
```

- **Boundary / endpoint:** `axial.holdings.probe(...)` as called from
  `axial.intake.intake(...)` (module-level, exercised through intake).
- **Outer test type:** pytest integration test (recorded/stub LLM client; no
  network, no tree, no envelope).
- **Outer test file (planned):** tests/ingestion/test_holdings_model_adjudicated.py
  — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] running header/footer stripping removes a folio recurring across pages, so
      `viii Contents` becomes `Contents`; a heading that appears once is untouched
- [ ] physical page count is read from a PDF; a DOCX yields no page count and the
      code path handles its absence without error
- [ ] the model call is made with reasoning ON, one call per source, over the
      cleaned front matter (+ tail), using the same `get_client`/pass-config seam
      the envelope uses (`pass_name` carries the holdings pass)
- [ ] a model verdict of "partial" produces a flag carrying source, document
      kind, claimed extent + what stated it, observed page count, and stated reason
- [ ] a model verdict of "complete" produces `None` (no flag)
- [ ] a research paper with no contents page is judged complete (kind = research
      paper), not flagged — the distinction that forces model adjudication
- [ ] the flag carries no source text / no verbatim excerpt (DEC-23): reason and
      values only
- [ ] DOCX: a DOCX whose front matter names it a volume/part of a larger work may
      be flagged; a DOCX flagged merely for missing coverage evidence is not
- [ ] flag-only: the check never raises and never rejects; intake still returns a
      `Source` for a flagged source
- [ ] the check reads neither `data/trees/` nor `data/envelopes/` — none needs to
      exist for it to run (observed by asserting those paths are never opened)

## Out of scope for this slice (deferred)

- **Persisting the flag.** The flag is attached to the returned `Source` only;
  writing it to `data/source_meta/<source_id>.json` is slice 02.
- **Author/title/date.** Read at intake too, but a separate concern (§7.13);
  slices 02/03.
- **Repair / re-fetch / reject.** v0 is flag-only forever in this feature (§7.11).
- **Tuning window sizes to a final value.** Any stated tunable's value is set by
  measurement over the 30 sources during the slice, not fixed in advance and not
  asserted in the plan.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test
      GREEN.
- [ ] Measured over the 30-source corpus: 2 TP, 0 FP, 0 FN (the bar; it does not
      move). Evidence recorded in the PR.
- [ ] Any stated tunable named and its value justified by measurement, not
      assertion; over-engineering tripwires checked (no hand-tuned magic constant
      reintroduced).
- [ ] Refactor pass complete with the bar green; the retired deterministic design
      and its determinism-guard test are fully removed.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-21 planned.
