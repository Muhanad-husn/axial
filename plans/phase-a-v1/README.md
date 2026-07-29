# Feature: Phase A v1 — the graph, built by interrogation instead of labelling

Phase A v0 produced 18,761 isolated notes, 584 intra-book edges, and zero
prose-to-prose or cross-book connections. The cause was not sparsity. The only
mechanism that ever minted an edge asked one question per note ("does this text
say *as Table 3 shows*?") and filtered the answer against that book's own figure
list, so the edge set was bipartite and intra-source **by construction**.
Everything else the pipeline produced was attributes: values picked off closed
lists, which sort notes into bins and cannot express a relation.

Phase A v1 replaces labelling with interrogation. The same model, over the same
extracted text, is asked open questions instead of multiple-choice ones, and the
answers carry the specifics that make a connection possible: what is claimed,
who it argues against, who it cites, what it names. Notes meet each other at
shared names. What the two sides actually disagree about is found in a second,
cheap pass that reads the notes gathered at a name side by side, because a model
reading one paragraph of Ayubi has never seen Mann and cannot be asked to
compare them.

The operator benefits: a vault whose graph view is populated and traversable, an
index that is discoverable because it grew out of the corpus rather than being
decided before anything was read, and cross-book disagreements stated explicitly
with their grounds attached.

- **Slug:** phase-a-v1
- **Created:** 2026-07-27
- **Status:** **CLOSED 2026-07-29.** Slices 00–07 shipped; slice 08 was never
  built, by its own condition. See "Closure" at the end of this file.
- **New system?** no — it re-shapes the existing Phase-A pipeline. Extraction is
  untouched; every stage after it is replaced, deleted, or added.
- **Project directory:** `.`

## The pattern this follows

Karpathy's LLM-wiki pattern (the product's original inspiration, alongside
Obsidian): raw sources are immutable, an LLM-owned wiki layer sits above them,
and a schema document tells the model how to maintain it. Nodes are pages about
things; edges are links written while composing. There is no controlled
vocabulary, because the topics come out of the sources.

Axial v0 inverted all three: nodes were mechanical text fragments nobody
authored, edges were detected rather than written, and the vocabulary was fixed
before a single book was read. v1 keeps our real advantages over the plain
pattern — cached structural trees, per-book thesis/scope/chapter list, source
metadata, a domain frame — and spends them as **context for the interrogation**
rather than as filing categories.

## Decisions this plan encodes

Settled in design discussion, 2026-07-27. Numbered so issues can cite them.

1. **D1 — Note size.** Band moves from 1000–3000 characters to **3500–9000**
   (`CHUNK_MIN`/`CHUNK_MAX`, `src/axial/chunk.py`). Rationale: a claim and the
   evidence for it usually sit several paragraphs apart, so a 3k window holds
   half an argumentative move and the model can only answer half the questions.
2. **D2 — No note spans two chapters.** Already guaranteed: chunks are built
   inside a single section node, so they cannot cross a heading. No work needed.
