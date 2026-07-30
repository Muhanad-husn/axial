# PRD — Axial: Phase C Paper Authorship

**Project:** Axial · **Version:** 1.0 · **Status:** Ratified · **Owner:** Operator (single-operator system)

**Inherits.** This PRD is the Phase-C phase spec under [`specs/CHARTER.md`](CHARTER.md), the product-wide behavioural constitution; its P0 criteria are the authorship-layer instance of the charter's five principles. Its substrate is Phase B, specified in [`specs/PHASE-B.md`](PHASE-B.md); Phase B is consumed here, never modified here, and never triggered from here. Phase A ([`specs/PRODUCT.md`](PRODUCT.md)) is consumed read-only beneath both. This spec does not restate or override the charter (charter §4).

**On the name.** Phase C is **Paper Authorship**. Phase B produces an analysis: a claim graph over one brief, marked, grounded, and banded. A stack of analyses is not a paper. Phase C takes a thesis question and a named set of existing Phase-B analysis records and produces a **paper**: a narrative arc across those analyses, plus the apparatus that makes it checkable. Its own contribution is cross-source synthesis on the (b) seam. Venue conventions, citation style, and length targets are Phase D.

**Self-sufficiency note.** This document is the complete build specification for Phase C v0. The input contract, the arc, the paper record, the apparatus, the acceptance criteria, the per-run rung-3 gates, and the offline coherence eval track are all here. Beyond the charter and the Phase-A/Phase-B contracts it consumes, it references no external file. Where a decision is genuinely unresolved it is listed under **Open Questions**; everything else is settled and should be built as written. Status flags mark tentative content: **[FIRM]** build as-is · **[TENTATIVE]** likely to shift after the first real papers.

---

## 0. What this is, in one paragraph

Phase C is a single-operator paper author driven through the `axial` CLI. It takes a **paper brief**, which is a thesis question plus a named set of Phase-B analysis records, and returns a **paper record** plus a rendered markdown paper. The claim inventory it draws on is already grounded, marked, and banded by Phase B, so authorship is assembly and arrangement rather than fresh evidence-gathering. Phase C's own new knowledge is a bounded set of new **(b) claims**: cross-source inferences that relate claims across two or more analysis records, which is what a paper actually contributes over the analyses beneath it. Around the drafting sit four cheap gates that run on every paper and can block its release: provenance integrity and counter-position presence, both mechanical, plus two narrow judged checks on the grounding and the labelling of the new (b) claims. Where the named records argue opposite sides, that disagreement is the scholarly substance rather than a defect: both sides survive into the paper with their sources identified, and the counter-position gate holds the result to charter Principle IV. Whether the argument actually holds together is a different question, and it is not answered per paper. It is **measured offline, on a sample**, by a panel of at least three frontier-model reviewers from a different vendor than the drafter, each seeing only a sealed packet and holding no tools with which to read anything else. That panel is an instrument for measuring the system's accuracy across performance tiers and model combinations, not a checkpoint every paper waits at, and its own numbers count for nothing until it has been shown to catch deliberately planted defects. The enforced standard is unchanged from every layer beneath: **accountability to grounds, with honest confidence** (charter §0).

---

## 1. Problem statement & context

Phase B solved the analysis layer. Given one brief, it returns a claim graph in which every claim is marked (a)/(b)/(c), carries resolvable grounds, and discloses a confidence band against a per-polity coverage map. What it does not do, deliberately, is write. A reader handed five analysis records has five answers to five questions and no argument.

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
2. **No format adaptation.** Venue conventions, house style, and length targets are **Phase D**. v0 renders one plain markdown paper.
3. **No citation style.** The apparatus is mechanical: markers that resolve, and a bibliography from recorded metadata. Chicago, APA, footnote-vs-endnote, and short-form subsequent citations are Phase D.
4. **No new speculation.** Phase C emits no new kind-(c) claims in v0. A (c) claim already present in a source record may be carried, marked, and cited; the drafter does not invent new ones. A paper's speculative conclusion is a real want and is P2, not v0.
5. **No corpus, schema, vault, or analysis-record modification.** Phase C reads `data/analyses/`, `data/source_meta/`, and the vault read-only, and writes only its own artifacts. A Phase-C run never writes to `data/analyses/`.
6. **No UI beyond the CLI.**
7. **No human referee.** No file, gate, or acceptance criterion in this phase may depend on academic-authored data (§9).
8. **No multi-paper orchestration or batching** in the authorship pipeline, beyond running one paper brief and inspecting it. The offline eval track (§10.2) reads a set of already-written papers, which is not orchestration: it produces no papers of its own.
9. **No per-run coherence gating.** No paper waits on a reviewer panel to be released. The four per-run gates (§10.1) are cheap and run on every paper; the coherence panel (§10.2) is an offline measuring instrument over a sample, and it blocks nothing.
10. **No adjudication between contradictory source records.** Phase C does not decide which of two opposing records is right, and does not reconcile them. It carries both, identifies their sources, and holds the result to charter Principle IV (§7.14).

---

## 4. Architecture principle

**The paper is assembled from settled claims; the system is measured by strangers.**

