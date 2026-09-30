![Axial](axial-logo.png)

# Axial — the September rebuild

**What changed when the name pages went and the argument map became the wiki, and what that did to the answers**

Version 1.0 · 1 October 2026 · Muhanad Abulhusn

*This is an update to the [research report](axial-report.md) and the [engineering report](axial-technical-report.md), both of 7 August 2026. Where they describe name pages, the Gather pass or the `name` retrieval arm, read this first: those parts no longer exist. Everything else they describe stands. The decision behind the change is DEC-75 (28 September 2026); the decisions that closed it are DEC-76 (1 October 2026). The engineering record is [dec-75-outcome.md](dec-75-outcome.md).*

---

## Summary

In late September Axial was rebuilt around one idea: the argument map, not the name, is where the books meet. Until then the system had three ways of saying how two passages connect (a shared name, a shared stake, a shared category) and kept the full machinery for all three. The name layer alone meant 47,584 pages, of which 83% linked to a single book, and a pass that cost $4.94 every time it ran. Nothing in the final output ever read one of those pages: every claim in a paper cites a passage directly.

So the name pages went, and the argument map took their place. The wiki is now one page per position, 1,937 of them, with every relation between positions drawn as a link, so the graph view shows who argues with whom. Each relation was given a type (one position supports, contests or is preferred to another), and a new pass looked for relations between authors who never cite each other, roughly doubling them.

**The result is a system that is much smaller and better organised, and whose answers are as good as before, not better.** Nothing regressed. Answers use the new relations, but they do not cite more books, and they still engage disagreement between authors less than they could. The most useful finding was about the questions rather than the system: how many books an answer draws on is decided by what the question asks, not by how much the retrieval finds.

The work ran as twelve issues and seventeen merged changes over four days, and the paid runs cost about $20.

---

## 1. What changed

| change | what it did |
|---|---|
| name pages, Gather and the `name` arm removed | 47,584 pages gone; the wiki fell from 299 MB to 178 MB; about 15,000 lines of name-layer code removed; Gather's $4.94 a pass gone |
| the argument map is the wiki | 1,937 position pages; every relation is a link on both ends; built by code, with no model calls |
| every relation has a type | 99.3% of 1,472 relations typed for $0.025; 13% of them are conflicts |
| names shared across five or more books linked to Wikidata | 36% of 1,343 names resolved, about 95% of them correctly; it exposed 15 merge mistakes in the name layer |
| the topic vocabulary can be exported | `about` and `move` are part of the fixed vocabulary; it exports to SKOS and maps onto the ELSST social-science thesaurus |
| new relations between authors | relations between different authors rose from 629 to about 1,170, for $0.90; positions with no relation at all fell from 432 to 321 |

Two further experiments tried to build a better map outright: one with a stronger model reading the same material, one grouping passages by who argues against whom. Each was judged against a bar written before it ran. Neither cleared it, and the map was not rebuilt. Together they cost about $10.

---

## 2. What it did to the answers

The answers were measured twice. First on the five short test briefs the system has always been checked against, then on ten new briefs written for this purpose, each asking a question that needs several books set against each other. Each brief was answered three times in each condition; a difference counts only where the three answers of one condition sit wholly clear of the other's.

| per answer, ten cross-book briefs | before | after |
|---|---:|---:|
| books cited | 4.67 | 4.50 |
| positions on the map cited | 5.3 | 6.9 |
| positions cited that only the new relations reach | 0 | 2.3 |
| conflicts where both sides are cited | 31% | 29% |
| cost | $0.054 | $0.060 |

**The new relations are used.** On nine briefs of ten, answers cite positions that only the new relations lead to, about two per answer.

**The answers are not broader.** Books cited did not move on any brief. They are higher on the new briefs than on the old ones (4.6 against 3.5), but in both conditions alike: the questions moved it, not the system. One old brief shows why. It is about a single territory, and it puts nineteen books in front of the model and cites one, because one book is what the question calls for.

**Disagreement is still under-used.** When two contesting positions both reach the model, it cites both sides about three times in ten on the new briefs, and less than one time in ten on the old ones. Telling the model explicitly which passages contest which changed nothing measurable.

**Nothing got worse.** Every answer's citations still resolve to real passages, and an answer still costs about six cents. Of 120 answers across all runs, three failed; none of the failures traces to the rebuild.

---

## 3. What it gained, and what it did not

**Gained.** A much smaller system, without the cost that bought nothing. A wiki that shows the structure of the argument instead of a pile of name pages. Relations that carry a type a program can act on. Names tied to a public identifier where it matters most. A vocabulary that other tools can read. And a better test: ten briefs that can show breadth, which the old five mostly could not.

**Not gained.** Answers that cite more books, or that set opposing authors against each other more often. The new relations were also judged slightly less sound by hand than the old ones (16 and 14 of 20 against 17 of 20), and only about a third of the shared names found a Wikidata match.

**Unchanged.** No human expert has yet judged any output. Every figure here measures the engine against questions an AI model wrote, which is the limit the research report ends on and still the most important one.

---

## 4. What was decided

- Retrieval is no longer tuned to make answers broader. Breadth follows from the question.
- The new relations stay.
- The ten cross-book briefs are how answers are measured from now on; the five old briefs remain as pass/fail checks only.
- Getting answers to engage disagreement is parked. Before it is reopened, one brief whose answers show conflicts and never cite both sides will be read by hand.
- One question remains open: whether a public export of the argument map, in the formats the field uses (AIF, SKOS, CiTO), is wanted at all.

---

## Final word

The rebuild did what a clean-up should: it removed what the output never used and gave the remaining structure a shape both people and code can read. It did not make the answers better, and it was never going to by itself. The next gains will come from the questions people actually bring and from a human reading what comes back, not from more work on retrieval.
