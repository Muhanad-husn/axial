# feat(positions-not-names): `map build --grouping category` runs extraction over category groups [slice 04]


**Spec:** docs/approach-positions-not-names.md#6-the-change · **Plan:** plans/positions-not-names/04-reformed-build-groups.md
**Depends on:** #828
**Labels:** enhancement, sub:analysis-v0

## Deliverable

`axial map build --grouping category` runs the existing selection and
extraction machinery over groups produced by slice 03's chosen split instead
of wording bags, writing a complete variant artifact set
(`data/map/<pin>-category/`) while the current build stays byte-untouched
beside it. `map.json` records grouping mode, the vocabulary scheme versions
grouped under, and ungrouped passages; a scheme-version mismatch refuses the
build. Resumable from its own ledger, exactly as today.

## Mechanism

A grouping switch at step 2 routed through slice 03's `grouping.py`, plus a
variant output directory. Extraction calls, prompts, blind render,
author-spread slicing and the resume ledger are reused unchanged.

## Acceptance criterion

```gherkin
Given built claim (and, if the chosen split needs it, mechanism) vocabularies
      and an existing default map build for the current pin
When  `uv run axial map build --grouping category` runs
Then  a variant directory (data/map/<pin>-category/) holds reads.jsonl,
      positions.jsonl and map.json, and map.json records the grouping mode,
      the vocabulary scheme versions it grouped under, and passages left
      ungrouped
And   the default build's directory is byte-identical to before the run
And   killing and re-running resumes from the variant's own ledger without
      re-asking completed slices
```

## Also in this slice: the `placed` log line

Folded in by founder ruling, 2026-08-29. This slice already edits
`src/axial/argmap/build.py`, and the defect is one line.

`build.py:1395` sets:

```python
placed = sum(position["size"] for position in raw_positions)
```

That sums member **slots** over **raw** positions — before the embedding merge,
counting a passage once per raw position it enters. On the live build it prints
**6,070** against 6,010 selected, so the log reads as if more passages were
placed than were shown. The true figure is **5,596 distinct chunk ids in
`positions.jsonl`**, leaving 414 of 6,010 unplaced (6.9%).

It is not a constant offset: 344 of the 5,596 placed chunks sit in 2-5
positions (#822), and both the raw-position count and the duplicate rate differ
per build — so the variant build's line is wrong by a different amount again.

Fix: log distinct placed chunk ids alongside the slot sum, naming which is
which.

```
raw positions N | placed slots N | distinct passages placed N | unassigned N | failed reads N
```

No behaviour outside the log line depends on `placed` today — confirm that
before changing it. #831's D4 already counts distinct chunk ids itself and is
unaffected either way.

Add one unit assertion: over a fixture where a chunk enters two raw positions,
the distinct-passages figure is below the slot sum and never exceeds selected.

## Files

```aeo-independence
slice: 04-reformed-build-groups
edits: src/axial/argmap/build.py
edits: src/axial/argmap/grouping.py
edits: src/axial/argmap/test_positions_on.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-reformed-map-build/summary.md
depends-on: 03-inner-split-chosen
```

## Out of scope

- The consolidation pass (slice 05) — this build's positions are expected to
  be fragmented across a category's groups; not a defect here.
- Relations over the variant; incremental bagging for the variant; any change
  to the default build path beyond the routing switch.

