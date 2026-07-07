# feat(minimal-ingestion): structural extraction — docling tree [slice 02]

**Spec:** specs/PRODUCT.md §5 (stage 2), §8 P0-2 · **Plan:** plans/minimal-ingestion/02-structural-extraction.md
**Depends on:** #13 (slice 01 intake)
**Labels:** sub:ingestion-v0

## Deliverable

`axial extract <file>` runs docling on an intake-validated source and produces a
hierarchical structural tree that separates prose sections from non-text
artifacts (tables, figures), each node preserving source ordering / section
provenance. The happy path of P0-2 and the structural substrate every later stage
consumes.

## Acceptance criterion

```gherkin
Given a born-digital fixture PDF containing prose sections and at least one table or figure
When  the user runs `axial extract <fixture>`
Then  it exits 0 and emits a hierarchical structural tree
And   the tree marks prose sections and non-text artifacts as distinct node types
And   each node preserves its source ordering / section provenance
```

## Out of scope

The Unstructured fallback (slice 03); artifact *role* classification (phase 3,
P0-5); the envelope pass (slice 04). This slice structures only — it does not tag
or summarize.
