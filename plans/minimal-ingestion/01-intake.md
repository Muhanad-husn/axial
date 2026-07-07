# Slice 01: Intake — format & text-layer validation

- **Feature:** minimal-ingestion
- **Slice slug:** intake
- **GitHub issue:** #13
- **Branch:** feat/minimal-ingestion/01-intake
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no (phase-1 skeleton already ships package/CLI/CI)

## Goal — the minimum testable behaviour

`axial intake <file>` accepts a born-digital `.pdf` or `.docx` that has a real
text layer and exits 0 with a source-metadata stub; it rejects any other
extension and any file lacking a text layer (scanned/image-only PDF) with a
nonzero exit and a clear logged reason. This is the pipeline's front door
(§5 stage 1, P0-1) and the corpus boundary that keeps OCR-less scanned files out.

## INVEST check

- **Independent:** builds only on the existing CLI; no later stage needed.
- **Valuable:** guarantees nothing without a text layer is silently passed
  downstream — the load-bearing intake guarantee of §10.
- **Small:** one subcommand + a text-layer probe + a metadata stub.
- **Testable:** CLI invocation against committed fixture files, exit code + message.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a born-digital fixture PDF with a text layer and a fixture DOCX with text
When  the user runs `axial intake <fixture>`
Then  it exits 0 and emits a source-metadata stub naming the file and detected format
And   against an image-only/no-text-layer PDF it exits nonzero with a message stating no text layer was found
And   against an unsupported file (e.g. .txt/.png) it exits nonzero naming the rejected extension
```

- **Boundary / endpoint:** CLI command `axial intake <file>`
- **Outer test type:** pytest integration test (subprocess)
- **Outer test file (planned):** tests/test_intake.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] extension check accepts `.pdf`/`.docx` (case-insensitive), rejects others with a typed error naming the extension
- [ ] text-layer probe returns True for a text PDF, False for an image-only PDF
- [ ] text-layer probe returns True for a DOCX with body text
- [ ] a missing/unreadable input path raises a clear typed error
- [ ] intake returns a source-metadata stub (path, format, text-layer-ok) on success

## Out of scope for this slice (deferred)

- Any parsing of *content* (that is slice 02 extraction); OCR (a permanent non-goal, §3);
  Google Drive sourcing (P0-11, later); author/title/date extraction (arrives with the envelope, slice 04).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
