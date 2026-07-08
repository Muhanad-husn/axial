# Slice 01: Stratified sampling of tagged chunks

- **Feature:** gold
- **Slice slug:** gold-sample
- **GitHub issue:** #53
- **Branch:** feat/gold/01-gold-sample
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes (introduces the `axial gold` subcommand + the `gold.py` module)

## Goal — the minimum testable behaviour

`axial gold sample` reads the tagged prose notes under `data/vault/prose/`, selects a set
of chunks **stratified** so that every represented field and every represented
empirical-scope value gets at least one chunk (and, when a source-type manifest is present,
both book and paper are represented), and writes the selected chunk records to
`data/gold/chunks/` — one record per chunk carrying `chunk_id`, `source`, `section`,
`chunk_text`, and the chunk's `field` / `empirical_scope` / `claim_type` / `theory_school`
tags. Selection is deterministic (seedable, stably ordered). Offline: no LLM call. This is
the sampling engine the label sheet (slice 02) renders.

## INVEST check

- **Independent:** reads only what the `tag`/`vault` features already wrote; introduces a new
  `axial gold` subcommand and `src/axial/gold.py`, touching no existing pass.
- **Valuable:** turns the tagged vault into a stratified gold *candidate set* — the raw
  material of the Academic deliverable and the eval answer key.
- **Small:** parse frontmatter → group by stratum → pick ≥1 per stratum, fill to band → write
  records. No new network, no new heavy dependency.
- **Testable:** given a vault of tagged notes spanning ≥2 fields and ≥2 scopes, assert the
  written record set covers each stratum and its size sits in the clamped band.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a populated prose vault whose tagged notes span at least two field values and at least two empirical_scope values
When  the user runs `axial gold sample`
Then  a set of chunk records is written under data/gold/chunks/
And   the selection includes at least one chunk for each represented field value and each represented empirical_scope value
And   the number of selected chunks sits within the configured band (default 30–50), clamped to the number of available chunks
And   each written record carries chunk_id, source, section, chunk_text and the chunk's field, empirical_scope, claim_type and theory_school tags
And   re-running produces the same selection (deterministic) and does not accumulate stale records
```

- **Boundary / endpoint:** CLI command `axial gold sample`
- **Outer test type:** pytest integration test (subprocess; offline — no provider)
- **Outer test file (planned):** tests/test_gold_sample.py — test-author, red, locked

## Inner loop — initial unit test list

- [ ] read and parse a tagged prose note's frontmatter into a chunk record (all needed fields)
- [ ] enumerate the vault dir, skipping non-note files, into a list of records
- [ ] compute each chunk's stratum key (field primary × empirical_scope value; × declared source_type when a manifest is given)
- [ ] select at least one chunk per non-empty stratum, then fill toward the target band without exceeding available chunks
- [ ] deterministic, seedable, stably ordered selection (a re-run reproduces the same set)
- [ ] write records to data/gold/chunks/, clearing any prior sample first (no stale accumulation)
- [ ] honor a data/gold/sources.yaml source-type manifest when present; when absent, stratify on field × scope only and log that source-type balancing was skipped

## Out of scope for this slice (deferred)

- **The xlsx label sheet** — slice 02 renders these records into `label_sheet.xlsx`.
- **Source-type inference** — operator-declared via manifest only; no envelope/LLM change.
- **Any scoring or eval** — P0-10, a separate feature.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
