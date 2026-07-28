# Can mechanical methods fix the merge pass's latency? Measured.

**No, not on their own — but they fail in the safe direction, which nothing
else fast does.** A model-free resolver reproduces the live pass's partition on
**62.7% of clusters at 91.7% pair precision**, in **4 seconds against 100.8
core-hours**. It finds only **26.4%** of the merges the model made, so it
cannot replace the pass. What it does do is refuse correctly: its errors run
**20 to 1 toward under-merging**, the recoverable direction, where the fast
LLM setting PR #441 rejected ran 8 to 1 toward fusing entities.

Two things turned up along the way that matter more than the headline. A
**shipped parser bug** is silently destroying merges in 7.8% of clusters, and
the model that produced the baseline **gets 12.7% of the undisputed cases
wrong**.

## What was measured, against what

Same method as PR #441, pointed at a different lever. The live pass's 18,873
recorded decisions are the baseline and they were free. Each candidate resolver
re-decides all of them and is compared as a **partition** — which surfaces ended
up grouped — never as a node list, since electing a canonical is a separate and
reversible question.

Three differences from PR #441's setup, all of them tightenings:

- **Every cluster, not a sample of 200.** A mechanical resolver costs
  milliseconds, so there is no reason to sample. Every number below is the whole
  corpus: 18,873 clusters, 56,449 within-cluster pairs, 16,270 of them merges.
- **Precision and recall reported apart, never one agreement number.**
  Over-merging destroys information; under-merging leaves two pages that can be
  rejoined. A single number hides which one a resolver is doing.
- **A held-out half.** Three agents built these rules by reading the errors
  they made on this corpus, which is how a rule set comes to describe its sample.
  The split is by a hash of the batch key. Every finalist was scored on both
  halves; the gap is at most 0.3 points, so the rules generalise.

## The result

| resolver | agreement | pair precision | pair recall | FP pairs | clusters over-merged | clusters under-merged | wall |
|---|---|---|---|---|---|---|---|
| never merge (floor) | 48.8% | 100% | 0.0% | 0 | 0 | 9,660 | 0.1s |
| trust the clusterer | 32.4% | 28.8% | 100% | 40,179 | 12,759 | 0 | 0.1s |
| fuzzy, best usable point | 53.0% | 83.4% | 9.5% | 309 | 250 | 8,710 | 0.4s |
| orthographic (citation-aware) | 53.9% | 86.3% | 11.5% | 299 | 262 | 8,479 | 1.4s |
| structural (token shape) | 57.9% | **95.2%** | 15.9% | 131 | 117 | 7,868 | 1.5s |
| **both, unioned** | **62.7%** | **91.7%** | **26.4%** | 386 | **342** | 6,771 | **4.1s** |
| neo4all's rule, as written | 44.4% | 35.8% | 76.4% | 22,324 | 8,195 | 2,693 | 1.8s |

**The floor is the number to read everything against.** Never merging anything
already scores 48.8%, because half the clusters are ones the model refused
outright. That also reframes PR #441's rejected option: reasoning-off's 68%
agreement was 19 points above doing nothing, not 68 points.

**Fuzzy matching is not usable here, and the threshold is not the problem.**
Across `ratio`, `partial_ratio`, `token_sort`, `token_set`, Jaro-Winkler,
metaphone, soundex and NYSIIS, swept at every cutoff: **recall at 99% pair
precision is 0.0% for every scorer. At 95% it is 0.0%. At 90% it is 0.0%.** The
best real point in the family is 85.9% precision at 0.3% recall. The reason is
structural. The pairs that most need refusing score highest — `Friedman and
Rowlands (1978)` against `(1982)`, `Epstein 2000` against `2000a`, `King Victor
Emmanuel II` against `III`. One character out of twenty carries the whole
distinction, and true variants live at the same scores. Half the surviving
false merges are that shape.

