# feat(positions-not-names): the inner split is computed both ways and chosen [slice 03]

**Spec:** docs/approach-positions-not-names.md#6-the-change · **Plan:** plans/positions-not-names/03-inner-split-chosen.md
**Depends on:** #827
**Labels:** enhancement, sub:analysis-v0

## Deliverable

`axial map grouping-report` computes, offline and with zero model calls, both
candidate groupings from the approach's §6 — claim × mechanism intersection,
and per-claim-category embedding sub-clustering — over the real corpus, and
prints group-size distributions, coverage lost, and projected extraction
slice counts side by side. The slice ends in a founder choice of one split,
recorded in the run log; slice 04 builds only the chosen variant.

## Mechanism

Two grouping functions: a join over `data/vocabulary/` columns, and a
sub-cluster reusing `build.py`'s existing injectable encoder/cluster seams.
The functions are exactly what slice 04 wires into the build — nothing here
is throwaway.

## Acceptance criterion

```gherkin
Given data/vocabulary/claim/ and data/vocabulary/mechanism/ exist and the
      current build's selected passages are readable
When  `uv run axial map grouping-report` runs
Then  it prints, per candidate: group count, group-size min/median/max,
      passages left ungrouped, and projected extraction slices at
      EXTRACT_SLICE
And   the two candidates print side by side in one table
```

## Files

```aeo-independence
slice: 03-inner-split-chosen
creates: src/axial/argmap/grouping.py
creates: src/axial/argmap/test_grouping.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-inner-split-choice/summary.md
depends-on: 02-bag-purity-crosstab
```

## Out of scope

- Wiring either grouping into `map build` (slice 04); any model call; a
  third candidate — if both measure badly, that is a founder conversation.
