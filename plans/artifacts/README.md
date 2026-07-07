# Feature: Artifact classification & routing

PRD build phase 3 (§11), the artifact half: each non-text artifact the structural
extraction separates out (a table, figure, block quote, typology — tree nodes typed
`artifact`) is classified with exactly one `artifact_role` from the schema's closed
Appendix D taxonomy and routed to a **separate artifact pool** (`data/vault/artifacts/`),
never embedded in prose (P0-5, P0-8). `discard`-roled artifacts (cover images, running
heads, page numbers) are retained in the pool but flagged non-retrievable. Artifacts
also carry a `field` tag and source/section provenance, with `cited_by` back-references
added later by the `xref` feature. Schema-driven and hard-erroring like prose tagging;
stub LLM in tests — no Academic dependency, no live network. Covers §5 stage 5 and
requirement P0-5 (and the artifact-pool half of P0-8).

- **Slug:** artifacts
- **Created:** 2026-07-08
- **Status:** planning
- **New system?** no
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | Issue | PR |
|---|-------|-----------------|--------|-------|----|
| 01 | [artifact-classify](01-artifact-classify.md) | `axial artifacts <file>` gives each artifact node exactly one `artifact_role` (Appendix D, schema-driven, hard-error); emits records | ☐ todo | [#30](https://github.com/Muhanad-husn/axial/issues/30) | — |
| 02 | [artifact-pool-write](02-artifact-pool-write.md) | artifact notes written to `data/vault/artifacts/` with `artifact_role` + `field` + provenance; `discard` retained-but-flagged non-retrievable | ☐ todo | [#32](https://github.com/Muhanad-husn/axial/issues/32) | — |

## Out of scope (whole feature)

- **Prose tagging** — the `tag` feature (P0-6).
- **Cross-reference backlinks** (`cited_by` on artifacts, `artifact_refs` on prose) — the
  `xref` feature (P0-7). Artifact notes here carry no backlinks yet.
- **Deep artifact understanding** — routing is feature-based classification (a role tag),
  not content extraction or OCR of the artifact (§3 non-goals, §5 stage 5 "a lightweight
  model suffices").
- **Live API calls in tests** — stub/record client via `AXIAL_LLM_PROVIDER`; CI is offline.

## Notes / open questions

- **Artifact id + provenance.** Each artifact gets a stable, deterministic id
  (`<source_id>_art_<order>`, from the node's unique `order`, mirroring how `chunk.py`
  builds `chunk_id`). Provenance is the enclosing section's verbatim heading — collected
  by walking the extraction tree, since artifact nodes sit as descendants under section
  nodes.
- **Classification pass LLM seam.** The pass identifies itself with `pass_name="artifacts"`
  so the stub returns an artifact-role-shaped canned response; a cheap model suffices in
  production (§5 stage 5). Same `get_client`/stub/record seam as the other passes.
- **`field` on artifacts reuses the prose validator.** `field` (Appendix A) applies to
  both prose and artifacts; slice 02 reuses the `primary_plus_secondary` validator built
  in `tag` slice 03 rather than reimplementing it — hence the dependency on `tag` 03.
- **`discard` is retained, not dropped.** P0-5 is explicit: a `discard` artifact is
  written to the pool with a `retrievable: false` flag, not deleted — so nothing silently
  vanishes and the decision is auditable.
