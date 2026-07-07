# feat(minimal-ingestion): vault write — prose-pool notes with structural frontmatter [slice 06]

**Spec:** specs/PRODUCT.md §5 (stage 7 prose half), §7.2, §8 P0-8 · **Plan:** plans/minimal-ingestion/06-vault-write.md
**Depends on:** #17 (slice 05 argumentative-chunking)
**Labels:** sub:ingestion-v0

## Deliverable

`axial vault write <file>` writes one Obsidian prose-pool note per chunk to
`data/vault/prose/`, each carrying valid YAML frontmatter with source-level
metadata (from the envelope), the section-level verbatim label, and chunk-level
`chunk_id` + `chunk_text` + section provenance. Closes the minimal end-to-end
thread (P0-8): a source in one end, structured prose notes out the other. Axis-tag
frontmatter and the `schema_version` stamp are deferred to phase-3 tagging (§7.1).

## Acceptance criterion

```gherkin
Given an extracted fixture source with a stored envelope and its chunk records, stub LLM provider
When  the user runs `axial vault write <fixture>`
Then  it exits 0 and writes one prose note per chunk under data/vault/prose/
And   each note has valid YAML frontmatter carrying source-level metadata, the section label, chunk_id, and chunk_text
And   the prose pool is a separate surface from data/vault/artifacts/ (which stays empty this phase)
```

## Out of scope

All axis-tag frontmatter (claim_type/field/empirical_scope/theory_school/
role_in_argument) and the `schema_version` stamp (phase-3 tagging); the artifact
pool's contents and `cited_by`/`artifact_refs` backlinks (phase-3 cross-reference
pass, P0-7).
