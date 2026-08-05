# feat(source-router): retire the per-pass non-prose gate; examine reads the router's decisions [slice 04]

**Spec:** specs/PRODUCT.md#5 · §7.7 · §7.8 · §8 P0-4b · **Plan:** plans/source-router/04-gate-retire-examine.md
**Depends on:** #167
**Labels:** sub:ingestion-v0
**Charter:** #164

## Deliverable

Close #164's "classify once, decide once" intent:

1. Retire `nonprose_guard.non_prose_skip_reason` as the **primary** prose/non-prose gate in
   `tag` and `xref` — the chunk artifact is already prose-only (routed), so they no longer
   re-decide per item at LLM entry. The guard stays only as a **backstop** for genuinely
   garbled prose that slips type classification.
2. `axial chunk examine` reports dropped blocks from the **router's** decisions — the single
   source of skip truth — so apparatus drops (TOC, index, endnotes, running heads) appear in
   examine's "skipped/dropped with reasons" section.

## Acceptance criterion

```gherkin
Given routed prose chunks (data/chunks/<source_id>.jsonl) and the router's recorded drops
When   the operator runs the downstream passes (tag, xref) and then `axial chunk examine`
Then   no tag/xref pass re-derives the prose/non-prose decision — every prose chunk reaches its pass
And    `axial chunk examine` reports the dropped document_index / index / footnote blocks with
       the router's reasons (the single source of skip truth)
And    a genuinely garbled prose chunk is still caught by the retained backstop, not silently tagged
```

## Out of scope

- Deleting `nonprose_guard` — the size/non-alpha arm stays as the backstop; only its role as
  the primary gate is retired.
- Routing logic / artifact pass — unchanged from slices 02/03.
