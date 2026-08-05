# feat(minimal-ingestion): argumentative chunking — envelope + surrounding sections in context [slice 05]

**Spec:** specs/PRODUCT.md §5 (stage 4), §8 P0-4 · **Plan:** plans/minimal-ingestion/05-argumentative-chunking.md
**Depends on:** #16 (slice 04 structural-envelope)
**Labels:** sub:ingestion-v0

## Deliverable

`axial chunk <file>` decides prose chunk boundaries per section by calling the LLM
with the stored envelope **plus surrounding sections** in context — never the
isolated section — and emits chunks carrying stable `chunk_id`s and section
provenance. Reuses the slice-04 client seam and reads the stored envelope (no
recompute). The argument-aware chunking the PRD exists to get right (§1); this is
P0-4.

## Acceptance criterion

```gherkin
Given an extracted fixture source with a stored envelope and the stub LLM provider
When  the user runs `axial chunk <fixture>`
Then  it exits 0 and emits prose chunks each with a stable chunk_id and its section provenance
And   the chunking call received the stored envelope plus the section's neighbours (not the isolated section)
And   the stored envelope is read from disk, not recomputed
```

## Out of scope

Long-section multi-call handling (P1-1); axis tagging of chunks (phase 3); writing
notes to the vault (slice 06). This slice produces chunk records; persistence is
the next slice.
