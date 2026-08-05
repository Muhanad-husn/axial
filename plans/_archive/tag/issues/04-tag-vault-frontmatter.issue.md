# feat(tag): persist axis tags into prose-note frontmatter [slice 04]

**Spec:** specs/PRODUCT.md#7-2 (three-level metadata), Appendix H · **Plan:** plans/tag/04-tag-vault-frontmatter.md
**Depends on:** tag slice 03 (this sprint), #18 (prose-pool vault write)
**Labels:** sub:ingestion-v0

## Deliverable

`axial vault write <file>` runs the tagger internally (which runs the chunker) and writes
the chunk-level axis frontmatter into each prose note — `claim_type`, `field`,
`empirical_scope` (+`country`), `theory_school` `[candidate]`, `role_in_argument` — plus
the `schema_version` stamp, completing the three-level frontmatter of §7.2 / Appendix H.
The phase-2 source-level (`source_meta`) and section-level metadata are preserved
unchanged, and re-running stays idempotent. This is the phase-3 payoff on disk: a vault a
human or a later retrieval pass can open and see tagged prose.

## Acceptance criterion

```gherkin
Given an extracted fixture source with a stored envelope and chunks, AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  each prose note's frontmatter carries schema_version and a chunk-level axis block (claim_type, field, empirical_scope, theory_school, role_in_argument) matching Appendix H
And   the phase-2 source-level and section-level metadata are unchanged
And   re-running is idempotent (no duplicate or conflicting frontmatter)
```

## Out of scope

- The artifact pool's contents (the `artifacts` feature).
- Backlinks — artifact_refs/cited_by (the `xref` feature).
- A single `axial ingest` orchestrator (each stage stays its own subcommand).
