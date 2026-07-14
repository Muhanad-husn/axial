# feat(chunk-redesign): embedding-based chunk stage → bounded chunks on disk [slice 01]

**Spec:** specs/PRODUCT.md#5-system-overview (stage 4), §7.7, §8 P0-4 · **Plan:** plans/chunk-redesign/01-chunk-stage.md
**Depends on:** none
**Charter:** #148
**Labels:** sub:ingestion-v0

## Deliverable

`axial chunk <source>` reads the persisted structural tree only and, for each prose
section, finds boundaries by embedding the section's sentences and splitting at
semantic-similarity troughs (gradient thresholding by default), then a deterministic guard
enforces a two-sided size band `[min,max]`: below `min`, adjacent chunks merge forward
(within-section only); above `max`, a chunk recursively splits at its next-best internal
boundary. It writes the chunk records to `data/chunks/<source_id>.jsonl` (§7.7), one JSON
object per line in section-then-position order, with **no text-generating LLM call anywhere
in the chunk path**. A garbage section (high non-alpha ratio) contributes no records and its
skip is logged; a large legitimate section is split, never skipped.

## Acceptance criterion

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
And   no text-generating LLM call is made during the run
```

## Out of scope

- Embedding cache (slice 02), `axial chunk examine` (slice 03), rewiring downstream
  consumers onto the artifact (slice 04/05). Band/breakpoint *tuning* is the operational
  examine loop, not this slice — ship sensible defaults.

## Notes

- **Contract change is spec-sanctioned:** #150 rewrote P0-4, so the test-author authors a
  new red outer test for the embedding-based behavior; the old LLM-echo outer test is replaced.
- **Embedding model is an in-slice decision** (§12): pick one with a deterministic offline
  stub for tests — the pytest gate and CI are offline, no network round-trip.
- **`nonprose_guard` size arm:** the chunk stage applies only the non-alpha garbage arm and
  splits large sections via the band's max side — size never skips (founder carry-forward).
