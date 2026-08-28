# Slice 06: `axial map compare` — the structural verdict and the go/no-go

- **Feature:** positions-not-names
- **Slice slug:** structural-comparison
- **Issue:** [#831](https://github.com/Muhanad-husn/axial/issues/831)
- **Branch:** feat/positions-not-names/06-structural-comparison
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial map compare <dir-a> <dir-b>` puts two map builds side by side on
structure alone — no judged gate, no model calls — so the founder can decide
whether the re-formed map earned everything after it. This is the feature's
hard gate: slices 07–09 do not start until the founder says go on this
slice's output.

## INVEST check

- **Independent:** reads two `positions.jsonl`/`map.json` pairs already on
  disk; the purity command from slice 02 is re-run alongside, unchanged.
- **Valuable:** the decision the whole feature turns on gets made on
  evidence; the saturated judged gate is deliberately not trusted with it.
- **Small:** one read-and-report module over artifacts with a stable shape.
- **Testable:** deterministic tables over fixture position files.

## Acceptance criterion (outer loop — the failing e2e/integration test)

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

- **Boundary / endpoint:** CLI — `uv run axial map compare <dir-a> <dir-b>`
- **e2e test type:** API/integration test (pytest, CLI-level, tmp fixture dirs)
- **e2e test file (planned):** src/axial/argmap/test_compare.py

## Files (parallel-safety declaration)

```aeo-independence
slice: 06-structural-comparison
creates: src/axial/argmap/compare.py
creates: src/axial/argmap/test_compare.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-map-structural-comparison/summary.md
depends-on: 05-category-consolidation
```

## Inner loop — initial unit test list

- [ ] Size distribution and single-passage share computed from a fixture
      positions.jsonl.
- [ ] Cross-book rate: share of positions whose sources span 2+ books.
- [ ] Passages reaching no position: selected minus placed, read from each
      build's own manifest counts.
- [ ] `consolidated_from` summed only when present; absent on the default
      build without error.
- [ ] Comparing builds with different corpus pins refuses with a clear
      message.

## Operational steps inside the slice

1. Run the comparison over the two real builds; re-run
   `axial map purity --column mechanism` against the variant's groups for
   the purity-after number; write
   `data/logs/2026-08-28-map-structural-comparison/`.
2. Hand-sample misassigned passages: pull a dozen positions and read whether
   their members belong together — the one judgment step, recorded as prose
   in the summary with the sampled ids.
3. Quote every margin against the run-to-run noise already measured; the
   assignment-disagreement rate is quoted next to the verdict (approach §6,
   noise policy).
4. **Founder go/no-go on slices 07–09.** Recorded in the summary and in the
   feature README.

## Out of scope for this slice (deferred)

- Any judged (model-graded) comparison — needs a gate harder than the
  saturated smoke set, which is separate work.
- Any change to either build.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Comparison + hand-sample done, log written, founder verdict recorded.
- [ ] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
