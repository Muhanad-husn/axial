# feat(positions-not-names): `axial map compare` delivers the structural verdict [slice 06]

**Spec:** docs/approach-positions-not-names.md#13-the-work-in-order · **Plan:** plans/positions-not-names/06-structural-comparison.md
**Depends on:** #830
**Labels:** enhancement, sub:analysis-v0

> Acceptance criterion rewritten 2026-08-29 to the bar the founder approved in
> this issue's thread, with the three corrections from #838's build of the
> held-out column and the `placed` fix folded in. The original criterion named
> five metrics and no bar; three of those five move in the "good" direction by
> arithmetic alone, and its `passages reaching no position` definition would
> have printed **-60** against a true **414**.

## Deliverable

`axial map compare <dir-a> <dir-b>` puts two map builds side by side and
decides whether the re-formed map earned slices 07–09. Five metrics decide
(D1–D5); everything else the command prints is context. No judged gate and no
model calls: the smoke gate is saturated and is deliberately not trusted with
this decision. The slice ends with a blind paired hand-sample, every margin
quoted against the measured replicate gap, and the founder's go/no-go recorded
in the run log and the feature README. **This is the feature's hard gate.**

## Mechanism

A read-and-report module over `positions.jsonl` / `map.json` / `reads.jsonl`
pairs, with a size-matched permutation null computed per build for D1, D2 and
D3, and MiniLM `all-MiniLM-L6-v2` for D3. Offline, deterministic given a seed,
zero model calls. Slice 02's `map purity` is **not** re-run here — it joins
bags against a vocabulary column, and under the variant the groups are the
categories, so its answer is 1.000 by construction. D2 is that arithmetic
re-pointed from bags to positions on a held-out axis.

## The deciding metrics

**D1 (primary) — book-spread ratio, size-matched.** Mean distinct `source_id`
per position ÷ the mean under a permutation of that build's own placed pool
into positions of the same sizes. Default build: **0.59 / 0.37 / 0.24 / 0.14**
at sizes 2 / 3–5 / 6–10 / 11–48 (overall observed 1.20 sources per position).
Direction: up. Invariant to how large the variant's positions turn out to be,
which is the confound that sinks the raw cross-book rate.

