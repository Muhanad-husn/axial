# DEC-75: what the plan did (#853–#860, #878–#883)

**Status: complete, 2026-10-01.** #883 closed the last open question; the
decisions it closed on are DEC-76.

DEC-75 ruled on 2026-09-28 that the name pages go, the argument map becomes
the vault, and each layer gets the schema it needs. The plan ran as eight
issues and four follow-ups, 17 merged pull requests, over four days.

**Reading: the system is much smaller and better structured, and answers are
as good as before, not better.** Nothing regressed. The map now carries twice
the cross-author relations, and answers use them on nine briefs of ten built
to need several books. They cite no more sources: how many books an answer
cites is set by the question, not by retrieval.

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
Paid runs came to about $20 in all, including #881's $0.79 and #883's $4.26.

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
- **Conflicts:** every conflict-joined corridor position reaches the synthesis prompt (42/42 and 48/48), and the model cites 4 and 0 of them, against about 20% for other corridor positions. Counted over all composed passages, though, answers cite both sides of a conflict in about half of them (8–12% of conflict pairs). #881 then listed the conflicts in the prompt, and the rate did not move (8%).
- **Reliability:** 2 of 45 draws failed. One cited a non-id the fail-closed check caught; one hit the 600s deadline three times.

## The cross-book briefs (#883)

Ten briefs written to need several books (`config/briefs/cross/`), each built
on a cluster of cross-author conflicts, 3 draws each, before and with #858.

| measure, mean per answer | count order, 1,472 | kind order + #858, 2,020 |
|---|---:|---:|
| sources cited | 4.67 | 4.50 |
| corridor positions cited | 5.33 | 6.87 |
| positions cited only via #858 | 0 | 2.27 |
| conflict pairs with both ends cited | 56/181 (31%) | 64/221 (29%) |
| cost per answer | $0.054 | $0.060 |

- **Breadth:** sources cited rise from 3.5 on the smoke set to 4.6 here, in both arms alike. The briefs moved it; #858 did not. No retrieval-side check could have predicted this: S-04 puts 19 books in front of synthesis and cites one, because it asks about one case.
- **#858:** cited on 9 of 10 briefs, 2.3 positions per answer that only the new relations reach.
- **Conflicts:** answers cite both sides about three times as often as on the smoke set, in both arms. X-06 (Ba'th socialism) shows conflict pairs in every answer and never cites both ends of one.
- **S-04's door stalls** (7 of 17 calls, 0 of 48 on other briefs) belong to that brief with the current door model, not to the deadline or the provider.

## Closed (DEC-76)

- Retrieval is not tuned further for breadth.
- The #858 relations stay.
- The ten cross-book briefs measure answers from here; the smoke briefs stay as pass/fail gates only.
- Conflicts stay parked. Before any reopening, a free read of X-06's six answers.
- No action on the S-04 door stalls.

Still open from the review: whether a public AIF/SKOS/CiTO export is wanted at all.

Run logs: `data/logs/2026-09-30-879-answer-arms/`,
`data/logs/2026-09-30-881-conflicts-arm-C/`,
`data/logs/2026-09-30-883-brief-set/`, and the per-issue logs under
`data/logs/2026-09-2{9,30}-85*`.
