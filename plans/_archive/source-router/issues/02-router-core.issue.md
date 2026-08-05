# feat(source-router): router classifies blocks by docling label; chunk routes on it [slice 02]

**Spec:** specs/PRODUCT.md#5 · §7.4 · §7.7 · §7.8 · §8 P0-4 · **Plan:** plans/source-router/02-router-core.md
**Depends on:** #166 (spec ratified & merged first)
**Labels:** sub:ingestion-v0
**Charter:** #164

## Deliverable

A new `src/axial/router.py` classifies each structural-tree block by its docling `label`
into **prose** (`text`, `section_header`, `title`, in-body `list_item`), **artifact**
(`table`, `picture`, `caption`), or **apparatus** (`document_index`, `footnote`,
`page_header`, `page_footer`, and a `list_item` under a back-matter section). The chunk
stage (`run_chunk_embedding`) routes on it: only prose-routed blocks are chunked; apparatus
is dropped and recorded to the router skip artifact with a reason; captions leave the prose
path. The chunk JSONL becomes prose-only and apparatus-free. One shared router function — no
consumer re-invents the decision.

## Acceptance criterion

```gherkin
Given a persisted tree with prose sections, a table-of-contents (document_index) block,
      an endnotes (footnote) block, an in-body list, and a captioned figure
When   the operator runs `axial chunk` on the source
Then   only the prose sections and the in-body list are chunked into data/chunks/<source_id>.jsonl
And    the document_index and footnote blocks are absent from the chunks and are recorded in
       the router skip artifact with a reason
And    the caption text is absent from the chunks (routed to the artifact path, not dropped as apparatus)
And    a list_item under a back-matter section is dropped as apparatus, not chunked
```

## Out of scope

- Artifact-pass consumption + caption attachment (slice 03) — here captions only leave the prose path.
- Retiring the tag/xref per-pass gate + examine reading router drops (slice 04).
- The chunk boundary/embedding mechanism — unchanged.
