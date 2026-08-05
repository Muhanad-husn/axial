# feat(xref): write bidirectional backlinks into both pools [slice 02]

**Spec:** specs/PRODUCT.md#5-7 (stage 7), #8 (P0-7, P0-8) · **Plan:** plans/xref/02-xref-backlinks.md
**Depends on:** xref slice 01 (this sprint), tag slice 04 (this sprint), artifacts slice 02 (this sprint), #18 (vault write)
**Labels:** sub:ingestion-v0

## Deliverable

`axial vault write <file>` runs the cross-reference detection after both prose and artifact
notes are written, then materialises each detected reference as bidirectional frontmatter:
`artifact_refs: [artifact_id, ...]` on the referencing prose note and `cited_by: [chunk_id,
...]` on the referenced artifact note. Every `artifact_refs` entry has a matching `cited_by`
and vice versa; re-running adds no duplicates. This completes P0-7 and the backlink half of
P0-8 — the vault becomes a navigable graph from a prose claim to the table it cites and
back, the terminal deliverable of Phase-A ingestion.

## Acceptance criterion

```gherkin
Given a fixture source whose chunk references an artifact, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  the referencing prose note's frontmatter carries artifact_refs including the artifact_id
And   the referenced artifact note's frontmatter carries cited_by including the chunk_id
And   a note with no references carries an empty or absent backlink field (never a dangling one)
And   re-running is idempotent — no duplicate backlink entries
```

## Out of scope

- New detection logic — reuses slice 01 unchanged.
- A single `axial ingest` orchestrator — `axial vault write` remains the terminal composition.