Two halves, and the split is the whole design. Note which noun each half takes: the *paper* is what gets assembled and gated, and the *system* is what gets measured.

**Assembly is bounded by an existing inventory.** Every claim the paper cites is either carried verbatim from a Phase-B analysis record, with its kind, grounds, and band intact, or is a new (b) claim that reasons across at least two claims drawn from at least two distinct records. The drafter cannot introduce evidence, because it has no path to any. It has no retrieval tools and no vault access: the claim inventory it is given is the whole world. This is generate-then-cite made structurally impossible rather than forbidden by instruction, which is the same move Phase B made at the tool-dispatch seam (PHASE-B §4).

**Judgment of the whole comes from outside, and it comes on a sample.** Every property that is cheap to check is checked on every paper: marker resolution, grounds resolution, band non-escalation, counter-position presence on a contested paper, bibliography completeness, and two narrow judged checks over the new (b) claims. The one property none of those reach is whether the argument holds together. That property is **measured, not gated**. A panel that never saw the repo, the specs, the prompts, or any seeded data reads a sample of finished papers, receives only the paper plus the evidence it cites, and reports how coherent the system's output is, broken out by performance tier and model combination. The panel's isolation is enforced by the harness that constructs its calls, not by anything written in its prompt: a model with file tools reads the repository regardless of what its instructions say. Isolation you ask for is not isolation.

The two halves run on different clocks, and that is deliberate. Release is a per-paper decision and must stay cheap. Accuracy is a property of the system and only appears across many papers, several tiers, and more than one model combination. Collapsing the second into the first would make every paper pay for a measurement that a single paper cannot produce.

Like every phase beneath it, the mechanism is domain-general and the content is data. No country-specific or venue-specific logic lives in `src/`.

---

## 5. System overview — the stages

**Five pipeline stages**, each independently testable. Stages 1, 4, and 5 are deterministic and make zero model calls. The coherence eval track is not a pipeline stage and is specified in §10.2.

1. **Paper-brief intake (deterministic).** Reads the paper brief (§7.1), resolves every named analysis record, verifies they share one `corpus_pin`, and rejects a brief naming a missing record, a refused record, or a mixed-pin set. Builds the **claim inventory**: every claim across every named record, keyed by `(brief_id, claim_id)`.
2. **Arc planning (model).** Emits the **paper plan** (§7.2): an ordered list of sections, each with a heading, an argumentative role, and the inventory claims assigned to it. No prose is written at this stage, and the plan is inspectable before any drafting call is paid for.
3. **Drafting (model, high tier + reasoning).** Writes the paper section by section from the plan, emitting prose with in-text citation markers and any new (b) claims it needs to relate material across records. The drafter sees the claim inventory and the plan. It has no tools.
4. **Claim assembly & citation indexing (deterministic).** Parses the drafted prose for markers, builds the citation index (§7.5), and assembles the record's `claims` list as exactly the claims cited. A marker naming an unknown claim is a hard failure here.
5. **Apparatus & rendering (deterministic).** Generates the bibliography from `data/source_meta/` for exactly the cited sources (§7.6), renders the markdown paper (§7.10), and writes the paper record (§7.3).

The pipeline ends here. A paper is releasable once the four per-run gates of §10.1 pass over its record, and none of them calls a reviewer. **Off the pipeline**, on its own cadence, sits the coherence eval track (§10.2): sealed-packet assembly (§7.7), the reviewer panel (§7.8), and the positive control that qualifies the panel before any of its numbers are trusted (§7.9), run over a stratified sample of already-written papers (§7.13).

---

## 6. Repository structure

Scaffold to this shape; adjust only with reason. Extends the Phase-A (`PRODUCT.md` §6) and Phase-B (`PHASE-B.md` §6) layouts; existing modules are unchanged.

```
src/axial/
  paper/        # paper-brief intake, claim inventory, arc plan, draft,
                # citation index, bibliography, render, persistence (stages 1-5)
  review/       # the OFFLINE coherence eval track (§10.2): sealed-packet
                # assembly, the reviewer panel, the positive control's plant
                # mutations. Never on the per-run pipeline path.
  gates/        # (existing) + the provenance-integrity gate (§10.1)
config/
  paper_briefs/
    dev/        # versioned dev paper briefs, driving every dry-run
evals/
  plants/       # positive-control plant specs: selectors + mutations only,
                # never prose and never chunk text (DEC-23)
  samples/      # coherence sample specs (§7.13): strata + paper ids only
data/
  papers/       # one paper record JSON + one rendered .md per run
  packets/      # runtime reviewer packets; assembled per eval run, never committed
tests/
```

`data/` is gitignored in full (DEC-23). `evals/plants/` and `evals/samples/` are committed and must stay content-free: selectors, strata, and ids, never prose and never chunk text (§7.9, §7.13).

The `paper/` and `review/` split is load-bearing rather than cosmetic. Nothing under `paper/` may import from `review/`, so the authorship pipeline cannot acquire a dependency on the panel, which is what keeps §3 non-goal 9 true by construction instead of by discipline.

---

## 7. Data & configuration contracts

### 7.1 The paper brief (input contract) **[FIRM]**

