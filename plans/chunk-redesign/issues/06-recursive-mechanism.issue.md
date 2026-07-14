# feat(chunk-redesign): selectable recursive/structural chunk mechanism for the examine head-to-head [slice 06]

**Spec:** specs/PRODUCT.md#5 (stage 4) · §7.7 · §8 P0-4 · **Plan:** plans/chunk-redesign/06-recursive-mechanism.md
**Depends on:** #151 (merged), #154 (downstream consume disk artifact)
**Sequence after:** #164 (source router) — so the head-to-head runs on routed prose only
**Charter:** #148
**Labels:** sub:ingestion-v0

> **Status: already filed as [#165](https://github.com/Muhanad-husn/axial/issues/165).**
> This draft mirrors the filed issue for folder parity; the plan is
> `plans/chunk-redesign/06-recursive-mechanism.md`.

## Deliverable

A second, **selectable** chunk-boundary mechanism: deterministic recursive/structural
splitting on a separator hierarchy (`\n\n` paragraph → `\n` line → sentence → char),
living behind the existing `_chunk_section_text` seam and selected by config/env. It
reuses the current two-sided band — recursive descent enforces `≤ max`, the existing
min-coalesce merges sub-`min` fragments — and writes the **identical §7.7 artifact**
(same `chunk_id` scheme, same fields), so `axial chunk examine` and every downstream
consumer work on it unchanged. Zero LLM and zero embedding-model calls.

The embedding-based mechanism (slice 01) remains the **default**; this adds an opt-in
alternative so the operator can run both on the same corpus and compare via `examine`.
P0-4's "embedding is the primary boundary signal" is unchanged for the default path.

## Acceptance criterion

```gherkin
Given a source with a known paragraph structure — some sections with clear \n\n breaks,
      and one section that is a single wall of text with no \n\n
When  the operator selects the recursive mechanism and runs `axial chunk`
Then  it writes data/chunks/<source_id>.jsonl with the §7.7 fields and stable chunk_ids,
      every chunk ≤ max and (modulo the section-tail exception) ≥ min,
      splitting the wall-of-text section by falling through \n\n → \n → sentence → char
And   it makes zero LLM calls and zero embedding-model calls
And   with the mechanism unset, `axial chunk` still runs the embedding-based default
And   `axial chunk examine` reports on the recursive artifact through the same stats surface
```

## Out of scope

- **Changing the default** or P0-4's "primary boundary signal" — a later,
  founder-adjudicated `spec-drift`, gated on the examine head-to-head result.
- The embedding mechanism (slice 01) and its cache (slice 02) — unchanged.
- Retrieval/answer-quality eval of the two mechanisms — `examine` is the first-pass arbiter.
- #159 (real embedding model) — independent; this path never embeds.
