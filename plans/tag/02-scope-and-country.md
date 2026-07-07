# Slice 02: Empirical scope + the `scope:country-case` country extra field

- **Feature:** tag
- **Slice slug:** scope-and-country
- **GitHub issue:** #28
- **Branch:** feat/tag/02-scope-and-country
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial tag <file>` additionally assigns `empirical_scope` — a single, exactly-one-value
axis — and, when that value is `scope:country-case`, attaches a `country` drawn from the
schema's controlled `country_list` (PRD Appendix C, G). A `country-case` record with no
country, or a country absent from `country_list`, is a hard error. This adds the
single-value axis that carries an extra field, so retrieval can separate
`scope:general` theory from `scope:country-case:Syria` evidence (Appendix C rationale).

## INVEST check

- **Independent:** extends the slice-01 tagger with one more axis + its extra-field rule;
  no other pass changes.
- **Valuable:** the scope axis is what makes "does Mann's infrastructural power apply to
  post-2011 Syria" retrievable as two separable buckets rather than one.
- **Small:** one more single-value axis plus a controlled-list lookup for `country`.
- **Testable:** run `axial tag` on a fixture; assert each record carries exactly one
  `empirical_scope`, and a `country-case` record carries an in-list `country`.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and chunks, AXIAL_LLM_PROVIDER=stub returning empirical_scope=scope:country-case with country=Syria
When  the user runs `axial tag <fixture>`
Then  each record carries exactly one `empirical_scope` value drawn from the schema
And   a `scope:country-case` record carries a `country` drawn from the schema's country_list
And   a country-case with a missing or out-of-list country exits non-zero with a clear error
```

- **Boundary / endpoint:** CLI command `axial tag <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_tag.py (extends the slice-01 contract) — test-author, red, locked

## Inner loop — initial unit test list

- [ ] `empirical_scope` validated as exactly one in-schema value (zero/multiple → error), reusing the slice-01 single-cardinality validator
- [ ] `scope:country-case` requires a `country`; a missing country raises a hard error
- [ ] `country` must be a member of the schema's `country_list`; an unknown country raises a hard error naming the offending value
- [ ] a non-`country-case` scope carries no `country` field
- [ ] the record still carries `role_in_argument` from slice 01 (no regression)

## Out of scope for this slice (deferred)

- **The primary+secondary axes** — `field`, `claim_type`, `theory_school` (slice 03).
- **Vault persistence** (slice 04).
- **Expanding the `country_list`** — the placeholder list ships as-is; growing it is a schema edit, not a code change (PRD §4).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
