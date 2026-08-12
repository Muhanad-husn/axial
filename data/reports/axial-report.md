![Axial](axial-logo.png)

# Axial — a research report

**What it is, how it works, how it was tested, and what the tests showed**

Version 2.3 · 7 August 2026 · Muhanad Abulhusn

*Version 2.3 corrects §7.6's two reproducibility figures against the run logs behind them: Gather's byte-identical self-disagreement is 19.3% per name, not the 53% flip rate that belongs to a changed packet, and name merging moves 0.43% of the material. Version 2.2 adds Appendix F, an index of the six further papers drafted since — five of them deliberately off the Syrian case the library is built around — and records what that exercise exposed about the shelf. Nothing in the system or its evaluation has changed; the panel figures in section 7.4 still cover the two papers in Appendices D and E and nothing else. Version 2.1 (6 August 2026) restructured the dossier as a research paper: an executive summary at the front, the full question inventory moved to an appendix, and the closing section recast as a final word. Version 1.0 (1 August 2026) remains superseded: it described a retrieval layer and a final deliverable that have both since been replaced.*

---

## Executive summary

Axial reads a shelf of academic books once, in full, and writes from the reading. It works passage by passage — a passage being a few paragraphs, about one complete move in an argument — and records what each passage claims, whose position that is, who it argues against, whom it cites, and every person, place, institution, event and concept it names. From that single reading it builds three things: an encyclopaedia in which every named thing has its own page; a map of the arguments running through the library, including where books that never cite each other disagree; and, on request, a research paper in which every citation can be traced, link by machine-checkable link, to a passage in a real book.

That makes it different in kind from the tools most readers already have. A chat assistant with PDFs attached, like every "chat with your documents" product, searches first and reads second: it sees only the fragments a question happens to retrieve, and nothing in its output separates what a source asserted from what the model composed on top. Axial reads everything before any question is asked. Every assertion in its output is marked as exactly one of three kinds — a source says it, Axial inferred it across sources, or the analyst's judgment — and the marking is enforced by checks that block release, not requested in a prompt. The model that drafts the final paper has no access to the library at all: its whole world is the list of claims that already passed the checks, so citing invented evidence is not forbidden by instruction but impossible by construction. What comes out is **governed data** rather than model prose: every record carries its source, its kind and its confidence because code put them there.

The current library is thirty-five works of scholarship on state formation, nationalism and political violence, built around Syria as a case. Reading it produced 6,842 passages, an encyclopaedia of 47,584 name pages, and an argument map of 1,937 positions joined by 1,472 stated relations — 328 of them connecting positions with no author in common. The map cost $0.75 to build and $0 to update when four books were added. A complete run, from question to finished paper, costs well under a dollar.

Four instruments test it. Mechanical gates pass at 1.00 on every paper: every citation resolves, no confidence claim was inflated, and the opposing case is present or its absence disclosed. On a nine-question test of reach, the engine's citations met 26 of 37 evidence demands. A sealed panel of reviewer models — each from a different lab than the model that wrote the paper, each shown only the paper and the passages it cites — caught all three defects planted as a control and rated both development papers adequate to strong. The panel also found the two defects no mechanical check could: a citation that resolves to a publisher's catalogue page, and a keystone Syrian claim carried by Moroccan and Egyptian evidence because the library lacks the Syrian book that should carry it. In a paired trial, open-weight models matched proprietary ones on quality at three and a half times less cost.

Eight papers now exist, and the shape of the set is itself a finding. The two reproduced in full are on Syria, because the library is. Six more, listed in Appendix F, move off it: European nation-state formation, the quasi-states concept, Transnistria, Somaliland, nationalism and war, and one further Syrian question. Two of the six cite exactly one book each, which is the library reporting its own shape rather than the engine failing — the shelf holds one comparative study of unrecognised states and no monograph on either territory. A paper carried by a single book is a well-formed argument over a thin shelf, and should never be read as a finding.

One limit bounds every figure: the test questions were written by an AI model, and no output has yet been judged by a human expert. The numbers measure the engine, not answer quality against a real scholarly question. Closing that gap needs people rather than code, and this report ends with a request for exactly that: a few real research questions, one refereed reading of one paper, and the names of the books the shelf is missing.

---

## Contents

