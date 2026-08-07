![Axial](axial-logo.png)

# Axial — a research report

**What it is, how it works, how it was tested, and what the tests showed**

Version 2.2 · 7 August 2026 · Muhanad Abulhusn

*Version 2.2 adds Appendix F, an index of the six further papers drafted since — five of them deliberately off the Syrian case the library is built around — and records what that exercise exposed about the shelf. Nothing in the system or its evaluation has changed; the panel figures in section 7.4 still cover the two papers in Appendices D and E and nothing else. Version 2.1 (6 August 2026) restructured the dossier as a research paper: an executive summary at the front, the full question inventory moved to an appendix, and the closing section recast as a final word. Version 1.0 (1 August 2026) remains superseded: it described a retrieval layer and a final deliverable that have both since been replaced.*

---

## Executive summary

Axial reads a shelf of academic books once, in full, and writes from the reading. It works passage by passage — a passage being a few paragraphs, about one complete move in an argument — and records what each passage claims, whose position that is, who it argues against, whom it cites, and every person, place, institution, event and concept it names. From that single reading it builds three things: an encyclopaedia in which every named thing has its own page; a map of the arguments running through the library, including where books that never cite each other disagree; and, on request, a research paper in which every citation can be traced, link by machine-checkable link, to a passage in a real book.

That makes it different in kind from the tools most readers already have. A chat assistant with PDFs attached, like every "chat with your documents" product, searches first and reads second: it sees only the fragments a question happens to retrieve, and nothing in its output separates what a source asserted from what the model composed on top. Axial reads everything before any question is asked. Every assertion in its output is marked as exactly one of three kinds — a source says it, Axial inferred it across sources, or the analyst's judgment — and the marking is enforced by checks that block release, not requested in a prompt. The model that drafts the final paper has no access to the library at all: its whole world is the list of claims that already passed the checks, so citing invented evidence is not forbidden by instruction but impossible by construction.

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

**Once at retrieval.** Interrogation produced a graph, and then materialisation threw most of it away by grouping passages into pages by their surface string. Whom a passage argues against was answered on **76.4%** of passages, and only **4.7%** of those targets joined to anything a question could actually reach. The opposition was recorded and not indexed. Loading the same passages into a relational store lifted that to **44%** and exposed **43,101 cross-source opposition pairs**. That is the redesign that made this version of the report necessary.

**Once at the argument map.** The relation pass could have been given a tidy list of relationship types. It was not, for the reason stated in section 3: an engine told to look for opposition finds opposition. Given no menu it coined 504 labels, and the shapes that recur were named afterwards from what came back.

### 4.7 What the old vocabularies are still good for

They did not disappear. They survive as **examples**, and the design around them is the single most important guard in the reading pass.

The model answers every question in its own words **first**. Only afterwards is it shown the example vocabulary, in a separate section, with the instruction that these are "NOT a menu, NOT a vocabulary, and NOT a set of allowed answers", that "nothing checks your free answers against them", and that "an answer that matches none of them is the normal case". It then adds a *second*, separate note about which example its free answer happens to sit nearest, and whether the fit is close, loose or none. Code never bridges the two fields — no normalisation, no rewriting, no filling one from the other.

That ordering is the whole difference between this design and the one it replaced. Reverse it and Axial is a tagger again, with extra steps, and nobody could tell from the output.

---

## 5. Why any of it can be checked

A production tool makes novel claims, and a novel claim has no answer key. There is no gold standard for "the right synthesis of thirty-five books". So Axial does not claim correctness. It claims **auditability**, and organises everything around one sentence: *accountability to grounds, with honest confidence.*

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

**Gather does not fully reproduce.** Asked twice about the same name, on byte-identical input, the pass agrees with itself 53% of the time, and **36.1% of the disagreements it records come back null on the second reading**. This was investigated and accepted as model variance. Its consequence is enforced in the design rather than hoped away: **a Gather finding is a retrieval hint and never a citation.** No gate scores an answer against one, and no answer is credited for repeating one.

**Name merging disagrees with itself 13.3% of the time** on names with three or more variants. Investigating it showed the disagreements are almost entirely singular/plural and article variants, and that they move **0.4% of the underlying material**. A surface changing group is not its evidence moving, and conflating the two overstated the problem by a factor of thirty.

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
