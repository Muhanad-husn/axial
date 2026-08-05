# Slice 04: Downstream passes consume the disk artifact; remove the LLM-echo chunker

- **Feature:** chunk-redesign
- **Slice slug:** pipeline-rewire
- **GitHub issue:** #154
- **Branch:** feat/chunk-redesign/04-pipeline-rewire
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`tag`, `artifacts`, `xref`, and the `vault` writer read prose chunks from
`data/chunks/<source_id>.jsonl` (§7.7) instead of calling `run_chunk` in-process, and the
old LLM-echo chunker (`chunk.py`'s per-section echo call + its envelope dependency) is
removed. The pipeline order becomes: `chunk` writes the artifact → downstream LLM passes
consume it. #147's `reasoning:{enabled:false}` is kept for the remaining (non-chunk) LLM
passes. No chunk boundary is ever recomputed by a downstream pass.

## INVEST check

- **Independent:** consumes slice 01's artifact; changes the *source* of chunks for
  downstream passes without changing what those passes do with a chunk. The chunk stage
  itself is unchanged from slice 01.
- **Valuable:** completes the disk-first inversion — downstream never triggers an LLM-echo
  chunk, and the monster-section failure path is gone from every consumer (#148 DoD).
- **Small-ish (L):** a mechanical swap of one call (`run_chunk(...)`) for one reader
  (`read_chunks(source_id)`) across four consumers, plus deletion of the old chunker body.
  Bounded by the four call sites already enumerated (`tag.py`, `xref.py`, `vault.py`,
  `artifacts` path).
- **Testable:** run `axial vault`/`axial tag`/`axial xref` against a source whose
  `data/chunks/<source_id>.jsonl` exists; assert they read it (a sentinel record flows
  through to output) and make **no chunk-pass LLM call**; assert `run_chunk`'s echo path is
  gone.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a source with data/chunks/<source_id>.jsonl already written by `axial chunk`
When  the user runs the downstream passes (tag, artifacts, xref, vault) on that source
Then  each pass reads chunks from data/chunks/<source_id>.jsonl (the artifact's records
      flow through to their output) and makes no LLM call to (re)chunk
And   the pipeline makes zero calls into the removed LLM-echo chunk path
And   running a downstream pass with no chunk artifact present fails with a clear message
      telling the operator to run `axial chunk` first (no silent re-derivation)
```

- **Boundary / endpoint:** the `tag` / `artifacts` / `xref` / `vault` CLI passes
- **Outer test type:** pytest integration test (subprocess; stub LLM; no network)
- **Outer test file (planned):** tests/test_pipeline_rewire.py (or extend the existing
  tag/xref/vault outer tests) — test-author, red, locked

## Inner loop — initial unit test list

- A `read_chunks(source_id)` reader parses `data/chunks/<source_id>.jsonl` into chunk
  records with the §7.7 fields.
- `tag` consumes the reader (was `run_chunk`); tagged output preserves `chunk_id`/provenance.
- `xref` consumes the reader; link pairs still reference the right `chunk_id`s.
- `vault` writes one prose note per artifact record (was per `run_chunk` record).
- `artifacts` path unaffected by chunk source but verified still routed correctly.
- Missing-artifact error: a downstream pass with no JSONL exits non-zero, "run `axial chunk`
  first" — never re-derives chunks in-process.
- The old echo-chunker code path and its envelope import are deleted; nothing imports it.

## Out of scope (this slice)

- **gold / eval** migration — slice 05.
- **The chunk stage's own mechanism** — slice 01; unchanged here.
- **#147** — kept as-is for the remaining LLM passes; not re-implemented.

## Notes

- Consumers today (memory [[parallel-119-132-worktree]], and `grep run_chunk src/`):
  `tag.py`, `xref.py`, `vault.py`, `gold.py`. `gold.py` moves in slice 05; this slice does
  `tag`/`artifacts`/`xref`/`vault`.
- `nonprose_guard`'s size arm becomes effectively dead for the chunk path once consumers
  read already-bounded (≤`max`) disk chunks — leave the shared constant for any non-chunk
  caller, but the chunk consumers no longer skip on size.
- Full acceptance suite runs once here (blast radius is wide) per [[tiered-test-suite-principle]].
