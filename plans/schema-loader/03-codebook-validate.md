# Slice 03: Codebook cross-validation

- **Feature:** schema-loader
- **Slice slug:** codebook-validate
- **GitHub issue:** #8
- **Branch:** feat/schema-loader/03-codebook-validate
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`uv run axial schema validate config/domains/syria` cross-checks schema ↔
codebook — every schema tag has a codebook entry (definition + positive +
negative example) and every codebook tag exists in the schema — exiting 0 when
consistent and nonzero listing every offender when not. Delivers the placeholder
`codebook.yaml` (PRD Appendices B–F) and the loader-side half of P0-6's
"tag not in schema is a hard error".

## INVEST check

- **Independent:** builds on slice 02's loader.
- **Valuable:** the codebook is both the tagger's reference and the Academic's labeling instrument (§7.1); consistency is what makes the placeholder→validated swap a pure data change.
- **Small:** one validation pass + one subcommand + the committed codebook.
- **Testable:** CLI against the real committed pair, plus broken fixtures.

## Acceptance criterion (outer loop)

```gherkin
Given the committed schema.yaml and codebook.yaml for config/domains/syria
When  the user runs `uv run axial schema validate config/domains/syria`
Then  it exits 0 and reports every axis consistent
And   run against a fixture domain dir whose codebook omits one schema tag, it exits nonzero and names that tag and its axis
And   run against a fixture whose codebook carries a tag absent from the schema, it exits nonzero and names it
```

- **Boundary / endpoint:** CLI command `axial schema validate <domain-dir>`
- **Outer test type:** pytest integration test (subprocess; broken-pair fixtures under tests/fixtures/)
- **Outer test file (planned):** tests/test_schema_validate.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] codebook parser exposes definition / positive_example / negative_example per tag
- [ ] validator flags a schema tag missing from the codebook (axis + tag named)
- [ ] validator flags a codebook tag missing from the schema
- [ ] validator flags a codebook entry missing an example field
- [ ] consistent pair → empty finding list

## Out of scope for this slice (deferred)

- Tagging itself (later subproject); runtime enforcement inside the tagger; status-flag lifecycle (keep/cut decisions belong to the eval).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite green; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
