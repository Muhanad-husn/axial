# Derived-vocabulary categorisation, all twelve columns — corrected run

**Run:** 2026-08-27, issue #805 slice 01, branch
`feat/derived-vocabulary/01-the-sentence-columns-are-counted` at `8646788`.
Same command and same samples as `../2026-08-27-vocabulary-categorise/`, re-run
after the reviewer found a silent-failure path in the assign loop. **That run's
logs are kept; this one is written beside them, not over them.**

**Cost:** $0.1028 over 74 model calls. ~20 minutes, twelve processes in
parallel.

## What was wrong with the first run

The assign path could not tell *the model refused this value* from *the model
never answered about it*. Any index missing from a batch response counted as
unassigned. Two failure modes followed, both deflating the assignment rate —
the exact number bar condition 4 turns on:

- a truncated completion loses its tail (these calls produce ~10k completion
  tokens over 170–250s, squarely that regime);
- a model that renumbers a later batch `1..100` instead of `101..200`
  overwrites the first batch through `dict.update`, so those indexes read as
  unassigned too.

The fix validates that a batch answered about the indexes it was asked about
and re-asks when it did not, and reports **unanswered** and **refused**
separately.

**Across all twelve columns of this run, `unanswered` is 0 and `refused` is
303.** Every value now either lands in a category or is a recorded refusal.

## Per column, with the first run's coverage beside it

| column | categories | 5+ | cross-book | assigned | first run | largest | agreement (n) | bar |
|---|---|---|---|---|---|---|---|---|
| claim | 10 | 9 | 9 | 99.5% | 75.0% | 21.2% | 77.0% (100) | **passes** |
| evidence | 10 | 10 | 10 | 99.2% | 87.5% | 22.2% | 82.0% (100) | **passes** |
| about | 10 | 10 | 10 | 98.0% | 94.0% | 19.8% | 81.9% (94) | **passes** |
| move | 13 | 13 | 13 | 97.5% | 97.5% | 15.2% | 72.0% (100) | **passes** |
| position | 15 | 15 | 15 | 89.8% | 98.5% | 11.5% | 71.1% (90) | **passes** |
| mechanism | 20 | 20 | 20 | 88.5% | 50.7% | 8.0% | 61.4% (83) | **passes** |
| arguing_against | 9 | 9 | 9 | 68.2% | 71.8% | 22.8% | 61.8% (68) | **passes** |
| assumes | 10 | 10 | 10 | 99.0% | 99.8% | 25.2% | 66.0% (100) | fails c2 |
| comparison | 10 | 8 | 8 | 99.0% | 98.8% | 50.5% | 61.0% (100) | fails c2 |
| concedes | 10 | 10 | 10 | 98.5% | 96.0% | 27.0% | 59.2% (98) | fails c2, c5 |
| stops_holding | 20 | 13 | 13 | 94.0% | 96.0% | 25.5% | 62.2% (90) | fails c2 |
| ranges_over | 7 | 7 | 7 | 93.0% | 95.2% | 32.5% | 87.1% (85) | fails c1, c2 |

**Seven of twelve clear all five conditions**, against six in the first run. The
six that passed before all pass again; `position` joins them. Nothing that
passed before fails now.

## What this run says

**The defect was deflating real coverage, and by a lot.** `mechanism` went
50.7% → **88.5%**, `claim` 75.0% → **99.5%**, `evidence` 87.5% → 99.2%. Those
are far outside the ~7-point run-to-run noise measured on byte-identical input,
so they are not variance — the first run was losing assignments that had been
made. The reviewer predicted the direction of the error exactly.

**The margins that were thin are now comfortable — with two exceptions, named.**
In the first run `mechanism` cleared the coverage floor by 0.7 points; it now
clears it by 38.5. But `arguing_against` clears the agreement floor by **1.8
points at n=68** and `mechanism` by **1.4 points at n=83**, where the standard
error is about 5.5 points. Both are still inside their own noise. Five of the
seven passes clear every condition with real margin; those two do not, on that
one condition.

**Every category reaching five members still crosses books. Twelve columns of
twelve, both runs, no exceptions.** This is the most stable result in the whole
exercise and it is the property the feature exists for.

**Every failure is still the blob condition.** `comparison` at 50.5% is the only
bad one; `assumes` (25.2%), `stops_holding` (25.5%) and `concedes` (27.0%) miss
by one to two points. Nothing fails for lack of structure.

**Granularity remains the dominant source of variance, and it cuts both ways.**
Same prompt, same model, same corpus, two runs: `position` 5 → 15 categories,
`stops_holding` 7 → 20, `mechanism` 36 → 20, `move` 16 → 13. `position` passes
now *because* its scheme came out finer — its largest category fell from 56.8%
to 11.5%, while its coverage dropped 8.7 points. That trade is the thing slice
02 has to control. It is not a defect in this instrument; it is what the
instrument measured.

## Caveats

- 400 + 400 per column against populations of 2,718 to 20,334 — estimates with
  a sampling error, not census figures.
- The proposing model does the bulk assignment; the second model checks a
  100-value subsample. `agreement where assigned` is the honest number and its
  `n` is in the table.
- Nothing is persisted. These schemes exist only in this log directory.
