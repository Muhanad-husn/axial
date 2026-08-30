# 2026-08-30 — the structural comparison, and the killed replicate (#831, slice 06)

**Verdict: no-go on slices 07–09.** Two of the five deciding metrics fail
against issue #831's own bar, and both are named failure conditions there
(2 and 4). Full report: `compare.txt`, reproduced byte-identically on two runs.

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
| **D3** member coherence | at or above the A/null midpoint in every band; 11+ reads 0.6692 against the 0.6643 floor | **passed**, thinly |
| **D4** passages reaching no position | **513 of 6,010 = 8.5%** (457 declined by the extraction model, 31 in failed reads, 17 ungrouped) | **failed** — above the 6.9% ceiling (414 of 6,010) |
| **D5** blind paired hand-sample | not run | see "D5 not run" below |

The instrument validates against the figure it was built to reproduce: D2 on
the default build reads **0.7597**, exactly #831's measured baseline.

## D2 is not size-matched the way D1 is — flagged, not decided

The bar compares raw member-weighted purity across two builds whose position
sizes differ by a lot: band 11+ holds **2,713 of B's 5,542 member slots**
against **1,110 of A's 5,987**. Purity falls with group size mechanically, and
#831 says so itself. Against its **own** size-matched null the variant reads
**lift 1.914 against the baseline's 1.880** — marginally better, not worse.

D1 was deliberately built as a ratio for exactly this reason ("invariant to how
large the variant's positions turn out to be, which is the confound that sinks
the raw cross-book rate"). D2 was not given the same treatment. On the bar as
written D2 fails; on D1's own logic applied to D2 it does not. `map compare`
prints both readings and applies the bar as written. Whether the bar should be
re-cut is the founder's call, not the command's.

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

Reproduced verbatim below because `compare.txt` is a raw report and stays
gitignored; these numbers are the evidence.

```
D1 BOOK-SPREAD RATIO, SIZE-MATCHED (mean distinct source_id per position, over the same figure under a seeded permutation of that build's own placed pool into positions of identical sizes)
  build  band  positions  slots  observed  null   ratio  cross-book  cross-book null
  A      2     397        794    1.16      1.96   0.59   16.1%       95.9%
  A      3-5   519        1923   1.31      3.51   0.37   24.1%       99.9%
  A      6-10  192        1397   1.56      6.44   0.24   39.1%       100.0%
  A      11+   66         1110   1.77      12.31  0.14   39.4%       100.0%
  B      2     256        512    1.29      1.96   0.66   28.9%       96.5%
  B      3-5   260        968    1.72      3.52   0.49   47.7%       99.9%
  B      6-10  117        877    2.54      6.64   0.38   70.1%       100.0%
  B      11+   128        2713   5.10      14.24  0.36   89.1%       100.0%
  plurality band on B (the band holding the most member slots): 11+

D2 HELD-OUT `position`-AXIS PURITY, SIZE-MATCHED (the modal `position` category's share of a position's CATEGORISED members; the axis is built and never grouped on)
  build  scored  excluded (<2 categorised)  of which 0 categorised  member-weighted  null    lift   per-position mean
  A      1121    816                        95                      0.7597           0.4041  1.880  0.7804
  B      717     516                        75                      0.6620           0.3459  1.914  0.7079
  categorised base A: 5549 of 6010 selected (92.3%) -- counted over this build's own group state of 6010 chunk id(s), 0 selected passage(s) outside it
  categorised base A: 5257 of 5596 placed (93.9%)
  categorised base B: 5537 of 6010 selected (92.1%) -- counted over this build's own group state of 5993 chunk id(s), 17 selected passage(s) outside it
  categorised base B: 5174 of 5497 placed (94.1%)
  assignment-instability floor: 0.0331 purity points (measured 2026-08-29 over two model draws of the `position` column)

D3 MEMBER COHERENCE (mean cosine of members' `claim` texts to their position's own centroid, sentence-transformers/all-MiniLM-L6-v2; the floor is the midpoint of A's own band value and A's own band null)
  build  band  positions scored  observed  null    floor
  A      2     397               0.9019    0.7855  0.8437
  A      3-5   519               0.8495    0.6710  0.7603
  A      6-10  192               0.8156    0.5878  0.7017
  A      11+   66                0.7913    0.5374  0.6643
  B      2     256               0.8738    0.7865  0.8437
  B      3-5   260               0.7911    0.6707  0.7603
  B      6-10  117               0.7253    0.5844  0.7017
  B      11+   128               0.6692    0.5306  0.6643
  members with no `claim` text (missing, never scored 0): A 0 | B 0

D4 PASSAGES REACHING NO POSITION (passages_selected minus the DISTINCT chunk ids in positions.jsonl -- never a sum of position sizes, which double-counts a passage sitting in two positions)
  A: 6010 selected, 5596 distinct placed, 414 unplaced = 6.9% of selected (member slots 5987, which is not a passage count)
     of which: declined by the extraction model 373, shown in a failed read 35, reaching no group at all not recorded
  B: 6010 selected, 5497 distinct placed, 513 unplaced = 8.5% of selected (member slots 5542, which is not a passage count)
     of which: declined by the extraction model 457, shown in a failed read 31, reaching no group at all 17

CONTEXT (reported, never deciding -- fewer positions, larger positions and a lower single-passage share follow from the extraction call count, not from quality)
  A: 1937 position(s) | size p25/median/p75 1.0 / 2.0 / 4.0 | 5987 member slot(s) over 5596 distinct placed passage(s)
     single-passage: 763 = 39.4% of 1937 position(s), 12.7% of 5987 member slot(s)
     cross-book: 24.7% of 1174 position(s) of size 2+, 27.4% of 5987 member slot(s), 28.3% of 5596 distinct placed passage(s) -- band by band against its own null in D1's table above
     reads 679 | units asked 0 | units reused 679 | cost not recorded | wall 157.2s
     embedding merge: not recorded fold(s), n/a per final position
     consolidation: no consolidation stage in this build
  B: 1233 position(s) | size p25/median/p75 1.0 / 2.0 / 4.0 | 5542 member slot(s) over 5497 distinct placed passage(s)
     single-passage: 472 = 38.3% of 1233 position(s), 8.5% of 5542 member slot(s)
     cross-book: 51.8% of 761 position(s) of size 2+, 66.3% of 5542 member slot(s), 66.3% of 5497 distinct placed passage(s) -- band by band against its own null in D1's table above
     reads 226 | units asked 0 | units reused 226 | cost $0.7052 | wall 26917.3s
     embedding merge: 82 fold(s), 0.067 per final position
     consolidation: 721 fold(s), 0.548 per final position (never added to the embedding merge's own -- two stages, two figures)

VERDICT (the bar is issue #831's own)
  D1: not resolved at this sample -- clears 2x the baseline in band 11+ and falls in no band, but the replicate gap was not measured
  D2: failed -- 0.6620 clears the baseline's 0.7597 by -0.0977, which does not exceed the 0.0331 assignment-instability floor
  D3: passed -- at or above the baseline/null midpoint in every band
  D4: failed -- 8.5% of selected rises above the baseline's 6.9%
  D5: not computed -- a blind paired hand-sample: 12 positions per build, size-stratified, shuffled, judged before the labels are revealed
  overall: no-go on slices 07-09
```
