# feat(artifacts): artifact classification — one artifact_role per artifact node [slice 01]

**Spec:** specs/PRODUCT.md#5-5 (stage 5), Appendix D · **Plan:** plans/artifacts/01-artifact-classify.md
**Depends on:** #14 (structural extraction)
**Labels:** sub:ingestion-v0

## Deliverable

`axial artifacts <file>` runs structural extraction, collects the non-text artifact nodes
(tree nodes typed `artifact`) with their enclosing-section provenance, and assigns each
exactly one `artifact_role` from the schema's closed Appendix D taxonomy via one LLM call
(`pass_name="artifacts"`). A returned role absent from the schema is a hard error. Each
tagged artifact record — a stable `artifact_id` (`<source_id>_art_<order>`),
`artifact_role`, source/section provenance — is emitted to stdout. This is the routing
decision that separates artifacts from prose (P0-5, goal 4).

## Acceptance criterion

```gherkin
Given an extracted fixture source containing at least one artifact node (a table or figure), and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial artifacts <fixture>`
Then  it exits 0 and emits one record per artifact node as JSON
And   each record carries a stable artifact_id, an artifact_role drawn from the schema's artifact_role axis, and source/section provenance
And   a stub returning a role absent from the schema exits non-zero with a clear error
```

## Out of scope

- Routing to the artifact pool on disk (slice 02) — records go to stdout only.
- The field tag on artifacts and the discard non-retrievable flag (slice 02).
- Cross-reference backlinks (the `xref` feature).
- Deep artifact/content extraction or OCR (§3 non-goals).
