# feat(xref): detect prose→artifact references, emit link pairs [slice 01]

**Spec:** specs/PRODUCT.md#5-7 (stage 7), #8 (P0-7) · **Plan:** plans/xref/01-xref-detect.md
**Depends on:** #17 (chunking), artifacts slice 01 (this sprint)
**Labels:** sub:ingestion-v0

## Deliverable

`axial xref <file>` takes the source's prose chunks and its classified artifacts and
detects prose→artifact references ("as Table 3 shows") — one LLM call per chunk
(`pass_name="xref"`), given the chunk text and the source's artifact list — emitting the
detected `(chunk_id → artifact_id)` link pairs to stdout. A referenced `artifact_id` not
among the source's actual artifacts never becomes a pair, so no dangling link is ever
produced. Runs after chunking and artifact classification (P0-7); this slice makes the
detection observable before any note is rewritten.

## Acceptance criterion

```gherkin
Given a fixture source with prose chunks and classified artifacts, and AXIAL_LLM_PROVIDER=stub canned to reference one artifact
When  the user runs `axial xref <fixture>`
Then  it exits 0 and emits the detected (chunk_id, artifact_id) reference pairs as JSON
And   a referenced artifact_id not among the source's artifacts produces no pair (no dangling link)
And   a source with no detected references emits an empty pair list without error
```

## Out of scope

- Writing backlinks into notes (slice 02) — pairs go to stdout only.
- Non-citation relatedness — only explicit textual references are detected.
