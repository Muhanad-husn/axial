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
