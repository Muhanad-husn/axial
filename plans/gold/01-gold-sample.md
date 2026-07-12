# Slice 01: Stratified sampling of tagged chunks

- **Feature:** gold
- **Slice slug:** gold-sample
- **GitHub issue:** #53
- **Branch:** feat/gold/01-gold-sample
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes (introduces the `axial gold` subcommand + the `gold.py` module)

## Goal — the minimum testable behaviour

`axial gold sample` reads the tagged prose notes under `data/vault/prose/`, **excludes
non-substantive back-matter** (endnotes, references/bibliography, index, appendix,
front-matter) from the sampling frame, and selects a set of chunks **stratified on
field × empirical_scope × role_in_argument** so that every represented value of each of
those three axes gets at least one chunk. source-type (book/paper), claim_type, and
theory_school are **not** balancing strata — they ride along descriptively on whatever is
drawn; each source-type present in `data/gold/sources.yaml` contributes at least one chunk.
It writes the selected chunk records to `data/gold/chunks/` — one record per chunk carrying
`chunk_id`, `source`, `section`, `chunk_text`, and the chunk's `field` / `empirical_scope` /
`role_in_argument` / `claim_type` / `theory_school` tags. Selection is deterministic
(seedable, stably ordered). Offline: no LLM call. This is the sampling engine the label
sheet (slice 02) renders.

## INVEST check

- **Independent:** reads only what the `tag`/`vault` features already wrote; introduces a new
  `axial gold` subcommand and `src/axial/gold.py`, touching no existing pass. The back-matter
  classifier can reuse/mirror #113's section-classification logic.
- **Valuable:** turns the tagged vault into a stratified gold *candidate set* — the raw
  material of the Academic deliverable and the eval answer key.
- **Small:** parse frontmatter → drop back-matter → group by stratum → pick ≥1 per stratum,
  fill to band → write records. No new network, no new heavy dependency.
- **Testable:** given a vault of tagged notes spanning ≥2 fields, ≥2 scopes and ≥2 roles,
  assert the written record set covers each stratum, excludes back-matter, and its size sits
  in the clamped band.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a populated prose vault whose tagged notes span at least two field values, at least two empirical_scope values and at least two role_in_argument values
And   the vault contains at least one non-substantive back-matter note (e.g. an endnotes or bibliography section)
When  the user runs `axial gold sample`
Then  a set of chunk records is written under data/gold/chunks/
And   the selection includes at least one chunk for each represented field value, each represented empirical_scope value and each represented role_in_argument value
And   no selected chunk comes from a non-substantive back-matter section
And   when data/gold/sources.yaml is present, each source-type it declares that is present in the corpus contributes at least one chunk
And   the number of selected chunks sits within the configured band (default 100–120), clamped to the number of available chunks
And   each written record carries chunk_id, source, section, chunk_text and the chunk's field, empirical_scope, role_in_argument, claim_type and theory_school tags
And   re-running produces the same selection (deterministic) and does not accumulate stale records
```

- **Boundary / endpoint:** CLI command `axial gold sample`
- **Outer test type:** pytest integration test (subprocess; offline — no provider)
- **Outer test file (planned):** tests/test_gold_sample.py — test-author, red, locked

## Inner loop — initial unit test list

- [ ] read and parse a tagged prose note's frontmatter into a chunk record (all needed fields, incl. `role_in_argument`)
- [ ] enumerate the vault dir, skipping non-note files, into a list of records
- [ ] classify a note's `section` as substantive vs. back-matter (endnotes / references-bibliography / index / appendix / front-matter) and drop back-matter from the frame
- [ ] compute each chunk's stratum key: field primary × empirical_scope value × role_in_argument
- [ ] select at least one chunk per non-empty stratum, then fill toward the target band without exceeding available chunks
- [ ] guarantee each source-type present in data/gold/sources.yaml contributes ≥1 chunk (descriptive coverage, not a balancing stratum)
- [ ] deterministic, seedable, stably ordered selection (a re-run reproduces the same set)
- [ ] write records to data/gold/chunks/, clearing any prior sample first (no stale accumulation)
- [ ] when data/gold/sources.yaml is absent, log that source-type coverage was skipped and stratify on the three axes only

## Out of scope for this slice (deferred)

- **The xlsx label sheet** — slice 02 renders these records into `label_sheet.xlsx`.
- **Balancing claim_type / theory_school** — descriptive only; their long tails (many values <1%) are unsamplable as strata at N=100–120.
- **Source-type inference** — operator-declared via manifest only; no envelope/LLM change.
- **Deleting back-matter from the vault** — the notes stay; the sampler only excludes them from the frame.
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
- 2026-07-13 re-aligned to the ratified P0-9 stratification (PR #124): strata field × empirical_scope × role_in_argument; source-type/claim_type/theory_school descriptive; back-matter excluded from the sampling frame.
