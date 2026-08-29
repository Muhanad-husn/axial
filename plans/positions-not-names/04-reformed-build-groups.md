# Slice 04: `map build --grouping category` — extraction over category groups

- **Feature:** positions-not-names
- **Slice slug:** reformed-build-groups
- **Issue:** [#829](https://github.com/Muhanad-husn/axial/issues/829)
- **Branch:** feat/positions-not-names/04-reformed-build-groups
- **Project directory:** .
- **Status:** ☑ PR open (#844), awaiting founder approval
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial map build --grouping category` runs the existing selection and
extraction machinery over groups produced by slice 03's chosen split instead
of wording bags, writing a complete variant artifact set into its own
directory while the current build stays byte-untouched beside it.

## INVEST check

- **Independent:** grouping functions exist (slice 03); extraction, resume
  ledger, and merge are reused as they stand.
- **Valuable:** the re-formed map exists on disk for the first time — the
  thing slice 06 measures.
- **Small:** the delta is a grouping switch at step 2 and a variant output
  directory; extraction calls, prompts, and ledger mechanics are unchanged.
- **Testable:** with an injected fake client, the variant build produces the
  full artifact set from fixture answers; the default path is proven
  untouched.

## Acceptance criterion (outer loop — the failing e2e/integration test)

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

- **Boundary / endpoint:** CLI — `uv run axial map build --grouping category`
- **e2e test type:** API/integration test (pytest, CLI-level, injected fake LLM client)
- **e2e test file (planned):** src/axial/argmap/test_positions_on.py (extended)

## Files (parallel-safety declaration)

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

## Inner loop — initial unit test list

- [ ] `--grouping category` routes step 2 through slice 03's chosen grouping;
      the default path still bags by wording, untouched.
- [ ] The variant writes under `<pin>-category/`, never under `<pin>/`.
- [ ] `map.json` records grouping mode and the scheme versions; a scheme
      version mismatch against `data/vocabulary/` refuses the build rather
      than grouping under a stale scheme.
- [ ] Ungrouped passages (refused on a grouping axis) are counted in
      `map.json`, parallel to today's `passages_unassigned`.
- [ ] Resume: a seeded ledger line for a (group, slice) key is skipped.
- [ ] Author-spread slicing and the blind render apply to category groups
      exactly as to bags.
- [ ] **The `placed` log line** (folded in 2026-08-29). `build.py:1395` sums
      position sizes over *raw* positions — member slots, 6,070 against 6,010
      selected on the live build. Log distinct placed chunk ids alongside the
      slot sum, naming which is which. Over a fixture where one chunk enters
      two raw positions, the distinct figure is below the slot sum and never
      exceeds selected.

## Operational steps inside the slice

1. Run the variant build over the real corpus, detached, journaled,
   checkpointed, in the main checkout; write
   `data/logs/2026-08-28-reformed-map-build/`.
2. Record read counts, ungrouped counts, cost and wall time in the summary.

## Out of scope for this slice (deferred)

- The consolidation pass (slice 05) — this build's positions are expected to
  be fragmented across a category's groups; that is not a defect here.
- Relations over the variant (slice 07).
- Incremental bagging for the variant (bag_state reuse) — a later concern,
  the pin is stable.
- Any change to the default build path beyond the routing switch.

## Definition of done

- [x] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [x] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [x] Refactor pass complete with the bar green.
- [x] Slice's tests run in CI (`tdd-ci`).
- [x] Real-corpus variant build complete, log written, default build verified untouched.
- [x] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
- 2026-08-29 built, real-corpus variant build run ($0.7052, 41m, 226 reads over
  176 groups). PR [#844](https://github.com/Muhanad-husn/axial/pull/844), CI
  green. Reviewer and verifier both DONE_WITH_CONCERNS; all ten findings fixed
  on the branch. Awaiting founder approval.
