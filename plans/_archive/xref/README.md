# Feature: Prose↔artifact cross-reference pass

PRD build phase 3 (§11), the final stitch: detect prose→artifact references in the
tagged chunks ("as Table 3 shows") and write **bidirectional** links — `artifact_refs`
into the referencing prose note, `cited_by` into the referenced artifact note — then the
vault carries a navigable graph between the two pools (P0-7, and the backlink half of
P0-8). Runs only after both prose chunking/tagging and artifact classification have
completed, since it needs both sides to link them. Schema-agnostic (it links ids, it does
not tag), stub LLM in tests — no Academic dependency, no live network. Covers §5 stage 7
(cross-reference) and requirement P0-7.

- **Slug:** xref
- **Created:** 2026-07-08
- **Status:** planning
- **New system?** no
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | Issue | PR |
|---|-------|-----------------|--------|-------|----|
| 01 | [xref-detect](01-xref-detect.md) | `axial xref <file>` detects prose→artifact references and emits `(chunk_id → artifact_id)` link pairs | ☐ todo | [#33](https://github.com/Muhanad-husn/axial/issues/33) | — |
| 02 | [xref-backlinks](02-xref-backlinks.md) | writes bidirectional frontmatter — `artifact_refs` into prose notes, `cited_by` into artifact notes | ☐ todo | [#34](https://github.com/Muhanad-husn/axial/issues/34) | — |

## Out of scope (whole feature)

- **Prose and artifact tagging** — the `tag` and `artifacts` features. This feature links
  what they produce; it does not tag.
- **Artifact→prose reference direction that isn't a textual citation** — v0 detects
  prose→artifact references ("as Table 3 shows") and materialises them in both
  directions; it does not infer semantic relatedness beyond an explicit reference.
- **Live API calls in tests** — stub/record client via `AXIAL_LLM_PROVIDER`; CI is offline.

## Notes / open questions

- **Runs last (ordering is load-bearing).** P0-7 requires the pass to run after both
  chunking and artifact classification. Slice 01 consumes the chunk records and the
  classified artifacts; slice 02 writes backlinks only after both prose and artifact notes
  exist on disk — so its acceptance test drives the full `axial vault write` thread.
- **Detection LLM seam.** The detection pass identifies itself with `pass_name="xref"` so
  the stub returns a reference-pair-shaped canned response; same `get_client`/stub/record
  seam as the other passes. A referenced `artifact_id` the model returns that is not among
  the source's actual artifacts is rejected (unknown ids can't produce a valid backlink) —
  the exact handling (hard error vs. logged drop) is settled by the test-author with the
  reviewer; the plan requires only that no dangling backlink is ever written.
- **Bidirectional consistency is the invariant.** Every `artifact_refs` entry on a prose
  note must have a matching `cited_by` entry on the artifact note, and vice versa — slice
  02's tests assert this both ways.
- **Idempotency.** Re-running `axial vault write` must not duplicate backlink entries — the
  same phase-2 idempotency guarantee, now extended to list-valued frontmatter fields.
