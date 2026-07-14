# feat(chunk-redesign): `axial chunk examine` — inspect chunk quality, zero LLM spend [slice 03]

**Spec:** specs/PRODUCT.md#7.7, §8 P0-4b · **Plan:** plans/chunk-redesign/03-chunk-examine.md
**Depends on:** #151
**Charter:** #148
**Labels:** sub:ingestion-v0

## Deliverable

`axial chunk examine` reads the on-disk chunk artifact(s) under `data/chunks/` and reports
chunk-quality stats making **zero LLM and zero embedding-model calls**: total and per-source
chunk counts; size distribution (min/max/mean/median), from which the two-sided band is
verifiable; a boundary-sanity summary (chunks above `max`, chunks below `min`, sections
split, sections skipped-as-garbage with reasons); and an eyeball sample of chunk texts. It
never mutates the artifact.

## Acceptance criterion

```gherkin
Given a fixture data/chunks/ with known chunk counts, a known size distribution, one section
      split into multiple chunks, and one recorded garbage-skip
When  the user runs `axial chunk examine`
Then  it exits 0 and reports total + per-source counts, the size distribution
      (min/max/mean/median), and boundary sanity (chunks above max, chunks below min,
      sections split, sections skipped-as-garbage with reasons), plus a chunk-text sample
And   the numbers match the fixture and no chunk above `max` is reported
And   the command makes zero LLM calls and zero embedding-model calls, and modifies no file
      under data/chunks/
```

## Out of scope

- Producing chunks (slice 01) or caching embeddings (slice 02). No scoring/judgment beyond
  the stats — examine reports, the operator judges.

## Notes

- This is the instrument that **proves** the gradient/band defaults from slice 01 (founder
  direction: prove with examine, don't assert).
- Depends on how slice 01 records garbage-skips so examine can report them without re-running
  the guard; if slice 01 does not persist skip reasons, that gap is flagged for a slice-01 follow-up.
