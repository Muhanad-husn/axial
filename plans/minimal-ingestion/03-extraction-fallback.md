# Slice 03: Extraction fallback — Unstructured on docling failure

- **Feature:** minimal-ingestion
- **Slice slug:** extraction-fallback
- **GitHub issue:** #15
- **Branch:** feat/minimal-ingestion/03-extraction-fallback
- **Project directory:** .
- **Status:** ☑ PR #21 open — awaiting founder merge approval
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

When docling fails or returns degenerate output for a source, `axial extract`
falls back to Unstructured for that source and logs that the fallback was used,
producing the same normalized tree shape. This is the second half of P0-2 —
robustness against per-source parser failure across a real ~120-source corpus.

## INVEST check

- **Independent:** a business-rule variation layered on slice 02's happy path.
- **Valuable:** one unparseable source no longer halts or silently corrupts the
  run; the fallback is visible in the log for later per-source judgment (P1-3).
- **Small:** a failure/degeneracy detector + an Unstructured adapter emitting the same tree shape.
- **Testable:** force docling to fail/return degenerate output on a fixture and
  assert Unstructured ran and the fallback was logged.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a source on which docling fails or returns degenerate (empty/structureless) output
When  the user runs `axial extract <fixture>`
Then  it exits 0 having produced a structural tree via the Unstructured fallback
And   the run logs that docling failed and Unstructured was used for that source
And   the fallback tree uses the same prose/artifact node shape as the docling path
```

- **Boundary / endpoint:** CLI command `axial extract <file>` (fallback path)
- **Outer test type:** pytest integration test (subprocess; docling failure injected via a controllable fixture/seam)
- **Outer test file (planned):** tests/test_extract_fallback.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] degeneracy detector flags an empty/structureless docling result as "needs fallback"
- [ ] a raised docling exception routes to the Unstructured adapter (not a crash)
- [ ] the Unstructured adapter emits the same normalized `prose`/`artifact` tree shape as slice 02
- [ ] the fallback event is logged with the source id and the reason (exception vs. degenerate)
- [ ] when docling succeeds normally, the fallback is not invoked (no regression to slice 02)

## Out of scope for this slice (deferred)

- Tuning docling's degeneracy thresholds beyond a simple "empty/no structure" rule;
  retry/backoff; artifact role tagging (phase 3). The seam that lets a test force
  docling failure is design work owned here.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (Unstructured installed).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
- 2026-07-07 built test-first: red outer test (896129f) using the
  AXIAL_FORCE_DOCLING_FAILURE seam; Unstructured fast-strategy fallback +
  degeneracy detector + shared _build_tree (3634c92, a879556); review-found
  Header-opens-section bug fixed (c5938c7); evidence (09e6677). Reviewer
  two-stage review DONE_WITH_CONCERNS — Stage 1 PASS; one bug fixed; two items
  tracked (fragile fallback nesting; env-var seam). Full suite 79 passed.
  PR #21 opened into main — awaiting founder merge approval.