**D2 (primary) — held-out `position`-axis purity, size-matched.** Position
purity = the modal `position` category's share of a position's categorised
members, against the size-matched null. The `position` column is built and
never grouped on (#838, built before slice 03 as ruled).

**D3 (guard, not tradable against D1/D2) — member coherence floor.** Mean
cosine of a position's members' `claim` texts to that position's centroid,
MiniLM `all-MiniLM-L6-v2`. Default build, 1,174 multi-member positions:
0.902 / 0.850 / 0.816 / 0.791 by band, 0.858 overall, band null 0.537 at 11–48
and 0.689 overall. Coherence falls with size in the default build too, so
compare band against band.

**D4 (guard) — passages reaching no position, share of selected.** Counted as
**distinct chunk ids in `positions.jsonl`** subtracted from selected. Default:
6,010 selected, 5,596 distinct placed, **414 unplaced = 6.9%**, of which 373
were declined by the extraction model (`unassigned` summed over `reads.jsonl`;
all 6,010 were shown) and ~41 were lost to 3 failed reads. Direction: must not
rise.

**D5 (veto) — blind paired hand-sample.** 12 positions from each build,
stratified to the same size bands, shuffled, judged "do these members make one
argument" **before** the labels are revealed.

## The bar

| metric | bar | measured against |
|---|---|---|
| **D1** book-spread ratio | rises to **at least 2×** the default build's value in the size band holding the plurality of the variant's placed passages, **and** exceeds the replicate gap by 2×, **and** does not fall in any band | 0.59 / 0.37 / 0.24 / 0.14 above; the replicate gap measured, not assumed |
| **D2** held-out `position` purity | **above 0.349**, and above the default build's value, by **at least 2× the replicate gap**; a lift at or below 1.00 fails outright whatever the gap | the 0.349 floor below, not the 0.196 null |
| **D3** coherence | in every populated size band, **at or above the midpoint between the default build's value in that band and that band's permutation null**. For 11–48 that is **0.664** | this build's own bands and nulls |
| **D4** no-position share | **at or below 6.9%** of selected, distinct chunk ids in `positions.jsonl` | 414 of 6,010 |
| **D5** hand-sample | **8 or more of 12**, and **at or above the default build's score** on the same blind pass | the paired draw itself |

The 2× factor is a chosen margin, not a measurement: the smallest multiple that
keeps a claim outside the interval a single replicate can resolve, and stricter
than #809's "inside its own draw spread" test, which this feature has already
failed once.

**The replicate is approved and required** (~$0.42, plus the ~$0.075 `position`
column already built). It runs **forced**, in its own directory, with
prior-pin seeding off — `_prior_pin_dir` (`build.py:1173`) picks the newest
sibling under `map_dir` by `map.json` mtime, and `_seed_reads_from_prior_pin`
would refill the ledger from a slice-identical variant and reproduce it
byte-for-byte, reading a zero error bar. `map compare` must **verify
`units_reused == 0` in the replicate manifest** before quoting any margin
against the gap, and print it.

## D2's three corrections (#838)

1. **D2's population is 5,549, not 6,010.** The `position` *answer* is present
   on 6,010 of 6,010 selected; the *assignment* is not. After 379 refusals and
   666 excluded abstentions the built column carries a category for **5,549 of
   6,010 selected (92.3%)** and **5,257 of 5,596 placed (93.9%)**. D2 decides
   over categorised members — quote that base, both numbers.
2. **The gap is not random, and D2 is partly blind where it falls.** Refusals
   concentrate in `vignal-2021` (39.8%), `batatu-1999` (38.0%) and
   `tilly-1978` (34.1%) — 47% of all 379 refusals across three of 35 sources,
   because two committed categories exclude single-country material and this
   corpus is geographically concentrated. If the rebuild changes how those
   books' passages group, D2 partly cannot see it. Print the per-source
   coverage next to the verdict.
3. **D2's floor is 0.349, not the null.** Over the 5,773 passages carrying
   both columns, the weighted conditional purity of `position` given `claim` is
   **0.349** against a permutation null of **0.196** (20 shuffles, max 0.198),
   lift **1.78×**; largest `position` category share 0.195. So a variant
   grouped on `claim` starts at `position` purity ≈ 0.349 **before the rebuild
   contributes anything**. A D2 result of 0.38 is inside the arithmetic, not
   evidence.

## Normalisation rules the command must obey

**(a) The `placed` fix.** `build.py:1395` sets
`placed = sum(position["size"] for position in raw_positions)` — member *slots*
over **raw** positions, 6,070 on the live build, so "selected minus placed"
prints **-60**. D4 is computed from **distinct chunk ids in
`positions.jsonl`** (5,596 → 414 unplaced). The offset is not constant: the
variant's raw-position count and duplicate rate both differ. The misleading
log line in `build.py` is a separate one-line defect and is not fixed here.

**(b) Positions overlap, so member slots are not passages.** 344 of 5,596
placed chunks sit in 2–5 positions (#822); member slots sum to 5,987. Every
share names its denominator. Passage-weighted companions for the default
build: 12.7% of slots in single-passage positions, 27.4% in cross-book
positions, 28.3% of distinct placed passages reaching at least one cross-book
position — against the 39.4% / 15.0% position-weighted figures.

**(c) Consolidation has no counterpart in the default build.** Report it as
**folds per final position** (default, via the embedding merge: 2,206 → 1,937,
269 folds over 207 positions, **0.139**) or the builds are not on one axis. The
embedding merge still runs on the variant across categories, so its folds are
reported **separately** from the consolidation pass's own.

**(d) The pin check is not sufficient on the corpus pin alone.** The pin hashes
raw sources only and the recorded `corpus_pin` is a manifest name, not a digest
(#816). `map compare` prints and refuses on a mismatch of the **corpus pin,
the vocabulary scheme versions** (`claim` at `2026-08-28-claim-v1`, plus
`position`) **and the answers pin** (`d5517979069efe79`).

**(e) The first variant build can leak from the default build.** With
`data/map/9b796b3a6312b329/` as the newest sibling it will attempt to seed bag
state and reads from it. Category slices will rarely match a bag slice, so the
leakage should be small — it is not zero, and it is reported, not assumed away.

## Reported, never deciding

Position count; size median and quartiles; single-passage share; the binary
cross-book rate **with its null beside it or not at all** (96.2% at size 2,
99.9% at 3–5, 100.0% above — saturated before the comparison starts);
extraction reads and units asked/reused; cost and wall clock; consolidation
folds; the `claim`-assignment disagreement rate (~23% at n=100, #826) and the
`position`-assignment two-model agreement (**73.8%** where assigned, n=84;
70.0% overall), both quoted next to the verdict per approach §6's noise policy.

**Fewer positions, larger positions and a lower single-passage share are not
results.** They follow from 113–207 extraction calls replacing 679.

## Acceptance criterion

```gherkin
Given the default build and the forced variant replicate for one corpus pin,
      one answers pin and one set of vocabulary scheme versions
When  `uv run axial map compare data/map/<pin> data/map/<pin>-category` runs
Then  it prints D1 book-spread ratio per size band for each build, observed
      over its own size-matched permutation null
And   it prints D2 held-out `position` purity per build over the same null,
      naming the categorised base (5,549 of 6,010 selected; 5,257 of 5,596
      placed on the default build) and the 0.349 conditional-purity floor
And   it prints D3 mean member coherence per size band per build with that
      band's null
And   it prints D4 passages reaching no position as distinct chunk ids in
      `positions.jsonl` subtracted from selected, never as a sum of position
      sizes
And   it prints the replicate gap on D1 and D2, and `units_reused` for the
      replicate build
And   it prints each build's context lines with their denominators named, and
      the cross-book rate only alongside its null
And   consolidation is reported as folds per final position, with the
      embedding merge's folds separate from the consolidation pass's own
And   the two builds appear side by side in one table naming the corpus pin,
      the answers pin, the vocabulary scheme versions and both artifact paths
And   comparing builds that disagree on any of those pins or versions refuses
      with a message naming which one differs
```

## What counts as failure

Any one of these is a no-go on slices 07–09:

1. **D1 does not clear 2× in the plurality band, or falls in any band.**
2. **D2 is at or below 0.349, at or below the default build's value, or the
   lift is at or below 1.00.**
3. **D3 breaches a band floor** (11–48: below 0.664). That is gluing, and no
   story about deliberately removing wording similarity survives it.
4. **D4 rises above 6.9%.** On a `claim × mechanism` inner split this already
   starts at **797 of 6,010 = 13.3%** before any model call (788 mechanism, 17
   claim) — that split is rejected in #828 on this ground unless the ungrouped
   797 get an explicit home.
5. **D5 scores under 8 of 12, or under the default build on the same blind
   pass.** A veto, independent of every number above.
6. **The replicate gap swallows the result.** If the replicate gap on D1 or D2
   is larger than half the variant-versus-default gap, the answer is "not
   resolved at this sample", not "passed". That is the #809 lesson.

## Open question for the founder, carried into this slice

Correction 3 (#838) gives the `position` assignment a two-model agreement of
73.8% where assigned — "a D2 difference smaller than it is not readable". That
is an agreement **rate**; D2 is measured in **purity points**. The two are not
in the same units, so the sentence cannot be turned into a threshold without a
ruling. Until one exists, the agreement figure is **quoted beside the D2
verdict** and no arithmetic is derived from it. Options: (i) leave as
reporting-only, as written here; (ii) require the D2 gap to exceed the
replicate gap by more than 2× on the strength of it; (iii) measure the
assignment's effect on D2 directly by recomputing D2 over the second model's
draw, ~$0.075.

## Files

```aeo-independence
slice: 06-structural-comparison
creates: src/axial/argmap/compare.py
creates: src/axial/argmap/test_compare.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-map-structural-comparison/summary.md
depends-on: 05-category-consolidation
```

## Out of scope

- Any judged (model-graded) comparison — needs a gate harder than the
  saturated smoke set, which is separate work.
- Any change to either build.
- Fixing the `placed` log line at `build.py:1395`. `map compare` computes D4
  correctly regardless; the log line is its own defect.
- Re-running slice 02's `map purity` against the variant's groups. It measures
  1.000 by construction there.
