# Slice 05: The consolidation pass reunites a category's arguments

- **Feature:** positions-not-names
- **Slice slug:** category-consolidation
- **Issue:** [#830](https://github.com/Muhanad-husn/axial/issues/830)
- **Branch:** feat/positions-not-names/05-category-consolidation
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Wherever a category spans more than one extraction group, a second model pass
reads that category's raw arguments and says what recurs among them — the same
judgment as extraction, one level up — replacing the embedding merge as the
primary reunifier inside a category. The embedding merge survives only for
cross-category near-duplicate folding.

## INVEST check

- **Independent:** consumes slice 04's variant reads ledger; touches nothing
  in the default build.
- **Valuable:** closes the failure mode that made "only step 2 moves" wrong —
  without it, wording similarity silently carries the reunification and the
  re-formed map cannot be trusted (approach §6).
- **Small:** one new pass with its own prompt, ledger, and fold step; the
  wiring is a stage between extraction and merge.
- **Testable:** with a fake client, per-group namings of one argument fold to
  one position with the union of chunk_ids; cross-category merge behaviour is
  pinned by test.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a variant build whose reads span multiple groups inside one category
When  `uv run axial map build --grouping category` runs its consolidation stage
Then  positions.jsonl carries one position where one argument was named from
      several groups of the same category, with the union of its chunk_ids
      and a consolidated_from count
And   map.json reports raw positions, consolidated positions, and the final
      merged count separately
And   the consolidation stage has its own resume ledger, so a kill mid-pass
      never re-asks a completed category
And   genuinely opposed arguments inside one category survive as separate
      positions
```

- **Boundary / endpoint:** CLI — the consolidation stage of `uv run axial map build --grouping category`
- **e2e test type:** API/integration test (pytest, CLI-level, injected fake LLM client)
- **e2e test file (planned):** src/axial/argmap/test_consolidate.py

## Files (parallel-safety declaration)

```aeo-independence
slice: 05-category-consolidation
creates: src/axial/argmap/consolidate.py
creates: src/axial/argmap/test_consolidate.py
edits: src/axial/argmap/build.py
edits: src/axial/argmap/test_positions_on.py
creates: data/logs/2026-08-28-consolidation-pass/summary.md
depends-on: 04-reformed-build-groups
```

## Inner loop — initial unit test list

- [ ] A category whose arguments all came from one group is passed through
      without a model call.
- [ ] Two per-group namings folded by the model become one position: union of
      chunk_ids, sources, authors; `consolidated_from: 2`.
- [ ] The prompt forbids fusing opposed accounts (same rule as extraction);
      a model answer keeping them apart yields two positions.
- [ ] A handle the model invents is dropped and counted, never repaired
      (extraction's fault-isolation contract, mirrored).
- [ ] Resume ledger keyed by category and content hash; completed categories
      skipped on restart.
- [ ] Embedding merge now folds only across categories; two same-category
      positions are never folded by embedding distance alone.

## Operational steps inside the slice

1. Run the full variant build (extraction resumes from slice 04's ledger,
   consolidation runs fresh) in the main checkout, detached; write
   `data/logs/2026-08-28-consolidation-pass/`.
2. Summary records: raw → consolidated → merged counts, model calls spent,
   and the reasoning setting used (`config/pipeline.yaml`, same treatment as
   `position_extract`).

## Out of scope for this slice (deferred)

- The structural comparison (slice 06) — this slice produces the map, the
  next one judges it.
- Tuning the consolidation prompt beyond parity with extraction's rules.
- Consolidation across categories — that remains the embedding merge's job,
  by design (approach §6).

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Real-corpus consolidation complete, counts in the log.
- [ ] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
