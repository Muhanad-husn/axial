# The consolidation pass over the category-grouped variant

Issue [#830](https://github.com/Muhanad-husn/axial/issues/830), slice 05 of
positions-not-names. Branch `feat/positions-not-names/05-category-consolidation`.

## Command

```
# from D:/axial, with the branch's code and the branch's config
D:/axial-wt/830-consolidation/.venv/Scripts/python.exe scratchpad/run_consolidation_pass.py
# which calls run_map_build(config_path=<branch>/config/pipeline.yaml,
#                           grouping=GROUPING_CATEGORY)
```

The branch's venv installs `axial` editable against the worktree's `src/`, so
running it with cwd `D:/axial` gets the branch's code over the main checkout's
`data/`. `map build` exposes no `--config` flag, and only the branch config
carries the `position_consolidate` pass entry, so it is passed through
`run_map_build`'s own `config_path` seam rather than by editing either tree.
The run asserts both facts before making a call.

Started 2026-08-29 15:44:14Z, finished 18:14:06Z. Wall 8,992s (2h30m), of
which the consolidation stage is 8,950s. Extraction resumed all 226 reads from
slice 04's ledger and spent nothing.

## What it cost

| stage | calls | prompt tok | completion tok | cost |
|---|---|---|---|---|
| extraction (resumed, paid 2026-08-29) | 226 | — | — | $0.7052 |
| consolidation | 188 | 400,392 | 2,435,076 | **$0.7379** |

$1.44 for the variant end to end. Consolidation ran 3x my $0.25 pre-run
estimate: the estimate priced a consolidation call at extraction's measured
$0.0031, and the real figure is $0.0039 — but the pass made 188 calls rather
than the 79 the r=0.5 row of the projection assumed, because the model folds
far less per round than that row supposed (see retention below).

**Output-bound, and heavily.** 2.4M completion tokens against 400k prompt —
12,952 completion tokens per call at `reasoning: high`. That, plus rounds
being strictly sequential and the last rounds only 4-11 calls wide, is why
2h30m buys 188 calls at 40 workers.

## Result

2,036 raw positions -> **1,093 consolidated** -> **1,024 merged**.

| | default build | variant (category + consolidation) |
|---|---|---|
| raw positions | 2,206 | 2,036 |
| final positions | 1,937 | 1,024 |
| reunification folds | 269 (embedding) | 943 (consolidation) + 69 (embedding) |
| positions carrying >1 naming | 207 | 282 (consolidation) + 61 (embedding) |
| folds per final position | 0.139 | **0.863** (consolidation), 0.067 (embedding) |
| distinct passages placed | 5,596 | 5,497 |
| median / max position size | 2 / 48 | 2 / 163 |
| singleton positions | 763 | 435 |

Judgment reunites 6.2x what wording distance did, measured the same way. The
cross-category embedding merge, now the only thing that fold is left to do,
accounts for 69 of the 1,012 folds — the restriction did not cost the merge
its original job.

`sum(consolidated_from)` over the final map is **2,036 exactly**, against 2,036
raw positions. The overcounting path the pre-run review found (a handle claimed
by two entries) is closed, and the corpus confirms it rather than a fixture.

## Convergence: 3 of 9 categories, and the six that stopped hold the material

A category is read again until one call reads everything it has left. Six never
got there and stopped at the round cap.

| category | calls | trajectory | outcome |
|---|---|---|---|
| state-formation-or-power | 55 | 480→422→380→316→277→255→247→228→211→187 | round_cap (9) |
| empirical-finding | 51 | 437→376→347→323→300→293→284→272→253 | round_cap (8) |
| violence-war-or-conflict | 25 | 287→244→200→179→164→147→135 | round_cap (6) |
| characterization-of-regime | 27 | 281→245→220→210→195→184→176 | round_cap (6) |
| critique-of-theories | 13 | 197→162→141→137→123 | round_cap (4) |
| nationalism-or-identity | 8 | 158→114→108→91 | round_cap (3) |
| methodological-preconditions | 5 | 98→72→55→51 | **converged** (3) |
| comparative-or-typological | 3 | 70→54→52 | **converged** (2) |
| bibliographic-source-note | 1 | 28→25 | **converged** (1) |

The three that converged are the three smallest. The six that did not hold
~1,700 of the 2,036 raw positions, so **most of the map's material still ends
in a state where its category was never read in a single call** — and the
embedding merge is now forbidden from folding inside a category, so nothing
else will reunite what those rounds missed. This is the residue the pass
reports rather than hides (`categories_stopped_at_round_cap: 6`), and it is
the thing slice 06 will be judging a partly-reunited map on.

**Measured retention is 0.87-0.96 per round, not the 0.5-0.6 the fixed point
was ordered on.** Per-round folding also decays inside a category
(state-formation: 0.88 in round 1, 0.96 by round 6), which is what approaching
a real number of distinct arguments looks like rather than a pass grinding at
random — but it is also exactly why the cap binds.

## Faults

3 consolidation calls failed and were recorded as errors; their raw positions
passed through unchanged, losing nothing. 4 handles were dropped (invented by
the model, or claimed by a second entry). Extraction's own 2 failed reads and
457 declined passages are slice 04's, unchanged by this run.

## The extraction cost in this manifest was restored by hand

`cost_usd: 0.7052` and the 2,466s
it accumulates from were typed back into the manifest before this run, because
a free resume had already overwritten them with `null`/34.4s — the defect this
slice fixes. They are restored, not measured here. `usage` for the extraction
stage stays `null`: the token totals were never recorded anywhere.

The accumulation itself works: the post-run manifest reports `runs: 2` and
`cost_usd: 0.7052` for extraction (this run spent nothing on it) with
consolidation's `$0.7379` nested separately at `runs: 1`.

Their only source is `data/logs/2026-08-28-reformed-map-build/summary.md` and
PR #844. The pre-patch manifest is kept beside this file as
`map.json.before-cost-patch`, which `.gitignore` keeps out of the repo along
with `console.log`; both stay on the box.

**Anything reading extraction's cost off the post-run manifest is reading a
$0.7052 that was typed in.**

## A second pass over the finished folds does not improve them (negative result)

2026-08-30. The blind audit of the built map found folded positions whose
standing sentence states something not every member asserts, and folds holding
arguments that do not share a claim. The obvious cheap fix -- re-read every
fold once against its own members, in one concurrent wave over the finished
map, no rebuild -- was run and **it does not work**.

`repair_map.py` (kept beside this file) put all 341 folded positions in front
of `deepseek-v4-flash` at `reasoning: high`, one call each, 40 at a time: 1,529s
wall, 341 of 341 answered, 0 failed, 1.14M tokens. The prompt was RE_READ_PROMPT's
question without its heading framing, which presumes a group is too large to be
one claim and is false of a two-member fold. Members were redistributed, never
invented or dropped: `sum(consolidated_from)` closes at 2,036 on both sides.

**Taken wholesale it destroys the deliverable.** 309 of the 341 folds were
split, including 143 of the 165 two-member folds shattered into singletons.
Folding falls from 803 to 195 and the map goes 1,233 -> 1,841 positions, which
is a 9.6% reduction on 2,036 raw arguments -- what the map looked like before
consolidation existed. Reading ten of the shattered pairs by hand, three are
plainly one argument (two phrasings of Mann's sociology being exemplary; two
statements that modern bureaucracy was never fully rationalised). A call asked
to verify a merge finds a reason to reject it.

**Taken selectively it changes nothing measurable.** Keeping the original
wherever the repair returned every member in its own group -- a call that
declines to group has not found a better grouping -- and accepting the 103 real
regroupings gives 1,424 positions and 612 folds. 36 folded groups, 18 from each
map, shuffled and judged blind against their own members before the labels were
revealed:

| map | sound | mixed | wrong |
|---|---|---|---|
| before the repair | 7 | 6 | 5 |
| after the repair | 8 | 4 | 6 |

Nothing moves. One group drawn into both samples (a legitimacy-crisis fold the
repair left alone) was judged wrong on both sides, so the two columns are at
least reading the same way.

The cost was $1.80 and 25 minutes, and what it buys is the knowledge that the
remaining defect is not reachable by asking the same model the same question a
second time. It is a judgment limit at this model and price, not a missing pass.
`positions.selective.jsonl`, `repair_reads.jsonl`, `audit_items.md` and
`audit_key.json` are under `repair/` on the box; `.gitignore` keeps them there.
