# Feature: Classify-once source router — only prose is chunked

Charter **#164**. Insert a **routing step at the source** — over the persisted
structural tree (`data/trees`, §7.4), after extraction and before chunking — that
classifies every block by its docling structural `label` and routes it, so
**only prose enters the chunk → tag → xref path**:

- **Prose** (`text`, `section_header`, `title`, in-body `list_item`) → chunk stage → §7.7 artifact.
- **Artifact** (`table`, `picture`, `caption`) → the existing artifact classification
  pass (`artifacts.py`) → vault artifact notes (`artifact_role`, provenance, `cited_by`).
  Captions attach to their figure/table. They **never** enter the prose chunk path.
- **Apparatus** (`document_index` = TOC/index, `footnote`/endnotes, `page_header`/`page_footer`)
  → **dropped**: not chunked, not artifact-noted. The drop is recorded with a reason.

The per-pass `nonprose_guard.non_prose_skip_reason` (a `>30k chars` / `>40% non-alpha`
size-and-garble heuristic, re-decided independently at each LLM entry in xref/tag/artifacts)
is **retired as the primary gate** — it cannot see block *type*, so a clean TOC or a
well-formed endnotes section sails through today. It may remain a backstop for genuinely
garbled prose that slips type classification. `axial chunk examine`'s "skipped-as-garbage
with reasons" reads the **router's** decisions — the single source of skip truth.

- **Slug:** source-router
- **Created:** 2026-07-14
- **Status:** planning
- **New system?** no — adds `src/axial/router.py` and rewires the existing `chunk`,
  `artifacts`, `tag`, `xref` consumers of the tree/chunk artifact
- **Project directory:** .

## Pre-flight unknown — RESOLVED (issue #164 comment)

`data/trees` **preserves** docling's block-type `label` verbatim (`extract.py:150-159`
sets `label = str(item.label)`); extraction is not flattened. No "preserve type through
extraction" slice is needed. A real cached tree confirms every leaf carries a `label`
(`text`, `list_item`, `section_header`, `table`, `caption`, `footnote`, `document_index`).
OCR is off (`do_ocr=False`), so scanned running-heads mostly never enter the tree. This
shrinks #164 to a pure routing stage over the already-labeled tree.

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR (except slice 01,
a spec pass with no outer test).

| # | Slice | Goal (one line) | Depends on | Size | Status | Issue | PR |
|---|-------|-----------------|-----------|------|--------|-------|----|
| 01 | [spec-pass](01-spec-pass.md) | Spec-author amends §5 (routing stage + pipeline position), adds the routing-decision contract, and points P0-4 / P0-4b at the prose-only routed tree — **spec window, no outer test** | none | S | ☐ todo | [#166](https://github.com/Muhanad-husn/axial/issues/166) | — |
| 02 | [router-core](02-router-core.md) | `src/axial/router.py` classifies each block by docling `label` into prose / artifact / apparatus; the chunk stage routes on it — only prose-routed blocks are chunked, apparatus (TOC / index / endnotes / running heads) is dropped and recorded with a reason, captions leave the prose path | 01 (#166) | L | ☐ todo | [#167](https://github.com/Muhanad-husn/axial/issues/167) | — |
| 03 | [artifact-caption-routing](03-artifact-caption-routing.md) | The artifact pass consumes the router: `table` / `picture` route to artifact notes as today, each `caption` attaches to its figure/table, and apparatus is never artifact-noted | 02 (#167) | M | ☐ todo | [#168](https://github.com/Muhanad-husn/axial/issues/168) | — |
| 04 | [gate-retire-examine](04-gate-retire-examine.md) | Retire `non_prose_skip_reason` as the primary prose/non-prose gate in `tag` / `xref` (kept only as a genuine-garble backstop); `axial chunk examine` reports dropped blocks from the router's decisions — the single source of skip truth | 02 (#167) | M | ☐ todo | [#169](https://github.com/Muhanad-husn/axial/issues/169) | — |

Slices 03 and 04 both depend only on 02 (the router + its skip-decision artifact) and are
independent of each other — they can run in parallel once 02 lands.

## Design note — how the router is shared (resolved in 01/02)

The router is a **shared classification function** (`route_for(node) -> "prose" | "artifact"
| "apparatus"`, driven by `label`), called by every consumer on the in-memory tree. "No
downstream pass re-derives the prose/non-prose decision" (#164 DoD) is satisfied because
all consumers call the **same** router, not because a new annotated tree is persisted. The
**drop decisions** (apparatus + genuine garble) are recorded to the router-owned skip
artifact (generalizing today's `data/chunks/<source_id>.skips.jsonl`), which is the single
source of skip truth `examine` reads. Whether the route is also annotated onto the persisted
tree is an implementation choice the spec pass (01) sanctions and slice 02 makes; the DoD
does not require it.

## Out of scope (whole feature)

- **The chunk boundary mechanism** (embedding slice, chunk-redesign #151; recursive split) —
  the router feeds it unchanged. The router decides *which blocks* are prose, not *how* prose
  is split.
- **Re-scoring artifacts** — the artifact pass is unchanged except for being the sole home of
  tables/figures and gaining caption attachment.
- **The gold / eval frame** — already excludes back-matter (memory [[gold-p0-9-strata-ratified]]);
  no change here.
- **Re-parsing / docling** — every slice reads the persisted tree (`data/trees/<source_id>.json`)
  only. No slice re-triggers docling. OCR stays off.
- **`non_prose_skip_reason` deletion** — slice 04 demotes it from primary gate to optional
  backstop; it is not deleted (the size arm still guards genuinely garbled prose).

## Notes / open questions

- **Charter dependency #154 is MERGED** (PR #163) — tag/xref/vault already consume the on-disk
  chunk artifact via `read_chunks`. This feature routes *what reaches* the chunk stage.
- **`caption` is `type=prose` today** (extract.py's `_classify`), so captions leak into
  chunking now. Slice 02 stops the leak (route=artifact ⇒ not chunked); slice 03 attaches the
  caption to its figure/table so its text is not lost. Between 02 and 03 a caption is
  routed-but-not-yet-attached — acceptable interim on a feature branch, but 03 should land
  close behind 02 so no caption text is dropped in a shipped state.
- **`list_item` is ambiguous** (in-body lists vs. a bibliography rendered as list-items). The
  router rule (slice 02): `list_item` is prose **unless** its enclosing section is back-matter
  (reuse `chunk._is_back_matter` / `_BACK_MATTER_TITLES`), in which case it is apparatus.
  `document_index` already catches most TOC/index; this rule covers the residual reference-list
  case.
- **Spec freeze.** Slice 01 is the deliberate spec window (founder opens `.claude/spec-mode`,
  dispatches spec-author, deletes the flag). Implementation slices (02–04) run only after 01 is
  ratified and merged — the frozen-spec rule binds them.
