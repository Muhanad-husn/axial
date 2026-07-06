# Slice 02: Schema load & show

- **Feature:** schema-loader
- **Slice slug:** schema-load
- **GitHub issue:** #TBD
- **Branch:** feat/schema-loader/02-schema-load
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`uv run axial schema show config/domains/syria` loads the committed placeholder
`schema.yaml` (PRD Appendix G) and prints each axis with its cardinality and
value count; a missing or malformed schema fails with a clear message. Delivers
the loader core of PRD §7.1 and the v0.1 Syria `schema.yaml`.

## INVEST check

- **Independent:** builds only on slice 01's CLI.
- **Valuable:** the swappable-domain loader is the architecture's load-bearing seam (§4).
- **Small:** loader + one subcommand + the committed schema file.
- **Testable:** CLI invocation against a real committed config file.

## Acceptance criterion (outer loop)

```gherkin
Given the committed placeholder schema at config/domains/syria/schema.yaml (version 0.1)
When  the user runs `uv run axial schema show config/domains/syria`
Then  it exits 0 and lists the six axes (field, claim_type, empirical_scope, theory_school, artifact_role, role_in_argument), each with its cardinality and value count, and the schema version
And   running it against a nonexistent directory exits nonzero with a message naming the missing file
```

- **Boundary / endpoint:** CLI command `axial schema show <domain-dir>`
- **Outer test type:** pytest integration test (subprocess)
- **Outer test file (planned):** tests/test_schema_show.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] loader parses axes with `applies_to`, `cardinality`, `values` from YAML
- [ ] loader exposes the `version` field; missing version is a hard error
- [ ] unknown cardinality value is a hard error naming the axis
- [ ] loader takes a domain *directory* (no code path branches on country — §4)
- [ ] missing schema.yaml raises a clear, typed error

## Out of scope for this slice (deferred)

- codebook.yaml (slice 03), tag status flags semantics, extra_fields/country list validation beyond parse.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite green; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
