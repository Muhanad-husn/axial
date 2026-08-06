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

<!--LIBRARY_TABLE-->

The full bibliography, with publishers, editions, translation notes and per-file provenance caveats, is in `docs/corpus-bibliography.md`.

**Two entries are small enough to question.** Kandiah 2018 and Malešević 2026 are a master's research paper and a journal article rather than books, and both are close to invisible in the index. Gould 2003 now joins them at the thin end.

**The metadata warning is not hypothetical.** The Heydemann *War, Institutions, and Social Change* file carries embedded metadata attributing it to Michael Hanby's *Augustine and Modernity*, a different book entirely. Two further files carry a placeholder author or a scanning-tool title. Embedded metadata alone is not a safe basis for citation, which is why it is cross-checked against the title page and why unconfirmed fields stay marked.

**Copyright.** No source text is committed to the repository. Every derived artifact that carries verbatim passages — the passage records, the name pages, the reviewer packets — lives outside version control for that reason, and reviewer packets are assembled at run time and never written into the repository.

---

<!--PAPERS-->

## Appendix F — Every question Axial asks

Inside the pipeline, a model is consulted in sixteen places, plus a set of judges that sit outside it. Nowhere is it asked to pick from a list. Every one of the sixteen is an open question with an explicit right to answer "I cannot tell from this", and in every one code assembles what the model sees and reads what comes back.

The inventory below is complete. The questions are quoted from the working system, lightly trimmed for length.

### F.1 Reading the corpus

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

### F.2 Answering a question

| | Asked of | How often | The question |
|---|---|---|---|
| **8. Brief interrogation** | Your question, against the library's measured coverage | Once | "Find every premise smuggled into this brief's case and request, and test each one against the corpus coverage stated below — **never against what you recall or assume about the world**." Each premise comes back supported, contradicted, or the corpus is silent. Refusal is available. |
| **9. Fork check** | Your question, against a measured imbalance | Once, and usually finds nothing | Is there a real fork here — a source imbalance, or a mismatch between the period you asked about and the years the books were published — that would change what evidence gets assembled? If so, ask the analyst. If not, do not. |
| **10. Retrieval** | The library, through ten deterministic tools | Many turns, bounded | Which passages bear on this? The model proposes one query at a time and is told back only what the evidence set now holds and which books it spans. |
| **11. The door** *(optional map path)* | Your question alone, **before anything shows it the corpus** | Once | "Say what arguments this question is actually about. Write each one as a standalone sentence that a scholar could assert and another could deny… **Name no authors and no books.** Do not hedge and do not balance. Each account gets its strongest statement, **including the one the question may end up rejecting**." |
| **12. Synthesis** | The assembled evidence | Once | "Answer this question, using the evidence below as your grounds… Where this question asks you to choose between positions, **your answer must commit to one of them and defend it**, rather than surveying the positions without settling anything. **At least one claim must also state plainly where the account you commit to is weak or fails.**" Every claim is marked (a), (b) or (c) and carries its grounds. |
| **13. Counter-position** | The same evidence, when the question is contested | Once | "State the **strongest** opposing position the corpus itself supports, or say plainly that it does not — **never to invent one**." |

The synthesis instruction forbids the failure mode a careful assistant defaults to. A model asked to weigh two accounts will usually produce a balanced summary in which both have a point, because that is the safest-sounding output. Axial requires a verdict, and then requires the verdict's own weakness to be stated as a claim in its own right.

### F.3 Writing the paper

| | Asked of | How often | The question |
|---|---|---|---|
| **14. Arc plan** | The inventory of claims that survived | Once | "Plan an arc. Order the sections so each earns the next, and assign each claim to the section that uses it… **At least one section must state the opposing position at its strongest**, unless the records themselves report the corpus is one-sided. A paper that quietly drops the side it disagrees with is the failure this pass most needs to avoid." |
| **15. Drafting** | One section's assigned claims | Once per section | "Write ONE section of a paper. **You have no tools, no retrieval, and no access to any source: the claims below are the whole world**, and you may not assert anything that is not traceable to one of them." |
| **16. Shape check** | The finished paper | Once | Does this read as an argument or as a list? Reported, never blocking. |

### F.4 The judges, which sit outside the pipeline

Five bounded checks — does a cited passage support its claim, is an inference contradicted by its own evidence, is the opposing case stated at its strongest (a *steelman*) or knocked down in a weakened form nobody actually holds (a *strawman*), did the pre-pass catch the planted premise, did the answer do something the case declares disqualifying — plus the sealed review panel.

**None of them may be run by the model that produced the thing being judged.** The guard raises before the call is made, not after. The panel goes further and requires a different training lab, because a family-mate's agreement is weak evidence.

---

## Appendix G — Glossary

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
