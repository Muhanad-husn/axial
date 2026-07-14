# Slice 01: Embedding-based chunk stage → bounded chunks on disk

- **Feature:** chunk-redesign
- **Slice slug:** chunk-stage
- **GitHub issue:** #151
- **Branch:** feat/chunk-redesign/01-chunk-stage
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes — establishes the new chunk mechanism and the on-disk artifact

## Goal — the minimum testable behaviour

`axial chunk <source>` reads the persisted structural tree (`data/trees/<source_id>.json`)
and, for each prose section, finds chunk boundaries by **embedding the section's sentences
and splitting at semantic-similarity troughs** (gradient thresholding by default), then a
deterministic guard enforces a two-sided size band `[min,max]` around those breakpoints:
below `min`, adjacent chunks merge forward (within-section only); above `max`, a chunk is
recursively split at its next-best internal boundary. It writes the chunk records to
`data/chunks/<source_id>.jsonl` (§7.7) — **one JSON object per line, section-then-position
order, no text-generating LLM call anywhere in the path.** A garbage section (high
non-alpha ratio) contributes no records and its skip is logged; a large legitimate section
is split, never skipped.

## INVEST check

- **Independent:** reads only the persisted tree; adds a new embedding dependency + an
  injectable embedder. Downstream consumers still call the old `run_chunk` until slice 04 —
  this slice writes the artifact but does not yet rewire consumers.
- **Valuable:** dissolves the monster-section problem at its source and produces the
  inspectable disk artifact — the whole point of the redesign (#148 DoD).
- **Small:** one stage, one artifact format. No LLM, no downstream rewiring, no examine
  tooling (slice 03), no cache (slice 02).
- **Testable:** chunk a fixture source with a >`max` section and a garbage section; assert
  the JSONL exists, every `text` is within `[min,max]` (modulo the last chunk of a section
  or a whole section < `min`), `chunk_id`s are stable and section provenance is preserved,
  the big section produced multiple records, and the garbage section produced none (with a
  logged reason). Assert **zero LLM calls** were made.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture source whose persisted tree has (a) a normal prose section, (b) a
      legitimate section far larger than `max`, and (c) a high-non-alpha "garbage" section
When  the user runs `axial chunk <fixture>` with a deterministic stub embedder
Then  it exits 0 and writes data/chunks/<source_id>.jsonl with one JSON object per line
And   every record's `text` length is <= `max`, and >= `min` except a section's last chunk
      or a whole section shorter than `min`
And   each record carries chunk_id (`<source_id>_<section order>_<slug>_<NNN>`), section
      (verbatim heading), section_order (the tree node order), and text
And   the oversized legitimate section is split into multiple in-band records (never dropped)
And   the garbage section contributes no records and the skip + reason are logged
And   no text-generating LLM call is made during the run (chunk critical path is LLM-free)
```

- **Boundary / endpoint:** CLI command `axial chunk <file>` (behavior change: writes the
  JSONL artifact rather than emitting records to stdout)
- **Outer test type:** pytest integration test (subprocess; deterministic stub embedder,
  no network)
- **Outer test file (planned):** tests/test_chunk.py — test-author, red, locked (DEC-1).
  The existing LLM-echo outer test is replaced (P0-4 was rewritten in #150).

## Inner loop — initial unit test list

- Sentence segmentation of a section into units.
- Consecutive-distance series from the (stubbed) embedder; gradient breakpoint detection
  fires at a topic shift and not on shallow noise.
- Band guard, MAX side: a chunk over `max` recursively splits at its next-best boundary;
  no output record exceeds `max`.
- Band guard, MIN side: adjacent below-`min` chunks merge forward; merge never crosses a
  section boundary; a section tail / short section may remain below `min`.
- `chunk_id` is stable and deterministic across two runs on the same bytes; `section_order`
  disambiguates two sections sharing a heading.
- Garbage section (non-alpha arm of `nonprose_guard`) yields no records + a logged reason;
  size alone never triggers a skip.
- The JSONL is written in section-then-position order; re-run overwrites cleanly (idempotent
  on the same source bytes).

## Out of scope (this slice)

- **Embedding cache** — slice 02. Slice 01 may re-embed on every run.
- **`axial chunk examine`** — slice 03.
- **Rewiring tag/artifacts/xref/vault/gold/eval onto the artifact** — slice 04/05. Those
  keep calling the old `run_chunk` until then.
- **Band/breakpoint tuning** — ship sensible defaults (gradient; band anchored on today's
  ~1–3k chars); proving the values is the operational examine loop.

## Decisions to make in this slice

- **Embedding model** (§12 leaves it to impl): pick one with a deterministic offline stub
  for tests, mirroring `AXIAL_LLM_PROVIDER=stub`. No test may hit the network.
- **`[min,max]` default values** and the gradient threshold — sensible starting points,
  documented in the module, not asserted as final.
