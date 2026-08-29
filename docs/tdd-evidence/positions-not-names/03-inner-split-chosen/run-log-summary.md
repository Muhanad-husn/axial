# Inner-split choice — #828, slice 03

**Run date:** 2026-08-29 · **Pin:** `9b796b3a6312b329` · **Model calls:** 0 · **Cost:** $0
**Code:** branch `feat/positions-not-names/03-inner-split-chosen`, merged to `main` as
`1f1ab37` (PR #843). The tables below were produced at `ca907bf`, the branch's final
commit; run from the worktree `D:/axial-wt/828-inner-split` against `D:/axial/data`
via `--map-dir` / `--vocabulary-dir`.

**Copy of** `data/logs/2026-08-28-inner-split-choice/summary.md`, which is gitignored.
The live run log there stays the source; this copy is committed because the founder's
choice of inner split is a decision the repo has to carry.

## Commands

```
uv run axial map grouping-report --map-dir D:/axial/data/map --vocabulary-dir D:/axial/data/vocabulary
uv run python docs/tdd-evidence/positions-not-names/03-inner-split-chosen/sweep.py
```

Raw output: `console.log`, `threshold-sweep.log`.

## The two candidates

Universe: 6,010 selected passages at the pin. `claim` level 1, `mechanism` level 1.

| | claim × mechanism | claim + subcluster |
|---|---|---|
| groups | 167 | 1,181 |
| group size min / median / max | 1 / 15.00 / 248 | 1 / 2.00 / 139 |
| ungrouped | 797 | 17 |
| projected extraction slices (EXTRACT_SLICE=55) | 207 | 1,190 |

The intersection arm's 797 ungrouped, per axis: **9** hold no claim category,
**780** hold no mechanism category, **8** hold neither. So 788 of the 797 have a
claim category and could fall back to a claim-only cell; 9 could not.

## The confound, closed

The subcluster arm's inner distance threshold is `BAG_DISTANCE_THRESHOLD = 0.55`,
inherited from corpus-wide bagging and never chosen for splitting *inside* a
category. Swept before reading the comparison:

| threshold | groups | min / median / max | ungrouped | slices |
|---|---|---|---|---|
| 0.50 | 1,734 | 1 / 2.00 / 110 | 17 | 1,737 |
| 0.55 (inherited) | 1,181 | 1 / 2.00 / 139 | 17 | 1,190 |
| 0.60 | 785 | 1 / 3.00 / 225 | 17 | 806 |
| 0.70 | 250 | 1 / 5.00 / 484 | 17 | 311 |
| 0.80 | 53 | 1 / 4.00 / 1,577 | 17 | 151 |
| 0.90 | 11 | 1 / 441.00 / 1,648 | 17 | 115 |

There is no threshold at which the subcluster arm produces balanced groups. It
goes from fragmented (median 2–5, hundreds to thousands of groups) to blob
(max 1,577 at 0.80, 1,648 at 0.90) with nothing in between. At its best sweep
point, 0.70, the median group is still 5 and the largest is 484 passages — nine
extraction slices in one group. The claim × mechanism shape (167 groups, median
15, max 248) is not reachable by retuning the subcluster. The comparison is not
a threshold artifact.

This reproduces the shape already measured on the category work: every failure
is the blob condition, never missing structure, and granularity is unstable.

## What each costs

**claim × mechanism.** 207 extraction slices against the subcluster's 1,190 at
the inherited threshold — 5.7x cheaper — and a median group of 15 sits close to
today's mean bag of 9, so most cells fit one slice and "what recurs here" stays
one call. The largest cell is 248 passages, five slices, which is exactly the
case §6's two-pass consolidation (slice 05) exists to reunite. Price: **797
passages, 13.3% of the universe, fall out** — the compounded refusal rate §6
predicted, `mechanism` assigning 5,315 of 5,871 answered corpus-wide against
`claim`'s 6,671 of 6,697. The loss is overwhelmingly mechanism-side: 780 of the
797 are missing only that axis, 9 only the claim axis, 8 both. Those passages
are not destroyed; whether slice 04 falls the 788 that still hold a claim
category back to a claim-only cell is slice 04's decision, not this one.

**claim + subcluster.** Loses almost nothing (17 passages) but reinstates the
pathology the feature exists to remove: a median group of 2 is the median
position the current wording-bagged map already produces, and wording
similarity would be back deciding who meets whom, one level down.

## Recommendation

**claim × mechanism.** It is the only candidate that produces readable,
balanced groups at all, it costs 5.7x less to extract, and its 13.3% coverage
loss is a stated, quotable price rather than a structural defect.

## Founder's choice

**claim × mechanism**, chosen by the founder 2026-08-29 on the numbers above.
Slice 04 builds only that variant; the subcluster function stays in
`grouping.py` as the measured alternative, unwired.

## Next steps

1. ~~Founder chooses the inner split~~ — done, claim × mechanism.
2. Slice 04 (#829) wires claim × mechanism into `map build`, and decides
   what happens to the 797 passages that hold no mechanism category.
3. `safe-pr` on `feat/positions-not-names/03-inner-split-chosen`, CI green, founder merges.

## Review, and the fix pass

A reviewer and a verifier read the branch from staged packets after the first
run. Both returned DONE_WITH_CONCERNS; six findings were fixed in `e55df01` and
the report re-run over the same pin. **No number in the tables above moved** —
the fixes changed what the readout discloses, not what it computes.

What the first version of this log got wrong, and now states correctly: it
attributed all 797 ungrouped passages to a missing mechanism category. The
report had never measured per axis. It does now, and the true split is
9 / 780 / 8. The sentence handed slice 04 a fallback population of 797 where the
real one is 788.

The other five: the subcluster arm's inner distance threshold is now printed in
the header (it was invisible, and it is the parameter the whole right-hand
column turns on — see the sweep above); the slices row names `EXTRACT_SLICE`
rather than showing a bare `(55)`; the unreachable `NOISE_LABEL` branch is
deleted, so the subcluster arm's ungrouped count is exactly "no claim category"
and never encoder residue; the docstrings no longer claim "zero network" (zero
model calls and $0 are true, but the local encoder loads for the subcluster arm,
which is what prints the HF-hub warning above every run); and `sweep.py` is now
committed under `docs/tdd-evidence/positions-not-names/03-inner-split-chosen/`,
since its result is load-bearing in the decision and it was reproducible from
nothing in the repo.
