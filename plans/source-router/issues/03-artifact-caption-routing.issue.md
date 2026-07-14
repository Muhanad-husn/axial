# feat(source-router): artifact pass consumes the router; captions attach to their figure/table [slice 03]

**Spec:** specs/PRODUCT.md#5 · §7.2 · §7.8 · §8 P0-5 · **Plan:** plans/source-router/03-artifact-caption-routing.md
**Depends on:** #167
**Labels:** sub:ingestion-v0
**Charter:** #164

## Deliverable

The artifact pass (`run_artifacts`) collects artifact-routed blocks via the router:
`table`/`picture` become vault artifact notes as today, and each `caption` block attaches
to its figure/table so its text rides on that artifact note (not lost, not chunked).
Apparatus-routed blocks are never picked up as artifacts. This completes the caption's
journey out of the prose path (slice 02) and onto the artifact it describes.

## Acceptance criterion

```gherkin
Given a persisted tree with a captioned figure, a table, a table-of-contents (document_index),
      and an endnotes (footnote) section
When   the operator runs `axial artifacts` on the source
Then   the figure and the table each become one vault artifact note (artifact_role / provenance)
And    the figure's artifact note carries its caption text (the caption attached, not lost)
And    no artifact note is produced for the document_index or the footnote blocks
And    the caption is absent from data/chunks/<source_id>.jsonl (from slice 02, still true)
```

## Out of scope

- Retiring the per-pass gate + examine reading router drops (slice 04).
- Re-scoring/re-classifying artifacts — role taxonomy and `cited_by` unchanged.
- The chunk stage — unchanged from slice 02.
