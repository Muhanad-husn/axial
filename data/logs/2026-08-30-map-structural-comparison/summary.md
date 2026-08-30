# 2026-08-30 — the structural comparison, and the killed replicate (#831, slice 06)

**Verdict: no-go on slices 07–09.** Two of the five deciding metrics fail
against issue #831's own bar, and both are named failure conditions there
(2 and 4). The full report is quoted verbatim at the bottom of this log —
`compare.txt` is gitignored, so this is the only committed copy. It reproduced
byte-identically on two runs on the day, and again after the amendment below.

> **Amended 2026-08-30 after the review of PR #846**, which found two wrong
> readings in this log and four things the report did not print. The command
> was re-run — zero model calls, $0 — and the report quoted in full at the
> bottom is that re-run. What moved: **D3 goes from "passed, thinly" to "not
> resolved at this sample"** (its 11+ margin is 0.0048 against a null spread
> of 0.0078); the baseline's embedding-merge folds are now derived and
> printed (0.139 per final position against B's 0.067); and the "D1's logic
> applied to D2" claim below was **false and is corrected**. The verdict is
> unchanged: D2 and D4 fail, D1 is not resolved, no-go.

## Command

```
uv run axial map compare data/map/9b796b3a6312b329 \
                         data/map/9b796b3a6312b329-category \
                         --vocabulary-dir data/vocabulary
```

Run from the slice-06 branch worktree `D:/wt/831` against the main checkout's
`data/`, because `data/` is gitignored and does not exist in a worktree. Zero
model calls, seed 831, 20 permutation trials per null.

## Result

| metric | reading | against the bar |
|---|---|---|
| **D1** book-spread, size-matched | 0.66 / 0.49 / 0.38 / **0.36** by band, against A's 0.59 / 0.37 / 0.24 / **0.14**. Rises in every band; 2.6× in the plurality band (11+) | **not resolved** — clears 2× and falls in no band, but the replicate gap was never measured (see below) |
| **D2** held-out `position` purity | **0.6620** against A's **0.7597** | **failed** — moved *down* 0.0977, three times the 0.0331 assignment-instability floor, in the wrong direction |
| **D3** member coherence | at or above the A/null midpoint in every band, margins +0.0301 / +0.0308 / +0.0236 / **+0.0048** | **not resolved** — the 11+ margin is 0.0048 against that band's own null spread of 0.0078. The floor is half a null estimate; this margin is inside it |
| **D4** passages reaching no position | **513 of 6,010 = 8.5%** (at least 457 declined by the extraction model, 31 in failed reads, 17 ungrouped — 505 attributed, 8 not) | **failed** — above the 6.9% ceiling (414 of 6,010) |
| **D5** blind paired hand-sample | not run | see "D5 not run" below |

The instrument validates against the figure it was built to reproduce: D2 on
the default build reads **0.7597**, exactly #831's measured baseline.

## D2 is not size-matched the way D1 is — flagged, and it changes nothing

The bar compares raw member-weighted purity across two builds whose position
sizes differ by a lot: band 11+ holds **2,713 of B's 5,542 member slots**
against **1,110 of A's 5,987**. Purity falls with group size mechanically, and
#831 says so itself. D1 was deliberately built as a ratio for exactly this
reason ("invariant to how large the variant's positions turn out to be, which
is the confound that sinks the raw cross-book rate"). D2 was not given the same
treatment.

**On a ratio basis the two builds are indistinguishable, not "the variant is
marginally better".** The variant's lift is **1.914 against the baseline's
1.880** — a difference of **+0.034 against the 0.068 lift floor** the same
2026-08-29 measurement produced. Half the floor, inside the noise. The floor
was measured on all three scales this report prints (0.0331 member-weighted,
0.0294 per-position mean, 0.068 lift) and the report now prints all three, so
the lift column cannot be read without it.

**And D1's own bar applied to D2 does not rescue it either.** D1's rule is not
"the ratio rose" — it is ratio against own null, with the variant reaching at
least **2×** the baseline's ratio. Applied to D2 that requires a lift of at
least **2 × 1.880 = 3.76**; the variant reads **1.914**. D2 fails on the bar as
written and on D1's construction alike.

What survives is the narrower observation: D2's bar compares raw purity across
builds with very different size distributions while D1's is a ratio, and the
two are not built the same way. Whether the bar should be re-cut is the
founder's call — it makes no difference to this verdict.

**D4 is not a size artifact and stands either way.** 457 extraction-model
declines against the baseline's 373 are deterministic counts with no noise term.

## The replicate was launched, then killed

Launched 05:21 as a forced category build (`map build --grouping category
--force`), detached, unbuffered. **Killed at ~206 of 226 extraction reads,
before the consolidation stage started** — founder's call, on the reading that
the replicate buys an error bar on a verdict it cannot change: D4 is
arithmetic, and a D2 gap of −0.098 is either real or means the noise is so wide
the answer is "not resolved", which is also a no-go.

Spent and kept: **~206 extraction reads, roughly $0.30**, preserved at
`reads.partial-replicate.jsonl` rather than deleted. Not spent: the ~$1.80,
~6.8-hour consolidation pass.

**Cost correction worth carrying forward:** #831 budgets the replicate at
~$0.42. That predates slice 05. Draw A's own manifest puts a full forced
replicate at **~$2.50 and ~7.5 hours**, dominated by consolidation ($1.796,
24,372s).

### Directory handling, and how the variant was restored

`map build --grouping category` writes to `data/map/<pin>-category/` and takes
no output-directory flag; `--force` sets that directory's own ledgers aside and
rewrites its artifacts in place. So the paid draw A was copied out before
launch, and after the kill the directory was put back:

- the partial replicate ledger moved to this log directory,
- draw A's own `reads.jsonl` moved back from its timestamped sibling,
- the stale `RUNNING.pid` removed,
- **all five artifacts verified byte-identical (md5) to the pre-launch copy**,
  which was then dropped.

`--force` never destroyed a paid ledger, as its help text promises.

## D5 not run

D5 is a veto: it can sink a pass, never rescue a failure. With D2 and D4 both
failing, a blind 24-position hand-sample cannot change the verdict, so it was
not run. It would still answer a *different* question worth asking — whether
the variant's much larger cross-book positions read as one argument to a human
— and that is available on request as input to whatever replaces slices 07–09.

## Operational notes

- `map compare` needs `sentence-transformers` for D3, which lives in the
  `distill` group. A fresh worktree venv from a plain `uv sync` does not have
  it and the command dies `ModuleNotFoundError`. `uv sync --group distill`.
- The ambient `AXIAL_SECRETS_PATH` on this box is the container path
  `/secrets/secrets.toml`; every model call fails without
  `AXIAL_SECRETS_PATH=secrets/secrets.toml`.
- One extraction call burned a 600s deadline and retried cleanly during the
  replicate — not a defect, recorded because it is the only error in the run.

## The report as printed

The whole report, verbatim and complete, because `compare.txt` is gitignored
and this log is the only committed copy. This is the 2026-08-30 re-run after
the review of PR #846; the same text is the slice's CLI evidence at
`docs/tdd-evidence/positions-not-names/06-structural-comparison/cli-demo.txt`.

```
axial map compare -- A is the baseline (the default build), B is the variant
seed 831, 20 permutation trial(s) per null; vocabulary D:\axial\data\vocabulary

IDENTITY (a field absent on one side is reported, never a mismatch -- a bag-grouped build records no grouping block at all)
  field                       A                                   B
  path                        D:\axial\data\map\9b796b3a6312b329  D:\axial\data\map\9b796b3a6312b329-category
  corpus pin                  9b796b3a6312b329                    9b796b3a6312b329
  answers pin                 not recorded                        not recorded
  grouping mode               not recorded                        category
  scheme version `claim`      not recorded                        2026-08-28-claim-v1
  scheme version `mechanism`  not recorded                        2026-08-28-mechanism-v1
  vocabulary columns on disk (one value each, not a per-build field): `claim` 2026-08-28-claim-v1 | `position` 2026-08-29-position-v1
  verified equal: corpus pin (A, B); `claim` scheme version (B, the column on disk)
  not verifiable on this pair: answers pin (recorded by neither build); `mechanism` scheme version (recorded by B only); `position` scheme version (recorded by the column on disk only)
  the refusal above fires on a build-versus-build disagreement only; a field only one side records is disclosed here and does not refuse

D1 BOOK-SPREAD RATIO, SIZE-MATCHED (mean distinct source_id per position, over the same figure under a seeded permutation of that build's own placed pool into positions of identical sizes)
  build  band  positions  slots  passages  observed  null   null spread      ratio  cross-book  cross-book null
  A      2     397        794    783       1.16      1.96   1.9421-1.9748    0.59   16.1%       95.9%
  A      3-5   519        1923   1842      1.31      3.51   3.4740-3.5356    0.37   24.1%       99.9%
  A      6-10  192        1397   1355      1.56      6.44   6.3594-6.5573    0.24   39.1%       100.0%
  A      11+   66         1110   1078      1.77      12.31  12.0606-12.5455  0.14   39.4%       100.0%
  B      2     256        512    512       1.29      1.96   1.9375-1.9805    0.66   28.9%       96.5%
  B      3-5   260        968    968       1.72      3.52   3.4615-3.5538    0.49   47.7%       99.9%
  B      6-10  117        877    875       2.54      6.64   6.4957-6.7436    0.38   70.1%       100.0%
  B      11+   128        2713   2694      5.10      14.24  14.0703-14.3828  0.36   89.1%       100.0%
  plurality band on B: 11+ -- the band holding the most DISTINCT placed passages, which is issue #831's own denominator. Positions overlap, so a passage can sit in two bands and the passage column does not partition; the slot column does
  null spread is the min-max of the 20 per-trial estimates behind each null mean, not a confidence interval

D2 HELD-OUT `position`-AXIS PURITY, SIZE-MATCHED (the modal `position` category's share of a position's CATEGORISED members; the axis is built and never grouped on)
  build  scored  excluded (<2 categorised)  of which 0 categorised  member-weighted  null    null spread    lift   per-position mean
  A      1121    816                        95                      0.7597           0.4041  0.3932-0.4108  1.880  0.7804
  B      717     516                        75                      0.6620           0.3459  0.3425-0.3526  1.914  0.7079
  categorised base A: 5549 of 6010 selected (92.3%) -- counted over this build's own group state of 6010 chunk id(s), 0 selected passage(s) outside it
  categorised base A: 5257 of 5596 placed (93.9%)
  categorised base B: 5537 of 6010 selected (92.1%) -- counted over this build's own group state of 5993 chunk id(s), 17 selected passage(s) outside it
  categorised base B: 5174 of 5497 placed (94.1%)
  assignment-instability floor: 0.0331 purity points, 0.0294 on the per-position mean, 0.068 on lift (one measurement, 2026-08-29, over two model draws of the `position` column, on each of the three scales this table prints)
  B - A on each scale, against that scale's own floor: member-weighted -0.0977 against 0.0331 (outside the floor) | per-position mean -0.0726 against 0.0294 (outside the floor) | lift +0.034 against 0.068 (inside the floor)
  a difference inside its own floor is not readable at this sample, whichever way it points
  `position` coverage per book for THIS DRAW (D:\axial\data\vocabulary), over the passages either build placed -- worst first, and a property of this draw, never of the corpus: which books a draw refuses on does not reproduce across models (#838)
    vignal-2021-c7005c2bf8ef: 70 of 121 (57.9%)
    batatu-1999-598624067df3: 113 of 187 (60.4%)
    tilly-1978-f908c910464c: 97 of 154 (63.0%)
    beshara-2011-8410a9059300: 191 of 226 (84.5%)
    heydemann-2004-72a4a9a9b3b0: 139 of 158 (88.0%)
    kao-2025-ab19e646ab7d: 98 of 109 (89.9%)
    wimmer-2013-a67941b77943: 134 of 148 (90.5%)
    chouliaraki-2024-91e7fc84f05c: 69 of 76 (90.8%)
    hinnebusch-1990-ac29981e616e: 200 of 218 (91.7%)
    ungor-2020-ae5701dcc706: 79 of 86 (91.9%)
    malesevic-2007-323a2518e61b: 136 of 146 (93.2%)
    mann-v4-2013-1b7e828e0199: 277 of 290 (95.5%)
    smith-2009-cba7b6f3dfba: 68 of 71 (95.8%)
    gelvin-1998-f7e1df5f9b1d: 168 of 174 (96.6%)
    gould-2003-abae3539cf15: 89 of 92 (96.7%)
    malesevic-2013-5d3ec1809b12: 203 of 209 (97.1%)
    white-2011-5f35a47d9657: 102 of 105 (97.1%)
    ayubi-1995-16fd6a2e503f: 294 of 302 (97.4%)
    gellner-1981-a8b0206cb566: 229 of 234 (97.9%)
    hall-2006-449559bfe4dc: 207 of 211 (98.1%)
    kalyvas-2006-0b5817b2642e: 264 of 269 (98.1%)
    wedeen-2019-3ae1f7af318d: 125 of 127 (98.4%)
    bayat-2017-ce6bb0643cfb: 112 of 113 (99.1%)
    elcheroth-2017-78f0cccef5b9: 112 of 113 (99.1%)
    mann-v1-2012-5f90ead66c93: 341 of 343 (99.4%)
    agamben-2005-b22edc40e0fc: 48 of 48 (100.0%)
    caspersen-2012-fbc0efe4fffc: 92 of 92 (100.0%)
    heydemann-2000-66701ffbb36c: 175 of 175 (100.0%)
    jackson-1990-7eb3f39a639f: 116 of 116 (100.0%)
    kandiah-2018-454c87b22e16: 27 of 27 (100.0%)
    malesevic-2010-fd2cbe41384f: 185 of 185 (100.0%)
    malesevic-2026-4faeb528594d: 17 of 17 (100.0%)
    mann-v2-1993-ec759675dcbd: 448 of 448 (100.0%)
    mann-v3-2012-3e9f48ff605a: 315 of 315 (100.0%)
    zaum-2007-834d3343aa95: 106 of 106 (100.0%)

D3 MEMBER COHERENCE (mean cosine of members' `claim` texts to their position's own centroid, sentence-transformers/all-MiniLM-L6-v2; the floor is the midpoint of A's own band value and A's own band null)
  build  band  positions scored  observed  null    null spread    floor   margin
  A      2     397               0.9019    0.7855  0.7828-0.7888  0.8437  0.0582
  A      3-5   519               0.8495    0.6710  0.6684-0.6734  0.7603  0.0892
  A      6-10  192               0.8156    0.5878  0.5850-0.5910  0.7017  0.1139
  A      11+   66                0.7913    0.5374  0.5340-0.5418  0.6643  0.1269
  B      2     256               0.8738    0.7865  0.7813-0.7928  0.8437  0.0301
  B      3-5   260               0.7911    0.6707  0.6675-0.6754  0.7603  0.0308
  B      6-10  117               0.7253    0.5844  0.5806-0.5886  0.7017  0.0236
  B      11+   128               0.6692    0.5306  0.5284-0.5335  0.6643  0.0048
  the floor is half an estimate: it moves with the baseline's own null, whose per-trial spread is in the column beside it. A margin inside that spread is reported as not resolved, never as passed
  the top band is open-ended: A's largest position holds 48 member slot(s) over 66 position(s), mean 16.8; B's holds 79 over 128, mean 21.2. B is scored in 11+ against a floor set by A's systematically smaller positions, and coherence falls with size in both builds -- the direction is conservative against B
  members with no `claim` text (missing, never scored 0): A 0 | B 0

D4 PASSAGES REACHING NO POSITION (passages_selected minus the DISTINCT chunk ids in positions.jsonl -- never a sum of position sizes, which double-counts a passage sitting in two positions)
  A: 6010 selected, 5596 distinct placed, 414 unplaced = 6.9% of selected (member slots 5987, which is not a passage count)
     of which, at least: declined by the extraction model 373, shown in a failed read 35, reaching no group at all not recorded
        408 attributed of 414, 6 not attributed -- the three counts are not guaranteed disjoint, so each is a lower bound and the remainder is a residual, not a fourth cause
  B: 6010 selected, 5497 distinct placed, 513 unplaced = 8.5% of selected (member slots 5542, which is not a passage count)
     of which, at least: declined by the extraction model 457, shown in a failed read 31, reaching no group at all 17
        505 attributed of 513, 8 not attributed -- the three counts are not guaranteed disjoint, so each is a lower bound and the remainder is a residual, not a fourth cause

D5 BLIND PAIRED HAND-SAMPLE
  not computed -- D5 is a human hand-sample: 12 positions from each build, stratified to the same size bands, shuffled, judged before the labels are revealed

CONTEXT (reported, never deciding -- fewer positions, larger positions and a lower single-passage share follow from the extraction call count, not from quality)
  A: 1937 position(s) | size p25/median/p75 1.0 / 2.0 / 4.0 | 5987 member slot(s) over 5596 distinct placed passage(s)
     single-passage: 763 = 39.4% of 1937 position(s), 12.7% of 5987 member slot(s)
     cross-book: 24.7% of 1174 position(s) of size 2+, 27.4% of 5987 member slot(s), 28.3% of 5596 distinct placed passage(s) -- band by band against its own null in D1's table above
     reads 679 | units asked 0 | units reused 679 | cost not recorded | wall 157.2s
     embedding merge: 269 fold(s) (derived: raw 2206 - merged 1937), 0.139 per final position
     consolidation: no consolidation stage in this build
  B: 1233 position(s) | size p25/median/p75 1.0 / 2.0 / 4.0 | 5542 member slot(s) over 5497 distinct placed passage(s)
     single-passage: 472 = 38.3% of 1233 position(s), 8.5% of 5542 member slot(s)
     cross-book: 51.8% of 761 position(s) of size 2+, 66.3% of 5542 member slot(s), 66.3% of 5497 distinct placed passage(s) -- band by band against its own null in D1's table above
     reads 226 | units asked 0 | units reused 226 | cost $0.7052 | wall 26917.3s
     embedding merge: 82 fold(s), 0.067 per final position
     consolidation: 721 fold(s), 0.548 per final position (never added to the embedding merge's own -- two stages, two figures)

NOISE (reporting only, per the approach doc's §6 noise policy)
  `claim` assignment disagreement ~23% at n=100 (#826)
  `position` two-model agreement 73.8% where assigned (n=84), 70.0% overall (#838)
  `position` full-column label agreement 73.0% where both draws assigned, n=5,581 (#831)

REPLICATE
  not supplied -- the D1 and D2 replicate gaps were NOT measured, and no margin below is quoted against one

VERDICT (the bar is issue #831's own)
  D1: not resolved at this sample -- clears 2x the baseline in band 11+ and falls in no band, but the replicate gap was not measured
  D2: failed -- 0.6620 is 0.0977 BELOW the baseline's 0.7597 -- issue #831's failure condition 2, and the wrong direction, not a small margin
  D3: not resolved at this sample -- at or above the floor in every band (2 0.8738 - 0.8437 = +0.0301; 3-5 0.7911 - 0.7603 = +0.0308; 6-10 0.7253 - 0.7017 = +0.0236; 11+ 0.6692 - 0.6643 = +0.0048), but 11+ margin 0.0048 is inside that band's own null spread 0.0078
  D4: failed -- 8.5% of selected rises above the baseline's 6.9%
  D5: not computed -- a blind paired hand-sample: 12 positions per build, size-stratified, shuffled, judged before the labels are revealed
  overall: no-go on slices 07-09
```

## Known limitation of the instrument, recorded rather than fixed

The reviewer on PR #846 found that D2's permutation null is **size-matched but
not population-matched**. The observed reading scores positions with at least
two categorised members; the null re-tests that condition on each drawn
position independently. Permuting redistributes uncategorised members, so the
set of positions that qualify under the null is not the set scored observed,
and since purity falls with group size, that shift moves the null. Every lift
figure in this report inherits it — including the 1.914 against 1.880 that the
D2 discussion above turns on.

Matching the population would fix it and would change every lift printed here.
The founder shelved this direction on 2026-08-30 after the no-go, so it is
recorded here and in `compare.py`'s docstring rather than fixed: the correction
would move numbers nobody is going to read. **Do not quote a lift from this
report as a settled figure without doing it first.** The verdict does not rest
on it — D2 fails on member-weighted purity and on the per-position mean, both
outside their own floors, and D4 fails on arithmetic with no null at all.
