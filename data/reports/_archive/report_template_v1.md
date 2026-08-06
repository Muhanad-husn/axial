![Axial](axial-logo.png)

# Axial — a report for the general reader

**What it is, how it was tested, and what the tests showed**

Version 1.0 · 1 August 2026 · Muhanad Abulhusn

---

## Contents

- [Introduction](#introduction)
- [Test Design and Evaluation Methodology](#test-design-and-evaluation-methodology)
- [Sources](#sources)
- [Coverage of the Library](#coverage-of-the-library)
- [Test Cases – Short Briefs](#test-cases--short-briefs)
- [Test Cases – Hard Briefs](#test-cases--hard-briefs)
- [Final Note](#final-note)

---

## Introduction

Axial reads a shelf of academic books and writes an encyclopaedia about them.

Not a summary of each book. An encyclopaedia of what the books say to each other. The unit is not the volume and not the chapter but the **passage** — a few paragraphs long, about the size of one complete move in an argument. Axial reads every passage in the library, one at a time, and writes down what that passage says. Then it builds a page for every name any passage mentions: every scholar, every country, every institution, every concept. A name's page lists the passages that mention it, and says what the authors gathered there disagree about.

The result reads like a short book split into entries, each entry a little Wikipedia article — except that no human wrote them, and every sentence traces back to a passage in a real book.

### Why read passage by passage

The obvious way to make a machine useful over a library is to let it search for keywords and then summarise whatever it finds. That approach has a known failure: the machine finds text that *sounds* relevant and writes something plausible on top of it. Nobody can check it, because nothing links the sentence to the page it came from.

Axial inverts the order. Nothing is retrieved until everything has been read. Each passage is interrogated once, in isolation, before anyone asks a question. The interrogation is deliberately open-ended — the model is not given a list of boxes to tick. It is asked what the passage says, and it answers in its own words.

The rule that governs the whole reading is short: **answer only from the passage in front of you.** The model is told not to use anything it knows about the book, the author or the subject from anywhere else, and not to look anything up. Where the passage does not support an answer, it must say so explicitly. An abstention is a normal, expected answer. A guessed answer is treated as worse than no answer at all, because a reader cannot tell a guess from a reading.

### The questions every passage is asked

Sixteen questions, the same sixteen for every passage in every book:

1. **About** — what is this passage about? Short phrases, in your own words.
2. **Claim** — what is being claimed, in one sentence.
3. **Move** — what is this passage *doing* in the argument? Not a label like "evidence" but the move itself, for example "conceding a point in order to narrow it".
4. **Ranges over** — what does the claim cover?
5. **Stops holding** — where does the author say it stops being true?
6. **Position of** — whose position is this? Name the holder and nothing else: the author's own, a named scholar, a named school, a group the passage describes.
7. **Position** — what *is* that position, in the passage's own terms? One sentence stating the stance itself.
8. **Arguing against** — who or what is it arguing against?
9. **Names** — every named thing: people, places, institutions, events, movements, periods, and any figure or table the passage names, each with what kind of thing it is.
10. **Citations** — who does it cite, and is each citation used as support, as a foil, or as an authority?
11. **Mechanism** — what causes what, in what order.
12. **Evidence** — what evidence is offered.
13. **Comparison** — what comparison is made, stated or implied.
14. **Defines / uses** — what is defined here, and separately, what is merely used without being defined.
15. **Concedes** — what the author concedes or hedges.
16. **Assumes** — what it assumes without saying.

Three of those questions do double duty: what a claim covers and where it stops; whose position it is and who it argues against; what is defined and what is only used. Together they produce a record of seventeen fields per passage.

Two answers carry most of the weight. **Names** is how passages find each other: two passages that both mention Charles Tilly end up on the same page, whether or not their authors ever met. **Arguing against** is how disagreement becomes visible: an author who names an opponent has done the work of locating the dispute, and Axial simply records it rather than inferring it.

### How a book is split, and what travels with each piece

A book arrives as a PDF or a Word file. Before anything is read, its structure is recovered — chapters, sections, headings, tables, figures, footnotes, the index, the bibliography. Front and back matter that carries no argument is set aside and recorded as set aside, not silently dropped. Tables and figures go to their own pool. Only the running prose goes forward.

That prose is then cut into passages. The cut follows the author's own paragraph and sentence boundaries, never a fixed word count, and every passage is kept inside a size band — roughly 3,500 to 9,000 characters, or one to four pages of a printed book. The size is chosen for the questions above, not for storage. A claim and the evidence for it usually sit several paragraphs apart; a smaller window would catch half an argument and produce abstentions for want of text rather than for want of an answer. The cutting involves no AI at all. It is mechanical, repeatable, and inspectable before a single penny of model spend.

Nothing is read out of context. Before the interrogation begins, one pass over each book extracts what the book itself says it is doing: the author's stated thesis, the scope, the argument as stated, and a reconstructed table of contents — grounded in the book's own prose, never in what a model might know about the title. That context travels with every passage. So does the source's author, title and date, read from the file itself, and the chapter and section heading the passage sits under. A model reading one paragraph of a book it has never seen otherwise has no idea what the book is arguing. Here it always does.

### The pipeline, step by step

**Intake.** Accept the file. Check it has real text and is not a scan. Read the author, title and date. Check whether the file contains the whole work it claims to be, and flag it if not.

**Structure.** Rebuild the book's hierarchy. Repair the damage that PDFs do to text — broken hyphens, mangled spacing, stray glyph names. Sort every block into prose, artifact, or apparatus.

**Envelope.** One pass per book to capture its thesis, scope, stated argument and contents.

**Chunking.** Cut the prose into passages, mechanically, inside the size band.

**Artifacts.** Route tables and figures to their own pool with their captions and provenance.

**Interrogation.** One pass per passage: the sixteen questions above. This is where the library is actually read.

**Reconciliation.** The same person, place or idea appears under many names — "Charles Tilly", "Tilly", "C. Tilly 1975". These are gathered, compared, and merged where they are genuinely the same thing. Merging is reversible, and the merge decisions are recorded.

**Materialisation.** The encyclopaedia is written. Every passage becomes a page carrying its own answers. Every surviving name becomes a page listing the passages that mention it. This step involves no AI: it is a rendering of what the previous steps produced.

**Gathering.** For each name, the claims made at that name are put side by side and the question is asked: what do these authors disagree about? The answer is written onto the name's page. This is the step that turns a library into a conversation.

Then, and only then, can a question be asked.

**Asking a question.** A question arrives as a short brief: a case and a request. It is first interrogated in its own right — does the library actually cover this, are there hidden assumptions in the way it is phrased, should the answer be bounded, or should the question be refused outright? Refusing is a legitimate outcome, not an error.

**Searching.** If the question proceeds, the engine walks the name pages: it resolves the phrases in the question to names the library holds, reads who is gathered at each, follows who cites whom and who argues against whom, and re-queries when a result comes back thin. Every step is logged with the exact pages it touched.

**Answering.** The evidence gathered is assembled and shown before the expensive step runs. Then the answer is written as a list of numbered claims, and every claim is marked for what kind of claim it is:

- **(a)** something a source says, cited to the passage that says it;
- **(b)** an inference Axial itself has drawn across sources, marked as its own;
- **(c)** speculation, marked as speculation.

Every (a) and (b) claim points at the passages behind it. Nothing is written first and cited afterwards.

**Checking.** Mechanical checks then run outside the model's control. Does every claim carry a kind? Do all its cited passages actually resolve? Is there a counter-position — the strongest version of the argument against the answer's own conclusion — or an explicit statement that the library is one-sided on this question? Is there a coverage map saying how much evidence each name in the answer actually rests on, and a confidence band that cannot exceed what that coverage supports? A failed check blocks the answer.

That last mechanism is worth naming plainly. If an answer leans on a name the library holds only three passages about, the answer's stated confidence is pulled down to match, whatever the writing model thought of itself. Confidence is capped by evidence, not by tone.

### How it was tested

Axial was smoke-tested on **six short briefs**, then run on **three much harder cases**. On one of those three, a combination of open-source models was set head-to-head against a combination of proprietary ones, on the same question and the same library at the same moment.

The six short briefs were each chosen to stress a different shape of search:

| Brief | Why it was chosen |
|---|---|
| **P3-04** | The library's centre of gravity. Its anchor, `Syria`, carries 962 passages across 22 books — the case where one huge name can swamp everything else. |
| **S-01** | Scholar against scholar over a densely covered question: Tilly (154 passages, 20 books) against Mann (377 passages, 15 books). |
| **S-02** | A concept several books use in incompatible ways: `nationalism`, 158 passages across 18 books. |
| **S-03** | A concept whose own founding book is on the shelf: `quasi-states`, 51 passages but only 5 books. |
| **S-04** | Thin coverage. `Transnistria`: 36 passages, 2 books. Does the engine notice it is thin without being told? |
| **S-05** | Single-source concentration. `Somaliland`: 52 passages, all from one book. Does the engine say so? |

S-04 and S-05 deliberately do **not** tell the engine what they are testing. An earlier draft asked about "the library's thin evidence on Transnistria". Naming the finding in the question would have made a pass prove only that the model follows instructions.

The three hard cases are long, compound questions of the kind a doctoral examiner would set: they require weighing four or more competing explanations, testing a preferred account against a second historical setting, and engaging the critics of the major theorists rather than only the theorists themselves.

Every question and every answer is reproduced in full below, in [Test Cases – Short Briefs](#test-cases--short-briefs) and [Test Cases – Hard Briefs](#test-cases--hard-briefs). The measurement method is in [Test Design and Evaluation Methodology](#test-design-and-evaluation-methodology), and the library itself is listed in [Sources](#sources).

---

## Test Design and Evaluation Methodology

### How quality was judged

There is no single accuracy score, and none was invented. Quality was measured two ways.

**Mechanically**, by counting things that can be counted without an opinion: does every claim carry a kind and resolvable sources; how many of the books a question demands did the answer actually reach; how much evidence was gathered, how much reached the writing model, how much was cited; how many of Axial's own cross-source inferences rest on more than one book.

**By peer review.** Each answer was packaged into a sealed packet — the answer plus the full text of every passage it cites, and nothing else — and handed to an independent reviewer with no access to the code, the repository, or any other answer. The reviewer graded three dimensions (factual correctness, citation grounding, completeness) and listed every defect it could find, by kind: misattributed, unsupported, overconfident, contradicted, evasive, strawman.

The reviewer is a different vendor's model from the ones that wrote the answers, and it never grades its own work.

### Short briefs: the peer-reviewed result

The six short briefs were reviewed twice — once before a round of fixes, once after. The second round is the one that counts, and it is the most recent set of runs, each capped at 14 search steps.

| | Before fixes | After fixes |
|---|---|---|
| Factual correctness | 6 answers "adequate" | **5 "strong"**, 1 adequate |
| Citation grounding | 5 adequate, 1 strong | **4 strong**, 2 adequate |
| Completeness | **4 "weak"**, 2 strong | **5 strong**, 1 adequate, **0 weak** |
| Total defects found | 40 | **15** |

Four whole classes of defect went to zero: **misattributed** (crediting a position to the wrong person), **contradicted** (a claim its own cited passage argues against), **evasive** (dodging the hard half of the question), and **strawman** (arguing against a caricature nobody holds). What survives is the two softest classes — an inference reaching slightly past the passage it cites, and an emphasis the passage does not quite carry. Those are the defects a careful human editor argues about. The ones that disappeared are the ones that made an answer wrong.

Total cost for all six answers: **$0.77**.

### A check on the judge

Before any of those grades were trusted, the reviewer was tested. A copy of one answer was doctored with three planted defects — a claim's sources repointed to an unrelated passage, the counter-position replaced with a caricature, the confidence band raised against its own thin evidence — and handed to a fresh reviewer that was not told a control was running. It caught **all three**, named each correctly, and quoted the evidence contradicting each one. It also re-found the answer's genuine defects underneath the plants.

That test has a known asymmetry, and it is stated rather than glossed: it proves the reviewer catches defects that are there. Nothing tests whether it invents defects that are not. Its false-positive rate is unmeasured.

### Hard briefs: the model comparison

On the hardest of the three questions — the one requiring a committed judgment between two rival explanations of violence in the Syrian civil war — the same question was run twice against the same library, at the same moment, in two sealed processes that could not see each other's configuration. One process used only open-source models. The other used only proprietary ones.

| | Open-source arm | Proprietary arm |
|---|---|---|
| Reading the question | `z-ai/glm-5.2` | `openai/gpt-5.4` |
| Searching the library | `deepseek/deepseek-v4-pro` | `openai/gpt-5.4` |
| Writing the answer | `moonshotai/kimi-k3` | `openai/gpt-5.6-sol` |
| Writing the counter-position | `moonshotai/kimi-k3` | `openai/gpt-5.4` |
| **Cost** | **$0.39** | **$0.89** |
| Books reached | 7 | 5 |
| Required books reached | **4 of 5** | 3 of 5 |
| Claims in the answer | 16, of which 5 are Axial's own inferences | 17, of which 9 are |
| Inferences resting on two or more books | 4 of 5 | 9 of 9 |

**The sealed reviewer, working blind, chose the open-source answer — and called the margin narrow.** Both scored "strong" on factual correctness and on citation grounding. They split on completeness: open-source "strong", proprietary "adequate".

The reason the reviewer gave is specific and worth repeating, because it is the kind of error that is easy to miss. Both answers cite the same passage from Üngör on paramilitary violence, which argues that paramilitaries emerge where states cannot monopolise violence and where outside powers quietly sponsor armed groups — *rather than from cultural divisions alone*. The open-source answer read that as written: a structural argument, and an argument against culture-first explanations. It then used the passage to test its own conclusion. The proprietary answer used the same passage **against its own thrust**, to prop up an account built on the production of sectarian identity. The reviewer also credited the open-source answer for anchoring its judgment in the Daraa case — the most granular ground-level evidence in its packet — and for stating the position it rejected in that position's strongest form.

So the proprietary arm cost 2.3 times as much, reached fewer books, and read one of its key passages backwards.

**This is not decisive, and it should not be read as decisive.** Three reasons, all of them structural:

1. **The test cases are AI-simulated.** All nine questions in this report were written by a model, not by a working academic. Every figure here measures the engine, never answer quality against a real scholarly question.
2. **One reading, one judge.** N = 1 per cell. There is no spread, so no grade is a measurement — each is one reviewer's opinion on one reading, and the reviewer's own false-positive rate is unmeasured. One of the short briefs has been measured moving 39% between two runs of identical code on the identical question, so single-run differences smaller than that are not signal.
3. **Four models moved at once.** The two arms differ in every one of their four roles. The comparison measures two complete wirings. It cannot say which of the four swaps produced the result.

What it does support is narrower and still worth saying: **open-source models are competitive in production for this kind of work, at a fraction of the cost.**

### The other two hard questions

The two long comparative questions (A and C below) were run on the open-source stack only, at two different search budgets — 14 steps and 20 steps — to settle whether searching harder produces better answers.

It does not. Across four paid runs, the amount of evidence that actually reached the writing model never moved — 17, 21, 18, 20 passages — while the amount *gathered* ranged from 56 to 181. Question C at the higher budget gathered 181 passages across 15 books, nearly double its own run at the lower budget, and put **one fewer passage** in front of the model. Question A's six extra steps cost 65% more and delivered one extra passage.

The wall was never the constraint. The constraint is that the writing step reads about twenty passages however much is gathered. The budget stays at 14.

### What the engine does badly, stated plainly

- **Reaching every required book is the weak spot.** Each hard question names the books a good answer must reach. Question A decomposed the claim that war made the modern state without ever citing Tilly. Question C reached two of six required books at the lower budget, three of six at the higher. Both runs of question B missed the book carrying one of the two explanations the question asks them to weigh.
- **The bottleneck is the writing step, not the search.** About twenty passages reach the model no matter how many are gathered. No retrieval change made in this phase has moved it.
- **A judged number drawn once is indistinguishable from noise.** One quality metric was re-scored three times on identical input and returned 0.571, 1.000 and 0.000 before the cause was found and fixed. Metrics drawn once are reported as one draw, not as measurements.
- **A shared judgment call is unresolved.** When a chapter sits inside a book edited by someone else, the passage is credited to the volume's editor rather than the chapter's author. This was found by the reviewer, deferred deliberately, and produced no defects in the second round — but it will recur.

### A note on how the answers are presented here

Each answer below is reproduced as the engine produced it. One presentational change was made for readability: each claim's citations are stored internally as exact passage identifiers, and are rendered here as the book they came from, with a count where a claim rests on more than one passage from the same book. Nothing was added, removed, or reworded. Every claim in the underlying record still points at the exact passage behind it, down to the section heading and the position within it.

---

## Sources

Thirty-one books and papers, 10,314 printed pages. Publisher and page count are read from library records; author, title and date are read from the file itself.

{{SOURCES_TABLE}}

The library is deliberately lopsided. It is built around comparative-historical political sociology — state formation, nationalism, political violence, sovereignty — with Syria and the wider Middle East as the empirical centre. That is a research corpus, not a balanced encyclopaedia, and every result in this report is bounded by it.

**Three notes on the table.** Michael Mann's *The Sources of Social Power* appears as four separate volumes, because they are four separate books with different arguments. Five entries are edited collections, and chapters inside them are currently credited to the volume's editor rather than to the chapter's author — a known limitation, recorded above. And three entries carry no publisher in the library record; rather than fill the gap from memory, they are marked "not recorded".

---

## Coverage of the Library

How lopsided the library is has been measured, not estimated, and the measurement is reported separately in **[*Axial — what the library covers, and what it does not*](axial-coverage.md)**. It counts how the 6,092 passages spread across the 49,674 name pages the library produced: how many passages sit at each name, how many different books those passages come from, and which topics are covered at length by only one author.

That companion document is the right place to look for two things this report does not settle. The first is how much weight any particular name can bear — the test questions above were chosen against exactly those counts, and the same counts say which other questions this library could answer well. The second is which book to add next, which the coverage figures answer far more directly than a reading of the shelf would.

One finding from it belongs here, because it bounds every result below: **about 84% of the library's name pages exist inside a single book**, and only 329 of the 49,674 pages carry enough passages from enough different books to support a comparison between authors. The library is not thin — it is deep in a small number of places and single-voiced almost everywhere else.

---

## Test Cases – Short Briefs

### How the questions were written

The questions were not written by the people who built the system, and not inside it.

Five of the six (**S-01** through **S-05**) were written by **GPT-5.6 Pro**, working from a measurement of what the library actually contains — how many passages sit at each name, and across how many books — with no access to the code, the engine, or any previous answer. **P3-04** was written earlier by **GPT-5.6 Terra**, working from a description of the research domain alone.

### How the set was kept diverse

An earlier version of this set was all Syria, all the time. That left most of the library untouched: 25 of the 31 sources are not about Syria, and the widest meeting points in the whole collection are Tilly, Weber, Marx, nationalism and the two world wars. The set was rebuilt on 30 July 2026 against the measured index, one brief per retrieval shape:

- a **hub** anchor at the corpus's centre of gravity (P3-04, `Syria`, 962 passages / 22 books);
- **two scholars in dispute** over densely covered ground (S-01, Tilly 154/20 against Mann 377/15);
- a **contested concept** several books use incompatibly (S-02, `nationalism`, 158/18);
- a **concept whose own founding book is on the shelf** (S-03, `quasi-states`, 51/5);
- **thin coverage** (S-04, `Transnistria`, 36/2);
- **single-source concentration** (S-05, `Somaliland`, 52/1).

Every S-brief anchor is mid-sized by design. P3-04 was kept deliberately as the one Syria brief, because the hub case has to be exercised by something.

All six ran on the same open-source stack: **DeepSeek v4 Pro** reading the question and searching the library, **GLM 5.2** writing the answer and its counter-position.

{{SHORT_BRIEFS}}

---

## Test Cases – Hard Briefs

Three questions, written outside this environment with no access to the repository, each built around a genuine unsettled dispute in the literature rather than a question with a lookup answer. Each carries a rubric and a set of "instant dismissal" criteria — shapes of answer that fail regardless of how well written they are.

The head-to-head between open-source and proprietary models ran on **question B**, the judgment question. Questions **A** and **C** ran on the open-source stack only, at two search budgets, to settle whether searching harder helps. It did not — see [Test Design and Evaluation Methodology](#test-design-and-evaluation-methodology). The best run of each is reproduced here.

**Only question B was peer-reviewed.** A and C were measured mechanically. Their peer-review rows say so rather than inventing a verdict.

{{HARD_BRIEFS}}

### What the comparison does and does not show

The open-source combination won this round on a blind reading, at 2.3 times less money, reaching more of the library. It is **not** decisive evidence that open-source models have an upper hand. It is one question, one draw per arm, judged once by a single reviewer whose false-positive rate has never been measured, on a question written by a model rather than by a scholar. Four models moved at the same time, so the result cannot be attributed to any one of them.

It is, however, a real signal, and it is the one worth acting on: **open-source models are competitive in production.** For a workload that reads a library, follows an argument across books, and has to be honest about what it does not know, a fully open stack produced the better answer here and cost less than half as much.

---

## Final Note

Axial will be open-sourced on GitHub:

**https://github.com/Muhanad-husn/axial**

The repository contains **code only**. The sources themselves and any excerpts from them are excluded, to avoid copyright issues. Everything the code produces from a library — the passage records, the name pages, the answers — is generated on the operator's own machine from the operator's own files, and none of it is published here.

The project is open to collaborators and to supporters, and there are two distinct ways in.

**For domain experts** — historians, political scientists, sociologists, librarians. The hard problems in Axial are not engineering problems. What should a passage be asked? The sixteen questions above are a first draft and they are visible, editable data, not code. What counts as a good answer to a comparative question, and who decides? How should a system disclose that it is arguing from three passages rather than three hundred? Where does an argument stop being supported by its evidence? Better questions, better search strategy, better prompts, and above all better judgement about what a defensible answer looks like — this is where the product is won or lost, and it is not won by writing more software.

**For engineers.** The pipeline is Python, driven by a command-line tool, with the domain content held as configuration rather than code — porting the whole system to a different field is a configuration change, not a rewrite. Retrieval, evaluation harnesses, cost and latency, the vault layer, the query API, and the packaging of all of it into something another person can install and run: all of it is open, and all of it has room.

The measurements in this report are the honest state of the thing as of 1 August 2026. Where a number is one draw, it says so. Where a check is unproven, it says so. Where the engine is bad at something, it is written down with the number attached. That is the standard the project intends to keep.
