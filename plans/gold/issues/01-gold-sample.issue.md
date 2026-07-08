# feat(gold): stratified sampling of tagged chunks [slice 01]

**Spec:** specs/PRODUCT.md#9 (gold corpus & labeling), #8 (P0-9) · **Plan:** plans/gold/01-gold-sample.md
**Depends on:** none (reads the shipped `tag` #27–#31 and `vault` #18 output)
**Labels:** sub:ingestion-v0

## Deliverable

`axial gold sample` reads the tagged prose notes under `data/vault/prose/`, selects a set of
chunks **stratified** so every represented field value and every represented empirical-scope
value gets at least one chunk (and, when a `data/gold/sources.yaml` source-type manifest is
present, both book and paper are represented), and writes the selected chunk records to
`data/gold/chunks/` — one record per chunk carrying `chunk_id`, `source`, `section`,
`chunk_text` and the chunk's `field` / `empirical_scope` / `claim_type` / `theory_school`
tags. Selection is deterministic (seedable, stably ordered); the sample size sits in a
configurable band (default 30–50) clamped to available chunks. Offline — no LLM call. This
introduces the `axial gold` subcommand and `src/axial/gold.py`, and is the sampling engine
the label sheet (slice 02) renders.

## Acceptance criterion

```gherkin
Given a populated prose vault whose tagged notes span at least two field values and at least two empirical_scope values
When  the user runs `axial gold sample`
Then  a set of chunk records is written under data/gold/chunks/
And   the selection includes at least one chunk for each represented field value and each represented empirical_scope value
And   the number of selected chunks sits within the configured band (default 30–50), clamped to the number of available chunks
And   each written record carries chunk_id, source, section, chunk_text and the chunk's field, empirical_scope, claim_type and theory_school tags
And   re-running produces the same selection (deterministic) and does not accumulate stale records
```

## Out of scope

- The xlsx label sheet — slice 02 renders these records into `label_sheet.xlsx`.
- Source-type inference — operator-declared via manifest only; no envelope/LLM change.
- Any scoring or eval — P0-10, a separate feature.
