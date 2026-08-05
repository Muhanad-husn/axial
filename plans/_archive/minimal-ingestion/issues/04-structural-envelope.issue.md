# feat(minimal-ingestion): structural envelope — one LLM call per source, written once [slice 04]

**Spec:** specs/PRODUCT.md §5 (stage 3), §7.3, §8 P0-3 · **Plan:** plans/minimal-ingestion/04-structural-envelope.md
**Depends on:** #14 (slice 02 structural-extraction)
**Labels:** sub:ingestion-v0

## Deliverable

`axial envelope <file>` makes one LLM call per source over its
intro/abstract/conclusion (from the extraction tree) and writes an envelope JSON
— `{source_id, author, title, date, thesis, toc[], scope, stated_argument}` — to
`data/envelopes/`. Re-running for a source that already has an envelope reuses the
stored file (no recompute, §10). Introduces the fake-able LLM client seam
(interface + fixture-backed stub for tests; a thin real OpenRouter client behind
the same interface, never called live in CI) and `config/pipeline.yaml` provider
config. This is P0-3.

## Acceptance criterion

```gherkin
Given an extracted fixture source and the LLM provider configured to the stub client
When  the user runs `axial envelope <fixture>`
Then  it exits 0 and writes data/envelopes/<source_id>.json with thesis, toc, scope, and stated_argument
And   running `axial envelope <fixture>` again reuses the stored envelope without a second LLM call
```

## Out of scope

Chunking's use of the envelope (slice 05); model-per-pass tuning; retries/backoff
beyond a minimal shape; the NVIDIA provider (OpenRouter suffices for v0). Live API
calls are never made in tests.
