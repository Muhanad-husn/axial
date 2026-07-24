# PRD — Axial: Phase C Paper Authorship

**Project:** Axial · **Version:** 1.0 · **Status:** Ratified · **Owner:** Operator (single-operator system)

**Inherits.** This PRD is the Phase-C phase spec under [`specs/CHARTER.md`](CHARTER.md), the product-wide behavioural constitution; its P0 criteria are the authorship-layer instance of the charter's five principles. Its substrate is Phase B, specified in [`specs/PHASE-B.md`](PHASE-B.md); Phase B is consumed here, never modified here, and never triggered from here. Phase A ([`specs/PRODUCT.md`](PRODUCT.md)) is consumed read-only beneath both. This spec does not restate or override the charter (charter §4).

**On the name.** Phase C is **Paper Authorship**. Phase B produces an analysis: a claim graph over one brief, marked, grounded, and banded. A stack of analyses is not a paper. Phase C takes a thesis question and a named set of existing Phase-B analysis records and produces a **paper**: a narrative arc across those analyses, plus the apparatus that makes it checkable. Its own contribution is cross-source synthesis on the (b) seam. Venue conventions, citation style, and length targets are Phase D.

**Self-sufficiency note.** This document is the complete build specification for Phase C v0. The input contract, the arc, the paper record, the apparatus, the sealed-packet reviewer panel, the acceptance criteria, and the rung-3 gates are all here. Beyond the charter and the Phase-A/Phase-B contracts it consumes, it references no external file. Where a decision is genuinely unresolved it is listed under **Open Questions**; everything else is settled and should be built as written. Status flags mark tentative content: **[FIRM]** build as-is · **[TENTATIVE]** likely to shift after the first real papers.

---

## 0. What this is, in one paragraph

Phase C is a single-operator paper author driven through the `axial` CLI. It takes a **paper brief**, which is a thesis question plus a named set of Phase-B analysis records, and returns a **paper record** plus a rendered markdown paper. The claim inventory it draws on is already grounded, marked, and banded by Phase B, so authorship is assembly and arrangement rather than fresh evidence-gathering. Phase C's own new knowledge is a bounded set of new **(b) claims**: cross-source inferences that relate claims across two or more analysis records, which is what a paper actually contributes over the analyses beneath it. Around the drafting sit mechanical gates the model cannot reach: every citation-bearing sentence must trace to a real claim, and no claim may carry a higher confidence band than the record it came from. The one judgment that cannot be mechanized, whether the argument holds together, is delegated outward to a panel of at least three frontier-model reviewers from a different vendor than the drafter, each of which sees only a sealed packet and has no tools with which to read anything else. That panel is trusted only after it has been shown to catch deliberately planted defects. The enforced standard is unchanged from every layer beneath: **accountability to grounds, with honest confidence** (charter §0).

---

## 1. Problem statement & context

Phase B solved the analysis layer. Given one brief, it returns a claim graph in which every claim is marked (a)/(b)/(c), carries resolvable grounds, and discloses a confidence band against a per-polity coverage map. What it does not do, deliberately, is write. A reader handed five analysis records has five answers to five questions and no argument.

The gap Phase C closes is the arc. A paper is not a concatenation of findings. It states a thesis, orders material so that each section earns the next, states the opposing school at its strongest, and carries apparatus that lets a reader check any sentence. The value the operator wants is the charter's framing at its full scale: original comparative-historical scholarship, produced rather than retrieved (charter §0).

Three failure modes govern this phase, and all three are invisible in fluent prose.

**Laundering by re-voicing.** The easiest way to write a paper from analyses is to restate their (a) claims in the paper's own voice. The result reads as the tool's synthesis while contributing nothing, and it erases the (b) seam the charter makes non-negotiable (Principle II). Restatement is not synthesis.

**Confidence inflation across a layer boundary.** A claim disclosed as `low` in a Phase-B record, quoted into a paper's argument and surrounded by confident prose, reads as settled. Nothing in the prose carries the band forward. The band must survive the copy, and it must survive the inference built on top of it.

