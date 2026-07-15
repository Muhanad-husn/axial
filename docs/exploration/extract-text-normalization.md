# Extract-stage text normalization — six-book corpus analysis

**Date:** 2026-07-15
**Status:** finding + plan; founder-approved direction, pending spec pass and slices
**Related:** PRD §5 stage 2, §7.4 (structural tree); issues #148 (chunk redesign), #164 (source router)

## Origin

While preparing the operational `axial chunk examine` loop on `batatu-syrias-peasantry.pdf`,
the persisted tree showed pervasive text garble — `● Hawr¯ an`, `/asper Alaw¯ ı`, double
spacing. The founder checked the source PDF, found its text layer clean, and suspected the
pipeline — not the source — was the cause. That was correct.

## Diagnosis

Extraction runs with OCR disabled (`extract.py`, `do_ocr=False`), so this is **not** an OCR
problem: docling's PDF text-layer *decoding* mangles glyphs that a normal reader (and
pypdfium2) lift cleanly. A same-passage, three-extractor comparison confirmed it:

| Extractor | Acknowledgements passage |
|---|---|
| pypdfium2 | `…in the Hawr¯ an, the Druze and Alaw¯ı mountains…` — single-spaced, clean |
| pdfminer | `…the  Gh¯u(cid:1)tah  of  Damascus…` — double-spaced; unmapped glyph = `(cid:1)` |
| docling (ours) | `…the ● Him ● s and ● Ham¯ ah plains…` — `●`, `/asper`, double spaces |

Two independent causes: (1) a genuine font deficiency — a few transliteration glyphs
(underdot, ayn, macron) have no ToUnicode mapping (pdfminer proves it with `(cid:1)`), which
no extractor can recover; (2) docling makes it worse than necessary (renders the unmapped
glyph as a visible `●`/`/asper`, double-spaces, drops em-dashes). A pypdfium2-backend probe
gave far cleaner text but weakened structure detection (footnotes 75→35, headers 168→132),
so the decision is **keep docling-parse and add a deterministic post-extract normalization
pass**.

## Six-book corpus census

Trees extracted once each (serially — concurrent docling OOM-crashes) and censused:

| Book | prose | dbl-space | soft-hyph | comb-marks | PUA | asper/lenis | dotless-i | small-caps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| batatu (Princeton '99) | 3334 | 46,132 | 0 | 10,676 | 0 | 2,891 | 2,791 | 9% |
| hall-schroeder | 2922 | 111,469 | 0 | 0 | 0 | 0 | 0 | 9% |
| kalyvas (Cambridge '06) | 3399 | 5 | 0 | 498 | 123 | 0 | 42 | 23% |
| mann (Cambridge) | 2143 | 19,831 | 0 | 0 | 0 | 0 | 0 | 12% |
| tilly (Addison-Wesley '78) | 3226 | 30,572 | 1,343 | 0 | 0 | 0 | 0 | 5% |
| vignal (modern '17) | 1352 | 29,567 | 0 | 1 | 0 | 0 | 1 | 6% |

### What the corpus proves

1. **Small-caps letter-spacing is the only universal defect** (all 6, 5–23%). Highest value,
   hardest to fix safely (`"I saw"→"Isaw"`).
2. **Whitespace damage is near-universal and cheap** — double-spacing 5/6 (up to 111k);
   soft-hyphens split words invisibly in tilly (1,343). Zero-risk to fix.
3. **Every glyph-level defect is font-specific and isolated to 1–2 books, with disjoint glyph
   sets.** batatu's `●¯/asper` and kalyvas's `´¨`+PUA share nothing; four books are glyph-clean.
   The pass must be principle-based and a no-op when its target is absent (vignal, clean font,
   must pass through untouched).
4. **`/word` false positives appear in all six books** — URLs (`/reliefweb`), paired terms
   (`threat/opportunity`, `infrastructural/despotic`), page-refs (`/p111`). Glyph-name repair
   must be a curated allowlist, never a pattern strip.

## Plan — a tiered, order-independent normalizer

Applied at **tree-build time in `extract.py`**, so the persisted tree is clean and every
downstream pass (chunk, tag, xref, artifacts) inherits clean text. Regenerates cached trees.

- **Tier 1 — whitespace (universal, zero-risk):** strip soft-hyphens (U+00AD), collapse space
  runs, fix space-before-punctuation.
- **Tier 2 — glyph repair (font-specific, no-op when absent):** drop/reattach detached
  combining marks (Unicode Sk); decode PUA offset-glyphs (`chr(c−0xF700)`) else drop; curated
  glyph-name allowlist (`asper`→ʿ, `lenis`→ʾ, `H####`/`Q##`→drop); dotless-i→i.
- **Tier 3 — small-caps repair (universal, hard):** density-gated / dictionary-validated merge.
  Separate slice so it cannot destabilize Tiers 1–2.
- **Out of scope:** middle-dots (`·`, legit notation), composed accents, math symbols.

## Test strategy

The repo may not contain book text (all `data/` is gitignored; no verbatim source text). So:
- **Committed acceptance test:** synthetic defect fixtures — crafted mini-trees reproducing
  each pattern (`●`, `/asper`, soft-hyphen, PUA, double-space, small-caps).
- **Local validation corpus:** the six real books — re-extract, re-census, confirm each
  defect count drops to zero (and that clean books like vignal are unchanged).

## Next steps

1. Spec pass: add the normalization contract to PRD §7.4 / §5 stage 2 (spec-drift — the tree
   text is currently specified "verbatim from extraction").
2. Slice A: Tiers 1+2. Slice B: Tier 3.
