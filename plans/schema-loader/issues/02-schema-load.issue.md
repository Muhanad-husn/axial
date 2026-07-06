# feat(schema-loader): domain schema loader + `axial schema show` [slice 02]

**Spec:** specs/PRODUCT.md §4, §7.1, Appendix G · **Plan:** plans/schema-loader/02-schema-load.md
**Depends on:** #6
**Labels:** sub:ingestion-v0

## Deliverable

The schema loader of PRD §7.1: reads `config/domains/<name>/schema.yaml`,
exposes axes/cardinalities/values/version, hard-errors on malformed input, and
takes the domain as a directory path (no country logic in code — §4). Ships the
committed v0.1 placeholder Syria `schema.yaml` (Appendix G) and the
`axial schema show <domain-dir>` subcommand that lists the six axes.

## Acceptance criterion

```gherkin
Given the committed placeholder schema at config/domains/syria/schema.yaml (version 0.1)
When  the user runs `uv run axial schema show config/domains/syria`
Then  it exits 0 and lists the six axes with cardinality, value count, and schema version
And   against a nonexistent directory it exits nonzero naming the missing file
```

## Out of scope

codebook.yaml (slice 03); status-flag semantics; country-list validation beyond
parse.
