# Positions, not names

**An architecture approach for Axial. Drafted 2026-08-28, revised the same day
after review (see
[`approach-positions-not-names-review.md`](approach-positions-not-names-review.md)).
This version is the buildable one: §13 is written to take a tdd-plan directly.**

The map is right and stays. What was missing is a sense of what a passage is
about, and the interrogation has been producing it all along. The map gets
re-formed around it. The name pages go — after the re-formed map is measured
against the old one, not before.

---

## 1. What the product is

A wiki whose articles are the real things in intellectual life: a position
somebody holds, the argument they make for it, the concept they work with.
Articles connect by how they stand to each other — agreement, conflict,
qualification.

An article is a **position**. Its title is the claim. Its body says what is
claimed, who holds it, in which books, and what it argues against. Its links
are the relations that run to other positions.

This is why a name can never be an article. A name asserts nothing, so nothing
can agree or disagree with it. A page per name is an index entry wearing an
article's clothes.

The distinction that governs everything below:

| | |
|---|---|
| **Co-occurrence** | Two passages both say "Syria". A coincidence of vocabulary. Nothing follows from it and nothing can be argued about it. |
| **Stake** | Two passages both explain why a state came apart. One says war made it, the other says rents unmade it. They are in conflict, and that conflict is the content. |

## 2. What is broken, and what is not

The system has answered one question three times and kept all three answers.
The question is: *how do two passages meet?*

The first answer was a shared name. The second was a shared stake, which is the
argument map. The third was a shared category. Each was added; none replaced its
predecessor.

**The map's idea is correct.** Positions relate to each other, and those
relations are the scholarship. It also measured better than the name layer on
grounding, on fewer sources, which is the outcome that matters.

**The map's manufacture is not — and this is now measured, not argued.** The
passages a model is allowed to read together are chosen by wording similarity.
Joining the current build's bag assignments against the mechanism categories
(the one axis already assigned corpus-wide): only 13.9% of bags are pure on
that axis, the median bag splits over three categories — and, the number that
bites, **each mechanism category is scattered across a median of 92 bags**.
Passages sharing a causal story are systematically never shown to the model
together. That is why the same argument gets named out of many bags, why merge
folds 2,206 raw positions to 1,937, and why the median position holds two
passages. One caveat stands: mechanism is one axis, and the same cross-tab on
the claim axis is unmeasured until the claim vocabulary is built — which is
why it is the first slice of §13.

### The other defect is time

The application works. The answers are good. They take far too long to arrive,
and the wait sits in the name layer and the retrieval built on it — the
resolution tiers, the page index, and a tool loop that circles back many times.

Measured over the same briefs at the same commit, a draw through the name layer
ran roughly four times as long as the same draw through the map, and cost more
than three times as much, with no advantage in grounding. To be exact about
what that buys: the map arm is already the fast path today, without categories.
What categories add to retrieval is an entry point and an address layer (§7),
not the raw speed — that is already banked by entering through the map at all.

## 3. The substrate

Every passage is interrogated once with the same open questions. What does it
claim, whose position is it, who does it argue against, what causes what and in
what order, what does it name.

That is what makes two passages comparable at all. Everything above reads it,
and nothing above is worth keeping if it is disturbed.

**The interrogation is the one layer this approach does not touch.** That
sentence binds everything below it. In particular it settles *where* category
assignment happens: not inside the interrogation prompt (§4).

## 4. Categorisation is curation, not research

This is where the last implementation went furthest astray, and where the
simplification is largest.

### What already exists

`config/domains/syria/codebook.yaml` holds **67 hand-written categories across
five axes** — field, claim type, empirical scope, theory school, role in
argument. Each carries a definition, a positive example, and a negative example
naming which category it belongs to instead. That is a codebook in the ordinary
social-science sense: committed by a person, applied by a model.

`config/vocabulary.yaml` holds the first committed derived scheme — twenty
mechanism categories, read and approved by a person — and
`data/vocabulary/mechanism/` holds the corpus filed against them. That is the
same idea, built the long way round.

