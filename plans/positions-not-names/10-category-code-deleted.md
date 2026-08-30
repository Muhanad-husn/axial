# Slice 10: The shelved category-grouping code is deleted

- **Feature:** positions-not-names (closing chore)
- **Slice slug:** category-code-deleted
- **Branch:** chore/positions-not-names/10-category-code-deleted
- **Project directory:** .
- **Issue:** [#850](https://github.com/Muhanad-husn/axial/issues/850)
- **Status:** planned (2026-08-30)
- **Walking skeleton?** no
- **Depends on:** nothing open — #831, #837, #835 closed, records on `main`

## Goal — the minimum testable behaviour

The shelved category-grouping rebuild (DEC-74) comes out of the tree in one
PR: the four dead modules (`purity`, `grouping`, `consolidate`, `compare` and
their tests), the category branch in `build.py`, and the `map purity` /
`map grouping-report` / `map compare` / `map build --grouping` CLI surface —
while the default build path, the vocabulary layer, and `positions_on`
retrieval stay byte-for-byte in behaviour. The issue body is the contract;
this plan only frames it for the lane.

## INVEST check

- **Independent:** pure subtraction; nothing open depends on it.
- **Valuable:** the tree stops carrying, importing and CI-exercising a path
  nobody will take again (the point of DEC-74's shelving).
- **Small:** large in lines (~8,800 across 8 files), small in judgment — the
  issue pre-adjudicates every deletion and every keep.
- **Testable:** the acceptance Gherkin in #850, plus the $0 resume check.

## Acceptance criterion (outer loop)

Verbatim from #850 — that Gherkin is the locked outer test. Decisive checks:

1. `uv run pytest` green, `uv run ruff check` clean, full `tests/` tree green
   in CI.
2. `uv run axial map build` before and after: manifest resumes byte-identical
   (`units_reused: 679`, `units_asked: 0`, $0). If the manifest moves, stop.
3. `git grep -l "argmap.purity\|argmap.grouping\|argmap.consolidate\|argmap.compare"`
   returns nothing under `src/`.
4. No live `map ask` — costs money, touches nothing deleted.

- **Boundary / endpoint:** CLI — retired subcommands and `--grouping` refuse;
  `vocabulary build` and `map ask` still offered
- **e2e test type:** pytest, CLI-level
- **e2e test file:** src/axial/test_cli.py (edited, not deleted)

## Files (parallel-safety declaration)

Deletions declared as edits, per convention. The keep-list (vocabulary layer,
`vocabulary_join`, `ask.py`, default build path) is in #850 and is not
restated here.

```aeo-independence
slice: 10-category-code-deleted
edits: src/axial/argmap/purity.py
edits: src/axial/argmap/test_purity.py
edits: src/axial/argmap/grouping.py
edits: src/axial/argmap/test_grouping.py
edits: src/axial/argmap/consolidate.py
edits: src/axial/argmap/test_consolidate.py
edits: src/axial/argmap/compare.py
edits: src/axial/argmap/test_compare.py
edits: src/axial/argmap/build.py
edits: src/axial/argmap/test_positions_on.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
```

## Inner loop — initial unit test list

- [ ] `map build --help` offers no `--grouping`; `map purity`,
      `map grouping-report`, `map compare` are unknown subcommands.
- [ ] `uv run axial --help` still offers `vocabulary build` and `map ask`.
- [ ] `test_positions_on.py` minus its seven category tests (:431–:695), the
      `category_corpus` fixture and the consolidate import stays green.
- [ ] `test_cli.py` keeps `test_main_vocabulary_examine_…` (:542) and
      `test_main_eval_layers_forwards_every_arm_dir_to_compare_arms` (:1687).
- [ ] `build_argument_map` loses the `grouping` parameter entirely
      (single-valued parameter = named tripwire; state the call in the PR).

## Operational steps inside the slice

1. Pin the before-state: run `uv run axial map build` on `main`, keep the
   manifest for the diff.
2. Delete the four module pairs and the category branch in `build.py` in one
   commit train; suite green at the end, not necessarily each step (the
   modules import each other).
3. Strip the CLI surface and the two dead imports (`cli.py:19`, `:23`).
4. Edit, don't delete, the two mixed test files per #850's line ranges.
5. Re-run `map build`, diff the manifest against step 1.
6. PR body records SHA `53165ff` as the restore point for every deleted file.

## Out of scope (from #850)

- The vocabulary layer, including the dormant `use_vocabulary` ask step.
- The approach doc, plan files, `docs/tdd-evidence/`, DEC-74.
- Anything under `data/` — the 17MB category artifacts cost $2.50/7.5h and
  stay.
- Any change to default build behaviour.

## Definition of done

- [x] Acceptance Gherkin from #850 green (fast tier local; full tree runs in CI on PR #851).
- [x] Manifest diff empty on the $0 resume check (modulo `wall_time_sec`/`runs`, which accumulate on every resume by design).
- [x] `grouping` parameter decision stated in the PR body (removed from the signature).
- [x] Evidence collected and PR #851 opened into main (`safe-pr`), closing #850.

## Status / progress log

- 2026-08-30 planned from #850's body (sprint-plan on a single filed issue —
  the issue is the draft and the contract; no new issues filed).
- 2026-08-30 built. Acceptance tests written first and watched red (5 red, 1
  keep-guard green); 8 files deleted, build.py/cli.py stripped, two mixed
  test files edited. −10,875/+192 lines. Fast tier green (exit 0), ruff
  clean, `git grep` criterion empty. Two deviations from the issue, stated
  in the PR: `_prior_pin_dir` keeps its `-category` exclusion (the variant
  artifacts stay on disk and would otherwise become a seedable prior pin),
  and `test_a_later_default_build_never_treats_a_category_variant_as_a_prior_pin`
  plus `test_distinct_placed_passages_are_counted_below_the_slot_sum` stay
  (they pin kept behaviour). The manifest is byte-identical except
  `wall_time_sec`/`runs`, which accumulate by design on every resume — the
  issue's "byte-identical" claim was optimistic about those two fields.
- 2026-08-30 PR opened: https://github.com/Muhanad-husn/axial/pull/851. Reviewer and verifier dispatched, findings to follow as advisory PR comments.