The phase's input, supplied as a versioned file. Shape:
`{paper_brief_id, thesis, analysis_ids[], title?}`.

- `thesis` — the paper's organizing question, free text. Required, non-empty after whitespace stripping.
- `analysis_ids` — a list of Phase-B `brief_id` values naming records under `data/analyses/`. Required and non-empty. Every id must resolve to an existing record; an unresolvable id is rejected at intake, naming the id, and **Phase C never runs Phase B to produce it** (§3 non-goal 1).
- `title` — optional working title for the rendered paper. When absent, the renderer uses the thesis.
- `paper_brief_id` — a stable, deterministic id over the brief's content, no randomness and no timestamps, so re-running the same paper brief is traceable.

Three intake rules, all mechanical and all blocking:

- **Pin agreement.** Every named record must carry the same `corpus_pin` (PHASE-B §7.12). A mixed-pin set is rejected, naming the disagreeing ids. Records produced against different corpora are not comparable, so a paper across them is not defensible.
- **No refusals.** A named record whose `interrogation.disposition` is `refuse` is rejected, naming the id. A refusal is a valid Phase-B outcome and a completed run; it is not material for a paper, because it carries no claims.
- **Schema agreement.** Every named record must carry the same `schema_version`. A mixed set is rejected.

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

`role` is exactly one of `setup`, `claim`, `evidence`, `counter-position`, `synthesis`. This vocabulary is **reused unchanged from the Phase-A `role_in_argument` axis** (PRODUCT.md Appendix F) rather than invented here: the substrate already tags chunks by argumentative move, and a paper's sections are the same moves at a larger scale.

Two mechanical constraints on a valid plan:

- **Order is meaningful.** `sections` is an ordered list, and the rendered paper follows it exactly. Rendering never reorders.
- **Counter-position presence.** At least one section carries `role: counter-position`, unless **every** named source record discloses `counter_position.corpus_one_sided: true` (PHASE-B §7.8), in which case the plan carries no counter-position section and the paper must render the one-sided disclosure instead. Neither present is a red flag, not a clean result (charter Principle IV), and fails intake of the plan. This is a cheap plan-time guard read off the source records alone; the authoritative check is the post-draft counter-position gate (§7.14, §10.1), which sees what the paper actually cited.

A section may carry an empty `assigned_claims` list only when its role is `setup`. Every other section must carry at least one.

### 7.3 The paper record (output contract) — the load-bearing artifact **[FIRM]**

One JSON per run at `data/papers/<paper_brief_id>.json`, the phase's analogue of the Phase-B analysis record. Shape is locked; no field is nullable except where stated.

```
{
  paper_brief_id, paper_brief,       # the brief (§7.1), verbatim
  corpus_pin,                        # the single shared pin of the source records
  schema_version,
  source_analyses: [ brief_id ],     # the records drawn on, in brief order
  plan,                              # the arc (§7.2)
  claims: [ <paper_claim> ],         # §7.4; exactly the claims cited in the prose
  citations: [ <citation> ],         # §7.5, in document order
  counter_position,                  # the PHASE-B §7.8 shape, reused unchanged (§7.14)
  coverage_map,                      # §7.8
  confidence: { overall_band, rationale },
  bibliography: [ <bib_entry> ],     # §7.6
  paper_markdown_path,               # the rendered paper written alongside
  model_by_pass,
  cost                               # per-pass tokens + dollars, PHASE-B §7.14 shape
}
```

`counter_position` reuses the PHASE-B §7.8 shape unchanged: `{present, stance, grounds[], corpus_one_sided, one_sided_reason}`. It is either the counter-position material carried into the paper, naming the section that states it and the source claims it is built from, or the explicit one-sided disclosure, carrying the source records that reported it. It is never absent. Where the named source records themselves argue opposite sides, this is the field that carries the opposition into the paper (§7.14).

