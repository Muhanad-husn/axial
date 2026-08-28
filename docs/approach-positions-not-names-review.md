# Positions, not names — a research review

**A review of [`approach-positions-not-names.md`](approach-positions-not-names.md).
2026-08-28. Everything checked against the repository, the data on disk, and the
run logs; one new measurement was taken for this review and is reported in §2.**

## 1. Verdict

The direction is right and its central premise now has evidence: the `claim`
column categorises cleanly (10 categories, 99.5% assigned, largest 21.2%,
cross-model agreement 77%), and a new cross-tab taken for this review shows the
current wording bags really do shred stakes — median bag purity 0.5 against the
mechanism categories, and each mechanism category scattered across a median of
92 bags. The diagnosis in §5 of the approach is correct and now measured.

Four things the approach does not confront, two of them load-bearing:

1. Swapping the bagging criterion breaks the extraction step's arithmetic, and
   the doc's "steps 1, 3 and 4 stay exactly as they are" is false in effect
   (§3 below).
2. "Assign at read time" contradicts the doc's own promise not to touch the
   interrogation, and the measured evidence supports the post-hoc path, not the
   read-time one (§4 below).
3. Category assignment noise becomes hard partition noise (§5 below).
4. The doc deletes the evaluation apparatus while proposing a change nothing
   currently measurable could validate (§6 below).

None are fatal. All four have concrete resolutions, listed in §8.

## 2. What the research confirms

**The claim column categorises.** The corrected categorisation run
(`data/logs/2026-08-27-vocabulary-categorise-v2/`) has `claim` passing all five
conditions: 10 categories, all cross-book, 99.5% assigned, largest category
21.2%, agreement 77.0% at n=100. The approach's cornerstone — that the field
being swapped into category-bagging is categorisable — holds. So do `position`
(15 categories) and `mechanism` (20), the other constitutive candidates.
`arguing_against` passes but with only 68.2% assigned and agreement inside its
own noise.

**Wording bags mix stakes — new measurement.** Joining the current pin's
`bag_state.json` against `data/vocabulary/mechanism/assignments.jsonl` (5,222
chunks in both, pin `9b796b3a6312b329`):

- Of 424 bags with 2+ categorised members, only **13.9% are pure** on the
  mechanism axis. Median purity (share of a bag in its modal category) is
  **0.5**; median distinct categories per bag is **3**.
- The reverse is the fragmentation smoking gun: every mechanism category is
  scattered over **39 to 181 bags, median 91.5**. Passages sharing a causal
  story are systematically never shown to the model together. That is exactly
  why the same argument gets named out of many bags, why merge folds 2,206 raw
  positions to 1,937, and why the median position holds two passages.

Caveat: mechanism is one axis and purity against `claim` categories is
unmeasured — the claim vocabulary was never built. And impurity alone is not
harm; extraction is allowed to split a bag. The scatter number is the one that
bites.

