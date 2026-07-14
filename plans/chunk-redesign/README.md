# Feature: Chunk redesign — embedding-based, disk-first, LLM-independent

Charter **#148**. Split **parse → chunk** out of the LLM layer into its own pipeline
stage that produces a cheap, inspectable artifact on disk *before* any LLM spend:
`tree → [chunk stage] → data/chunks/<source_id>.jsonl → examine → LLM tag/artifacts/xref`.
The spec pass (charter slice 1) is ratified and merged in **#150**: boundary method =
embedding-based semantic chunking; every chunk bounded by construction into a two-sided
band `[min,max]`; on-disk JSONL artifact (§7.7); `axial chunk examine` (P0-4b); envelope
dropped from the chunk stage. This feature folder decomposes the remaining build work
(charter slices 2–5) into shippable slices. Covers PRD §5 stage 4, §7.7, P0-4, P0-4b.

- **Slug:** chunk-redesign
- **Created:** 2026-07-14
- **Status:** planning
- **New system?** no — reworks the existing `src/axial/chunk.py` (LLM-echo chunker) and
  its consumers (`tag`, `artifacts`, `xref`, `vault`, `gold`, `eval`)
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Depends on | Size | Status | Issue | PR |
|---|-------|-----------------|-----------|------|--------|-------|----|
| 01 | [chunk-stage](01-chunk-stage.md) | `axial chunk <src>` embeds sentences, splits at semantic troughs, enforces the `[min,max]` band, writes `data/chunks/<source_id>.jsonl` — **no LLM in the chunk path** | none | L | ☐ todo | [#151](https://github.com/Muhanad-husn/axial/issues/151) | — |
| 02 | [embedding-cache](02-embedding-cache.md) | per-source sentence embeddings cached in `data/chunk_cache/` keyed by `source_id`+model; a band re-sweep re-runs the guard without re-embedding | 01 | S | ☐ todo | [#152](https://github.com/Muhanad-husn/axial/issues/152) | — |
| 03 | [chunk-examine](03-chunk-examine.md) | `axial chunk examine` reports counts, size distribution, and boundary sanity off the JSONL — **zero LLM, zero embedding-model calls** | 01 | M | ☐ todo | [#153](https://github.com/Muhanad-husn/axial/issues/153) | — |
| 04 | [pipeline-rewire](04-pipeline-rewire.md) | `tag`/`artifacts`/`xref`/`vault` consume `data/chunks/<source_id>.jsonl`; the LLM-echo chunker is removed; #147 reasoning-disable kept for the remaining LLM passes | 01 | L | ☐ todo | [#154](https://github.com/Muhanad-husn/axial/issues/154) | — |
| 05 | [gold-eval-migration](05-gold-eval-migration.md) | `gold` sampling and the `eval` harness read the on-disk chunk artifact instead of re-deriving chunks in-process | 04 | M | ☐ todo | [#155](https://github.com/Muhanad-husn/axial/issues/155) | — |
| 06 | [recursive-mechanism](06-recursive-mechanism.md) | a second, **selectable** LLM-free/embedder-free recursive/structural splitter (`\n\n`→`\n`→sentence→char) behind `_chunk_section_text`, writing the identical §7.7 artifact — for the `examine` head-to-head; embedding stays the default | 01, 03, 04 | M | ⏳ PR open | [#165](https://github.com/Muhanad-husn/axial/issues/165) | [#181](https://github.com/Muhanad-husn/axial/pull/181) |

Slices 02 and 03 are independent of each other and can run in parallel once 01 lands.
04 waits on 01; 05 waits on 04. 06 is an added, out-of-band slice (charter #148): it
sequences after 04 (single disk-consumption path) and 03 (the examine surface it
A/Bs through), and reuses slice 01's band machinery; the embedding mechanism stays
the default.

## Out of scope (whole feature)

- **#147 disable-reasoning** — the immediate canary hotfix on `fix/llm/147-disable-reasoning`
  (committed `1e857b7`, green, unmerged). Keep it and merge on founder approval independently;
  slice 04 keeps `reasoning:{enabled:false}` for the remaining (non-chunk) LLM passes but does
  not re-do #147.
- **Chunk-quality / band tuning** — sweeping `[min,max]` and breakpoint settings to find good
  values is an *operational* loop run via `axial chunk examine` (slice 03) after 01/02 land,
  not a coded slice. Slice 01 ships sensible defaults (gradient thresholding, band anchored on
  today's ~1–3k-char working size); it does not claim the defaults are final.
- **Envelope pass** — unchanged; tagging still reads `data/envelopes/`. The chunk stage no
  longer consumes it (§5 stage 3, §7.3).
- **Re-parsing / docling** — every slice reads the persisted tree (`data/trees/<source_id>.json`)
  only. No slice re-triggers docling.

## Notes / open questions

- **Slice 01 changes P0-4's outer contract deliberately.** The current `axial chunk` outer
  test encodes the old LLM-echo behavior (one call per section, echoing text back). #150
  rewrote P0-4, so the test-author authors a *new* red outer test for the embedding-based
  behavior in slice 01; the old outer test is replaced, not weakened in place. This is a
  spec-sanctioned contract change (the spec already merged), not spec drift.
- **Embedding model is an in-slice-01 decision (§12 leaves it to impl).** Constraint: the
  chunk stage needs an **injectable embedder with a deterministic offline stub for tests**,
  mirroring the existing `AXIAL_LLM_PROVIDER=stub` seam — the pre-commit pytest gate and CI
  are offline, so no slice may require a network round-trip to embed.
- **Gradient thresholding is the preferred starting point, not a locked requirement**
  (founder direction). Slice 01 defaults the breakpoint detector to gradient; whether it
  stays is proven via slice 03's size-distribution / boundary-sanity stats, not asserted.
- **`nonprose_guard.py` size arm.** Today it *skips* sections over `MAX_CHARS=30000`; the new
  spec forbids skipping on size ("size never skips; split instead"). Slice 01's chunk stage
  applies only the non-alpha garbage arm and splits large legitimate sections via the band's
  max-side recursive split. The shared `MAX_CHARS` constant stays for the other callers
  (`xref`/`tag`/`artifacts`) until slice 04 rewires them onto already-bounded disk chunks,
  after which the size arm is effectively dead for the chunk path.
- **Section-tail / short-section exception is intentional** (founder direction): a section
  tail, or a whole section shorter than `min`, may stay below `min` — merging across a
  section boundary would break `chunk_id`/provenance. The band's min-side merge is
  within-section only.
