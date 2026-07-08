# feat(gold): render the label sheet label_sheet.xlsx [slice 02]

**Spec:** specs/PRODUCT.md#7.5 (label sheet), Appendix I (columns), #8 (P0-9) · **Plan:** plans/gold/02-label-sheet.md
**Depends on:** #53 (gold slice 01, this sprint)
**Labels:** sub:ingestion-v0

## Deliverable

`axial gold sheet` reads the sampled chunk records under `data/gold/chunks/` and writes
`data/gold/label_sheet.xlsx`: one header row plus one row per sampled chunk, columns exactly
per Appendix I — `chunk_id | source | section | chunk_text | field | empirical_scope |
claim_type | theory_school | notes`. The four axis columns carry dropdown data-validation
whose options come from the codebook / schema. The pre-labeled columns (`field`,
`empirical_scope`) arrive filled with each chunk's existing tag; the blind columns
(`claim_type`, `theory_school`) arrive empty for the Academic. Adds `openpyxl`. This
completes P0-9 — the Academic's ready-to-label instrument, and (once returned) the eval
answer key with no transform between labeling and scoring (§7.5).

## Acceptance criterion

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

## Out of scope

- Eval / scoring — reading the returned sheet and computing agreement is P0-10.
- The `country` sub-field surfacing — a test-author detail, not a new column (Appendix I has none).
- κ metrics; the `notes` column ships empty.