3. **D3 — Short sections are accepted.** The below-floor merge is same-section
   only (`_enforce_min`, issue #207), and a section that is the sole group is
   kept as-is. A section under 3500 characters in total therefore yields one
   short note. That is a trade-off, not a defect, and follows directly from D2.
4. **D4 — The three-draw tagging pass is deleted** and replaced by **one open
   interrogation call per note** (D6). `votes_by_pass: {tag: 3}` and the
   majority-vote / abstention layer go with it.
5. **D5 — The table-reference hunt (`xref`) is deleted outright.** One call per
   note, and everything it produced is unused downstream. Figures and tables
   instead become nameable things the interrogation can name like any other
   entity, which is a strictly better replacement than a phrase detector.
6. **D6 — The interrogation.** One call per note. Context supplied: the note,
   its author/title/date, the book's thesis and scope, the chapter and section
   it came from, and the domain frame. Questions:
   - What is this passage about (multi-valued; the three domain values become
     the frame, not the answer).
   - What is being claimed, in one sentence.
   - What is this passage *doing* in the argument (not "evidence" but
     "conceding a point in order to narrow it").
   - What does the claim range over, and where does the author say it stops
     holding.
   - Whose position is this, and who is it arguing against.
   - Every named thing: people, places, institutions, events, movements,
     periods.
   - **Who does it cite, and is the citation support, foil, or authority.**
     Academic prose carries explicit references to other scholars, our books
     cite each other, and no pass we ever ran looked for them. These are
     author-stated cross-book edges available from the first reading.
   - What is the mechanism: what causes what, in what order.
   - What evidence is offered.
   - What comparison is made, stated or implied.
   - What is defined here versus merely used.
   - What the author concedes or hedges.
   - What it assumes without saying.
7. **D7 — Abstention is explicit.** Every answer is to be given *only* from the
   passage. Where the passage does not support one, the model says so plainly,
   including "cannot judge between X and Y".
8. **D8 — Examples must not capture the answer.** The old closed vocabularies
   (22 claim types, 7 argument roles, 5 scope values, the theory schools) are
   supplied as **examples**. The free answer is asked for **first**, in the
   model's own words; the nearest example is a **separate, secondary, marked**
   field. Getting this order wrong rebuilds the tag list through the back door
   and is the single biggest regression risk in the feature.
9. **D9 — The schema stops being a rulebook.** Two things survive: the
   canonical place/person spelling list (`polity_canonical.yaml`) as a *cleanup
   aid*, never a gate; and the domain frame as prompt context. Every closed
   value list, the off-list validator, and the agreement scoring against the
   hand-labeled set are retired.
10. **D10 — Reconcile runs over names, not notes.** Similarity and clustering
    are a **viewing aid** so the merge aggressiveness can be chosen by looking
    at the distribution; the model makes the merge calls with clusters as hints.
    Start loose, tighten by inspection. The output is an alias map, which is
    data, so every merge is reversible and re-runnable.
11. **D11 — Links live in the name pages, not in the notes.** Code writes one
    file per surviving name (no model): the name, its aliases, and its member
    notes as links. Obsidian treats links as connections in both directions, so
    the graph draws identically, and the whole link layer stays regenerable —
    a changed Reconcile rewrites a few hundred name pages instead of six
    thousand notes.
12. **D12 — Gather cannot blow the context window, by construction.** The model
    never fetches. Code assembles a fixed packet per name (per member note:
    author, year, the one-sentence claim, whose position, who it argues
    against — roughly 400 characters each) under a **hard character budget in
    code, not in the prompt**. A name whose packet would exceed the budget is
    split into batches, Gather runs per batch, and a short final call merges the
    batch findings. Large names are the interesting ones, so batching is a
    designed path, not an edge case.
13. **D13 — Verbatim text is a separate, narrow step.** Where a disagreement
    needs quoting, that is its own call over exactly two notes (~18k characters,
    safe by construction). Gather itself never reads full notes.
14. **D14 — Model routing.** The interrogation pass runs on `z-ai/glm-5.2`.
    That family was high-variance on the book-level pass and was reverted once
    for it (DEC-27/28), so the run **samples ~50 outputs at the start** rather
    than reading results after paying for all of them.
15. **D15 — Eval is deferred deliberately.** The hand-labeled agreement score
    measured a layer we are deleting, and open answers cannot be scored against
    it. How to measure the new pipeline is decided *after* Reconcile's output
    exists, because that output determines what is measurable.
16. **D16 — Everything except extraction re-runs.** Re-cutting notes changes
    every note id, so tags, edge pairs, vault files, the hand-labeled set and
    the corpus pin all stop matching. Most of that is being deleted on purpose.
    The structural trees are cached, so no book is re-processed and the re-cut
    is hours, not days. Figure/table records come off the cached structure
    rather than off the notes, so their descriptions should not need re-paying —
    to be confirmed, not assumed, in slice 01.

17. **D17 — Every model pass records its inputs and its outcome.** Settled
    2026-07-29, later than the rest of this list. A pass that asks a model to
    make a judgment writes one record per judgment: what it was shown, what came
    back, and enough identity to trace it to the passages behind it. The reason
    is D15's own deferral. The quality measure is still undecided (#447) and
    every candidate instrument needs the same provenance, so a pass that writes
    only its finished prose forces a re-run of the whole pass to recover it
    later. The record doubles as the resume checkpoint, so it costs one file
    rather than two. Interrogate complies (`data/answers/`), merge complies
    (`merge_decisions.jsonl`, carrying `evidence_tier` and `escalated` per
    decision, though the oldest 267 of 22,910 rows predate both fields and a
    whole-file read must not treat them as uniform), and Gather complies as of
    #412 (`data/names/disagreements.jsonl`). Materialize is exempt because it
    makes no model call. Slice 08 inherits this rather than being told again.

## What the pipeline looks like after

| Run | How often | Status |
|---|---|---|
| Extract | per book | unchanged, not an LLM pass |
| Source lookup | per book | unchanged |
| Envelope | per book | unchanged, and **promoted to context for everything below** |
| Page-furniture check | per suspect block | unchanged, it is a cleaner |
| Tables and figures | per table | unchanged, it is content |
| ~~Tagging ×3~~ | ~~per note~~ | **deleted** |
| ~~Table-reference hunt~~ | ~~per note~~ | **deleted** |
| **Interrogate** | once per note | **new** (D6) |
| **Reconcile** | once over all answers | **new** (D10) — merges names, emits the index |
| **Materialize** | once over the index | **new** (D11) — one file per name, no model |
| **Gather** | once per name | **new** (D12) — what the authors at this name disagree about |
| **Pairwise support** | on demand | **new** (D13), optional |

Call-count effect: about 56,000 note-level calls today (18.8k notes × 3 draws,
plus 18.8k table-reference calls) become roughly 6,000 (a 9k cap yields about a
third as many notes, read once). Cost is to be measured by a probe in slice 02,
not estimated here.

**Measured, 2026-07-27 (slice 02's probe, `data/logs/2026-07-27-interrogate-probe/`).**
The re-cut corpus is **6,166 notes**. Interrogation on glm-5.2 costs
**$0.00548/note billed**, so a full single-draw pass is **~$34** (floor ~$29).
Note the price table in `llm.py` computes $0.00636/note — 14% high against what
OpenRouter actually billed, measured with a credits-API delta over a 5-note run.
Treat any `PRICE_TABLE_USD_PER_1K` figure as a ceiling; the gap is prompt
caching on the ~9k-character example prefix every call shares.
D8 held: **0% collapse** onto the nearest example on `about`, `claim`, `move`
and `ranges_over`, over a 50-note sample drawn from the body prose of five
books. The one leak is `position_of`, where 6% of notes answered with a v0
sentinel (`unlisted`, `not-applicable`) carried in by the codebook's own
labelling imperatives — the lever, if it matters, is rendering example ids
without their definitions.

## Slices

Develop top to bottom. One slice = one issue = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 00 | spec rewrite | #417 | `specs/PRODUCT.md` rewritten for v1: interrogation replaces tagging, the wiki layer replaces the tag index, D1–D16 land as the contract, and the retired criteria are struck rather than left dangling | ✅ done | #420 |
| 01 | re-cut the notes | #418 | Band to 3500–9000, corpus re-chunked off cached trees, distribution reported (below-floor count, short-whole-sections, notes per book), figure records confirmed to survive | ✅ done | #428 |
| 02 | the interrogation pass | #419 | One call per note answering D6's questions with D7 abstention and D8 answer ordering, envelope context threaded in, per-note answer records on disk, plus a cost probe and a 50-output sample gate | ✅ done | #430 |
| 03 | retire tagging, xref and the vote layer | #414 | Delete the tag pass, the `xref` pass, `votes_by_pass`, the off-list validator and the closed-vocabulary gates; the schema file survives only as prompt examples and the spelling list | ✅ done | #433 |
| 04 | name inventory and similarity view | #415 | Collect every name from 02, embed, cluster, and report the distribution at a sweep of tightnesses so merge aggressiveness is chosen by looking (LLM-free; reuses `src/axial/distill/embed.py`) | ✅ done | #436 |
| 05 | Reconcile | #416 | Model merges names with 04's clusters as hints; emits a reversible alias map plus the surviving name list, which is the index | ✅ done | #437 |
| 06 | materialize the wiki | #411 | Code writes one file per surviving name (aliases, member notes as links) and notes carry their answers as frontmatter; **first point the founder can open the graph view and look** | ✅ done | #444 |
| 06b | name-variant candidate generation | #446 | Found opening the vault (#411/#444): clustering's own recall gap left `C. Tilly`/`Charles Tilly` as two pages because the merge pass never saw them together. A second, deterministic, LLM-free step (`axial.name_candidates`) proposes the missing pairs — initial-vs-full forename, bare surname with exactly one candidate (both `person`), case/whitespace-only — as additional clusters for the same, unchanged merge call | ✅ done | #448 |
| 07 | Gather | #412 | Per-name packet assembly under a hard budget with batching and merge, disagreement text written onto the name page, name-to-name links, plus a per-name disagreement record on disk (provenance for #447's undecided quality measure) | ✅ done | #468 |
| 08 | pairwise verbatim support | #413 | Two-note call that supplies quoted grounds where Gather found a disagreement worth quoting — optional, last, only if 07 shows it is needed | ✖ not built | — |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- **00 first.** This is a design change, not a behaviour tweak; the contract
  moves before the code does.
- **01 → 02.** The interrogation reads the re-cut notes. Running it against
  3k notes would pay for the wrong unit.
- **02 → 03.** Add the new pass before removing the old ones, so the pipeline
  is never headless.
- **02 → 04 → 05 → 06.** Each consumes the previous one's output.
- **06 → 07.** Gather writes onto pages that must already exist.
- **07 → 08**, and 08 may never be built.
- 01, 04 and 06 are LLM-free by construction. 02, 05, 07 and 08 are the only
  model calls added by this feature.

## Index quality — the backlog slice 06 opened

Opening the vault exposed work the slice plan did not anticipate. It is not a
slice; it is a set of fixes to the index that 07 will read. Tracked here so the
sequencing is visible, because most of it competes for one scarce resource.

| Issue | What | Lane | State |
|-------|------|------|-------|
| #463 | Fold case, whitespace and punctuation upstream of candidate generation — 305 groups the model refused, 489 it never saw. Absorbs #459 | A | **shipped** (PR #466) |
| #458 | `names merge` re-clusters 78k vectors on every run, silently, after `build` already did it | B | **shipped** (PR #465) |
| #457 | `DEFAULT_WORKERS = 36` rests on a measurement the corpus run contradicts (96 sustained 5.88 clusters/s, not 2.2) | B | **blocked** — the sweep that ran was underpowered and is retracted; needs ~3,000-batch points |
| #460 | Reinstate tier-3 passage evidence: escalation 54.3% → 15.4%, extra merges 75% correct | — | blocked, founder picks the scope — and see the escalation composition below |
| #461 | 5,629 escalated surfaces are a dead end; nothing reads them | C | **shipped** (PR #464), listing run |
| #462 | Sample the 18,034 pairs token containment proposes and the blocker never shows | D | ready, no `src/` change |
| #447 | D15 has expired: Phase A v1 has no measure of quality | E | **decided** (DEC-54) — the unit is the Gather disagreement entry, the reference is grounding against D17 provenance, calibrated once against the founder |
| #478 | The instrument #447 chose: `axial gather-eval sheet` / `score` | E | **shipped** (PR #479), not yet run on the corpus |
| #469 | Merge parse failures scale with worker count, 6 → 17 across one sweep | B | new, from #457's sweep |

### What the 2026-07-29 pass actually settled

Three shipped in parallel worktrees and were validated together on one corpus
probe: **#463 folded 3,367 mechanical groups with zero model calls** (canonical
names 63,872 → 63,012), **#458's reuse made clustering instant** instead of 10+
silent minutes, and **#461's listing ran**.

Two results change the table above:

- **#457 is not done, and its premise is untested.** A four-point sweep
  (36/64/96/128) measured a nearly flat curve, but each point was only ~436
  batches — too few waves to reach steady state, so ramp-up and tail-drain
  dominated. #454's run has 50x the sample and stands. `DEFAULT_WORKERS` must not
  move on the sweep's evidence in either direction.
  Retraction in `data/logs/2026-07-29-merge-worker-curve/summary.md`.
- **The escalation pile is mostly real.** 82% of the 6,141 escalations are
  name-shaped, and **87% of those appear in only one book** — the model abstained
  for want of a second attestation, not because the surface was junk. Bare
  page numbers are 3.2%, not the large share a first eyeball read suggested.
  That shrinks #460's addressable subset from 5,629 to roughly 660 multi-source
  surfaces. `data/logs/2026-07-29-escalation-composition/summary.md`.

### The serial spine

A corpus re-decide takes ~89 min and ~$3.60 plus a vault rebuild, and two cannot
overlap. Three of the issues above want one:

1. **#463 first.** It changes which batches exist, so affected batches re-decide.
   Partial and cheap.
2. **#460 next, if it goes ahead at all.** It changes every batch's rendering, so
   everything re-decides. Running it before #463 pays for a full pass over input
   that is about to change.
3. **#457's worker curve rides along with whichever pass runs**, rather than
   being its own corpus run. This was tried on #463's re-decide and did not
   work: that re-decide was only 1,746 batches, which split four ways gives
   points too short to measure. A valid curve needs points of ~3,000+ batches
   each, so it can only ride a **full** re-decide — #460's, if it goes ahead.

That gives one full re-decide instead of two, and it runs on clean input. It is
the same rule the benchmark work already learned: build the prerequisites before
the corpus-scale run, do not footnote them alongside it.

### What runs at the same time

Lanes A, B and D are concurrent — separate worktrees, and D touches no code at
all. C and E are founder design decisions, not builder dispatches. The practical
ceiling is about three at once, and the bottleneck is review, not tooling.

### Sequencing note

Index quality is not the product. **07 is.** Everything in this table makes the
meeting points cleaner and none of it produces a single disagreement, so it must
not be allowed to crowd out the slice it exists to serve.

#447 is the honest gate. Nothing currently measures whether a cleaner index
produces better disagreements, and its own body names the trap: answering that
question means running Gather both ways, which is the spend these fixes were
meant to protect. Hold #460 until #447 says what "better" means — otherwise it
buys a 75%-precision improvement to something unscoreable.

Evidence for the whole table lives in
`data/logs/2026-07-28-names-merge-evidence-redecide/`,
`data/logs/2026-07-28-evidence-tiers-by-escalation/`,
`data/logs/2026-07-28-cip-candidate-routing/` and
`data/logs/2026-07-29-name-fragmentation-scaling/`.

## Out of scope (whole feature)

- **Phase B's retrieval and brief pipeline.** It currently filters on the closed
  vocabularies that this feature retires, so it *will* need rewriting against
  pages. That is a separate feature and must not be smuggled in here. Until it
  is done, `axial brief` is expected to be degraded, not working-as-before.
- **The hand-labeled set, the agreement score, and the corpus pin.** Retiring
  and re-pinning are consequences of D16 and belong to their own cleanup, not to
  a slice here (D15 defers the replacement measure).
- **Best-of-N interrogation.** One draw. Voting was precision spend on a layer
  being deleted; if variance turns out to matter it is a config change later.
- **Rewriting any note's prose.** The notes are good. Nothing in this feature
  asks a model to replace them. Only frontmatter and name pages are written.
- **A new chunker.** D1 is two constants; the recursive/structural chunker is
  unchanged.
- **Web or external lookup of any kind** during interrogation. The passage and
  its book-level context are the only inputs (charter Principle I).

## Notes / open questions

- **D8 is the regression risk.** If the interrogation answers in the example
  vocabulary, we have rebuilt tagging with more values and the feature has
  failed silently. Slice 02 needs a check that the free answers are not
  collapsing onto the example strings.
- **Merge aggressiveness has no right answer up front.** "State formation
  through war" and "bellicist state building" must meet; two genuinely different
  ideas must not. D10 makes this a looking-and-tightening loop, which is why 04
  exists as its own slice rather than being folded into 05.
- **Fragmentation grows with the logarithm of corpus size, not linearly**
  (`data/logs/2026-07-29-name-fragmentation-scaling/`). Detectable splits go
  2.67% at 31 books to ~4.7% at 1000. Spelling variants per entity saturate at
  about two by the third book, and severity falls as attestation rises: when a
  9+-book entity is split, its best page still holds 82% of the occurrences
  against 64% for a one-book entity. The model's hardest case is *two* books,
  not many. So corpus growth is not the threat to the index that the present
  mechanical backlog is, and D10's under-merge bias stays affordable at scale.
  Caveats travel with the curve: fitted over k=2..31 and read out to 1000, with
  merging held fixed at the 31-book decision.
- **Citation harvest will be partial.** Some in-text references come out of the
  scan mangled and the furniture cleaner drops some footnote markers, and most
  of what these books cite is not in our corpus. Out-of-corpus citations are
  still valuable as names — they say who the author is arguing with — but cannot
  become internal links. Expected, not a failure.
- **Figures and tables as nodes** is the honest replacement for the deleted
  table-reference hunt (D5). Confirm in slice 06 that a figure's page
  materializes like any other name.
- **Slice 06 is the first look.** Everything before it is invisible. It is worth
  sequencing so the founder can open the graph view as early as possible, and
  worth resisting the urge to build 07 before that look happens.

## Closure

**Closed 2026-07-29 by founder decision.** The feature's premise was that
interrogation beats labelling at producing a connected graph. It did.

### What shipped

| | v0 | v1 |
| --- | ---: | ---: |
| notes | 18,761 isolated | 6,148 interrogated |
| edges | 584, intra-book by construction | a name layer of 62,821 pages |
| cross-book meeting points | 0 | 9,505 names, 8,769 of them cross-author |
| stated disagreements | — | 447 |

Slices 00–07 all shipped. The pipeline runs end to end: interrogate, reconcile,
materialize, gather. The vault opens in Obsidian with a populated graph.

### What was not built, and why

- **Slice 08 (pairwise verbatim support, #413)** — never built, exactly as the
  slice table allowed: "optional, last, only if 07 shows it is needed." 07 did
  not show it. Closed not-planned rather than left hanging.
- **A quality number.** The instrument exists (#478/#480, `axial gather-eval`)
  and has never been run against the corpus. Nobody has read the 447
  disagreements for correctness. The defect classes measured during the corpus
  pass are absent, but "no measured defect" is not "verified right," and the
  phase closes without that verification. This is a stated gap, not an
  oversight: three days of mechanism inspection produced no change to the
  product's output, and the founder cut it off in favour of using the thing.
  The ship-blocking bar (#483) stays blocked until someone runs the score.

### The backlog, closed out

Every leftover was measured against one bar the founder set: **anything moving
accuracy, latency or cost by less than about 5% is dropped or converted to
future expansion.** Phase A v1 leaves zero open issues.

| # | measured effect | outcome |
| --- | --- | --- |
| #473 | metadata present in the corpus of record; 63 disagreements attribute Heydemann correctly | closed — the gap was already fixed, the issue body was stale |
| #483 | gates a phase that is now closed | closed — a ship gate cannot be defined after the ship |
| #457 | worker count changes pass latency, **0%** of output, and no more passes are due | closed |
| #481 | author-vs-editor is a display distinction; Crossref already flattens it | closed |
| #482 | 37 of 1,910 names (1.9%), 10 of 447 findings (2.2%) | future expansion — trigger: an answer wrong because an author's evidence was split across year-pages |
| #460 | escalation 54.3% → 15.4% is large on the mechanism, but severity falls with attestation so the effect is tail-shaped, against a full merge re-run plus re-gather | future expansion — trigger: an answer wrong because two pages should have been one |
| #484 | Phase B's sweep gates on the pin (`resolve_trusted`) | moved to Phase B, not dropped |

Two things this list is not. It is not a list of things believed unimportant:
#460's mechanism number is real and #482's measurement stands, and both bodies
survive as the starting point when their trigger fires. And it is not a promise
that the index is clean. It is a statement that **no further index work starts
without a failure from use to aim it.**

The standing rule: **new issues come from using the product, not from auditing
it.** Re-open only when a real answer is visibly wrong — then the failure names
which one to fix, instead of leaving it to guesswork.

### The one thing that carries forward

Phase B filters on the closed vocabularies this feature retired, so `axial
brief` is degraded by design. That was called out in "Out of scope" from the
start and is now due. It is the next feature, not an unfinished part of this
one.
