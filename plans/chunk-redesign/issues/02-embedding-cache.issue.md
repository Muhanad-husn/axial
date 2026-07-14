# feat(chunk-redesign): cache per-source sentence embeddings for cheap band sweeps [slice 02]

**Spec:** specs/PRODUCT.md#5-system-overview (stage 4) · **Plan:** plans/chunk-redesign/02-embedding-cache.md
**Depends on:** #151
**Charter:** #148
**Labels:** sub:ingestion-v0

## Deliverable

The chunk stage computes each source's sentence embeddings (or the consecutive-distance
series) once and caches them under `data/chunk_cache/` (gitignored), keyed by `source_id` +
embedding-model id. Re-running the chunk stage on the same source with different band params
reshapes chunks from the cached embeddings **without re-embedding**. Changing the embedding
model invalidates the cache. Chunk output for identical inputs is byte-identical with and
without the cache.

## Acceptance criterion

```gherkin
Given a source chunked once with a counting stub embedder (cache cold)
When  the chunk stage runs again on the same source bytes with a different [min,max] band
Then  it makes zero new embedding calls (reads data/chunk_cache/), and the re-run's chunks
      match what a from-scratch run with that band would produce
And   running again after changing the embedding-model id re-embeds (cache key differs)
And   an edited source (new content-hashed source_id) never reuses another source's cache
```

## Out of scope

- Chunk boundary logic (slice 01) and examine tooling (slice 03) — unchanged. No sharing of
  the cache with downstream passes.

## Notes

- Makes the band/breakpoint sweep cheap (founder direction: never re-parse, cache embeddings).
- Add `data/chunk_cache/` to `.gitignore`; keep all of `data/` gitignored (copyright).
