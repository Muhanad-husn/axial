# feat(positions-not-names): `axial map compare` delivers the structural verdict [slice 06]

**Spec:** docs/approach-positions-not-names.md#13-the-work-in-order · **Plan:** plans/positions-not-names/06-structural-comparison.md
**Depends on:** #830
**Labels:** enhancement, sub:analysis-v0

## Deliverable

`axial map compare <dir-a> <dir-b>` puts two map builds side by side on
structure alone — position count, size distribution, single-passage share,
cross-book rate, passages reaching no position, and (for the variant) how
many positions consolidation reunited. No judged gate, no model calls: the
saturated smoke gate is deliberately not trusted with this decision. The
slice ends with a hand-sample of positions, margins quoted against measured
noise, and the founder's go/no-go on slices 07–09 recorded in the run log
and the feature README. **This is the feature's hard gate.**

## Mechanism

A read-and-report module over `positions.jsonl`/`map.json` pairs, plus a
re-run of slice 02's `map purity` against the variant's groups. Comparing
builds with different corpus pins refuses.

## Acceptance criterion

```gherkin
Given the default build and the variant build for the same corpus pin
When  `uv run axial map compare data/map/<pin> data/map/<pin>-category` runs
Then  it prints, per build: position count, position-size distribution
      (median and quartiles), single-passage-position share, cross-book
      position rate, and passages reaching no position
And   for the variant: how many positions the consolidation pass reunited
And   the two builds print side by side in one table with the pin and both
      artifact paths named
```

## Files

```aeo-independence
slice: 06-structural-comparison
creates: src/axial/argmap/compare.py
creates: src/axial/argmap/test_compare.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-map-structural-comparison/summary.md
depends-on: 05-category-consolidation
```

## Out of scope

- Any judged (model-graded) comparison — needs a gate harder than the
  saturated smoke set, which is separate work.
- Any change to either build.