- [Executive summary](#executive-summary)
- [1. What Axial is](#1-what-axial-is)
- [2. Why the tools you already have do not do this](#2-why-the-tools-you-already-have-do-not-do-this)
- [3. How it works](#3-how-it-works)
- [4. Why questions, and not tags](#4-why-questions-and-not-tags)
- [5. Why any of it can be checked](#5-why-any-of-it-can-be-checked)
- [6. What is actually in the library](#6-what-is-actually-in-the-library)
- [7. How it was tested, and what the tests showed](#7-how-it-was-tested-and-what-the-tests-showed)
- [8. Known limits and open problems](#8-known-limits-and-open-problems)
- [Final word](#final-word)
- [Appendix A — How the test questions were designed](#appendix-a--how-the-test-questions-were-designed)
- [Appendix B — How answers and papers are judged](#appendix-b--how-answers-and-papers-are-judged)
- [Appendix C — The library](#appendix-c--the-library)
- [Appendix D — The first paper, and the questions behind it](#appendix-d--the-first-paper-and-the-questions-behind-it)
- [Appendix E — The second paper, and the questions behind it](#appendix-e--the-second-paper-and-the-questions-behind-it)
- [Appendix F — The other papers, listed rather than reproduced](#appendix-f--the-other-papers-listed-rather-than-reproduced)
- [Appendix G — Every question Axial asks](#appendix-g--every-question-axial-asks)
- [Appendix H — Glossary](#appendix-h--glossary)

---

## 1. What Axial is

Axial reads a shelf of academic books once, in full, and writes down what every passage says. Then it answers research questions out of that reading, and ends by drafting the paper the answer is the material for.

The unit is not the book and not the chapter. It is the **passage**: a few paragraphs, about the size of one complete move in an argument. Axial reads every passage in the library, one at a time, in isolation, and records what that passage claims, whose position it is, who it argues against, whom it cites, and every named thing in it. That reading happens before any question is asked, and it is the only time a book is read.

What the reading produces is three things, in layers.

**An encyclopaedia of names.** Every scholar, country, institution, event and concept any passage mentions gets a page. The page lists the passages that mention it and, where the page is big enough to hold an argument, states what the authors gathered there disagree about. Two books that never cite each other meet on the page for the name they both use.

> **Name, and name page.** A *name* in Axial is any specific thing a passage names: a person (Charles Tilly), a place (Aleppo), an institution (the French Mandate), an event (the 1925 revolt), a concept (infrastructural power), or a book. It is whatever the passage itself named, in the passage's own words, not a category chosen from a list. A *name page* is the page Axial builds for one such name, and it works like an encyclopaedia entry that writes itself: it holds every passage in the library that mentioned that name, from whichever book, and it is the place where two authors who never read each other end up side by side. The library currently has 47,584 of them.

**A map of arguments.** Passages that make the same argument are grouped into a **position**, once, offline.

> **Position.** A *position* is one argument, held by however many passages make it. If eleven passages spread over five books all argue that states build bureaucracies in order to pay for war, those eleven passages are one position, and the position is stated in a single sentence drawn from their own wording. It is not a topic and not a category. It is a claim someone could disagree with, and the disagreement is exactly what the map is built to find. A position keeps every passage behind it, so it can always be opened back up into the books it came from.

Then every position is asked how it stands to its neighbours. The result is a graph of what supports, qualifies, exemplifies and contradicts what, across the whole library, stated in the corpus's own words. Nobody handed the model a menu of relationship types; it coined 504 distinct labels on this corpus, of which the four commonest are *supports*, *exemplifies*, *qualifies* and *contradicts*.

**A paper.** You give Axial a case and a request. It interrogates the question before answering it, walks the two layers above for evidence, writes an answer as a list of claims each marked for what kind of claim it is and pointed at the passages behind it, runs a set of mechanical checks the model cannot reach, and then drafts a paper from the claims that survived. One command does all of it.

The finished paper reads like a journal article. Every citation in it resolves to a passage in a real book on the shelf, and the chain from sentence to passage is machine-checkable at every link.

### What it is not

It is not a chatbot, not a search engine, and not a summariser. It never reaches the open web, and it cannot cite anything that is not in the library. It has no opinion it did not build from the corpus, and where the corpus is silent it is designed to say so rather than fill the gap from what the model happens to remember.

---

## 2. Why the tools you already have do not do this

You have probably uploaded PDFs to a chat assistant and asked questions, or pressed a "deep research" button. Those tools are useful. They are built for a different job, and the difference is structural rather than a matter of quality.

**The order of operations is inverted.** Every retrieval-based tool searches first and reads second: it finds text that looks relevant to your question, then writes something on top of it. That has one well-known failure and one less obvious one. The known failure is that plausible-sounding text gets retrieved and plausible-sounding prose gets written over it, and nobody can check the join. The less obvious failure is that the tool can only ever see the part of the library your query happened to reach. It has no idea what is in the rest.

Axial reads everything before anything is asked. Retrieval then runs over a record of a completed reading, not over raw text. The question cannot decide what gets read, because the reading is already done.

**Against uploading books to a chat assistant.** The assistant retrieves a few passages and paraphrases them. It rarely separates what a source *claims* from what it is *inferring*, it attributes unreliably, and it will produce a confident paragraph whether or not the sources support one. It never tells you what it left out. In Axial every assertion in an answer is marked as exactly one of three kinds, and the marking is enforced by a check that blocks release, not requested in a prompt.

**Against RAG and knowledge-graph systems.**

> **RAG.** Short for *retrieval-augmented generation*, and it is the standard way almost every "chat with your documents" product works. The documents are cut into fragments and indexed. When you ask a question, the system searches that index, pulls out the handful of fragments that look most similar to your wording, pastes them invisibly above your question, and asks a language model to answer using them. It is a genuine improvement on a model answering from memory alone, because at least something real is in front of it. Its two limits are structural rather than fixable by a better search: the model only ever sees what your question happened to retrieve, and nothing in the arrangement distinguishes a sentence a source actually asserted from a sentence the model composed on top of it. A *knowledge-graph* system is a more sophisticated relative — it first extracts entities and the links between them, then searches that structure instead of raw text — but the order of operations, and therefore both limits, are the same.

Those systems improve retrieval: they find better passages, and some of them build a graph of entities to find them by. Axial builds that layer too, and then does the thing retrieval systems do not attempt, which is **synthesis** — producing an argument no single source made, across sources, the way a scholar writes a review essay, held to the attribution a scholar is held to. A knowledge graph tells you that Tilly and Mann are both connected to "state formation". Axial's argument map records that a specific claim of Mann's *qualifies* a specific claim of Tilly's, in a sentence, with the passages on both sides.

> **Tilly and Mann.** The two scholars this report keeps returning to, because they are the two the library's own passages meet over most often.
>
> **Charles Tilly** (1929–2008) was an American sociologist and historian, at his death the Joseph L. Buttenwieser Professor of Social Science at Columbia, holding a joint appointment in sociology and political science. He published over fifty books and some six hundred articles, and effectively created the field now called contentious politics — the study of strikes, riots, revolutions and social movements as one family of behaviour. He is best known outside that field for the argument compressed into the phrase *war made the state, and the state made war*: rulers who needed to fight had to extract taxes to pay for it, extracting taxes required a bureaucracy, resisting subjects had to be bargained with, and the modern European state is what came out the other end. Tilly himself put the comparison bluntly, likening the arrangement to a protection racket. The library holds his *From Mobilization to Revolution* (1978).
>
> **Michael Mann** (b. 1942, Manchester) is Distinguished Research Professor Emeritus of Sociology at UCLA, where he taught from 1987, after a decade at the London School of Economics. His principal work is the four-volume *The Sources of Social Power* (1986, 1993, 2012, 2013), a history of power in human societies built on the claim that power runs through four channels — ideological, economic, military and political — which interact but never reduce to one another. His 1984 paper on the autonomous power of the state introduced the distinction between *despotic* power (what a ruler can do to people without negotiating) and *infrastructural* power (how deeply the state can actually reach into the society it governs to collect a tax or enforce a law). That distinction runs through both papers in the appendices. All four volumes are in the library, along with a volume of critical essays on his work.
>
> The two are not opponents in any simple sense, and the map does not treat them as such. Mann's later work concedes that war no longer makes states the way it once did, which is one of the qualifications the library records. Axial was built the attribute-and-query way first, and [section 4](#4-why-questions-and-not-tags) reports what that produced: 18,761 tagged passages and zero connections between any two books.

**Against "deep research" on the open web.** Those tools scrape whatever the web offers, weigh a preprint the same as a blog post, and sometimes cite sources that do not exist. Axial works on a curated shelf of real scholarship and cannot reach outside it. The grounding is not a policy. It is structural: the drafting model that writes the final paper has **no retrieval tools at all**. Its whole world is the list of claims that already passed the checks. It cannot introduce evidence because it has no path to any.

**The honest version of the comparison.** For "what does this book say about X", a chat assistant with the PDF attached is faster and cheaper, and you should use one. Axial is for the question a chat assistant cannot take seriously: what does a body of scholarship, read whole, say about a contested question, and where do its authors disagree.

---

## 3. How it works

### 3.1 Before you ask anything

**Intake.** A book arrives, from a Google Drive folder or from disk. Axial checks it has a real text layer and is not a scan, reads the author, title and date out of the file itself, and checks whether the file contains the whole work it claims to be. Bibliographic fields that cannot be confirmed from the file are recorded as not recovered rather than guessed. This matters more than it sounds: one file in the current library carries embedded metadata attributing it to an entirely different book, left over from the tool that made the PDF.

**Structure.** The book's hierarchy is rebuilt — chapters, sections, headings, tables, figures, footnotes, index, bibliography. The damage PDFs do to text is repaired. Every block is sorted into prose, artifact, or apparatus. Front and back matter that carries no argument is set aside and recorded as set aside, never silently dropped.

**Envelope.** One pass per book captures what the book says it is doing: the author's stated thesis, the scope, the argument as stated, and a table of contents reconstructed from the book's own prose. This is grounded in the text, never in what a model might know about the title. It travels with every passage afterwards, so a model reading one paragraph of a book it has never otherwise seen always knows what the book is arguing.

**Chunking.** The prose is cut into passages along the author's own paragraph and sentence boundaries, never a fixed word count, and every passage is kept between roughly 3,500 and 9,000 characters — one to four pages of a printed book. The size is chosen for the questions below. A claim and the evidence for it usually sit several paragraphs apart, and a smaller window would produce abstentions for want of text rather than for want of an answer. **The cutting involves no AI at all.** It is mechanical, repeatable, and inspectable before a penny of model spend.

**The reading.** One model call per passage. Fourteen open questions, producing seventeen recorded answers:

| | Question |
|---|---|
| 1 | **About** — what is this passage about? Short phrases, in your own words. |
| 2 | **Claim** — what is being claimed, in one sentence. |
| 3 | **Move** — what is this passage *doing* in the argument? Not a label like "evidence" but the move itself, for example "conceding a point in order to narrow it". |
| 4 | **Ranges over / stops holding** — what does the claim cover, and where does the author say it stops being true? |
| 5 | **Position of / position** — whose position is this, and what *is* that position in the passage's own terms? |
| 6 | **Arguing against** — who or what is it arguing against? |
| 7 | **Names** — every named thing: people, places, institutions, events, movements, periods, and any figure or table the passage names, each with what kind of thing it is. |
| 8 | **Citations** — whom does it cite, and is each citation used as support, as a foil, or as an authority? |
| 9 | **Mechanism** — what causes what, in what order. |
| 10 | **Evidence** — what evidence is offered. |
| 11 | **Comparison** — what comparison is made, stated or implied. |
| 12 | **Defines / uses** — what is defined here, and separately, what is merely used without being defined. |
| 13 | **Concedes** — what the author concedes or hedges. |
| 14 | **Assumes** — what it assumes without saying. |

Three rules govern the whole reading, and each exists because the obvious alternative fails.

*Answer only from the passage in front of you.* No web, no lookup, no memory of the book. Where the passage does not support an answer, say so. **An abstention is a normal answer and a guessed answer is worse than none**, because nothing downstream can tell a guess from a reading.

*The free answer comes first, the examples second.* Each question is asked open, in the model's own words. Only afterwards is the model shown the domain's example vocabulary, and only as a separate, clearly-marked field. No code ever bridges the two — no normalisation, no rewriting, no filling one from the other. This ordering is the single guard against the failure that would make the whole design pointless: if the reading answered in the example vocabulary, Axial would have rebuilt keyword tagging with extra steps and hidden it.

*Every passage is accounted for.* Answered plus failed plus skipped must equal the source's own passage count, or the pass raises rather than reporting a partial read as a complete one.

Two of the seventeen answers carry most of the later weight. **Names** is how passages find each other. **Arguing against** is how disagreement becomes visible: an author who names an opponent has already done the work of locating the dispute, and Axial records it rather than inferring it.

**Reconciliation.** The same person or idea appears under many names — "Charles Tilly", "Tilly", "C. Tilly 1975", "Ba'th" and "Baath". A spelling fold that needs no model at all handles the mechanical cases. Clustering proposes the rest as *hints*, and a model call decides. **"Cannot tell" is a real third outcome**, not a failure, and merges are reversible and logged.

**Materialisation.** The encyclopaedia is written out: a page per passage carrying its own answers, a page per surviving name listing the passages that mention it. This step involves no AI. It is a rendering of what the previous steps produced.

**Gathering.** For each name big enough to hold an argument, the claims made at that name are put side by side and one question is asked: what do these authors disagree about? Code assembles the packet and enforces the budget, so the pass cannot be talked into fetching more and cannot blow its context window. A name with fewer than two members is skipped before a packet exists, because a disagreement needs two parties.

**The argument map.** This is the layer that made version 1.0 of this report obsolete, and it is the one place Axial does something no retrieval system does.

Reaching a passage through a name it happens to mention is a narrow door. A passage that makes exactly the argument you need but names nobody you thought to ask about is unreachable. So the map is built the other way round:

1. **Select** every passage that actually argues something. Passages that abstain on every argumentative question — bibliographies, acknowledgements, method throat-clearing — are dropped. On the current library that leaves 6,010 of 6,842.
2. **Bag** them by the similarity of their own one-sentence claims, using a local sentence encoder. A *bag* is a rough pile of passages whose claims are worded alike, assembled by arithmetic rather than by reading — the working tray a model is later handed, never a finding in itself. Zero model calls, and the grain is a stated choice rather than a fitted one.
3. **Extract.** Every bag is read in full, never sampled. The model is asked to name the arguments that *recur* across passages, and told explicitly that producing roughly as many arguments as passages is a failed read. The reading is **blind**: it sees the claims under bare handles, never the authors. Authorship visible during extraction would let the model decide what meets, which would make the later cross-author counts measure their own input.
4. **Merge** the near-duplicate namings, keeping every raw phrasing and how many times each argument was independently named.

The current library yields **1,937 positions** over 5,987 placed passages. Then every position is asked how it stands to its neighbours — again blind, again with **no menu of relationship types**, because an engine told to look for opposition finds opposition. That produced **1,472 asserted relations** under **504 labels the model coined itself**, of which **328 connect two positions with no author in common** — a genuine meeting between different books rather than one author elaborating on themself.

The whole map cost **$0.75 and 45 minutes** to build the first time. Rebuilding it after four books were added cost **$0** and 157 seconds, because a passage already placed keeps its bag and a reading whose input did not change is never re-asked.

### 3.2 When you ask

**The question is interrogated before it is answered.** A brief is a case and a request. Axial first tests it: does the library actually cover this, are there premises smuggled into the phrasing, should the answer be bounded, should the question be refused outright. **Refusal is a completed run, not an error.** A refused question makes no synthesis call and drafts no paper, and still exits cleanly.

Where the question's own terms produce a genuine, *measured* fork — a real source imbalance, or a mismatch between the period the question asks about and the years the library's books were published — Axial asks the analyst, with options and free text. It never asks when no fork is found, which is the common case, and it never guesses a weight from the question's wording.

**Retrieval.** This is the one genuinely agentic loop in the system. The model plans and re-queries freely in the middle; code it cannot reach stands on both sides. It proposes one query at a time against ten deterministic tools over the notes, the name pages, the opposition edges and the argument-map positions. Every proposed call is validated against a schema before it touches the store. The tools contain no model calls: the same query returns the same passages in the same order, always.

The feedback the model gets back states what the evidence set now holds and which books it spans, and nothing else. It is never told the budget or the cap, because a cap a model can see is a cap it argues with. It is also never told "you already asked that", because saying so was measured to *raise* repeat queries from 14% to 20%.

A second, optional path replaces this loop entirely, walking the map of arguments instead of the name pages. It has three steps, and the names for them are the report's own shorthand.

> **Door, landing, corridor.** The *door* is the first step: Axial reads your question and states, in plain contestable sentences, what arguments the question is actually about. It does this before it has looked at the library at all, so what happens to be on the shelf cannot bend what the question is taken to mean. The *landing* is where those stated arguments come to rest on the map: the positions that match them. The *corridor* is what opens off the landing: every position that argues with something that landed, followed in both directions. The corridor is the point of the whole arrangement. It is how the account your answer has to reject arrives — because it argues with what you landed on, and not because your question happened to mention it.

**Synthesis.** The evidence is assembled deterministically, interleaved across sources so one book cannot spend the whole budget, and shown to the writing model under opaque short handles rather than real identifiers, so there is no long id in the prompt to transcribe or blend. The answer comes back as numbered claims, each marked:

- **(a) source-says** — a source in the library asserts it, cited to the passage that does;
- **(b) tool-infers-across-sources** — Axial's own inference relating what different books say. **This is the new knowledge, and it is also the whole risk**, so it is never allowed to appear in a source's voice;
- **(c) the analyst's judgment** — reasoning that runs past what the corpus grounds, marked as such.

> **Grounds, and the confidence band.** A claim's *grounds* are the specific passages it rests on — not a book, not a page range, but the exact passages, recorded as pointers a machine can follow back to the text. Every claim of the first two kinds must carry them, and every pointer must resolve, or the claim is rejected. The *confidence band* is Axial's own statement of how much weight a claim will bear, in three steps: high, medium or low. It is deliberately three words and never a number, because a decimal like 0.87 implies a precision nothing here could justify.

**Checking.** Mechanical checks then run outside the model's control. Does every claim carry a kind? Do its cited passages actually resolve? Is there a counter-position stating the opposing case at its strongest, or an explicit statement that the library is one-sided here? Is there a coverage map saying how much evidence each name in the answer rests on, and a confidence band that cannot exceed what that coverage supports? A failed check blocks release.

If an answer leans on a name the library holds three passages about, the answer's stated confidence is pulled down to match, whatever the writing model thought of itself. **Confidence is capped by evidence, not by tone.**

**The paper.** The answer is not the deliverable. Once it is written and persisted, Axial drafts the paper it is the material for: it takes an inventory of the claims that survived, plans a narrative arc with a role for each section, drafts one section at a time, builds a citation index, and renders the paper with a bibliography of exactly the books it actually cited.

The drafter sees the claim inventory and what earlier sections already cited. That is its entire world. **It has no retrieval tools and no access to the library**, so generate-then-cite is not forbidden by instruction, it is impossible by construction. An unknown citation marker is fatal at indexing rather than repaired.

Drafting roughly doubles the cost of a question, from $0.11–$0.30 for the answer to a further $0.08–$0.20 for the paper. A flag stops at the answer for exploratory work.

### 3.3 The rules every model call answers under

Across the whole pipeline, a model is consulted in sixteen places, plus a set of judges that sit outside it. Three rules hold everywhere. Every question is open: nowhere is the model asked to pick from a list, and every question carries an explicit right to answer "I cannot tell from this". Where a count downstream depends on the answer, the question is asked blind: the models that group arguments and relate them never see the authors, so a count of how often the map joins different books measures the corpus rather than the model's sense of who ought to argue. And code stands on both sides of every call: code assembles what the model sees, and code reads what comes back.

The judges add a rule of their own: **none may be run by the model that produced the thing being judged**, and the sealed review panel goes further and requires a different training lab, because a family-mate's agreement is weak evidence.

The complete inventory — all sixteen questions, quoted from the working system — is in [Appendix G](#appendix-g--every-question-axial-asks).

---

## 4. Why questions, and not tags

Axial's first version did the standard thing, and the standard thing failed in a way worth reporting, because the same approach is what most document-intelligence and knowledge-graph products are built on today.

### 4.1 What the first version did

Every passage was **tagged** against five closed vocabularies: what field it belonged to, what kind of claim it made, which theoretical school it spoke from, what its empirical scope was, and what role it played in the argument. A separate pass looked for cross-references. This is the mechanical version of axial coding, and it is exactly what a knowledge-graph pipeline does: turn text into attributes, then query the attributes.

For months the tags looked fine. A model read a passage, produced a sensible label, and moved on. Nobody had measured whether the labels were *right*, because measuring requires an answer key.

### 4.2 The measurement

Two frontier models from two different labs were given the same neutral instructions and independently labelled the same 120 passages. Two independent labellers means agreement can be measured.

**On the two hardest axes — kind of claim, and theoretical school — they agreed 49% of the time.** The internal bar for keeping an axis at all was 60%. Both were underwater.

The three obvious reactions were each tested, and each did nothing.

| The obvious fix | What happened |
|---|---|
| "Use a smarter model." | The cheap production tagger agreed with one frontier labeller **more** than the two frontier labellers agreed with each other. The model was not the lever. |
| "The definitions are vague, rewrite them." | A codebook rewrite costing 55% more prompt moved agreement by **roughly zero**. An explicit rule about what unit to label added **0.02**. |
| "Give it more context." | Feeding the book's own thesis and stated argument into the labelling call scored **−0.01** on the full sample. |

### 4.3 The finding that ended the approach

Then the ceiling was measured, and there was nothing left to fix.

**The same model, given the identical prompt twice, reproduced its own theoretical-school label only 73% of the time.** Two independent coders also agreed 73%. Agreement between two readers cannot exceed the reliability of one reader with themself, so there was no headroom. The disagreement was not in the model, the prompt, or the definitions.

**It was in the question.** "Which school does this passage speak from?" does not have one answer. A closed vocabulary forces one anyway, and then the number it produces looks like knowledge.

A majority vote across several draws was built and shipped, and it did raise reliability. It did not repair anything, because the reliability was never the real problem.

### 4.4 The structural failure underneath

At the end of that version, over 31 books, the corpus looked like this:

| What was counted | The count |
|---|---|
| Passages tagged | 18,761 |
| Connections between passages | **584** |
| Of those, inside a single book | **584** |
| Links between two books | **0** |
| Links between two passages of prose | **0** |

Not one connection across the library. And the cause was not a bad setting. The only mechanism that could ever create a connection asked a closed question and filtered the answer against that book's own list of figures, so its output was confined to one book by construction. No parameter could have produced a cross-book link.

**The diagnosis is one sentence: an attribute is not a relation.** A tag sorts a passage into a bin. Two passages in the same bin have been sorted the same way; they have not met. What actually makes two books argue is that one of them names Charles Tilly and so does the other, or that one says whom it argues against and the other is that target. **A closed vocabulary cannot record either, because it has to know the answer before it reads.**

### 4.5 What replaced it

The fix is the question, not a better detector. Ask what the passage says, in the passage's own words, and specifics come back rather than bins. Over the same books:

| | Tagging | Interrogation |
|---|---|---|
| Passages | 18,761 | 6,148 |
| Names shared across books | — | **9,505** |
| Of those, shared across different authors | — | **8,769** |
| Stated disagreements between authors | 0 | **447** |

The passage count fell because the passages got bigger, deliberately, to fit whole arguments. Everything else appeared for the first time.

### 4.6 The same lesson, twice more

**Once at retrieval.** Interrogation produced a graph, and then materialisation threw most of it away by grouping passages into pages by their surface string. Whom a passage argues against was answered on **76.4%** of passages, and only **4.7%** of those targets joined to anything a question could actually reach. The opposition was recorded and not indexed. Loading the same passages into a relational store lifted that to **44%** and exposed **43,101 cross-source opposition pairs**. Resolving what was left against the argument map — the targets that describe a position in prose, with no name in them to join on — took it to **60.2%** of all targets, for $1.08. That is the redesign that made this version of the report necessary.

**Once at the argument map.** The relation pass could have been given a tidy list of relationship types. It was not, for the reason stated in section 3: an engine told to look for opposition finds opposition. Given no menu it coined 504 labels, and the shapes that recur were named afterwards from what came back.

### 4.7 What the old vocabularies are still good for

They did not disappear. They survive as **examples**, and the design around them is the single most important guard in the reading pass.

The model answers every question in its own words **first**. Only afterwards is it shown the example vocabulary, in a separate section, with the instruction that these are "NOT a menu, NOT a vocabulary, and NOT a set of allowed answers", that "nothing checks your free answers against them", and that "an answer that matches none of them is the normal case". It then adds a *second*, separate note about which example its free answer happens to sit nearest, and whether the fit is close, loose or none. Code never bridges the two fields — no normalisation, no rewriting, no filling one from the other.

That ordering is the whole difference between this design and the one it replaced. Reverse it and Axial is a tagger again, with extra steps, and nobody could tell from the output.

---

## 5. Why any of it can be checked

A production tool makes novel claims, and a novel claim has no answer key. There is no gold standard for "the right synthesis of thirty-five books". So Axial does not claim correctness. It claims **auditability**, and organises everything around one sentence: *accountability to grounds, with honest confidence.*

What that produces is **governed data**, not model output. Every record carries where it came from, what kind of statement it is, and how much confidence it is entitled to, and code put all three there. None of them was requested in a prompt, and no model can omit them. A model writes the content; what counts as a record is not its decision.

Five commitments follow, and each is enforced somewhere a model cannot reach.

**Every claim is witnessed by the corpus, never by training memory.** The model's job is to reason *across* grounded material, never to supply facts *from itself*. Where the corpus is silent the output says so.

**Outputs are assembled from grounded moves, never written and then fitted with citations.** Marking every assertion as one of three kinds makes the join visible — the *seam*, in this report's shorthand, being the line where what a source said stops and what Axial concluded begins. The (b) seam is where the value is and where the risk is, in the same place, so it is checked first.

**The brief is interrogated, not obeyed.** A research brief is a claim about what is worth asking, and it can be wrong. Bounding and refusal are first-class outputs.

**Counter-position is mandatory.** Comparative-historical sociology is a field of live disputes. A synthesis that reports one side has not settled the dispute, it has collapsed to one side and hidden that. **On a contested question, no counter-position is a red flag, not a clean result.** When the library really is one-sided, the output says so and attributes the one-sidedness to the corpus, which is a different statement from "the sources agree".

**Confidence is disclosed, and trust is compositional.** There is no single quality score and none was invented. Trust decomposes into layers — is the substrate cleanly read, is every claim marked with the right kind, does the argument follow from its grounds, does stated confidence track reality — and a failure low down poisons everything above it. A flawless synthesis over a mis-attributed reading is worthless. The layers multiply; they do not average.

Two structural properties support all five.

*Code holds the line on both sides of every model call.* Code assembles what the model sees, so a packet cannot overflow and a prompt cannot be talked into fetching more. Code reads what comes back, so an invented reference is dropped rather than repaired and a response nothing could be parsed from is never recorded as a verdict. And code keeps a ledger beside every paid pass, so an interrupted run resumes instead of paying twice.

*Nothing is a one-way door.* Every intermediate artifact is on disk and inspectable: the structural tree of each book, the seventeen answers for every passage, every name page, every position and relation, every retrieval step with the exact pages it touched, and the cost of each pass. A claim in a finished paper can be walked back to the passage in the book, by hand, in under a minute.

---

## 6. What is actually in the library

The current library is **35 books**, listed in full in [Appendix C](#appendix-c--the-library). It is deliberately built around one case, Syria, set inside the comparative-historical literature on state formation, nationalism and political violence — Mann's four volumes, Tilly, Gellner, Wimmer, Smith, Kalyvas, Jackson, Caspersen, alongside Batatu, Ayubi, Heydemann, White, Hinnebusch, Gelvin, Wedeen, Üngör and Vignal.

Reading it produced **6,842 passages** and **47,584 name pages** carrying 137,276 mentions.

A separate report, [*Axial — what the library covers, and what it does not*](axial-coverage-v2.md), measures that index page by page. Its central finding is repeated here.

**A page is useful for research when it holds enough passages to compare and enough different books for the comparison to be between authors rather than within one.** That means roughly thirty to two hundred passages from five or more books. **329 of the 47,584 pages meet that bar.** Seven in ten thousand.

| What was counted | The count |
|---|---|
| Median passages per page, every kind of name | **1** |
| Pages mentioned exactly once and never again | 32,447 of 47,584 |
| Pages that exist inside a single book | **83.0%** |
| Concepts discussed by five or more books at all | **135** |
| Concepts meeting the research bar | **18** |

Three readings follow from this, and all three are useful.

**The tail is real and it is mostly bibliography.** The *tail* is the long, thin end of the distribution: the enormous number of name pages that carry almost nothing, as against the small number that carry a great deal. Two in three pages are a name a passage mentioned once. Works cited are the extreme case: 94.2% appear in one book only, which is what a bibliography looks like when you index it.

**Places, not concepts, are this library's strongest entry points.** Countries and places hold 35,493 mentions off 4,670 pages, more than twice the density of any other kind, and 129 of the 329 research-grade pages. That is a genuine property of a case-organised shelf. Its authors meet each other over Syria, Iraq, Britain and France far more often than over any idea.

**Some topics are covered at length and yet not argued about.** Take every page with ten or more passages and ask whether one book supplies seventy percent of them. *Negative sovereignty*: 47 passages, 87% Jackson. *State of exception*: 27 passages, 93% Agamben. *IEMP model*: 80 passages, 82% Hall and Schroeder. These are not gaps in the ordinary sense. Every one is well covered. What is missing is a second author, which is a much more specific and much more fixable thing.

That measurement is what tells us which book to add next, and it is computed mechanically from the finished index with no model asked to judge anything.

---

## 7. How it was tested, and what the tests showed

### 7.1 The principle: no single number, and no number without its frame

Axial computes no aggregate accuracy score and must not. A single figure lets a strong layer average away a weak one, which is precisely the failure the design exists to avoid. Instead there are four instruments, on different clocks, each reported on its own terms.

| Instrument | What it judges | When it runs | Can it block a release? |
|---|---|---|---|
| **Mechanical checks** | Does the output have the shape it must: kinds present, grounds resolvable, coverage map non-empty | Every run | **Yes** |
| **The required-source oracle** | Did the run's citations actually reach the books the question demands | On the test set | No — it is a measurement |
| **The four paper gates** | Provenance, grounding of new inferences, mislabelled seams, counter-position | Every paper | **Yes** |
| **The sealed peer-review panel** | Is the paper any good | Offline, on a sample | No — and deliberately so |

Every number below is stated with the conditions that produced it. Where a figure is one draw of one question, it says so.

**The caveat that bounds every figure below.** Every test question in this report was written by an AI model, not by a working scholar. **Every figure here therefore measures the engine. None of them measures answer quality against a real scholarly question.**

That arrangement was chosen so the engine could be built and hardened without waiting on anyone, and it did its job: a machine-written question exercises retrieval perfectly well, and nothing simulated was ever used as an answer key ([Appendix A](#appendix-a--how-the-test-questions-were-designed)). What it cannot do is tell us whether an answer is any good to a scholar who knows the field. That is the one instrument this project does not have, and closing the gap needs people rather than code. It is the substance of the request in the [final word](#final-word), and the limit is carried in the specification so that no future run can quietly drop it while it stands.

### 7.2 The engine test: nine questions, run end to end

Six short briefs and three hard ones, each chosen to stress a different shape of search.

| Brief | Why it was chosen |
|---|---|
| **P3-04** | The library's centre of gravity. Its anchor, `Syria`, carried 962 passages across 22 books — the case where one huge name can swamp everything else. |
| **S-01** | Scholar against scholar over a densely covered question: Tilly (154 passages, 20 books) against Mann (377, 15). |
| **S-02** | A concept several books use in incompatible ways: `nationalism`, 158 passages across 18 books. |
| **S-03** | A concept whose own founding book is on the shelf: `quasi-states`, 51 passages but only 5 books. |
| **S-04** | Thin coverage. `Transnistria`: 36 passages, 2 books. Does the engine notice it is thin without being told? |
| **S-05** | Single-source concentration. `Somaliland`: 52 passages, all from one book. Does it say so? |
| **A** | Reach. Does the bellicist account of state formation survive transfer from Europe to the twentieth-century Middle East, with its critics engaged on their own terms? |
| **B** | Judgment. Which account explains violence against Syrian civilians — control-and-information, or violence as identity-production? Forced to commit, and to state the rejected account at its strongest. |
| **C** | Reach. Four competing explanations of why nationhood and mass war arrived together, tested against the mandate case. |

*Anchor counts above were measured against the live index on 2026-07-30, when the library held 31 books. The four books added since have moved them.*

**S-04 and S-05 deliberately do not name what they are testing.** An earlier draft asked about "the library's thin evidence on Transnistria". Naming the finding in the question would make a pass prove only that the model follows instructions.

The scoring instrument is a **required-source oracle**. An *oracle*, in testing, is a rule that says what a correct result looks like, so a machine can mark the answer without a person reading it. This one is a list, written per question before the run: for each demand the question makes, which books carry material capable of satisfying it. A demand is met when the run's citations reach any book on its list. It is purely mechanical, needs no model call, and is the only measure of reach the project has.

The most recent full run, on 2026-08-04 across all nine questions on the 31-book library:

| What was measured | The result |
|---|---|
| Demands reached | **26 of 37** |
| Total cost, nine questions | **$2.57** |
| Cost per question | $0.18 – $0.43 |
| Evidence composed per question | 40 – 61 passages |

That run was the first on a rewritten retrieval layer, and it produced the single most useful negative result the project has: **the model was shown two to three times more evidence than the previous run and the oracle went down, not up.** A second draw settled which of the losses were real. One question that appeared to regress badly scored its best result ever on the re-run, retiring the regression. Two single-demand losses reproduced exactly, demand for demand, across both draws, and are recorded as real.

The lesson generalised, and it is the one that governs how every figure in this report is read: **one draw of one question is not a measurement.** One of the six short briefs has been measured moving 39% between two runs of identical code on the identical question. Differences smaller than that are noise until a second draw says otherwise.

### 7.3 The four paper gates

The paper is the deliverable, so it is gated on every run. All four checks are cheap by design. Two are purely mechanical and two are narrow judged checks scoped to the paper's own new inferences.

| Gate | What it requires | Kind |
|---|---|---|
| **Provenance integrity** | Every citation marker in the paper resolves to a claim with resolvable grounds; no claim's confidence band was raised above what its source claim carried | Mechanical, **hard**. One dangling marker fails. One upgraded band fails. |
| **Grounding of new inferences** | No new cross-source inference is contradicted by a passage it cites | Judged, by an independent model anchored to the passage text |
| **Seam fidelity** | No cross-source inference is dressed as something a source said; no speculation credits a source with the paper's own verdict | Judged, same call, two questions |
| **Counter-position presence** | A contested paper carries an opposing position with grounds, or explicitly discloses that the library is one-sided and why | Mechanical, **hard** |

On the two development papers reproduced in Appendices D and E, redrafted on the current build.

**How to read the table.** Each row is one check. The **value** is the share that passed, on a scale where 1.0000 is everything and 0.0000 is nothing — so a rate reads 1.0000 when the check found no fault anywhere, and a count reads 0 when nothing was flagged. **n** is how many things were actually examined: 215 citation markers, 105 claims, 32 cross-source inferences, 2 papers. A perfect score over a small n is a small piece of evidence, which is why n is printed beside every figure rather than left out.

| Gate | What was checked | Value | n |
|---|---|---|---|
| Provenance integrity | citation markers resolving to a real claim | **1.0000** | 215 |
| Provenance integrity | claims whose confidence was raised | **0** | 105 |
| Counter-position | contested papers carrying the opposing case | **1.0000** | 2 |
| Paper grounding | new inferences not contradicted by their own evidence | **1.0000** | 5 |
| Attribution fidelity | claims carrying a valid kind | **1.0000** | 105 |
| Attribution fidelity | inferences wrongly dressed as a source's words | **0.0000** | 32 |
| Attribution fidelity | judgments wrongly credited to a source | **0.0000** | 19 |

The judging model is never the model that wrote the paper, and the guard raises before any judging call is made rather than checking afterwards.

The denominators are small, which is why they are printed. Five new inferences is five, not a rate.

### 7.4 The panel: strangers who read the paper and nothing else

The cheap checks catch everything cheap to catch. The one thing none of them reaches is whether the argument holds together. That is measured by an offline panel, on a sample, and it blocks nothing.

A reviewer receives one **sealed packet**: the rendered paper, plus the resolved text of every passage its claims cite, plus the bibliography. Nothing else. No repository, no specifications, no prompts, no other reviewer's verdict, no pre-written model answer to anchor to.

The isolation is enforced by the code that builds the call, never by an instruction in the prompt. A model that has been handed file access will read the repository whatever its instructions say, so reviewers are dispatched down a path that **has no parameter for tools to be passed through in the first place**. The distinction is the whole point: an instruction to stay sealed can be disregarded, and a capability that was never granted cannot be.

Each reviewer must come from a **different training lab** than the model that wrote the paper — a stricter bar than a different model id, because shared training priors survive within a family and a family-mate's agreement is weak evidence. A model whose lab is not declared is a hard error, never assumed distinct. Reviewers return a fixed structure, never free prose: three ordinal bands plus a list of named defects tied to specific claims.

**N ≥ 3 per packet, and the spread is the error bar.** Three reviewers splitting 1/3/5 and three agreeing on 3 are different results and must never render identically.

#### The control that qualifies the instrument

**The panel produces no reportable number until it has caught planted defects.** LLM judges are systematically generous and are moved by confident prose. A panel that waves a defective packet through is measuring nothing, and its clean verdicts are worthless until it is fixed.

Three defects were planted in a copy of one of the papers, and the reviewers were not told a control was running:

1. A fabricated cause of regime survival, cited to a passage about local governance in Daraa that says nothing of the kind.
2. The section stating the opposing case replaced with a caricature — "the regime got lucky… it need not detain us".
3. A high confidence band asserted over coverage the paper's own map discloses as thin.

| | The control | The same paper, clean |
|---|---|---|
| Factual correctness | **weak ×3** | adequate ×3 |
| Citation grounding | **weak ×3** | adequate ×3 |
| Completeness | **weak ×3** | **strong ×3** |
| Planted defects caught | **3 of 3, by all three reviewers** | — |

The panel discriminates, so the verdicts below are numbers rather than impressions.

#### What the panel said

Twelve sealed reviewers ran in that round, three per packet — three on the control, three on the control's clean twin, and three on each of the two papers:

| Paper | Factual correctness | Citation grounding | Completeness |
|---|---|---|---|
| *Privilege and the Contracted-Out Militia* | adequate ×3 | adequate ×3 | **strong ×3** |
| *What the Mandate Built* | **strong ×3** | strong ×1, adequate ×2 | **strong ×3** |

Spread is zero on seven of the eight cells. An earlier round ran one reviewer per packet, which made the bands a sorting rather than a measurement. At three reviewers they reproduce.

#### The two things the reviewers found that the gates could not

**Five of six reviewers independently flagged the same citation.** Both papers use a passage from Bayat 2017 to tie Heydemann's networks-of-privilege framework to Syria. The passage is a publisher's book-series list — the line "Bassam Haddad, *Business Networks in Syria*" inside a catalogue. It resolves. It passes every mechanical check, because the machinery can verify that a marker points at a real passage and cannot judge that the passage is a catalogue entry.

**Four reviewers reached the same diagnosis unprompted: the keystone Syrian claim in both papers is carried by Moroccan and Egyptian evidence.** The library holds no Syria-specific networks-of-privilege passage, so the drafter reached for the nearest thing and argued by analogy.

That second finding is the important one, and it is not a retrieval bug. **It is a corpus gap presenting as a citation defect, and no amount of retrieval work fixes it.** The fix is a book. This is exactly what the library measurement in section 6 is for.

Two further defects the four gates do not see: the rendered paper repeated a section heading verbatim, and its citation table listed identifiers that never appear as markers in the body. Both were found by reviewers, both were real, and both have since been fixed. The papers in Appendices D and E are reproduced as they were rendered, with the duplicate heading still visible in Appendix D. It is left there rather than tidied.

### 7.5 Open-weight models against proprietary ones

The same two hard questions were run twice against the same library at the same moment, in two sealed processes that could not read each other's configuration. One used only open-weight models. The other used only proprietary ones. Six blind reviewers judged the outputs, three per question, with the arm order flipped between the two so no judge could learn a position bias.

| | Open arm | Proprietary arm |
|---|---|---|
| Reading the question, retrieval, counter-position | `deepseek-v4-pro`, `glm-5.2` | `openai/gpt-5.4` |
| Writing the answer | `glm-5.2` | `openai/gpt-5.6-sol` |
| **Question B** (judgment) | **open, 3–0** | |
| **Question C** (survey) | | **closed, 3–0** |
| Cost, both questions | **$0.618** | **$2.167** |

**Nobody won the round.** Each arm took the question that suited it, and the six ballots agree on why.

*B is a case question*: which account explains the Syrian pattern, tested against Syrian paramilitaries. The proprietary arm composed five passages, reached no Syrian evidence at all, and answered the paramilitary question with a Colombian example from a footnote. Every judge rated its grounding strong or impeccable and its completeness adequate or weak. Rigorous about material that does not answer the question.

*C is a survey question*: weigh four explanations and test the winner. The proprietary arm weighed all four. The open arm never engaged Wimmer's exclusion-as-legitimacy account, routing that competitor through a narrower thesis instead.

**The mechanical oracle and the human-shaped reader found the same hole, and this is the first time they have been checked against each other.** C on the open arm scored 7 of 8 with "exclusion built into the nation-state form" as its single missed demand. Two blind reviewers, with no access to the case file, named the absence of Wimmer as the reason they preferred the other arm.

The practical reading: the arms are close on quality, split by question type, and **the open arm costs 3.5 times less on the same two questions.** Nothing here argues for moving the wiring.

Three limits bound this comparison and none of them is soft. The test questions are AI-written. Every model in an arm moved at once, so the comparison measures two complete wirings and cannot say which swap produced the result. And it is one draw per cell.

### 7.6 The measurements that were uncomfortable

These are reported because they change how the rest of the report should be read, and because a report that only carries its good numbers is not evidence of anything.

**Gather does not fully reproduce.** Asked twice about the same name, on byte-identical input, the pass returns a different answer **19.3% of the time**, and — the figure that matters more — **36.1% of the disagreements it records come back null on the second reading**. That second number is the honest confidence interval on a name page's central claim: it is the share of asserted disagreements the pass would not re-assert ten hours later. This was investigated and accepted as model variance. Its consequence is enforced in the design rather than hoped away: **a Gather finding is a retrieval hint and never a citation.** No gate scores an answer against one, and no answer is credited for repeating one.

**Name merging disagrees with itself 13.3% of the time** on names with three or more variants. Investigating it showed the disagreements are almost entirely singular/plural and article variants, and that they move **0.43% of the underlying material**. A surface changing group is not its evidence moving, and conflating the two overstated the problem by a factor of thirty.

**Retrieval misses one demand persistently.** Question B's identity-production leg has gone unreached five times, across three versions of the code and two model wirings. The retrieval rewrite was the change most likely to close it. It did not. It is recorded as an open finding rather than explained away.

**More evidence did not produce better answers.** Raising the amount of evidence put in front of the writing model by two to three times tripled the bill and the oracle did not follow. Searching harder was tested separately at two budgets across four paid runs, and the amount of evidence that actually reached the model never moved — 17, 21, 18, 20 passages — while the amount gathered ranged from 56 to 181.

**The panel's false-positive rate is unmeasured.** The control proves the reviewers catch defects that are there. Nothing tests whether they invent defects that are not. Every panel figure carries that limit, and "trusted" means the instrument catches planted defects, never that it does not manufacture them.

---

## 8. Known limits and open problems

Every limit the evidence in this report exposes, collected in one place.

**The test questions are machine-written.** Every question in this report was written by an AI model working from a description of the library. This is the project's largest single limit, and it is the one that most needs outside help to close.

**There is no human referee in the loop yet.** Answer quality is currently judged by a panel of models. **No number in this report may be described as measured against human expert judgment, because none of it is** — and the specification forbids relabelling one that way. That constraint stays in force for as long as the panel is the only referee, and it is exactly what a scholar's questions and a scholar's reading would begin to relax.

**The library is thin where it matters most.** Concepts are the weakest kind of page in it. 83% of all pages exist inside a single book. Several of the largest concept pages are one author's vocabulary that nobody else on the shelf uses.

**A corpus gap looks exactly like a citation defect.** When the library has no passage on the specific thing a paper needs, the drafter reaches for the nearest thing and argues by analogy. The panel caught this. The mechanical gates cannot.

**The shelf is built around Syria, and every paper inherits that.** Six of the eight papers written so far were drafted deliberately off the Syrian case to test how far the library reaches (Appendix F). Two of them ended up citing a single book, because one comparative study is all the shelf holds on unrecognised states. Topic balance in the questions does not produce topic balance in the evidence, and only new books close that gap.

**Some checks are structurally blind.** A citation marker that resolves to a publisher's catalogue page passes every automated check there is. Whether a passage is the *right kind of thing* to cite is a judgment, and only a reader makes it.

**One draw is not a measurement, and most figures here are one draw.** Run-to-run variance on a single question has been measured at 39% on unchanged code.

**Axial is built, not deployed.** It runs as a command-line tool on one machine, against a library assembled by one person. There is no service, no multi-user boundary, no hosted product. The two-role command-line split that exists today is a guard against running the wrong command by accident, not a security boundary.

**Two phases are not built.** Format adaptation and lens application exist as milestones with no specification, no date and no scheduled work.

---

## Final word

Three phases are built and working: reading the corpus, answering a question from it, and writing the paper. The full chain runs end to end on one command, on a real library of thirty-five scholarly books, for well under a dollar a paper.

What the evidence in this report supports, and no more:

- **The construction holds.** Claims are marked, grounds resolve, confidence is capped by coverage, and counter-position is present or its absence is disclosed. Those are hard gates and they pass at 1.00 on every paper.
- **The panel discriminates.** It caught three planted defects unanimously, and at three reviewers per packet the bands reproduce.
- **The findings that matter came from readers, not from the machinery.** The two most valuable defects found in this evaluation were a mis-typed citation and a corpus gap, and both were found by sealed reviewers reading the paper the way a referee reads a submission.
- **Open-weight models are competitive in production for this work, at roughly a third of the cost.**

What it does not support: any claim about answer quality against a real scholarly question. That gap is the shape of what we are asking for.

**If you are a scholar or a researcher**, there are three contributions, in ascending order of commitment, and the first is genuinely small.

*Set the questions.* A few real research questions from your area of expertise, of the kind you would actually put to a doctoral student. Three is a real contribution. A machine can invent a question that exercises the engine; only someone who knows the field can write one whose answer is worth judging.

*Read an answer.* A paper and the passages it cites, judged the way you would referee a submission. That is the instrument section 7.4 currently fills with a panel of models, and a human verdict beside those would be the first of its kind here.

*Say what the shelf is missing.* The library measurement in section 6 names which topics have only one voice. Which book should answer Jackson on sovereignty, or Mann on infrastructural power, is a question a specialist answers in a sentence and we cannot answer at all.

**If you are an institution or a funder**, the interesting property is that everything here is checkable. There is no aggregate score to take on faith. Every claim in every output walks back to a passage in a book, every intermediate artifact is on disk, every model call has a recorded cost, and the limits are written into the specification rather than into a footnote.

**If you want to see it fail**, the fastest route is a question the library is thin on. That is a legitimate test and it is the one the design most wants to pass, because saying "the sources do not support this" is a first-class output rather than an error.

---

## Appendix A — How the test questions were designed

Who wrote the tests, and could they have been written to be passed?

### A.1 Why the questions are machine-written, and what would change that

The original plan was to collect research questions from working scholars and test Axial against those. When none had arrived, the project stopped waiting and built its own set, so that the engine could be developed and hardened rather than blocked. That is where things stand today: the question set is machine-written, and it is the standing arrangement rather than a settled end state. A set of questions from people who know the field is the single contribution that would most change what this report can claim, and asking for it is the reason this document exists.

"We used AI to write our own test" invites a suspicion it should invite, so here is what the machine-written questions are and are not used for. A test question does two jobs here. It is an **input** that exercises a retrieval shape, and it is an **answer key** against which quality is scored. Axial's evaluation uses simulated questions only for the first job. **Nothing simulated is ever an answer key.** Every judgment in every gate is anchored to material the library actually holds — the resolved text of a cited passage, a premise a test brief states plainly about itself, the paper's own coverage counts. Not one of them compares an output against a model's opinion of a good answer.

An earlier design did have such an answer key, a pre-written "expected answer" per case. **It was retired as a referee**, on the grounds that scoring against it measures agreement with one model's opinion rather than quality, and it is now barred from ever being placed in a reviewer packet, because showing a reviewer a pre-written answer anchors it to that answer.

So the honest statement is the one made in section 7.1: the questions are machine-written, and **that bounds what the numbers mean rather than what they are anchored to.** It also names the gap a scholarly contribution would fill.

### A.2 The two question sets, and why they are different

**Six short briefs, run on every change.** These exist to catch regressions cheaply, so each is short and each exercises exactly one retrieval shape: a hub anchor at the library's centre of gravity, scholar against scholar, a contested concept, a concept whose founding book is on the shelf, thin coverage, and single-source concentration. Their anchors were measured against the live index before they landed, book by book, and are printed in section 7.2.

The set was **rebuilt from scratch on 2026-07-30** for a reason that says something about how this project handles its own convenience. All five original briefs were Syria briefs. Twenty-five of the then thirty-one books are not about Syria, so the set was leaving most of the library unexercised and scoring well on the part it did reach. The replacements were authored **by a model with no access to this repository**, working from the measured index alone, then verified anchor by anchor before being accepted. One Syria brief was deliberately retained, because the source-concentration inspection needs a hub name to bite on.

**Three hard questions, run when the engine is stable.** These are long compound questions of the kind a doctoral examiner sets: weigh four or more competing explanations, test a preferred account against a second historical setting, engage the critics of the major theorists rather than only the theorists. They were authored the same way — by a model outside this environment, working from the library overview alone, **told what each question had to stress and forbidden to name a book or ask for citations.** Their provenance, and the single edit made to them, is recorded in the repository.

**An adversarial set, which is the one place a question does carry an answer key.** Each of these briefs has a premise deliberately smuggled into it, and states that premise plainly in a block **that is stripped out before the brief ever reaches the interrogation prompt.** A brief that leaks its own answer key measures nothing. The gate then asks whether the pre-pass caught the premise, judged by an independent model as correspondence of meaning rather than string matching.

One question moved into this set for an instructive reason. It asks about "Tilly's coercive-extraction cycle", which is the argument of *Coercion, Capital and European States*. The library holds a different Tilly book. That is a smuggled premise, and it is worth more as a test of whether Axial notices than as a synthesis question.

### A.3 Two design rules that keep a question from being a softball

**A question must not name the finding it probes.** The thin-coverage and single-source questions ask nothing about thinness or concentration. Asking "why is the evidence on Transnistria thin" would make a pass prove only that the model follows instructions. The requirement that a run notice thinness unprompted lives in the scoring rubric instead, where the system cannot read it.

**Gates are scored on questions the system cannot already ace.** A test suite tuned until it passes measures the tuning. The three hard questions are deliberately the hardest thing the engine is asked to do, and two of their known weaknesses are documented in the specification rather than removed from the set.

### A.4 The oracle: how "did it reach the right books" is scored

Each test question has a **case file** stating what the answer must reach, as a list of demands. Each demand names the books that carry material capable of satisfying it, and a demand is met when the run's citations reach **any** of them.

That structure replaced a flat list of required book identifiers, and the reason is a real defect it caused. Under the old shape one question required a commentary volume *about* a theorist and could be satisfied without ever citing that theorist's own four books, because a mechanical count-and-cut rule had named the commentary as the leading carrier. The rule is now explicit: **a demand whose anchor is an author or a work names that author's own books, never the books that cite them**, and counts choose among candidate carriers only where a demand's material genuinely spans more than one book.

Building a case file is one read-only pass over the index plus a judgment per demand. It costs no model call, and it is checked against the live index so that a case naming a book the library no longer holds is a named failure rather than a silent zero.

---

## Appendix B — How answers and papers are judged

### B.1 The four instruments, and what each cannot do

**Mechanical checks, on every run.** Does every claim carry a kind? Do all cited passages resolve? Is the coverage map non-empty? Did the run stay inside its cost and time budget? Was any proposed query refused by the dispatcher? None of these is a quality judgment, and none of them can be. They are the floor.

An important property of this layer: **a check with nothing to measure reports a third state, and that third state blocks release.** A metric that vacuously passes on zero observations reads as a green light for a check that never ran. A metric that fails on an input it never had sends a reader debugging the wrong thing. Both are worse than saying plainly that nothing was measured, so "not scoreable" is distinct from both pass and fail and is never collapsed back into a boolean anywhere downstream.

**The five engine gates.** Attribution fidelity, grounding, counter-position presence and steelman quality, band-wise calibration, and adversarial premise-catching. Each judged check runs under its own identity and **must resolve to a different model than the pass it grades**; the guard raises before any judging call is made. Confidence is checked band by band — do the claims marked high actually hold up at the rate high implies — rather than as an error over a continuous score, because the three-band vocabulary deliberately does not produce a number to compute an error over.

**The four paper gates**, described in section 7.3.

**The panel**, described in section 7.4.

### B.2 Why several obvious metrics are deliberately not gates

Source concentration, the cross-source inference rate, the share of evidence drawn from commentary rather than primary work, and the contradiction rate on new inferences are all computed and reported on every run, and **none of them is a gate.**

That absence is a decision rather than an oversight. A threshold asserted before its distribution has been inspected would flag legitimately concentrated, legitimately single-source, legitimately commentary-drawing analyses as failures. The stated rule for promoting any of them to a gate is: inspect the distribution, find a cut point that separates what a reader judges good from what they judge bad, then set it. Not before.

The same discipline retired a check that had been asserted and never fired: a threshold on how much three reviewers may disagree with each other. Outside a gate there is nothing for a threshold to block, and a number nobody enforces invites the reflex of loosening it until it stops firing. **Reporting the spread stays mandatory. Thresholding it does not.**

### B.3 The seven properties that make a review a review

1. **A stranger to the repository.** Each reviewer is a model that has never seen this codebase, its specifications, its prompts, or its cases. It reads the paper the way a journal referee reads a submission.
2. **A sealed packet, enforced by tooling.** The rendered paper, the resolved text of every cited passage, the bibliography. Nothing else. No path into the repository exists in the packet.
3. **A different training lab, not merely a different model.** A vendor collision is an error raised before any reviewer call.
4. **N ≥ 3 independent reviewers, and the spread is reported.** A mean without a spread is not reportable.
5. **A structured verdict, never free prose.** Ordinal bands per dimension plus named defects tied to claim identifiers. A response that does not parse is a failed call, never a silently imputed score.
6. **A positive control, mandatory before any number is trusted.** Three planted defects: a mis-grounded claim, a strawmanned counter-position, an over-confident band. A plant that cannot be applied is an error, never a skip — a control that quietly plants two defects and then passes is worse than no control.
7. **Packets are assembled at run time and never committed.** They carry verbatim text from copyrighted books. What may be recorded is the verdict: scores, defect kinds, claim identifiers, reviewer models and labs. Never the text.

### B.4 The reporting rules that bind

**Every panel figure travels with its frame**: which papers, drawn from which performance tiers, under which model wirings, at which corpus version, judged by how many reviewers from which labs, with what spread. A number without its frame is a different claim.

**No panel figure may be reported as measured against human expert judgment.** There is no human expert in this loop today. A model-refereed score relabelled as a human-validated one is manufactured precision wearing a different costume, and it is the one way this project could launder its own limits. If human referees do join, their verdicts are a separate instrument with its own frame, reported as such and never merged into the panel's numbers.

**No paper waits on a panel and no gate reads one.** A gate that named a missing panel verdict as its reason for being untrusted would be wrong by construction, because most papers will never receive one by design.

---

## Appendix C — The library

Thirty-five sources. Thirty-three are books, all held complete; seven of those are edited collections and four are volumes of one work (Mann's *Sources of Social Power*). The remaining two are a journal article and an unpublished master's research paper, flagged below.

Bibliographic data was recovered from the files themselves — embedded metadata, title pages, copyright pages — and cross-checked. Fields that could not be confirmed are marked as not recovered rather than guessed.

"Passages" is how many passages the book was cut into. "Concepts it alone holds" counts the concepts no other book on the shelf mentions, which is the sharpest measure of where the library has nobody to answer a book with.

| Source | Passages | Name pages touched | Concepts it alone holds |
|---|---:|---:|---:|
| Mann, *The Sources of Social Power*, vol. II | 459 | 4,127 | 431 |
| Heydemann, ed., *War, Institutions, and Social Change* (2000) | 350 | 2,617 | 199 |
| Mann, *The Sources of Social Power*, vol. I | 349 | 2,950 | 338 |
| Kalyvas, *The Logic of Violence in Civil War* (2006) | 335 | 3,225 | 205 |
| Mann, *The Sources of Social Power*, vol. III | 319 | 3,265 | 362 |
| Ayubi, *Over-stating the Arab State* (1995) | 317 | 3,484 | 581 |
| Mann, *The Sources of Social Power*, vol. IV | 293 | 2,934 | 354 |
| Beshara, ed., *The Origins of Syrian Nationhood* (2011) | 290 | 3,247 | 309 |
| Gellner, *Muslim Society* (1981) | 268 | 1,675 | 171 |
| Batatu, *Syria's Peasantry* (1999) | 237 | 2,988 | 168 |
| Hall & Schroeder, eds., *An Anatomy of Power* (2006) | 232 | 2,063 | 321 |
| Hinnebusch, *Authoritarian Power and State Formation* (1990) | 228 | 1,517 | 126 |
| Malešević, *Nation-States and Nationalisms* (2013) | 214 | 1,525 | 144 |
| Heydemann, ed., *Networks of Privilege* (2004) | 208 | 2,260 | 186 |
| Wimmer, *Waves of War* (2013) | 197 | 1,750 | 172 |
| Malešević, *The Sociology of War and Violence* (2010) | 194 | 1,994 | 264 |
| Gelvin, *Divided Loyalties* (1998) | 191 | 2,001 | 144 |
| Tilly, *From Mobilization to Revolution* (1978) | 189 | 1,406 | 234 |
| Kao & Lust, eds., *Decentralization, Local Governance, and Inequality* (2025) | 183 | 2,112 | 100 |
| Wedeen, *Authoritarian Apprehensions* (2019) | 166 | 1,823 | 179 |
| Zaum, *The Sovereignty Paradox* (2007) | 165 | 1,864 | 130 |
| White, *The Emergence of Minorities in the Middle East* (2011) | 160 | 1,475 | 103 |
| Malešević & Haugaard, eds., *Ernest Gellner and Contemporary Social Thought* (2007) | 150 | 1,751 | 304 |
| Vignal, *War-Torn* (2021) | 146 | 1,419 | 104 |
| Jackson, *Quasi-States* (1990) | 132 | 1,463 | 181 |
| Chouliaraki, *Wronged* (2024) | 127 | 1,742 | 136 |
| Bayat, *Revolution without Revolutionaries* (2017) | 122 | 1,924 | 192 |
| Elcheroth & Reicher, *Identity, Violence and Power* (2017) | 120 | 981 | 87 |
| Caspersen, *Unrecognized States* (2012) | 115 | 1,338 | 84 |
| Gould, *Collision of Wills* (2003) | 109 | 658 | 73 |
| Üngör, *Paramilitarism* (2020) | 92 | 1,355 | 88 |
| Smith, *Ethno-symbolism and Nationalism* (2009) | 84 | 1,292 | 146 |
| Agamben, *State of Exception* (2005) | 53 | 624 | 188 |
| Kandiah, *State Legitimacy and Capacity in the Syrian Conflict* (2018)<br/>*master's research paper* | 29 | 223 | 14 |
| Malešević, 'Do Civil Wars Make or Break States?' (2026)<br/>*journal article* | 19 | 336 | 15 |
| **35 sources** | **6,842** | | |

The full bibliography, with publishers, editions, translation notes and per-file provenance caveats, is in `docs/corpus-bibliography.md`.

**Two entries are small enough to question.** Kandiah 2018 and Malešević 2026 are a master's research paper and a journal article rather than books, and both are close to invisible in the index. Gould 2003 now joins them at the thin end.

**The metadata warning is not hypothetical.** The Heydemann *War, Institutions, and Social Change* file carries embedded metadata attributing it to Michael Hanby's *Augustine and Modernity*, a different book entirely. Two further files carry a placeholder author or a scanning-tool title. Embedded metadata alone is not a safe basis for citation, which is why it is cross-checked against the title page and why unconfirmed fields stay marked.

**Copyright.** No source text is committed to the repository. Every derived artifact that carries verbatim passages — the passage records, the name pages, the reviewer packets — lives outside version control for that reason, and reviewer packets are assembled at run time and never written into the repository.

---

## Appendix D — The first paper, and the questions behind it

### The paper brief

**Title.** Privilege and the Contracted-Out Militia

**Organising question (the `thesis` field).** The Syrian regime's survival and its violence are usually explained by different mechanisms, and they should not be. If networks of privilege are what institutionalised the state, then contracting coercion out to militias is not a departure from that arrangement but its continuation by other means.

**Lens.** political-economy

**Built from 2 prior analysis records.** The drafter never sees the library. It sees only the claims those records produced, and it cannot fetch anything else.

### The research questions those records answered

These are the questions put to Axial, verbatim. Each was answered on its own, with its own retrieval, its own counter-position and its own checks, before the paper was planned.

**Question 1** — `124f7ba6ff8927c7`

> **Case.** Syria, 2000–2011
>
> **Request.** Does the concept of the 'fierce but weak' state resolve the paradox of Syrian authoritarian resilience, or do networks of privilege constitute the actual institutional structure of the regime, rendering infrastructural power assessments misleading?

**Question 2** — `47f316f6fb04bba7`

> **Case.** Syria, 2011-2024
>
> **Request.** How does the deliberate, state-sponsored paramilitarization of the Syrian conflict (Ungor) challenge Tilly's coercive-extraction cycle? Specifically, how does reliance on external geopolitical rents and non-state militias circumvent the necessity for domestic taxation and bureaucratic rationalization, thereby causing the war-making apparatus to actively hollow out infrastructural power rather than consolidate it (Malesevic, Mann)?

### What the paper came out as

| What was counted | The count |
|---|---|
| Claims | 39 |
| By kind | (a) 20, (b) 12, (c) 7 |
| Made by the paper itself, not carried from a record | 4 |
| Books cited | 13 |
| Confidence band | low |
| Shape check | strong |
| Cost to draft | $0.082 |

### The paper, as rendered

*Reproduced exactly as Axial produced it, including the confidence and coverage disclosure, the shape check, the citation index and the bibliography. Nothing has been edited, tidied or shortened.*

---

### Privilege and the Contracted-Out Militia

Because networks of privilege constituted Syria's institutional structure, the regime's survival and its turn to paramilitary coercion are a single political-economic process: contracting violence to militias continued the rent-distribution logic that had long bound elites and populations to the state.

#### The puzzle of separate explanations for survival and violence

The Syrian conflict produced two literatures that rarely speak to each other. One asks how the regime survived a mass uprising that toppled counterparts in Tunisia, Egypt, and Libya; the other asks why the state's monopoly on organized force fragmented into a patchwork of militias, shabiha, and foreign proxies. Each question has generated its own explanations—survival attributed to sectarian engineering, international patronage, or institutional cohesion; violence attributed to military weakness, sectarian hatred, or tactical adaptation. What falls out of this division is the possibility that the two phenomena are not merely concurrent but constitutive of one another, that the mechanism which kept the regime alive is the same mechanism that pushed it to contract coercion to irregular armed groups.

That possibility becomes visible only when survival and violence are read through the regime's political-economic structure rather than against a backdrop of institutional form. Syria's state did not rest on a Weberian bureaucracy extracting taxes and delivering services; it rested on networks of privilege through which rents—whether from oil, smuggling routes, land, or aid flows—were distributed in exchange for loyalty. Under normal conditions, those networks bound elites and populations to the state by making their material reproduction dependent on the state's continued capacity to allocate. When uprising and sanctions contracted the rents available for distribution, the logic did not disappear; it found a new substrate. Contracting violence to militias distributed the means of coercion along the same channels that had distributed economic rents, binding commanders and fighters to the regime's survival through the spoils of war rather than the salaries of peacetime.

The puzzle this paper addresses, then, is not why the regime survived or why it turned to paramilitaries considered separately. It is why these two outcomes, so persistently analyzed in isolation, are better understood as a single process: the continuation of rent-distribution under conditions in which violence itself became the principal rent. Treating them together requires setting aside the assumption that institutional form and coercive strategy are independent variables, and asking instead what distributive structure could make the outsourcing of violence a rational—indeed the most rational—response to a crisis of revenue and loyalty.

#### Networks of privilege as the institutional foundation of the Syrian state

#### Networks of privilege as the institutional foundation of the Syrian state

The institutional structure of the Syrian state between 2000 and 2011 was not its bureaucracy but its patronage networks. Dense, overlapping ties among public officials and private economic actors so thoroughly dissolved the boundary between state and business that treating "public" and "private" as separable domains risks misdescribing the regime's actual operating logic [pc-001]. This is not a deficiency of formal capacity that the regime compensated for through coercion; it is a substitution of one form of infrastructural penetration — rent distribution through elite networks — for the bureaucratic penetration that standard frameworks expect [pc-007].

Mann's definition of infrastructural power as the state's capacity to penetrate its territory and logistically implement decisions presupposes that penetration runs through administrative channels [pc-004]. Where the operative mechanism is patronage rather than bureaucracy, that definition will register absence: it will read network-based control as state weakness. Yet what appears as infrastructural deficit may instead be the displacement of administrative capacity by material incentives that empower non-state actors aligned with the regime — a pattern visible as early as the Ottoman period in southern Syria, where external subsidies to tribal actors eroded bureaucratic penetration not because the state lacked power but because network-based control was substituted for it [pc-006]. Critiques of Mann's framework for conflating ideological power with organizational infrastructure, and for requiring subjective appraisals of meaning-systems that fit poorly with organizational materialism, compound the problem: a framework already built around bureaucratic legibility becomes doubly unreliable when applied to regimes whose institutional structure is informal and network-based [pc-008][pc-036].

The durability of this structure under pressure confirms that it is institutional rather than incidental. Egypt's 1990s privatization did not dismantle elite networks; it allowed state bureaucrats and businessmen to entrench monopoly positions while the state retained its central role as rent distributor [pc-002]. Market-oriented reform, in other words, did not break the network — it reconfigured it. The same scholarly trajectory that established this pattern for Middle Eastern authoritarianisms more broadly directly connected it to Syrian authoritarian resilience in the pre-2011 period [pc-003]. If no Arab state has been a developmental success story — Ayubi's own concession — the explanation under this lens is not the absence of state power but the redirection of distributive capacity toward elite reproduction rather than developmental outcomes [pc-005]. The state was not weak; it was organized for a different purpose.

This reframing dissolves what has been framed as a paradox. The "fierce but weak" characterization of the Syrian regime is descriptively accurate about coercive posture but resolves nothing analytically, because it misidentifies the source of resilience: stability derived not from despotic power compensating for infrastructural weakness, but from networks of privilege that functioned as a substitute form of infrastructural penetration, organizing society through patronage rather than administration [pc-007]. The regime's institutional foundation was rent distribution through networks, and the turn to paramilitary coercion after 2011 would prove to be a continuation of that same logic under conditions of armed conflict.

#### The war-as-erosion view: external rents, paramilitaries, and the hollowing of the state

The most forceful challenge to reading Syria's paramilitarization as a continuation of rent-distribution comes from the bellicist tradition, in which war is the engine of state-building: preparation for war drives rulers to extract resources from subject populations, build new bureaucracies to manage that extraction, face resistance, and emerge with durable increases in infrastructural capacity [pc-010][pc-011]. If this mechanism operated in Syria, the war should have consolidated the state. The erosion view contends that it did the reverse—that Syria's wartime trajectory produced the inverse of the European bellicist outcome.

Three convergent dynamics are said to have reversed the cycle. First, external geopolitical rents from Iran and Russia funded the regime's war-making, eliminating the necessity for domestic taxation as a precondition for sustained coercion [pc-022]. When external alliances supply resources to a war-making movement, they obviate the need to struggle with domestic social actors over extraction, marginalizing internal contests and fragmenting authority through competitive rent-seeking [pc-013]. The Palestinian case supplies the theoretical key: under conditions of external rent substitution, war undermined state building rather than facilitating it, leaving a polity that is fragile, fragmented, and contested, with the right to rule grounded in armed struggle rather than a negotiated social pact [pc-014][pc-024]. Syria's transformation from uprising to civil war to inter-state war through external intervention multiplied this dynamic, as each intervening power brought its own forces and proxies, further substituting geopolitical rents for domestic extraction and producing the opposite of the European outcome where war drove bureaucratization and infrastructural consolidation [pc-018][pc-025]. Second, the outsourcing of violence to paramilitaries who are self-funded through looting and rent-seeking decoupled the war-making apparatus from both domestic extraction and the state's bureaucratic apparatus [pc-012][pc-026]. Self-funding militias operating through criminal economies bypassed the state's extractive apparatus while usurping its monopoly on legitimate coercion, so that paramilitarization actively hollowed out infrastructural power rather than consolidating it [pc-023]. The fusion of external rents with outsourced paramilitary violence produced a coercive ecology that was structurally parasitic on the state's own infrastructural substance rather than generative of it [pc-027]. Third, this double decoupling compounds a structural condition predating the war: the Arab state already lacks infrastructural power—the capacity to penetrate society through mechanisms such as taxation—and must resort to raw coercion to preserve itself [pc-009][pc-015]. External rents delink extraction and redistribution from the national productive economy, producing high state autonomy vis-à-vis social interests; in the mid-1990s more than half of Middle Eastern state revenues were non-tax revenues [pc-016], and oil rents in Jordan expanded the public sector while simultaneously weakening institutional capacity [pc-017]. On this reading, paramilitarization did not create a novel dynamic of state erosion so much as accelerate a pre-existing trajectory of infrastructural weakness [pc-030].

The bellicist tradition itself supplies grounds for doubting that Syria should have followed the European path. Mann revised Tilly's dictum to acknowledge that wars no longer make states as they once did and that the fiscal-military nexus is no longer the backbone of advanced countries [pc-020], and the Tilly/Mann war-driven modernization path may be a European exception rather than a global norm, given that Latin America and postcolonial Africa saw very few inter-state wars [pc-019]. Civil wars foster state formation only under specific conditions—total victory, political neutralization of the opposition, reduction of ethnic factionalism, and continuous economic growth—none of which obtained in Syria, where external intervention, ethnic factionalism, and economic collapse prevailed [pc-021]. The deliberate, state-sponsored paramilitarization of the Syrian conflict thus constitutes, on this account, a definitive challenge to the coercive-extraction cycle: the fusion of external geopolitical rents with outsourced paramilitary violence created a war-making apparatus structurally decoupled from domestic extraction and bureaucratic rationalization, causing it to hollow out infrastructural power rather than consolidate it [pc-028].

The erosion view nonetheless carries a liability it does not resolve. If infrastructural power was being actively destroyed through paramilitarization and external rent dependence, the account must explain why the Assad regime endured rather than collapsed [pc-029]. The concession the framework gestures toward—that despotic power exercised through paramilitaries backed by external patrons may substitute for infrastructural power in sustaining regime survival—undermines its own premise that coercion organized outside the bureaucratic apparatus is evidence of state weakness rather than of an alternative form of penetration. The networks-of-privilege framework identifies exactly such penetration: patronage networks that organize society without bureaucratic legibility and that the standard infrastructural-power assessment systematically misreads as weakness [pc-004][pc-036]. Both the erosion view's inability to account for regime survival and the infrastructural-power assessment's misreading of network-based control as state weakness converge on the same blind spot: each presupposes that effective state penetration must be bureaucratically legible, so that paramilitary coercion organized through informal channels is read as erosion rather than as a substitute mode of penetration that sustains the regime [pc-037]. What the erosion view describes as the hollowing of the state is therefore better understood as the continuation of a rent-distribution logic displaced onto paramilitary channels—the same logic that, before the war, bound elites and populations to the state through networks of privilege rather than through administrative capacity [pc-001][pc-007][pc-038].

#### Continuation by other means: paramilitary violence as network logic

Paramilitary violence in Syria did not replace the regime's institutional structure; it was that structure, operating through the same logic of rent distribution via informal networks that had constituted the regime's power before 2011. What looks like state collapse—the proliferation of militias, the outsourcing of coercion to criminal networks, the regime's inability to reassert bureaucratic control even after military reconquest—is better understood as the continuation of a rent-distribution logic displaced onto paramilitary channels [pc-038].

The regime's operative institutional structure was never bureaucratic capacity but dense, overlapping networks of public officials and private economic interests that distributed rent and managed access to economic opportunity [pc-001]. These networks performed the functional equivalent of infrastructural penetration—binding elites and populations to the state through patronage rather than administration [pc-031][pc-007]. Standard assessments that look only for formal bureaucratic capacity therefore systematically misread network-based control as state weakness [pc-036][pc-037]. The "fierce but weak" framework, which treats the regime's coercive posture as compensation for absent infrastructural power, resolves no paradox because it misidentifies the source of resilience: stability derived from networks that functioned as substitute penetration, not from despotic power filling an institutional vacuum [pc-007][pc-031].

When the uprising ruptured these networks in 2011, the regime's response was not to build the bureaucratic capacity it had never possessed but to displace the rent-distribution logic onto paramilitary channels. Paramilitary forces conducted counter-insurgency operations, held power beyond the state's official security organs, maintained close links with political elites including the head of state, and operated in the social milieu of organized crime [pc-034]. Their self-funding through looting and rent-seeking meant the war-making apparatus was decoupled from both domestic extraction and the state's bureaucratic apparatus [pc-012][pc-026]—but this decoupling reproduced, rather than abandoned, the regime's reliance on informal networks as the operative mechanism of social control: the paramilitaries' criminal self-funding was itself a form of rent distribution through informal channels, the same logic by which networks of privilege had allocated economic opportunity before the war [pc-039]. The Suleiman al-Assad murder case encapsulates the dynamic. A regime-connected figure killed an air force colonel with impunity; the state's judicial apparatus failed to hold him accountable; an external patron, Iranian Quds Force commander Qasem Suleimani, intervened to mediate; and the perpetrator ultimately fled to Romania [pc-035]. The state's formal institutions were irrelevant to the resolution. The operative mechanisms were network ties, external rent, and patronage mediation—the same elements that had constituted the regime's institutional structure all along.

This synthesis carries an honest limit. If networks of privilege constituted a robust institutional structure that functionally substituted for infrastructural power, the scale and speed of the 2011 uprising's spread across Syria suggests these networks either did not penetrate society as deeply as the framework implies, or that they generated grievances among excluded populations that outweighed their stabilizing effects [pc-032]. Post-2011 evidence from Daraa compounds the difficulty: even after military reconquest the regime could not reinstate a monopoly over local governance and operated through tacit delegation to armed factions and tribal committees [pc-033]. This indicates that the regime's infrastructural reach was always thinner than either the "fierce but weak" or the networks-of-privilege framework fully captures, and that both overstate the regime's institutional depth in different ways [pc-033]. The continuation thesis does not require that the networks were uniformly deep or uniformly stabilizing. It requires that the regime's response to their partial failure followed the same logic that had governed their operation—rent distribution through informal delegation rather than bureaucratic consolidation—and on that score the evidence is consistent.

#### Confidence and coverage

**Overall confidence:** low (band shown with the coverage counts that justify it).

overall confidence is 'low', bounded by the least-covered name the paper cites ('Business Networks in Syria: The Political Economy of Authoritarian Resilience', band 'thin'); coverage by name: Business Networks in Syria: The Political Economy of Authoritarian Resilience (thin: 1 corpus notes, 1 cited claims); Charles Tilly (dense: 154 corpus notes, 18 cited claims); Infrastructural power (moderate: 51 corpus notes, 10 cited claims); Loyalist paramilitary group (thin: 2 corpus notes, 10 cited claims); Siniša Malešević (moderate: 69 corpus notes, 1 cited claims); Syria (dense: 962 corpus notes, 26 cited claims); Syrian regime (thin: 11 corpus notes, 2 cited claims); fierce state (thin: 1 corpus notes, 6 cited claims); networks of privilege (thin: 2 corpus notes, 7 cited claims); oil rents (thin: 3 corpus notes, 3 cited claims)

| name | corpus notes | cited claims | coverage |
|---|---:|---:|---|
| Business Networks in Syria: The Political Economy of Authoritarian Resilience | 1 | 1 | thin |
| Charles Tilly | 154 | 18 | dense |
| Infrastructural power | 51 | 10 | moderate |
| Loyalist paramilitary group | 2 | 10 | thin |
| Siniša Malešević | 69 | 1 | moderate |
| Syria | 962 | 26 | dense |
| Syrian regime | 11 | 2 | thin |
| fierce state | 1 | 6 | thin |
| networks of privilege | 2 | 7 | thin |
| oil rents | 3 | 3 | thin |

#### Shape check

**Band:** strong.

#### Citations

| id | kind | confidence | grounds | source |
|---|---|---|---|---|
| pc-001 | a (carried) | low | heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001 | Steven Heydemann (2004) |
| pc-002 | a (carried) | low | heydemann-2004-72a4a9a9b3b0_58_conclusion_001 | Steven Heydemann (2004) |
| pc-003 | a (carried) | low | bayat-2017-ce6bb0643cfb_101_joel-beinin-editor_001 | Asef Bayat (2017) |
| pc-004 | a (carried) | medium | hall-2006-449559bfe4dc_68_infrastructural-power-and-globalization_001 | John A. Hall and Ralph Schroeder (2006) |
| pc-005 | b (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001 | Ayubi, Nazih N.; (1995); Steven Heydemann (2004) |
| pc-006 | a (carried) | medium | heydemann-2000-66701ffbb36c_38_conclusion_001 | Steven Heydemann (2000) |
| pc-007 | c (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001, hall-2006-449559bfe4dc_68_infrastructural-power-and-globalization_001 | Ayubi, Nazih N.; (1995); John A. Hall and Ralph Schroeder (2006); Steven Heydemann (2004) |
| pc-008 | b (carried) | medium | hall-2006-449559bfe4dc_111_frank-trentmann_009, hall-2006-449559bfe4dc_48_performance-on-the-hazards-of-analytical-tacking_001 | John A. Hall and Ralph Schroeder (2006) |
| pc-009 | a (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003 | Ayubi, Nazih N.; (1995) |
| pc-010 | a (carried) | high | mann-v1-2012-5f90ead66c93_136_implication-i-the-emergence-of-the-national-state_003 | Mann, Michael (2012) |
| pc-011 | a (carried) | high | mann-v2-1993-ec759675dcbd_111_phase-2-revolution-reform-and-representation-1780-1850_003 | Michael Mann (1993) |
| pc-012 | a (carried) | low | ungor-2020-ae5701dcc706_31_92-paramilitarism_003 | Uğur Ümit Üngör (2020) |
| pc-013 | a (carried) | high | heydemann-2000-66701ffbb36c_101_yezid-sayigh_004 | Steven Heydemann (2000) |
| pc-014 | a (carried) | high | heydemann-2000-66701ffbb36c_101_yezid-sayigh_004 | Steven Heydemann (2000) |
| pc-015 | a (carried) | high | ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002 | Ayubi, Nazih N.; (1995) |
| pc-016 | a (carried) | low | heydemann-2004-72a4a9a9b3b0_90_rents-and-fiscal-policy_001 | Steven Heydemann (2004) |
| pc-017 | a (carried) | low | heydemann-2004-72a4a9a9b3b0_93_oil-boom-and-rent-seeking-1973-1989_001 | Steven Heydemann (2004) |
| pc-018 | a (carried) | high | malesevic-2026-4faeb528594d_10_forging-statehood-through-inter-and-intra-state-wars_001 | Siniša Malešević (2026) |
| pc-019 | a (carried) | medium | malesevic-2007-323a2518e61b_22_militarism-and-empire_001 | Siniša Malešević and Mark Haugaard (2007) |
| pc-020 | a (carried) | high | mann-v4-2013-1b7e828e0199_14_mad-and-the-decline-of-war_002 | Michael Mann (2013) |
| pc-021 | a (carried) | medium | malesevic-2026-4faeb528594d_10_forging-statehood-through-inter-and-intra-state-wars_002 | Siniša Malešević (2026) |
| pc-022 | b (carried) | low | mann-v1-2012-5f90ead66c93_136_implication-i-the-emergence-of-the-national-state_003, ungor-2020-ae5701dcc706_31_92-paramilitarism_003, ungor-2020-ae5701dcc706_10_4-paramilitarism_001, heydemann-2000-66701ffbb36c_101_yezid-sayigh_004, malesevic-2026-4faeb528594d_10_forging-statehood-through-inter-and-intra-state-wars_001 | Mann, Michael (2012); Siniša Malešević (2026); Steven Heydemann (2000); Uğur Ümit Üngör (2020) |
| pc-023 | b (carried) | low | ungor-2020-ae5701dcc706_31_92-paramilitarism_003, ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002, ungor-2020-ae5701dcc706_10_4-paramilitarism_001, mann-v1-2012-5f90ead66c93_136_implication-i-the-emergence-of-the-national-state_003, mann-v2-1993-ec759675dcbd_111_phase-2-revolution-reform-and-representation-1780-1850_003 | Ayubi, Nazih N.; (1995); Mann, Michael (2012); Michael Mann (1993); Uğur Ümit Üngör (2020) |
| pc-024 | b (carried) | low | heydemann-2000-66701ffbb36c_101_yezid-sayigh_004, malesevic-2026-4faeb528594d_10_forging-statehood-through-inter-and-intra-state-wars_001, ungor-2020-ae5701dcc706_31_92-paramilitarism_003 | Siniša Malešević (2026); Steven Heydemann (2000); Uğur Ümit Üngör (2020) |
| pc-025 | b (carried) | medium | malesevic-2007-323a2518e61b_22_militarism-and-empire_001, malesevic-2026-4faeb528594d_10_forging-statehood-through-inter-and-intra-state-wars_001, mann-v4-2013-1b7e828e0199_14_mad-and-the-decline-of-war_002, mann-v1-2012-5f90ead66c93_136_implication-i-the-emergence-of-the-national-state_003 | Mann, Michael (2012); Michael Mann (2013); Siniša Malešević (2026); Siniša Malešević and Mark Haugaard (2007) |
| pc-026 | b (carried) | low | ungor-2020-ae5701dcc706_31_92-paramilitarism_003, ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002, ungor-2020-ae5701dcc706_10_4-paramilitarism_001 | Ayubi, Nazih N.; (1995); Uğur Ümit Üngör (2020) |
| pc-027 | b (carried) | low | heydemann-2000-66701ffbb36c_101_yezid-sayigh_004, heydemann-2004-72a4a9a9b3b0_90_rents-and-fiscal-policy_001, ungor-2020-ae5701dcc706_31_92-paramilitarism_003, ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002, ungor-2020-ae5701dcc706_10_4-paramilitarism_001 | Ayubi, Nazih N.; (1995); Steven Heydemann (2000); Steven Heydemann (2004); Uğur Ümit Üngör (2020) |
| pc-028 | c (carried) | low | mann-v1-2012-5f90ead66c93_136_implication-i-the-emergence-of-the-national-state_003, ungor-2020-ae5701dcc706_31_92-paramilitarism_003, heydemann-2000-66701ffbb36c_101_yezid-sayigh_004, ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002, ungor-2020-ae5701dcc706_10_4-paramilitarism_001 | Ayubi, Nazih N.; (1995); Mann, Michael (2012); Steven Heydemann (2000); Uğur Ümit Üngör (2020) |
| pc-029 | c (carried) | medium | mann-v2-1993-ec759675dcbd_111_phase-2-revolution-reform-and-representation-1780-1850_003, ungor-2020-ae5701dcc706_10_4-paramilitarism_001, ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002 | Ayubi, Nazih N.; (1995); Michael Mann (1993); Uğur Ümit Üngör (2020) |
| pc-030 | c (carried) | low | ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002, ungor-2020-ae5701dcc706_31_92-paramilitarism_003, heydemann-2000-66701ffbb36c_101_yezid-sayigh_004 | Ayubi, Nazih N.; (1995); Steven Heydemann (2000); Uğur Ümit Üngör (2020) |
| pc-031 | b (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001 | Ayubi, Nazih N.; (1995); Steven Heydemann (2004) |
| pc-032 | c (carried) | low | vignal-2021-c7005c2bf8ef_30_fragmenting-space-and-society-to-suppress-the-revolution_001, vignal-2021-c7005c2bf8ef_22_the-shabab-revolution_001 | Leila Vignal ; (2021) |
| pc-033 | b (carried) | low | kao-2025-ab19e646ab7d_54_1-introduction_001, kao-2025-ab19e646ab7d_58_5-local-governance-and-the-return-of-the-regime-mid-2018-to-the-present_002 | Kristen Kao (Editor) (2025) |
| pc-034 | a (carried) | high | ungor-2020-ae5701dcc706_10_4-paramilitarism_001 | Uğur Ümit Üngör (2020) |
| pc-035 | a (carried) | high | ungor-2020-ae5701dcc706_10_4-paramilitarism_001 | Uğur Ümit Üngör (2020) |
| pc-036 | c (this paper's verdict) | medium | hall-2006-449559bfe4dc_68_infrastructural-power-and-globalization_001, hall-2006-449559bfe4dc_111_frank-trentmann_009, hall-2006-449559bfe4dc_48_performance-on-the-hazards-of-analytical-tacking_001 | John A. Hall and Ralph Schroeder (2006) |
| pc-037 | b (this paper's inference) | medium | mann-v2-1993-ec759675dcbd_111_phase-2-revolution-reform-and-representation-1780-1850_003, ungor-2020-ae5701dcc706_10_4-paramilitarism_001, ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002, hall-2006-449559bfe4dc_68_infrastructural-power-and-globalization_001, hall-2006-449559bfe4dc_111_frank-trentmann_009, hall-2006-449559bfe4dc_48_performance-on-the-hazards-of-analytical-tacking_001 | Ayubi, Nazih N.; (1995); John A. Hall and Ralph Schroeder (2006); Michael Mann (1993); Uğur Ümit Üngör (2020) |
| pc-038 | c (this paper's verdict) | low | mann-v2-1993-ec759675dcbd_111_phase-2-revolution-reform-and-representation-1780-1850_003, ungor-2020-ae5701dcc706_10_4-paramilitarism_001, ayubi-1995-16fd6a2e503f_10_the-middle-east-and-the-state-debate-a-conceptual-framework_002, hall-2006-449559bfe4dc_68_infrastructural-power-and-globalization_001, hall-2006-449559bfe4dc_111_frank-trentmann_009, hall-2006-449559bfe4dc_48_performance-on-the-hazards-of-analytical-tacking_001, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_58_conclusion_001, mann-v1-2012-5f90ead66c93_136_implication-i-the-emergence-of-the-national-state_003, ungor-2020-ae5701dcc706_31_92-paramilitarism_003, heydemann-2000-66701ffbb36c_101_yezid-sayigh_004 | Ayubi, Nazih N.; (1995); John A. Hall and Ralph Schroeder (2006); Mann, Michael (2012); Michael Mann (1993); Steven Heydemann (2000); Steven Heydemann (2004); Uğur Ümit Üngör (2020) |
| pc-039 | b (this paper's inference) | low | ungor-2020-ae5701dcc706_31_92-paramilitarism_003, ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001 | Ayubi, Nazih N.; (1995); Steven Heydemann (2004); Uğur Ümit Üngör (2020) |

#### Bibliography

- **kao-2025-ab19e646ab7d** — author: Kristen Kao (Editor) (from embedded metadata); title: Decentralization, Local Governance, and Inequality in the Middle East and North Africa (from embedded metadata); date: 2025 (from title page); publisher: University of Michigan Press (from open_library)
- **vignal-2021-c7005c2bf8ef** — author: Leila Vignal ; (from embedded metadata); title: War-Torn (from embedded metadata); date: 2021 (from title page); publisher: C. Hurst and Company (Publishers) Limited (from open_library)
- **ayubi-1995-16fd6a2e503f** — author: Ayubi, Nazih N.; (from embedded metadata); title: Over-stating the Arab State (from open_library); date: 1995 (from title page); publisher: I. B. Tauris (from open_library)
- **bayat-2017-ce6bb0643cfb** — author: Asef Bayat (from embedded metadata); title: Revolution Without Revolutionaries (from embedded metadata); date: 2017 (from title page); publisher: Stanford University Press (from open_library)
- **hall-2006-449559bfe4dc** — author: John A. Hall and Ralph Schroeder (from title page); title: An anatomy of power : the social theory of Michael Mann (from embedded metadata); date: 2006 (from title page); publisher: Cambridge University Press (from open_library)
- **heydemann-2004-72a4a9a9b3b0** — author: Steven Heydemann (from embedded metadata); title: Networks of Privilege in the Middle East (from embedded metadata); date: 2004 (from title page); publisher: Palgrave Macmillan (from open_library)
- **heydemann-2000-66701ffbb36c** — author: Steven Heydemann (from title page); title: War, Institutions, and Social Change in the Middle East (from title page); date: 2000 (from title page); publisher: University of California Press (from title page)
- **malesevic-2026-4faeb528594d** — author: Siniša Malešević (from title page); title: Do civil wars make or break states? Towards a historical sociology of intra-state conflicts (from title page); date: 2026 (from title page); publisher: Springer Science and Business Media LLC (from crossref)
- **malesevic-2007-323a2518e61b** — author: Siniša Malešević and Mark Haugaard (from title page); title: Ernest Gellner and Contemporary Social Thought (from title page); date: 2007 (from title page); publisher: Cambridge University Press (from open_library)
- **mann-v4-2013-1b7e828e0199** — author: Michael Mann (from embedded metadata); title: The Sources of Social Power (from embedded metadata); date: 2013 (from title page); publisher: Cambridge University Press (from open_library)
- **mann-v1-2012-5f90ead66c93** — author: Mann, Michael (from embedded metadata); title: The Sources of Social Power, Volume 1 (from embedded metadata); date: 2012 (from title page); publisher: Cambridge University Press (from open_library)
- **mann-v2-1993-ec759675dcbd** — author: Michael Mann (from embedded metadata); title: The Sources of Social Power: Volume 2, The Rise of Classes and Nation States 1760-1914 (from embedded metadata); date: 1993 (from title page); publisher: Cambridge University Press (from open_library)
- **ungor-2020-ae5701dcc706** — author: Uğur Ümit Üngör (from title page); title: Paramilitarism: Mass Violence in the Shadow of the State (from title page); date: 2020 (from title page); publisher: Oxford University Press (from open_library)

---

## Appendix E — The second paper, and the questions behind it

### The paper brief

**Title.** What the Mandate Built

**Organising question (the `thesis` field).** The institutions that decided who held power in Syria after 2011 were built under the mandate, not by the Baath and not by the war. What changed across a century was which group the arrangement favoured, and what stayed constant was that belonging, rather than office, was the thing being allocated.

**Lens.** political-economy

**Built from 3 prior analysis records.** The drafter never sees the library. It sees only the claims those records produced, and it cannot fetch anything else.

### The research questions those records answered

These are the questions put to Axial, verbatim. Each was answered on its own, with its own retrieval, its own counter-position and its own checks, before the paper was planned.

**Question 1** — `0ae817e05d4dc424`

> **Case.** Syria, 1920-2011
>
> **Request.** In what specific organizational ways do the French colonial institutionalization of minority identities (White) and the class-based, agrarian mobility structures of the lesser rural notables (Batatu) intersect with Wimmer's 'waves of war' thesis? How did these pre-existing networks of privilege (Heydemann) utilize ethno-nationalist and sectarian boundaries to ensure the organizational cohesion of the state's despotic core against a peri-urban opposition?

**Question 2** — `124f7ba6ff8927c7`

> **Case.** Syria, 2000–2011
>
> **Request.** Does the concept of the 'fierce but weak' state resolve the paradox of Syrian authoritarian resilience, or do networks of privilege constitute the actual institutional structure of the regime, rendering infrastructural power assessments misleading?

**Question 3** — `fd0c2636d456d0fc`

> **Case.** Syria, 2011–2024 — regime, AANES/SDF northeast, Idlib
>
> **Request.** Is fragmented Syria one juridical sovereign under stress or several empirical polities that never acquired recognition? Distinguish Jackson-style negative sovereignty from Caspersen-style de-facto statehood; do not collapse the two.

### What the paper came out as

| What was counted | The count |
|---|---|
| Claims | 66 |
| By kind | (a) 34, (b) 20, (c) 12 |
| Made by the paper itself, not carried from a record | 10 |
| Books cited | 15 |
| Confidence band | low |
| Shape check | strong |
| Cost to draft | $0.199 |

### The paper, as rendered

*Reproduced exactly as Axial produced it, including the confidence and coverage disclosure, the shape check, the citation index and the bibliography. Nothing has been edited, tidied or shortened.*

---

### What the Mandate Built

The institutions that allocated power in Syria from the mandate through the civil war were structured not around formal office or bureaucratic capacity but around the distribution of belonging itself—first by the French imposition of communitarian categories, then by the class-based capture of the state's coercive apparatus by a rural minoritarian officer corps, and finally by the reorganization of rent-seeking through ethno-sectarian patronage networks that substituted infrastructural penetration with clientelistic loyalty, such that what changed across a century was which group the arrangement favored and what remained constant was that material survival and political power depended on inclusion in the network of privilege the state recognized as its own.

#### Introduction: The Puzzle of Syrian Institutional Continuity

Syria's political order survived three ruptures that should, by most accounts, have destroyed it: the end of mandate rule, the social revolution that brought a rural officer corps to power, and the ascent of a narrow patronage regime that repaid loyalty with access to rents. Yet beneath each transition the basic logic of who got what, and on what terms, moved less than the surface drama suggested. The puzzle is not why Syria experienced conflict—it plainly did—but why a century of upheaval left intact a particular institutional grammar: power allocated not through office or capacity but through recognized membership in a privileged network, and survival tied to inclusion in that network rather than to any enforceable claim on the state. This paper argues that the institutions governing distribution in Syria, from the French mandate through the civil war, were structured around the distribution of belonging itself. What shifted across the period was which group the arrangement favored; what remained constant was the mechanism—material survival and political power depended on inclusion in the network of privilege the state recognized as its own. The French imposed communitarian categories that made sect a unit of fiscal and administrative classification; a rural minoritarian officer corps then captured the coercive apparatus on a class basis, converting military rank into a lever over the allocation of resources; and the later regime reorganized rent-seeking through ethno-sectarian patronage networks that substituted clientelistic loyalty for infrastructural penetration. At each stage, the economic base of political power was not productive capacity or broad taxation but the controlled distribution of access—to land, to posts, to licenses, to protection—and the cost was borne by those excluded from whichever category the state currently privileged. Read through a political-economy lens, the continuity is not a residue or a lag but the thing to be explained: how the arrangement reproduces itself when the group it favors changes.

#### The Mandate Origins of Communitarian Allocation

The institutions the French mandate established in Syria allocated access to the state's material resources not through bureaucratic capacity or formal office but through communal category — and in doing so produced the very categories of belonging that would organize Syrian political life for the next century. Officials who arrived with a communitarian understanding of society institutionalized it through military recruitment and administrative division along communal lines [pc-003]. The categories this system required were not primordial: the term 'minority' appeared infrequently in the archives until approximately 1930, when it rapidly became widespread [pc-001], and a coherent Sunni Muslim Arabic-speaking majority had no political reality until the developing Syrian state, together with nationalist ideology, enframed diverse actors and constituted them as a single group [pc-002]. What the mandate imposed, then, was a scheme for allocating material access — to military salaries, to administrative positions, to inclusion within rather than subjection to the coercive apparatus — distributed by communal category rather than by bureaucratic capacity or formal office, while simultaneously manufacturing the categories of minority and majority that would make such allocation appear to reflect the natural composition of society [pc-059].

The Great Revolt of 1925-7 exposed the distributive stakes of this arrangement. French forces suppressed the revolt using irregular troops drawn from Armenian, Circassian, and other communities, organizing coercion against what was in fact a cross-communal, cross-class coalition — one that, as Michael Provence argues, served as a crucible of Syrian nationhood, contrary to the French interpretation of the revolt as sectarian — along the very communal lines the mandate had been institutionalizing [pc-004]. The French interpretation concealed a material logic at work: communities whose members were recruited into irregular paramilitary formations gained access to the state's coercive payroll, while the cross-communal and cross-class coalition that revolted bore the cost of resisting an arrangement that allocated opportunity by communal category rather than by claim of right [pc-060].

The gradual spread of the concept of 'minority' through the 1920s and 1930s as Syrian society transformed under the nation-state form [pc-003] tracked the consolidation of this distributional arrangement. The concept carried ideological baggage that permitted regimes to curtail political rights while presenting themselves as expressions of popular will, through the public aggrandizement of the 'nation' or 'majority' and the identification and persecution of 'minorities' [pc-005]. The logic this established — that a ruling group could claim majoritarian legitimacy while deploying sectarian categories against its opponents — directly predicted the mechanism by which Syria's later despotic core would operate: the regime presented itself as representing the majority while identifying the peri-urban opposition as sectarian threats, inverting the actual minority character of the ruling elite [pc-005]. The mandate's communitarian allocation thus established not merely a taxonomy of identity but a distributional template — in which belonging, not bureaucratic capacity or formal office, determined access to the material resources of the state — whose beneficiaries would change across the century but whose logic would persist [pc-061].

#### Class, Coercion, and the Ruralization of the State

The colonial political economy that concentrated private wealth in an agrarian landed bourgeoisie made the army the one institution through which the rural poor could accumulate political power [pc-008][pc-059]. This was not a design choice but a structural consequence: families too impoverished to pay the badal, the conscription exemption fee, sent their sons into uniform, while the landed and merchant classes purchased their way out [pc-006]. The officers who emerged from this selection were overwhelmingly of rural and peasant extraction, drawn from common provincial provenance and disproportionately from religiously minoritarian communities the mandate had already positioned within rather than against the coercive apparatus [pc-007][pc-010][pc-059]. Their cohesion as a political force derived initially not from sectarian identity but from shared class position and Ba'thist ideology [pc-011]. What made ruralization decisive was the underdevelopment of the local capitalist class: the state had grown overdeveloped relative to the private economy, so that a bureau-technocratic bourgeoisie of officers and administrators could derive political weight from control of the state apparatus itself rather than from any independent economic base [pc-009]. The nationalist intelligentsia, economically powerless against the landed bourgeoisie, had ceded the field to men whose organized force could break the stalemate civilians could not [pc-008]. Between 1963 and 1968, successive purges eliminated Sunni and Druze rivals and left the rural minoritarian faction in command [pc-007]. Yet the purges operated through political, regional, and class cleavages that only retrospectively congealed into sectarian ones, as each round of elimination narrowed the circle of belonging and left communal identity as the visible residue of who remained [pc-011]. The material consequences of this capture were initially redistributive: the radical Ba'thist period narrowed rural income gaps [pc-012]. But the retreat from radicalism and liberalization after 1972 reversed those gains, with the producers' share of agricultural income collapsing from 12.8 percent in 1970 to 5.1 percent in 1975 [pc-012]. The ruralization of political power did not produce a ruralization of the economy; it produced a ruling corps whose relationship to the countryside it claimed to represent turned extractive, as the officers' transformation into a bureau-technocratic bourgeoisie severed their material interests from those of the rural poor whose sons still filled the ranks [pc-012][pc-009][pc-062]. What persisted across this transformation was the distributional template the mandate had established: belonging, not bureaucratic capacity or formal office, determined access to the state's material resources [pc-061]. What changed was which group the template favored — from communities the French had recruited as irregulars to communities that had entered the officer corps through poverty — and what remained constant was the logic that material survival and political power depended on inclusion in the network of privilege the state recognized as its own [pc-061][pc-011].

#### The Counter-Position: Fierce but Weak—Despotic Power as the Explanatory Framework

One influential alternative to the networks-of-privilege account would explain the Syrian state's trajectory through the distinction between despotic and infrastructural power. On this view, the Arab state is often violent precisely because it is weak: it excels in despotic power—arbitrary action without constraint—while lacking the infrastructural capacity to genuinely penetrate and organize society, making it 'fierce' rather than 'strong' [pc-013][pc-014]. The framework has real explanatory purchase on the Syrian trajectory. When the 2011 uprising massed, the regime's repressive strategy—fragmenting national space through checkpoints, military force, and propaganda to atomize the movement—resembled precisely the pattern a fierce-state analysis predicts: a state resorting to coercion because it lacked the capacity to relate to society through organization [pc-015]. Under conditions of mass mobilization, the networks of privilege that had structured access to the state's resources proved insufficient as a mechanism of societal control, and the state fell back on raw coercion—the one capacity it had cultivated without interruption [pc-015]. The framework also concedes a developmental limit of its own. No Arab country has been 'a glaring success story' on the developmental front, a failure that the fierce-state account registers as symptomatic of infrastructural weakness [pc-016]. Yet this developmental failure need not be read as an absence of state power; it can equally be read as evidence that the state's distributive capacity is organized through networks of privilege that prioritize elite reproduction over developmental goals [pc-016]. The infrastructural deficit the framework identifies is not a generic accident of peripheral state formation but a structural feature of a state whose capacity to distribute material resources runs through patronage organized by belonging rather than through bureaucratic penetration of society [pc-063]. The counter-position correctly registers the violence as a symptom of organizational deficit, but it cannot explain the distributive logic that determines which deficit is tolerated and whose capacity is built [pc-064].

#### Networks of Privilege as the Real Institutional Structure

The institutional structure that sustained the Syrian regime between 2000 and 2011 was not its formal bureaucracy, its legal apparatus, or even its coercive machinery considered in isolation. It was the dense, overlapping networks of public officials and private economic interests that distributed rent, managed access to opportunity, and bound society to the regime through patronage rather than administration. In Middle Eastern political economies where these networks operate, the boundary between public and private becomes so thoroughly blurred that insisting on it is "potentially misleading," meaning the state's operative institutional structure is constituted not by bureaucratic capacity but by the patronage networks that actually perform the work of governance [pc-020]. Egypt's 1990s privatization illustrates the pattern: rather than breaking elite networks, reform allowed state bureaucrats and private businessmen to entrench their monopoly power while the state retained its central role as distributor of rent, demonstrating that networks of privilege are resistant to market-oriented reform and constitute the regime's actual institutional architecture [pc-021]. That Syria's business networks have been studied within the same scholarly program that produced this framework directly ties the question of Syrian authoritarian resilience to the operations of networks of privilege [pc-022].

What this means is that economic liberalization does not eliminate rent-seeking; it reorganizes it. Privileged actors mobilize politically through networks to preserve and enhance access to politically mediated resources, shaping the very reforms that ostensibly discipline them [pc-017]. Reform is thus constitutive of new distributive coalitions, generating regulatory hybrids and compromise formulas that cut across conventional categories of state and market, public and private [pc-018]. In Syria, the retreat from Ba'thist radicalism in 1972 and the liberalization of the 1980s did not dismantle the rural-based elite's control but reorganized rent-seeking around loyalist business networks, producing the crosscutting coalitions between military officers, technocrats, and private capitalists that this framework predicts [pc-019]. The officers who had become a bureau-technocratic bourgeoisie dependent on control of the state apparatus rather than any independent economic base had by then structurally severed their material interests from the rural constituency whose sons still filled the ranks, so liberalization's reversal of rural gains expressed not a betrayal of the regime's founding logic but its fulfillment [pc-062].

The implication for assessing state power is fundamental. Infrastructural power, as Mann defines it, is the institutional capacity of a central state to penetrate its territories and logistically implement decisions [pc-023]. Assessing infrastructural power by looking for formal bureaucratic penetration will therefore miss cases where the operative mechanism of penetration is patronage rather than administration—where the state reaches society not through its own offices but through the networks it sponsors [pc-023]. The Ottoman experience in southern Syria makes the point concrete: infrastructural power was undermined not by state weakness per se but by external subsidies and material incentives that empowered tribal actors, demonstrating that what looks like state incapacity may actually be the substitution of network-based control for bureaucratic penetration [pc-024]. This substitution recurs across Syrian state formation—from the Ottoman period through the mandate's communitarian allocation of access to the coercive payroll, through the Ba'thist officers' reorganization of rent—such that the pattern is better understood as a structural feature of a state whose distributive capacity runs through patronage organized by belonging rather than as a contingent failure of administrative capacity [pc-065][pc-063].

This reframing exposes the limits of the "fierce but weak" thesis. The framework holds that Arab states excel in despotic power—arbitrary coercion free from constitutional constraint—while lacking the infrastructural capacity to genuinely penetrate and organize society, making their violence a symptom of weakness rather than strength [pc-013][pc-014]. No Arab country, by this framework's own concession, has been a "glaring success story" on the developmental front [pc-016]. But the framework treats the absence of formal infrastructural capacity as the whole story, when the evidence from the networks-of-privilege research program shows that elite networks of public officials and private interests perform the functional equivalent of infrastructural penetration—distributing rent, managing access to economic opportunity, and binding society to the regime—rendering standard infrastructural power assessments that look only for bureaucratic capacity fundamentally inadequate [pc-026]. The regime's stability during 2000–2011 derived not from despotic power compensating for infrastructural weakness but from networks of privilege that functioned as a substitute form of infrastructural penetration, organizing society through patronage rather than bureaucracy [pc-025]. The "fierce but weak" framework, while descriptively accurate about the regime's coercive posture, thus resolves no paradox, because it misidentifies the source of authoritarian resilience: the regime was not strong in coercion because it was weak in penetration; it was resilient because its penetration ran through networks rather than offices [pc-025].

The difficulty is compounded by broader critiques of Mann's framework, which has been charged with conflating ideological power with organizational infrastructure and with requiring subjective appraisal of meaning-systems that do not fit organizational materialism—critiques that further undermine the reliability of standard infrastructural power assessments for regimes like Syria's, where the operative institutional structure is informal and network-based rather than bureaucratically legible [pc-027]. The fierce-state counter-position correctly registers the regime's violence as a symptom of organizational deficit, but it cannot explain the distributive logic that determines which deficit is tolerated and whose capacity is built [pc-064]. Under the networks-of-privilege lens, the developmental failure the fierce-state framework observes is explained not by an absence of state power but by the fact that the state's distributive capacity is organized through networks that prioritize elite reproduction over developmental goals [pc-016]. The regime's repressive strategy in 2011—fragmenting national space through checkpoints, military force, and propaganda to atomize the movement—did resemble a fierce state relying on coercion because it lacked the capacity to relate to society through organization [pc-015]. But this should be read not as confirmation that networks of privilege were always structurally insufficient, but as evidence that networks of privilege, while constituting the operative institutional structure of the regime, proved insufficient as a mechanism of societal control under conditions of mass mobilization—failing precisely because the patronage circuits that had substituted for bureaucratic penetration could not manage a crisis that demanded universal rather than selective distribution [pc-015].

#### The Wartime Stress Test: Belonging as Dispossession

The civil war did not rupture the distributional logic of the Syrian state; it exposed that logic in its most elemental form. When mass mobilization emerged in 2011 from precisely those peri-urban and urban populations the state had never genuinely integrated through infrastructural capacity—populations it had controlled despotically but never organized bureaucratically—the regime's response was not to extend penetration but to weaponize the despotic core's organizational cohesion to physically eliminate opposition and transfer property to loyalists [pc-033][pc-031]. Survival in civil war, as the Syrian case demonstrates, requires controlling or neutralizing the political center and eliminating or integrating competitors, and the Assad regime tied these imperatives together into a single strategy in which destruction, displacement, and dispossession were not byproducts but instruments of regime survival [pc-029][pc-028]. The ruling elite, described as hell-bent on survival, deployed wartime dispossession and reconstruction policy to deliberately exclude large sections of the population from their homes and property rights [pc-028]. What looked like chaos was the distributional template operating without its peacetime camouflage: belonging, not right or capacity, determined who retained property and who lost it [pc-061]. The organizational cohesion that made this possible was not improvised. The regime's despotic core—Alawite officers unified by shared rural-peasant origins and Ba'thist persuasion who controlled the air squadrons, missile detachments, armored brigades, and intelligence services—could be mobilized as a sectarily-defined coercive apparatus against peri-urban and urban opposition precisely because successive purges had eliminated rival factions and Sunni officers had remained fragmented along urban-rural, class, and political lines [pc-030]. This cohesion had been built over decades through the convergence of sectarian boundaries and class-based military structures, such that when the Muslim Brotherhood rose in the 1970s-80s and again when the 2011 uprising erupted, the state lacked the infrastructural power to genuinely penetrate society but possessed a organizationally cohesive coercive apparatus defined by belonging [pc-030]. The wartime dispossession policies thus represent the culmination of a logic that had been operating since the rural-based, disproportionately minoritarian Ba'thist elite captured the state's despotic instruments and then used economic liberalization not to dismantle privilege but to reorganize rent-seeking opportunities around loyalist networks [pc-031][pc-019]. The French mandate had supplied the categorical framework—minority and majority—that made ethnic exclusion politically meaningful, while the class-based mechanisms of agrarian depression driving Alawite peasants into military service and deep Sunni class divisions provided the organizational vehicle through which an ethno-sectarian minority captured the state's coercive core [pc-032]. What the nation-state form imposed, the civil war revealed as an exclusionary power structure: institutionally weak elites favor their own communities because they lack the capacity to build genuine nationhood, and the waves of ethnic rebellion and civil conflict that followed were not deviations but the predictable products of a state that distributed material resources through patronage organized by belonging rather than through administrative capacity [pc-032][pc-063]. The regime's reliance on paramilitaries and local strongmen during the war further confirms that this was not a case of state collapse but of what Üngör terms perverse state formation—a state that actively produces strongmen and maintains over a dozen intelligence agencies and prisons alongside paramilitary organizations even while appearing weak in service provision [pc-034]. The resulting local governance architecture was fragmented and fragile precisely because the regime's punitive approach to disloyal populations and reliance on tribal and militia actors for governance legitimacy produced dispersed, contested authority across the South, Idlib, Kurdish areas, Aleppo, and Homs [pc-035]. This fragmentation was not the failure of a distributional system but its wartime expression: the state that had substituted network-based control for bureaucratic penetration now substituted militia-based coercion for territorial administration, with the same underlying logic—access to material resources and physical security determined by proximity to the networks the regime recognized as its own [pc-065][pc-025]. The officers who had transformed into a bureau-technocratic bourgeoisie whose political weight derived from control of the state apparatus rather than any independent economic base had long since severed their material interests from the rural constituency whose sons still filled the ranks [pc-062][pc-009]. Wartime dispossession thus completed a century-long arc: the communitarian allocation that the French mandate imposed—who could draw military pay, staff administrative posts, or be positioned within rather than against the apparatus of coercion—had evolved into a system in which the ruling corps could dispossess entire populations not in spite of its dependence on belonging but because of it, since the regime's survival no longer required the welfare of any constituency outside the network of privilege [pc-059][pc-062]. What changed across the century was which group the arrangement favored and how violently the exclusion was enforced; what remained constant was that material survival and political power depended on inclusion in the network the state recognized as its own.

#### Sovereignty Without Capacity: The Juridical Scaffolding of Network Rule

The survival of the Assad regime through a decade of territorial fragmentation, external intervention, and mass displacement presents a paradox only if one assumes that rule requires governance capacity. It does not, if rule is organized through networks of belonging rather than through bureaucratic penetration of society. What the regime required was not the ability to administer territory but the ability to remain the sole recognized entity entitled to distribute the material resources of sovereignty—and this it retained through a juridical scaffolding that international norms and great-power patronage maintained even as the state's empirical capabilities collapsed [pc-036][pc-037]. The distinction between negative sovereignty—the formal-legal entitlement to non-intervention—and positive sovereignty—the empirical capacity to govern—was separated by decolonization, producing quasi-states that possess the first by definition and the second only partially [pc-036][pc-037]. Syria from 2011 through 2024 fits this template precisely: the regime retained its UN seat, its diplomatic relations, and the protection of Russia and China at the Security Council, where thirteen resolutions aimed at investigating, condemning, sanctioning, or intervening against the regime were vetoed [pc-039]. It remained a single juridical sovereign even as its positive sovereignty was severely degraded by territorial fragmentation, external intervention, and factionalized elites [pc-038]. The 2018 Fragile States Index recorded the consequence—External Intervention at 10.0, State Legitimacy at 9.9, Factionalized Elites at 9.9, and Public Services at 9.3—governance capacity and state legitimacy severely deteriorated while state functions were very heavily dictated by external actors [pc-043]. What negative sovereignty protected was not a state in any infrastructural sense but a monopoly position: the regime's claim to be the sole legitimate distributor of the resources—legal validity, property titles, international aid access, reconstruction contracts—that networks of privilege required to function [pc-066]. The contrast with the PLO makes the stakes visible. The PLO developed statelike institutions, serving as the receptacle for political legitimacy and the central arena for national politics, yet because it was not juridically recognized it was deprived of the advantages of negative sovereignty that recognized states enjoyed even after losing empirical attributes of sovereignty [pc-041]. An organization that built institutions but lacked recognition could be easily abandoned by international actors [pc-040]. The Assad regime faced no such vulnerability: its recognized sovereign status insulated it from abandonment regardless of its empirical governance failures [pc-040][pc-038]. The asymmetry reveals that what matters for network rule is not capacity but entitlement—the juridically guaranteed position of being the actor the international system treats as the state [pc-066]. The regime's use of this position to enforce its monopoly on material access is visible in the micro-structure of property and legal documentation during the war. Local councils in opposition-held areas established their own land and property registries; the Free Syrian Lawyers Association operated offices registering contracts in Idlib [pc-042]. These were functional substitutes for state administration—the kind of institutional capacity that standard analyses equate with sovereignty. But the regime's Legislative Decree 11 of 2016 declared all property registrations in areas outside regime control null and void [pc-042]. The decree could not be enforced in territory the regime did not control, yet it retained juridical force because the regime retained negative sovereignty: its acts remained the acts of a recognized state, while the opposition's records were the acts of non-sovereign actors. This is the mechanism by which juridical scaffolding preserved network rule—the opposition could administer territory but could not make its administration legally durable, while the regime could not administer territory but could make its legal acts binding. In a system where material survival depends on inclusion in the network of privilege the state recognizes as its own, the capacity to invalidate alternative legal records is the capacity to ensure that inclusion runs through the regime's networks alone [pc-067]. External patrons sustained this arrangement not as a byproduct of indifference but through active geopolitical investment. Where external patron powers have geopolitical interests, their interference substantially hinders long-term state stability, because domestic leaders are caught between meeting the demands of citizens and foreign backers, causing governance capacity and state stability to take a back seat [pc-044]. The Security Council vetoes were the international expression of this dynamic: Russia and China maintained the regime's negative sovereignty not to enable governance but to preserve a client whose value lay in geopolitical alignment, not in administrative competence [pc-039][pc-044]. The result is that the state's infrastructural deficit—the absence of bureaucratic capacity to genuinely penetrate and organize society—was not a gap waiting to be filled but a structural feature of a political order in which the distribution of material resources runs through patronage organized by belonging rather than through administrative capacity [pc-063][pc-065]. The regime's perverse state formation—commanding over a dozen intelligence agencies and prisons alongside paramilitary organizations even while appearing weak in service provision—confirms that capacity was built selectively, where it served the networks of privilege, and left unbuilt where it did not [pc-034]. Negative sovereignty insulated this selectivity from external challenge: no international actor could legally displace the regime's claim to rule, and no domestic alternative could acquire the juridical standing to make its governance enforceable beyond the territory it held by force. What remained constant across the century—from the French mandate's communitarian allocation of access to the coercive payroll [pc-059][pc-061], through the rural officer corps's capture of the state's despotic instruments [pc-006][pc-010], to the wartime regime's invalidation of opposition property records—was that material survival and political power depended on inclusion in the network of privilege the state recognized as its own. What changed was which group the arrangement favored. The juridical scaffolding of negative sovereignty ensured that the question of who counted as the state was settled internationally, not empirically, and that the answer determined whose networks of belonging would be the only ones with legal force [pc-067].

#### Synthesis: Belonging, Not Office, as the Constant of Syrian Political Economy

Across a century of Syrian state formation, the distribution of belonging—not formal office or bureaucratic capacity—determined who could access the material resources of the state. The French mandate established this distributional template by allocating access to military pay, administrative posts, and the apparatus of coercion along communal lines, while simultaneously producing the very minority/majority categories that would naturalize the resulting distribution [pc-059][pc-061]. The suppression of the Great Revolt of 1925-7 laid bare the material stakes: communities recruited into irregular paramilitary formations gained entry to the state's coercive payroll, while the cross-communal and cross-class coalition that resisted bore the cost of an arrangement that allocated opportunity by communal category rather than by claim of right [pc-060]. This was not a communitarian overlay on an otherwise functional administrative system; it was the constitutive mechanism through which the state distributed material resources, and it established a template whose beneficiaries would change across the century but whose logic would persist [pc-061].

The post-independence state did not dismantle this template; it transferred it to new beneficiaries through class-based mechanisms. Rural peasants from minoritarian communities, driven into military service by economic deprivation that made the conscription exemption fee unaffordable, captured the coercive apparatus while their Sunni counterparts remained fragmented along class, regional, and political lines [pc-006][pc-007]. Their transformation into a bureau-technocratic bourgeoisie—whose political weight derived from control of the state apparatus rather than from any independent economic base—structurally severed their material interests from the rural constituency whose sons still filled the ranks [pc-009][pc-062]. The reversal of rural gains under post-1972 liberalization, when the producers' share of agricultural income fell from 12.8 percent to 5.1 percent, was therefore not a betrayal of the regime's founding logic but a predictable expression of it: the ruling corps had ceased to depend on the welfare of the countryside it claimed to represent [pc-012][pc-062]. The officers who captured the state's coercive instruments had become a class whose economic base was the state itself, and whose material interest lay in preserving the distribitional mechanism that had brought them to power rather than in broadening it.

Economic liberalization reorganized rather than eliminated rent-seeking, generating crosscutting coalitions between military officers, technocrats, and private capitalists that operated through the ethno-sectarian boundaries the mandate had institutionalized and the class-based military structures that had carried the Ba'thists to power [pc-017][pc-019][pc-031]. The regime's wartime dispossession policies represent the culmination of this logic—using the despotic core's organizational cohesion to physically eliminate peri-urban opposition and transfer property to regime loyalists, so that reconstruction itself became an instrument of redistribution toward the network of belonging [pc-028][pc-031]. What persisted across each reorganization was the underlying mechanism: the state's capacity to distribute material resources ran through patronage organized by belonging rather than through administrative capacity [pc-063][pc-065]. This was not an isolated episode of reform producing unintended consequences but a recurring pattern across Syrian state formation, in which what appears as infrastructural deficit is the structural form of a state that distributes through patronage rather than through bureaucracy [pc-065].

This distributional logic reframes the debate over whether Syria was a fierce state compensating for infrastructural weakness or a regime governed by networks of privilege. The infrastructural deficit the fierce-state framework identifies is not a generic accident of peripheral state formation but a structural feature of a state whose distributive mechanism is patronage organized by belonging [pc-063]. The violence the fierce-state framework registers as a symptom of weakness is better understood as the coercive face of a distributive system that allocates material resources by inclusion or exclusion from networks of belonging [pc-064]. Networks of privilege did not compensate for an absence of state capacity; they constituted the state's operative institutional structure, performing the functional equivalent of infrastructural penetration by distributing rent, managing access to economic opportunity, and binding society to the regime through clientelistic loyalty rather than bureaucratic administration [pc-025][pc-026]. The regime's repressive strategy in 2011—fragmenting national space through checkpoints and military force to atomize the movement—resembled the fierce state's reliance on coercion precisely because it lacked the capacity to relate to society through organization, which is consistent with the view that networks of privilege, while structurally real, proved insufficient as a mechanism of societal control under conditions of mass mobilization [pc-015].

The international dimension of this system is not incidental but structural. Jackson's separation of negative from positive sovereignty is the condition that makes network rule viable: when international recognition insulates a regime from intervention, it can substitute patronage networks for bureaucratic capacity without losing its claim to rule, because the juridical shield prevents alternative institutional structures from acquiring the sovereign legitimacy needed to challenge the network's monopoly on distributing material resources [pc-066]. Fragmented Syria from 2011 to 2024 is best understood as one juridical sovereign under stress rather than several empirical polities—the Assad regime retained its UN seat, diplomatic recognition, and great-power protection even as its empirical governance capacity collapsed and the conflict transformed from uprising to civil war to interstate war with the intervention of Turkey, Iran, Russia, the United States, and Hezbollah [pc-047][pc-038][pc-051]. The juridical scaffolding preserved the regime's monopoly as the sole legitimate distributor of material resources, so that even functional opposition governance—property registries, contract registration by the Free Syrian Lawyers Association—could be juridically erased by Legislative Decree 11 of 2016, a decree unenforceable on the ground but decisive in law [pc-067][pc-042]. The breakaway entities never consolidated the independent, self-sustaining de facto statehood that would qualify them as unrecognized states under the standard criteria, because their heavy dependence on external patrons—the United States for the SDF, Turkey for opposition groups—undermined the de facto independence requirement, and the AANES pursued autonomy within Syria rather than full secession [pc-052][pc-056][pc-057]. Caspersen's distinction between unrecognized states and states-within-states further clarifies the asymmetry: entities that maintain high independence but recognize the central government and operate with its tacit approval face no external threat to their de facto existence, whereas Syria's breakaway entities possessed neither recognition nor the central government's acquiescence [pc-053]. The PLO case demonstrates the vulnerability this produces: the PLO built statelike institutions but, lacking juridical recognition, was deprived of negative sovereignty protections and could be easily abandoned by international actors—precisely the vulnerability the Assad regime avoided by retaining its recognized sovereign status regardless of its empirical governance failures [pc-040][pc-041].

This century-long trajectory confirms, with striking precision, the prediction that exclusionary nation-state power structures violate the principle of self-rule and trigger ethnic rebellion and outside intervention [pc-045][pc-058]. The nation-state form the French mandate imposed created the categorical framework that made ethnic exclusion politically meaningful, while the class-based mechanisms of agrarian mobility provided the organizational vehicle through which an ethno-sectarian minority could capture the state's despotic core [pc-032]. Successive waves of rebellion—the Muslim Brotherhood uprising, the 2011 revolution—followed as the framework anticipates [pc-045]. Yet treating this trajectory as a near-automatic consequence of nation-state formation, as Wimmer's structuralist thesis implies, overstates its inevitability [pc-046]. The position adopted here—that French minority institutionalization, class-based agrarian mobility, and exclusionary power structures converge to explain Syria's despotic core—risks reproducing the very anachronism the mandate evidence warns against: the officers who captured the state did not initially act as Alawis but as rural peasants and Ba'thists, and the sectarianization of state power was an emergent product of successive purges and political crystallizations rather than a pre-planned ethno-nationalist strategy [pc-046][pc-011]. The organizational cohesion of the despotic core was as much a product of unintended class dynamics and military institutional accidents as of deliberate ethno-sectarian boundary-making [pc-046].

More fundamentally, the networks-of-privilege framework struggles to explain the regime's near-collapse in 2011. If networks of privilege constituted a robust institutional structure that functionally substituted for infrastructural power, the scale and speed of the uprising's spread across Syria suggests these networks either did not penetrate society as deeply as the framework implies, or that they generated grievances among excluded populations that outweighed their stabilizing effects—an outcome the framework does not adequately predict [pc-048]. Post-2011 evidence from Daraa shows that even after military reconquest the regime could not reinstate a monopoly over local governance and operated through tacit delegation to armed factions and tribal committees, suggesting that the regime's infrastructural reach was always thinner than either the fierce-but-weak or the networks-of-privilege framework fully captures [pc-049]. The regime's reliance on paramilitaries and informal parastatal networks rather than regular state institutions—thriving not in genuine state weakness but in a perverse state formation that actively produces strongmen while maintaining strong coercive capacities—reinforces this assessment [pc-034][pc-035]. The hollowness of negative sovereignty compounds the problem: with Syria's External Intervention score at 10.0, the juridical sovereign was increasingly a legal fiction sustained by Russian and Iranian patronage rather than a meaningful independent actor, and if external patrons withdrew, the juridical shell might collapse faster than the Jacksonian framework predicts, because the regime's negative sovereignty was maintained not by international norms alone but by active great-power intervention [pc-050][pc-043][pc-044].

What changed across the century was which group the arrangement favored and what idiom of belonging it invoked: communal category under the mandate, class and party under early Ba'thism, sectarian network under liberalized patronage. What remained constant was that material survival and political power depended on inclusion in the network of privilege the state recognized as its own [pc-068]. The French distributed access by communal category; the Ba'thist officers distributed it by class origin and party loyalty that crystallized into sectarian networks; the liberalized regime distributed it through crosscutting patronage coalitions that blurred the boundary between public and private so thoroughly that establishing one was potentially misleading [pc-020]. The distributive mechanism was belonging in each case, not office, and the state's institutional structure was constituted by the network rather than by the bureaucracy it nominally contained [pc-068].

#### Confidence and coverage

**Overall confidence:** low (band shown with the coverage counts that justify it).

overall confidence is 'low', bounded by the least-covered name the paper cites ('Business Networks in Syria: The Political Economy of Authoritarian Resilience', band 'thin'); coverage by name: Business Networks in Syria: The Political Economy of Authoritarian Resilience (thin: 1 corpus notes, 1 cited claims); French Mandate (moderate: 55 corpus notes, 13 cited claims); French Mandate Syria (thin: 19 corpus notes, 14 cited claims); Hanna Batatu (moderate: 29 corpus notes, 9 cited claims); Idlib (moderate: 30 corpus notes, 22 cited claims); Infrastructural power (moderate: 51 corpus notes, 17 cited claims); Rojava (thin: 4 corpus notes, 2 cited claims); Steven Heydemann (moderate: 45 corpus notes, 17 cited claims); Syria (dense: 962 corpus notes, 51 cited claims); Syria's Peasantry, the Descendants of Its Lesser Rural Notables, and Their Politics (thin: 5 corpus notes, 7 cited claims); Syrian regime (thin: 11 corpus notes, 3 cited claims); Waves of War (thin: 3 corpus notes, 4 cited claims); de facto independence (thin: 6 corpus notes, 5 cited claims); despotic power (moderate: 27 corpus notes, 14 cited claims); fierce state (thin: 1 corpus notes, 13 cited claims); minorities (thin: 12 corpus notes, 8 cited claims); negative sovereignty (moderate: 47 corpus notes, 9 cited claims); networks of privilege (thin: 2 corpus notes, 7 cited claims)

| name | corpus notes | cited claims | coverage |
|---|---:|---:|---|
| Business Networks in Syria: The Political Economy of Authoritarian Resilience | 1 | 1 | thin |
| French Mandate | 55 | 13 | moderate |
| French Mandate Syria | 19 | 14 | thin |
| Hanna Batatu | 29 | 9 | moderate |
| Idlib | 30 | 22 | moderate |
| Infrastructural power | 51 | 17 | moderate |
| Rojava | 4 | 2 | thin |
| Steven Heydemann | 45 | 17 | moderate |
| Syria | 962 | 51 | dense |
| Syria's Peasantry, the Descendants of Its Lesser Rural Notables, and Their Politics | 5 | 7 | thin |
| Syrian regime | 11 | 3 | thin |
| Waves of War | 3 | 4 | thin |
| de facto independence | 6 | 5 | thin |
| despotic power | 27 | 14 | moderate |
| fierce state | 1 | 13 | thin |
| minorities | 12 | 8 | thin |
| negative sovereignty | 47 | 9 | moderate |
| networks of privilege | 2 | 7 | thin |

#### Shape check

**Band:** strong.

#### Citations

| id | kind | confidence | grounds | source |
|---|---|---|---|---|
| pc-001 | a (carried) | low | white-2011-5f35a47d9657_11_introduction_001 | White, Benjamin Thomas. (2011) |
| pc-002 | a (carried) | low | white-2011-5f35a47d9657_11_introduction_002 | White, Benjamin Thomas. (2011) |
| pc-003 | a (carried) | low | white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001 | White, Benjamin Thomas. (2011) |
| pc-004 | a (carried) | low | white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001 | White, Benjamin Thomas. (2011) |
| pc-005 | b (carried) | low | white-2011-5f35a47d9657_21_the-emergence-of-minorities_001, batatu-1999-598624067df3_48_section_001, vignal-2021-c7005c2bf8ef_107_conclusion_001 | Hanna Batatu (1999); Leila Vignal ; (2021); White, Benjamin Thomas. (2011) |
| pc-006 | a (carried) | medium | batatu-1999-598624067df3_48_section_001 | Hanna Batatu (1999) |
| pc-007 | a (carried) | medium | batatu-1999-598624067df3_48_section_001 | Hanna Batatu (1999) |
| pc-008 | a (carried) | medium | ayubi-1995-16fd6a2e503f_41_a-colonial-mode-of-production_004 | Ayubi, Nazih N.; (1995) |
| pc-009 | a (carried) | medium | ayubi-1995-16fd6a2e503f_66_a-closer-look-at-social-classes_002 | Ayubi, Nazih N.; (1995) |
| pc-010 | a (carried) | high | ayubi-1995-16fd6a2e503f_118_syria_002 | Ayubi, Nazih N.; (1995) |
| pc-011 | b (carried) | medium | batatu-1999-598624067df3_48_section_001, ayubi-1995-16fd6a2e503f_118_syria_002 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999) |
| pc-012 | a (carried) | low | batatu-1999-598624067df3_20_the-d-istribution-of-a-gricultural-i-ncome-prior-to-and-since-the-r_005 | Hanna Batatu (1999) |
| pc-013 | a (carried) | medium | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003 | Ayubi, Nazih N.; (1995) |
| pc-014 | a (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003 | Ayubi, Nazih N.; (1995) |
| pc-015 | b (carried) | low | vignal-2021-c7005c2bf8ef_30_fragmenting-space-and-society-to-suppress-the-revolution_001, ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003 | Ayubi, Nazih N.; (1995); Leila Vignal ; (2021) |
| pc-016 | b (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001 | Ayubi, Nazih N.; (1995); Steven Heydemann (2004) |
| pc-017 | a (carried) | medium | heydemann-2004-72a4a9a9b3b0_11_6-steven-heydemann_001 | Steven Heydemann (2004) |
| pc-018 | a (carried) | medium | heydemann-2004-72a4a9a9b3b0_16_12-steven-heydemann_001 | Steven Heydemann (2004) |
| pc-019 | b (carried) | low | heydemann-2004-72a4a9a9b3b0_127_conclusion-fiscal-reforms-and-historical-trajectories_001, batatu-1999-598624067df3_20_the-d-istribution-of-a-gricultural-i-ncome-prior-to-and-since-the-r_005, heydemann-2004-72a4a9a9b3b0_16_12-steven-heydemann_001, ayubi-1995-16fd6a2e503f_118_syria_002 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Steven Heydemann (2004) |
| pc-020 | a (carried) | low | heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001 | Steven Heydemann (2004) |
| pc-021 | a (carried) | low | heydemann-2004-72a4a9a9b3b0_58_conclusion_001 | Steven Heydemann (2004) |
| pc-022 | a (carried) | low | bayat-2017-ce6bb0643cfb_101_joel-beinin-editor_001 | Asef Bayat (2017) |
| pc-023 | a (carried) | medium | hall-2006-449559bfe4dc_68_infrastructural-power-and-globalization_001 | John A. Hall and Ralph Schroeder (2006) |
| pc-024 | a (carried) | medium | heydemann-2000-66701ffbb36c_38_conclusion_001 | Steven Heydemann (2000) |
| pc-025 | c (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001, hall-2006-449559bfe4dc_68_infrastructural-power-and-globalization_001 | Ayubi, Nazih N.; (1995); John A. Hall and Ralph Schroeder (2006); Steven Heydemann (2004) |
| pc-026 | b (carried) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001 | Ayubi, Nazih N.; (1995); Steven Heydemann (2004) |
| pc-027 | b (carried) | medium | hall-2006-449559bfe4dc_111_frank-trentmann_009, hall-2006-449559bfe4dc_48_performance-on-the-hazards-of-analytical-tacking_001 | John A. Hall and Ralph Schroeder (2006) |
| pc-028 | a (carried) | medium | vignal-2021-c7005c2bf8ef_107_conclusion_001 | Leila Vignal ; (2021) |
| pc-029 | a (carried) | medium | vignal-2021-c7005c2bf8ef_12_argument-of-the-book_001 | Leila Vignal ; (2021) |
| pc-030 | b (carried) | medium | batatu-1999-598624067df3_48_section_001, ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, vignal-2021-c7005c2bf8ef_107_conclusion_001, vignal-2021-c7005c2bf8ef_12_argument-of-the-book_001 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Leila Vignal ; (2021) |
| pc-031 | b (carried) | medium | heydemann-2004-72a4a9a9b3b0_11_6-steven-heydemann_001, heydemann-2004-72a4a9a9b3b0_16_12-steven-heydemann_001, batatu-1999-598624067df3_48_section_001, ayubi-1995-16fd6a2e503f_118_syria_002, vignal-2021-c7005c2bf8ef_107_conclusion_001, ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Leila Vignal ; (2021); Steven Heydemann (2004) |
| pc-032 | b (carried) | low | white-2011-5f35a47d9657_11_introduction_001, white-2011-5f35a47d9657_11_introduction_002, batatu-1999-598624067df3_48_section_001, wimmer-2013-a67941b77943_1_waves-of-war_001 | Hanna Batatu (1999); White, Benjamin Thomas. (2011); Wimmer, Andreas (2013) |
| pc-033 | b (carried) | medium | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_11_6-steven-heydemann_001, ayubi-1995-16fd6a2e503f_118_syria_002, vignal-2021-c7005c2bf8ef_107_conclusion_001 | Ayubi, Nazih N.; (1995); Leila Vignal ; (2021); Steven Heydemann (2004) |
| pc-034 | a (carried) | high | ungor-2020-ae5701dcc706_36_dual-state-deep-state-hybrid-state-parastate_002, ungor-2020-ae5701dcc706_10_4-paramilitarism_001 | Uğur Ümit Üngör (2020) |
| pc-035 | a (carried) | medium | kao-2025-ab19e646ab7d_59_6-the-architecture-of-local-governance_001 | Kristen Kao (Editor) (2025) |
| pc-036 | a (carried) | medium | jackson-1990-7eb3f39a639f_12_introduction_001, jackson-1990-7eb3f39a639f_12_introduction_004 | Robert H. Jackson (1990) |
| pc-037 | a (carried) | medium | jackson-1990-7eb3f39a639f_12_introduction_007 | Robert H. Jackson (1990) |
| pc-038 | b (carried) | medium | jackson-1990-7eb3f39a639f_12_introduction_001, kandiah-2018-454c87b22e16_14_approaching-the-syrian-conflict-legitimacy-and-geopolitics-in-a-contested_001, kandiah-2018-454c87b22e16_20_interference-of-geopolitical-considerations-in-mediation-attempts_001 | Lavan Kandiah (2018); Robert H. Jackson (1990) |
| pc-039 | a (carried) | medium | kandiah-2018-454c87b22e16_20_interference-of-geopolitical-considerations-in-mediation-attempts_001 | Lavan Kandiah (2018) |
| pc-040 | b (carried) | medium | heydemann-2000-66701ffbb36c_110_summary-and-conclusions-the-palestinians-beyond-war_001, jackson-1990-7eb3f39a639f_12_introduction_001, kandiah-2018-454c87b22e16_20_interference-of-geopolitical-considerations-in-mediation-attempts_001 | Lavan Kandiah (2018); Robert H. Jackson (1990); Steven Heydemann (2000) |
| pc-041 | a (carried) | medium | heydemann-2000-66701ffbb36c_110_summary-and-conclusions-the-palestinians-beyond-war_001 | Steven Heydemann (2000) |
| pc-042 | a (carried) | medium | vignal-2021-c7005c2bf8ef_100_the-loss-of-property-titles_001 | Leila Vignal ; (2021) |
| pc-043 | a (carried) | high | kandiah-2018-454c87b22e16_14_approaching-the-syrian-conflict-legitimacy-and-geopolitics-in-a-contested_001 | Lavan Kandiah (2018) |
| pc-044 | a (carried) | high | kandiah-2018-454c87b22e16_13_the-influence-of-international-geopolitical-forces-on-domestic-state-legitimacy_003 | Lavan Kandiah (2018) |
| pc-045 | b (carried) | low | wimmer-2013-a67941b77943_1_waves-of-war_001, white-2011-5f35a47d9657_11_introduction_001, batatu-1999-598624067df3_48_section_001, ayubi-1995-16fd6a2e503f_118_syria_002, heydemann-2004-72a4a9a9b3b0_11_6-steven-heydemann_001 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Steven Heydemann (2004); White, Benjamin Thomas. (2011); Wimmer, Andreas (2013) |
| pc-046 | c (carried) | low | white-2011-5f35a47d9657_11_introduction_001, batatu-1999-598624067df3_48_section_001, wimmer-2013-a67941b77943_1_waves-of-war_001 | Hanna Batatu (1999); White, Benjamin Thomas. (2011); Wimmer, Andreas (2013) |
| pc-047 | c (carried) | low | jackson-1990-7eb3f39a639f_12_introduction_001, caspersen-2012-fbc0efe4fffc_13_insurgent-states-black-spots-states-within-states_001, vignal-2021-c7005c2bf8ef_100_the-loss-of-property-titles_001, kandiah-2018-454c87b22e16_20_interference-of-geopolitical-considerations-in-mediation-attempts_001, vignal-2021-c7005c2bf8ef_102_wartime-reconstruction_001 | Caspersen, Nina (2012); Lavan Kandiah (2018); Leila Vignal ; (2021); Robert H. Jackson (1990) |
| pc-048 | c (carried) | low | vignal-2021-c7005c2bf8ef_30_fragmenting-space-and-society-to-suppress-the-revolution_001, vignal-2021-c7005c2bf8ef_22_the-shabab-revolution_001 | Leila Vignal ; (2021) |
| pc-049 | b (carried) | low | kao-2025-ab19e646ab7d_54_1-introduction_001, kao-2025-ab19e646ab7d_58_5-local-governance-and-the-return-of-the-regime-mid-2018-to-the-present_002 | Kristen Kao (Editor) (2025) |
| pc-050 | c (carried) | low | kandiah-2018-454c87b22e16_14_approaching-the-syrian-conflict-legitimacy-and-geopolitics-in-a-contested_001, vignal-2021-c7005c2bf8ef_100_the-loss-of-property-titles_001, ungor-2020-ae5701dcc706_36_dual-state-deep-state-hybrid-state-parastate_002, kao-2025-ab19e646ab7d_59_6-the-architecture-of-local-governance_001, vignal-2021-c7005c2bf8ef_114_2-borders-and-the-fragmentation-of-the-nation-state_001 | Kristen Kao (Editor) (2025); Lavan Kandiah (2018); Leila Vignal ; (2021); Uğur Ümit Üngör (2020) |
| pc-051 | a (carried) | high | malesevic-2026-4faeb528594d_10_forging-statehood-through-inter-and-intra-state-wars_001 | Siniša Malešević (2026) |
| pc-052 | a (carried) | low | caspersen-2012-fbc0efe4fffc_13_insurgent-states-black-spots-states-within-states_001 | Caspersen, Nina (2012) |
| pc-053 | a (carried) | low | caspersen-2012-fbc0efe4fffc_13_insurgent-states-black-spots-states-within-states_001 | Caspersen, Nina (2012) |
| pc-056 | b (carried) | low | caspersen-2012-fbc0efe4fffc_13_insurgent-states-black-spots-states-within-states_001, vignal-2021-c7005c2bf8ef_114_2-borders-and-the-fragmentation-of-the-nation-state_001, kandiah-2018-454c87b22e16_13_the-influence-of-international-geopolitical-forces-on-domestic-state-legitimacy_003 | Caspersen, Nina (2012); Lavan Kandiah (2018); Leila Vignal ; (2021) |
| pc-057 | b (carried) | low | jackson-1990-7eb3f39a639f_12_introduction_001, caspersen-2012-fbc0efe4fffc_13_insurgent-states-black-spots-states-within-states_001, kandiah-2018-454c87b22e16_20_interference-of-geopolitical-considerations-in-mediation-attempts_001 | Caspersen, Nina (2012); Lavan Kandiah (2018); Robert H. Jackson (1990) |
| pc-058 | a (carried) | low | wimmer-2013-a67941b77943_1_waves-of-war_001 | Wimmer, Andreas (2013) |
| pc-059 | c (this paper's verdict) | low | white-2011-5f35a47d9657_11_introduction_001, white-2011-5f35a47d9657_11_introduction_002, white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001 | White, Benjamin Thomas. (2011) |
| pc-060 | c (this paper's verdict) | low | white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001 | White, Benjamin Thomas. (2011) |
| pc-061 | c (this paper's verdict) | low | white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001, white-2011-5f35a47d9657_21_the-emergence-of-minorities_001, batatu-1999-598624067df3_48_section_001, vignal-2021-c7005c2bf8ef_107_conclusion_001 | Hanna Batatu (1999); Leila Vignal ; (2021); White, Benjamin Thomas. (2011) |
| pc-062 | c (this paper's verdict) | low | ayubi-1995-16fd6a2e503f_66_a-closer-look-at-social-classes_002, batatu-1999-598624067df3_20_the-d-istribution-of-a-gricultural-i-ncome-prior-to-and-since-the-r_005, ayubi-1995-16fd6a2e503f_118_syria_002 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999) |
| pc-063 | b (this paper's inference) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001, white-2011-5f35a47d9657_21_the-emergence-of-minorities_001, batatu-1999-598624067df3_48_section_001, vignal-2021-c7005c2bf8ef_107_conclusion_001 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Leila Vignal ; (2021); White, Benjamin Thomas. (2011) |
| pc-064 | c (this paper's verdict) | low | ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001, heydemann-2004-72a4a9a9b3b0_58_conclusion_001, ayubi-1995-16fd6a2e503f_66_a-closer-look-at-social-classes_002, batatu-1999-598624067df3_20_the-d-istribution-of-a-gricultural-i-ncome-prior-to-and-since-the-r_005, ayubi-1995-16fd6a2e503f_118_syria_002 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Steven Heydemann (2004) |
| pc-065 | b (this paper's inference) | low | heydemann-2000-66701ffbb36c_38_conclusion_001, heydemann-2004-72a4a9a9b3b0_127_conclusion-fiscal-reforms-and-historical-trajectories_001, batatu-1999-598624067df3_20_the-d-istribution-of-a-gricultural-i-ncome-prior-to-and-since-the-r_005, heydemann-2004-72a4a9a9b3b0_16_12-steven-heydemann_001, ayubi-1995-16fd6a2e503f_118_syria_002 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Steven Heydemann (2000); Steven Heydemann (2004) |
| pc-066 | b (this paper's inference) | low | jackson-1990-7eb3f39a639f_12_introduction_001, jackson-1990-7eb3f39a639f_12_introduction_004, jackson-1990-7eb3f39a639f_12_introduction_007, heydemann-2000-66701ffbb36c_110_summary-and-conclusions-the-palestinians-beyond-war_001, kandiah-2018-454c87b22e16_20_interference-of-geopolitical-considerations-in-mediation-attempts_001, ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001, white-2011-5f35a47d9657_21_the-emergence-of-minorities_001, batatu-1999-598624067df3_48_section_001, vignal-2021-c7005c2bf8ef_107_conclusion_001 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Lavan Kandiah (2018); Leila Vignal ; (2021); Robert H. Jackson (1990); Steven Heydemann (2000); White, Benjamin Thomas. (2011) |
| pc-067 | c (this paper's verdict) | low | jackson-1990-7eb3f39a639f_12_introduction_001, kandiah-2018-454c87b22e16_14_approaching-the-syrian-conflict-legitimacy-and-geopolitics-in-a-contested_001, kandiah-2018-454c87b22e16_20_interference-of-geopolitical-considerations-in-mediation-attempts_001, vignal-2021-c7005c2bf8ef_100_the-loss-of-property-titles_001, heydemann-2000-66701ffbb36c_38_conclusion_001, heydemann-2004-72a4a9a9b3b0_127_conclusion-fiscal-reforms-and-historical-trajectories_001, batatu-1999-598624067df3_20_the-d-istribution-of-a-gricultural-i-ncome-prior-to-and-since-the-r_005, heydemann-2004-72a4a9a9b3b0_16_12-steven-heydemann_001, ayubi-1995-16fd6a2e503f_118_syria_002 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Lavan Kandiah (2018); Leila Vignal ; (2021); Robert H. Jackson (1990); Steven Heydemann (2000); Steven Heydemann (2004) |
| pc-068 | c (this paper's verdict) | low | white-2011-5f35a47d9657_26_divide-and-rule-but-on-what-grounds_001, white-2011-5f35a47d9657_21_the-emergence-of-minorities_001, batatu-1999-598624067df3_48_section_001, vignal-2021-c7005c2bf8ef_107_conclusion_001, heydemann-2004-72a4a9a9b3b0_11_6-steven-heydemann_001, heydemann-2004-72a4a9a9b3b0_16_12-steven-heydemann_001, ayubi-1995-16fd6a2e503f_118_syria_002, ayubi-1995-16fd6a2e503f_146_conclusion-the-strong-the-hard-and-the-fierce_003, ayubi-1995-16fd6a2e503f_66_a-closer-look-at-social-classes_002, batatu-1999-598624067df3_20_the-d-istribution-of-a-gricultural-i-ncome-prior-to-and-since-the-r_005, heydemann-2000-66701ffbb36c_38_conclusion_001, heydemann-2004-72a4a9a9b3b0_127_conclusion-fiscal-reforms-and-historical-trajectories_001, heydemann-2004-72a4a9a9b3b0_144_the-genesis-of-a-network-the-rise-of-postindependence-private-elites-in-morocco_001 | Ayubi, Nazih N.; (1995); Hanna Batatu (1999); Leila Vignal ; (2021); Steven Heydemann (2000); Steven Heydemann (2004); White, Benjamin Thomas. (2011) |

#### Bibliography

- **kao-2025-ab19e646ab7d** — author: Kristen Kao (Editor) (from embedded metadata); title: Decentralization, Local Governance, and Inequality in the Middle East and North Africa (from embedded metadata); date: 2025 (from title page); publisher: University of Michigan Press (from open_library)
- **vignal-2021-c7005c2bf8ef** — author: Leila Vignal ; (from embedded metadata); title: War-Torn (from embedded metadata); date: 2021 (from title page); publisher: C. Hurst and Company (Publishers) Limited (from open_library)
- **ayubi-1995-16fd6a2e503f** — author: Ayubi, Nazih N.; (from embedded metadata); title: Over-stating the Arab State (from open_library); date: 1995 (from title page); publisher: I. B. Tauris (from open_library)
- **batatu-1999-598624067df3** — author: Hanna Batatu (from title page); title: Syria’s Peasantry, the Descendants of Its Lesser Rural Notables, and Their Politics (from title page); date: 1999 (from title page); publisher: Princeton University Press (from open_library)
- **bayat-2017-ce6bb0643cfb** — author: Asef Bayat (from embedded metadata); title: Revolution Without Revolutionaries (from embedded metadata); date: 2017 (from title page); publisher: Stanford University Press (from open_library)
- **caspersen-2012-fbc0efe4fffc** — author: Caspersen, Nina (from embedded metadata); title: Unrecognized States (from embedded metadata); date: 2012 (from title page); publisher: [unavailable - a read was attempted and found nothing]
- **hall-2006-449559bfe4dc** — author: John A. Hall and Ralph Schroeder (from title page); title: An anatomy of power : the social theory of Michael Mann (from embedded metadata); date: 2006 (from title page); publisher: Cambridge University Press (from open_library)
- **heydemann-2004-72a4a9a9b3b0** — author: Steven Heydemann (from embedded metadata); title: Networks of Privilege in the Middle East (from embedded metadata); date: 2004 (from title page); publisher: Palgrave Macmillan (from open_library)
- **heydemann-2000-66701ffbb36c** — author: Steven Heydemann (from title page); title: War, Institutions, and Social Change in the Middle East (from title page); date: 2000 (from title page); publisher: University of California Press (from title page)
- **jackson-1990-7eb3f39a639f** — author: Robert H. Jackson (from title page); title: Quasi-states: sovereignty, international relations, and the third world (from title page); date: 1990 (from title page); publisher: Cambridge University Press (from open_library)
- **kandiah-2018-454c87b22e16** — author: Lavan Kandiah (from embedded metadata); title: EXAMINING THE CENTRALITY OF STATE LEGITIMACY AND CAPACITY TO STABLE GOVERNANCE IN THE SYRIAN CONFLICT: THE DETRIMENTAL EFFECTS OF INTERNATIONAL GEOPOLITICAL INFLUENCES ON LONG-TERM STATE STABILITY (from title page); date: 2018 (from title page); publisher: [unavailable - a read was attempted and found nothing]
- **malesevic-2026-4faeb528594d** — author: Siniša Malešević (from title page); title: Do civil wars make or break states? Towards a historical sociology of intra-state conflicts (from title page); date: 2026 (from title page); publisher: Springer Science and Business Media LLC (from crossref)
- **white-2011-5f35a47d9657** — author: White, Benjamin Thomas. (from embedded metadata); title: Emergence of Minorities in the Middle East (from embedded metadata); date: 2011 (from title page); publisher: Edinburgh University Press (from open_library)
- **wimmer-2013-a67941b77943** — author: Wimmer, Andreas (from embedded metadata); title: Waves of War (from embedded metadata); date: 2013 (from title page); publisher: Cambridge University Press (from open_library)
- **ungor-2020-ae5701dcc706** — author: Uğur Ümit Üngör (from title page); title: Paramilitarism: Mass Violence in the Shadow of the State (from title page); date: 2020 (from title page); publisher: Oxford University Press (from open_library)

---


## Appendix F — The other papers, listed rather than reproduced

Appendices D and E carry two papers in full because a reader has to see at least one end to end. Reproducing every paper would treble this document, so the rest are indexed here: what each was asked, what it argued, and what it cost. Each renders to `data/papers/<id>.md`, with the record that produced it beside it.

All 6 were drafted on corpus pin `sim-2026-07-30`, the same pin as the two papers above, so the whole set is comparable. Each stands on one prior analysis record, where the papers in D and E stand on two and three.

| Paper | The case it was asked about | Lens | Claims | Books cited | Confidence | Shape | Cost |
|---|---|---|---:|---:|---|---|---:|
| Extraction Bargains Make Nations, Rent Breaks Them | Comparative: nationalism and nation-state formation, nineteenth and twentieth centuries | political-economy | 15 | 8 | low | strong | $0.0081 |
| War, Extraction, and the Rent Rupture | Comparative: European nation-state formation, 1760-1914 | state-formation | 15 | 10 | low | strong | $0.0077 |
| Material Contests Over Juridical Arrangements | Comparative: quasi-states, recognition and international statebuilding, 1945-2012 | political-economy | 19 | 4 | medium | strong | $0.0101 |
| Dual Dependency and the Conversion Gap | Transnistria in the post-Soviet space, 1991-2012 | political-economy | 29 | 1 | low | strong | $0.0190 |
| Viable but Strained Diaspora Statehood | Somaliland, 1991-2012 | political-economy | 46 | 1 | low | strong | $0.0188 |
| Sectarian Exclusion as Political Order | Syria, 2011–2024 | political-economy | 22 | 8 | low | strong | $0.0098 |

**The whole set cost $0.07 to draft.** A paper standing on one analysis record is roughly a tenth the price of the multi-record papers in D and E, because cost tracks the size of the claim inventory the drafter is handed and nothing else.

**Read the books-cited column before anything else.** 2 of these papers — *Dual Dependency and the Conversion Gap*, *Viable but Strained Diaspora Statehood* — cite exactly **one book**. That is not a drafting failure; it is the library reporting its own shape. The shelf holds one comparative study of unrecognised states and no monograph on either territory, so a question about one of them has one source to stand on and the paper says so in its own coverage disclosure. It is the same corpus gap the sealed panel found in section 7.4, showing up before any reviewer was asked. A paper carried by a single book should be read as a well-formed argument over a thin shelf, never as a finding.

**None of these were put to the sealed panel.** The panel figures in section 7.4 cover the two papers in D and E and their planted-defect control, and adding papers to the shelf does not extend them. The four mechanical gates ran on every paper here, as they run on every paper by construction.

### Extraction Bargains Make Nations, Rent Breaks Them

*`data/papers/9f449f41b88e5c70.md` · lens: political-economy · 15 claims, 0 of them the paper's own · 8 books cited*

**The thesis put to it.** Nationalism is best explained as a boundary-making force that ties state formation to war. Industrial modernity and reconstructed ethnic symbols describe what nationalism looked like; the fiscal-military nexus of extraction, conscription and the citizenship bargains they forced explains why it took hold. Where external rent replaces domestic extraction, the mechanism fails and so does the nationalism it was supposed to produce.

**The question behind it** — `e7d6a2646523cb1d`

> **Case.** Comparative: nationalism and nation-state formation, nineteenth and twentieth centuries
>
> **Request.** Is nationalism best explained as a product of modernity, a reconstruction of inherited symbols, an organized ideology of the nation-state, or a boundary-making force linking state formation to war?

### War, Extraction, and the Rent Rupture

*`data/papers/a1039fad4da31320.md` · lens: state-formation · 15 claims, 2 of them the paper's own · 10 books cited*

**The thesis put to it.** Mann's distinction between infrastructural and despotic power specifies Tilly's war-centred account of European nation-state formation rather than displacing it: war remains the driver, and the distinction explains why the same war pressure produced effective bureaucratic capacity in some states and hollow coercion in others. The specification fails where external rent substitutes for domestic extraction and severs the war-taxation- representation link the model runs on.

**The question behind it** — `ec94042430910584`

> **Case.** Comparative: European nation-state formation, 1760-1914
>
> **Request.** Does Michael Mann's distinction between infrastructural and despotic power overturn Charles Tilly's war-centred account of European nation-state formation, or merely specify its mechanisms?

### Material Contests Over Juridical Arrangements

*`data/papers/f5ae5ff2f09766af.md` · lens: political-economy · 19 claims, 7 of them the paper's own · 4 books cited*

**The thesis put to it.** Later accounts of sovereignty and statebuilding contest what Jackson's quasi-states were meant to explain rather than merely narrowing or extending the concept: Zaum contests the persistence of the negative-sovereignty regime, Caspersen contests the one-way direction of the juridical-empirical gap, and Ayubi contests the sufficiency of a normative-legal frame. The contestation is self-limiting, because each account argues in the vocabulary Jackson built.

**The question behind it** — `fa44475aaaa90a48`

> **Case.** Comparative: quasi-states, recognition and international statebuilding, 1945-2012
>
> **Request.** How do later accounts of sovereignty, recognition and international statebuilding modify Jackson's concept of quasi-states: do they narrow it, extend it, or contest what it was meant to explain?

### Dual Dependency and the Conversion Gap

*`data/papers/408378f2e286fff2.md` · lens: political-economy · 29 claims, 6 of them the paper's own · 1 book cited*

**The thesis put to it.** Non-recognition built Transnistria through a dual dependency -- Russia for security, energy and credit, Moldova for customs and trade access -- that no other post-Soviet unrecognized state carries. That structure funded real institutions and a militarized hybrid regime at the same time, and it made the entity's domestic politics turn on business interests that pay the cost of isolation. What it does not explain is how the inflows were converted into working institutions.

**The question behind it** — `be50533708e44f33`

> **Case.** Transnistria in the post-Soviet space, 1991-2012
>
> **Request.** How has non-recognition shaped Transnistria's internal state-building, and what can be established about that case specifically rather than about post-Soviet unrecognized states in general?

### Viable but Strained Diaspora Statehood

*`data/papers/273aea05df54e2df.md` · lens: political-economy · 46 claims, 15 of them the paper's own · 1 book cited*

**The thesis put to it.** Somaliland substituted diaspora remittances for a patron state and inter-clan consensus for imposed unity, and that substitution produced statehood that works relative to its collapsed parent while carrying its own structural strain: clan-skewed remittance flows, militarized spending, and democratic backsliding after 2006. The account rests on a thin evidential base, and saying so is part of the finding rather than a caveat attached to it.

**The question behind it** — `c2afb6d42f713e1c`

> **Case.** Somaliland, 1991-2012
>
> **Request.** How does the absence of international recognition shape Somaliland's internal state-building and its claim to sovereignty, and how secure is the evidential basis for that account?

### Sectarian Exclusion as Political Order

*`data/papers/5d866ef2ce4971ae.md` · lens: political-economy · 22 claims, 2 of them the paper's own · 8 books cited*

**The thesis put to it.** Sectarian exclusion in Syria after 2011 was a strategy of political order, not a by-product of the war. Selective repression, shabbiha deployment, spatial fragmentation and a war economy that dispossessed whole populations politicized sectarian difference from above; the uprising's own origins were cross-communal. Sectarianism's long history in Syria made it available to be activated, and does not show it was waiting to surface.

**The question behind it** — `92d2d85745ecaa2d`

> **Case.** Syria, 2011–2024
>
> **Request.** Did the war politicize sectarian difference primarily through elite organization, coercive networks, and territorial rule, or did it disclose pre-existing mass sectarian solidarities?


## Appendix G — Every question Axial asks

Inside the pipeline, a model is consulted in sixteen places, plus a set of judges that sit outside it. Nowhere is it asked to pick from a list. Every one of the sixteen is an open question with an explicit right to answer "I cannot tell from this", and in every one code assembles what the model sees and reads what comes back.

The inventory below is complete. The questions are quoted from the working system, lightly trimmed for length.

### G.1 Reading the corpus

| | Asked of | How often | The question |
|---|---|---|---|
| **1. Envelope** | Each book's own opening and closing prose | Once per book | What is the author's stated thesis, the scope of the argument, the argument as restated, and the table of contents? *Based only on the supplied text. Do not infer from the title, the filename, or any outside knowledge.* |
| **2. Interrogation** | One passage | Once per passage | The fourteen questions in section 3. *Answer only from the passage. If it does not support an answer, say so. A guessed answer is worse than an abstention, because a reader cannot tell it from one you actually read.* |
| **3. Name merging** | A cluster of similar-looking name forms | Once per cluster | "They were grouped together by a clustering algorithm because their wordings are similar. **That grouping is a hint, and it is often wrong.** Decide which of them name the same thing… Where what is shown does not let you tell, say so instead of guessing." |
| **4. Gather** | Every passage that names one thing | Once per name | "Say what the disagreement actually is, in a few sentences, naming who holds which side… **null is a last resort, not the default answer.**" |
| **5. Gather merge** | The partial findings for one very large name | Only when one call could not hold the name | "Treat them as partial evidence about one name, never as competing claims to weigh against each other." |
| **6. Position extraction** | A group of passages with similar claims, shown **without their authors** | Once per group | "Find the arguments running through these passages. Your job is to find **what RECURS**… If you are producing roughly as many arguments as there are passages, you are restating the passages rather than finding the arguments in them, and **you have not done the task**." |
| **7. Relating positions** | A neighbourhood of arguments, again **without authors** | Once per neighbourhood | "Say how these arguments actually stand to one another… **There is no list of allowed relations.** Do not pick from a menu and do not reach for opposition by default… **Most pairs have no relationship, and saying so costs nothing.**" |

**Questions 6 and 7 are asked blind.** The model is shown the claims and never the authors. If it could see who wrote what, it could decide that Mann and Tilly meet because they are Mann and Tilly. The count of how often the map joins different books would then be measuring the model's sense of who *ought* to argue, not the corpus. Hiding the authors costs nothing and makes that count mean something.

**Question 7 is asked with no vocabulary at all.** Not "is this support or opposition?" but "what is actually there?" The consequence is measurable: because nothing asked for opposition, opposition came back at 6.6% rather than at whatever rate a leading question would have produced. The model invented 504 labels of its own.

### G.2 Answering a question

| | Asked of | How often | The question |
|---|---|---|---|
| **8. Brief interrogation** | Your question, against the library's measured coverage | Once | "Find every premise smuggled into this brief's case and request, and test each one against the corpus coverage stated below — **never against what you recall or assume about the world**." Each premise comes back supported, contradicted, or the corpus is silent. Refusal is available. |
| **9. Fork check** | Your question, against a measured imbalance | Once, and usually finds nothing | Is there a real fork here — a source imbalance, or a mismatch between the period you asked about and the years the books were published — that would change what evidence gets assembled? If so, ask the analyst. If not, do not. |
| **10. Retrieval** | The library, through ten deterministic tools | Many turns, bounded | Which passages bear on this? The model proposes one query at a time and is told back only what the evidence set now holds and which books it spans. |
| **11. The door** *(optional map path)* | Your question alone, **before anything shows it the corpus** | Once | "Say what arguments this question is actually about. Write each one as a standalone sentence that a scholar could assert and another could deny… **Name no authors and no books.** Do not hedge and do not balance. Each account gets its strongest statement, **including the one the question may end up rejecting**." |
| **12. Synthesis** | The assembled evidence | Once | "Answer this question, using the evidence below as your grounds… Where this question asks you to choose between positions, **your answer must commit to one of them and defend it**, rather than surveying the positions without settling anything. **At least one claim must also state plainly where the account you commit to is weak or fails.**" Every claim is marked (a), (b) or (c) and carries its grounds. |
| **13. Counter-position** | The same evidence, when the question is contested | Once | "State the **strongest** opposing position the corpus itself supports, or say plainly that it does not — **never to invent one**." |

The synthesis instruction forbids the failure mode a careful assistant defaults to. A model asked to weigh two accounts will usually produce a balanced summary in which both have a point, because that is the safest-sounding output. Axial requires a verdict, and then requires the verdict's own weakness to be stated as a claim in its own right.

### G.3 Writing the paper

| | Asked of | How often | The question |
|---|---|---|---|
| **14. Arc plan** | The inventory of claims that survived | Once | "Plan an arc. Order the sections so each earns the next, and assign each claim to the section that uses it… **At least one section must state the opposing position at its strongest**, unless the records themselves report the corpus is one-sided. A paper that quietly drops the side it disagrees with is the failure this pass most needs to avoid." |
| **15. Drafting** | One section's assigned claims | Once per section | "Write ONE section of a paper. **You have no tools, no retrieval, and no access to any source: the claims below are the whole world**, and you may not assert anything that is not traceable to one of them." |
| **16. Shape check** | The finished paper | Once | Does this read as an argument or as a list? Reported, never blocking. |

### G.4 The judges, which sit outside the pipeline

Five bounded checks — does a cited passage support its claim, is an inference contradicted by its own evidence, is the opposing case stated at its strongest (a *steelman*) or knocked down in a weakened form nobody actually holds (a *strawman*), did the pre-pass catch the planted premise, did the answer do something the case declares disqualifying — plus the sealed review panel.

**None of them may be run by the model that produced the thing being judged.** The guard raises before the call is made, not after. The panel goes further and requires a different training lab, because a family-mate's agreement is weak evidence.

---

## Appendix H — Glossary

**Passage.** The unit Axial reads: a few paragraphs cut along the author's own boundaries, 3,500 to 9,000 characters. One to four printed pages.

**Name page.** A page for every named thing any passage mentions, listing the passages that mention it. 47,584 of them in the current library.

**Position.** A group of passages that make the same argument, found once and offline by reading each group in full. 1,937 in the current library.

**Relation.** A stated link between two positions — supports, qualifies, contradicts, and 501 other labels the model coined itself. 1,472 in the current library, 328 of them connecting positions with no author in common.

**Brief.** A question put to Axial: a case and a request. Optionally a lens and source weights.

**Disposition.** What Axial decided to do with a brief: proceed, proceed with stated bounds, or refuse. A refusal is a completed run.

**The three kinds.** Every assertion is marked as exactly one: **(a)** a source says it, **(b)** Axial inferred it across sources, **(c)** the analyst's judgment running past what the corpus grounds.

**Grounds.** The passages behind a claim. Every (a) and (b) claim carries them, and every one must resolve or the claim fails a hard gate.

**Counter-position.** The opposing case, stated at its strongest from corpus grounds. Mandatory on a contested question, or the one-sidedness must be explicitly disclosed and attributed to the library.

**Coverage map.** Per name, how many passages the library actually holds and how many claims the answer hung on it. The input to the confidence cap.

**Confidence band.** High, medium or low. Capped by the least-covered name the output relies on, and never raisable by the writing model.

**Tag (retired).** A label from a closed list, attached to a passage. Axial's first version used five such lists and they were measured and abandoned (section 4). They survive only as *examples*, shown after the free answer and never checked against it.

**Blind pass.** A model call deliberately denied information it would otherwise use. Position extraction and relation-finding never see the author of a passage, so a count of how often the map joins different books measures the corpus rather than the model's sense of who ought to argue.

**Corpus pin.** A content hash of the raw sources. Two outputs are comparable only if they were produced at the same pin.

**Gate.** A blocking check the model cannot reach. Distinct from a *measurement*, which is reported and blocks nothing.

**Sealed packet.** What a reviewer sees: the paper, the resolved text of every passage it cites, the bibliography, and nothing else.

**Positive control.** A copy of a real paper with three known defects planted in it, used to prove the reviewers are still reading before any of their verdicts are trusted.