**Coherence without an oracle.** The mechanical checks in this phase are all local: this sentence traces to that claim, this band did not rise. None of them can tell whether section 4 follows from section 3, or whether the counter-position is a steelman or a puppet. That judgment needs a reader who was not in the room. Until 2026-07-24 the plan was a human referee. There will not be one (§9). The replacement has to be at least as adversarial as the thing it replaces, which is why it is sealed, multi-vendor, plural, and positive-controlled.

This PRD covers **Phase C (authorship) only**. It does not cover analysis (Phase B owns it), format adaptation (Phase D), or any change to the corpus, schema, or analysis records.

---

## 2. Goals

1. **A narrative arc over existing analyses.** Produce a paper whose sections are planned before any prose is written, each section built from named claims already present in the source analysis records (charter Principle II, grounded by construction).
2. **New knowledge only on the (b) seam.** Phase C's own contribution is cross-source inference relating claims across two or more analysis records, always marked as the tool's inference, never voiced as a source assertion (charter Principle II).
3. **No claim outranks its source.** A carried claim keeps its band exactly; a new (b) claim never exceeds the weakest claim it stands on. Confidence disclosure survives the layer boundary intact (charter Principle V).
4. **Mechanical apparatus.** In-text citation markers that resolve claim to grounds to chunk to source, and a bibliography generated from `source_meta` for exactly the sources cited. One plain format, deterministic, no style engine.
5. **The counter-position survives into the paper.** The opposing school is stated at its strongest in the paper itself, or the paper explicitly discloses that its source records found the corpus one-sided (charter Principle IV).
6. **Coherence judged from outside, and the judge itself is tested.** A sealed-packet panel of at least three reviewers from a different vendor than the drafter, whose number is untrusted until a positive control proves the panel catches planted defects (charter Principle V, §2 rung 3).
7. **No dependency on human-authored referee data.** The phase builds, runs, and gates end to end with no academic in the loop, permanently (§9).

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
8. **No multi-paper orchestration or batching** beyond running one paper brief and inspecting it.

---

## 4. Architecture principle

**The paper is assembled from settled claims, then judged by strangers.**

Two halves, and the split is the whole design.

**Assembly is bounded by an existing inventory.** Every claim the paper cites is either carried verbatim from a Phase-B analysis record, with its kind, grounds, and band intact, or is a new (b) claim that reasons across at least two claims drawn from at least two distinct records. The drafter cannot introduce evidence, because it has no path to any. It has no retrieval tools and no vault access: the claim inventory it is given is the whole world. This is generate-then-cite made structurally impossible rather than forbidden by instruction, which is the same move Phase B made at the tool-dispatch seam (PHASE-B §4).

**Judgment of the whole comes from outside.** Every property that can be checked mechanically is checked in code: marker resolution, grounds resolution, band non-escalation, counter-position presence, bibliography completeness. The one property that cannot is whether the argument holds together. That is delegated to a panel that never saw the repo, the specs, the prompts, or any seeded data, and that receives only the paper plus the evidence it cites. The panel's isolation is enforced by the harness that constructs its calls, not by anything written in its prompt: a model with file tools reads the repository regardless of what its instructions say. Isolation you ask for is not isolation.

Like every phase beneath it, the mechanism is domain-general and the content is data. No country-specific or venue-specific logic lives in `src/`.

---

## 5. System overview — the stages

Seven stages, each independently testable. Stages 1, 5, and 6a are deterministic and make zero model calls.

