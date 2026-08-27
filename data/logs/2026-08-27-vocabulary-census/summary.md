# Clustering census (rejected) and the probes that replaced it

**Run:** 2026-08-27, issue #805 slice 01. This directory holds the instrument
the slice first shipped — an embedding-clustering census over the twelve
sentence-valued answer columns — and the two probes that replaced it. The
categorisation run that superseded it is in
`../2026-08-27-vocabulary-categorise/`.

## What ran

1. **`console-first-pass.log`** — the census as first built. Rejected before
   reading: it printed a group count and a cross-source count over *all*
   groups, but the bar quantified over groups with 5+ members and used that set
   as its own denominator, so the report could not be read against the bar it
   existed to serve. Fixed in commit `615bd26`.
2. **`console.log`** — the census, re-run whole. Twelve columns, five distance
   thresholds each (0.35–0.75), MiniLM cosine with average linkage, one linkage
   per column cut at every threshold. Zero model calls. ~35 minutes.
3. **`probe-mechanism.log` / `.json`** — the categorisation probe: a model reads
   400 random `mechanism` values, names the recurring kinds, then assigns 400
   disjoint values it has never seen. 5 calls, **$0.026**.
4. **`probe-mechanism-residue.log` / `.json`** — the second round over what the
   scheme did not fit. 5 calls, **$0.024**.

`run.jsonl` holds one record per column for the census sweep, plus one for the
first probe.

## The census, and why it was rejected

Per-column population and distinct-string counts (`run.jsonl` carries the full
sweep):

| column | answered | distinct strings | excluded |
|---|---|---|---|
| about | 20,334 | 19,785 | 17 |
| arguing_against | 11,950 | 11,742 | 347 |
| move | 6,784 | 6,750 | 58 |
| claim | 6,697 | 6,696 | 145 |
| ranges_over | 6,508 | 6,246 | 334 |
| position | 6,176 | 6,172 | 666 |
| concedes | 5,974 | 5,974 | 868 |
| comparison | 5,964 | 5,964 | 878 |
| evidence | 5,884 | 5,884 | 958 |
| mechanism | 5,871 | 5,871 | 971 |
| assumes | 5,558 | 5,558 | 1,284 |
| stops_holding | 2,718 | 2,706 | 4,124 |

String reuse is essentially zero — `mechanism`, `evidence`, `comparison`,
`concedes` and `assumes` have one distinct string per answered value. The
exclusion counts are findings on their own: `stops_holding` is refused on 60.3%
of the notes that reached it, `assumes` on 18.8%.

**The founder rejected the instrument, not the run.** Embedding distance
measures wording. The clearest evidence is in this directory's own output:
`about`'s largest group at threshold 0.55 held **415 sentences across 12
sources whose only shared feature was the word "Syrian"** — "agricultural
income of Syrian small farmers" beside "Syrian video art as critical
alternative to sentimental nationalism". `mechanism` at 0.55 gave 772 groups,
264 with 5+ members.

A geometric group crosses books easily, because different books use the same
words about the same country. That is why the geometric instrument reports
64.4% cross-source on `claim` where the model-named argument positions already
on disk report 35.3%. The flattering number is the wrong one.

## The three instruments, same `mechanism` column

| instrument | units produced | 5+ members | reaching 2+ books |
|---|---|---|---|
| MiniLM cosine clusters at 0.55 | 772 groups | 264 | 200 (75.8%) |
| argmap positions on `claim`, `data/map/9b796b3a6312b329/positions.jsonl` | 1,937 | 357 | 126 (35.3%) |
| model reads 400 values and names categories | **14** | 14 | 14 (**100%**) |

**The `claim` answer was already on disk** and was not searched for before the
census was built — 1,937 model-named positions written 2026-08-06. `data/` is
gitignored, so a code search never surfaces it.

**Bagging by wording is what fragments argmap.** It bags first and names each
bag, so it inherits the geometry: 1,937 positions at a median size of 2, near
the restatement failure its own prompt warns about. Reading a random sample
cold, with no bag, produced 14 general categories instead.

## Probe 1 — does a named scheme hold on unseen values?

`mechanism`, 400 propose / 400 assign, disjoint, `deepseek-v4-flash`.

- 14 categories named, **every one** reaching 5+ members and 2+ sources.
- **70.8%** of the 400 unseen values assigned.
- Largest category 43 members = 10.8% of the sample.
- Examples: "Ideological and religious mobilization" (43 members, 18 books),
  "Elite networks and clientelism" (25, 13), "Path dependence and institutional
  legacy" (18, 12).
- **$0.026.**

## Probe 2 — are the 29.2% one-offs, or is the scheme too coarse?

Same scheme, same 400 held-out values, re-assigned and then interrogated about
what was left.

- Re-assignment reached **78.2%**, against the first run's 70.8% on
  byte-identical input. **A single run's assignment rate carries roughly 7
  points of run-to-run noise.**
- 87 values left unplaced. A second round named **5 further real categories**
  covering **36 of them (41.4%)** — war initiation and escalation,
  macroeconomic policy feedback, symbolic and discursive legitimation,
  state-society fusion, administrative rationalization.
- **51 judged genuinely one-off.**
- A two-round scheme would reach **87.2%** on this column.
- **$0.024.**

So the residue is roughly four parts scheme-too-coarse to six parts genuine
one-off, and a second round is worth about 16 points of coverage for 3 cents.

## Caveats

- Both probes are 800 of 5,871 values on one column.
- The same model proposed and assigned in both. The independent second-model
  check does not exist here; it was built into the command afterwards and is
  measured in `../2026-08-27-vocabulary-categorise/`.
- The census sampled `about` (20,334) and `arguing_against` (11,950) at 6,860
  for clustering. Every other column was measured whole.
- The clustering code these logs describe no longer exists on the branch. It
  was deleted when the slice was rewritten; this directory is the record of
  what it did and why it was not kept.