Two by-products worth keeping: **transitive closure is a pure loss** here (the
pairs it alone adds are correct 21–36% of the time, at or below the 28.8% chance
rate), and **`partial_ratio` and `token_set_ratio` are structurally unusable**
rather than badly tuned — both still emit thousands of false pairs at threshold
100, because containment scores 100 by construction.

**Where the mechanical win actually comes from** is token *shape*, not character
distance: name inversion (`Ostrom, Elinor` / `Elinor Ostrom`, 96.6% reliable),
initials, bare-surname attachment gated on both surfaces being `person` (97.8%),
and refusing on ambiguity whenever a short form has more than one candidate. The
structural family carries no numeric threshold at all — no cutoff, no length
ratio, no score. Its one lexicon is a 30-word function-word list, and that is
its weakest rule.

### The traps

On the eight clusters PR #441 and its notes name by hand, the union scores **six
PASS, two under-merge, zero over-merges.** It keeps `O'Rourke & Williamson, 1999`
apart from `, 2002` while folding the two 2002 forms; it refuses `dignitas` /
`dignitas non moritur`, `Robert Mendick` / `Robert Mendick and Harry Yorke`,
`Upper Volta` / `Voltaire`, and all three Khalife people. It misses `Huxley` →
`Aldous Huxley` (world knowledge, unwinnable mechanically) and the Phelps-Brown
fold.

The traps are eight clusters out of 18,873, and passing them is necessary rather
than sufficient — one mid-threshold fuzzy resolver passes seven of eight while
emitting 5,099 false pairs corpus-wide.

## neo4all's techniques, transplanted and measured

Its entity resolution is a hand-written Jaro-Winkler, a Dice token overlap, and
a token-containment test, combined as
`JW ≥ 0.95 OR (JW ≥ 0.90 AND overlap ≥ 0.5) OR containment`. No fuzzy library,
no phonetics, no alias table.

Run as a decider on this corpus it gives **35.8% precision and 22,324 false
pairs**, and over-merges five of the eight traps, including `dignitas` and the
O'Rourke years. Repairing the containment guard bug — the code tests `< 1` where
its own docstring, CHANGELOG and three currently-failing unit tests say `< 2` —
lifts it to 38.6%. Dropping containment entirely gives 38.2%.

**That is not a criticism of neo4all, and the reason is the transferable
finding.** In neo4all this rule decides nothing. Since its 1.0.8 release nothing
merges mechanically: the rule *generates candidates*, and an LLM plus a human
approves each one. Its NLP is the blocking half of record linkage — and **Axial
already has that half.** HDBSCAN clustering is what those functions would
produce. The part Axial needs is the decision, and that is precisely the part
neo4all also hands to a model.

The technique that did transfer is smaller and lives in neo4all's instincts
rather than its thresholds: filter stopwords before comparing tokens, refuse a
containment merge when the shorter side is a single token, and treat "one string
contains the other" as a question rather than an answer.

## Two things found along the way

### A shipped bug is destroying merges in 7.8% of clusters

`merge_names.parse_merge_response` resolves the model's answer back onto the
batch's members through a casefolding normalizer:

```python
known = {_normalize(surface_form): surface_form for surface_form in members}
```

Two members differing only in case collapse to one key. The model's answer
resolves both strings to the same member, the second is already `claimed` and is
dropped, and the surface it came from is left unplaced — surviving as its own
node. Reproduced directly: for members `("Janjaweed", "janjaweed")` and a model
answer merging them, the parser returns `[{'canonical': 'janjaweed', 'aliases':
[]}]` and the merge is gone.

- **1,471 clusters (7.8%)** contain such a collision, over **1,568 pairs**.
- All 1,568 are recorded as "refused" — 1,568 of 1,568, which is what a
  deterministic bug looks like next to a model's judgment.
- The shipped `alias_map.json` carries **1,514 canonical names that differ from
  another canonical only by case**, so that many name pages are set to be minted
  twice.