### The simplification

**One mechanism: a scheme is drafted from a sample, edited and committed by a
person into configuration, and assigned by a cheap model pass over the answer
column the interrogation already produced.** That is `vocabulary examine`
(drafting), a founder edit, and `vocabulary build` (assigning) — all of which
exist. What goes is everything else: the measurement apparatus inside examine
(held-out scoring, the two-model cross-check), and the idea of a derived
vocabulary as its own evolving artifact rather than committed configuration.

**Assignment happens after reading, not during.** An earlier draft of this
document proposed folding assignment into the interrogation at read time. That
is rejected, for three reasons. It contradicts §3 — a changed prompt and output
schema is the substrate disturbed. Every measured assignment rate came from the
post-hoc path — categorising an answer already written — so read-time
assignment is the unmeasured variant. And read-time closed-vocabulary tagging
is precisely the v0.1 mechanism the spec retired (D4/D9): this repository has
already watched tags-as-index die once. What is different this time, and the
only reason to try again: the categories are derived from the corpus's own
answers after reading, not imposed on the reading, and their job is grouping
material for a model's judgment, never serving as retrieval bins directly.
Assigning at read time would give back half of that difference.

The corollary is free: the existing corpus needs no re-ask for any axis whose
question was already asked. Adding an axis over an existing answer column is
one `vocabulary build` pass. Only a genuinely new question — an axis with no
column — needs the one-question re-ask, and `position_backfill` is the
precedent for that.

### Not all axes are equal

Some axes **constitute** a position — what is claimed, the stance taken, the
causal story, what it argues against. Those say what somebody asserts.

The rest **describe** it — what it is about, where and when it holds, what
evidence it rests on, what it concedes.

Only the constitutive axes should decide how passages are grouped. The
descriptive ones narrow and address. Keeping that line is what stops the
grouping from fragmenting.

The constitutive candidates already measured categorisable: `claim` (10
categories, 99.5% assigned, agreement 77%), `position` (15), `mechanism` (20).
`arguing_against` passes the categorisation bar but with only 68.2% assigned
and agreement inside its own noise — it may address, but it must not gate a
grouping.

## 5. How a position is formed today

Four steps, run by `axial map build`.

1. **Select.** Every interrogated passage's own `claim`, minus abstentions,
   back matter, and passages that argue nothing. 6,010 selected.
2. **Bag.** A local sentence-transformer embeds each claim and agglomerative
   clustering groups them by **wording similarity**. Zero model calls. Result:
   660 bags over 6,070 passages, roughly nine per bag. 373 passages placed
   nowhere.
3. **Extract.** Each bag is read in full, in author-spread slices, one model
   call per slice, reasoning high, asked what argument *recurs* across passages
   that merely resemble each other, and told explicitly not to fuse opposed
   accounts. Authors hidden, so it cannot use who said it to decide what meets.
   2,206 raw positions.
4. **Merge.** The same argument gets named out of more than one bag;
   near-duplicate namings are folded by sentence similarity. 2,206 → **1,937
   positions**.

Distance does **not** decide what a position is. The model already decides —
step 3 is exactly the judgment call, with reasoning on, and it is already
proven. What distance decides is **which passages the model is allowed to read
together**. That is the defect, and §2's cross-tab is its measurement.

## 6. The change

**Swap the grouping criterion from wording similarity to shared categories —
and redesign the extraction mechanics to survive the group sizes that swap
produces.** An earlier draft said only step 2 moves and steps 3 and 4 stay
exactly as they are. That was wrong, and here is why.

Today's bags average nine passages, so nearly every bag fits one extraction
slice and "what recurs here" is judged over the whole bag in a single call.
Ten claim categories over six thousand passages is a mean bag of roughly six
hundred and a largest bag over a thousand — dozens of slices. An argument
recurring across slices would never be seen in one call, and the only thing
reuniting its per-slice namings would be step 4's merge, which folds
near-duplicate wordings. Wording similarity would not have been removed from
the grouping principle; it would have moved from step 2 to step 4 and become
*more* load-bearing. That failure mode is disqualifying, so the design must
close it explicitly:

