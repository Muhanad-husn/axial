# feat(chunk-redesign): downstream passes consume disk chunks; remove LLM-echo chunker [slice 04]

**Spec:** specs/PRODUCT.md#7.7, §8 P0-4b (downstream consume) · **Plan:** plans/chunk-redesign/04-pipeline-rewire.md
**Depends on:** #151
**Charter:** #148
**Labels:** sub:ingestion-v0

## Deliverable

`tag`, `artifacts`, `xref`, and the `vault` writer read prose chunks from
`data/chunks/<source_id>.jsonl` (§7.7) instead of calling `run_chunk` in-process, and the
old LLM-echo chunker (the per-section echo call and its envelope dependency) is removed.
Pipeline order becomes: `chunk` writes the artifact → downstream LLM passes consume it. No
downstream pass recomputes a chunk boundary. #147's `reasoning:{enabled:false}` is kept for
the remaining (non-chunk) LLM passes.

## Acceptance criterion

```gherkin
Given a source with data/chunks/<source_id>.jsonl already written by `axial chunk`
When  the user runs the downstream passes (tag, artifacts, xref, vault) on that source
Then  each pass reads chunks from data/chunks/<source_id>.jsonl (the artifact's records flow
      through to their output) and makes no LLM call to (re)chunk
And   the pipeline makes zero calls into the removed LLM-echo chunk path
And   running a downstream pass with no chunk artifact present fails with a clear message
      telling the operator to run `axial chunk` first (no silent re-derivation)
```

## Out of scope

- gold / eval migration (slice 05). The chunk stage's own mechanism (slice 01) is unchanged.
  #147 is kept as-is, not re-implemented.

## Notes

- Call sites to swap (`grep run_chunk src/`): `tag.py`, `xref.py`, `vault.py` (and the
  artifacts path); `gold.py` moves in slice 05.
- Introduce a `read_chunks(source_id)` reader for the §7.7 JSONL; slices 05 reuses it.
- Wide blast radius → run the full acceptance suite once on this PR.
