# Positions, not names

**An architecture approach for Axial. Draft, 2026-08-28. Written to be argued
with and edited, not to be implemented as it stands.**

The map is right and stays. What was missing is a sense of what a passage is
about, and the interrogation has been producing it all along. The map gets
re-formed around it. The name pages go.

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

**The map's manufacture is not.** See §5 for exactly how a position is formed
today. The short version: the passages a model is allowed to read together are
chosen by wording similarity, so the model is asked what recurs inside a group
assembled on the wrong principle.

### The other defect is time

The application works. The answers are good. They take far too long to arrive,
and the wait sits in the name layer and the retrieval built on it — the
resolution tiers, the page index, and a tool loop that circles back many times.

Measured over the same briefs at the same commit, a draw through the name layer
ran roughly four times as long as the same draw through the map, and cost more
than three times as much, with no advantage in grounding.

## 3. The substrate

Every passage is interrogated once with the same open questions. What does it
claim, whose position is it, who does it argue against, what causes what and in
what order, what does it name.

That is what makes two passages comparable at all. Everything above reads it,
and nothing above is worth keeping if it is disturbed.

**The interrogation is the one layer this approach does not touch.**

## 4. Categorisation is curation, not research

This is where the last implementation went furthest astray, and where the
simplification is largest.

### What already exists

`config/domains/syria/codebook.yaml` holds **67 hand-written categories across
five axes** — field, claim type, empirical scope, theory school, role in
argument. Each carries a definition, a positive example, and a negative example
naming which category it belongs to instead. Bellicist, neo-bellicist, external
statebuilding, materialist.

That is a codebook in the ordinary social-science sense. Data scientists have
built these for decades. It is committed by a person, applied by the model
**while it reads a passage**, and it has been in the repository the whole time.

### What was built instead

The derived-vocabulary work rebuilt the same idea from scratch for the twelve
free-text answer columns: a separate pass proposes a category list from a
sample, a person commits it, a second pass assigns the whole column, and the
result is persisted as its own artifact.

Two mechanisms for one job. And around the second one, a measurement apparatus —
disjoint held-out samples, a second model cross-checking the first, a refusal if
the two tiers resolve to the same model. That is instrumentation, not
categorisation.

### The simplification

**Put the axes you want in the codebook, and have the interrogation assign them
at read time.** One pass. No derive step, no assign step, no separate artifact.

A category list is a list of names with a definition and two examples each. It
is written by a person who knows the field. A model can draft it from a sample
in an afternoon, and that draft is a starting point for the person, not an
output.

**The one honest cost:** notes already interrogated were never asked about the
new axes, so each added axis needs a one-question re-ask over the corpus. The
repository has already done exactly this once, for a question added late.

### Not all axes are equal

Some axes **constitute** a position — what is claimed, the stance taken, the
causal story, what it argues against. Those say what somebody asserts.

The rest **describe** it — what it is about, where and when it holds, what
evidence it rests on, what it concedes.

Only the constitutive axes should decide how passages are grouped. The
descriptive ones narrow and address. Keeping that line is what stops the
grouping from fragmenting.

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

### The correction this makes to an earlier reading

Distance does **not** decide what a position is. The model already decides —
step 3 is exactly the judgment call, with reasoning on, and it is already
proven.

What distance decides is **which passages the model is allowed to read
together**. That is the defect. A bag is nine passages that *sound alike*, and
inside a group assembled by wording there is often nothing that recurs beyond
the wording. Hence 660 bags yielding 2,206 arguments, and a median position of
two passages.

## 6. The change

**Swap the bagging criterion from wording similarity to shared categories.**

Steps 1, 3 and 4 stay exactly as they are. Step 2 is the only thing that moves.

The bag step embeds the `claim` field, so `claim` is the column whose categories
decide whether this works at all — same field, grouping criterion swapped. It is
the first axis to get right.

A group is then passages that answer the same question the same way, which is a
group where "what recurs here" is a real question with a real answer.

This is a re-forming of the map, not a patch on it. Patching would leave nodes
made on the wrong principle and merely merge some of them back together.

### What a position carries afterwards

A re-formed position inherits the category values its passages hold, on every
axis. Call it the position's **profile**. It costs nothing — a join over
material the interrogation already produced.

The profile does two things:

**It decides where to spend the model on relations.** The space of possible
position pairs is far too large to ask about exhaustively, which is exactly why
relations today are thin and partly incidental. Profiles rank the pairs: same
region, opposed stance, different books is where a real disagreement is likely.

**It gives the map an address.** A question lands on a region of the debate
before it lands on any single position. The map gains a coarse layer it has
never had, and that layer is what a reader navigates.

## 7. Retrieval, and where the time comes back

A question does not land on one axis. It lands on several at once.

"State formation in Syria" pins the claim and mechanism axes, possibly the
stance axis too. The intersection of two or three axes is small **before any
model call happens**. Syria is applied at the end, to narrow what came back.

