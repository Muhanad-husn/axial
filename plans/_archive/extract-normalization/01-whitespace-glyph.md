# Slice A — Post-extract text normalization: Tiers 1 + 2 (whitespace + glyph repair)

**Issue:** #188 (epic — this slice does not close it; Slice B / Tier 3 remains)
**Spec contract:** PRD §5 stage 2, §7.4 "Post-extract text normalization", acceptance criteria **P0-2b**
**Finding / rationale:** `docs/exploration/extract-text-normalization.md` (six-book census)
**Module:** `src/axial/extract.py`

## Behavioral change

At tree-build time, before the tree is persisted, a **deterministic, model-free**
normalization pass repairs decoding defects in each block's `text`. It runs once,
here, so every downstream pass (chunk, tag, xref, artifacts) inherits clean text.
It touches **only `text` values** — never the tree's shape, nor any block's
`label`, `type`, or `order`. It is organized as **independent transforms, each a
no-op when its target defect is absent**, so a clean-font source passes through
materially unchanged.

Applies on **both** extraction paths — the docling `normalize()` path and the
Unstructured `_normalize_unstructured()` fallback path (both build nodes via a
`*_leaf_node` helper that sets `node["text"]`). The single normalization function
must cover both.

## In scope (this slice)

**Tier 1 — whitespace (universal, zero-risk):**
- strip soft-hyphens (U+00AD)
- collapse runs of whitespace to a single space
- remove space-before-punctuation

**Tier 2 — glyph repair (font-specific, no-op when absent):**
- drop or reattach detached combining marks (Unicode category **Sk** — e.g. a
  detached macron `¯`, acute, diaeresis, cedilla stranded by decoding)
- decode Private-Use-Area offset glyphs where recoverable (`chr(c − 0xF700)`);
  drop them where unrecoverable
- curated glyph-name **allowlist**: `asper`→ayn `ʿ`, `lenis`→hamza `ʾ`,
  `H####` / `Q##` font-internal codes → drop
- normalize dotless-i (`ı`) → `i`

**Safety principle — curated allowlist, never a pattern strip.** Glyph-name repair
matches only the specific leaked names on its allowlist. It must **never** strip
slash-words as a class: legitimate `and/or`, `threat/opportunity`, `/reliefweb`,
`/p111` are preserved. When a leaked name is not on the allowlist, leave the text
unchanged rather than guess.

## Explicitly out of scope (left untouched)

- Middle-dots (`·`, legitimate notation), correctly-composed accents, math symbols.
- **Tier 3 — small-caps letter-spacing repair** — deferred to Slice B; kept
  separate so it cannot destabilize Tiers 1–2.

## Invariants the acceptance test must pin (P0-2b)

1. Pass alters no block's `label`, `type`, or `order` and does not change the
   tree's shape; only `text` is eligible to change.
2. Each transform is a no-op when its target defect is absent: a clean-font
   source passes through materially unchanged.
3. Tier 1 whitespace defects repaired (soft-hyphen removed, whitespace runs
   collapsed, space-before-punctuation removed).
4. Tier 2 glyph defects repaired per the transforms above.
5. Glyph-name repair is an allowlist, not a `/word` strip — the four legitimate
   slash-word shapes survive.
6. Out-of-scope characters (middle-dot, composed accents, math symbols) untouched.

## Test strategy

`data/` is gitignored — the repo holds no book text. So:
- **Committed acceptance test:** synthetic defect fixtures — crafted mini-trees
  (nested `{children, type, order, label, text}`) reproducing each pattern, plus
  a clean-tree pass-through case and the slash-word preservation case.
- **Local validation (not committed):** the six real books — re-extract,
  re-census, confirm each in-scope defect count drops to zero and clean books
  (vignal) are unchanged. Founder-run; evidence only, no source text committed.

## Notes for the implementer

- Cleanest insertion point: normalize the `text` value where nodes are built
  (`_leaf_node` / `_unstructured_leaf_node` both set `node["text"]`), or a single
  tree-walk pass invoked before `persist_tree`. Either satisfies "before the tree
  is persisted" and covers both extraction paths — pick the one that keeps the
  two paths sharing one normalizer.
- Keep the transforms individually testable and order-independent.
- No new heavy dependency: `unicodedata` (stdlib) supplies the Sk category check.