**Grouping is two-level.** The constitutive category — `claim`'s scheme first —
is the outer level. Inside a category, a cheap inner split brings groups down
to readable size. Two candidate inner splits, to be decided by measurement in
§13, not by taste here:

- **A second constitutive axis.** `claim` × `mechanism` yields cells that fit
  one or two slices. Cost: coverage multiplies down (two refusal rates
  compound) and misassignment multiplies too.
- **Wording similarity, demoted to sizing.** Embedding clustering *inside* a
  category is harmless in a way it is not corpus-wide: every passage in the
  cell already shares a stake, so the inner split only decides reading order
  and batch boundaries, not who may ever meet whom — provided the level above
  it gets a consolidation pass.

**Extraction is two-pass wherever a category spans multiple groups.** The
first pass is today's step 3, unchanged, per group. The second pass reads the
first pass's arguments *within one category* and asks what recurs among them —
the same judgment, one level up, replacing the embedding merge as the primary
reunifier inside a category. Step 4's embedding merge survives only for its
original job: folding near-duplicate namings across categories.

That restriction arrives with the consolidation pass, not before it. §13's
slice 4 ships the unchanged global merge, which does fold within a category as
well; the case for relaxing it there, and where it is reinstated, is stated
under that slice.

This is a re-forming of the map, not a patch on it. Patching would leave nodes
made on the wrong principle and merely merge some of them back together.

### The noise policy

Category assignment carries model disagreement — roughly one claim assignment
in four is disputed between two models. Under embedding bagging a borderline
passage lands near its neighbours; under category grouping a misassigned
passage sits in the wrong bag with no path back, because merge reunites
namings, never passages. The policy, stated rather than silent: **a passage is
assigned to exactly one category per axis, the error rate is accepted, and it
is quoted next to every comparison the re-formed map is judged by.** Dual
membership is rejected — #822 measured what duplicate membership costs at
assembly, and an assignment pass that hedges is a scheme that no longer
partitions. If the measured loss from misassignment turns out to dominate the
structural gains (§13 slice 5 would show it), a one-shot adjudication pass over
borderline assignments is the fallback, and it is a new decision, not part of
this design.

