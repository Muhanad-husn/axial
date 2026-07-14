# Slice 05: Gold sampling and eval read the on-disk chunk artifact

- **Feature:** chunk-redesign
- **Slice slug:** gold-eval-migration
- **GitHub issue:** #155
- **Branch:** feat/chunk-redesign/05-gold-eval-migration
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

The gold-set sampler (`axial gold sample`/`sheet`) and the eval harness read prose chunks
from the on-disk chunk artifact `data/chunks/<source_id>.jsonl` (§7.7) instead of
re-deriving chunks in-process via `run_chunk`. Sampling strata, sheet format, delivery
bundle, and eval scoring are otherwise unchanged — only the *source of chunks* moves to the
disk artifact. `chunk_id`/provenance from the artifact flows through the sheet and the
answer key unchanged.

## INVEST check

- **Independent:** consumes slice 01's artifact via slice 04's reader; changes where gold /
  eval get chunks, not how they stratify, sheet, deliver, or score.
- **Valuable:** closes the #148 DoD ("gold/eval flows updated") — the last consumer of the
  old in-process chunker is gone, so the whole pipeline is disk-first end to end.
- **Small (M):** swap `run_chunk` for `read_chunks(source_id)` in `gold.py` and the eval
  path; keep everything else.
- **Testable:** run `axial gold sample`/`sheet` against a fixture with
  `data/chunks/*.jsonl`; assert the sampled rows come from the artifact (same `chunk_id`s /
  text), strata still satisfied, and no `run_chunk`/LLM-echo call occurs; run eval and
  assert scoring reads the same artifact-sourced chunks.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given fixture sources with data/chunks/<source_id>.jsonl artifacts present
When  the user runs `axial gold sample` then `axial gold sheet`
Then  the sampled gold chunks are drawn from the on-disk artifact (their chunk_id/text match
      the JSONL), the field×empirical_scope×role balancing strata still hold, and no chunk
      is re-derived in-process (no LLM-echo chunk call)
And   `axial eval` scores the tagger output against labels using the same artifact-sourced
      chunk_ids, with per-axis agreement unchanged in shape from before the migration
```

- **Boundary / endpoint:** `axial gold sample` / `axial gold sheet` and `axial eval`
- **Outer test type:** pytest integration test (subprocess; stub LLM; no network)
- **Outer test file (planned):** extend tests/test_gold.py and tests/test_eval.py —
  test-author, red, locked

## Inner loop — initial unit test list

- `gold.py` sampling reads `data/chunks/<source_id>.jsonl` (via the slice-04 reader) rather
  than calling `run_chunk`.
- Strata balancing (field × empirical_scope × role_in_argument) still satisfied off the
  artifact-sourced chunks; back-matter exclusion still applies.
- Sheet rows carry the artifact's `chunk_id`/`section`/`chunk_text` unchanged.
- Eval reads the same artifact-sourced `chunk_id`s; agreement computation unchanged.
- No `run_chunk`/LLM-echo call on the gold or eval path.

## Out of scope (this slice)

- Sampling strata, sheet columns, delivery bundle, eval metrics — all unchanged; this is a
  source-of-chunks swap only.
- Real Academic labels — the eval still runs against placeholder labels
  ([[eval-harness-p0-10-shipped]]); the label-swap is a separate, already-tracked concern.

## Notes

- Depends on slice 04's `read_chunks(source_id)` reader; do not re-implement it here.
- After this slice, nothing in `src/` calls the old `run_chunk` — grep to confirm the echo
  chunker is fully retired.
