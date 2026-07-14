# Slice 02: Cache per-source sentence embeddings for cheap band sweeps

- **Feature:** chunk-redesign
- **Slice slug:** embedding-cache
- **GitHub issue:** #152
- **Branch:** feat/chunk-redesign/02-embedding-cache
- **Project directory:** .
- **Status:** ☐ PR prepared — https://github.com/Muhanad-husn/axial/pull/162 (awaiting founder approval)
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

The chunk stage computes each source's sentence embeddings (or the consecutive-distance
series) **once** and caches them under `data/chunk_cache/` (gitignored), keyed by
`source_id` + embedding-model id. Re-running the chunk stage on the same source with
different band params (`[min,max]`, breakpoint settings) reshapes chunks from the cached
embeddings **without re-embedding**. A change of embedding model invalidates the cache
(the key differs), forcing a re-embed.

## INVEST check

- **Independent:** a caching layer around slice 01's embedder; changes no chunk output, only
  whether embeddings are recomputed. Chunk records for the same inputs are byte-identical
  with and without the cache.
- **Valuable:** makes the band/breakpoint sweep (the operational examine loop) cheap —
  re-running the guard with new params must not re-embed. Founder direction; memory
  [[chunk-experiment-caching]].
- **Small:** one cache read/write keyed by `source_id`+model; invalidation on model change.
- **Testable:** run the chunk stage twice on one source with a counting stub embedder;
  assert the second run makes **zero** embed calls and the same params produce identical
  chunks; assert a changed model id forces a re-embed.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a source chunked once with a counting stub embedder (cache cold)
When  the chunk stage runs again on the same source bytes with a different [min,max] band
Then  it makes zero new embedding calls (reads data/chunk_cache/), and the re-run's chunks
      match what a from-scratch run with that band would produce
And   running again after changing the embedding-model id re-embeds (cache key differs)
And   an edited source (new content-hashed source_id) never reuses another source's cache
```

- **Boundary / endpoint:** the chunk stage's embedder path (observed via embed-call count
  and `data/chunk_cache/` contents)
- **Outer test type:** pytest integration test (counting stub embedder; no network)
- **Outer test file (planned):** tests/test_chunk_cache.py — test-author, red, locked

## Inner loop — initial unit test list

- Cache key = `source_id` + model id; two sources never collide.
- Cold run writes the cache; warm run reads it and skips the embedder.
- Model-id change invalidates (re-embeds); band-param change does not (re-uses).
- Cache lives under `data/chunk_cache/` and is gitignored.

## Out of scope (this slice)

- Chunk boundary logic (slice 01) — unchanged.
- Examine tooling (slice 03).
- Any sharing of the cache with downstream passes — only the chunk stage reads it.

## Notes

- `data/chunk_cache/` must be added to `.gitignore`. Copyright hygiene: cached embeddings
  are derived vectors, but keep the whole `data/` tree gitignored as today
  ([[copyright-no-book-text-in-repo]]).