1. **Paper-brief intake (deterministic).** Reads the paper brief (§7.1), resolves every named analysis record, verifies they share one `corpus_pin`, and rejects a brief naming a missing record, a refused record, or a mixed-pin set. Builds the **claim inventory**: every claim across every named record, keyed by `(brief_id, claim_id)`.
2. **Arc planning (model).** Emits the **paper plan** (§7.2): an ordered list of sections, each with a heading, an argumentative role, and the inventory claims assigned to it. No prose is written at this stage, and the plan is inspectable before any drafting call is paid for.
3. **Drafting (model, high tier + reasoning).** Writes the paper section by section from the plan, emitting prose with in-text citation markers and any new (b) claims it needs to relate material across records. The drafter sees the claim inventory and the plan. It has no tools.
4. **Claim assembly & citation indexing (deterministic).** Parses the drafted prose for markers, builds the citation index (§7.5), and assembles the record's `claims` list as exactly the claims cited. A marker naming an unknown claim is a hard failure here.
5. **Apparatus & rendering (deterministic).** Generates the bibliography from `data/source_meta/` for exactly the cited sources (§7.6), renders the markdown paper (§7.10), and writes the paper record (§7.3).
6. **Sealed-packet review (6a deterministic assembly, 6b model panel).** Assembles one packet per reviewer (§7.7): the rendered paper plus the resolved grounds text of every cited claim, and nothing else. Runs at least three reviewers, each in an independent call, each under a vendor-separation guard, each returning a structured verdict (§7.8).
7. **Positive control (deterministic mutation + the same panel).** Applies content-free defect plants to a real paper record, runs the panel over each planted variant, and scores whether the plants were caught (§7.9). Until this has run and passed at the current configuration, the coherence number from stage 6 is reported untrusted.

---

## 6. Repository structure

Scaffold to this shape; adjust only with reason. Extends the Phase-A (`PRODUCT.md` §6) and Phase-B (`PHASE-B.md` §6) layouts; existing modules are unchanged.

```
src/axial/
  paper/        # paper-brief intake, claim inventory, arc plan, draft,
                # citation index, bibliography, render, persistence (stages 1-5)
  review/       # sealed-packet assembly, the reviewer panel, the positive
                # control's plant mutations (stages 6-7)
  gates/        # (existing) + provenance-integrity and argument-coherence gates
config/
  paper_briefs/
    dev/        # versioned dev paper briefs, driving every dry-run
evals/
  plants/       # positive-control plant specs: selectors + mutations only,
                # never prose and never chunk text (DEC-23)
data/
  papers/       # one paper record JSON + one rendered .md per run
  packets/      # runtime reviewer packets; assembled per run, never committed
tests/
```