### Why this is faster, structurally

Today a query enters through the name, which is the **least** discriminating
thing in the corpus — Syria appears in nearly every book — so everything after
that is work spent narrowing. Reversed, the query enters through the most
discriminating thing and narrows with the least.

Same information, opposite order, far fewer steps. The walk becomes: question →
region → positions → relations → passages. Bounded, few calls, no tool loop, and
no round trips spent discovering that a name reached nothing.

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

## 9. What this lets go

- The name pages as a structure, and the machinery that manufactures them.
- The pass that reads across name pages looking for disagreement.
- The tool-driven retrieval loop built to walk that structure.
- The residue pass. It exists to rescue what the old clustering left out; once
  categories decide what is comparable, there is no leftover of that kind.
- Embedding-based bagging as the thing that decides what gets read together.
- The separate derive-and-assign vocabulary passes, folded into the codebook and
  the interrogation.
- The evaluation apparatus, which is a large share of the codebase and could not
  tell three retrieval methods apart when it was finally asked to.

This is subtraction from a working system, not a rebuild. The substrate —
extraction, chunking, interrogation — is sound, expensive to reproduce, and
untouched.

## 10. Three conditions

**The category list is committed once and pinned.** The same prompt on the same
model produced lists of different sizes on different runs — `position` five
categories then fifteen, `stops_holding` seven then twenty, `mechanism`
thirty-six then twenty. A category system that reshuffles between runs is not an
index. It is committed configuration, versioned, changed deliberately or not at
all.

**A shared category is not a relation.** This is exactly where the last
implementation went wrong: it treated a shared category as a connection between
passages, which reproduces the name layer's mistake with better labels. Sharing
a category says only that two things sit in the same region. That is a reason to
ask whether they relate. It is never the answer.

**The model decides every relation.** Nothing mechanical may assert an argument.
Categories select, rank and propose; a model reads two positions and says how
they stand, or says they do not. The scholarship is in that judgment and cannot
be produced by a join.

## 11. What this does not settle

**Which axes earn a place.** Not every question categorises usefully. Some
produce one undifferentiated blob; some are refused too often to be an axis at
all. The axes are the ones that survive that test, not the full list of
questions.

**How fine an axis should be.** Too coarse and every position sits in the same
region, so the axis discriminates nothing. Too fine and it fragments the way the
bagging already does. This is a judgment per axis and it needs a stated test for
when a list is right.

**What happens to passages that sit nowhere.** A passage with no category on any
constitutive axis cannot be placed. Whether it stays reachable, and how, is
unresolved. It is the residue problem returning under a new name, and it should
be answered rather than assumed away.

**Whether the codebook's existing five axes and the new ones are one system or
two.** The codebook's axes are applied at read time and are tag-shaped. The new
ones would be too, under this approach — which suggests one system, but the
existing five were designed for a different job and may not carry this one.

## 12. What happens to the work already done

Five slices shipped between #805 and #809. One was the wrong idea; four hold.

**Deleted — the category join (#807, PRs #821 and #823).**
`axial.argmap.vocabulary_join` makes two passages meet because they share a
category. That is the condition in §10 violated directly: a shared category is
not a relation. It reproduces the name layer's mistake with better labels. The
join goes, and the `map+vocab` arm goes with it. Tracked in
[#825](https://github.com/Muhanad-husn/axial/issues/825).

**Kept, and it is the valuable part — the mechanism category list (#806).**
Twenty categories in `config/vocabulary.yaml`, read and approved by a person,
and 5,315 passages already filed against them under `data/vocabulary/`. That is
the curation work of §4, and it is exactly what a re-bagged map must be tested
against.

**Kept, demoted to a drafting tool — `vocabulary examine` (#805).** Somebody
still has to draft a category list from a sample before a person edits it. That
is all this does. The held-out scoring and the two-model cross-check inside it
are measurement, not drafting, and can go.

**Kept, probably as the backfill — `vocabulary build` (#806).** Adding an axis
to an already-interrogated corpus means assigning existing notes against a list
without re-reading every passage. That is this pass, and it is the same job
`position_backfill` already does for a late-added question.

**Kept, unrelated to any of it — the sweep's arm recording (#808) and
`eval layers` (#809).** Which arm ran, at which commit, with how many distinct
sources cited, and a table comparing arms. None of it is tied to the
vocabulary, and any future comparison needs both.

### One thing to record before it is misquoted

The three-arm comparison came back null: the grounding gate read a perfect score
on thirteen of fifteen cells, and every source-count difference between `map`
and `map+vocab` sat inside its own draw spread.

**That was a measurement of the join.** It says nothing about categories as a
bagging criterion, which is the use this document proposes and which was never
measured. Nobody should later cite the null as evidence against this approach.
It tested a mechanism now agreed to be the wrong one.

---

*Written after the session of 2026-08-28. Everything above is architecture and
logic. Nothing here is an implementation plan, and the numbers quoted are
measurements already taken, not projections.*
