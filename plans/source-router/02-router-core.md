# Slice 02: Router core — classify blocks by docling label; chunk routes on it

- **Feature:** source-router
- **Slice slug:** router-core
- **GitHub issue:** #167
- **Branch:** feat/source-router/02-router-core
- **Project directory:** .
- **Status:** ✅ merged (PR #171) — with a carried concern: the back-matter `list_item` → apparatus rule is unreachable in the wired chunk stage (the whole-section `_is_back_matter` filter, backed by the locked #113 outer test, subsumes it). Reconciling the two is a founder/spec decision; candidate for slice 04 or a spec-mode pass. See issue #167.
- **Walking skeleton?** yes — introduces `router.py` and wires its first consumer (chunk) end-to-end

## Goal — the minimum testable behaviour

A new `src/axial/router.py` classifies each tree block by its docling structural `label`
into one of three routes — **prose**, **artifact**, **apparatus** — and the chunk stage
(`run_chunk_embedding`) routes on it:

- **prose** (`text`, `section_header`, `title`, in-body `list_item`) → chunked as today.
- **apparatus** (`document_index`, `footnote`, `page_header`, `page_footer`, and a
  `list_item` whose enclosing section is back-matter) → **dropped**: never chunked, and
  recorded to the router-owned skip artifact with a reason.
- **artifact** (`table`, `picture`, `caption`) → not chunked (left for the artifact pass,
  slice 03). Captions therefore leave the prose chunk path here.

The chunk JSONL becomes **prose-only and apparatus-free**. The router is a single shared
classification function so no consumer re-invents the decision.

## INVEST check

- **Independent:** adds a new module + changes only the chunk stage's block selection;
  the boundary/embedding mechanism is untouched. Artifacts/tag/xref rewire in 03/04.
- **Valuable:** stops apparatus (TOC, index, endnotes) and captions leaking into prose
  chunks — the core defect #164 names, which the char-ratio heuristic cannot fix.
- **Small-ish (L):** one new module (label→route map + the back-matter `list_item` rule)
  plus swapping the chunk stage's implicit `type`/title filtering for an explicit router call
  and generalizing its skip sidecar to carry apparatus drops.
- **Testable:** run `axial chunk` on a tree with prose + a `document_index` block + a
  `footnote` block + a `caption` in a prose section; assert none of those texts appear in
  `data/chunks/<source_id>.jsonl`, and the skip artifact records the TOC and endnotes drops
  with reasons.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a persisted tree with prose sections, a table-of-contents (document_index) block,
      an endnotes (footnote) block, an in-body list, and a captioned figure
When   the operator runs `axial chunk` on the source
Then   only the prose sections and the in-body list are chunked into data/chunks/<source_id>.jsonl
And    the document_index and footnote blocks are absent from the chunks and are recorded in
       the router skip artifact with a reason ("apparatus: table of contents" / "apparatus: endnotes")
And    the caption text is absent from the chunks (routed to the artifact path, not dropped as apparatus)
And    a list_item under a back-matter section (e.g. a reference list) is dropped as apparatus, not chunked
```

- **Boundary / endpoint:** the `axial chunk` CLI pass
- **Outer test type:** pytest integration test (fabricated persisted tree; stub embedder; no network)
- **Outer test file (planned):** tests/test_source_router.py — test-author, red, locked

## Inner loop — initial unit test list

- `router.route_for(node)` maps each docling `label` to prose / artifact / apparatus per the
  contract; unknown/absent labels default to prose (fail-open to content, never silently drop).
- A `list_item` under a back-matter section resolves to apparatus; an in-body `list_item`
  resolves to prose (rule reuses `chunk._is_back_matter`).
- A tree walk yields, per block, its route + the enclosing section (for skip provenance).
- `run_chunk_embedding` chunks only prose-routed blocks; artifact/apparatus blocks contribute
  no chunk records.
- Apparatus drops are written to the skip artifact with a route-specific reason; the sidecar is
  rewritten cleanly on rerun (idempotent, as today).
- `caption` blocks are not chunked (route=artifact) and not written to the skip artifact (they
  are not dropped — they belong to the artifact pass).

## Out of scope (this slice)

- **Artifact-pass consumption + caption attachment** — slice 03. Here captions merely leave
  the prose path; their arrival at an artifact note is 03.
- **Retiring the tag/xref per-pass gate + examine reading router drops** — slice 04.
- **The chunk boundary mechanism** — unchanged.

## Notes

- Today's chunk stage already excludes `type=="artifact"` nodes (`_prose_text_lines`) and drops
  back-matter *sections* by title (`_is_back_matter`). This slice replaces that implicit,
  label-blind filtering with the explicit router, adding the block-level apparatus labels
  (`document_index`, `footnote`, page heads/feet) the title match misses.
- The skip artifact generalizes today's `<source_id>.skips.jsonl` (currently garbage-only) to
  also carry apparatus drops — same `{section, section_order, reason}` shape, richer reasons.
- Full acceptance suite runs once here (new module + chunk change) per [[tiered-test-suite-principle]].
- Embedder stays the offline stub seam (`AXIAL_EMBEDDER=stub`) — no network in the gate/CI.
