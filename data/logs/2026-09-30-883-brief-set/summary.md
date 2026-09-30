# 2026-09-30 — #883: the cross-book brief set and the S-04 door failures, $0

**Reading: the issue's free check cannot reject a brief. Every smoke brief and
every draft passes "corridor reaches 3+ books", S-04 with 24. S-04 and S-05
cite one or two books because they ask about one case, not because retrieval
is narrow. The set is chosen by the question, and the founder approves it.
The S-04 door failures belong to that brief with v4.1-flash: 7 of 17 S-04 door
calls stalled, 0 of 48 on the other briefs.**

## Commands

```
cd D:/axial-runs
python data/logs/2026-09-30-883-brief-set/density.py > density.txt     # regions, author-pair conflicts
python - > conflicts.txt                                                 # 68 cross-author conflicts listed (inline, see issue)
python data/logs/2026-09-30-883-brief-set/dryrun.py > dryrun.txt        # landing + corridor, encoder only
python data/logs/2026-09-30-883-brief-set/predictor.py > predictor.txt  # composed prefix vs books cited
```

Main at `f40f5ed`. Map `9b796b3a6312b329`, 1,937 positions, 2,020 relations
(727 cross-author, 68 of them conflicts). Zero model calls.

## 1. Brief set

13 drafts (`candidates.json`), each built on a cluster of cross-author
conflicts. Two stand-ins for the door, since the real door is a model call:
`proxy` (arguments written with the draft, biased upward) and `request` (the
request sentence alone, top 24, a floor).

| | corridor books, min over briefs |
|---|---:|
| smoke, real door asks | 11 (S-02); S-04 24 |
| drafts, proxy | 11 |
| drafts, request only | 9 |

All pass at 3. The composed prefix does not separate them either:

| brief | books composed | effective books | books cited |
|---|---:|---:|---:|
| S-01 | 15.7 | 8.3 | 4.6 [3-6] |
| S-02 | 10.5 | 6.2 | 6.7 [5-8] |
| S-03 | 13.8 | 5.6 | 3.8 [3-5] |
| S-04 | 18.9 | 9.5 | 1.1 [1-2] |
| S-05 | 16.6 | 7.1 | 1.5 [1-3] |

S-04 feeds synthesis the broadest prefix and cites the fewest books. Its
request asks for "that case specifically"; S-05's shape is "single-source
concentration". The narrowness is the brief's, by design.

Proposed set of 10 (`briefs/`): X-01 genocide, X-02 civil-war violence, X-03
the European miracle, X-04 oriental despotism, X-05 Syrian and Arab
nationalism, X-06 the Ba'th political economy, X-09 war and popular
nationalism, X-10 sources of social power, X-11 tribes and the state, X-13 how
the Asads held power. Dropped: X-07 (repeats S-03), X-08 (repeats S-04/S-05's
single-case shape), X-12 (repeats S-02).

## 2. S-04 door failures

| brief | door calls | stalled | median s | median completion tokens | median tok/s |
|---|---:|---:|---:|---:|---:|
| S-01 | 12 | 0 | 21 | 2,899 | 137 |
| S-02 | 12 | 0 | 30 | 2,250 | 79 |
| S-03 | 12 | 0 | 37 | 5,294 | 152 |
| S-04 | 17 | 7 | 54 | 4,834 | 74 |
| S-05 | 12 | 0 | 30 | 4,335 | 146 |

- 6 calls hit the 600s deadline (arm B: 3, arm C: 3 in a row on draw 2). The 7th returned after 400s with 2,063 tokens and a cut-off JSON body (`finish_reason=stop`, 1,246 chars): #881's "not valid JSON".
- Other passes running beside each stall answered in under 75s, so the provider was not stalled.
- S-04's successful door answers are not longer than S-03's. The stalls do not fit "long outputs".
- Cause: the brief with this model. The deadline is not the cause: it is ten times the median. Nothing to build; S-04 is not in the new set.

## Next

Founder approves the set (or edits it). Then arms A and C on it, 3 draws:
60 answers at ~$0.065 by #879's cost, estimate $3.90, cap $5.85.

## 3. Paid run: arms A and C on the ten briefs (approved 2026-09-30)

```
cd D:/axial-runs
python data/logs/2026-09-30-883-brief-set/watch_run.py \
  .venv/Scripts/python.exe data/logs/2026-09-30-883-brief-set/arms.py A C
python analyze.py > analysis.txt; python pairs.py > pairs.txt
```

$4.26 by key usage against a $3.90 estimate and a $5.85 cap (1.09x). 3,593s
wall clock. 60 of 60 draws OK, no door failures. Both files restored.
`pairs.py` reproduces #881's arm C row on #879's records exactly (76 / 6 / 21 / 6).

**Reading: on briefs that need several books, the #858 relations reach every
brief but the answers do not get broader. Sources cited: 4.67 (A) and 4.50 (C),
with one brief lower in C and none higher. Cited corridor positions rise from
5.3 to 6.9, clear of the spread on 2 of 10 briefs. Answers cite both sides of a
conflict about three times as often as on the smoke set, in both arms.**

| measure, mean per answer | A count order, 1,472 | C kind order, 2,020 | separated (C vs A) |
|---|---:|---:|---|
| sources cited | 4.67 | 4.50 | 0 up / 1 down (X-01) |
| corridor positions cited | 5.33 | 6.87 | 2 up (X-04, X-06) |
| cited positions reached only via #858 | 0 | 2.27 | 7 up (9 of 10 briefs non-zero) |
| cited positions, cross-author link | 1.20 | 2.30 | 3 up |
| corridor size | 23.1 | 39.8 | 5 up |
| claims | 11.6 | 11.0 | 1 down |
| cost per answer | $0.054 | $0.060 | |

Conflict pairs (both ends in the composed prompt):

| arm | pairs shown | both ends cited | one end cited | answers with a both-ends pair |
|---|---:|---:|---:|---:|
| A | 181 | 56 (31%) | 67 | 21 / 30 |
| C | 221 | 64 (29%) | 79 | 22 / 30 |
| smoke, #879 C (for scale) | 76 | 6 (8%) | 21 | 6 / 13 |

- Sources cited are higher than on the smoke set (4.6 against 3.5), but that is the briefs, not the arms: both arms rise together.
- X-06 (Ba'th socialism) and X-13 (how the Asads held power) cite both ends of no conflict pair in either arm, on 8-16 and 2-3 pairs shown. X-06 is the only brief where a question that turns on a conflict shows pairs and never cites both sides.
- Gates flip without a pattern across arms (X-01 A PPPF to C PPPP; X-10 PPPP to FPPF). Grounding passes everywhere.
