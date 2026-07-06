# feat(schema-loader): codebook cross-validation + `axial schema validate` [slice 03]

**Spec:** specs/PRODUCT.md §7.1, §8 P0-6, Appendices B–F · **Plan:** plans/schema-loader/03-codebook-validate.md
**Depends on:** #<slice-02 issue>
**Labels:** sub:ingestion-v0

## Deliverable

`axial schema validate <domain-dir>` cross-checks schema ↔ codebook: every
schema tag has a codebook entry (definition + positive + negative example),
every codebook tag exists in the schema; exit 0 when consistent, nonzero
naming every offender otherwise. Ships the committed v0.1 placeholder Syria
`codebook.yaml` derived from PRD Appendices B–F. This is the loader-side half
of P0-6's "a tag not in the schema is a hard error", and it is what makes the
Academic's validated labels a pure data swap later.

## Acceptance criterion

```gherkin
Given the committed schema.yaml and codebook.yaml for config/domains/syria
When  the user runs `uv run axial schema validate config/domains/syria`
Then  it exits 0 and reports every axis consistent
And   against a fixture whose codebook omits one schema tag it exits nonzero naming that tag and axis
And   against a fixture whose codebook carries a tag absent from the schema it exits nonzero naming it
```

## Out of scope

The tagger itself and its runtime enforcement; status-flag keep/cut decisions
(gold-set eval territory).
