# Slice 09: Demolition — the name layer and its dependents come out

- **Feature:** positions-not-names
- **Slice slug:** demolition
- **Branch:** feat/positions-not-names/09-demolition
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Gated on:** slices 06 (founder go), 07 and 08 shipped — nothing is
  deleted until what replaces it is live (approach §9's ordering rule).

## Goal — the minimum testable behaviour

Everything slices 06–08 made redundant is removed — the name pages as a
structure, the disagreement-manufacturing pass, the name-walking retrieval
loop, the residue pass, the vocabulary measurement apparatus, and the eval
code nothing remaining reads — leaving the name index itself as a filter, the
suite green, and every deletion citing the slice that made it safe.

**Absorbs [#825](https://github.com/Muhanad-husn/axial/issues/825)** (founder
ruling, 2026-08-28): the category join comes out here too —
`axial.argmap.vocabulary_join` and its tests, the `map+vocab` arm and its
four CLI knobs, the `vocabulary` block in the answer record, and the third
arm's paragraphs in `specs/PHASE-B.md` §7.17/§7.19 (the two measured
findings inside them move, not drop — see #825's body for the list). #825's
keep-list is already this feature's keep-list. The slice-09 PR closes #825
alongside its own issue.

## INVEST check

- **Independent:** pure subtraction once its gates are passed; no new
  behaviour.
- **Valuable:** the stated point of the feature — the codebase sheds its
  largest dead weight and the product keeps only what the measurements
  defended.
- **Small:** large in lines, small in judgment — every deletion is
  pre-justified; anything contested stays and is filed instead.
- **Testable:** the suite is green after removal; the kept name-filter path
  still answers "where is this discussed"; the deleted CLI surfaces are gone.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given slices 06-08 are merged and the founder's go is recorded
When  the demolition branch is built
Then  the retired CLI surfaces (name-page materialisation, the gather pass,
      the name-walking ask loop, the residue pass) no longer exist as
      commands
And   `axial brief run --arm map+vocab` is refused as an unknown arm, and
      the four --vocabulary-* knobs are gone from run and sweep (#825)
And   the kept surface still works: asking where a name is discussed returns
      its passages, spelling variants folded
And   `uv run pytest` is green and `uv run ruff check` is clean with the
      deleted modules' tests removed alongside them
And   the PR body lists every deleted module with the slice or measurement
      that made it safe
```

- **Boundary / endpoint:** CLI — the retired commands refuse; the kept name lookup answers
- **e2e test type:** API/integration test (pytest, CLI-level)
- **e2e test file (planned):** src/axial/test_cli.py (extended)

## Files (parallel-safety declaration)

Deletions declared as edits; the definitive list is drawn up at slice start
from what slices 06–08 actually left unreferenced, and recorded here before
the branch is cut.

```aeo-independence
slice: 09-demolition
edits: src/axial/argmap/vocabulary_join.py
edits: src/axial/argmap/test_vocabulary_join.py
edits: src/axial/argmap/ask.py
edits: src/axial/argmap/test_ask.py
edits: src/axial/answer/record.py
edits: src/axial/brief/sweep.py
edits: src/axial/brief/test_sweep.py
edits: specs/PHASE-B.md
edits: src/axial/gather.py
edits: src/axial/argmap/residue.py
edits: src/axial/argmap/test_residue.py
edits: src/axial/vocabulary.py
edits: src/axial/test_vocabulary.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
edits: specs/PRODUCT.md
depends-on: 08-retrieval-address-arm
```

## Inner loop — initial unit test list

- [ ] The kept name index answers a lookup with variants folded (regression
      pin before anything is deleted).
- [ ] Retired commands are absent from the CLI parser.
- [ ] No surviving module imports a deleted one (import sweep is green).
- [ ] The spec's retrieval sections describe the address walk and the
      name-as-filter rule; the name-page sections are gone.

## Operational steps inside the slice

1. Draw up the deletion list by reference sweep, record it in this plan.
2. Delete in dependency order, suite green at each step.
3. The eval apparatus goes last, and only the parts nothing remaining reads —
   `eval layers` and the arm recording stay (approach §12).
4. Spec update rides in the same branch (behaviour moved, spec moves with it).
5. While in `src/axial/vocabulary.py`, take **#835** with you — a one-word fix
   in the build report, where `built: N newly assigned` (values processed) sits
   one line above `M assigned to a category` and both are called "assigned".
   Found by the verifier on #826. This slice is the only planned opener of that
   file, so the fix rides here rather than earning its own branch.

## Out of scope for this slice (deferred)

- Deleting `vocabulary examine`'s drafting path or `vocabulary build` — both
  are load-bearing now (approach §12).
- Deleting the name index itself — it is the kept filter, permanently.
- Rewriting retrieval documentation beyond the spec sections that named the
  deleted machinery.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Deletion list recorded with per-item justification; spec updated in-branch.
- [ ] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
