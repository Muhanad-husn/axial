# Slice 01: The claim column has a committed, assigned category scheme

- **Feature:** positions-not-names
- **Slice slug:** claim-vocabulary-committed
- **Issue:** [#826](https://github.com/Muhanad-husn/axial/issues/826)
- **Branch:** feat/positions-not-names/01-claim-vocabulary-committed
- **Project directory:** .
- **Status:** ☑ PR open, awaiting founder approval
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`config/vocabulary.yaml` carries a founder-approved category scheme for the
`claim` column, and `axial vocabulary build --columns claim` files the corpus
against it into `data/vocabulary/claim/`. This is the axis the whole re-formed
map groups on; nothing downstream can start without it.

## INVEST check

- **Independent:** uses only existing, column-generic commands
  (`vocabulary examine`, `vocabulary build`) and the existing config shape.
- **Valuable:** the grouping axis exists corpus-wide; slices 02–04 all read it.
- **Small:** the code delta is one config block plus a loader test; the rest
  is two runs and a founder edit.
- **Testable:** the committed scheme loads and validates; the build artifact
  exists with the pinned version, observable via the CLI.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given config/vocabulary.yaml carries a committed `claim` scheme with a version
      and every category bearing an id, name and gloss
When  `uv run axial vocabulary build --columns claim` runs against data/answers/
Then  data/vocabulary/claim/manifest.json exists, records that scheme version,
      and reports assigned, refused and unanswered counts per category
And   a second run under the same scheme version resumes rather than re-asking
```

- **Boundary / endpoint:** CLI — `uv run axial vocabulary build --columns claim`
- **e2e test type:** API/integration test (pytest, CLI-level, injected fake client)
- **e2e test file (planned):** src/axial/test_vocabulary_build.py (extended)

## Files (parallel-safety declaration)

```aeo-independence
slice: 01-claim-vocabulary-committed
edits: config/vocabulary.yaml
edits: src/axial/test_vocabulary.py
edits: src/axial/test_vocabulary_build.py
creates: data/logs/2026-08-28-claim-vocabulary/summary.md
```

## Inner loop — initial unit test list

- [ ] The committed `claim` scheme parses: unique ids, non-empty glosses, a
      version string distinct from every other column's.
- [ ] `vocabulary build` accepts `claim` as a column and refuses a manifest
      built under a different scheme version (existing behaviour, extended to
      the new column by test).
- [ ] The scheme's category count and ids match what the founder committed —
      a pin against silent drift.

## Operational steps inside the slice (not code, in order)

1. `uv run axial vocabulary examine --columns claim` — the drafting run
   (paid, small). Its proposed scheme is a draft, not an output.
2. **Founder edits and approves the category list.** Hard gate; the slice
   waits here.
3. Commit the scheme to `config/vocabulary.yaml` with a version.
4. `uv run axial vocabulary build --columns claim` in the main checkout;
   write `data/logs/2026-08-28-claim-vocabulary/` (run.jsonl, console.log,
   summary.md with coverage, refusals, per-category member and source counts).

## Out of scope for this slice (deferred)

- Any change to `vocabulary examine`'s internals (its measurement apparatus
  is deleted in slice 09, not here).
- Categorising any other column.
- Reading the assignments anywhere (slice 02 onward).

## Definition of done

- [x] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [x] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [x] Refactor pass complete with the bar green.
- [x] Slice's tests run in CI (`tdd-ci`).
- [x] The corpus run is done, its log written, coverage and refusal numbers in the summary.
- [x] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
- 2026-08-28 built. The drafting run was already on disk from 2026-08-27, so no
  new examine pass was paid for. Founder approved the drafted scheme with one
  edit: the 1-member "Acknowledgment or credit statement" category dropped and
  folded into the bibliographic gloss. Nine categories committed as
  `2026-08-28-claim-v1`. Corpus build: 6,697 answered, 6,671 assigned, 26
  refused, 0 unanswered, 68 calls, $0.0839; second run 0 calls, 2.1s,
  byte-identical artifact. Log at `data/logs/2026-08-28-claim-vocabulary/`.
  PR [#834](https://github.com/Muhanad-husn/axial/pull/834).
