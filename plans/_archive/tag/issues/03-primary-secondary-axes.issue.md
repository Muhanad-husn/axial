# feat(tag): primary+secondary axes — field, claim_type, theory_school [slice 03]

**Spec:** specs/PRODUCT.md#5-6 (stage 6), Appendices A/B/E · **Plan:** plans/tag/03-primary-secondary-axes.md
**Depends on:** tag slice 02 (this sprint)
**Labels:** sub:ingestion-v0

## Deliverable

`axial tag <file>` additionally assigns the three multi-value axes through one shared,
data-driven cardinality validator: `field` (one primary + zero-or-more secondary),
`claim_type` (one primary + optional secondary, with its declared `subtags`), and
`theory_school` (one primary + optional secondary, `status: candidate`). Every primary,
secondary, and subtag is validated against the loaded schema; any absent tag is a hard
error. After this slice every prose axis the schema declares is tagged — a chunk carries
its full multi-axis set (Appendix H). No per-axis branching: adding an axis of the same
cardinality is data, not code (PRD §4).

## Acceptance criterion

```gherkin
Given an extracted fixture source with a stored envelope and chunks, AXIAL_LLM_PROVIDER=stub returning a full multi-axis tag response
When  the user runs `axial tag <fixture>`
Then  each record carries field {primary, secondary[]}, claim_type {primary, secondary?, subtags[]}, and theory_school {primary, secondary?, status: candidate}
And   every primary, secondary, and subtag exists in the schema
And   any returned tag absent from the schema exits non-zero with a hard error naming the axis and tag
```

## Out of scope

- Vault persistence (slice 04).
- Artifact field tagging (the `artifacts` feature reuses this validator).
- Resolving [CONTESTED]/[CANDIDATE] tags — the tagger applies what the schema declares; keep/cut is the eval's job (phase 6).