`data/` is gitignored in full (DEC-23). `evals/plants/` is committed and must stay content-free (§7.9).

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
- **Counter-position presence.** At least one section carries `role: counter-position`, unless **every** named source record discloses `counter_position.corpus_one_sided: true` (PHASE-B §7.8), in which case the plan carries no counter-position section and the paper must render the one-sided disclosure instead. Neither present is a red flag, not a clean result (charter Principle IV), and fails intake of the plan.

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
  counter_position,                  # §7.9 of PHASE-B, carried or disclosed (below)
  coverage_map,                      # §7.8
  confidence: { overall_band, rationale },
  bibliography: [ <bib_entry> ],     # §7.6
  paper_markdown_path,               # the rendered paper written alongside
  model_by_pass,
  cost                               # per-pass tokens + dollars, PHASE-B §7.14 shape
}
```

`counter_position` is either the counter-position material carried into the paper, naming the section that states it and the source claims it is built from, or the explicit one-sided disclosure permitted by §7.2, carrying the source records that reported it. It is never absent.

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

**The confidence ceiling.** Bands are ordered `low < medium < high`.

- A carried claim's band equals its origin's band. Not higher, and not lower either: silently downgrading is its own dishonesty.
- A new (b) claim's band is at most the **minimum** band among its `derived_from` claims. A synthesis is no stronger than the weakest thing holding it up.

Both rules are mechanical, both are hard, and a violation of either fails the provenance-integrity gate outright (§10).

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

The panel's entire input. Assembled at runtime, in memory, per reviewer.

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

**Per-reviewer coherence score:** `coherent` = 1.0, `coherent_with_reservations` = 0.5, `incoherent` = 0.0. The gate reports the mean across reviewers **and the spread** (§10). A single judge draw is a single draw.

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

**The trust rule, mechanically enforced.** The argument-coherence gate reports `trusted: false` unless the positive control has been run against the same panel configuration (same reviewer models, same N) and passed. This mirrors the existing `trusted` computation in `axial.gates.harness`: a dry-run number is never a trusted number, and here the untrustworthiness is about the judge rather than the corpus.

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
- **The reviewer panel (stage 6)** — frontier tier, and constrained by §7.7's vendor rule before any tier consideration applies.

---

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

**P0-9 Grounding and (b)-seam gates, reusing Phase B (charter Principles I, II).**
- [ ] Phase C's new (b) claims are scored by the **existing grounding judge** in `src/axial/gates/grounding.py`: its prompt, verdict vocabulary, unresolvable-grounds error, and self-grading guard are reused unchanged. The only Phase-C-specific part is the claim selector, which selects new (b) claims where the Phase-B gate selects kind-(a) claims. The judge's self-grading guard is re-anchored to Phase C's drafting pass rather than the Phase-B synthesis pass.
- [ ] The `b_seam_mislabel_rate` judged check in `src/axial/gates/attribution.py` is reused unmodified over the paper record's claims. It is the check that catches Phase C restating an (a) claim as its own inference, so no second judge seam is invented for that rule.

**P0-10 The sealed-packet reviewer panel (charter Principle V, §2 rung 3).**
- [ ] The packet carries exactly the §7.7 contents and nothing else. Observable: a test asserts the assembled packet's keys against the contract and fails on any addition.
- [ ] Reviewer calls are constructed with an **empty tool list**, enforced by the harness. Observable: the harness rejects a reviewer configuration carrying any tool, before any call is made.
- [ ] Each reviewer's model resolves to a **different vendor** than every generating pass; a model id absent from the vendor table is a hard error, raised before any call. Observable: zero reviewer calls are made when the vendor guard fires.
- [ ] At least **three** independent reviewers run; no reviewer sees another's packet or verdict.
- [ ] Each returns the structured §7.8 verdict. Free prose is not accepted, and an out-of-vocabulary `finding_kind` is a load error.
- [ ] Packets are written only under `data/packets/`, and the writer refuses any destination outside the gitignored data root (DEC-23).

**P0-11 The positive control (mandatory before any trusted panel number).**
- [ ] The three §7.9 plants are implemented as **content-free, deterministic record mutations** driven by specs under `evals/plants/`. Observable: no committed plant file contains prose or chunk text.
- [ ] Each planted variant is rendered and packeted exactly as a real paper is, and scored by the same panel. A plant is caught when at least `ceil(N/2)` reviewers return a matching `finding_kind` pointing at the mutated target.
- [ ] The argument-coherence gate reports `trusted: false` unless the positive control has passed against the same panel configuration. Observable: a coherence report produced without a passing control is never marked trusted, whatever its value.

**P0-12 CLI surface with inspect-before-spend.**
- [ ] `axial paper draft <paper_brief_file>` runs stages 1 through 5 and writes the record and rendered paper.
- [ ] `axial paper examine <paper_brief_file>` runs intake and arc planning and reports the plan, the claim inventory, and the sections' assigned claims **without the drafting call**, analogous to `axial brief examine` (PHASE-B P0-9). Observable: `examine` makes zero drafting calls.
- [ ] `axial paper review <paper_record>` assembles packets and runs the panel; the gates run through the existing `axial gate run <gate>` surface.

**P0-13 Dev paper briefs landed as versioned data.**
- [ ] At least three dev paper briefs land under `config/paper_briefs/dev/` in the §7.1 shape, each naming Phase-B dev briefs that have actually been run, so every dry-run in this phase is reproducible from the repo. Observable: the dev paper briefs drive the harnesses with no operator-local file.

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

**What the panel is not.** It is not a correctness oracle. Correctness at the frontier of a synthesis has no answer key, which is the charter's founding observation (charter §0). The panel judges whether an argument holds together over the evidence it was shown. That is checkable, and it is the property the mechanical gates cannot reach. It is not, and must not be reported as, a claim that the paper is right.

---

## 10. Success metrics & rung-3 gates

These are the **rung-3 ship-blocking eval gates** for the layer Phase C builds (charter §2). Trust composes multiplicatively across layers: Phase-A's κ eval is rung 1, Phase-B's five gates sit above it, and these sit above those. A flawless paper over a mis-attributed analysis is worthless. The principles behind each gate are **FIRM**; the numeric thresholds are **TUNABLE** starting hypotheses.

| Gate | Charter | Metric | Starting threshold [TENTATIVE] |
|------|---------|--------|--------------------------------|
| **Provenance integrity** | Principle II | `provenance_completeness` = share of citation markers resolving to a record claim with resolvable grounds; plus `confidence_upgrade_count` = claims violating the §7.4 ceiling | completeness = **1.00** and upgrades = **0**; both mechanical hard gates, no sampling |
| **Grounding of new (b) claims** | Principle I | `grounding_support_rate` over Phase C's new (b) claims, judged by the existing `axial.gates.grounding` judge anchored to resolved grounds text | **≥ 0.90** |
| **(b)-seam mislabel rate** | Principle II | `b_seam_mislabel_rate` over the paper record's (b) claims, via the existing judged check in `axial.gates.attribution` | **≤ 0.05** |
| **Argument coherence** | Principles IV, V | `argument_coherence_rate` = mean per-reviewer coherence score across N ≥ 3 sealed-packet reviewers; `reviewer_spread` = max − min of those scores | rate **≥ 0.67**; spread **≤ 0.50**; `trusted` only after the positive control passes |
| **Positive control** | charter §2 | `positive_control_catch_rate` = planted defects caught by ≥ ⌈N/2⌉ reviewers, over the three §7.9 plants | **= 1.00** on three plants |

**Notes that bind.**

- **The two hard gates are hard.** Provenance completeness and confidence-upgrade count are mechanically checkable, so they are not sampled rates. One dangling marker fails. One upgraded band fails.
- **Reuse, do not re-derive.** The grounding gate reuses `src/axial/gates/grounding.py`'s judge (prompt, verdict vocabulary, unresolvable-grounds error, self-grading guard) with only its claim selector changed and its guard re-anchored to Phase C's drafting pass. The (b)-seam gate reuses `src/axial/gates/attribution.py`'s judged check wholesale. No second judge seam is invented for either.
- **The vendor bar applies to the panel only.** The grounding and (b)-seam judges keep the existing different-model guard. Those answer a narrow question against pinned text. The coherence judgment is open-ended, and that is where shared family priors bite (§7.7).
- **Report the spread, always.** The coherence gate reports mean and spread together, because the mean alone is ambiguous. Three reviewers scoring 0.5, 0.5, 0.5 and three scoring 1.0, 0.5, 0.0 both average 0.5. The first is a panel that agreed the paper has reservations. The second is a panel that could not agree at all, and its average describes none of its members. Reporting only the mean would make those two results indistinguishable.
- **`reviewer_spread`'s threshold is the weakest number in this table.** It is asserted before any panel has run, which is exactly the position `source_usage` was in at Phase B (PHASE-B §7.13). If the first panels show that legitimate papers routinely spread past 0.50, the honest move is to demote spread to disclosure-only rather than to loosen the number until it stops firing. That demotion is pre-authorized by this note.
- **Three plants is a small n.** `positive_control_catch_rate = 1.00` over three plants is a floor, not a demonstration of sensitivity. P1-3 adds two more classes. A panel that catches three obvious plants has not proven it catches a subtle one, and the control's own limits are stated in every report it produces.
- **No self-grading anywhere.** The drafting model never judges its own paper, never sits on the panel, and never supplies the vendor table entry that would let it.

---

## 11. Build phases

Bottom-up, so each layer stands on a tested one beneath it. Nothing in this ladder waits on a human.

1. **Scaffolding, paper-brief intake, dev paper briefs.** Repo per §6; intake and the claim inventory (P0-1); land the dev paper briefs (P0-13). Deterministic, no model calls.
2. **Arc planning (P0-2)** and the inspect-before-spend `examine` affordance (P0-12).
3. **Drafting and new (b) claims (P0-3, P0-4)**, with the confidence ceiling enforced at assembly.
4. **Apparatus: citation index and bibliography (P0-5, P0-6).** Both deterministic and fully testable with no LLM client.
5. **Record, rendering, persistence (P0-7).**
6. **Provenance-integrity gate (P0-8)** and the reused grounding / (b)-seam gates (P0-9).
7. **Sealed-packet harness and the panel (P0-10).** The harness's isolation and vendor guards are testable without spending a single real reviewer call.
8. **Positive control (P0-11).** Only after this passes does any coherence number get reported trusted.

---

## 12. Dependencies, preconditions & tech stack

**Preconditions (must exist for the build, not merely for trusted numbers):**

- **Phase-B analysis records** under `data/analyses/`, at least three sharing one corpus pin, produced by the operator running dev briefs through Phase B. Phase C cannot produce them (§3 non-goal 1).
- **The source-metadata records** at `data/source_meta/<source_id>.json` (PRODUCT.md §7.12, §7.13), for every source the cited claims reach. A source with no metadata record renders as a stated absence rather than failing the run, but a corpus with no records at all makes the bibliography vacuous.
- **The Phase-A vault**, read-only, for resolving grounds text into reviewer packets.
- **At least two vendors configured.** The vendor guard (§7.7) cannot be satisfied with a single-lab model roster, and this is a real operational precondition, not a formality.

**Explicitly not a precondition:** any academic-authored data. There is none and there will be none (§9).

**Stack.** Python, driven through the `axial` CLI. **Inference:** the existing provider clients, through the existing `model_by_pass` / `reasoning_by_pass` seams; drafting wants the high tier with reasoning ON, arc planning may run cheaper, the panel runs frontier tier under the vendor constraint. **No new inference dependency**, and no tool-calling at all in this phase: the drafter and the reviewers both run tool-free by design (§4, §7.7). **Substrate consumed read-only:** `data/analyses/` (Phase-B records), `data/source_meta/` (Phase-A metadata), and the Phase-A vault via the Phase-B query API.

**Owned elsewhere:** citation style, venue conventions, and length adaptation (Phase D); analysis, retrieval, and the corpus (Phases B and A).

---

## Open Questions

Genuinely unresolved; everything else in this document is settled.

- **[product]** **Is the thesis operator-supplied or engine-derived?** §7.1 makes it operator-supplied, which is the smallest thing that works and keeps Phase C a pure consumer. But the operator writing the thesis is also the operator deciding what the analyses add up to, which is arguably the paper's central intellectual act and exactly the act the tool exists to perform. An engine-derived thesis, proposed from the claim inventory and confirmed or overridden by the operator, is the obvious alternative. It is not built in v0 because it would need its own gate: a thesis the corpus cannot carry is the Principle-III failure at paper scale, and nothing here interrogates it. Resolve after the first real papers show whether the operator-supplied theses were any good.
- **[eval]** **What is the minimum reviewer-panel sample for a meaningful coherence number?** N = 3 yields a mean over four possible values, which is coarse, and a spread that is either 0, 0.5, or 1.0. Two sub-questions sit under this. First, how many reviewers: the cost is linear and the resolution improves slowly, so the answer is probably 3 or 5 rather than 10, but nothing here measures it. Second, how many *papers*: one paper's panel is one observation, and a coherence rate over a single paper is not a system property. Neither number can be set before the first panels run, and both are the reason §10's coherence thresholds are the softest in the table.
- **[design]** **May the drafter read chunk text, or only claims?** §7.4 gives it the claim inventory and no vault access, which is grounded-by-construction at its strictest and makes generate-then-cite structurally impossible. The cost is that the drafter writes from claim summaries rather than from the sources, and the prose may read thin or repetitive as a result. Allowing it to read the grounds text of claims already assigned to its section is a narrow relaxation that keeps the inventory as the boundary. Whether it is needed is an empirical question about the first drafts.
- **[product]** **What happens when two named analysis records contradict each other?** They share a corpus pin, so they read the same corpus, but two Phase-B runs over different briefs can still produce (a) claims that conflict. v0 has no adjudication rule: the drafter sees both in the inventory and nothing forces it to notice. The candidate answers are all plausible and none is obviously right: surface the conflict as a finding, treat it as a counter-position, refuse the paper, or let the drafter choose and disclose. This deserves a founder decision before it appears in a real paper rather than after.
- **[engineering]** **What counts as a vendor?** §7.7 defines it as the lab that trained the model, not the API provider, which is correct and is the important half. The edges are unresolved: a model fine-tuned by one lab on another lab's base, a lab's model served under a partner's brand, and lab mergers all break a flat table. The static table is the right seam for now because it fails loudly on an unknown id rather than silently. Whether it needs to become something richer is a question for the first time the table cannot answer cleanly.
