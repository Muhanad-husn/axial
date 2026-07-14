# Slice 06: Selectable recursive/structural chunk mechanism (examine head-to-head)

- **Feature:** chunk-redesign
- **Slice slug:** recursive-mechanism
- **GitHub issue:** #165
- **Branch:** feat/chunk-redesign/06-recursive-mechanism
- **Project directory:** .
- **Status:** ⏳ PR open — [#181](https://github.com/Muhanad-husn/axial/pull/181)
- **Walking skeleton?** no — adds a second mechanism behind an existing seam; the
  stage, artifact, and `examine` surface already exist (slices 01/03)

## Goal — the minimum testable behaviour

A second, **operator-selectable** chunk-boundary mechanism: deterministic
recursive/structural splitting on a separator hierarchy (`\n\n` paragraph → `\n`
line → sentence → char), living behind the existing `_chunk_section_text` seam and
chosen by an env/config selector that mirrors the `AXIAL_EMBEDDER` / `get_embedder`
seam. Recursive descent enforces `≤ max`; the **existing** `_enforce_min` coalesce
merges sub-`min` fragments — same two-sided band, different cut. It writes the
**identical §7.7 artifact** (same `chunk_id` scheme, same fields, same
section-then-position order, same `.skips.jsonl` sidecar contract), so `axial chunk
examine` and every downstream consumer work on it unchanged. **Zero LLM and zero
embedding-model calls** on the recursive path — the embedder and its cache (slice
02) are never constructed when this mechanism is selected. The embedding mechanism
(slice 01) stays the **default**; unset selector = today's behaviour, byte-identical.

## INVEST check

- **Independent:** reads only the persisted tree, writes only the existing artifact.
  Touches `src/axial/chunk.py` (new splitter + selector + orchestrator branch) and
  the `_chunk` CLI handler. No downstream consumer changes — they read the same
  JSONL. No spec change (P0-4's "embedding is the primary signal" holds for the
  default path; flipping the default is a later, founder-adjudicated `spec-drift`).
- **Valuable:** gives the operator a strong LLM-free / embedder-free baseline to run
  head-to-head against the embedding mechanism on the same corpus via `examine` —
  the first-pass arbiter for whether recursive can match embedding at far lower
  operational cost (and potentially retire #159 for chunking).
- **Small:** one new pure splitter, one selector, one orchestrator branch that skips
  embedder construction. Reuses `_enforce_min`, `segment_sentences`,
  `_hard_split_by_chars`, `build_chunk_records`, the router body walk, the skips
  sidecar, and the whole `examine` surface untouched.
- **Testable:** chunk a fixture whose tree has (a) sections with clean paragraph
  breaks and (b) one wall-of-text section with no paragraph breaks; select recursive;
  assert the JSONL has the §7.7 fields and stable `chunk_id`s, every chunk `≤ max`
  and (modulo the section-tail exception) `≥ min`, the wall-of-text section fell
  through the separator hierarchy, **zero LLM and zero embedding calls** were made,
  the default (unset) path still runs embedding, and `examine` reports on it through
  the same stats surface.

## Acceptance criterion (outer loop — the failing e2e/integration test)

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

- **Boundary / endpoint:** CLI `axial chunk <source>` with the mechanism selector
  set (env var), producing the same on-disk artifact the default path produces.
- **Outer test type:** pytest integration test (subprocess; deterministic, offline,
  no network). A spy/counter proves zero embedding-model `encode` calls and zero LLM
  calls on the recursive path.
- **Outer test file (planned):** tests/test_chunk.py (or a sibling
  tests/test_chunk_recursive.py) — test-author, red, locked (DEC-1).

## Inner loop — initial unit test list

- **Selector** (`get_chunk_mechanism` mirroring `get_embedder`): `AXIAL_CHUNK_MECHANISM=recursive`
  selects recursive; unset / any other value → embedding default.
- **Separator hierarchy:** a section with clean `\n\n` paragraph breaks splits at
  paragraphs first; a section with only `\n` line breaks (no `\n\n`) falls through to
  `\n`; a run-on paragraph with no line breaks falls through to sentence
  (`segment_sentences`); a single unsplittable "sentence" over `max` falls through to
  raw char split (`_hard_split_by_chars`).
- **MAX side (recursive descent):** no emitted chunk exceeds `max`, with no exception
  (the unconditional guarantee, same as the embedding path's MAX side).
- **MIN side (reused `_enforce_min`):** short paragraphs coalesce forward within a
  section; a section tail / whole section shorter than `min` may stay below `min`
  (the documented exception); merge never crosses a section boundary.
- **Artifact parity:** the recursive path produces records with the identical field
  set and `chunk_id` scheme as the embedding path (`build_chunk_records` shared,
  unchanged); `chunk_id`s are stable across two runs on the same bytes.
- **Zero-cost proof:** the recursive path constructs no embedder and no
  `_CachingEmbedder`, reads no `data/chunk_cache/` entry, and makes zero LLM calls.
- **Default untouched:** with the selector unset, the embedding path's output is
  byte-identical to before this slice.
- **examine parity:** `examine_chunks` / `format_examine_report` read the recursive
  artifact through the same surface with no changes.

## Decisions to make in this slice

- **Paragraph fidelity / how the top separator gets a `\n\n` to split on
  (PRE-FLIGHT — resolve first).** `run_chunk_embedding` today builds a section body
  as `"\n".join(body_lines)` — a **single** `\n` between docling prose blocks, so a
  literal `\n\n` top separator would never fire on inter-block boundaries and every
  split would degrade to the `\n` level. Confirm docling's paragraph fidelity on one
  real cached source (memory [[chunk-experiment-caching]] — read cached trees, never
  re-run docling), then choose the join for the recursive path: most likely **join
  prose blocks with `\n\n`** (treat each docling block as a paragraph, which is what
  the router already yields), so the `\n\n → \n → sentence → char` hierarchy is
  meaningful. This is the single most load-bearing decision in the slice; the
  boundary-quality claim rests on it. If docling collapses paragraph breaks, the
  hierarchy still falls through cleanly to `\n`/sentence — the mechanism stays
  correct, only the "paragraph-first" quality claim weakens.
- **Where the mechanism branch lives / keeping embedding zero-cost.** The selector
  must be checked **before** the embedder + `_CachingEmbedder` are constructed so the
  recursive path pays nothing for embedding. Options: (a) branch inside
  `run_chunk_embedding` and skip embedder construction when recursive; (b) extract a
  shared `run_chunk` orchestrator (tree read → per-section route → split → write →
  skips sidecar) that both mechanisms call with a mechanism-specific section splitter,
  leaving `run_chunk_embedding` as the embedding wiring. Prefer (b) if it stays small
  — it keeps `run_chunk_embedding`'s name honest and isolates the "no embedder"
  guarantee structurally — but (a) is acceptable if the refactor would balloon the
  slice. Either way the CLI `_chunk` handler dispatches on the selector.
- **Selector name.** `AXIAL_CHUNK_MECHANISM` (env, mirroring `AXIAL_EMBEDDER`) with
  values `embedding` (default) / `recursive`, vs a `config/pipeline.yaml` key. Env
  var is the closer mirror and needs no config plumbing; pick it unless a config key
  is trivially free.

## Out of scope (this slice)

- **Changing the default** or reframing P0-4's "primary boundary signal" — a later,
  founder-adjudicated `spec-drift` gated on the examine head-to-head result. Not here.
- **The embedding mechanism (slice 01) and its cache (slice 02)** — unchanged; the
  default path must stay byte-identical.
- **Retrieval / answer-quality eval of the two mechanisms** — the `examine`
  size-distribution + boundary eyeball is the first-pass arbiter; deeper eval is
  separate scope.
- **#159 (real embedding model)** — independent; this path never embeds.
- **Band / separator tuning** — ship sensible defaults reusing the existing
  `[CHUNK_MIN, CHUNK_MAX]`; proving values is the operational examine loop.