`confidence.overall_band` is one of `high` / `medium` / `low` and may not exceed the **lowest** overall band among the named source records. `confidence.rationale` states the coverage counts behind it, drawn from `coverage_map`.

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
  confidence,                        # high | medium | low
  derived_from: [ paper_claim_id ]   # non-empty only for a new (b) claim
}
```

**A carried claim** is copied from the inventory with `kind`, `grounds`, and `confidence` **byte-identical** to the source record's claim, and `origin` naming where it came from. Its `text` may be re-worded for the paper's prose, but a re-worded carried (a) claim is still kind `a` and still carries its origin. **Phase C never restates an (a) claim as its own** (charter Principle II): re-voicing a source's assertion as the tool's inference is the laundering failure this phase exists to prevent.

**A new (b) claim** is Phase C's own contribution. It carries `kind: b`, `origin: null`, non-empty `grounds`, and a `derived_from` list of at least two `paper_claim_id`s that between them come from **at least two distinct `brief_id`s**. That is what makes it cross-source rather than a restatement, and it is mechanically checkable. Its `grounds` are the union of the grounds of the claims it derives from, so it points at real vault ids without the drafter ever touching the vault.

**No new (c) claims** in v0 (§3 non-goal 4). A carried (c) claim keeps `kind: c` and its origin.

**A new (b) claim may characterise a disagreement between source records, and may not settle it.** Where two named records argue opposite sides, a claim that names the disagreement, locates it, or says what the two positions turn on is genuine cross-source synthesis, and it is arguably the best contribution a paper built this way can make. What it may not do is declare a winner beyond what its grounds support. "Record A's position rests on evidence B's does not engage" is a claim with grounds. "Record A is correct" is a verdict, and no grounds in the inventory carry it. The distinction is the ordinary one every (b) claim already faces, and it is enforced by the same two gates: grounding of new (b) claims, and the (b)-seam mislabel check (§10.1). Both sides of the disagreement survive into the paper regardless, each carrying its `origin` (§7.14).

**The confidence ceiling.** Bands are ordered `low < medium < high`.

- A carried claim's band equals its origin's band. Not higher, and not lower either: silently downgrading is its own dishonesty.
- A new (b) claim's band is at most the **minimum** band among its `derived_from` claims. A synthesis is no stronger than the weakest thing holding it up.

Both rules are mechanical, both are hard, and a violation of either fails the provenance-integrity gate outright (§10.1).

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

**Nothing else.** No paper brief, no plan, no source analysis records, no trajectory, no coverage map internals, no spec text, no prompt history, no gate configuration, no other reviewer's verdict.

Four enforcement rules, all FIRM and all enforced by the harness rather than by prompt text.

- **No tools.** The reviewer call is constructed with an empty tool list. An agent with file tools will read the repository regardless of what its instructions say, so instruction is not a control here. Observable: the panel harness rejects any reviewer configuration carrying a non-empty tool list, before any call is made.
- **Different vendor.** Each reviewer's model must resolve to a different **vendor** than every model that generated the paper (`model_by_pass`). Vendor means the **lab that trained the model**, never the API provider that serves it: OpenRouter serves everything, so provider identity is not separation. The mapping is a static in-code table in the same spirit as `axial.llm.PRICE_TABLE_USD_PER_1K`: a manually-maintained snapshot, not a live service. **A model id absent from the table is a hard error, never assumed distinct.** A missing entry silently defeating the guard is exactly the failure the guard exists to prevent. The check runs before any reviewer call is made, mirroring `axial.gates.grounding.SelfGradingError`.
- **N >= 3, independent.** At least three reviewers, each an independent call. No reviewer sees another's packet, verdict, or existence.
- **Packets are never committed.** The packet contains verbatim chunk text from copyrighted books. It is written only under the gitignored `data/packets/`, and the packet writer refuses any destination outside that root (DEC-23).

**Why the vendor bar is stricter here than elsewhere.** The Phase-B grounding and attribution judges run under a different-model guard, not a different-vendor one, and that stays as it is. Those judges answer a narrow question against pinned text: does this passage support this sentence. The coherence judgment is open-ended and stylistic, and shared training priors survive within a model family. A sibling model finds the same arguments persuasive for the same reasons.

### 7.8 The reviewer verdict **[FIRM]**

Structured, never free prose. One per reviewer.

```
{
  reviewer_id, model, vendor,
  coherence_verdict,                 # coherent | coherent_with_reservations | incoherent
  findings: [ {
    finding_kind,
    section_id,                      # nullable
    paper_claim_id,                  # nullable
    statement                        # one sentence, the reviewer's reason
  } ]
}
```

`finding_kind` is exactly one of a closed vocabulary, which is what makes the positive control (§7.9) scoreable:

- `unsupported_claim` — the packet's own cited evidence does not support the claim.
- `strawman_counter_position` — the opposing position is stated at less than its strongest.
- `overconfident_band` — the disclosed band overstates what the cited evidence carries.
- `arc_break` — a section does not follow from the argument before it.
- `unmarked_inference` — a cross-source inference is presented as though a source asserted it.

An out-of-vocabulary `finding_kind` is a load error, never silently accepted, mirroring the closed-vocabulary contract in `axial.gates.adversarial`.

**Per-reviewer coherence score:** `coherent` = 1.0, `coherent_with_reservations` = 0.5, `incoherent` = 0.0. The eval report carries the mean across reviewers **and the spread** (§10.2). A single judge draw is a single draw.

A verdict belongs to the measurement run that produced it and to that run's frame (§7.13). It is never written back into the paper record (§7.3), and no paper record carries a field for it. A paper is not a thing that has a verdict; a measurement run over a sample of papers is.

### 7.9 The positive control (mandatory) **[FIRM]**

LLM judges are systematically generous, and they are sensitive to confident prose. A panel that never fails anything is indistinguishable from a panel that stopped reading. **No coherence number from §7.8 is trusted until the panel has caught deliberately planted defects at the current configuration.**

**Plants are transformations, never content.** A plant spec under `evals/plants/` names a selector and a mutation, and is applied at runtime to a real paper record. It carries no prose and no chunk text, which is what keeps `evals/` committable under DEC-23.

```
{ plant_id, defect_kind, selector, mutation }
```

Three plants are mandatory, one per defect class, and each mutation is content-free and deterministic:

1. **Mis-grounded claim** (`unsupported_claim`). Swap the `text` fields of two claims whose grounds resolve to **disjoint source sets**. Both claims now cite evidence that does not support them, with every grounds pointer still resolving. Selector: the first such disjoint pair in `paper_claim_id` order. This plant has two mutated targets, and a finding pointing at either one counts as pointing at the target.
2. **Strawman counter-position** (`strawman_counter_position`). Replace the counter-position section's assigned claims with the single lowest-band claim among them, discarding the rest. The opposing school is now represented by its weakest available evidence, which is a strawman by construction rather than by rewriting.
3. **Overconfident band** (`overconfident_band`). Raise to `high` the band of the claim touching the thinnest polity in `coverage_map`.

**Scoring.** Each planted variant is rendered and packeted exactly as a real paper is, and the same panel runs over it. A plant is **caught** when at least `ceil(N/2)` reviewers return a finding whose `finding_kind` matches the plant's `defect_kind` and whose `paper_claim_id` or `section_id` points at the mutated target. `positive_control_catch_rate` = plants caught / plants planted.

**The trust rule, mechanically enforced.** The **coherence eval report** (§10.2) carries `trusted: false` unless the positive control has been run against the same panel configuration (same reviewer models, same N) and passed. The untrustworthiness here is about the judge, not the corpus and not the paper.

This rule binds the eval report and nothing else. **No per-run gate report (§10.1) has a trust field that a panel could fill**, so no paper is ever held back, and no gate is ever reported untrusted, for want of a reviewer verdict. A report that named a missing panel verdict as its reason for being untrusted would be wrong by construction, because the panel is not on that path at all.

### 7.10 The rendered paper **[FIRM]**

Plain markdown at `data/papers/<paper_brief_id>.md`, rendered deterministically from the record. The same record renders the same markdown, byte for byte.

Contents, in order: title, thesis statement, the plan's sections in plan order with their prose and in-text markers, the counter-position section (or the one-sided disclosure), the confidence and coverage disclosure, the citation table, and the bibliography.

Two rules carried forward from the layer beneath, restated here because they bind on this artifact:

- **Every confidence band renders next to the counts that justify it** (PHASE-B §7.4, §7.10). A band rendered bare is a rendering failure.
- **Claim kind is legible.** Every entry in the citation table carries its claim's kind, so a reader can see which claims a source made and which the tool made. In the prose itself, the seam is carried by voice: a new (b) claim is written in the tool's own register and is never attributed to a source ("Smith argues" is available only to a carried (a) claim). Attribution-marker clutter in every sentence is not the mechanism; the citation table plus honest voicing is.

This is plain rendering only. Venue, length, and house style are Phase D (§3).

### 7.11 The coverage map and confidence, carried forward **[FIRM]**

The paper's `coverage_map` is the union of the source records' coverage maps over the polities the paper's cited claims actually touch, recomputed deterministically from the same `polities_touched` facet Phase B used (PHASE-B §7.7). It is a count, never a model judgment.

Where two source records disagree on a polity's `corpus_chunk_count`, the records were produced against the same pin (§7.1), so they cannot legitimately disagree. A disagreement is a hard error naming both records, not a value to average.

### 7.12 Per-pass model tiering **[TENTATIVE]**

Model choice and reasoning are per-pass settings carried in the existing `model_by_pass` / `reasoning_by_pass` seams (PRODUCT.md §7.9), never hardcoded. Starting assignments, to be proven by measurement on the dev paper briefs:

- **Drafting (stage 3)** — high tier, reasoning ON. The judgment-heavy once-per-paper call.
- **Arc planning (stage 2)** — a cheaper tier may suffice; it emits structure, not prose.
- **The reviewer panel (§10.2)** — frontier tier, and constrained by §7.7's vendor rule before any tier consideration applies. The panel's cost sits on the eval budget, not on the per-paper budget.

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

- **Performance tier.** The sample must span more than one tier, so a coherence number is not read off the system's best work alone. Tier is assigned from signals the paper record already carries: its `confidence.overall_band`, the count of new (b) claims, and the `grounding_support_rate` its per-run gate recorded. The exact cut points are a stated tunable, proven by inspection over the first real papers, in the discipline PHASE-B §7.7 and §7.8 already follow: state the tunable, prove it, then set it. A single-tier sample measures a tier, not a system.
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

**Reuse, and more of it than expected.** PHASE-B's predicate is already implemented over **claim grounds, not over the retrieval trajectory**: `axial.validators.counter_position.detect_contested` reads `record["claims"]`, takes the union of chunk-typed `grounds` pointers, resolves each through `get_chunk`, and inspects what those notes say. A Phase-C paper record carries `claims` with the same `grounds` shape pointing at the same real vault ids (§7.4, §7.5), so both existing arms apply to a paper record **unmodified**:

- `opposed_positions` — two of the paper's cited notes are different sides and one names the other's side in its `arguing_against` answer.
- `gather_disagreement` — a name the paper both rests on and cites evidence from carries a Gather disagreement section.

> **CORRECTED (Phase B v1 slice 05, issue #490, D3).** This paragraph was written against PHASE-B's v0 arms, `theory_school_spread` and `role_counter_position`, which counted tag axes Phase A v1 deleted and matched nothing against the v1 vault; the `contested_detection.min_distinct_theory_schools` knob went with them. The two arms above are what PHASE-B §7.8 now specifies. Nothing structural changes for Phase C — both arms still read a record's own `claims[].grounds` and resolve them through the vault, which is the property this section depends on — but the second arm additionally reads `record["trajectory"]`, which a Phase-C paper record must therefore carry or forgo.

This satisfies the no-vault-access constraint by construction: the resolution happens in the validator, which already reads the vault, and never in the drafter, which has no path to it (§4).

**What is genuinely new: a third arm, and it closes a real hole.** Both inherited arms read only what the paper **cited**. A drafter that simply declines to carry any opposing material produces a paper whose cited evidence spans one school, which both arms score as uncontested, which waives the counter-position requirement. That is laundering a contested question into a clean one by omission, and it is exactly the failure Principle IV names. So:

- `source_record_contested` **[new]** — fires when any **named source record** carries a `counter_position` section that is present-with-grounds or discloses `corpus_one_sided: true`, or when that record's own contested predicate fired. It reads the source records under `data/analyses/`, which the paper record already names in `source_analyses`.

This arm reads record fields only. **Zero vault reads and zero model calls**, and it fires from what the inputs contained rather than from what the drafter chose to keep. A paper whose sources argued both sides cannot become uncontested by dropping one side.

The predicate is the disjunction of the three arms, evaluated in the order above, and the fired signal is recorded on the report exactly as PHASE-B records it, so the rule can be tuned on evidence later.

**No new tunable.** The predicate reuses PHASE-B's existing `contested_detection.min_distinct_theory_schools` config key with the same default of 2, rather than introducing a Phase-C-specific one. The third arm is a boolean over fields that already exist and needs no threshold.

**Why this section is [TENTATIVE], and what would settle it.** Not the principle, which is FIRM and is the charter's. What is unproven is whether the third arm earns its place. If, over the first real papers, `source_record_contested` never fires alone (never without one of the two inherited arms also firing), it is dead weight and should be dropped. If it fires alone with any regularity, each instance is a paper that dropped its opposition and would otherwise have passed, and the arm is load-bearing. That inspection is the tuning, and it follows the discipline PHASE-B §7.7 and §7.8 already set: state the rule, prove it by inspection, then settle it.

## 8. Requirements

### Must-Have (P0)

**P0-1 Paper-brief intake and the claim inventory (charter Principle II).**
- [ ] Reads a versioned paper brief (§7.1), resolves every `analysis_ids` entry against `data/analyses/`, and builds the claim inventory keyed by `(brief_id, claim_id)`.
- [ ] Rejects, naming the offending id: an unresolvable record, a record whose disposition is `refuse`, a mixed `corpus_pin` set, and a mixed `schema_version` set.
- [ ] **Zero Phase-B invocations.** Observable: intake makes no call into the Phase-B brief pipeline, and a paper brief naming an un-run brief fails with an error telling the operator to run it through Phase B first.

**P0-2 Arc planning before prose (charter Principle II).**
- [ ] Emits the §7.2 paper plan: ordered sections with headings, roles from the `role_in_argument` vocabulary, and claims assigned from the inventory. Observable: the plan is produced and inspectable with zero drafting calls made.
- [ ] At least one section carries `role: counter-position`, unless every named source record discloses `corpus_one_sided: true`, in which case the paper renders that disclosure. Neither present fails plan validation (charter Principle IV).

**P0-3 Drafting from the inventory, with no retrieval path (charter Principle I).**
- [ ] The drafter writes prose per section from the plan and the inventory, and has **no tools**: no vault query API, no file access, no web. Observable: the drafting call is constructed with an empty tool list, and the drafter cannot introduce a grounds pointer that was not already in the inventory.
- [ ] New (b) claims are emitted with `kind: b`, `origin: null`, and a `derived_from` list spanning at least two distinct source `brief_id`s (§7.4). Observable: a new claim derived from a single record fails validation.
- [ ] No new (c) claims are emitted (§3 non-goal 4).

**P0-4 The confidence ceiling (charter Principle V).**
- [ ] A carried claim's `kind`, `grounds`, and `confidence` are identical to its origin's. Observable: a record in which any carried claim's band differs from its origin fails the provenance-integrity gate.
- [ ] A new (b) claim's band is at most the minimum band among its `derived_from` claims. Observable: a `high`-band (b) claim derived from a `medium` and a `low` claim fails.
- [ ] The paper's `confidence.overall_band` is at most the lowest overall band among the named source records.

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
- [ ] Phase C's new (b) claims are scored by the **existing grounding judge** in `src/axial/gates/grounding.py`: its prompt, verdict vocabulary, unresolvable-grounds error, and self-grading guard are reused unchanged. The only Phase-C-specific part is the claim selector, which selects new (b) claims where the Phase-B gate selects kind-(a) claims. The judge's self-grading guard is re-anchored to Phase C's drafting pass rather than the Phase-B synthesis pass.
- [ ] The `b_seam_mislabel_rate` judged check in `src/axial/gates/attribution.py` is reused unmodified over the paper record's claims. It is the check that catches Phase C restating an (a) claim as its own inference, so no second judge seam is invented for that rule.

**P0-10 The sealed-packet reviewer panel (offline eval instrument; charter Principle V, §10.2).**
- [ ] **The panel is off the pipeline and blocks nothing.** Observable: `axial paper draft` completes end to end with zero reviewer calls and zero packets assembled, and no module under `src/axial/paper/` imports from `src/axial/review/`.
- [ ] A run reads a committed sample spec (§7.13) spanning **more than one performance tier and more than one model combination**, and reports one coherence figure per stratum. Observable: a single-tier or single-model-combination sample is rejected, naming which axis is unstratified; and no run emits a pooled system-wide mean.
- [ ] The report states its full frame: `sample_id`, paper ids, strata and tiers, model combinations, panel configuration, and `corpus_pin`. Observable: a report is never produced without a frame.
- [ ] The packet carries exactly the §7.7 contents and nothing else. Observable: a test asserts the assembled packet's keys against the contract and fails on any addition.
- [ ] Reviewer calls are constructed with an **empty tool list**, enforced by the harness. Observable: the harness rejects a reviewer configuration carrying any tool, before any call is made.
- [ ] Each reviewer's model resolves to a **different vendor** than every generating pass; a model id absent from the vendor table is a hard error, raised before any call. Observable: zero reviewer calls are made when the vendor guard fires.
- [ ] At least **three** independent reviewers run; no reviewer sees another's packet or verdict.
- [ ] Each returns the structured §7.8 verdict. Free prose is not accepted, and an out-of-vocabulary `finding_kind` is a load error.
- [ ] Packets are written only under `data/packets/`, and the writer refuses any destination outside the gitignored data root (DEC-23).

**P0-11 The positive control (the instrument's own admission criterion).**
- [ ] The three §7.9 plants are implemented as **content-free, deterministic record mutations** driven by specs under `evals/plants/`. Observable: no committed plant file contains prose or chunk text.
- [ ] Each planted variant is rendered and packeted exactly as a real paper is, and scored by the same panel. A plant is caught when at least `ceil(N/2)` reviewers return a matching `finding_kind` pointing at the mutated target.
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
- [ ] The §7.14 contested predicate reuses `axial.validators.counter_position`'s two existing arms unchanged over the paper record's claim grounds, and adds the third `source_record_contested` arm. Observable: a paper whose source records carried opposing positions is flagged contested **even when the drafter cited only one side**, which is the hole the third arm exists to close.
- [ ] The third arm is computed with **zero vault reads and zero model calls**, from the named source records' own fields. Observable: it is produced in tests with no LLM client present and no vault directory configured.
- [ ] A **mechanical** per-run gate blocks a contested paper carrying neither a present-with-grounds counter-position nor a one-sidedness disclosure with a reason (§10.1). An uncontested paper is excluded from the denominator, never counted as a pass. Observable: a contested paper with neither fails; an uncontested paper with neither passes.
- [ ] A new (b) claim may characterise a disagreement and may not declare a winner beyond its grounds (§7.4). This is enforced by the existing grounding and (b)-seam gates, with no new judge seam.

### Nice-to-Have (P1)

- **P1-1** A per-section drafting log recording which inventory claims the drafter considered and passed over, the authorship analogue of PHASE-B's trajectory log.
- **P1-2** Reviewer-finding aggregation across papers: which `finding_kind`s recur, and on which sections, so a systematic drafting weakness is visible rather than merely suspected.
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
| **Grounding of new (b) claims** | Principle I | `grounding_support_rate` over Phase C's new (b) claims, judged by the existing `axial.gates.grounding` judge anchored to resolved grounds text | **≥ 0.90** |
| **(b)-seam mislabel rate** | Principle II | `b_seam_mislabel_rate` over the paper record's (b) claims, via the existing judged check in `axial.gates.attribution` | **≤ 0.05** |
| **Counter-position presence** | Principle IV | `counter_position_presence_rate` = share of **contested** papers (§7.14's three-arm predicate) whose `counter_position` is present-with-grounds or discloses one-sidedness with a reason. Mechanical | **1.00**. A contested paper with neither is a red flag, not a clean result, and is blocked |

**Notes that bind.**

- **The two hard gates are hard.** Provenance completeness and confidence-upgrade count are mechanically checkable, so they are not sampled rates. One dangling marker fails. One upgraded band fails.
- **Reuse, do not re-derive.** The grounding gate reuses `src/axial/gates/grounding.py`'s judge (prompt, verdict vocabulary, unresolvable-grounds error, self-grading guard) with only its claim selector changed and its guard re-anchored to Phase C's drafting pass. The (b)-seam gate reuses `src/axial/gates/attribution.py`'s judged check wholesale. The counter-position gate reuses `src/axial/validators/counter_position.py`'s presence-or-disclosure check and both inherited contested arms unchanged, adding only §7.14's third arm. No second judge seam is invented for any of them.
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

---

## 11. Build phases

Bottom-up, so each layer stands on a tested one beneath it. Nothing in this ladder waits on a human.

**The pipeline ladder (steps 1–6).** Phase C is shippable at the end of step 6: papers are written, and every one of them passes the four per-run gates before release.

1. **Scaffolding, paper-brief intake, dev paper briefs.** Repo per §6; intake and the claim inventory (P0-1); land the dev paper briefs (P0-13). Deterministic, no model calls.
2. **Arc planning (P0-2)** and the inspect-before-spend `examine` affordance (P0-12).
3. **Drafting and new (b) claims (P0-3, P0-4)**, with the confidence ceiling enforced at assembly.
4. **Apparatus: citation index and bibliography (P0-5, P0-6).** Both deterministic and fully testable with no LLM client.
5. **Record, rendering, persistence (P0-7).**
6. **The four per-run gates: provenance integrity (P0-8), the reused grounding / (b)-seam gates (P0-9), and the counter-position gate (P0-14).** This closes the release path.

**The eval track (steps 7–9), a separate ladder.** It measures the system built above and gates none of it. It can be built after step 6, or in parallel by a second worker once step 5 lands, because it consumes finished paper records and touches no pipeline module. It has no place in the release path and must not be sequenced as though a paper waits on it.

7. **Sample spec and stratification (§7.13, P0-10).** Deterministic. Needs enough real papers to stratify, so it follows the first real drafting runs rather than preceding them.
8. **Sealed-packet harness and the panel (P0-10).** The isolation, vendor, and no-pooling guards are all testable without spending a single real reviewer call.
9. **Positive control (P0-11).** Only after this passes does any coherence number from step 8 get reported trusted.

---

## 12. Dependencies, preconditions & tech stack

**Preconditions for the authorship pipeline (steps 1–6):**

- **Phase-B analysis records** under `data/analyses/`, at least three sharing one corpus pin, produced by the operator running dev briefs through Phase B. Phase C cannot produce them (§3 non-goal 1).
- **The source-metadata records** at `data/source_meta/<source_id>.json` (PRODUCT.md §7.12, §7.13), for every source the cited claims reach. A source with no metadata record renders as a stated absence rather than failing the run, but a corpus with no records at all makes the bibliography vacuous.
- **The Phase-A vault**, read-only, for resolving grounds pointers.

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
- **[eval]** **How many papers, across which tiers and which model combinations, make a meaningful coherence number?** Now that coherence is a sampled offline measurement rather than a per-run gate (§10.2), the sample shape is the whole question, and it is three questions stacked. **How many papers per stratum**: one paper's panel is one observation, and a rate over a single paper is not a system property. **How many strata, and cut where**: §7.13 requires more than one performance tier and more than one model combination, which is a floor and not a design; the tier cut points are an explicit stated tunable with no measured basis yet. **How many reviewers per paper**: cost is linear in N and resolution improves slowly, so the answer is probably 3 or 5 rather than 10, but nothing here measures it. The three interact, and the budget is one number spread across all of them: reviewers per paper, papers per stratum, and number of strata trade directly against each other. This is the main reason §10.2 sets no threshold on `argument_coherence_rate`. A threshold over a sample whose shape is unsettled would be a number about the sample, not about the system.
- **[design]** **May the drafter read chunk text, or only claims?** §7.4 gives it the claim inventory and no vault access, which is grounded-by-construction at its strictest and makes generate-then-cite structurally impossible. The cost is that the drafter writes from claim summaries rather than from the sources, and the prose may read thin or repetitive as a result. Allowing it to read the grounds text of claims already assigned to its section is a narrow relaxation that keeps the inventory as the boundary. Whether it is needed is an empirical question about the first drafts.
- **[product]** ~~**What happens when two named analysis records contradict each other?**~~ **RESOLVED by founder ruling (recorded here 2026-07-25).** The question was mis-framed. I listed four candidate answers (surface the conflict as a finding, treat it as a counter-position, refuse the paper, let the drafter choose and disclose) and asked which adjudication rule to adopt. None of them is right, because contradiction is not a condition to adjudicate. **Contradictory records are opposite arguments, the soul of the academic domain, and are understood as opposing claims or arguments within the context.** The disagreement is the scholarly substance, not a defect in the input. The ruling is therefore not a new rule but an existing principle applied one level up: charter Principle IV, which PHASE-B §7.8 already implements within a single analysis, lifted to hold across a set of them. Contradiction is never an intake rejection, never adjudicated, and never silently reconciled; both sides survive with their sources identified; a paper over opposing records is a contested paper and Principle IV binds it; and a new (b) claim may characterise the disagreement without declaring a winner beyond its grounds. Specified at §7.14, gated at §10.1, required at P0-14. *The reasoning is kept here rather than deleted, because the mis-framing is the instructive part: an adjudication question was really a case of a principle already in the charter.*
- **[engineering]** **What counts as a vendor?** §7.7 defines it as the lab that trained the model, not the API provider, which is correct and is the important half. The edges are unresolved: a model fine-tuned by one lab on another lab's base, a lab's model served under a partner's brand, and lab mergers all break a flat table. The static table is the right seam for now because it fails loudly on an unknown id rather than silently. Whether it needs to become something richer is a question for the first time the table cannot answer cleanly.
