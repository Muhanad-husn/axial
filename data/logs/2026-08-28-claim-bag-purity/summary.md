# The bag/vocabulary cross-tab, on `claim` and `mechanism` (issue #827)

**Run:** 2026-08-28, issue #827 (positions-not-names, slice 02), `axial map
purity`. Executed in the worktree `D:/axial-wt/827` on
`feat/positions-not-names/02-bag-purity-crosstab`, pointed at the main
checkout's real artifacts via `--map-dir`/`--vocabulary-dir` since `data/` is
gitignored and does not exist in a worktree. Zero model calls, zero network,
both runs -- a pure join over `data/map/9b796b3a6312b329/bag_state.json` and
`data/vocabulary/<column>/assignments.jsonl`, both already on disk and paid
for by earlier slices (#677's bagging, #806/#826's vocabulary build).

**Updated 2026-08-28, fix round on PR #836** (reviewer + verifier findings):
the command now also reports the scatter table's own population (distinct
from purity's `eligible_bag_count`) and a coverage count for chunks carrying
2+ categories, both printed below; the prose here is corrected per reviewer
F3 (see "Reading the scatter numbers across two different category counts").
The verdict is unchanged.

```
uv run axial map purity --column claim --map-dir D:/axial/data/map --pin 9b796b3a6312b329 --vocabulary-dir D:/axial/data/vocabulary
uv run axial map purity --column mechanism --map-dir D:/axial/data/map --pin 9b796b3a6312b329 --vocabulary-dir D:/axial/data/vocabulary
```

## Kill condition, stated up front (plan's "Operational steps", issue #827)

> if claim-axis median purity is HIGH and scatter LOW -- wording bags already
> respect the claim categories -- the feature stops. Mechanism-axis baseline
> measured 2026-08-28: median purity 0.5, 13.9% pure, scatter median 92 bags.

**Verdict: NOT killed. Confirmed, proceed.** Claim-axis median purity is
0.56. Read against a chance-level floor (below), that is real signal, not
nothing -- but 0.56 is nowhere near "high" under any reading: a bag whose
categorised members split roughly 56/44 between two categories on average is
not a bag that already respects the axis, and only 17.3% of eligible bags
are fully pure. The diagnosis in `docs/approach-positions-not-names.md`
section 2 -- wording similarity does not respect a constitutive axis --
holds on the second axis measured. Nothing here changes the plan for slice
03 onward.

| | claim (9 categories) | mechanism (20 categories, baseline) |
|---|---|---|
| median purity | 0.5578 | 0.5 |
| mean purity | 0.6233 | 0.55 |
| pure bags (purity == 1.0) | 83 / 480 (17.3%) | 59 / 424 (13.9%) |
| median distinct categories/bag | 2.0 | 3.0 |
| scatter min / median / max (bags, raw) | 69 / 141 / 356 | 39 / 91.5 / 181 |
| scatter population (bags with 1+ categorised member) | 650 | 577 |
| overlap (bagged + categorised) | 6,010 | 5,724 |
| overlap chunks with 2+ categories | 0 | 0 |

## Reading the scatter numbers across two different category counts (reviewer F3, corrected)

The first version of this log said claim's scatter was "higher" than
mechanism's because its raw median (141 bags/category) exceeds mechanism's
(92 bags/category baseline; 91.5 exact on this run). **That comparison is
confounded and the earlier wording overstated it.** `claim` has 9 categories,
`mechanism` has 20, over the same ~660 bags and roughly the same pool of
categorised chunks (5,993 vs 5,222) -- fewer categories means each one
necessarily absorbs a larger and more scattered slice of the corpus, which
is arithmetic, not a property of the axis.

Normalised per categorised member, `claim` scatters LESS, not more:

| | claim | mechanism |
|---|---|---|
| aggregate bags-per-member (total scatter bag-slots / total members) | 0.268 | 0.356 |
| mean per-category bags-per-member | 0.328 | 0.410 |
| median per-category bags-per-member | 0.315 | 0.399 |

`claim`'s own scatter, once you divide out the fact that it has fewer,
bigger categories, is about 20-25% lower than `mechanism`'s. This does not
change the verdict -- median purity (0.56) is still the deciding number, and
it is nowhere close to "the bags already respect this axis" -- but the raw
"claim scatters worse" framing in the first version of this log was wrong
and is retracted here.

## A scale for 0.56: the prevalence-weighted chance-level modal share

Purity numbers only mean something next to a baseline for "no signal at
all." The corpus's own category sizes are already unequal (`claim`'s
largest category, `causal-argument-state-formation-or-power`, holds 1,648 of
5,993 categorised, bagged values, 27.5%) -- a bag assembled with NO regard
for topic at all would still look partly "pure" by that skew alone. The
standard way to state that floor is the Herfindahl concentration index over
category prevalence, `H = sum(share_i^2)`: the probability that two
categorised chunks, picked at random from the corpus with no bag structure
whatsoever, land in the same category purely by how common each category
already is.

| | claim | mechanism |
|---|---|---|
| H (chance-level pairwise match probability) | 0.166 | 0.070 |
| observed median purity | 0.558 | 0.500 |
| purity / H (how far above chance) | 3.4x | 7.1x |

Both axes sit well above their own chance floor -- wording similarity is not
capturing *zero* topical signal, which is consistent with bags being formed
from real text rather than noise. But `mechanism`'s purity clears its own,
much lower, chance floor by a wider margin (7.1x) than `claim`'s clears its
higher one (3.4x): `claim`'s 9, coarser categories are easier to land in by
chance, so 0.56 represents LESS above-chance structure than mechanism's 0.50
does, not more. Either reading keeps the same verdict: above chance, far
below pure, and nowhere near the kill condition's "the bags already respect
this axis."

## What the pair table says about the two #826 pairs (raw counts)

Issue #827's added clause: the ranked category-pair table, and the two pairs
#826's verification flagged as ambiguous glosses, reported by name whether
or not they rank. On `claim` (397 multi-category bags, 36 possible pairs,
all 36 observed at least once):

| pair | bags | share of multi-category bags | rank of 36 |
|---|---|---|---|
| causal-argument-state-formation-or-power x causal-argument-violence-war-or-conflict | 112 | 28.2% | 5th |
| characterization-of-regime-movement-or-system x empirical-finding-without-causal-claim | 137 | 34.5% | 3rd |

Both sit in the top quintile of 36 pairs, well above the median rank (18.5)
-- not "inside the spread of every other pair." Per the issue's own reading
guide: this is evidence the two flagged glosses are splitting arguments that
belong together, and a precedence sentence is worth costing out before
slice 04 forms anything from these categories. That is a finding to hand to
the founder, not a decision made here -- #827 measures, the glosses are the
founder's call (issue comment's own scope note), and no scheme edit is made
on this branch. (The fix round adds a `--named-pair` override so this check
is not hardwired to these two claim-scheme ids for a future run against a
different scheme; the default stays these two so the guarantee holds on a
bare run.)

On `mechanism`, neither #826 pair applies -- neither category id exists in
that column's own scheme -- and the command reports that explicitly rather
than silently printing zeros:

```
NAMED PAIRS (#826's verification -- reported whether or not they rank)
  causal-argument-state-formation-or-power x causal-argument-violence-war-or-conflict: not applicable (not both in this column's scheme)
  characterization-of-regime-movement-or-system x empirical-finding-without-causal-claim: not applicable (not both in this column's scheme)
```

## Coverage (never silently dropped)

`claim`: 6,010 bagged chunks, all 6,010 have a `claim` vocabulary record
(0 bag-only); 687 vocabulary-side chunks have no bag (chunks the map's own
selection/bagging step excluded -- abstentions, back matter, argue-nothing
passages -- that the vocabulary build still answered). Of the 6,010-chunk
overlap: 5,993 assigned a category, 17 refused, 0 out-of-scheme, and 0
carrying 2+ categories at once (`claim` is not a list-valued column, so this
is an inert check on this run -- reviewer F4 -- printed anyway so a future
list-valued column cannot silently break the chunk-count assumption purity's
denominator makes).

`mechanism`: 5,724 overlap (286 bag-only, 147 vocabulary-only -- `mechanism`
has its own, larger refusal population per issues #697/#815, 502 of the
overlap refused here against `claim`'s 17; 0 carrying 2+ categories, same
reason).

## Full command output, claim

```
pin: 9b796b3a6312b329 (D:\axial\data\map\9b796b3a6312b329)
column: claim (level 1)
vocabulary: D:\axial\data\vocabulary\claim

COVERAGE
  bag-side chunks: 6010
  vocabulary-side chunks: 6697
  overlap (joinable both sides): 6010
  bag-only (no vocabulary record for this column): 0
  vocabulary-only (no bag): 687
  overlap assigned a category: 5993
  overlap assigned 2+ categories: 0
  overlap refused: 17
  overlap out-of-scheme: 0

PURITY (bags with 2+ categorised members)
  eligible bags: 480
  excluded (fewer than 2 categorised members): 180
  median purity: 0.56
  mean purity: 0.62
  pure bags (purity == 1.0): 83 (17.3%)
  median distinct categories per bag: 2.00
  mean distinct categories per bag: 2.99

CATEGORY SCATTER (over 650 bag(s) holding at least one categorised member)
  min/median/max bags per populated category: 69 / 141.00 / 356
    empirical-finding-without-causal-claim: 356 bag(s), 1131 member(s)
    causal-argument-state-formation-or-power: 309 bag(s), 1648 member(s)
    characterization-of-regime-movement-or-system: 214 bag(s), 755 member(s)
    causal-argument-violence-war-or-conflict: 187 bag(s), 906 member(s)
    critique-of-existing-theories-or-concepts: 141 bag(s), 441 member(s)
    methodological-preconditions: 128 bag(s), 269 member(s)
    causal-argument-nationalism-or-identity: 112 bag(s), 511 member(s)
    comparative-or-typological-classification: 87 bag(s), 157 member(s)
    bibliographic-source-note-or-formal-description: 69 bag(s), 175 member(s)

CATEGORY PAIR CO-OCCURRENCE (397 multi-category bag(s))
  1. causal-argument-state-formation-or-power x empirical-finding-without-causal-claim: 178 bag(s) (44.8%)
  2. causal-argument-state-formation-or-power x characterization-of-regime-movement-or-system: 146 bag(s) (36.8%)
  3. characterization-of-regime-movement-or-system x empirical-finding-without-causal-claim: 137 bag(s) (34.5%)
  4. causal-argument-violence-war-or-conflict x empirical-finding-without-causal-claim: 120 bag(s) (30.2%)
  5. causal-argument-state-formation-or-power x causal-argument-violence-war-or-conflict: 112 bag(s) (28.2%)
  6. critique-of-existing-theories-or-concepts x empirical-finding-without-causal-claim: 89 bag(s) (22.4%)
  7. causal-argument-state-formation-or-power x critique-of-existing-theories-or-concepts: 88 bag(s) (22.2%)
  8. causal-argument-violence-war-or-conflict x characterization-of-regime-movement-or-system: 86 bag(s) (21.7%)
  9. causal-argument-nationalism-or-identity x empirical-finding-without-causal-claim: 79 bag(s) (19.9%)
  10. characterization-of-regime-movement-or-system x critique-of-existing-theories-or-concepts: 69 bag(s) (17.4%)
  ... (26 further pairs, 44 to 11 bags each; full ranking reproducible for $0 via the command above)
  36. bibliographic-source-note-or-formal-description x comparative-or-typological-classification: 11 bag(s) (2.8%)

NAMED PAIRS (#826's verification -- reported whether or not they rank)
  causal-argument-state-formation-or-power x causal-argument-violence-war-or-conflict: 112 bag(s) (28.2%), rank 5
  characterization-of-regime-movement-or-system x empirical-finding-without-causal-claim: 137 bag(s) (34.5%), rank 3
```

## Full command output, mechanism (baseline reproduction)

```
pin: 9b796b3a6312b329 (D:\axial\data\map\9b796b3a6312b329)
column: mechanism (level 1)
vocabulary: D:\axial\data\vocabulary\mechanism

COVERAGE
  bag-side chunks: 6010
  vocabulary-side chunks: 5871
  overlap (joinable both sides): 5724
  bag-only (no vocabulary record for this column): 286
  vocabulary-only (no bag): 147
  overlap assigned a category: 5222
  overlap assigned 2+ categories: 0
  overlap refused: 502
  overlap out-of-scheme: 0

PURITY (bags with 2+ categorised members)
  eligible bags: 424
  excluded (fewer than 2 categorised members): 236
  median purity: 0.50
  mean purity: 0.55
  pure bags (purity == 1.0): 59 (13.9%)
  median distinct categories per bag: 3.00
  mean distinct categories per bag: 4.03

CATEGORY SCATTER (over 577 bag(s) holding at least one categorised member)
  min/median/max bags per populated category: 39 / 91.50 / 181
    elite-competition-and-coalition-formation: 181 bag(s), 460 member(s)
    ideological-persuasion-and-legitimation: 165 bag(s), 617 member(s)
    war-and-state-formation: 146 bag(s), 592 member(s)
    social-mobilization-and-collective-action: 142 bag(s), 437 member(s)
    institutional-path-dependence-and-state-capacity: 137 bag(s), 338 member(s)
    economic-dependency-and-structural-adjustment: 128 bag(s), 397 member(s)
    modernization-and-cultural-change: 108 bag(s), 232 member(s)
    organizational-logics-and-bureaucratic-rationality: 103 bag(s), 243 member(s)
    state-repression-and-violence: 102 bag(s), 303 member(s)
    identity-construction-and-boundary-making: 99 bag(s), 269 member(s)
    international-norms-and-external-intervention: 84 bag(s), 302 member(s)
    territorial-control-and-conflict-dynamics: 82 bag(s), 246 member(s)
    feedback-loops-and-unintended-consequences: 67 bag(s), 112 member(s)
    learning-adaptation-and-innovation: 52 bag(s), 91 member(s)
    market-penetration-and-commodification: 47 bag(s), 99 member(s)
    micro-interaction-and-symbolic-reciprocity: 47 bag(s), 139 member(s)
    legal-and-normative-frameworks: 45 bag(s), 106 member(s)
    technological-change-and-infrastructure: 45 bag(s), 66 member(s)
    resource-extraction-and-rentier-state: 42 bag(s), 88 member(s)
    demographic-and-ecological-pressures: 39 bag(s), 85 member(s)

CATEGORY PAIR CO-OCCURRENCE (365 multi-category bag(s))
  1. economic-dependency-and-structural-adjustment x elite-competition-and-coalition-formation: 76 bag(s) (20.8%)
  2. elite-competition-and-coalition-formation x social-mobilization-and-collective-action: 74 bag(s) (20.3%)
  3. elite-competition-and-coalition-formation x institutional-path-dependence-and-state-capacity: 73 bag(s) (20.0%)
  ... (185 further pairs; full 190-pair ranking reproducible for $0 via the command above)
  190. demographic-and-ecological-pressures x micro-interaction-and-symbolic-reciprocity: 1 bag(s) (0.3%)

NAMED PAIRS (#826's verification -- reported whether or not they rank)
  causal-argument-state-formation-or-power x causal-argument-violence-war-or-conflict: not applicable (not both in this column's scheme)
  characterization-of-regime-movement-or-system x empirical-finding-without-causal-claim: not applicable (not both in this column's scheme)
```

This reproduces the approach doc's own mechanism-axis baseline: median
purity 0.5, 13.9% pure. The doc states scatter median as "92 bags"; this
run's exact figure is 91.5 (the average of the 10th and 11th of 20 sorted
populated-category `bag_count` values, since 20 is even) -- the same number,
the doc's is a rounding.

## Files

- `run.jsonl` -- one record per column run, every number in the tables above
  plus the two named-pair results, both `cost_usd: 0.0`/`model_calls: 0`.
- `summary.md` -- this file. `console.log` is not tracked (see `.gitignore`);
  the decisive output is pasted above in full for the top ranks of each pair
  table and abbreviated for the long tail, which is reproducible for $0 via
  the two commands at the top of this file.
