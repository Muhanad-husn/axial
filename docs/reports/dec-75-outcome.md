# DEC-75: what the plan did (#853–#860, #878, #879)

2026-09-30. DEC-75 ruled on 2026-09-28 that the name pages go, the argument
map becomes the vault, and each layer gets the schema it needs. The plan ran as
eight issues and two follow-ups, 17 merged pull requests, over three days.

**Reading: the system is much smaller and better structured, and answers are
as good as before, not better.** Nothing regressed. The map now carries twice
the cross-author relations, and answers use them on two briefs of five. They
cite no more sources, and they still leave conflicting positions uncited.

## The system

| lever | issue | measured |
|---|---|---|
| name pages, Gather and the `name` arm deleted | #853 | 47,584 pages gone; vault 299 MB to 178 MB; −15,270 lines in #862; Gather's $4.94 a pass gone; the retired arm had cost 3.2x and run 4x slower than the map for no grounding gain (#809) |
| the map is the vault | #854 | 1,937 position pages; every relation a link on both ends; deterministic; zero model calls |
| relations carry a committed kind | #855 | 99.3% of 1,472 typed for $0.025; 13% conflict; two-model agreement 77–82% |
| Wikidata QIDs for names in 5+ sources | #856 | 35.9% of 1,343 resolved, ~95% right; exposed 5 wrong merges and 10 missed ones |
| `about` and `move` committed; SKOS export | #857 | coverage 93.8% and 96.6%; agreement 74.6% on `about`; $0.60 |
| relations proposed from the vocabulary profile | #858, #877 | cross-author relations 629 to about 1,170; 564 new relations for $0.90; hand-read 16/20 and 14/20 sound against the old pass's 17/20 |
| the new relations reach answers and the vault | #878 | 2,020 relations on pages; isolated positions 432 to 321 |
| frontier extraction model | #859 | book spread unmoved; bar failed; no rebuild ($3.54) |
| opposition-seeded bagging | #860 | book spread up about a fifth against a 2x bar; purity down; no rebuild ($6.52) |

Across the 17 pull requests: +12,318 / −15,897 lines. The additions include
tests and #873's restore of `map compare`, which #851 had deleted before the plan began.
Paid runs came to about $15 in all.

## The answers (#879)

The five smoke briefs, 3 draws each, on three corridor states. Mean per
answer; a difference counts only where one arm's draw range sits wholly
clear of the other's.

| measure | before (count order, 1,472) | kind order | kind order + #858 (2,020) |
|---|---:|---:|---:|
| sources cited | 3.33 | 3.60 | 3.54 |
| corridor positions cited | 3.67 | 4.33 | 5.00 |
| conflict-joined positions cited | 0.13 | 0.27 | 0.00 |
| positions cited only via #858 | 0 | 0 | 1.54 |
| grounding | 1.000 | 1.000 | 1.000 |
| cost per answer | $0.061 | $0.057 | $0.056 |

- **Breadth:** unchanged on every brief. Two of the five briefs draw on one book in every arm and have no room to broaden.
- **#858:** used where a brief has cross-book structure. S-01 and S-02 cite 3 and 5.5 positions per answer that only the new relations reach. On S-01 the cited corridor positions rise from 1.7 to 5.0, clear of the draw spread.
- **Kind order (#855):** no measurable effect.
- **Conflicts:** every conflict-joined position reaches the synthesis prompt (42/42 and 48/48), and the model cites 4 and 0 of them, against about 20% for other corridor positions. The counter-position pass skips them too. The prompt never says which passages contest which.
- **Reliability:** 2 of 45 draws failed. One cited a non-id the fail-closed check caught; one hit the 600s deadline three times.

## What stays open

- Making synthesis engage the conflicts the map found. That is a design call, filed as its own issue.
- Five briefs are a small instrument: two of them cannot show breadth at all. A brief set built for cross-book questions would resolve smaller effects.

Run logs: `data/logs/2026-09-30-879-answer-arms/` and the per-issue logs
under `data/logs/2026-09-2{9,30}-85*`.
