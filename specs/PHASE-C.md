# PRD — Axial: Phase C Paper Authorship

**Project:** Axial · **Version:** 1.0 · **Status:** Ratified · **Owner:** Operator (single-operator system)

**Inherits.** This PRD is the Phase-C phase spec under [`specs/CHARTER.md`](CHARTER.md), the product-wide behavioural constitution; its P0 criteria are the authorship-layer instance of the charter's five principles. Its substrate is Phase B, specified in [`specs/PHASE-B.md`](PHASE-B.md); Phase B is consumed here, never modified here, and never triggered from here. Phase A ([`specs/PRODUCT.md`](PRODUCT.md)) is consumed read-only beneath both. This spec does not restate or override the charter (charter §4).

**On the name.** Phase C is **Paper Authorship**. Phase B produces an analysis: a claim graph over one brief, marked, grounded, and banded. A stack of analyses is not a paper. Phase C takes a thesis question and a named set of existing Phase-B analysis records and produces a **paper**: a narrative arc across those analyses, plus the apparatus that makes it checkable. Its own contribution is cross-source synthesis on the (b) seam. Venue conventions, citation style, and length targets are Phase D.

> **FOUNDER RULING 2026-08-01, and it moves a boundary rather than a detail.** A Phase-B answer must itself read as an argued paper, not as a bulleted claim inventory. The evidence is the rendered answer: smoke-v5's S-01 puts its own thesis — *"the available evidence supports the conclusion that Mann's distinction merely specifies… rather than overturning it"* — in the **twelfth of twelve bullets**, after eleven premises in retrieval order, and then renders `usage_ratio=22.954545454545453` beneath them. The material of a paper is all present and none of it is arranged. A user who asks a question and receives that has been handed the parts.
>
> **So the prose layer must serve one analysis record as readily as several.** Arc planning, drafting, the citation index, the bibliography and rendering all take a *list* of records, and a list of one is not a special case. That is what stops the machinery being written twice.
>
> **REVISED the same day, on the founder's second reading, and this supersedes what stood here.** The first version of this ruling put the prose layer in Phase B and had `axial ask` render through it immediately. That is the riskier order. Phase B was closed and benchmarked one day earlier; smoke-v6 and eval-v2 are the standing baseline, the sealed panel's packets are built from the **rendered** answer (§7.7), and re-rendering it changes what every prior reviewer read and what every prior number means. Reopening a just-measured layer to restructure its output is the polishing-past-the-bar the handbook names as a process bug.
>
> **The layer is therefore built here, in `paper/`, and Phase B is not reopened now.** This costs nothing that the first version bought: the duplication it guarded against is prevented by the record-count-agnostic signature, not by which phase holds the file. If Phase B later routes `axial ask` through it, that is a call plus a mechanical module move — no design decision is deferred and none is pre-made. A neutral shared home is **not** built ahead of a second caller (over-engineering tripwire: an abstraction with one implementation).
>
> **What this leaves Phase C is what it always actually was:** an arc across *several* analyses, and the cross-source (b) claims that span them. That is a narrower and truer definition than "the layer where prose happens". Nothing else in this spec changes shape — the paper record, the confidence ceiling, the four gates, the contested predicate and the panel all still describe the multi-record case. What changes is where three of the five stages **live**, which is settled here and specified in Phase B.
>
> **The lens carries the argumentative register**, which is why it is essential and why it is named in §7.1. A lens is the difference between a paper and a list of true sentences. As of this ruling it reaches the synthesis model as a bare filename stem — `axial.analyze.synthesis._available_lenses` globs `config/lenses/*.yaml` and takes `path.stem`, and nothing in `src/` ever opens a lens file, so the `description` that defines the lens is unread data. Phase B owns that fix.

**Self-sufficiency note.** This document is the complete build specification for Phase C v0. The input contract, the arc, the paper record, the apparatus, the acceptance criteria, the per-run rung-3 gates, and the offline coherence eval track are all here. Beyond the charter and the Phase-A/Phase-B contracts it consumes, it references no external file. Where a decision is genuinely unresolved it is listed under **Open Questions**; everything else is settled and should be built as written. Status flags mark tentative content: **[FIRM]** build as-is · **[TENTATIVE]** likely to shift after the first real papers.

**Revised 2026-08-01 against Phase B v1's close.** This spec was written against Phase B v0. Phase B v1 replaced the contracts it consumed and measured several things it assumed. Every changed passage is marked **CORRECTED** or **STRUCK** in place rather than silently rewritten, so what moved stays readable. Four changes are design rather than wording:

- The coverage map is **unioned from the source records**, not recomputed, because recomputation now needs a retrieval trajectory a paper record does not have (§7.11, §7.14).
- A carried claim carries its origin's **clamped** band, not the band the analysis record persisted (§7.4).
- The drafter reads **one section's assigned claims at a time**, because Phase B measured that ~20 notes reach a model however many are supplied (§4, §7.2, PHASE-B P2-7).
- **Phase C does not build a panel.** `src/axial/panel/` exists, was built under PHASE-B §9.4 / issue #385, and has run twice. Phase C extends it (§6, §7.7–§7.9, §11).