This also corrupted the experiment before it was found: the fuzzy family read
those refusals as a preference and concluded "never casefold before scoring,"
which is advice derived from a bug. Every headline above is therefore also
reported with those pairs excluded (`score_repaired`). It moves the union's
precision by nothing, because no rule proposes them; it moves a case-folding
variant from 71.2% to 90.4%.

The fix is one line in scope — resolve against the member list rather than a
lossy dict, or fail loudly on collision. It is not in this diff, which changes
no `src/` behaviour.

### The baseline itself is 12.7% wrong

On pairs that are the same citation differing only in punctuation —
`Huntington (1991)` against `Huntington, 1991`, where "same thing" is not a
judgment call — the live pass **refused 142 of 1,117**, with the parser artifact
already excluded. `Repetto (2007)` / `Repetto, 2007` refused; `Whitney (2001)` /
`Whitney, 2001` merged.

Every agreement number in this report and in PR #441 is fighting that noise
floor. Some fraction of the union's 386 "false" merges are the model being
wrong, not the resolver.

## The ceiling: why no amount of rule-writing gets much further

Two pairs that look identical to a mechanical resolver must get the same answer
from it. Where the live pass answered them differently, one of the two is a
forced error. Grouping all 56,449 pairs by a signature of cheap string facts —
token relation, year compatibility, what the distinguishing tokens look like,
whether the kinds match — and letting an oracle answer each signature with its
majority label gives the best score any resolver over those features could
reach:

**72.3% pair precision at 53.4% recall.** Even an optimal rule would fuse
entities on more than a quarter of what it merges.

That bound is against *this model run*, so model noise is inside it. Read it as
the shape of the answer rather than a hard number: the information needed to
decide is substantially not in the strings. The largest single ambiguous class
is bare-versus-dated citation — `Barnard` / `Barnard (2003)` merged, `Drake` /
`Drake (1991)` refused. The strings are identical up to the year, and 1,019
gold merges sit on one side of that line with 1,722 refusals on the other.

## What this means for the latency problem

The prize, measured rather than inherited from the PR: **100.8 core-hours** of
model time, median 8.9s per call, p99 164s, max 710s. **40% of it went to
two-member clusters** and **46% to clusters whose answer was "nothing merges."**
Nearly half the spend was on saying no.

The union reproduces the model's exact partition on 11,842 clusters, behind
which sits **56.1% of that model time**. It asserts a merge in only 22% of
clusters and over-merges 1.8%.

So the honest reading, given the founder's constraint that this be mechanical
only:

- **As a replacement for the pass, it fails.** 26.4% recall means three
  quarters of the real merges never happen, and 342 clusters get fused wrongly.
  Against D10 that is not shippable.
- **As the fast option, it is the safest one measured.** Its errors run 342
  over-merges against 6,771 under-merges. Reasoning-off — five times faster and
  rejected in PR #441 — ran 55 over-merges against 7 under-merges on its sample,
  a 27.5% over-merge rate against this resolver's 1.8%.
- **PR #441's conclusion stands.** Concurrency remains the only lever that
  costs no judgment. Nothing here displaces it.

The two changes this experiment supports on their own merits are the parser bug
fix, which is a correctness matter rather than a speed one, and the observation
that 46% of the model time buys refusals.

## Reproducing

```
uv sync --group experiment
uv run python -m experiments.mechanical_merge.bench \
    experiments.mechanical_merge.resolvers.combined:union --hard
uv run python -m experiments.mechanical_merge.score_repaired  <same args>
uv run python -m experiments.mechanical_merge.holdout         <same args>
uv run python -m experiments.mechanical_merge.ceiling --repaired
```

Reads `data/names/{merge_decisions,inventory}.jsonl` and writes nothing under
`data/`. Because `data/` does not exist in a worktree, these run in the main
checkout. Full evidence, including every sweep table:
`data/logs/2026-07-28-mechanical-name-merge/`.