**The retrieval numbers are real.** The name arm measured 3.2x dearer and 4x
slower than the map arm for no grounding advantage (#809). The demotion of
names to a filter is already justified on the books.

**The residue fear is backwards.** §11 worries about passages with no category.
Measured, the category path *loses fewer* passages than bagging does: `claim`
refuses 0.5%, where the current build leaves 545 of 6,010 unassigned by the
model inside bags plus everything bagged nowhere. The residue problem shrinks
under this approach; it does not return. It is quantifiable for free the day
the claim vocabulary is built.

## 3. The bag-size arithmetic breaks step 3 — the load-bearing problem

Today: 680 bags, mean ~9 passages. `EXTRACT_SLICE = 55`, so nearly every bag is
one slice and "what recurs here" is judged over the whole bag in a single call.

Under claim categories: 10 categories over ~5,900 selected passages is a mean
bag of ~590 and a largest bag of ~1,250 (21.2%). At slice size 55 that is 11 to
23 slices per bag. An argument recurring across slices is never seen in one
call. The only thing that reunites its per-slice namings is step 4's merge —
embedding similarity over argument sentences at threshold 0.30.

So wording similarity is not removed from the grouping principle. It moves from
step 2 to step 4 and becomes *more* load-bearing, because far more of every
argument's instances now sit in different calls. The merge was measured folding
near-duplicate namings (2,206 → 1,937); it was never asked to carry the primary
reunification of a corpus-scale argument, and nothing says it can.

Three resolutions, one honest:

- **Intersect two constitutive axes.** `claim` × `mechanism` gives at most 200
  cells, mean ~27 members — back inside one or two slices. Cost: coverage
  multiplies down (0.995 × 0.905 ≈ 0.90) and misassignment multiplies too.
- **Hierarchical extraction.** First pass per slice as today; second pass over
  a bag's per-slice arguments, asking what recurs among *them*. A new step —
  which is fine, but the doc must say so instead of "steps stay exactly as
  they are".
- **Bigger slices.** The context window allows more than 55 one-sentence
  claims; but a 600-claim call reproduces the measured failure mode where the
  model misses relations from load alone (the 53-position neighbourhood
  lesson).

The second is the honest one, possibly combined with the first. Either way §6
of the approach needs rewriting: the change is not "only step 2 moves".

## 4. Read-time assignment contradicts §3 — and the evidence backs post-hoc

§3 of the approach: the interrogation is the one layer not touched. §4: "have
the interrogation assign the axes at read time". Those conflict. Read-time
assignment changes the interrogation prompt and output schema — the substrate
moves.

The conflict is resolvable because the measured evidence is all on one side.
The 88.5–99.5% assignment rates were measured on the **post-hoc** path:
categorising a free-text answer already written, exactly what
`axial vocabulary build` does. Read-time assignment with a fixed list is
unmeasured here — and it is the v0.1 closed-vocabulary mechanism, which the
spec retired (D4/D9) in favour of abstention plus a verbatim free answer, with
the codebook demoted to examples. This matters historically: tags-as-index has
already died once in this repository. Phase B found `query_by_tag` returning
zero on every axis — not because tag retrieval was measured and failed, but
because Phase A v1 retired the closed vocabularies and notes stopped carrying
them. What is different this time, and the approach should say so explicitly:
the categories are derived from the corpus's own answers after reading, not
imposed on the reading; and their job is grouping for a model's judgment, not
serving as retrieval bins. Assigning at read time gives back half of that
difference.

The simplification that survives: keep interrogation free-text and untouched;
keep assignment as a separate cheap pass over the answer column (the mechanism
column cost ~$0.10 to categorise); commit schemes in `config/vocabulary.yaml`
(already done); demote `examine` to a drafting tool and delete its measurement
apparatus (the approach already says this in §12). The honest restatement of
§4: the two-mechanism problem is real, but the fold direction is *into the
vocabulary passes with the scheme in config*, not *into the interrogation*.
"One pass at read time" buys nothing for the 6,000 notes that exist — they
need backfill regardless — and risks answer drift on the substrate for future
books.

## 5. Assignment noise becomes hard partition noise

Cross-model agreement where assigned: `claim` 77%, `mechanism` 61.4%. Under
embedding bagging a borderline passage lands near its neighbours and the error
is graded. Under category bagging a misassigned passage sits in the wrong bag
with no path back — merge reunites namings, never passages. Roughly one claim
assignment in four is disputed between two models.

Not fatal, but it needs a stated policy: either a passage near a category
boundary is offered to both bags (which spends assembly cap slots — the #822
lesson says offer through exactly one survivor), or borderline assignments are
adjudicated once, or the error rate is simply accepted and stated. Silence is
the only wrong option.

## 6. The change is unmeasurable with the instrument the doc keeps

§9 deletes the evaluation apparatus; the smoke gate is saturated (grounding
1.000 on 13 of 15 cells) and could not tell three retrieval methods apart. The
approach's own §12 warning cuts both ways: nothing currently measurable would
show the re-formed map is *better* either. "Map beats name layer on grounding"
cannot be extended to "category-bagged map beats wording-bagged map" without a
harder gate.

The cheap instrument exists and is structural, not judged: a full rebuild costs
$0.77–0.87 plus $0.35–0.41 for relations (measured, `map.json`). Rebuild with
the swapped criterion and compare offline against the paid-for build: median
position size (now 2), cross-book position rate, share of positions folded at
merge, bag-purity by the axes not used for bagging, and the count of
"uncontestable generality" positions. Only after the structural comparison
says the map got denser and more cross-book is a judged comparison worth
paying for — and that one needs a gate harder than the saturated smoke set.

## 7. Smaller corrections

- **The speed claim double-counts.** §7's "where the time comes back" is
  mostly already banked: the map arm is deterministic after the door call and
  already 4x faster than names, today, without categories. What categories add
  to retrieval is the address layer and relation-pair ranking — genuine, but
  incremental on speed.
- **Profile-directed relations is the strongest section.** Relations today:
  1,328 asserted, only 492 cross-author, over neighbourhoods built by argument-
  sentence similarity — the same wording trap as bagging. Profiles ranking
  candidate pairs (same mechanism, opposed position, different books) is a
  principled candidate generator, and §10's conditions are exactly the right
  firewall against the join fallacy that killed `vocabulary_join`.
- **The granularity test §11 asks for already exists.** The five conditions in
  the categorise run log (coverage floor, blob condition, 5+ members cross-
  book, agreement floor) are that test. Point at them; do not invent a new
  one.
- **Known art, briefly.** This design is deductive qualitative coding with a
  committed codebook plus LLM assignment — standard practice, and the measured
  agreement (61–77% raw against 5–10% chance) sits in the range published
  LLM-coding studies report. The extraction step is Key Point Analysis
  (Bar-Haim et al., ACL 2020): mapping many arguments onto few key points,
  where the literature's finding matches this repository's — pure clustering
  fragments, and match-to-scheme beats cluster-then-name. The approach is not
  novel machinery; that is a point in its favour.

## 8. What to do before writing an implementation plan

In order, each cheap, each killing the plan early if it fails:

1. **Build the claim vocabulary** (examine → founder edits → commit scheme →
   `vocabulary build`). ~$0.20. Without it the cornerstone axis has no
   corpus-scale assignment, and every later measurement is blocked.
2. **Re-run the §2 cross-tab on claim categories** — free. If wording bags are
   pure on the claim axis the whole diagnosis weakens.
3. **Decide the step-3 mechanics** (§3 above: intersection, hierarchy, or
   both). This is a design decision, the founder's.
4. **Rebuild the map once with the swapped criterion** — ~$1.20 — and run the
   structural comparison of §6 against the existing build.
5. Only then: relations, retrieval, and the demolition list in §9 of the
   approach. Nothing in the name layer needs touching to run steps 1–4.