> **FURTHER CORRECTED 2026-08-01 (issue #570), later the same day.** The first bullet above is no longer the whole story. A paper record now has a trajectory -- not Phase B's, but its own, produced by the opposition gap-and-repair pass (§7.15) -- so the coverage map is a **union of two scopes**, not a union-only: the carried scope this bullet describes, unchanged, plus a second, **earned** scope computed natively over that trajectory, the same way Phase B computes a real analysis record's own map. The bullet is left as written because it was correct when written; §7.3, §7.11 and §3 non-goal 1 carry the full amendment below.

---

## 0. What this is, in one paragraph

Phase C is a single-operator paper author driven through the `axial` CLI. It takes a **paper brief**, which is a thesis question plus a named set of Phase-B analysis records, and returns a **paper record** plus a rendered markdown paper. The claim inventory it draws on is already grounded, marked, and banded by Phase B, so authorship is assembly and arrangement rather than fresh evidence-gathering. Phase C's own new knowledge is a bounded set of new **(b) claims**: cross-source inferences that relate claims across two or more analysis records, which is what a paper actually contributes over the analyses beneath it. Around the drafting sit four cheap gates that run on every paper and can block its release: provenance integrity and counter-position presence, both mechanical, plus two narrow judged checks on the grounding and the labelling of the new (b) claims. Where the named records argue opposite sides, that disagreement is the scholarly substance rather than a defect: both sides survive into the paper with their sources identified, and the counter-position gate holds the result to charter Principle IV. Whether the argument actually holds together is a different question, and it is not answered per paper. It is **measured offline, on a sample**, by a panel of at least three frontier-model reviewers from a different vendor than the drafter, each seeing only a sealed packet and holding no tools with which to read anything else. That panel is an instrument for measuring the system's accuracy across performance tiers and model combinations, not a checkpoint every paper waits at, and its own numbers count for nothing until it has been shown to catch deliberately planted defects. The enforced standard is unchanged from every layer beneath: **accountability to grounds, with honest confidence** (charter §0).

---

## 1. Problem statement & context

Phase B solved the analysis layer. Given one brief, it returns a claim graph in which every claim is marked (a)/(b)/(c), carries resolvable grounds, and discloses a confidence band against a per-name coverage map (per-polity until Phase B v1; see §7.11). What it does not do, deliberately, is write. A reader handed five analysis records has five answers to five questions and no argument.

The gap Phase C closes is the arc. A paper is not a concatenation of findings. It states a thesis, orders material so that each section earns the next, states the opposing school at its strongest, and carries apparatus that lets a reader check any sentence. The value the operator wants is the charter's framing at its full scale: original comparative-historical scholarship, produced rather than retrieved (charter §0).

Four failure modes govern this phase, and all four are invisible in fluent prose.

**Laundering by re-voicing.** The easiest way to write a paper from analyses is to restate their (a) claims in the paper's own voice. The result reads as the tool's synthesis while contributing nothing, and it erases the (b) seam the charter makes non-negotiable (Principle II). Restatement is not synthesis.

**Confidence inflation across a layer boundary.** A claim disclosed as `low` in a Phase-B record, quoted into a paper's argument and surrounded by confident prose, reads as settled. Nothing in the prose carries the band forward. The band must survive the copy, and it must survive the inference built on top of it.

**Collapsing a live dispute.** Comparative-historical sociology is a field of opposing arguments, and a paper built from records that argue opposite sides is the case this phase most needs to get right. The failure is to pick a side quietly: to reconcile the two records into one position, or to simply not cite the losing one, and produce a paper that reads as settled scholarship over a question the sources contest. Charter Principle IV names this exactly, as having "collapsed to one side and hidden that it did." The paper that drops its opposition looks cleaner than the paper that carries it, which is what makes this failure attractive and why a gate has to catch it (§7.14).

**Coherence without an oracle.** The per-run checks in this phase are all local: this sentence traces to that claim, this band did not rise, this one inference is supported by the text it cites. None of them can tell whether section 4 follows from section 3, or whether the counter-position is a steelman or a puppet. That judgment needs a reader who was not in the room. Until 2026-07-24 the plan was a human referee. There will not be one (§9). The replacement has to be at least as adversarial as the thing it replaces, which is why it is sealed, multi-vendor, plural, and positive-controlled. It is also, like the referee it replaces, applied to a **sample** of the work rather than to every draft. Measuring whether the system writes coherent papers and deciding whether one paper may be released are different jobs, and a panel run on every draft would do neither well: it would be too slow to gate on and too narrow to measure with.

This PRD covers **Phase C (authorship) only**. It does not cover analysis (Phase B owns it), format adaptation (Phase D), or any change to the corpus, schema, or analysis records.

---

## 2. Goals

1. **A narrative arc over existing analyses.** Produce a paper whose sections are planned before any prose is written, each section built from named claims already present in the source analysis records (charter Principle II, grounded by construction).
2. **New knowledge only on the (b) seam.** Phase C's own contribution is cross-source inference relating claims across two or more analysis records, always marked as the tool's inference, never voiced as a source assertion (charter Principle II).
3. **No claim outranks its source.** A carried claim keeps its band exactly; a new (b) claim never exceeds the weakest claim it stands on. Confidence disclosure survives the layer boundary intact (charter Principle V).
4. **Mechanical apparatus.** In-text citation markers that resolve claim to grounds to chunk to source, and a bibliography generated from `source_meta` for exactly the sources cited. One plain format, deterministic, no style engine.
5. **The counter-position survives into the paper.** The opposing school is stated at its strongest in the paper itself, or the paper explicitly discloses that its source records found the corpus one-sided (charter Principle IV).
6. **Cheap gates on every paper.** The four per-run gates are two mechanical checks and two narrow judged checks over the new (b) claims. Every paper passes through them, and no paper waits on anything expensive to be released (§10.1).
7. **Opposing positions are the substance, not a defect.** Source records that argue opposite sides are opposing arguments, never an error to adjudicate. Both sides survive into the paper with their sources identified, and charter Principle IV binds the result (§7.14).
8. **Coherence measured from outside, on a sample, with the judge itself tested.** A sealed-packet panel of at least three reviewers from a different vendor than the drafter, run offline across performance tiers and model combinations, reporting per-stratum numbers that count for nothing until a positive control proves the panel catches planted defects (charter Principle V, §10.2).
9. **No dependency on human-authored referee data.** The phase builds, runs, gates, and measures end to end with no academic in the loop, permanently (§9).

---

## 3. Non-goals

Each is excluded deliberately; documenting them protects the architecture.

1. **Phase C never runs Phase B.** It is a consumer of analysis records. A paper brief naming a brief that has not been run is an intake error, and the operator runs that brief through Phase B first. This is deliberate: it preserves PHASE-B non-goal 6 (no multi-brief orchestration) rather than smuggling brief-sweeping in behind an authorship command.

   > **CORRECTED 2026-08-01 (issue #570).** This non-goal is about running the Phase-B *pipeline* -- interrogation, the agentic retrieval loop, synthesis -- and it still holds exactly as written; nothing here reopens it. It does **not** mean Phase C never calls the vault. The opposition gap-and-repair pass (§7.15) calls `axial.query.names.who_argues_against`, the same read-only, deterministic query API Phase B's own tools are built from, directly and only when a gap is found. That is retrieval without a Phase-B run: no interrogation, no retrieval loop, no synthesis call, and no analysis record is produced or touched. The founder considered and rejected the alternative (commissioning a bounded Phase B run and joining its record into the input list) specifically to keep this non-goal true in the stronger sense -- see §7.15.
2. **No format adaptation.** Venue conventions, house style, and length targets are **Phase D**. v0 renders one plain markdown paper.
3. **No citation style.** The apparatus is mechanical: markers that resolve, and a bibliography from recorded metadata. Chicago, APA, footnote-vs-endnote, and short-form subsequent citations are Phase D.
4. **No new speculation.** Phase C emits no new kind-(c) claims in v0. A (c) claim already present in a source record may be carried, marked, and cited; the drafter does not invent new ones. A paper's speculative conclusion is a real want and is P2, not v0.
5. **No corpus, schema, vault, or analysis-record modification.** Phase C reads `data/analyses/`, `data/source_meta/`, and the vault read-only, and writes only its own artifacts. A Phase-C run never writes to `data/analyses/`.

   > **CORRECTED 2026-08-01 (issue #570).** "The vault read-only" now includes the name layer (`data/names/`), reached through the same read-only query API §7.15's gap-and-repair pass calls. Nothing here writes to the vault, the name layer, or any analysis record; the pass's own output lands only in the paper record it is building.
6. **No UI beyond the CLI.**
7. **No human referee.** No file, gate, or acceptance criterion in this phase may depend on academic-authored data (§9).
8. **No multi-paper orchestration or batching** in the authorship pipeline, beyond running one paper brief and inspecting it. The offline eval track (§10.2) reads a set of already-written papers, which is not orchestration: it produces no papers of its own.
9. **No per-run coherence gating.** No paper waits on a reviewer panel to be released. The four per-run gates (§10.1) are cheap and run on every paper; the coherence panel (§10.2) is an offline measuring instrument over a sample, and it blocks nothing.
10. **No adjudication between contradictory source records.** Phase C does not decide which of two opposing records is right, and does not reconcile them. It carries both, identifies their sources, and holds the result to charter Principle IV (§7.14).

---

## 4. Architecture principle

**The paper is assembled from settled claims; the system is measured by strangers.**

Two halves, and the split is the whole design. Note which noun each half takes: the *paper* is what gets assembled and gated, and the *system* is what gets measured.

**Assembly is bounded by an existing inventory.** Every claim the paper cites is either carried verbatim from a Phase-B analysis record, with its kind, grounds, and band intact, or is a new (b) claim that reasons across at least two claims drawn from at least two distinct records. The drafter cannot introduce evidence, because it has no path to any. It has no retrieval tools and no vault access: the claim inventory is the whole world. This is generate-then-cite made structurally impossible rather than forbidden by instruction, which is the same move Phase B made at the tool-dispatch seam (PHASE-B §4).

**The inventory bounds what may be cited; the plan bounds what is read.** Phase B measured that roughly twenty notes reach the synthesis model however much retrieval gathers — 62% more evidence assembled between two runs put *exactly* the same 127 notes in front of a model, and no retrieval change v1 made moved it (PHASE-B P2-7, issues #505 and #545). A claim inventory across three analysis records runs to 40–70 claims plus their grounds, so handing the drafter all of it in one call would reproduce that failure one layer up: a prompt whose tail the model never reads, with no way to know which claims fell off the end. **The drafter is therefore called once per section, over that section's `assigned_claims` and nothing else** (§7.2). The plan is what makes that possible, and this is the second reason to plan the arc before writing a word of it.

**Judgment of the whole comes from outside, and it comes on a sample.** Every property that is cheap to check is checked on every paper: marker resolution, grounds resolution, band non-escalation, counter-position presence on a contested paper, bibliography completeness, and two narrow judged checks over the new (b) claims. The one property none of those reach is whether the argument holds together. That property is **measured, not gated**. A panel that never saw the repo, the specs, the prompts, or any seeded data reads a sample of finished papers, receives only the paper plus the evidence it cites, and reports how coherent the system's output is, broken out by performance tier and model combination. The panel's isolation is enforced by the harness that constructs its calls, not by anything written in its prompt: a model with file tools reads the repository regardless of what its instructions say. Isolation you ask for is not isolation.

The two halves run on different clocks, and that is deliberate. Release is a per-paper decision and must stay cheap. Accuracy is a property of the system and only appears across many papers, several tiers, and more than one model combination. Collapsing the second into the first would make every paper pay for a measurement that a single paper cannot produce.

Like every phase beneath it, the mechanism is domain-general and the content is data. No country-specific or venue-specific logic lives in `src/`.

---

## 5. System overview — the stages

**Five pipeline stages, plus one gap-and-repair pass between the first two**, each independently testable. Stages 1, 4, and 5 are deterministic and make zero model calls; so is the pass between 1 and 2 (§7.15). The coherence eval track is not a pipeline stage and is specified in §10.2.

**Stages 2 through 5 are the prose layer, and they are built here** (the 2026-08-01 ruling as revised, §0). Every one of them takes a **list** of analysis records, and a list of one is an ordinary input rather than a special case — that signature is what keeps the machinery from being written a second time if Phase B later renders its own answers through it. Phase B is not reopened to do that now.

**Stage 1 is the one stage a single-record caller would not need**: resolving several records to one pin, rejecting a refusal or a mixed-pin set, and building an inventory keyed by `(brief_id, claim_id)` are questions a single answer never asks. Everything downstream of it reads the inventory and does not care how many records fed it.

1. **Paper-brief intake (deterministic).** Reads the paper brief (§7.1), resolves every named analysis record, verifies they share one `corpus_pin`, and rejects a brief naming a missing record, a refused record, or a mixed-pin set. Builds the **claim inventory**: every claim across every named record, keyed by `(brief_id, claim_id)`.

**Stage 1.5: the opposition gap-and-repair pass (deterministic query calls, zero model calls; §7.15, issue #570).** Over every name the claim inventory touches, checks whether `who_argues_against` returns opposing material none of the named source records already read, and — only where that gap is non-zero — shapes what comes back into ordinary kind-(a) claims added to the inventory before planning starts. This is retrieval, but it is not Phase B: no interrogation, no agentic loop, no synthesis call, no analysis record. Most runs find nothing here and pay for nothing beyond the lookup (§7.15).

2. **Arc planning (model).** Emits the **paper plan** (§7.2): an ordered list of sections, each with a heading, an argumentative role, and the inventory claims assigned to it — including, where the gap fired, any repair claim stage 1.5 added. No prose is written at this stage, and the plan is inspectable before any drafting call is paid for.
3. **Drafting (model, high tier + reasoning).** Writes the paper section by section from the plan, emitting prose with in-text citation markers and any new (b) claims it needs to relate material across records. **One call per section.** Each call sees the thesis, the plan, that section's `assigned_claims`, and a running list of what earlier sections already cited — `paper_claim_id`, kind, band and text, never grounds text — so a new (b) claim can still reach back across sections and therefore across records (§4, §7.2). It never sees the whole inventory, and it has no tools.
4. **Claim assembly & citation indexing (deterministic).** Parses the drafted prose for markers, builds the citation index (§7.5), and assembles the record's `claims` list as exactly the claims cited. A marker naming an unknown claim is a hard failure here.
5. **Apparatus & rendering (deterministic).** Generates the bibliography from `data/source_meta/` for exactly the cited sources (§7.6), renders the markdown paper (§7.10), and writes the paper record (§7.3).

The pipeline ends here. A paper is releasable once the four per-run gates of §10.1 pass over its record, and none of them calls a reviewer. **Off the pipeline**, on its own cadence, sits the coherence eval track (§10.2): sealed-packet assembly (§7.7), the reviewer panel (§7.8), and the positive control that qualifies the panel before any of its numbers are trusted (§7.9), run over a stratified sample of already-written papers (§7.13).

---

## 6. Repository structure

Scaffold to this shape; adjust only with reason. Extends the Phase-A (`PRODUCT.md` §6) and Phase-B (`PHASE-B.md` §6) layouts; existing modules are unchanged.

```
src/axial/
  paper/        # all five stages: paper-brief intake, record resolution, the
                # claim inventory, arc plan, draft, citation index,
                # bibliography, render, the paper record and its persistence.
                # Stages 2-5 take a LIST of analysis records and a list of one
                # is not a special case, so Phase B can later render through
                # them without any of this being rewritten (§0, §5).
  panel/        # EXISTING (PHASE-B §9.4, issue #385): the OFFLINE coherence
                # eval track (§10.2) -- packet, vendor, review, control, run.
                # Phase C adds a paper-shaped packet builder and two finding
                # kinds here. It does not build a panel. Never on the per-run
                # pipeline path.
  gates/        # (existing) + the provenance-integrity gate (§10.1)
config/
  paper_briefs/
    dev/        # versioned dev paper briefs, driving every dry-run
evals/
  samples/      # coherence sample specs (§7.13): strata + paper ids only
data/
  papers/       # one paper record JSON + one rendered .md per run
tests/
```

`data/` is gitignored in full (DEC-23). `evals/samples/` is committed and must stay content-free: strata and ids, never prose and never chunk text (§7.13).

> **CORRECTED 2026-08-01. There is no `src/axial/review/`, and Phase C must not create one.** This section originally scaffolded the whole eval track as new Phase-C code, and named `evals/plants/` as its plant-spec directory. Both were written before Phase B built the instrument. `src/axial/panel/` now exists and has run twice (`data/logs/2026-07-31-panel-smoke-v4/`, `data/logs/2026-07-31-smoke-v5/`): `packet` (assembly and the content half of the seal), `vendor` (the training-lab table, unknown id is a hard error), `review` (N ≥ 3 dispatch, structured verdicts, the spread), `control` (the three plants and the trust condition), `run` (control first). The three plants are implemented as **in-code record mutations**, not as committed spec files, so `evals/plants/` was never built and is not needed — the content-free requirement DEC-23 imposed on it is satisfied more strongly by code that writes no prose at all. What Phase C adds is listed at §7.7–§7.9, and it is small.

The `paper/` and `panel/` split is load-bearing rather than cosmetic. Nothing under `paper/` may import from `panel/`, so the authorship pipeline cannot acquire a dependency on the panel, which is what keeps §3 non-goal 9 true by construction instead of by discipline. The dependency runs the other way: `panel/` learns to read a paper record, and the pipeline never learns that a panel exists.

---

## 7. Data & configuration contracts

### 7.1 The paper brief (input contract) **[FIRM]**

The phase's input, supplied as a versioned file. Shape:
`{paper_brief_id, thesis, analysis_ids[], lens?, title?}`.

- `lens` — optional named lens from `config/lenses/`, inheriting PHASE-B §7.1's contract unchanged: the key is optional, its value is not, a present lens must be a non-empty string, and omitting the key is the only way to ask the stage to choose and record its choice. **The lens is the register the paper's argument is made in** (§0), which is why a paper carries its own rather than inheriting one. A paper drawn from records analysed under *different* lenses is normal and is not an intake rejection; the source records' lenses are disclosed on the record (§7.3), because "these three analyses were read through different lenses" is a fact about the paper's foundations that a reader is owed.

- `thesis` — the paper's organizing question, free text. Required, non-empty after whitespace stripping.
- `analysis_ids` — a list of Phase-B `brief_id` values naming records under `data/analyses/`. Required and non-empty. Every id must resolve to an existing record; an unresolvable id is rejected at intake, naming the id, and **Phase C never runs Phase B to produce it** (§3 non-goal 1).
- `title` — optional working title for the rendered paper. When absent, the renderer uses the thesis.
- `paper_brief_id` — a stable, deterministic id over the brief's content, no randomness and no timestamps, so re-running the same paper brief is traceable.

Two intake rules, both mechanical and both blocking:

- **Pin agreement.** Every named record must carry the same `corpus_pin` (PHASE-B §7.12). A mixed-pin set is rejected, naming the disagreeing ids. Records produced against different corpora are not comparable, so a paper across them is not defensible.

  **This bites harder than it used to, and that is correct.** Phase B v1 re-cut the pin (D6): its vault snapshot hash now covers the prose note ids **and the name layer** — `index.json`'s canonical name set, the alias map version, and the disagreement count (PHASE-B §7.12). A Gather run, a name merge, or a materialize that changes which pages exist all move the pin, because all three change what retrieval can reach. So analysis records straddling one of those runs will not share a pin, and a paper across them is rejected. The operational consequence is a real constraint on the operator, stated rather than discovered: **run every brief a paper will draw on inside one pin window.** Re-running a stale brief is cheap; a paper over two corpora is not defensible at any price.
- **No refusals.** A named record whose `interrogation.disposition` is `refuse` is rejected, naming the id. A refusal is a valid Phase-B outcome and a completed run; it is not material for a paper, because it carries no claims.

> **A third rule, schema agreement, was struck (issue #524).** It required every named record to carry the same `schema_version`. That field was cut from the Phase-B record because it was read off a note field zero live prose notes carry, so every record wrote `null` (PHASE-B §7.3). Pin agreement already subsumes it and is strictly stronger: a `corpus_pin` resolves to a manifest carrying `vault_snapshot_hash`, an exact content hash of the vault, so two records sharing a pin were produced against a byte-identical vault. DEC-45 names this rejection in passing among the existing three; its own substance — that contradiction is never an intake rejection — is untouched.

**Records that contradict each other are not rejected, and this is not an omission from that list.** Two named records arguing opposite sides of a question are opposing arguments, which is the substance of the domain, not a defect in the input. Contradiction is handled by charter Principle IV at paper scale (§7.14), never at the intake gate. Nothing may be added to the three rejections above on the grounds that two records disagree.

The **claim inventory** is the union of `claims` across the named records, keyed by `(brief_id, claim_id)`. It is the drafter's entire world.

### 7.2 The paper plan (the narrative arc) **[FIRM]**

Emitted by stage 2 and persisted into the paper record. The arc is planned before any prose exists, which is what makes the paper assembled rather than back-fitted.

```
plan: {
  thesis_statement,                 # the thesis as the paper will state it
  sections: [ {
    section_id,                     # stable, deterministic within a run
    heading,
    role,                           # see below
    assigned_claims: [ {brief_id, claim_id} ]
  } ]
}
```

`role` is exactly one of `setup`, `claim`, `evidence`, `counter-position`, `synthesis`.

> **CORRECTED 2026-08-01. The vocabulary stands; the reason given for it does not.** This paragraph justified the five values as "reused unchanged from the Phase-A `role_in_argument` axis (PRODUCT.md Appendix F)", on the grounds that "the substrate already tags chunks by argumentative move". Phase A v1 deleted that axis along with `field`, `claim_type` and `theory_school`; 0 of the ~6,100 live prose notes carry it, which is why `query_by_tag` returned zero on every axis and Phase B v1 exists. What survives in Appendix F is the value list as **examples for the free-text `move` answer** the interrogation writes, which is a different thing: a vocabulary a model is shown, not a facet anything can filter on. So these five words are a good vocabulary for a paper's sections, and Phase C is simply choosing them. It cannot claim they align a paper's sections with a tag on the chunks beneath, because there is no such tag.

Two mechanical constraints on a valid plan:

- **Order is meaningful.** `sections` is an ordered list, and the rendered paper follows it exactly. Rendering never reorders.
- **Counter-position presence.** At least one section carries `role: counter-position`, unless **every** named source record discloses `counter_position.corpus_one_sided: true` (PHASE-B §7.8), in which case the plan carries no counter-position section and the paper must render the one-sided disclosure instead. **A record whose counter-position section is `failed` does not count as disclosing one-sidedness** (§7.3): that is a run that died, not a corpus that had one side, and it must not be allowed to waive a counter-position section. Neither present is a red flag, not a clean result (charter Principle IV), and fails intake of the plan. This is a cheap plan-time guard read off the source records alone; the authoritative check is the post-draft counter-position gate (§7.14, §10.1), which sees what the paper actually cited.

A section may carry an empty `assigned_claims` list only when its role is `setup`. Every other section must carry at least one.

**`assigned_claims` is the drafting unit, not merely a plan annotation (§4).** The drafter is called once per section over that section's list, so the planner is deciding what each drafting call gets to see. Two consequences, both intended. A claim assigned nowhere is a claim no drafting call can cite, which is the planner's decision to make and is visible in the plan before a drafting dollar is spent. And a section assigned thirty claims is a section whose tail the model will not read (PHASE-B P2-7) — **the plan is where that is caught**, by an operator reading `examine` output, not by a gate. No cap is specified here: the number that matters is claims-plus-grounds characters against the drafting model's real attention, nobody has measured it for this pass, and a fitted constant would be the tripwire. State the exposure, measure it on the first real papers, then set it if it needs setting.

### 7.3 The paper record (output contract) — the load-bearing artifact **[FIRM]**

One JSON per run at `data/papers/<paper_brief_id>.json`, the phase's analogue of the Phase-B analysis record. Shape is locked; no field is nullable except where stated.

```
{
  paper_brief_id, paper_brief,       # the brief (§7.1), verbatim
  corpus_pin,                        # the single shared pin of the source records
  lens,                              # the lens applied, always recorded (§7.1)
  source_lenses: { brief_id: lens }, # what each source record was read through
  source_analyses: [ brief_id ],     # the records drawn on, in brief order
  plan,                              # the arc (§7.2)
  claims: [ <paper_claim> ],         # §7.4; exactly the claims cited in the prose
  citations: [ <citation> ],         # §7.5, in document order
  counter_position,                  # the PHASE-B §7.8 shape, reused unchanged (§7.14)
  coverage_map,                      # §7.11's CARRIED scope, from the named source records
  coverage_map_earned,               # §7.11's EARNED scope, from the pass below (§7.15)
  trajectory,                        # §7.15's own retrieval log, PHASE-B §7.6 shape -- NEW
  exact_match_opposition_gap,        # §7.15's gap record -- NEW
  confidence: { overall_band, rationale },
  bibliography: [ <bib_entry> ],     # §7.6
  paper_markdown_path,               # the rendered paper written alongside
  model_by_pass,
  cost                               # per-pass tokens + dollars, PHASE-B §7.14 shape
}
```

`counter_position` reuses the PHASE-B §7.8 shape unchanged: `{present, stance, grounds[], corpus_one_sided, one_sided_reason}`, **plus the two additive fields PR #558 introduced, `failed` and `failure_reason`**. It is never absent, and it now carries three states rather than two: the counter-position material carried into the paper, naming the section that states it and the source claims it is built from; the explicit one-sided disclosure, carrying the source records that reported it; or a **failure**, where the section could not be produced. Where the named source records themselves argue opposite sides, this is the field that carries the opposition into the paper (§7.14).

> **CORRECTED 2026-08-01.** This paragraph said the field had exactly two states. Phase B v1 added the third and the reason it added it binds here identically: a run that died in its closing stage used to be indistinguishable from a corpus that had only one side, so **a bug could read as a finding about the corpus**. A failed counter-position is a failed run — it persists the record with the section marked failed, and it fails the validator, the gate, and the exit code. It is never `corpus_one_sided`, and Phase C must not collapse the two when it carries the field forward.

> **CORRECTED 2026-08-01, twice in one day (issue #570).** This section said the paper record carries no `trajectory` "deliberately", because "Phase C performs no retrieval, so it has nothing to record." **The founder is amending that, explicitly, and this build makes the change rather than designing around it.** Phase C now retrieves directly through the deterministic query API, targeted and bounded, only to repair a found opposition gap (§7.15) — never through Phase B's interrogation, agentic loop or synthesis. Because that retrieval is real, it is now auditable: `trajectory` carries it, in the exact PHASE-B §7.6 shape (`{step, tool, args, result_ids[], result_count, total, detail}`), empty when the gap was zero everywhere. A retrieval nobody can inspect is the one thing this product has never shipped, and that did not stop being true just because the retrieving layer changed. `exact_match_opposition_gap` is the companion field: the gap as found and what got repaired, both counted before and after restriction to what the paper actually cites (§7.15's own disclosure discipline) — never a clean zero presented as though nothing needed repairing.

`confidence.overall_band` is one of `high` / `medium` / `low` and may not exceed the **lowest** overall band among the named source records **or**, when the paper cites a repair claim, the lowest band the earned coverage (§7.11, §7.15) supports.  `confidence.rationale` states the coverage counts behind it, drawn from `coverage_map`.

The record is the audit surface. Every cited sentence traces to a claim, every claim traces to grounds, every grounds pointer resolves to a real vault id, and every cited source appears in the bibliography.

### 7.4 The paper claim (carried vs. new) **[FIRM]**

Two kinds of entry, distinguished by `origin`.

```
{
  paper_claim_id,                    # stable, deterministic within a run
  text,
  kind,                              # a | b | c, per charter Principle II
  origin,                            # {brief_id, claim_id} for carried; null for new
  grounds: [ {ref_type, ref_id} ],
  confidence,                        # high | medium | low; the CLAMPED band (below)
  names_touched: [ canonical_name ], # carried from origin; unioned for a new (b) claim
  derived_from: [ paper_claim_id ]   # non-empty only for a new (b) claim
}
```

`names_touched` is added by this revision (2026-08-01) and is not decorative: it is what lets §7.11 compute the paper's coverage map with **zero vault reads**, and it is free — every Phase-B claim already carries it (PHASE-B §7.4), resolved through the alias map alone rather than through `find_names`' embedding tier, because a nearest-neighbour hit would land a claim on a plausible neighbouring name and fabricate coverage the corpus does not have.

**A "source record" is not only a named Phase-B analysis record (issue #570).** The opposition gap-and-repair pass (§7.15) injects its own repair claims into the intake inventory as though they came from one extra record, so `origin` can also name that pass's own synthetic `brief_id`. A repair claim is still, in every other respect, an ordinary carried (a) claim: same shape, same clamp, same gates. §7.15 is where this is specified in full; nothing below in this section needs to distinguish the two cases.

**A carried claim** is copied from the inventory with `kind`, `grounds`, and `confidence` **byte-identical** to the source record's claim — where `confidence` means the claim's **clamped** band, which is not the band the record persisted; see the confidence ceiling below — and `origin` naming where it came from. Its `text` may be re-worded for the paper's prose, but a re-worded carried (a) claim is still kind `a` and still carries its origin. **Phase C never restates an (a) claim as its own** (charter Principle II): re-voicing a source's assertion as the tool's inference is the laundering failure this phase exists to prevent.

**A new (b) claim** is Phase C's own contribution. It carries `kind: b`, `origin: null`, non-empty `grounds`, and a `derived_from` list of at least two `paper_claim_id`s that between them come from **at least two distinct `brief_id`s**. That is what makes it cross-source rather than a restatement, and it is mechanically checkable. Its `grounds` are the union of the grounds of the claims it derives from, so it points at real vault ids without the drafter ever touching the vault.

**No new (c) claims** in v0 (§3 non-goal 4). A carried (c) claim keeps `kind: c` and its origin.

**A new (b) claim may characterise a disagreement between source records, and may not settle it.** Where two named records argue opposite sides, a claim that names the disagreement, locates it, or says what the two positions turn on is genuine cross-source synthesis, and it is arguably the best contribution a paper built this way can make. What it may not do is declare a winner beyond what its grounds support. "Record A's position rests on evidence B's does not engage" is a claim with grounds. "Record A is correct" is a verdict, and no grounds in the inventory carry it. The distinction is the ordinary one every (b) claim already faces, and it is enforced by the same two gates: grounding of new (b) claims, and the (b)-seam mislabel check (§10.1). Both sides of the disagreement survive into the paper regardless, each carrying its `origin` (§7.14).

**The confidence ceiling.** Bands are ordered `low < medium < high`.

- A carried claim's band equals **its origin's clamped band**. Not higher, and not lower either: silently downgrading is its own dishonesty.
- A new (b) claim's band is at most the **minimum** clamped band among its `derived_from` claims. A synthesis is no stronger than the weakest thing holding it up.

Both rules are mechanical, both are hard, and a violation of either fails the provenance-integrity gate outright (§10.1).

**Which band a Phase-B claim's band actually is [CORRECTED 2026-08-01].** This section originally said "the origin's band" and left it there, because when it was written a claim had one. It now has two. PHASE-B §7.4, as amended by issue #550, derives per claim the coverage band of the names its own grounds touch and **clamps the band it renders** to that ceiling, while the persisted claim keeps the model's own emitted band unchanged. The two disagree often, not rarely: **93 of 121 claims across the six smoke-v5 records — 77% — were clamped**, and the per-claim rule clamped 55 of 112 in the round before it where the coarser run-level band clamped 103 of 112 and discriminated nothing.

So "copy the origin's `confidence` field" is a live defect, not a wording quibble. It would lift the unclamped band out of the record, drop it into a paper, and render it beside the paper's own coverage counts — reintroducing **confidence inflation across a layer boundary**, which §1 names as one of the four failure modes this phase exists to prevent, by the exact mechanism §1 describes: the band survives the copy, and the check that used to hold it down does not.

**The rule, stated once.** A carried claim's band is the band Phase B would render for it, computed by re-running PHASE-B §7.9's per-claim clamp against the source record's own coverage map. The paper record persists that band and nothing else; the unclamped one is not carried, not stored, and not rendered. A new (b) claim's ceiling is the minimum over its `derived_from` claims' clamped bands, so the clamp composes upward instead of being re-derived at paper scale over a coverage map that means something different (§7.11).

### 7.5 Citation markers and the citation index **[FIRM]**

**One plain format.** A citation marker is the literal token `[<paper_claim_id>]` placed at the end of the sentence it supports. Multiple markers adjoin with no separator: `[pc-004][pc-011]`. Nothing else in the rendered paper uses square-bracket tokens, so the format is unambiguously parseable.

A **citation-bearing sentence** is a sentence carrying at least one marker.

The citation index is built deterministically in stage 4 by parsing the drafted prose:

```
citations: [ {section_id, sentence_index, paper_claim_id} ]
```

one entry per marker occurrence, in document order.

Three rules, all mechanical and all blocking:

- **Every marker resolves** to a `paper_claim_id` present in `claims`.
- **The record's `claims` list is exactly the set of cited claims.** A claim assigned in the plan but never cited in the prose is dropped at persistence, not carried as an orphan.
- **Every claim's grounds resolve** to real vault ids through the Phase-B query API (`get_chunk` / `get_artifact`). A well-formed pointer to an id the vault does not contain is a failure, not a shape check.

The rendered paper carries a **citation table** (§7.10) that makes the whole chain readable on the page: claim id, kind, band, grounds chunk ids, and the bibliography entry for each grounds source. That is the `claim_id -> chunk_id -> source` resolution made visible rather than merely computable.

### 7.6 The bibliography **[FIRM]**

Generated deterministically, with no model call, from `data/source_meta/<source_id>.json` (PRODUCT.md §7.12, §7.13), for **exactly the sources cited**: the set of `source_id`s reachable from the grounds of the record's claims. A source that appears in a named analysis record but is never cited in this paper does not appear.

```
bibliography: [ {
  source_id,
  author, title, date, publisher,   # each: {value, provenance} or a stated absence
} ]
```

Three rules follow directly from PRODUCT.md §7.13 and are load-bearing here:

- **An absent field renders as a stated absence, never a blank and never a guess.** The source-metadata record distinguishes a value, `unavailable` (a read was attempted and found nothing), and `not attempted` (no read has run). The bibliography renders those as distinct, visible markers. A wrong value that looks right is more dangerous than an honest gap.
- **The filename is never a source for any of these fields.** Not for title, not for author, not for date, not for publisher.
- **Provenance travels with the value.** Where a field came from the embedded metadata, the title page, or an identifier lookup, the rendered bibliography says so.

Ordering is deterministic: by author surname where an author is known, then by title, then by `source_id` as the final tiebreak, so the same record always renders the same bibliography.

The bibliography carries **no source text** and no verbatim excerpts (DEC-23). It is metadata only.

### 7.7 The reviewer packet (sealed) **[FIRM]**

The panel's entire input. Assembled at runtime, in memory, per reviewer, **during an offline eval run only** (§10.2). No packet is ever assembled on the per-run authorship path.

```
packet: {
  packet_id,
  paper_markdown,                    # the rendered paper (§7.10), verbatim
  cited_evidence: [ {
    paper_claim_id, kind, confidence,
    grounds: [ {ref_id, text} ]      # the resolved chunk/artifact text
  } ],
  bibliography
}
```

**Nothing else.** No paper brief, no plan, no source analysis records, no coverage map internals, no spec text, no prompt history, no gate configuration, no other reviewer's verdict.

Four enforcement rules, all FIRM and all enforced by the harness rather than by prompt text. **All four are already implemented in `src/axial/panel/`** (PHASE-B §9.4, issue #385); what follows records what each one is, and where Phase C's obligation is nothing more than pointing the existing code at a paper record.

- **No tools.** *Implemented, and structurally rather than by check.* Reviewers dispatch through `complete_json`, the plain completion seam, which **has no `tools` parameter to pass** — a reviewer cannot be handed a tool registry even by mistake. This is stronger than what this section originally specified ("the harness rejects a configuration carrying a non-empty tool list"), which was a guard that could be forgotten. A reviewer must never be routed through `complete_with_tools`.
- **Different vendor.** *Implemented in `axial.panel.vendor`.* Each reviewer's model must resolve to a different **vendor** than every model that generated the paper (`model_by_pass`). Vendor means the **lab that trained the model**, never the API provider that serves it: OpenRouter serves everything, so provider identity is not separation. The mapping is a static in-code table in the same spirit as `axial.llm.PRICE_TABLE_USD_PER_1K`. **A model id absent from the table is a hard error, never assumed distinct**, and the check runs before any reviewer call. Phase C's only obligation is to hand the guard its own generating models: the drafting and arc-planning passes, read off the paper record's `model_by_pass`.
- **N >= 3, independent.** *Implemented as `MIN_REVIEWERS = 3` in `axial.panel.review`, enforced at dispatch.* No reviewer sees another's packet, verdict, or existence. See §9 for what has actually been run against it, which is not three.
- **Packets are never written at all.** *Implemented: `build_packet` returns a packet in memory and no function writes one to disk.* This section originally required packets to be written under a gitignored `data/packets/`; the implementation is stricter and better, so `data/packets/` is struck from §6. `assert_sealed` additionally refuses a packet carrying a repository path, which is the content half of the seal. A packet holds verbatim chunk text from copyrighted books (DEC-23).

**What Phase C actually adds, and it is the whole list.** A `build_paper_packet` beside the existing analysis-record one, assembling the §7.7 shape from a paper record; the two extra finding kinds of §7.8; and the sample spec of §7.13. Everything else is a call site.

**Why the vendor bar is stricter here than elsewhere.** The Phase-B grounding and attribution judges run under a different-model guard, not a different-vendor one, and that stays as it is. Those judges answer a narrow question against pinned text: does this passage support this sentence. The coherence judgment is open-ended and stylistic, and shared training priors survive within a model family. A sibling model finds the same arguments persuasive for the same reasons.

### 7.8 The reviewer verdict **[FIRM]**

Structured, never free prose. One per reviewer.

**The shape is the implemented one, extended by one dimension and two defect kinds [CORRECTED 2026-08-01].** This section originally specified a Phase-C-only verdict with its own `coherence_verdict` field and its own five-value `finding_kind` vocabulary. `axial.panel.review` already parses, validates and aggregates a verdict, and the positive control already matches its plants against that vocabulary by name. A second shape would mean a second parser, a second aggregator and a second control for one added question. So Phase C **extends** rather than replaces:

```
{
  reviewer_id, model, vendor,
  dimensions: {                      # each: weak | adequate | strong
    factual_correctness,             # existing
    citation_grounding,              # existing
    completeness,                    # existing
    coherence                        # NEW, paper packets only
  },
  defects: [ {
    defect_kind,
    section_id,                      # nullable, NEW -- an analysis has no sections
    claim_id,                        # nullable (a paper_claim_id here)
    note                             # one sentence, the reviewer's reason
  } ]
}
```

`coherence` is the one dimension the per-run gates cannot reach, and it is the reason a paper is packeted at all: whether the argument holds together over the evidence shown. It takes the existing three-band ordinal rather than a fourth vocabulary — `strong` / `adequate` / `weak` are exactly the `coherent` / `coherent_with_reservations` / `incoherent` this section first proposed, under names the code already carries.

`defect_kind` stays the implemented closed vocabulary, **extended by two and renaming nothing**: `mis_grounded`, `strawman_counter_position`, `overconfident`, `other`, plus `arc_break` (a section does not follow from the argument before it) and `unmarked_inference` (a cross-source inference presented as though a source asserted it). The first two of the original five were renames of implemented kinds — `unsupported_claim` for `mis_grounded`, `overconfident_band` for `overconfident` — and renaming them would break the positive control, which matches a plant's kind against a defect's kind by string. An out-of-vocabulary kind is a load error, never silently accepted.

**Per-reviewer coherence score:** `strong` = 1.0, `adequate` = 0.5, `weak` = 0.0. The eval report carries the mean across reviewers **and the spread** (§10.2), where spread is the existing ordinal distance `max − min`. A single judge draw is a single draw.

A verdict belongs to the measurement run that produced it and to that run's frame (§7.13). It is never written back into the paper record (§7.3), and no paper record carries a field for it. A paper is not a thing that has a verdict; a measurement run over a sample of papers is.

### 7.9 The positive control (mandatory) **[FIRM]**

LLM judges are systematically generous, and they are sensitive to confident prose. A panel that never fails anything is indistinguishable from a panel that stopped reading. **No coherence number from §7.8 is trusted until the panel has caught deliberately planted defects at the current configuration.**

**Plants are transformations, never content**, and the three that exist are the three Phase C uses. `axial.panel.control` implements them as deterministic in-code mutations of a real record, driven by selectors over what the record already holds. Nothing writes prose, invents a claim, or embeds chunk text — which satisfies DEC-23 more strongly than the committed plant-spec files this section originally called for, and is why `evals/plants/` was struck from §6.

1. **Mis-grounded claim** (`mis_grounded`). A claim's grounds are repointed at another claim's evidence, so it cites material that does not support it, with every pointer still resolving.
2. **Strawman counter-position** (`strawman_counter_position`). The counter-position is repointed at the primary claim's own grounds, so the "opposition" rests on the very material it supposedly opposes — a strawman by construction rather than by rewriting.
3. **Overconfident band** (`overconfident`). A claim over a **name** the coverage map discloses as thin is raised to the `high` band.

> **CORRECTED 2026-08-01, twice.** Plant 3 read "the thinnest **polity** in `coverage_map`". Coverage is per-name since Phase B v1 (D2, §7.11); a polity is now just a name whose kind is a place, and the implemented plant already selects on the `thin`/`none` coverage bands rather than on any polity. Separately, plants 1 and 2 were specified here as different mutations than the ones built — a `text` swap between claims with disjoint source sets, and a lowest-band-claim replacement. There is no reason to hold two definitions of the same three defects. The implemented mutations are the contract.

**A plant that cannot be applied is an error, never a skip** (`PlantNotApplicableError`). A control that quietly plants two defects instead of three and then passes is worse than no control. For Phase C this has a concrete consequence: the control paper must be one that can carry all three, so it needs a present-with-grounds counter-position and at least one thinly-covered name. Choosing a control paper that cannot carry a plant is an operator error the harness refuses to absorb.

**Scoring.** Each planted variant is rendered and packeted exactly as a real paper is, and the same panel runs over it. A plant is **caught** when a **strict majority** of reviewers — `caught_by > N/2`, which is `ceil(N/2)` at odd N and stricter at even N — return a defect whose kind matches the plant's and whose `claim_id` or `section_id` points at the mutated target. `positive_control_catch_rate` = plants caught / plants planted.

**The trust rule, mechanically enforced.** The **coherence eval report** (§10.2) carries `trusted: false` unless the positive control has been run against the same panel configuration (same reviewer models, same N) and passed. The untrustworthiness here is about the judge, not the corpus and not the paper.

This rule binds the eval report and nothing else. **No per-run gate report (§10.1) has a trust field that a panel could fill**, so no paper is ever held back, and no gate is ever reported untrusted, for want of a reviewer verdict. A report that named a missing panel verdict as its reason for being untrusted would be wrong by construction, because the panel is not on that path at all.

### 7.10 The rendered paper **[FIRM]**

Plain markdown at `data/papers/<paper_brief_id>.md`, rendered deterministically from the record. The same record renders the same markdown, byte for byte.

Contents, in order: title, thesis statement, the plan's sections in plan order with their prose and in-text markers, the counter-position section (or the one-sided disclosure), the confidence and coverage disclosure, the citation table, and the bibliography.

Two rules carried forward from the layer beneath, restated here because they bind on this artifact:

- **Every confidence band renders next to the counts that justify it** (PHASE-B §7.4, §7.10). A band rendered bare is a rendering failure.
- **Claim kind is legible.** Every entry in the citation table carries its claim's kind, so a reader can see which claims a source made and which the tool made. In the prose itself, the seam is carried by voice: a new (b) claim is written in the tool's own register and is never attributed to a source ("Smith argues" is available only to a carried (a) claim). Attribution-marker clutter in every sentence is not the mechanism; the citation table plus honest voicing is.

This is plain rendering only. Venue, length, and house style are Phase D (§3).

### 7.11 The coverage map, carried and earned **[FIRM]**

Coverage is **per name**, not per polity. The paper's coverage is a **union of two scopes, kept in two separate fields rather than merged**: `coverage_map`, unioned from the named source records exactly as before, and `coverage_map_earned` (issue #570), computed natively over the opposition-repair pass's own retrieval trajectory (§7.15). Both are counts, never a model judgment.

> **CORRECTED 2026-08-01, and this is the one place the mechanism actually changed.** This section read: "the union of the source records' coverage maps over the **polities** the paper's cited claims touch, **recomputed** deterministically from the same `polities_touched` facet Phase B used." Every load-bearing noun in that sentence is now wrong. `polities_touched` was deleted by Phase A v1 — 0 of ~6,100 live prose notes carry it, the map it fed computed empty, and `confidence.overall_band` was pinned `low` by its own derivation rule. Phase B v1 replaced it with `names_touched` (D2): the map is keyed on canonical names, its denominator `corpus_note_count` is the name page's own `member_count`, and it covers concepts and scholars rather than only polities, which is strictly wider than what it replaces.
>
> **Recomputation is the part that cannot simply be renamed.** Phase B does not compute its map over every name a claim touches. A live note's `names` answer lists every person, place, date and organisation the passage mentions — median 21 per note — so a 24-note evidence set touches **423 distinct canonical names on average**, and keying on all of them gave a 423-row map and a constant `low` band on 10 of 10 sets at every cut point tried. Phase B's fix (slice 05, #490) keys the map on the names the answer is *about*: `coverage_scope(claims, trajectory)`, the intersection of the names **this run's own retrieval trajectory queried** with the names its claims touch. That intersection needs a trajectory.

> **CORRECTED AGAIN 2026-08-01, later the same day (issue #570) — this retracts the sentence above it, not just a wording choice.** This section used to continue: "**A paper record has none and never will** (§7.3): Phase C retrieves nothing. Calling `compute_coverage_map` on a paper record does not approximate the right answer — it returns `{}`." **The founder is amending that, deliberately, and this build does not design around it or treat it as a prohibition.** A paper record now has a trajectory: the opposition gap-and-repair pass (§7.15) retrieves directly through the deterministic query API, targeted and bounded, and logs it. So `compute_coverage_map` on that trajectory no longer returns `{}` — it returns exactly what it would for a real Phase-B analysis record, because it is the same function, called the same way. The reasoning this section used to give for "unioned, never recomputed" was reasoning **from the absence of a trajectory**; give the paper layer one and the reasoning no longer applies, for the part of the map that trajectory actually reached. It does not apply retroactively to the source records' own coverage, which is still unioned, never recomputed — a paper still cannot re-derive what a source record's own retrieval saw, only what its own did.

**So the paper's coverage is now two maps, and a reader must be able to tell them apart.** `coverage_map` (carried) is assembled from the maps that already exist: each named source record carries its own §7.7 map, computed under its own trajectory, at the same pin, and the paper's carried map is those maps restricted to the names the paper's **cited** claims touch. `coverage_map_earned` (earned) is `axial.validators.coverage.compute_coverage_map` run over the repair pass's own trajectory and its own cited claims — the identical Phase-B mechanism, not a re-implementation, so the two maps cannot silently drift into disagreeing about what "coverage" means. Both share one shape:

```
canonical_name -> {
  corpus_note_count,        # the name page's own member_count -- carried in coverage_map,
                             # read fresh through the query API in coverage_map_earned
  cited_claim_count,        # this paper's own numerator: cited claims touching this name
  coverage_band             # re-derived from corpus_note_count, PHASE-B §7.7's thresholds
}
```

**The two are never merged into one field, and never silently combined into one number.** Both are legitimate; a reader who cannot tell which coverage the paper *earned* itself and which it *inherited* from a source record is being told less than the record actually knows, which is exactly the failure this amendment exists to prevent. The rendered paper (§7.10) shows both, one row per name per scope, labelled.

Three rules bind `coverage_map`, the carried scope, all mechanical, all with zero vault reads and zero model calls:

- **The denominator is carried, never recomputed.** `corpus_note_count` comes from the source records' maps. Where two records disagree on a name's count, they were produced against the same pin (§7.1) and so cannot legitimately disagree: that is a hard error naming both records, not a value to average. A name the index carries and the vault holds no page for keeps `null`, never a fabricated `0`, and `null` reads `thin` — the most conservative band — with the `null` travelling beside it (PHASE-B §7.7).
- **The numerator is the paper's own, and it is claims rather than notes.** An analysis counts the evidence notes it assembled; a paper's unit is the cited claim, and reusing a source record's `evidence_note_count` would report evidence the analysis gathered as though the paper had used it. `cited_claim_count` is computed from §7.4's `names_touched`, which every paper claim carries: for a carried claim it is its origin's, and for a new (b) claim it is the union across its `derived_from` claims. That is what keeps this whole section free of vault access.
- **A name outside every source record's map is not in `coverage_map`.** It is out of scope by construction, exactly as it was one layer down. The carried map does not grow at paper scale.

`coverage_map_earned` inherits PHASE-B §7.7's own rules unchanged, because it is PHASE-B §7.7's own function: `corpus_note_count` is a real vault read (the query API, not a source record's say-so), `coverage_band` is the same threshold derivation, and its scope is `coverage_scope(claims, trajectory)` — the repair pass's own claims and its own trajectory, never the paper's carried claims or a source record's trajectory. A name the repair pass checked and found nothing usable for is not in it either (§7.15): the earned map only ever contains names a repair claim was actually built for and cited.

**Where this leaves the scope question.** The intersection Phase B computes, for its own map, is "retrieved on **and** claimed about". `coverage_map`'s is "in a source record's map **and** cited in this paper" — the same shape with the paper's own second term, and the first term inherited rather than re-derived; it is narrower than the source maps and never wider, which is the direction an honest disclosure should move when material is dropped on the way into a paper. `coverage_map_earned`'s is Phase B's own intersection, unmodified, over the repair pass's own retrieval — the one scope in this whole section that is not inherited from anywhere.

`confidence.overall_band` (§7.3, §7.4) is derived from `coverage_map` exactly as before, then held to the lowest of: the named source records' own overall bands, and — only when the paper cites a repair claim — the overall band `coverage_map_earned` alone would derive (§7.15's `overall_confidence` extension). A paper that cites thinly-covered repair material cannot disclose a confidence the repair itself does not support.

### 7.12 Per-pass model tiering **[TENTATIVE]**

Model choice and reasoning are per-pass settings carried in the existing `model_by_pass` / `reasoning_by_pass` seams (PRODUCT.md §7.9), never hardcoded. Starting assignments, to be proven by measurement on the dev paper briefs:

- **Drafting (stage 3)** — high tier, reasoning ON. The judgment-heavy pass, now once per section rather than once per paper (§5), so its cost scales with the plan's length.
- **Arc planning (stage 2)** — high tier. **[CORRECTED 2026-08-01, founder direction.]** This read "a cheaper tier may suffice; it emits structure, not prose", which reads the pass backwards. **Deciding the arc is the judgment**: which claims earn a section, what order makes each section earn the next, and where the counter-position goes. The drafter only writes what this pass already decided, so a weak plan cannot be recovered by a strong drafter. Phase B made this exact mistake once and paid for it — `retrieve` sat on the flash tier on the same "it only picks" reasoning, and the tier turned out to decide whether a run reached 2 sources or 12 (issue #517). Upgraded before a measurement rather than after one.
- **The reviewer panel (§10.2)** — frontier tier, and constrained by §7.7's vendor rule before any tier consideration applies. The panel's cost sits on the eval budget, not on the per-paper budget.

**"High tier" should not be read as "closed frontier", and Phase B has one measurement against it.** Its two-arm eval ran the same hard question at the same pin and budget on an all-open wiring and an all-closed one. The **open arm won, at 2.3x less money**: $0.3905 against $0.8893, 7 sources reached against 5, 4 of 5 required sources against 3. A sealed referee, blind to which was which, chose it on a specific reading — both arms cite Üngör's argument that paramilitarism arises from incomplete monopolies of violence "rather than from cultural divisions alone", and only the open arm read it as written, while the closed arm marshalled the same passage against its own thrust. **The comparison swaps four models at once and cannot say which swap carried it**, and it is one draw. It is not a ruling for Phase C. It is enough to stop treating the expensive tier as the safe default, and to make the first dev-paper measurement a real question rather than a confirmation.

### 7.13 The coherence sample spec and its frame **[TENTATIVE]**

A coherence measurement run reads a **sample spec**: a committed file under `evals/samples/` naming which already-written papers the panel reads and how they are grouped. The panel never selects its own sample, so a run is reproducible and a number is attributable.

```
{
  sample_id,
  corpus_pin,                       # the single pin every named paper shares
  strata: [ {
    stratum_id,
    tier,                           # the performance tier this stratum represents
    model_combination,              # the model_by_pass signature the papers were drafted under
    paper_brief_ids: [ ... ]
  } ]
}
```

**Two stratification axes, both required.**

- **Performance tier.** The sample must span more than one tier, so a coherence number is not read off the system's best work alone. Tier is assigned from signals the paper record already carries: its `confidence.overall_band`, the count of new (b) claims, and the grounding rate its per-run gate recorded — **the last of which is only a usable tier signal once PHASE-B P2-4 lands** (P0-9), because a metric that reads 0.0000 on every paper sorts nothing. Until then, tier is assigned on the first two, and the report says so. The exact cut points are a stated tunable, proven by inspection over the first real papers, in the discipline PHASE-B §7.7 and §7.8 already follow: state the tunable, prove it, then set it. A single-tier sample measures a tier, not a system.
- **Model combination.** The sample must span more than one `model_by_pass` signature. Pooling papers drafted under different models into one number answers no question anyone asked: it cannot say which configuration writes coherent papers, which is the main thing an accuracy measurement is for.

**The frame travels with every number.** A coherence eval report states its frame: the `sample_id`, the paper ids read, the strata and their tiers, the model combinations covered, the panel configuration (reviewer models, vendors, N), and the `corpus_pin`. **A panel number belongs to a measurement run and its frame, never to a single paper and never to the system in the abstract.** A number quoted without its frame is not a weaker claim than the same number with it; it is a different and unsupported claim.

**Numbers are reported per stratum, never pooled into one headline.** This is charter Principle V applied where it bites: a single aggregate quality score is meaningless, and a strong tier must not be able to average away a weak one. A run reports one coherence figure per stratum plus the frame, and it does not report a system-wide mean.

Sample specs carry ids and strata only. No prose, no chunk text, no paper text (DEC-23).

### 7.14 Opposing positions across records (charter Principle IV at paper scale) **[TENTATIVE]**

**Contradiction between source records is the scholarly substance, not an error.** Two analysis records that argue opposite sides of a question are opposing arguments, which is the soul of the domain this product works in. Phase C treats them as charter Principle IV already requires: the opposition is stated at its strongest, or the one-sidedness is disclosed. Nothing here is new principle. This section only lifts Principle IV from within one analysis (PHASE-B §7.8) to across a set of them.

Three rules bind, and they are the whole of it.

- **Contradiction is never an intake rejection.** It is not in §7.1's rejection list and must not be added to it. A paper brief naming records that disagree is a normal, valid, and arguably the most interesting input this phase takes.
- **Contradiction is never adjudicated, resolved, or silently reconciled.** Both claims survive into the paper, each carrying its `origin` and therefore its source record (§7.4). Collapsing two contradictory records into one position without disclosure is Principle IV's exact named failure: the paper has "collapsed to one side and hidden that it did."
- **A paper whose source records carry opposing positions is a contested paper**, and Principle IV binds it. Its `counter_position` section (§7.3, the PHASE-B §7.8 shape reused unchanged) is either present at its strongest from grounds, or discloses and attributes the one-sidedness.

**The contested predicate.** This is the one place the mechanism needed real work, because PHASE-B's predicate is described in terms of retrieved chunks and Phase C has records. Stated plainly, split into what is reuse and what is new.

**Reuse, and more of it than expected.** PHASE-B's predicate is implemented over **claim grounds, not over the retrieval trajectory**: `axial.validators.counter_position.detect_contested` reads `record["claims"]`, takes the union of chunk-typed `grounds` pointers, resolves each through `get_chunk`, and inspects what those notes say. A Phase-C paper record carries `claims` with the same `grounds` shape pointing at the same real vault ids (§7.4, §7.5), which is the property this section depends on and which survived every v1 change.

PHASE-B §7.8 now has **three** arms, not two, and they divide cleanly for Phase C:

- `opposed_positions` — two of the paper's cited notes take different sides and one names the other's side in its `arguing_against` answer. **Applies to a paper record unmodified.**
- `names_opponent` — a cited note names an opponent at all. **Applies unmodified.** (This arm is not in the two-arm list this section used to carry; both it and `opposed_positions` fired across the six smoke-v5 records, three each.)
- `gather_disagreement` — a name the paper both rests on and cites evidence from carries a Gather disagreement section. **This is the one that needs work**, below.

> **CORRECTED 2026-08-01, superseding the slice-05 note this section carried.** That note said the second arm "additionally reads `record["trajectory"]`, which a Phase-C paper record must therefore carry or forgo", which named the wrong arm and posed a false choice. What shipped is narrower and has a better answer. Only `gather_disagreement` is trajectory-dependent: it is scoped to `coverage_scope(claims, trajectory)` — the names this run retrieved on that a claim's grounds note is a member of — for a measured reason that binds at paper scale too. A real evidence set's notes name 423 distinct canonicals on average, mostly one-off mentions, so a Gather finding at a name the answer merely brushed past says nothing about whether the answer is contested. The scope is not incidental to that arm; it is what makes it mean anything.

**Phase C supplies the scope instead of deriving it.** §7.11's coverage map is already the paper-scale analogue of `coverage_scope`: names present in a source record's own map **and** touched by a claim this paper cited. So `gather_disagreement` runs against `coverage_map.keys()`, and the arm keeps its measured meaning without a trajectory existing anywhere. Mechanically this asks `detect_contested` for an optional explicit scope rather than always deriving one — a parameter, not a second implementation, because two implementations of "is this contested" would let the generator and the gate that checks it disagree (issue #399).

All three inherited arms satisfy the no-vault-access constraint by construction: resolution happens in the validator, which already reads the vault, and never in the drafter, which has no path to it (§4).

**What is genuinely new: a fourth arm, and it closes a real hole.** All three inherited arms read only what the paper **cited**. A drafter that simply declines to carry any opposing material produces a paper whose cited evidence spans one school, which all three score as uncontested, which waives the counter-position requirement. That is laundering a contested question into a clean one by omission, and it is exactly the failure Principle IV names. So:

- `source_record_contested` **[new]** — fires when any **named source record** carries a `counter_position` section that is present-with-grounds or discloses `corpus_one_sided: true`, or when that record's own contested predicate fired. It reads the source records under `data/analyses/`, which the paper record already names in `source_analyses`. **A `failed` counter-position section (§7.3) is not a disclosure and must not fire this arm** — that state means a run died in its closing stage, and reading a bug as a finding about the corpus is the exact confusion PR #558 exists to prevent.

This arm reads record fields only. **Zero vault reads and zero model calls**, and it fires from what the inputs contained rather than from what the drafter chose to keep. A paper whose sources argued both sides cannot become uncontested by dropping one side.

The predicate is the disjunction of the four arms, evaluated in the order above, and the fired signal is recorded on the report exactly as PHASE-B records it, so the rule can be tuned on evidence later.

**No tunable at all, new or inherited.** This section previously claimed to reuse "PHASE-B's existing `contested_detection.min_distinct_theory_schools` config key with the same default of 2". That key does not exist: it counted a tag axis Phase A v1 deleted, and it was removed with the two v0 arms it served. None of the four arms above carries a threshold. `opposed_positions`, `names_opponent` and `source_record_contested` are booleans over fields that already exist, and `gather_disagreement`'s only parameter is the scope, which §7.11 computes.

**A stated limit, inherited whole.** Phase B measured this predicate's recall at **0.35–0.59** and kept it a boolean anyway, because two contracts block on the boolean and grading it would not recover a disagreement the predicate never saw. The same limit binds here and is worth naming plainly: the counter-position gate requires a counter-position **only where the predicate sees the disagreement**. It is not a claim that every contested paper is caught.

**Why this section is [TENTATIVE], and what would settle it.** Not the principle, which is FIRM and is the charter's. What is unproven is whether the fourth arm earns its place. If, over the first real papers, `source_record_contested` never fires alone (never without one of the three inherited arms also firing), it is dead weight and should be dropped. If it fires alone with any regularity, each instance is a paper that dropped its opposition and would otherwise have passed, and the arm is load-bearing. That inspection is the tuning, and it follows the discipline PHASE-B §7.7 and §7.8 already set: state the rule, prove it by inspection, then settle it.

### 7.15 The opposition gap-and-repair pass **[NEW, 2026-08-01, issue #570]**

Every gap number this product reported before this section counted volume, not effect. Reading 8 of 377 notes on a name costs nothing if the 369 unread say the same thing; the gap that matters is whether unread material **argues against** a conclusion. It is not hypothetical: a Phase-B brief declared `corpus_one_sided: true` while the corpus held the exact opposing account, 17 notes under one name and 14 under another, never retrieved across four consecutive runs (issue #569, DEC-60). The founder's ruling was that this fix does not belong in Phase B's retrieval loop, which plans before any claim exists and so cannot know what it missed — "missed" is only definable once there are claims to argue against. It belongs to the layer that writes the answer, targeted at exactly the material Phase B's own retrieval could have reached and did not.

**Placement (orchestrator decision).** This pass sits between stage 1 (intake) and stage 2 (planning) — "stage 1.5" in §5's stage list. `who_argues_against` keys on canonical names, and a new (b) claim's `names_touched` is the union of the claims it derives from (§7.4), so drafting adds no name intake did not already hold, and `reduce_to_cited` (§7.5) only removes claims, never adds names. The intake-time name set is therefore a **superset** of the post-draft one: checking here finds every gap a later check would, the plan and the draft each run once instead of twice, and no re-draft can open a fresh gap the first draft never saw. The cost is precision, disclosed rather than hidden: the gap is computed over every claim the source records carry, so it can repair opposition to a name the finished paper does not end up citing. Both numbers — the gap as found, and the gap restricted to what the paper actually cited — are recorded (below).

**Decision 1 (founder): Phase C retrieves directly.** An alternative shape was weighed and rejected: commission a bounded Phase B run and let its resulting analysis record join the input list, using the same list-of-records signature §0/§5 already require. That shape was **not** rejected for cost — a bounded run is still bounded — but because it trades a second orchestrated process for a simpler record, and the founder chose the simpler record. Phase C calls the deterministic query API itself and shapes what comes back into claims in its own layer (§3 non-goal 1's CORRECTED note; this is retrieval without running Phase B).

**Three rules, unchanged from the issue that specified them:**

1. **The tool is the existing deterministic query API, never an open search.** It returns ids from the index, so the layer cannot invent opposition to look balanced. Whatever comes back passes through the same (a)/(b) marking, the grounding gate and the steelman check as everything else — no new trust surface (§7.4, §10.1).
2. **It runs only where the gap is non-zero.** Most runs will not trigger a repair at all: the lookup is a plain, free vault read, not a retrieval loop and not a model call, so there is nothing to pay for beyond the lookup itself, and nothing is added to the record for a name with nothing unread.
3. **The gap is recorded before the repair, and the repair never erases it.** If the same figure both triggers the pass and scores the result, it goes to zero by construction and measures nothing. The record and the rendered paper must be able to say "gap found: 12 notes; 9 retrieved on the repair pass" — never a clean zero presented as though retrieval got it right the first time.

**What this measures is a FLOOR, and the reason is a join, not a content gap — measured 2026-08-01, and the number belongs beside every count this pass produces, not only in a caveat.** `who_argues_against` finds an opposing note by exact-matching a note's own `arguing_against` answer against a canonical name page. `arguing_against` stores prose, not a pointer: across 4,695 notes carrying 10,883 recorded targets, only **4.7%** exact-match a name page this way. The other 95.3% are free text — 91.2% run longer than three words, with real values like "the assumption that all peasants can be lumped together politically" or "a macro-structural Weberianism that gives no room to agency" — and **87.0%** of those contain a real canonical name of 6+ characters somewhere inside the string (4,716 concept, 1,628 institution/group, 786 movement/religion, 687 person) that the join cannot parse out. So the miss is not that most of this opposition went unnamed; it is that a join on exact string equality cannot recover a name from a sentence. A zero from this pass means no exact-match opposition went unread — never that the corpus holds no counter-argument, and never that the unmatched 95.3% named nobody. This sentence, with the 4.7% figure, is `axial.paper.opposition.OPPOSITION_GAP_SCOPE_NOTE`, and it is required to travel with the count into both the record (`exact_match_opposition_gap.scope_note`) and the rendered paper — a caveat without the magnitude reads as a formality.

**The lookup is an injected parameter, not a hardcoded call.** A richer resolution pass that recovers targets from the free-text 95.3% is real, separate, future work, and it must slot in without reopening the gap arithmetic, the repair retrieval, the record shape or the disclosure above. `run_opposition_repair`'s `lookup` parameter is that seam: `(canonical, limit, *, vault_dir, names_dir) -> (edges, total)`, defaulting to `axial.query.names.who_argues_against`. Everything downstream of the edge set it returns — already-read filtering, claim shaping, the trajectory, the coverage map, both gap counts — is correct for whatever lookup produced the edges.

**Step 1: compute the gap.** Over every canonical name the intake inventory's claims touch (§7.4's `names_touched`, unioned across every named record), the lookup is called once. An edge is **already read** when its chunk id appears in some named source record's own `trajectory` (a chunk-returning tool's `result_ids`, issue #556) OR among that record's own claims' grounds — the union of both, the more generous reading, so a note the retrieval loop saw but never cited is still credited as read. Understating "already read" is what overstates the gap; both source-record fields were checked to confirm they carry enough to determine this (below).

**Step 2: retrieve, only where the gap is non-zero.** A `who_argues_against`-shaped trajectory entry (§7.6's shape exactly: `{step, tool, args, result_ids[], result_count, total, detail}`) is appended, and the pass proceeds to shape claims, only for a name the lookup returned unread material for.

**Step 3: shape into claims, with zero model calls.** `OppositionEdge` (`axial.query.names`) already carries `chunk_id` (a real vault id), `source_id`, and the note's own one-sentence `claim` answer — a source's own assertion, with grounds that come out of the index together with the text, so generate-then-cite is structurally impossible here too, the same move Phase B's own tool-dispatch seam makes (§4). Each unread edge with a usable `claim` becomes an ordinary kind-(a) claim: `text` is the note's own `claim` verbatim, `grounds` is `[{ref_type: "chunk", ref_id: chunk_id}]`, `names_touched` is `[canonical]`, attributed to its own source. **Measured over the real corpus (2026-08-01, `data/vault/prose`, 6,148 live notes): 6,009 (97.7%) carry a real `claim` answer; 139 (2.3%) carry the `not-in-passage` abstention.** An abstained edge still counts toward the gap — the note is genuinely unread opposition — but is not shaped into an invented claim; it is counted separately (`skipped_abstentions`).

**Every repair claim is injected into the intake as though it came from one extra source record**, `axial.paper.opposition.REPAIR_BRIEF_ID` (never a real Phase-B `brief_id`), whose own `coverage_map` is computed natively over the repair pass's own trajectory (§7.11's `coverage_map_earned`). This is what makes rule 1 literally true: `carried_claim` (§7.4) clamps a repair claim's band exactly as it clamps any carried claim, reading the synthetic record's map the same way it reads a real one, and the provenance-integrity gate, the grounding gate and the (b)-seam gate need no special case for a repair claim at all. A repair claim's own emitted band is `high` by construction — there is no model judgment behind it to disclose — so the coverage ceiling, never the emitted value, is what actually governs its rendered band.

**The gap record (§7.3's `exact_match_opposition_gap`).** Both the gap as found and the gap restricted to what the finished paper cited, labelled:

```
exact_match_opposition_gap: {
  scope_note,                 # OPPOSITION_GAP_SCOPE_NOTE, the 4.7% floor disclosure, verbatim
  names_checked: [ canonical ],
  gap_found,                  # distinct unread notes across every checked name
  gap_repaired,               # of gap_found, how many became new grounded claims
  gap_found_cited_scope,      # gap_found restricted to what this paper actually cites
  gap_repaired_cited,         # of gap_repaired, how many were cited in the finished paper
  skipped_abstentions,        # gap notes whose own `claim` answer abstained
  by_name: { canonical -> {gap_found, gap_repaired, already_read, total_opposition_edges} }
}
```

**Render (§7.10).** The rendered paper carries a plain "Opposition check (exact-match join)" section, always present once the pass has run, stating the scope note (with its 4.7% figure) beside the found/repaired counts and the cited-restricted counts — never omitted on a zero, and a repaired run's counts are never allowed to read as a clean zero (rule 3). Engine telemetry stays out of the reader's paper exactly as before (§7.10); this section is not that — it is the same class of disclosure as the confidence band, a number the reader needs to weigh what the paper argues.

**What was checked before relying on this (per the build brief that specified it).** Whether the named source records carry enough to determine what they already read: yes — a real Phase-B analysis record always persists `trajectory` (`axial.answer.record.build_record`) and `claims[].grounds`, and this pass unions both. Whether shaping a repair claim from `OppositionEdge.claim` needs a model call: no, at 97.7% real-claim coverage over the live corpus, measured directly rather than assumed.

### Must-Have (P0)

**P0-1 Paper-brief intake and the claim inventory (charter Principle II).**
- [ ] Reads a versioned paper brief (§7.1), resolves every `analysis_ids` entry against `data/analyses/`, and builds the claim inventory keyed by `(brief_id, claim_id)`.
- [ ] Rejects, naming the offending id: an unresolvable record, a record whose disposition is `refuse`, and a mixed `corpus_pin` set. (A mixed `schema_version` set was a fourth rejection until issue #524 cut that field from the Phase-B record; the pin subsumes it — see §7.1.)
- [ ] **Zero Phase-B invocations.** Observable: intake makes no call into the Phase-B brief pipeline, and a paper brief naming an un-run brief fails with an error telling the operator to run it through Phase B first.

**P0-2 Arc planning before prose (charter Principle II).**
- [ ] Emits the §7.2 paper plan: ordered sections with headings, roles from the `role_in_argument` vocabulary, and claims assigned from the inventory. Observable: the plan is produced and inspectable with zero drafting calls made.
- [ ] At least one section carries `role: counter-position`, unless every named source record discloses `corpus_one_sided: true`, in which case the paper renders that disclosure. Neither present fails plan validation (charter Principle IV).

**P0-3 Drafting from the inventory, with no retrieval path (charter Principle I).**
- [ ] The drafter writes prose per section from the plan and the inventory, and has **no tools**: no vault query API, no file access, no web. Observable: the drafting call is constructed with an empty tool list, and the drafter cannot introduce a grounds pointer that was not already in the inventory.
- [ ] **One drafting call per section**, over that section's `assigned_claims` plus the ids, kinds, bands and text of what earlier sections cited — never the whole inventory (§4, §5, §7.2). Observable: for a plan of N sections the drafter is called N times, and no call's prompt contains a claim assigned to a later section.
- [ ] New (b) claims are emitted with `kind: b`, `origin: null`, and a `derived_from` list spanning at least two distinct source `brief_id`s (§7.4). Observable: a new claim derived from a single record fails validation.
- [ ] No new (c) claims are emitted (§3 non-goal 4).

**P0-4 The confidence ceiling (charter Principle V).**
- [ ] A carried claim's `kind`, `grounds`, and `confidence` are identical to its origin's, where the origin's `confidence` is its **clamped** band and not the band the analysis record persisted (§7.4). Observable: given a source claim whose persisted band is `high` and whose per-claim coverage clamps it to `medium`, the carried claim is `medium`; carrying `high` fails the provenance-integrity gate.
- [ ] A new (b) claim's band is at most the minimum clamped band among its `derived_from` claims. Observable: a `high`-band (b) claim derived from a `medium` and a `low` claim fails.
- [ ] The paper's `confidence.overall_band` is at most the lowest overall band among the named source records.
- [ ] Every paper claim carries `names_touched`, so §7.11's coverage map is computable with zero vault reads. Observable: the map is produced in tests with no vault directory configured.

**P0-5 Citation markers and the citation index (apparatus).**
- [ ] In-text markers use exactly the §7.5 format, and the citation index is built deterministically by parsing the rendered prose.
- [ ] Every marker resolves to a claim in `claims`; every claim's grounds resolve to real vault ids through the Phase-B query API; the record's `claims` list is exactly the set of cited claims. Any failure blocks release.
- [ ] The rendered citation table resolves the full chain: claim id, kind, band, grounds chunk ids, and the bibliography entry per grounds source.

**P0-6 Bibliography from `source_meta` (apparatus).**
- [ ] Generated deterministically with **zero model calls** from `data/source_meta/`, for exactly the cited sources. Observable: the bibliography is produced in tests with no LLM client present, and a source present in a named analysis record but never cited does not appear.
- [ ] An `unavailable` or `not attempted` field renders as a distinct, stated absence; no field is ever filled from a filename; provenance travels with each value (PRODUCT.md §7.13).
- [ ] Ordering is deterministic, and the entry carries no source text (DEC-23).

**P0-7 Paper record and rendered paper (output contract).**
- [ ] One record JSON per run at `data/papers/<paper_brief_id>.json` carrying the full §7.3 shape, and one rendered markdown paper alongside.
- [ ] Rendering is deterministic: the same record renders the same markdown, byte for byte.
- [ ] Every confidence band in the rendered paper appears next to the coverage counts that justify it, and claim kind is legible in the citation table (§7.10).

**P0-8 Provenance-integrity gate (charter Principle II; mechanical hard gate).**
- [ ] A **deterministic** gate scores `provenance_completeness`: the share of citation markers that resolve to a claim in the record whose grounds resolve to real vault ids. Threshold **1.00**. Observable: a record with one dangling marker or one unresolvable grounds pointer fails outright.
- [ ] The same gate scores `confidence_upgrade_count`: the number of claims violating the §7.4 ceiling. Threshold **0**. Observable: a single upgraded band fails the gate.
- [ ] Both metrics are computed with **zero model calls**.
- [ ] The gate report carries **no panel field and no panel-derived trust condition**. Observable: the report is produced, and can pass, with no reviewer panel configured and no reviewer call ever made (§10.1).

**P0-9 Grounding and (b)-seam gates, reusing Phase B (charter Principles I, II).**
- [ ] Phase C's new (b) claims are scored by the **existing grounding judge** in `src/axial/gates/grounding.py`: its prompt, verdict vocabulary, unresolvable-grounds error, and self-grading guard are reused unchanged. The judge's self-grading guard is re-anchored to Phase C's drafting pass rather than the Phase-B synthesis pass.
- [ ] **PHASE-B P2-4 is a precondition of this gate, not a background note.** Observable: the re-barred (b)-claim metric returns a non-zero score on a record holding a known mis-grounded (b) claim, before Phase C's gate is wired to it.
- [ ] The `b_seam_mislabel_rate` judged check in `src/axial/gates/attribution.py` is reused over the paper record's (b) claims, **and it must be handed each claim's distinct grounds source ids** (PR #559). It is the check that catches Phase C restating an (a) claim as its own inference, so no second judge seam is invented for that rule.

> **CORRECTED 2026-08-01. The claim selector this bullet asked for already exists, and what it computes is a metric Phase B has flagged as asking the wrong question.** The original text said "the only Phase-C-specific part is the claim selector, which selects new (b) claims where the Phase-B gate selects kind-(a) claims". Issue #550 already added that selector: `axial.gates.grounding` scores `grounding_support_rate` over kind-(a) claims **and** `b_claim_contradiction_rate` over kind-(b) claims, the latter asking whether *some cited passage contradicts* the claim rather than whether one supports it, since a sound inference need not be asserted outright by any passage.
>
> **That metric reports 0.0000 on both sealed review rounds, including the record holding the claim it was built to catch** — one whose cited passage opens "Contrary to Mann's assertion…". Its proposition is supported; what the passage contradicts is the claim's crediting of a scholar, and "does any cited passage contradict this claim" does not ask that. The note states the opposition in its own `arguing_against`, which the judge is never shown. The judge also resolves to `production_low`, the cheapest tier, which decides the (a) metric too (PHASE-B P2-4).
>
> **Why this matters more here than it did there.** In Phase B the (b) seam is a minority of claims and `grounding_support_rate` over (a) claims carries the gate. In Phase C the new (b) claims **are the entire contribution** — §2 goal 2, the only new knowledge the phase produces — so this metric would be the primary gate on the only thing Phase C adds. Adopting it as-is would ship a gate that reads 0.0000 whatever the drafter does, which is worse than no gate: it looks like evidence.
>
> PHASE-B's standing rule is that P2-4 through P2-9 wait until real use makes one visibly wrong, "because then the failure names which one to fix" (DEC-55). **Phase C is that use, and P2-4 is named.** Re-bar it first — the cheap fix P2-4 itself points at is showing the judge the note's own `arguing_against` — then wire this gate to it.

**On the (b)-seam threshold's denominator.** §10.1 sets `b_seam_mislabel_rate ≤ 0.05`. A Phase-B answer carries 12–26 claims of which 3–10 are (b); a Phase C paper's *new* (b) claims will be fewer still. At four new (b) claims, 0.05 is arithmetically zero-tolerance — one mislabel scores 0.25. Report the **count alongside the rate**, and read the rate as a target rather than a cliff until enough papers exist to set a real cut point. This metric was also a coin flip on identical input until PR #559 — 0.571, 1.000 and 0.000 on the same record — so a single draw of it is not a measurement.

**P0-10 The sealed-packet reviewer panel (offline eval instrument; charter Principle V, §10.2).**
**Phase C does not build this. `src/axial/panel/` exists and has run twice** (PHASE-B §9.4, issue #385). The bullets below are split into what the existing module already satisfies — verify, do not rebuild — and what Phase C owes.

*Already satisfied by `axial.panel`; Phase C's obligation is to point it at a paper record.*

- [x] Reviewer calls carry no tools, structurally: dispatch is through `complete_json`, which has no `tools` parameter (§7.7).
- [x] The different-vendor guard, with an unknown model id a hard error before any call (`axial.panel.vendor`).
- [x] `MIN_REVIEWERS = 3`, independent, enforced at dispatch (`axial.panel.review`).
- [x] Structured verdicts with a closed defect vocabulary; free prose is a parse failure, an out-of-vocabulary kind a load error.
- [x] Packets are never written to disk at all, and `assert_sealed` refuses one carrying a repository path.

*What Phase C owes.*

- [ ] **The panel is off the pipeline and blocks nothing.** Observable: `axial paper draft` completes end to end with zero reviewer calls and zero packets assembled, and no module under `src/axial/paper/` imports from `src/axial/panel/`.
- [ ] A paper-shaped packet builder beside the existing analysis-record one, plus the `coherence` dimension and the two added defect kinds (§7.8). Observable: an analysis packet still scores the original three dimensions and is unaffected.
- [ ] A run reads a committed sample spec (§7.13) spanning **more than one performance tier and more than one model combination**, and reports one coherence figure per stratum. Observable: a single-tier or single-model-combination sample is rejected, naming which axis is unstratified; and no run emits a pooled system-wide mean.
- [ ] The report states its full frame: `sample_id`, paper ids, strata and tiers, model combinations, panel configuration, and `corpus_pin`. Observable: a report is never produced without a frame.
- [ ] The paper packet carries exactly the §7.7 contents and nothing else. Observable: a test asserts the assembled packet's keys against the contract and fails on any addition.
- [ ] The vendor guard is handed the paper record's own generating passes — drafting and arc planning, off `model_by_pass`. Observable: zero reviewer calls are made when the guard fires.

**P0-11 The positive control (the instrument's own admission criterion).**
- [x] The three §7.9 plants are **content-free, deterministic record mutations** — implemented in `axial.panel.control` as in-code mutations rather than as committed spec files, which satisfies DEC-23 more strongly. `evals/plants/` is struck (§6).
- [ ] Each plant applies to a **paper** record and raises rather than skips where it cannot (`PlantNotApplicableError`). Observable: a control paper lacking a present-with-grounds counter-position raises instead of running a two-plant control.
- [ ] Each planted variant is rendered and packeted exactly as a real paper is, and scored by the same panel. A plant is caught when a **strict majority** of reviewers return a matching defect kind pointing at the mutated target (§7.9).
- [ ] The **coherence eval report** carries `trusted: false` unless the positive control has passed against the same panel configuration. Observable: a coherence report produced without a passing control is never marked trusted, whatever its value.
- [ ] The control qualifies the **instrument**, not any paper. Observable: a failing positive control blocks no paper's release and fails no per-run gate; it invalidates that measurement run's numbers and nothing else.

**P0-12 CLI surface with inspect-before-spend.**
- [ ] `axial paper draft <paper_brief_file>` runs stages 1 through 5 and writes the record and rendered paper.
- [ ] `axial paper examine <paper_brief_file>` runs intake and arc planning and reports the plan, the claim inventory, and the sections' assigned claims **without the drafting call**, analogous to `axial brief examine` (PHASE-B P0-9). Observable: `examine` makes zero drafting calls.
- [ ] The four per-run gates run through the existing `axial gate run <gate>` surface. Observable: `draft` and `examine` between them expose no path that invokes the reviewer panel.
- [ ] `axial eval coherence --sample <sample_spec>` runs the offline eval track: assembles packets, runs the panel over the sampled papers, and writes the per-stratum report with its frame. It is a separate command from `axial paper`, because it measures the system rather than producing a paper.

**P0-13 Dev paper briefs landed as versioned data.**
- [ ] At least three dev paper briefs land under `config/paper_briefs/dev/` in the §7.1 shape, each naming Phase-B dev briefs that have actually been run, so every dry-run in this phase is reproducible from the repo. Observable: the dev paper briefs drive the harnesses with no operator-local file.
- [ ] At least one dev paper brief names **source records that argue opposite sides**, so the §7.14 path is exercised by default rather than only under a hand-built fixture.

**P0-14 Opposing positions across records (charter Principle IV; §7.14).**
- [ ] Contradiction between named source records is **never an intake rejection**. Observable: a paper brief naming two records whose claims argue opposite sides is accepted and drafted, and no error path exists for record disagreement.
- [ ] Both sides survive into the paper with their source records identified. Observable: a paper drawn from opposing records carries claims from both, each with its `origin`, and no reconciliation step collapses them.
- [ ] The §7.14 contested predicate reuses `axial.validators.counter_position`'s three existing arms over the paper record's claim grounds — `opposed_positions` and `names_opponent` unchanged, `gather_disagreement` scoped by §7.11's coverage-map keys in place of a trajectory — and adds the fourth `source_record_contested` arm. Observable: a paper whose source records carried opposing positions is flagged contested **even when the drafter cited only one side**, which is the hole the fourth arm exists to close.
- [ ] The fourth arm is computed with **zero vault reads and zero model calls**, from the named source records' own fields, and a `failed` counter-position section never fires it. Observable: it is produced in tests with no LLM client present and no vault directory configured.
- [ ] A **mechanical** per-run gate blocks a contested paper carrying neither a present-with-grounds counter-position nor a one-sidedness disclosure with a reason (§10.1). An uncontested paper is excluded from the denominator, never counted as a pass. Observable: a contested paper with neither fails; an uncontested paper with neither passes.
- [ ] A new (b) claim may characterise a disagreement and may not declare a winner beyond its grounds (§7.4). This is enforced by the existing grounding and (b)-seam gates, with no new judge seam.

### Nice-to-Have (P1)

- **P1-1** A per-section drafting log recording which inventory claims the drafter considered and passed over, the authorship analogue of PHASE-B's trajectory log.
- **P1-2** Reviewer-defect aggregation across papers: which `defect_kind`s recur, and on which sections, so a systematic drafting weakness is visible rather than merely suspected.
- **P1-3** A fourth and fifth plant class in the positive control (an `arc_break` plant by section reordering, an `unmarked_inference` plant by re-voicing a (b) claim), once the first three are proven.

### Future Considerations (P2 — design for, don't build)

- **P2-1** New kind-(c) speculation, permitted in a clearly delimited concluding section, with its own gate. Deliberately not v0 (§3 non-goal 4).
- **P2-2** Reviewer panels that disagree productively: routing a split panel to a fourth tie-break reviewer rather than reporting a wide spread.
- **P2-3** Multi-paper corpora: a book-length work assembled from several paper records.

---

## 9. The referee seam

**There will be no human referee, permanently.** Issues #250 and #295 were closed as not-planned on 2026-07-24. Phase C therefore creates **no dependency on human-authored referee data**: no file, gate, acceptance criterion, or build phase in this spec waits on an academic. This is a change of kind from Phase B, whose §9 held a paused seam open for academic hard cases; that seam is closed, not paused, and Phase C does not reopen it.

**The sealed-packet panel is the permanent replacement**, not an interim stand-in. Its design is the founder's adjudication of what a referee actually provides that internal checks cannot: a reader who was not in the room. The four properties that make it a referee rather than a rubber stamp are §7.7's, and each one answers a specific way an LLM judge fails.

- **Sealed** answers *it read the answer key*. An agent with file tools reads the repo whatever its prompt says, so tool absence is enforced by the harness.
- **Different vendor** answers *it shares the drafter's priors*. A sibling model finds the same arguments persuasive for the same reasons.
- **N >= 3 with reported spread** answers *a single draw is a single draw*. The mean without the spread hides a panel that could not agree.
- **Positive-controlled** answers *judges are generous*. A panel that catches nothing is indistinguishable from a panel that stopped reading, and §7.9 makes that distinction mechanical.

**What has actually been run against those four properties, stated plainly [2026-08-01].** Phase B reviewed its own answers twice with this instrument, and the record is more mixed than the design reads. The positive control **passed 3 of 3** planted defects, so the panel demonstrably catches what it is shown. Against that: **both rounds ran one reviewer per packet, not three** (PHASE-B P2-9), so the bands sort the briefs and are not measurements, and no spread has ever been reported; and **the reviewer's false-positive rate is unmeasured** (P2-8) — the control tests only what it catches, never what it invents. The cheap close for the second is named and unbuilt: hand one reviewer a packet whose defects have been repaired and see what it still reports.

Two operational notes worth carrying rather than rediscovering. The reviewing that has happened ran on a **sealed Claude Code subagent** and cost no model money at all — N ≥ 3 there costs wall clock, not dollars, which removes the usual reason a panel stays at N=1. And a subagent judge is only different-vendor if the drafter is not Claude, so §7.7's vendor rule constrains the drafting tier as much as the reviewing one. Neither property in §7.7 is relaxed by any of this. What changes is that Phase C should stop describing N ≥ 3 as settled practice: it is a specified property with no run behind it.

**It is an eval instrument, not a turnstile.** This is the founder's ruling of 2026-07-24 and it governs everywhere the panel appears in this spec. The panel is run offline, over a stratified sample of already-written papers (§7.13), to measure how accurate the system is across performance tiers and model combinations. It is not a per-run gate, it blocks no paper, and no paper's release depends on it. The four per-run gates of §10.1 are what every paper passes through, and all four are cheap.

The cadence change costs nothing in integrity. Every property in §7.7 through §7.9 holds exactly as written: sealed, tool-free, different-vendor, N >= 3, structured verdicts, positive-controlled. What changed is **when the instrument runs and what it is pointed at**, not how rigorous it is. A sampled instrument with intact controls is a measurement; a per-run instrument with the same controls would be an expensive checkpoint that still could not tell you the system's accuracy, because accuracy does not live in a single paper.

**What the panel is not.** It is not a correctness oracle. Correctness at the frontier of a synthesis has no answer key, which is the charter's founding observation (charter §0). The panel judges whether an argument holds together over the evidence it was shown. That is checkable, and it is the property the per-run gates cannot reach. It is not, and must not be reported as, a claim that any paper is right.

---

## 10. Success metrics: the per-run gates and the coherence eval track

Two instruments with two different jobs, on two different clocks. §10.1 decides whether a paper may be released. §10.2 measures how accurate the system is. Neither substitutes for the other, and nothing in §10.2 can block anything in §10.1.

### 10.1 Rung-3 gates (per run, ship-blocking)

These are the **rung-3 ship-blocking eval gates** for the layer Phase C builds (charter §2). Trust composes multiplicatively across layers: Phase-A's κ eval is rung 1, Phase-B's five gates sit above it, and these sit above those. A flawless paper over a mis-attributed analysis is worthless. The principles behind each gate are **FIRM**; the numeric thresholds are **TUNABLE** starting hypotheses.

All four are cheap by design. Two are mechanical, and the other two are narrow judged checks scoped to Phase C's own new (b) claims, which are a small fraction of any paper's claims. Every paper passes through all four.

| Gate | Charter | Metric | Starting threshold [TENTATIVE] |
|------|---------|--------|--------------------------------|
| **Provenance integrity** | Principle II | `provenance_completeness` = share of citation markers resolving to a record claim with resolvable grounds; plus `confidence_upgrade_count` = claims violating the §7.4 ceiling | completeness = **1.00** and upgrades = **0**; both mechanical hard gates, no sampling |
| **Grounding of new (b) claims** | Principle I | the re-barred (b)-claim metric in `axial.gates.grounding`, over Phase C's new (b) claims, anchored to resolved grounds text. **Blocked on PHASE-B P2-4** — the metric as it stands reads 0.0000 on a record holding the defect it was built to catch (P0-9) | **≥ 0.90**, and unreadable until P2-4 lands |
| **(b)-seam mislabel rate** | Principle II | `b_seam_mislabel_rate` over the paper record's (b) claims, via the existing judged check in `axial.gates.attribution`, **shown each claim's distinct grounds source ids** (PR #559) | **≤ 0.05**, reported with the raw count — the denominator is small enough that the rate alone misleads (P0-9) |
| **Counter-position presence** | Principle IV | `counter_position_presence_rate` = share of **contested** papers (§7.14's four-arm predicate) whose `counter_position` is present-with-grounds or discloses one-sidedness with a reason. Mechanical | **1.00**. A contested paper with neither is a red flag, not a clean result, and is blocked |

**Notes that bind.**

- **The two hard gates are hard.** Provenance completeness and confidence-upgrade count are mechanically checkable, so they are not sampled rates. One dangling marker fails. One upgraded band fails.
- **Reuse, do not re-derive.** The grounding gate reuses `src/axial/gates/grounding.py`'s judge (prompt, verdict vocabulary, unresolvable-grounds error, self-grading guard), with its guard re-anchored to Phase C's drafting pass; its (b)-claim selector already exists and its question needs re-barring first (P0-9). The (b)-seam gate reuses `src/axial/gates/attribution.py`'s judged check wholesale. The counter-position gate reuses `src/axial/validators/counter_position.py`'s presence-or-disclosure check and all **three** inherited contested arms — two unchanged, and `gather_disagreement` handed §7.11's coverage-map keys as its scope in place of a trajectory — adding only §7.14's fourth arm. No second judge seam is invented for any of them.
- **A `failed` counter-position fails this gate, and is not a disclosure.** PR #558's third state satisfies neither the presence nor the one-sidedness limb, exactly as absence would, and the existing check already treats it that way (§7.3, §7.14).
- **The counter-position gate takes only the mechanical half.** This mirrors PHASE-B's own split at §7.9/§10 exactly: the presence-or-disclosure check is mechanical, so it gates per run; the model-judged steelman-quality half is a judgment about how well the opposition is stated, so it joins the eval track (§10.2). Splitting them is what keeps a per-run gate cheap without losing the quality question. `validate_counter_position` already separates the two, so the split is a call-site choice rather than a code change.
- **A hard 1.00 here does not mean every paper needs a counter-position.** An uncontested paper is excluded from the denominator, never counted as a pass or a failure, exactly as PHASE-B's `counter_position_presence_rate` excludes an uncontested brief. The gate binds only where §7.14's predicate fires.
- **No gate report waits on a panel.** None of the three carries a panel field, a reviewer verdict, or any trust condition a panel could satisfy. A report naming a missing panel verdict as its reason to be untrusted would be wrong by construction (§7.9).
- **`trusted` resolves from the corpus pin alone here** — and Phase C inherits that for free. The shared harness (`axial.gates.harness.resolve_trusted`) used to require at least one academic-authored hard case as a second conjunct. That conjunct was permanently unsatisfiable once #250/#295 closed not-planned, so it was deleted for Phase B's own five gates (issue #380, PHASE-B §9.2), and the rule is now the one Phase C needs: an unambiguous corpus pin and nothing else. **No change to the shared module is owed by P0-8.**
- **The vendor bar does not apply here.** The grounding and (b)-seam judges keep the existing different-model guard. Those answer a narrow question against pinned text. The stricter different-vendor bar is the panel's, because the coherence judgment is open-ended and that is where shared family priors bite (§7.7).
- **No self-grading anywhere.** The drafting model never judges its own paper and never sits on the panel.

### 10.2 The argument-coherence eval track (offline, sampled, blocking nothing)

Coherence is **measured, not gated** (§9). This track runs on its own cadence over a stratified sample of already-written papers, and its output is a measurement report, never a release decision.

| Instrument | Charter | Metric | Reporting rule |
|------------|---------|--------|----------------|
| **Argument coherence** | Principles IV, V | `argument_coherence_rate` = mean per-reviewer coherence score across N ≥ 3 sealed-packet reviewers, **reported per stratum** | Reported with `reviewer_spread` (max − min) and the full frame (§7.13). **No threshold.** A measurement is not a pass/fail. |
| **Steelman quality** | Principle IV | `steelman_quality` = share of papers carrying a present-with-grounds counter-position whose bounded steelman check verdicts `steelman` rather than `strawman`, via `axial.validators.counter_position`'s existing judge | Reported per stratum. PHASE-B's existing **0.90** bar carries over as a **reference line, not a block**: nothing in §10.2 blocks anything |
| **Positive control** | charter §2 | `positive_control_catch_rate` = planted defects caught by ≥ ⌈N/2⌉ reviewers, over the three §7.9 plants | **Threshold = 1.00**, and it is hard. Below it, the run's coherence numbers are reported `trusted: false`. |

**Where the two previously-flagged thresholds landed, and why.**

- **`reviewer_spread` loses its threshold entirely and becomes disclosure-only.** It was already the weakest number in the original table, asserted before any panel had run. Outside a gate there is nothing for a threshold to block, and a number nobody enforces is worse than no number: it invites the reflex of loosening it until it stops firing. **Reporting the spread stays mandatory.** Thresholding it does not, and a threshold can be added later if the first panels show a defensible cut point.
- **`positive_control_catch_rate = 1.00` keeps its threshold and stays hard.** It moved, but it did not soften. It is now the eval track's own **admission criterion**: it qualifies the instrument, not the paper. Below 1.00 on the three plants, the panel is a panel that may have stopped reading, and every coherence number from that run is reported untrusted. That is a real pass/fail with a real consequence, so it keeps a real number.

**Further notes that bind.**

- **Report the spread, always.** The mean alone is ambiguous. Three reviewers scoring 0.5, 0.5, 0.5 and three scoring 1.0, 0.5, 0.0 both average 0.5. The first is a panel that agreed the papers have reservations. The second is a panel that could not agree at all, and its average describes none of its members. Reporting only the mean would make those two results indistinguishable.
- **Per stratum, never pooled.** One coherence figure per stratum, plus the frame. No system-wide headline mean (§7.13, charter Principle V).
- **The steelman judge is the existing one, re-anchored.** `axial.validators.counter_position`'s bounded check runs under its own `pass_name` with its own same-model guard, which must be re-anchored from PHASE-B's synthesis pass to Phase C's drafting pass, exactly as the grounding judge is (§10.1). It keeps the different-model bar and does not take the panel's stricter different-vendor bar: like grounding, it answers a narrow question against pinned grounds text (§7.7).
- **A number without its frame is a different claim.** Every coherence figure travels with the sample, strata, tiers, model combinations, panel configuration, and corpus pin that produced it (§7.13).
- **Three plants is a small n.** `positive_control_catch_rate = 1.00` over three plants is a floor, not a demonstration of sensitivity. P1-3 adds two more classes. A panel that catches three obvious plants has not proven it catches a subtle one, and the control's own limits are stated in every report it produces.
- **The panel has never actually run at N ≥ 3**, and the first Phase-C report must not read as though it had. Both Phase-B rounds ran one reviewer per packet, so no spread has ever been reported and every band drawn so far sorts briefs rather than measures them (PHASE-B P2-9, §9). On a Claude Code judge this costs wall clock rather than money, so the first Phase-C coherence run is the natural place to close it.
- **What the panel invents is unmeasured** (PHASE-B P2-8). The control proves what it catches; nothing tests its false positives. A coherence figure carries that limit whether or not the control passed, and `trusted: true` means "the instrument catches planted defects", never "the instrument does not manufacture them".

---

## 11. Build phases

Bottom-up, so each layer stands on a tested one beneath it. Nothing in this ladder waits on a human.

**The pipeline ladder (steps 1–6).** Phase C is shippable at the end of step 6: papers are written, and every one of them passes the four per-run gates before release.

1. **Scaffolding, paper-brief intake, dev paper briefs.** Repo per §6; intake and the claim inventory (P0-1); land the dev paper briefs (P0-13). Deterministic, no model calls.
2. **Arc planning (P0-2)** and the inspect-before-spend `examine` affordance (P0-12).
3. **Drafting and new (b) claims (P0-3, P0-4)**, with the confidence ceiling enforced at assembly.
4. **Apparatus: citation index and bibliography (P0-5, P0-6).** Both deterministic and fully testable with no LLM client.
5. **Record, rendering, persistence (P0-7).**
6. **The four per-run gates: provenance integrity (P0-8), the reused grounding / (b)-seam gates (P0-9), and the counter-position gate (P0-14).** This closes the release path. **Re-bar the (b)-claim grounding metric first** (PHASE-B P2-4, P0-9): three of the four gates reuse working checks, and that one does not.

**The eval track (steps 7–9), a separate ladder.** It measures the system built above and gates none of it. It can be built after step 6, or in parallel by a second worker once step 5 lands, because it consumes finished paper records and touches no pipeline module. It has no place in the release path and must not be sequenced as though a paper waits on it.

7. **Sample spec and stratification (§7.13, P0-10).** Deterministic, and the only genuinely new piece of this ladder. Needs enough real papers to stratify, so it follows the first real drafting runs rather than preceding them.
8. **A paper packet, and the coherence dimension (P0-10).** Not a panel: `axial.panel` is built, sealed, vendor-guarded and N ≥ 3 at dispatch. This step adds a paper-shaped `build_packet`, the `coherence` dimension, and two defect kinds. The isolation, vendor and no-pooling guards are all testable without spending a real reviewer call, and most of them are already under test.
9. **Positive control over a paper (P0-11).** The three plants exist; this points them at a paper record and picks a control paper that can carry all three. Only after it passes does any coherence number from step 8 get reported trusted.

**This ladder is much shorter than it reads**, and that is the single largest change this revision makes to the plan of work. Steps 7–9 were scoped as building the instrument. The instrument exists.

---

## 12. Dependencies, preconditions & tech stack

**Preconditions for the authorship pipeline (steps 1–6):**

- **Phase-B analysis records** under `data/analyses/`, at least three sharing one corpus pin, produced by the operator running dev briefs through Phase B. Phase C cannot produce them (§3 non-goal 1).
- **The source-metadata records** at `data/source_meta/<source_id>.json` (PRODUCT.md §7.12, §7.13), for every source the cited claims reach. A source with no metadata record renders as a stated absence rather than failing the run, but a corpus with no records at all makes the bibliography vacuous.
- **The Phase-A vault**, read-only, for resolving grounds pointers.
- **One pin window.** Every record a paper draws on must have been produced between name-layer changes, because the pin now moves when the name layer does (§7.1).

**A stated ceiling on every paper, inherited and not fixable here [2026-08-01].** Phase B's own mechanical oracle is its weakest measured number. Across the six instrumented eval runs, the share of a question's `required_citation_source_ids` a run's grounds actually reached ran **2 of 6 to 4 of 5**: one brief decomposed the claim that war made the modern state **without ever citing Tilly**, and both runs of another missed the book carrying one of the two accounts the question asks them to weigh. A paper is assembled from those records, so a book an analysis never reached is a book the paper cannot cite, however clean its apparatus. This is not Phase C's to fix — it is retrieval, one layer down, and issue #560 is open on the oracle itself naming the wrong book for some legs. It is Phase C's to **disclose**: the paper's coverage map and confidence band describe what the source records reached, never what the corpus holds.

**Preconditions for the eval track (steps 7–9) only.** These are deliberately listed apart, because none of them blocks a paper from being written or released.

- **Enough finished papers to stratify.** A sample must span more than one performance tier and more than one model combination (§7.13), which means the drafting pipeline has to have run across more than one configuration first. The eval track cannot precede the thing it measures.
- **At least two vendors configured.** The vendor guard (§7.7) cannot be satisfied with a single-lab model roster. This is a real operational precondition for measuring, and a formality for nothing.

**Explicitly not a precondition, anywhere:** any academic-authored data. There is none and there will be none (§9).

**Stack.** Python, driven through the `axial` CLI. **Inference:** the existing provider clients, through the existing `model_by_pass` / `reasoning_by_pass` seams; drafting wants the high tier with reasoning ON, arc planning may run cheaper, and the panel runs frontier tier under the vendor constraint on the eval budget rather than the per-paper one. **No new inference dependency**, and no tool-calling at all in this phase: the drafter and the reviewers both run tool-free by design (§4, §7.7). **Substrate consumed read-only:** `data/analyses/` (Phase-B records), `data/source_meta/` (Phase-A metadata), and the Phase-A vault via the Phase-B query API.

**Owned elsewhere:** citation style, venue conventions, and length adaptation (Phase D); analysis, retrieval, and the corpus (Phases B and A).

---

## Open Questions

Genuinely unresolved; everything else in this document is settled.

- **[product]** **Is the thesis operator-supplied or engine-derived?** §7.1 makes it operator-supplied, which is the smallest thing that works and keeps Phase C a pure consumer. But the operator writing the thesis is also the operator deciding what the analyses add up to, which is arguably the paper's central intellectual act and exactly the act the tool exists to perform. An engine-derived thesis, proposed from the claim inventory and confirmed or overridden by the operator, is the obvious alternative. It is not built in v0 because it would need its own gate: a thesis the corpus cannot carry is the Principle-III failure at paper scale, and nothing here interrogates it. Resolve after the first real papers show whether the operator-supplied theses were any good.

  **Founder steer, 2026-08-01: "how the model responds as a thesis is the brand."** That does not settle the question, but it points at which way it should fall and it names the seam. The seam already exists and is not the input contract: §7.2's `plan.thesis_statement` is "the thesis as the paper will state it", emitted by the arc-planning pass. So even under an operator-supplied `thesis`, the engine is already the thing that turns an operator's question into the paper's stated claim — the difference between the two options is smaller than it looks, and it is entirely about how far the operator's wording constrains that pass. **The user puts an argument; the response is argumentative** — that is what `thesis_statement` and the lens (§7.1) exist to carry, and it is the property to measure on the first real papers rather than a fifth field to add to §7.1.
- **[eval]** **How many papers, across which tiers and which model combinations, make a meaningful coherence number?** Now that coherence is a sampled offline measurement rather than a per-run gate (§10.2), the sample shape is the whole question, and it is three questions stacked. **How many papers per stratum**: one paper's panel is one observation, and a rate over a single paper is not a system property. **How many strata, and cut where**: §7.13 requires more than one performance tier and more than one model combination, which is a floor and not a design; the tier cut points are an explicit stated tunable with no measured basis yet. **How many reviewers per paper**: resolution improves slowly with N, so the answer is probably 3 or 5 rather than 10, but nothing here measures it — and the cost premise has changed. Phase B's reviewing ran on a sealed Claude Code subagent at **no model cost**, so N is paid in wall clock rather than dollars (§9). That removes the reason a panel stays at 1, which is where both Phase-B rounds sat. The three interact, and the budget is one number spread across all of them: reviewers per paper, papers per stratum, and number of strata trade directly against each other. This is the main reason §10.2 sets no threshold on `argument_coherence_rate`. A threshold over a sample whose shape is unsettled would be a number about the sample, not about the system.
- **[design]** **May the drafter read chunk text, or only claims?** §7.4 gives it the claim inventory and no vault access, which is grounded-by-construction at its strictest and makes generate-then-cite structurally impossible. The cost is that the drafter writes from claim summaries rather than from the sources, and the prose may read thin or repetitive as a result. Allowing it to read the grounds text of claims already assigned to its section is a narrow relaxation that keeps the inventory as the boundary. **Per-section drafting (§4) changes the economics of this question rather than the principle**: a section's assigned claims are few, so their grounds text fits where the whole inventory's would not, and the relaxation is now cheap enough to test rather than merely argue about. It also makes the question urgent in a way it was not — Phase B measured that ~20 notes reach a model however many are supplied (P2-7), and a drafter reading claim summaries alone is exactly the compression that finding warns about, one layer up. Still an empirical question about the first drafts; now a cheap one to answer.
- **[product]** ~~**What happens when two named analysis records contradict each other?**~~ **RESOLVED by founder ruling (recorded here 2026-07-25).** The question was mis-framed. I listed four candidate answers (surface the conflict as a finding, treat it as a counter-position, refuse the paper, let the drafter choose and disclose) and asked which adjudication rule to adopt. None of them is right, because contradiction is not a condition to adjudicate. **Contradictory records are opposite arguments, the soul of the academic domain, and are understood as opposing claims or arguments within the context.** The disagreement is the scholarly substance, not a defect in the input. The ruling is therefore not a new rule but an existing principle applied one level up: charter Principle IV, which PHASE-B §7.8 already implements within a single analysis, lifted to hold across a set of them. Contradiction is never an intake rejection, never adjudicated, and never silently reconciled; both sides survive with their sources identified; a paper over opposing records is a contested paper and Principle IV binds it; and a new (b) claim may characterise the disagreement without declaring a winner beyond its grounds. Specified at §7.14, gated at §10.1, required at P0-14. *The reasoning is kept here rather than deleted, because the mis-framing is the instructive part: an adjudication question was really a case of a principle already in the charter.*
- **[engineering]** **What counts as a vendor?** §7.7 defines it as the lab that trained the model, not the API provider, which is correct and is the important half. The edges are unresolved: a model fine-tuned by one lab on another lab's base, a lab's model served under a partner's brand, and lab mergers all break a flat table. The static table is the right seam for now because it fails loudly on an unknown id rather than silently. Whether it needs to become something richer is a question for the first time the table cannot answer cleanly.
