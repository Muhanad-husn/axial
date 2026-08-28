# feat(positions-not-names): a consolidation pass reunites a category's arguments [slice 05]

**Spec:** docs/approach-positions-not-names.md#6-the-change · **Plan:** plans/positions-not-names/05-category-consolidation.md
**Depends on:** #829
**Labels:** enhancement, sub:analysis-v0

## Deliverable

Wherever a category spans more than one extraction group, a second model pass
reads that category's raw arguments and says what recurs among them — the
same judgment as extraction, one level up — replacing the embedding merge as
the primary reunifier inside a category. The embedding merge survives only
for cross-category near-duplicate folding. Without this pass, wording
similarity silently carries the reunification and the re-formed map cannot
be trusted (the approach's §6 failure mode).

## Mechanism

One new pass mirroring extraction's contract: its own prompt (same
no-fusing-opposed-accounts rule), its own resume ledger keyed by category and
content hash, the same fault isolation. Wired as a stage between extraction
and merge in the variant build.

## Acceptance criterion

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

## Files

```aeo-independence
slice: 05-category-consolidation
creates: src/axial/argmap/consolidate.py
creates: src/axial/argmap/test_consolidate.py
edits: src/axial/argmap/build.py
edits: src/axial/argmap/test_positions_on.py
creates: data/logs/2026-08-28-consolidation-pass/summary.md
depends-on: 04-reformed-build-groups
```

## Out of scope

- The structural comparison (slice 06); prompt tuning beyond parity with
  extraction's rules; consolidation across categories (the embedding merge's
  job, by design).
