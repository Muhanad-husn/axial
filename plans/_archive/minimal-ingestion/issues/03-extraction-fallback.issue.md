# feat(minimal-ingestion): extraction fallback — Unstructured on docling failure [slice 03]

**Spec:** specs/PRODUCT.md §5 (stage 2), §8 P0-2 · **Plan:** plans/minimal-ingestion/03-extraction-fallback.md
**Depends on:** #14 (slice 02 structural-extraction)
**Labels:** sub:ingestion-v0

## Deliverable

When docling fails or returns degenerate (empty/structureless) output for a
source, `axial extract` falls back to Unstructured for that source and logs that
the fallback was used, producing the same normalized prose/artifact tree shape.
The second half of P0-2 — robustness against per-source parser failure across the
real ~120-source corpus.

## Acceptance criterion

```gherkin
Given a source on which docling fails or returns degenerate (empty/structureless) output
When  the user runs `axial extract <fixture>`
Then  it exits 0 having produced a structural tree via the Unstructured fallback
And   the run logs that docling failed and Unstructured was used for that source
And   the fallback tree uses the same prose/artifact node shape as the docling path
```

## Out of scope

Tuning docling degeneracy thresholds beyond a simple empty/no-structure rule;
retry/backoff; artifact role tagging (phase 3).
