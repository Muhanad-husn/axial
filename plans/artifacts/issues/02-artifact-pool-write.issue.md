# feat(artifacts): route artifacts to the pool with field + provenance + discard flag [slice 02]

**Spec:** specs/PRODUCT.md#5-5 (stage 5), #8 (P0-5, P0-8) · **Plan:** plans/artifacts/02-artifact-pool-write.md
**Depends on:** artifacts slice 01 (this sprint), tag slice 03 (this sprint, `field` validator), #18 (vault write)
**Labels:** sub:ingestion-v0

## Deliverable

`axial vault write <file>` additionally writes one artifact note per classified artifact
to `data/vault/artifacts/` — a surface separate from `data/vault/prose/` — with
frontmatter carrying `artifact_role`, `field` (one primary + zero-or-more secondary,
reusing the `tag` cardinality validator), and source/section provenance. A `discard`-roled
artifact is retained in the pool but flagged `retrievable: false`, so nothing silently
vanishes. This completes the artifact routing of P0-5 and the artifact-pool half of P0-8 —
the separation of prose and artifacts (goal 4) made durable on disk.

## Acceptance criterion

```gherkin
Given an extracted fixture source with artifacts including one classified discard, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  one artifact note per artifact appears under data/vault/artifacts/ (a separate surface from data/vault/prose/)
And   each carries artifact_role, field, and source/section provenance in its frontmatter
And   the discard-roled artifact note is present but flagged retrievable: false
And   the prose notes are unaffected and re-running is idempotent
```

## Out of scope

- cited_by backlinks on artifact notes (the `xref` feature).
- Prose-note axis frontmatter (tag slice 04).
- Retrieval semantics of retrievable: false — this slice only records the flag.
