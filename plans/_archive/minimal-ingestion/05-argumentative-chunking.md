# Slice 05: Argumentative chunking — envelope + surrounding sections in context

- **Feature:** minimal-ingestion
- **Slice slug:** argumentative-chunking
- **GitHub issue:** #17
- **Branch:** feat/minimal-ingestion/05-argumentative-chunking
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial chunk <file>` decides prose chunk boundaries for each section by calling
the LLM with the stored envelope **plus surrounding sections** in context — never
the isolated section — and emits chunks that carry stable `chunk_id`s and section
provenance. This is §5 stage 4 / P0-4, the argument-aware chunking that the whole
PRD is built to get right (§1).

## INVEST check

- **Independent:** consumes an extraction tree + a stored envelope; reuses the
  slice-04 client seam; needs no vault writer.
- **Valuable:** argument-shaped chunks are the core value proposition — the
  difference between retrievable units and page-break fragments (§1).
- **Small:** one subcommand + a context-assembling prompt + chunk-id/provenance emission.
- **Testable:** run against a fixture with a stored envelope and a stub client;
  assert the call received envelope + neighbouring sections and that chunks carry stable ids + provenance.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and the stub LLM provider
When  the user runs `axial chunk <fixture>`
Then  it exits 0 and emits prose chunks each with a stable chunk_id and its section provenance
And   the chunking call received the stored envelope plus the section's neighbours (not the isolated section)
And   the stored envelope is read from disk, not recomputed
```

- **Boundary / endpoint:** CLI command `axial chunk <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_chunk.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] context assembler builds a chunking prompt containing the envelope + the target section + its neighbours
- [ ] the pass reads the envelope from `data/envelopes/` and errors clearly if it is absent (must run envelope first)
- [ ] the response parser turns model output into chunk records with `chunk_id` + section provenance
- [ ] chunk_ids are stable and deterministic for the same input (e.g. `<source_id>_<section>_<NNN>`)
- [ ] chunk records preserve the section's verbatim label for section-level metadata downstream
- [ ] a section with no chunkable prose yields zero chunks without error

## Out of scope for this slice (deferred)

- Long-section multi-call handling (P1-1); axis tagging of chunks (phase 3);
  writing notes to the vault (slice 06). This slice produces chunk records in
  memory/stdout; persistence to the vault is the next slice.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (stub provider; no network).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
- 2026-07-07 shipped to PR. Red outer test `af8646a`, implementation `ae6797c`,
  review fixes `32343c8` (chunk_id uniqueness via `order`; pass marker moved
  out-of-band). Two-stage review: stage 1 pass, two stage-2 findings addressed.
  Suite 150 passed, ruff clean. PR: https://github.com/Muhanad-husn/axial/pull/24
  (Closes #17). Awaiting founder approval to merge.
