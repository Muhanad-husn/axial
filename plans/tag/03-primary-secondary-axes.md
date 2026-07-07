# Slice 03: The primary+secondary axes — field, claim_type, theory_school

- **Feature:** tag
- **Slice slug:** primary-secondary-axes
- **GitHub issue:** #29
- **Branch:** feat/tag/03-primary-secondary-axes
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial tag <file>` additionally assigns the three multi-value axes with one shared,
data-driven cardinality validator: `field` (one primary + zero-or-more secondary),
`claim_type` (one primary + optional secondary, with its declared `subtags`), and
`theory_school` (one primary + optional secondary, `status: candidate`). Every primary,
secondary, and subtag is validated against the loaded schema; any absent tag is a hard
error. After this slice every prose axis the schema declares is tagged.

## INVEST check

- **Independent:** extends the tagger with the primary+secondary cardinality family;
  reuses the slice-01 hard-error validator; no other pass changes.
- **Valuable:** completes the axis coverage — a chunk now carries its full multi-axis
  tag set (Appendix H), the core of the pipeline's value.
- **Small:** one cardinality validator (two variants: `primary_plus_secondary`,
  `primary_plus_optional_secondary`) applied data-driven across three axes, plus subtag
  validation. No per-axis branching (PRD §4).
- **Testable:** run `axial tag` on a fixture; assert each record carries well-formed
  `field`, `claim_type` (+subtags), and `theory_school` (+candidate status), all
  in-schema.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and chunks, AXIAL_LLM_PROVIDER=stub returning a full multi-axis tag response
When  the user runs `axial tag <fixture>`
Then  each record carries `field` {primary, secondary[]}, `claim_type` {primary, secondary?, subtags[]}, and `theory_school` {primary, secondary?, status: candidate}
And   every primary, secondary, and subtag exists in the schema
And   any returned tag absent from the schema exits non-zero with a hard error naming the axis and tag
```

- **Boundary / endpoint:** CLI command `axial tag <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_tag.py (extends the slice-01/02 contract) — test-author, red, locked

## Inner loop — initial unit test list

- [ ] `primary_plus_secondary` validator: exactly one primary (required), zero-or-more secondary, all in-schema
- [ ] `primary_plus_optional_secondary` validator: one primary (required), at most one secondary
- [ ] `claim_type` subtags are validated against that tag's own declared `subtags`; an undeclared subtag is a hard error
- [ ] `theory_school` records `status: candidate` (from the schema's axis status)
- [ ] an unknown tag on any of the three axes raises the shared `TagNotInSchemaError`
- [ ] a chunk's assembled tag set carries all five prose axes (field, claim_type, empirical_scope, theory_school, role_in_argument)

## Out of scope for this slice (deferred)

- **Vault persistence** — slice 04 writes the assembled axis block into prose notes.
- **Artifact `field` tagging** — the artifacts feature reuses this validator for artifacts.
- **Resolving `[CONTESTED]`/`[CANDIDATE]` tags** — the tagger applies whatever the schema declares; keep/cut decisions are the eval's job (phase 6), not code.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
