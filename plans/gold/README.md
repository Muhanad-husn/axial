# Feature: Gold-set generation

PRD build phase 4 (§11), the Academic deliverable: sample ~30–50 tagged prose chunks
from 5–10 sources, **stratified** across field × source-type (book/paper) × empirical-scope
(§9), and emit `data/gold/label_sheet.xlsx` — one row per chunk, one column per axis, with
dropdown validation sourced from the codebook (§7.5, Appendix I). Pre-labeled columns
(`field`, `empirical_scope`) arrive filled with the tagger's guess; blind columns
(`claim_type`, `theory_school`) arrive empty. Fully offline: it reads notes the `tag`/`vault`
passes already wrote — no LLM call, no Academic dependency, no live network. Covers §5's
gold-loop wrap around stages 4–6 and requirement P0-9. Scoring the returned sheet is the
`eval` feature (P0-10), a separate subproject.

- **Slug:** gold
- **Created:** 2026-07-08
- **Status:** planning
- **New system?** no
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | Issue | PR |
|---|-------|-----------------|--------|-------|----|
| 01 | [gold-sample](01-gold-sample.md) | `axial gold sample` selects a stratified set of tagged chunks from the prose vault and writes chunk records to `data/gold/chunks/` | ☐ todo | [#53](https://github.com/Muhanad-husn/axial/issues/53) | — |
| 02 | [label-sheet](02-label-sheet.md) | `axial gold sheet` renders the sampled chunks into `data/gold/label_sheet.xlsx` with Appendix-I columns, codebook dropdowns, pre-labeled vs blind cells | ☐ todo | [#54](https://github.com/Muhanad-husn/axial/issues/54) | — |

## Out of scope (whole feature)

- **Eval / scoring** — reading returned labels and computing per-axis agreement is the
  `eval` feature (P0-10, §10), a distinct subproject. This feature produces the *unlabeled*
  instrument, not the score.
- **The Academic's labels** — the sheet ships empty in its blind columns; filling it is the
  §11 step-5 pause, not a code path here.
- **κ / Krippendorff metrics, ingestion log, batch/resume** — P1 items, not P0-9.
- **Live API calls** — the feature is offline by construction (reads tagged notes). No stub
  provider seam is needed for its own logic; tests only need a *populated prose vault* to
  read from (arranged as the other features arrange input — see notes).

## Notes / open questions

- **Source-type (book/paper) is operator-declared, not inferred.** §9 stratifies across
  source-type, but the pipeline records it nowhere (no field in the envelope, intake, or
  frontmatter — confirmed by triage), and Appendix I has no `source_type` column, so it is a
  **sampling guide, not an emitted field**. Rather than change the frozen envelope pass to
  infer it (scope creep / spec risk), the operator declares each source's type in a small
  manifest the sampler reads (e.g. `data/gold/sources.yaml: {source_id: book|paper}`). When
  no manifest is present the sampler stratifies on field × scope only and logs that
  source-type balancing was skipped — nothing silently vanishes. **Flag for founder review.**
- **No LLM in this feature.** Pre-labels for `field` and `empirical_scope` are copied from
  each chunk's existing frontmatter tags (written by the `tag` feature); the blind columns
  are left empty for the Academic. Sampling reads `data/vault/prose/*.md`. The whole feature
  runs offline.
- **Arranging the input vault in tests.** The outer tests need a populated prose vault to
  sample from. Either run the existing tag→vault thread on a fixture source under
  `AXIAL_LLM_PROVIDER=stub` (as the phase-3 tests do), or seed a handful of tagged note `.md`
  files directly into the vault dir. The test-author picks the lighter arrangement,
  consistent with #45 (arrange from stored fixtures, not live docling).
- **Sample-size band scales to the fixture.** P0-9 targets 30–50 chunks from 5–10 sources in
  production; a test fixture has far fewer. The band is configurable with a sensible default
  and clamps to available chunks, so the acceptance test asserts stratum coverage + the
  clamped band rather than a literal 30–50 on a tiny fixture.
- **Determinism.** Selection is seedable and stably ordered so a re-run reproduces the same
  sample and re-emitting the sheet is idempotent (overwrites, never appends).
- **Dependencies are shipped.** Gold-set generation reads the output of the `tag` (#27–#31)
  and `vault` (#18) features, all merged. No in-sprint dependency for slice 01; slice 02
  depends on slice 01.