**A refusal on the inner axis does not cost a passage its group.** The chosen
inner split is `claim` × `mechanism` (measured in
[#828](https://github.com/Muhanad-husn/axial/issues/828)), and on the real
corpus 797 of 6,010 selected passages form no cell: 780 hold a `claim`
category and no `mechanism` one, 9 the reverse, 8 neither. Dropping all 797
would leave 13.3% of selected passages beyond any position, against the 6.9%
ceiling §13's D4 allows. So the 780 are grouped by `claim` alone, in a
distinctly labelled claim-only cell per category, and read like any other
group; only the 17 with no `claim` category at all stay ungrouped, and they
are counted in the variant's `map.json`. Founder ruling, 2026-08-29, in
[#829](https://github.com/Muhanad-husn/axial/issues/829).

The fallback did what it was for and did not clear the ceiling it is argued
against. The built variant lands at **8.54%** beyond any position (513 of
6,010), still above D4's 6.9%. Only 0.28% of that is grouping loss; the rest
is the extraction model declining more passages when it is shown twenty at a
time instead of three (`unassigned` 457 against the default build's 373).
Whether that fails the variant or fails D4 as a guard is the comparison's
verdict, not this section's.

### What a position carries afterwards

A re-formed position inherits the category values its passages hold, on every
axis. Call it the position's **profile**. It costs nothing — a join over
material the interrogation already produced.

The profile does two things:

**It decides where to spend the model on relations.** The space of possible
position pairs is far too large to ask about exhaustively, which is exactly why
relations today are thin and partly incidental — only 492 of 1,328 asserted
relations cross authors, and the neighbourhoods they were asked in were built
by argument-sentence similarity, the same wording trap as the bagging.
Profiles rank the pairs: same region, opposed stance, different books is where
a real disagreement is likely. The model still decides every relation (§10).

**It gives the map an address.** A question lands on a region of the debate
before it lands on any single position. The map gains a coarse layer it has
never had, and that layer is what a reader navigates.

## 7. Retrieval, and where the time comes back

A question does not land on one axis. It lands on several at once.

"State formation in Syria" pins the claim and mechanism axes, possibly the
stance axis too. The intersection of two or three axes is small **before any
model call happens**. Syria is applied at the end, to narrow what came back.

Today a query enters through the name, which is the **least** discriminating
thing in the corpus — Syria appears in nearly every book — so everything after
that is work spent narrowing. Reversed, the query enters through the most
discriminating thing and narrows with the least. The walk becomes: question →
region → positions → relations → passages. Bounded, few calls, no tool loop,
and no round trips spent discovering that a name reached nothing.

Honest accounting: the raw speed advantage over the name layer is already
banked by the map arm as it exists. What this section adds is the *entry
point* — a question addressed to the debate's structure instead of resolved
through a name — and the removal of the machinery that made the name entrance
necessary.

## 8. Names are demoted, not deleted

Places, people, periods, works stay reachable. What changes is their job.

**A name is not an axis.** There is no "more Syria", no opposite of Syria. An
axis has values that stand in relation to one another — one causal story rivals
another, one stance opposes another. That is what makes an axis navigable. A
name is a membership list. You can intersect a list with a result; you cannot
reason along it.

| | |
|---|---|
| **Retired** | The page per name. The pass that manufactures disagreement across those pages. The retrieval loop that walks them. And the premise underneath: that sharing a name is a connection. |
| **Kept** | One index from a name to the passages that mention it, with spelling variants folded so a thing has a single entry. Ask for Syria, or Mann, or a period, and you are told where it is discussed. |

A name becomes a **filter over results**, never a join that forms them. It
answers "where is this discussed" and never "what is being argued". The cherry,
not the cake.

## 9. What this lets go, and when

- The name pages as a structure, and the machinery that manufactures them.
- The pass that reads across name pages looking for disagreement.
- The tool-driven retrieval loop built to walk that structure.
- The residue pass. It exists to rescue what the old clustering left out; once
  categories decide what is comparable, there is no leftover of that kind —
  and measured, the category path loses *fewer* passages than the bagging does
  (a half-percent refusal on `claim` against several hundred passages the
  current build places nowhere or leaves unassigned).
- Embedding-based bagging as the thing that decides what gets read together.
  It survives only demoted, as an inner sizing split (§6), if measurement
  picks that variant.
- The separate derive-and-assign machinery's measurement apparatus. The
  drafting tool and the assign pass stay (§4); the instrumentation goes.
- The evaluation apparatus — **last, not first.** It could not tell three
  retrieval methods apart when finally asked, which is exactly why the
  re-formed map is validated structurally (§13) before any judged gate is
  trusted again. Demolition of the eval code happens after the comparison has
  been run with it available, not before.

**Ordering rule for all of it: nothing on this list is deleted until the
re-formed map has been built and compared against the current one.** The
demolition comes after the comparison. This is subtraction from a working
system, not a rebuild. The substrate — extraction, chunking, interrogation —
is sound, expensive to reproduce, and untouched.

## 10. Four conditions

**The category list is committed once and pinned.** The same prompt on the same
model produced lists of different sizes on different runs. A category system
that reshuffles between runs is not an index. It is committed configuration,
versioned, changed deliberately or not at all. (`config/vocabulary.yaml`
already has this shape.)

**A shared category is not a relation.** This is exactly where the last
implementation went wrong: it treated a shared category as a connection between
passages, which reproduces the name layer's mistake with better labels. Sharing
a category says only that two things sit in the same region. That is a reason
to ask whether they relate. It is never the answer.

**The model decides every relation.** Nothing mechanical may assert an
argument. Categories select, rank and propose; a model reads two positions and
says how they stand, or says they do not. The scholarship is in that judgment
and cannot be produced by a join.

**One passage, one category per axis.** The noise policy of §6: no dual
membership, no hedged assignment, the error rate quoted rather than hidden.

## 11. What this does not settle

**Which axes earn a place.** Not every question categorises usefully. The test
already exists and is not to be reinvented: the five conditions of the
categorisation run (coverage floor, blob condition, five-plus members crossing
books, agreement floor) are the entrance exam, and seven of twelve columns
pass it today. The axes are the survivors of that test, not the full list of
questions.

**How fine an axis should be.** Too coarse and every position sits in the same
region; too fine and it fragments the way the bagging already does. Granularity
was the dominant source of variance between runs of the same prompt. The
committed scheme freezes one answer per axis; whether it is the *right* answer
is judged by the same five conditions plus the structural comparison of §13,
and refined by editing configuration, never by re-deriving.

**Whether the codebook's existing five axes and the new ones are one system or
two.** Both are person-committed schemes a model applies. But the codebook's
five were designed as reading context, and the new ones as grouping criteria —
different jobs. Unify them only if a real need appears; nothing in §13 requires
it.

## 12. What happens to the work already done

Five slices shipped between #805 and #809. One was the wrong idea; four hold.

**Deleted — the category join (#807, PRs #821 and #823).**
`axial.argmap.vocabulary_join` makes two passages meet because they share a
category. That violates §10 directly: a shared category is not a relation. The
join goes, and the `map+vocab` arm goes with it. Tracked in
[#825](https://github.com/Muhanad-husn/axial/issues/825).

**Kept, and it is the valuable part — the mechanism category list (#806).**
Twenty categories in `config/vocabulary.yaml`, read and approved by a person,
and the corpus already filed against them under `data/vocabulary/`. That is
the curation work of §4, it is one of the two candidate inner axes of §6, and
it is what §2's cross-tab was measured against.

**Kept, demoted to a drafting tool — `vocabulary examine` (#805).** Somebody
still has to draft a category list from a sample before a person edits it.
That is all this does. The held-out scoring and the two-model cross-check
inside it are measurement, not drafting, and can go.

**Kept, now load-bearing — `vocabulary build` (#806).** Under §4 this pass is
*the* assignment mechanism, not a backfill afterthought: every axis, existing
corpus and future books alike, is assigned by it over the answer column, after
reading.

**Kept, unrelated to any of it — the sweep's arm recording (#808) and
`eval layers` (#809).** Which arm ran, at which commit, with how many distinct
sources cited, and a table comparing arms. Any future comparison needs both.

### One thing to record before it is misquoted

The three-arm comparison came back null: the grounding gate read a perfect
score on thirteen of fifteen cells, and every source-count difference between
`map` and `map+vocab` sat inside its own draw spread.

**That was a measurement of the join.** It says nothing about categories as a
grouping criterion, which is the use this document proposes and which was never
measured. Nobody should later cite the null as evidence against this approach.
It tested a mechanism now agreed to be the wrong one. The same saturation also
cuts the other way: that gate cannot *validate* this approach either, which is
why §13 measures structure first.

## 13. The work, in order

Each step is cheap, each can kill the plan early, and nothing in the name
layer is touched until the last. This is the section a tdd-plan starts from.

**Slice 1 — the claim vocabulary is committed and assigned.** Run the drafting
pass over the `claim` column, founder edits, the scheme is committed to
`config/vocabulary.yaml`, `vocabulary build` files the corpus against it.
Done when: `data/vocabulary/claim/` exists with its manifest, coverage and
refusals reported, scheme version pinned.

**Slice 2 — the diagnosis is confirmed or weakened on the claim axis.** Re-run
§2's cross-tab: current bags against claim categories. Free, offline, no model
calls. Done when: purity and scatter numbers for the claim axis sit in a run
log next to the mechanism ones. If wording bags turn out pure on the claim
axis, stop and rethink — the central diagnosis just weakened.

**Slice 3 — the inner split is chosen by measurement.** Build both §6
candidates offline over the claim cells — the `claim` × `mechanism`
intersection, and per-category embedding sub-clustering — and compare group
sizes, coverage lost to compounded refusals, and slice counts. No extraction
calls yet. Done when: one inner split is chosen in writing, with the two
tables beside the choice.

**Slice 4 — the map is re-formed once.** `map build --grouping category`:
category grouping (outer axis + chosen inner split), per-group extraction
unchanged, embedding merge retained and unrestricted in this slice. Run
against the same corpus pin as the current build. Done when: a complete
`positions.jsonl` exists under a variant directory, with the current build
untouched beside it. The second consolidation pass per category, and relations
over the variant, are their own slices after this one
([#829](https://github.com/Muhanad-husn/axial/issues/829) scopes both out).

§6's across-categories-only restriction on the merge is relaxed here. It
arrives with the consolidation pass
([#830](https://github.com/Muhanad-husn/axial/issues/830)), which is what
replaces the merge as the within-category reunifier (decided 2026-08-29, while
building #829). Imposing it now would leave nothing at all reuniting a
category's per-slice namings — the largest real group is 248 passages over
five extraction slices — so the variant would fragment for a reason #830
exists to fix rather than for anything D1–D5 measures. The merge's
within-category reach is quoted with those numbers, not hidden in them.

**Slice 5 — the structural comparison decides.** No judged gate, structure
only, both maps side by side. Five metrics decide, and the bar for each is
stated in full in [#831](https://github.com/Muhanad-husn/axial/issues/831):
**D1** book-spread ratio, size-matched against the build's own permutation
null; **D2** purity on the held-out `position` axis, size-matched, above the default
build's measured 0.7597 by more than its 0.0331 instability floor; **D3** member
coherence as a band-by-band floor; **D4** passages reaching no position,
counted as distinct chunk ids and not allowed to rise above 6.9%; **D5** a
blind paired hand-sample, 12 positions per build, judged before the labels are
revealed, as a veto. A forced replicate of the variant supplies the error bar,
and every margin is quoted against it; D2 additionally clears its
assignment-instability floor, **0.0331 purity points**, measured 2026-08-29 by
recomputing D2's baseline over a second model's draw of the `position` column
before the variant was built.

Position count, position size, single-passage share and the raw cross-book
rate are **context lines, never the verdict**: the first three move in the
"good" direction by arithmetic alone when 113–207 extraction calls replace
679, and the cross-book null is 96% at size two and 100% above it, so a binary
cross-book rate is saturated before the comparison starts. "Denser and more
cross-book" is not the test. Done when: a run log states the comparison
against D1–D5, names which failure conditions were and were not met, and
carries the founder's go/no-go on everything after it.

**Slice 6 — profiles and profile-ranked relations.** Positions inherit their
passages' category values; relation neighbourhoods are proposed from profile
rank (same region, opposed stance, different books) instead of
argument-sentence similarity; the relate pass itself is unchanged. Done when:
a relations build over the re-formed map reports its cross-author rate next
to the current build's.

**Slice 7 — retrieval enters through the map's address layer.** Question →
region (axis intersection) → positions → relations → passages, names applied
as a terminal filter. Done when: the sweep runs this arm end to end and
records it like any other arm.

**Slice 8 — demolition.** Only now, and only for what slices 5–7 made
redundant: name pages, gather, the name-walking retrieval loop, the residue
pass, the vocabulary measurement apparatus, and — last of all — the parts of
the evaluation code nothing remaining reads. Each deletion cites the slice
that made it safe.

---

*Revised after review, 2026-08-28. Everything above is architecture and logic;
§13 is the build order. The numbers quoted are measurements already taken —
including this revision's own cross-tab — not projections.*
