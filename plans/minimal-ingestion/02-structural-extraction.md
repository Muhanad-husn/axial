# Slice 02: Structural extraction — docling tree

- **Feature:** minimal-ingestion
- **Slice slug:** structural-extraction
- **GitHub issue:** #14
- **Branch:** feat/minimal-ingestion/02-structural-extraction
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial extract <file>` runs docling on a validated source and produces a
hierarchical structural tree that separates prose sections from non-text
artifacts (tables, figures). This is §5 stage 2's happy path and the first half
of P0-2; every later stage consumes this tree.

## INVEST check

- **Independent:** consumes an intake-validated file; needs no envelope/chunking.
- **Valuable:** the structural tree is the substrate for envelope, chunking, and
  the prose/artifact routing — without it the pipeline has no structure to reason over.
- **Small:** one subcommand wrapping docling + a normalized tree shape.
- **Testable:** run docling on a committed fixture PDF containing prose + a table;
  assert prose sections and artifact nodes appear as distinct node types.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a born-digital fixture PDF containing prose sections and at least one table or figure
When  the user runs `axial extract <fixture>`
Then  it exits 0 and emits a hierarchical structural tree
And   the tree marks prose sections and non-text artifacts as distinct node types
And   each node preserves its source ordering / section provenance
```

- **Boundary / endpoint:** CLI command `axial extract <file>`
- **Outer test type:** pytest integration test (subprocess)
- **Outer test file (planned):** tests/test_extract.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] docling wrapper returns a normalized tree from a fixture PDF (adapter over docling's output)
- [ ] the normalizer classifies a prose block as a `prose` node and a table/figure as an `artifact` node
- [ ] each node carries a stable path/ordering so downstream provenance is possible
- [ ] extract on a non-intake-valid file surfaces intake's rejection (reuses slice 01)
- [ ] the tree serializes deterministically (stable JSON) for the outer test to assert against

## Out of scope for this slice (deferred)

- The Unstructured **fallback** (slice 03); artifact *role* classification (phase 3, P0-5);
  the envelope pass (slice 04). This slice only structures; it does not tag or summarize.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (docling installed in the CI environment).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
