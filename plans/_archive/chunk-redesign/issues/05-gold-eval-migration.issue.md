# feat(chunk-redesign): gold sampling and eval read the on-disk chunk artifact [slice 05]

**Spec:** specs/PRODUCT.md#7.7 (gold/eval consume) · **Plan:** plans/chunk-redesign/05-gold-eval-migration.md
**Depends on:** #154
**Charter:** #148
**Labels:** sub:ingestion-v0

## Deliverable

The gold-set sampler (`axial gold sample`/`sheet`) and the eval harness read prose chunks
from `data/chunks/<source_id>.jsonl` (§7.7) instead of re-deriving chunks in-process via
`run_chunk`. Sampling strata, sheet format, delivery bundle, and eval scoring are otherwise
unchanged — only the source of chunks moves to the disk artifact. `chunk_id`/provenance
flows through the sheet and answer key unchanged. After this slice nothing in `src/` calls
the old `run_chunk`.

## Acceptance criterion

```gherkin
Given fixture sources with data/chunks/<source_id>.jsonl artifacts present
When  the user runs `axial gold sample` then `axial gold sheet`
Then  the sampled gold chunks are drawn from the on-disk artifact (their chunk_id/text match
      the JSONL), the field×empirical_scope×role balancing strata still hold, and no chunk is
      re-derived in-process (no LLM-echo chunk call)
And   `axial eval` scores the tagger output against labels using the same artifact-sourced
      chunk_ids, with per-axis agreement unchanged in shape from before the migration
```

## Out of scope

- Sampling strata, sheet columns, delivery bundle, eval metrics — all unchanged; source-of-
  chunks swap only. Real Academic labels remain a separate, already-tracked concern (eval
  still runs on placeholder labels).

## Notes

- Reuses slice 04's `read_chunks(source_id)` reader; do not re-implement it.
- Grep to confirm the echo chunker is fully retired once this lands.
