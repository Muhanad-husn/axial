# #661 back-matter census: how much of the evidence set is not argument?

2026-08-04. Offline, read-only, no model calls. Run from `D:\axial` (main at
`e43e8b1`) against the live store `data/vault/notes.db` (6,148 notes, 31
sources). Script: `scratchpad/661_backmatter_census.py` (scratch, not
committed).

## What was measured

Every note's own `section` title, classified by the two rules the codebase
already ships:

- `axial.chunk._is_back_matter` — the chunk-pass vocabulary (#113). Exact
  match against 20 unambiguous titles. Deliberately conservative: "Notes",
  "Acknowledgments", "Preface" and appendices are KEPT, because a false keep
  is cheap at chunk time and a false drop loses real content.
- `axial.gold._is_back_matter` — the gold-frame rule (#53, #131, #134, #204).
  The same vocabulary plus appendix/annex prefixes, "notes to page N",
  roman-prefixed reference subsections, page-number prefixes, and a
  references-family suffix check.

## Result

| Metric | Value |
|---|---|
| Notes in store | 6,148 |
| Sections null or empty | 0 |
| Back matter by the chunk-pass vocabulary | **0 (0.0%)** |
| Back matter by the gold-frame rule | **497 (8.1%)** |
| Sources touched | 27 of 31 |
| Name answers on those notes | 19,984 of 140,596 (**14.2%**) |
| Citations on those notes | 4,891 of 32,796 (**14.9%**) |
| `arguing_against` targets on those notes | 237 of 12,743 (1.9%) |

Top titles by note count: `Notes` 269, `NOTES` 104, `3 General Secondary
Sources` 39, `Acknowledgements` 9, `Acknowledgments` 8, `Preface` 7, `Notes:`
6, `ACKNOWLEDGEMENTS` 4, `appendix bibliography (...)` 4, `Notes to pages
39-42` 3, `V. Articles and Periodicals` 3, then a long tail of page-prefixed
bibliography lines (`224 Y Bibliography`, `90 References`).

Both chunks named in the issue classify as back matter under the gold rule
and neither does under the chunk rule:

- `ungor-2020-ae5701dcc706_3_acknowledgments_001`, section `Acknowledgments`
- `vignal-2021-c7005c2bf8ef_113_notes_001`, section `NOTES`

## What it means

1. **The classifier already exists and already fires on exactly these notes.**
   Nothing needs inventing; the gold-frame rule is simply not wired to the
   retrievable evidence set. That makes #661 a wiring fix, not a heuristic.
2. **8.1% of notes, but 14–15% of the name answers and citations.** Endnote
   pages are citation-dense, so back matter is over-represented in precisely
   the relations #658's retrieval now walks. The share of retrieval exposure
   is larger than the share of notes.
3. **The interrogation pass did spend money on them** — 497 notes were
   interrogated to produce answers that should never ground a claim. At the
   measured ~$34 per full pass that is roughly $2.75 of every pass. Not worth
   a separate fix on its own; worth knowing before the next full pass.

## Next

Issue #661 dispatched to a builder on `fix/661-backmatter-not-evidence`:
promote the rule to a shared home, classify once at materialize into a
`back_matter` flag on `notes`, filter it in the store reads every retrieval
path goes through, and check the argument-map path too. The live store needs
a materialize re-run for the fix to bite on `data/`.
