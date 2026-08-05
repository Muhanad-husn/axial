# Slice 02: Render the label sheet (label_sheet.xlsx)

- **Feature:** gold
- **Slice slug:** label-sheet
- **GitHub issue:** #54
- **Branch:** feat/gold/02-label-sheet
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial gold sheet` reads the sampled chunk records under `data/gold/chunks/` and writes
`data/gold/label_sheet.xlsx`: one header row plus one row per sampled chunk, columns exactly
per Appendix I — `chunk_id | source | section | chunk_text | field | empirical_scope |
claim_type | theory_school | notes`. The four axis columns (`field`, `empirical_scope`,
`claim_type`, `theory_school`) carry dropdown data-validation whose options come from the
codebook / schema. The **pre-labeled** columns (`field`, `empirical_scope`) arrive filled
with each chunk's existing tag; the **blind** columns (`claim_type`, `theory_school`) arrive
empty for the Academic. Adds `openpyxl`. This completes P0-9 — the Academic's ready-to-label
instrument.

## INVEST check

- **Independent:** consumes slice 01's chunk records and the existing codebook loader; adds
  one dependency (`openpyxl`) and one subcommand; touches no pass.
- **Valuable:** produces the single artifact the Academic labels — the §11 step-4 deliverable
  and, once returned, the eval answer key (§7.5: no transform between labeling and scoring).
- **Small:** build a workbook, write header + rows, copy two tag columns in, attach four
  dropdowns from vocab the loader already exposes.
- **Testable:** open the written xlsx and assert columns, row count, pre-labeled vs blind
  cell contents, and dropdown validations sourced from the codebook.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a sampled gold set under data/gold/chunks/ and the Syria codebook
When  the user runs `axial gold sheet`
Then  data/gold/label_sheet.xlsx exists with one header row and one row per sampled chunk
And   the columns are chunk_id, source, section, chunk_text, field, empirical_scope, claim_type, theory_school, notes in that order
And   the field and empirical_scope cells are pre-filled from each chunk's tags
And   the claim_type and theory_school cells are empty
And   the field, empirical_scope, claim_type and theory_school columns carry dropdown validation whose options are the codebook's vocabulary for that axis
And   re-running overwrites the sheet in place (no duplicate rows, no stale sheet)
```

- **Boundary / endpoint:** CLI command `axial gold sheet`
- **Outer test type:** pytest integration test (subprocess; offline — reads xlsx with openpyxl)
- **Outer test file (planned):** tests/test_gold_sheet.py — test-author, red, locked

## Inner loop — initial unit test list

- [ ] add `openpyxl` to dependencies; create a workbook whose first row is the Appendix-I header in order
- [ ] one row per sampled chunk record; write chunk_id / source / section / chunk_text verbatim
- [ ] pre-fill the field and empirical_scope cells from the record's tags
- [ ] leave the claim_type and theory_school cells empty (blind)
- [ ] attach a DataValidation dropdown to each axis column, options loaded from the codebook/schema vocabulary for that axis (claim_type, theory_school, field; empirical_scope from the scope value set)
- [ ] write to data/gold/label_sheet.xlsx, overwriting any prior sheet (idempotent)

## Out of scope for this slice (deferred)

- **Eval / scoring** — reading the *returned* sheet and computing agreement is P0-10.
- **The `country` sub-field of scope:country-case** — the `empirical_scope` cell carries the
  scope value; how/whether the country is surfaced in the sheet is a test-author detail, not
  a new column (Appendix I has none).
- **κ metrics, notes-column pre-fill** — the `notes` column ships empty.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
