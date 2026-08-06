# What we're building, and why we ask for questions rather than answers

*The plain-language description of Axial, for a reader who does not read code. It is
attached to every persona prompt under `docs/sim-academic/prompts/`, and it is the answer
to the natural follow-up: "how is this different from just uploading the books to
ChatGPT?" It draws that line point by point. The corpus itself is listed in
[`corpus-bibliography.md`](corpus-bibliography.md).*

## The short version

Axial is a research instrument for comparative-historical analysis. You give it a *case*
and a *question* (for example, "Syria, 2011–2024: how did the fragmentation of the armed
opposition shape the trajectory of state collapse?") and it produces an original
analytical answer, or a full paper, grounded in a curated library of 35 scholarly works,
with every claim attributed, opposing positions surfaced, coverage disclosed, and its own
confidence stated honestly.

It is not a chatbot and not a search engine. Think of it as a disciplined research
assistant that has read a specific shelf of serious books, questioned every passage in
them, and can synthesize across them, while telling you what it is inferring versus what a
source actually said, and what it could not find.

## How it reads the library

Every passage in every book is read once and asked a set of open questions. What does it
claim? Whose position is that? Who is it arguing against? Who does it cite? What does it
name: which places, people, institutions, concepts, events?

Nothing is picked off a checklist. The answers are the reader's own words, and the passage
is allowed to say the question does not apply. There is no coding scheme decided in
advance and no vocabulary the corpus has to fit into.

Two things then happen with those answers. First, passages meet each other at the names
they share: a page is built for each name, and it says what the authors who wrote about
that name actually disagree about. Second, passages are grouped by what they *argue*, so a
passage can be reached through its claim even when it uses none of the words you would
have searched for.

That is the substrate the analysis runs over. It was grown from what the books said, not
imposed on them.

## Why it is different from the tools you already know

You have probably tried uploading PDFs to ChatGPT or Claude and asking questions, or used
a "deep research" button. Those are useful. Axial is deliberately different in ways that
matter for scholarship.

**Against uploading sources to a chatbot.** A chatbot retrieves a few relevant passages
and paraphrases them. It answers *from* a source. It rarely separates what a source
*claims* from what the model is *inferring*, it does not attribute reliably, and it will
produce a fluent, confident paragraph whether or not the sources support it. It never
tells you what it left out. Axial's core discipline is the opposite. Every assertion in
its output is marked as one of three kinds: **(a)** what a specific source states,
**(b)** the tool's own inference across sources, or **(c)** speculation running past what
the corpus grounds. A (b) claim with no real grounds is a failure the system is built to
catch, not a feature.

**Against hybrid retrieval and knowledge-graph systems.** Those improve *retrieval*: they
find better passages. Axial's harder problem is *synthesis*, producing an argument that no
single source made, across sources, the way a scholar writes a review essay, but held to
the attribution a scholar is held to.

**Against "deep research" on the open web.** Those tools scrape whatever the web offers,
weigh a preprint the same as a blog post, and sometimes cite sources that do not exist.
Axial works only on a curated corpus of real scholarship and never reaches outside it. Its
grounding is structural: it cannot cite what is not in the corpus.

## The honesty layer is the real point

Four things no consumer AI tool does, that a scholar would insist on:

- **The question is interrogated before it is answered.** Axial may bound a request ("the
  corpus covers this but not that") or refuse it outright. It surfaces premises smuggled
  into the question. Bounding and refusal are proper outputs, not errors.
- **Opposing positions are required.** If the corpus contains a serious challenge to the
  answer and the answer ignores it, that absence is treated as a red flag, not a clean
  result. On a genuinely contested question, finding no opposition means the analysis
  failed to look, not that no opposition exists.
- **Coverage is disclosed, name by name.** For every name an answer touches — a place, a
  scholar, an institution, a concept — it reports how much of the corpus actually stands
  behind it, so "we do not really know" stays visible instead of being papered over.
- **Confidence is calibrated, and never shown alone.** No manufactured "0.87" precision. A
  confidence band always appears next to the counts that justify it: this many passages,
  drawn from a name the corpus covers this thickly. The count is the honest signal; the
  band only summarizes it.

## Where the name comes from

**Axial coding** is the qualitative-research method of relating the concepts a corpus
raises to one another rather than reading each source on its own. That is the ambition and
the shape of the thing. What Axial does not do is the part of the tradition where a
researcher fixes the categories first. An earlier version of this system did label
passages against closed vocabularies, that design was measured, and it failed: it produced
almost no links between books, because attributes assigned in advance do not connect
anything. It was replaced by the open interrogation described above.

## Where it stands

The pipeline is built and runs end to end on the whole corpus: 35 works, 6,842 passages,
137,276 name mentions, 47,584 name pages.

Most of those pages are not useful, and the system says so. A page can carry a real
comparison when it holds roughly thirty to two hundred passages drawn from five or more
books — below thirty there is too little, above two hundred no reader can hold it, and
under five books it is one author talking. 329 pages clear that bar. Seven in ten
thousand. The binding constraint on this instrument is not the software; it is how many
books are in the library.

Papers it drafts are checked by four gates before release, and separately by panels of
reviewers who see the rendered paper and the full text of every passage it cites, and
nothing else. Those reviewers found something the mechanical gates could not: in both
dev papers the keystone Syrian claim is carried by Moroccan and Egyptian evidence, because
the corpus holds no Syria-specific passage on that mechanism. That is a gap in the
library presenting itself as a citation problem, and no amount of engineering fixes it.

## Why we ask for questions rather than answers

A question from someone who works in the field is the one input this system cannot
generate for itself. It reveals what a serious reader would actually want to know, which
sources the answer ought to rest on, where the real disagreement sits, and what would make
you dismiss an answer on sight. An answer, by contrast, is what the instrument is supposed
to produce; handed one, we learn nothing about whether it can.

So the ask is small: a few good research questions from your own area of expertise, the
ones that come out of your work rather than ones invented to be helpful. Even three is a
real contribution, and nothing about this is urgent.
