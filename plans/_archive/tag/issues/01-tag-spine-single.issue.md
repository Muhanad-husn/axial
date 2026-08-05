# feat(tag): schema-driven tagging spine — role_in_argument, hard-error, versioned [slice 01]

**Spec:** specs/PRODUCT.md#5-6 (stage 6) · **Plan:** plans/tag/01-tag-spine-single.md
**Depends on:** #17 (argumentative chunking)
**Labels:** sub:ingestion-v0

## Deliverable

`axial tag <file>` runs the chunking pass internally and tags each prose chunk on the
`role_in_argument` axis — a single-value, closed-set axis whose vocabulary is loaded from
the domain schema at runtime, never hardcoded. Any value the model returns that is absent
from the schema raises a hard error (P0-6). Each tagged record carries the chunk's
provenance (`chunk_id`, `section`, `chunk_text`) plus the `schema_version` it was tagged
under, and is emitted to stdout. This establishes the tagging spine — schema load →
codebook-driven prompt → LLM tag call (`pass_name="tag"`) → validate-against-schema →
versioned record — that slices 02–03 extend with the remaining axes.

## Acceptance criterion

```gherkin
Given an extracted fixture source with a stored envelope and its chunk records, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial tag <fixture>`
Then  it exits 0 and emits one tagged record per chunk as JSON
And   each record carries a role_in_argument value drawn from the schema's role_in_argument axis
And   each record carries the schema_version it was tagged under, plus its chunk_id and section provenance
```

## Out of scope

- Other axes: empirical_scope/country (slice 02); field/claim_type/theory_school (slice 03).
- Vault persistence of tags (slice 04) — records go to stdout only.
- Artifact and cross-reference tagging (the `artifacts` and `xref` features).
- Model-per-pass selection (issue #23).
