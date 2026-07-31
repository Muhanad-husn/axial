# PRD — Axial: Phase B Analysis Engine (Syria v1)

**Project:** Axial · **Version:** 2.0 (Phase B v1) · **Status:** Ready to build · **Date:** 2026-07-29 · **Owner:** Operator (single-operator system)

**Inherits.** This PRD is the Phase-B phase spec under [`specs/CHARTER.md`](CHARTER.md), the product-wide behavioural constitution; its P0 criteria are the analysis-layer instance of the charter's five principles. Its substrate is Phase A, specified in [`specs/PRODUCT.md`](PRODUCT.md); Phase A is consumed here, never modified here. This spec does not restate or override the charter (charter §4).

**On the name.** Phase B is the **Analysis Engine**. Phase A built the graph; Phase B is the first reasoning layer that stands on it. Given a *case* and a *request for analysis* (together, a **brief**), it produces a grounded analytical answer: it interrogates the brief, retrieves from the corpus anchored on the case, applies a theoretical lens and axial coding across sources, and emits claims each marked for what kind of claim it is, with a per-name coverage map and disclosed, calibrated confidence. The output is an **analysis, not a research paper**. Paper authorship is Phase C; format adaptation is Phase D.

**Why v2.** v0 retrieved by filtering closed-vocabulary tag axes. Phase A v1 deleted those axes and replaced them with a name layer: notes carry the interrogation's own open answers, and they meet each other on a page per name. Measured against the live vault on 2026-07-29, **four of v0's eight query tools return zero results**, and the four that work all require an id the caller already holds. `axial brief` was not producing poor answers; it could not reach the corpus at all. v1 applies the same inversion one layer up. Retrieval stops being a conjunction of filters and becomes traversal of the name layer: find the names a brief is about, read the notes that meet at them, follow what those notes say they argue against and who they cite.

**Self-sufficiency note.** This document is the complete build specification for Phase B v1. Everything required to scaffold and build the analysis engine — the architecture, the stages, the output contract, the query API, the acceptance criteria, and the eval gates — is contained here. Its single parent is the behavioural constitution in [`specs/CHARTER.md`](CHARTER.md), which governs *why* the engine is built as it is; beyond that one charter and the Phase-A substrate contracts it consumes, it references no external file. Where a decision is genuinely unresolved it is listed under **Open Questions**; everything else is settled and should be built as written. Status flags mark tentative content: **[FIRM]** build as-is · **[TENTATIVE]** likely to shift after the first real briefs · **[CONTESTED]** to be resolved before ship.

**How retired material is marked.** Phase B v1 retires several v0 mechanisms, following the convention `specs/PRODUCT.md` set. Nothing is deleted silently. A retired section, tool, criterion or rule keeps its number and heading, gains the word **STRUCK** in that heading or in bold at its head, and carries a note in this shape:

> **STRUCK (D1).** What is retired, in one clause. Where the replacement lives, or which slice owns the deletion.

`D1`–`D10` are the numbered decisions of the Phase B v1 design (`plans/phase-b-v1/README.md`), each carried by real text in this document. A struck item is dead contract: no builder implements it, no test pins it. Removing the code behind a struck item is its own slice, so a struck rule may still describe machinery that exists on disk today.

---

## 0. What this is, in one paragraph

Phase B is a single-operator analysis engine driven through the `axial` CLI. It takes a brief — a case plus a request for analysis — and returns a grounded analytical answer over the graph Phase A produced: ~30 processable sources, ~6,100 prose notes each carrying its own interrogation answers, one name page per surviving canonical name, a separate artifact pool, and one envelope per source. The middle of the engine is a **model-driven query agent** that plans and re-plans retrieval over a small, deterministic, LLM-free query API **over the name layer**. Around that agent sit **deterministic hard gates**: a brief-interrogation pre-pass that may bound or refuse the request, and post-pass validators that check attribution, counter-position, and coverage before an answer is released. The load-bearing artifact is a structured **analysis record** in which every claim is marked source-says, tool-infers-across-sources, or speculation, carries auditable pointers into the vault, and carries disclosed confidence. Correctness has no answer key at the frontier of a synthesis; the enforced standard is **accountability to grounds, with honest confidence** (charter §0).

---

## 1. Problem statement & context

Phase A solved substrate fidelity: clean text, structural trees, bounded notes, one open interrogation per note, and a name layer the corpus grew rather than a vocabulary decided in advance. It deliberately built no reasoning. A graph is not an answer. The value the operator wants is the charter's framing: give the system a case and a request, and get back original comparative-historical analysis that no single source made (charter §0).

Two failure modes govern this phase, and both are invisible in fluent prose. First, **ungrounded assertion**: an LLM asked for scholarship writes a confident claim from parametric memory and dresses it as a finding, laundering unvetted content into vetted-looking output (charter Principle I). Second, **generate-then-cite**: the model writes the synthesis first and hunts for citations after, so the citation decorates rather than founds the claim (charter Principle II). Both produce output that looks like success and is worthless. The cost of not solving them compounds: an analysis trusted because it reads well, resting on a claim the corpus never made, is worse than no analysis.

The engine's whole design follows from making those seams visible and checkable. This PRD covers **Phase B (analysis) only**. It does not cover paper authorship (Phase C), format adaptation (Phase D), or any change to the corpus or schema (Phase A owns ingestion).

---

## 2. Goals

1. **Grounded analytical answers, by construction.** Produce an analysis assembled from grounded moves, never generated then back-fitted with citations. Every claim is marked as one of the three kinds and carries auditable grounds (charter Principle II).
2. **The brief is interrogated, not obeyed.** A deterministic pre-pass surfaces smuggled premises, tests them against corpus coverage, and may bound or refuse the request. Bounding and refusal are first-class outputs, not errors (charter Principle III).
3. **Name-first retrieval, measured for recall (D1).** Retrieval is traversal of the name layer Phase A grew for exactly this: the canonical name index and its alias map, the member notes that meet at each name, and each note's own `arguing_against` and `citations` answers, plus the per-source envelope. **~~Tag-axis and facet filtering.~~ STRUCK (D1)** — the axes it filtered on no longer exist (`specs/PRODUCT.md` §7.1, Appendix C). No *chunk* embedding index ships in v1; recall is *measured* on the hard briefs (§3 non-goal 4, §9, Open Questions).
4. **Case-as-anchor, not case-as-fence.** A case anchors retrieval without fencing analysis to it. Corpus-grounded material about other polities that bears on the case is in scope, always labeled as the tool's cross-source inference (charter §3, Principle II).
5. **Disclosed, calibrated confidence and per-name coverage (D2).** Every answer discloses how well the corpus covers each name it touches, computed from the name pages' own member counts, and feeds that into a calibrated confidence disclosure (charter Principle V, §3). This is strictly wider than the per-polity map it replaces: it covers concepts, scholars, institutions and events, not only polities. A polity is a name whose `kind` is `country/state/place`; nothing special-cases it.
6. **No human referee in the loop.** The engine builds, runs, and is scored without an Academic. All five rung-3 gates are corpus-anchored and need no human judgment (§9). Answer quality is measured offline, on a sample, by the sealed-packet peer-reviewer panel (§9.4), which sits outside the pipeline entirely; every number it produces carries its disclosed ceiling.

---

## 3. Non-goals

Each is excluded deliberately; documenting them protects the architecture.

1. **No paper authorship.** The output is an analysis record plus a rendered answer, not a research paper with narrative arc and apparatus. Authorship is **Phase C**.
2. **No format adaptation.** Rendering to a specific venue, length, or house style is **Phase D**. This phase renders one plain markdown answer.
3. **No UI beyond the CLI.** The phase is driven through `axial` like every other phase. No web app, no notebook, no server.
4. **No chunk embedding / vector index.** Retrieval is deterministic traversal of the name layer. A *chunk* similarity index is a **named possible future addition, gated on demonstrated recall failure**: if measured recall on the hard briefs shows the name surface misses material a good answer needs, the index is reopened as a scoped follow-up (§9, Open Questions). It is not built speculatively.

   **D10 — reusing the name embeddings does not reopen this.** `find_names` (§7.5) reads the vectors Reconcile already built over **name surface forms** (`data/names/embeddings.lance`) as its last resolution tier. That is a different problem from chunk retrieval, on a different unit: the index is already built and paid for, and exact match demonstrably fails on the names briefs actually use — the index holds `Charles Tilly`, `Giorgio Agamben`, `Uğur Ümit Üngör` while briefs say Tilly, Agamben, Ungor. Hand-rolling a string matcher instead would be reinventing a wheel sitting in `data/names/`. Nothing here embeds, indexes or ranks a note's text, which is what this non-goal defers.
5. **No corpus or schema modification.** Phase A owns ingestion, interrogation, and the domain frame. Phase B reads the vault read-only. A gap found here routes to a Phase A issue under the DEC-55 rule — new issues come from using the product — never a Phase-B code patch.
6. **No multi-brief orchestration or batching** beyond what the CLI needs to run one brief, run the six-brief smoke set, and inspect either. Corpus-wide brief sweeps, scheduling, and caching across briefs are out of scope; the 30-brief sweep is retired (§9.0, D7).

---

## 4. Architecture principle

**A model-driven query agent wrapped in deterministic hard gates.**

The middle of the engine is an **agentic loop**: a model plans retrieval, calls a small fixed set of deterministic vault-query tools, inspects what came back, and re-queries when results are thin. A fixed retrieval pipeline was rejected precisely because thin results demand a second look that only an agent can decide to take. The agent's freedom is bounded on both sides by code the model cannot reach:

- **Before** the agent runs, a **brief-interrogation pre-pass** (Principle III) surfaces smuggled premises and may bound or refuse the request.
- **After** the synthesis, **deterministic validators** check attribution (Principle II), counter-position presence (Principle IV), and coverage/confidence disclosure (Principle V).

The validators are **code, not model judgment, wherever the property is mechanically checkable**: whether every claim carries a kind, whether every (a)/(b) claim's grounds resolve to real vault ids, whether a coverage map exists and a confidence disclosure is present. Where a check is genuinely not mechanical — does a cited chunk actually support the claim, is a counter-position steelmanned rather than strawmanned — it is a **bounded, separate model call**, never self-grading by the model that generated the answer. This mirrors Phase A's pattern of deterministic guards wrapped around LLM calls (PRODUCT.md §7.8, §7.3): the model does the judgment; the code holds the line.

Like Phase A, the mechanism is domain-general and the content is data. The lens vocabulary and the corpus are swappable; no country-specific logic lives in `src/`.

---

## 5. System overview — the stages

Six stages, each a discrete, independently testable module. Each stage notes whether it is deterministic or calls a model. Gates and validators sit **outside** the model's control.

1. **Brief intake & interrogation (model + deterministic wrapper; Principle III).** Reads the brief (§7.1). A bounded model pass interrogates it against corpus coverage and emits the structured **interrogation result** (§7.2): premises found, bounds proposed, or a refusal with reason. A deterministic wrapper reads that result and decides proceed / proceed-bounded / halt. The result is persisted whichever way it goes; a refusal is a completed run, not an error.
2. **Vault query API (deterministic, LLM-free; the foundation slice).** A small fixed tool set over the vault and the name layer (§7.5): resolve a phrase to canonical names, read a name page and its members, walk name co-occurrence, walk `citations` and `arguing_against`, fetch a note or artifact by id, read a source's envelope and notes, count coverage per name. It makes **zero LLM calls**, so it is fully testable without any LLM client. Every tool returns auditable vault ids.
3. **Retrieval planning & the agentic query loop (model-driven over deterministic tools).** From the interrogation result and the case anchor, a model plans retrieval, calls stage-2 tools, inspects results, and **re-queries when results are thin**. Case-as-anchor, not case-as-fence: the agent may pull cross-polity material bearing on the case (charter §3). Every tool call and every returned id is appended to the **retrieval trajectory log** (§7.6). The loop runs under a bounded step budget. The model calls the stage-2 tools via **native tool-calling** (`LLMClient.complete_with_tools`, alongside the existing JSON-completion `complete()`), not a hand-rolled JSON protocol; a **validating dispatcher** checks every requested call against the tool registry and its schema before it ever reaches the vault query API (§4's hard gate applied to tool use) — issue #253 slice 01.
4. **Evidence assembly & analysis (model, high tier + reasoning; Principles I, II).** The retrieved evidence set is assembled and made inspectable *before* the expensive call (inspect-before-spend, §7 CLI). The synthesis pass applies the lens and performs axial coding across the evidence, emitting the **claim graph** (§7.4): each claim marked (a)/(b)/(c) with grounds pointers into the vault. Grounded by construction, not generate-then-cite. **A Gather finding read along the way is a retrieval hint, never a citation (D4, §7.5).**
5. **Validators (deterministic, with bounded model checks where unavoidable; Principles II, IV, V).** Post-passes outside the model's control (§7.9): the **attribution validator** confirms every claim has a kind and every (a)/(b) claim has resolvable grounds; the **counter-position validator** confirms a counter-position section is present or an explicit one-sided disclosure is made on a contested brief; the **coverage/confidence validator** confirms a per-name coverage map (§7.7) and a confidence disclosure are present. A failed mechanical check blocks release.
6. **Rendering & persistence (deterministic).** Writes the structured **analysis record** (§7.3, one JSON per brief run), a rendered **markdown answer** (§7.10), and the **run report** (§7.15). The record carries the interrogation result, claim graph, counter-position section, coverage map, confidence disclosure, **source-usage disclosure** (§7.13), trajectory log, and the corpus-pin the run was produced against. The source-usage disclosure is computed here by counting, with no model call; it is recorded and rendered but gates nothing.

---

## 6. Repository structure

Scaffold to this shape; adjust only with reason. Extends the Phase-A layout (PRODUCT.md §6); Phase-A modules are unchanged.

```
src/axial/
  brief/        # brief intake + interrogation pre-pass (stage 1)
  query/        # deterministic, LLM-free vault + name-layer query API (stage 2)
  retrieve/     # retrieval planning + agentic query loop (stage 3)
  analyze/      # evidence assembly + lens/axial-coding synthesis -> claim graph (stage 4)
  validate/     # attribution / counter-position / coverage validators (stage 5)
  answer/       # analysis-record + source-usage counting + markdown rendering + persistence (stage 6)
  eval/         # (existing) + the rung-3 gate harnesses (§10)
  panel/        # the sealed-packet reviewer panel (§9.4) -- an OFFLINE eval
                #   instrument, never reached by a brief run
config/
  briefs/
    smoke/      # the six short briefs run on every slice (§9, D7)
    eval/       # the five hard briefs run when the engine is stable (§9, D7)
    sim/        # the v0 30-brief pool, kept as history; no longer swept (§9)
    dev/        # small fixture briefs for tests; NOT a brief set
    adversarial/  # seeded red-team briefs, each carrying its own answer key (§10)
  lenses/       # lens vocabulary as data (swappable, no country logic in src/)
data/
  analyses/     # one analysis-record JSON per brief run (<brief_id>.json)
  runs/         # one run report per brief run (§7.15)
evals/
  corpus_pin/   # pinned-corpus manifests (committed; ids + hashes only, DEC-23)
  cases/sim/    # the permanent sim hard cases (§9.3); ids only, DEC-23
tests/
```

---

## 7. Data & configuration contracts

### 7.1 The brief (input contract) **[FIRM]**

A brief is the phase's input, supplied as a versioned file. Its shape:
`{brief_id, case, request, lens?}`.
- `case` — the anchor: free text naming a polity or set of polities, written as the corpus writes them. It anchors retrieval; it does not fence it (Principle §3). It is resolved to canonical names through `find_names` (§7.5) like any other phrase in the brief, so a spelling the index does not hold fails visibly rather than silently returning nothing.
- `request` — the analytical question, free text.
- `lens` — optional named lens from `config/lenses/`; when absent the analysis stage selects one and records which, so the choice is always disclosed. The key is optional; its value is not. A present `lens` must be a non-empty string, and a blank or whitespace-only value is rejected exactly as a blank `case` or `request` is. Omitting the key is the only way to ask the stage to choose.
- `brief_id` — a stable, deterministic id over the brief's content (no randomness, no timestamps), so re-running the same brief is traceable.

`case` and `request` are required and must be non-empty after whitespace stripping. A brief that violates any of these field rules is rejected at intake, naming the offending field.

### 7.2 The interrogation result (Principle III) **[FIRM]**

Emitted by stage 1, persisted into the analysis record (§7.3). Shape:
`{premises_found[], bounds_applied[], refusal, disposition}`.
- `premises_found` — a list of `{premise, assessment}`: each smuggled premise the pre-pass found in the brief and whether the corpus supports it, contradicts it, or is silent.
- `bounds_applied` — a list of statements of what the corpus can and cannot answer for this brief (e.g. "covers X, not Y").
- `refusal` — `null`, or `{reason}` when the corpus does not support the request as posed.
- `disposition` — exactly one of `proceed`, `proceed_bounded`, `refuse`, set by the deterministic wrapper from the fields above, in this precedence: a non-null `refusal` always yields `refuse`, regardless of what `premises_found`/`bounds_applied` say; otherwise any `premises_found` entry assessed `contradicts`, or a non-empty `bounds_applied`, yields `proceed_bounded`; otherwise `proceed`. The wrapper is total (always resolves to exactly one of the three) and never reads a `disposition` the model itself emits — a model-supplied value is parsed-then-discarded, not trusted.

A `refuse` disposition is a completed, valid run: the record is written, the answer states the refusal and its reason, and no synthesis call is made.

**The pre-pass's coverage table is scoped to the brief's own resolved names, and is empty until that resolution lands (issue #487, D2).** The §7.7 map is per-name, so the honest table here is the coverage of the names *this brief* is about — not the whole index. Resolving a brief's names is the retrieval loop's job (§7.5's `find_names`, issue #488); until it passes a scoped map through, the pre-pass shows no table. Two things follow, and both are binding. Rendering the whole index instead is out of the question: measured 2026-07-30 at 62,821 rows, 2.08 MB, ~500k tokens and a 37–63s whole-vault read on every run, for a table nothing in the brief asked about. And **the prompt must not promise coverage it does not show** — an empty table under a "real coverage" heading invites the model to read absence as zero coverage and refuse, the same false-refusal failure the fabricated `case` row produced. It states the absence and its reason instead, and directs the model to judge premises `silent` rather than refuse for evidence it was never shown.

### 7.3 The analysis record (output contract) — the load-bearing artifact **[FIRM]**

One JSON per brief run at `data/analyses/<brief_id>.json`, the phase's analogue of the Phase-A envelope (PRODUCT.md §7.3). Shape is **locked**; no field is nullable except where stated:

```
{
  brief_id, brief,                     # the brief (§7.1), verbatim
  corpus_pin,                          # the pin id this run was produced against (§7.12)
  lens,                                # the lens applied (named), always recorded
  interrogation,                       # the interrogation result (§7.2)
  claims: [ <claim> ],                 # the claim graph (§7.4); may be empty only on refusal
  counter_position,                    # the counter-position section (§7.8)
  coverage_map,                        # per-name coverage (§7.7)
  confidence: { overall_band, rationale },   # disclosed, calibrated (Principle V)
  source_usage,                        # per-source contribution vs. available share (§7.13)
  trajectory: [ <tool_call> ],         # the retrieval trajectory log (§7.6)
  model_by_pass,                       # which model + reasoning setting each pass used
  cost                                 # per-pass token usage + computed dollar cost (§7.14)
}
```

`confidence.overall_band` is exactly one of `high` / `medium` / `low`, the same three-band vocabulary as the per-claim field (§7.4). `confidence.rationale` states the coverage counts that justify the band, drawn from `coverage_map`, so the band is never disclosed without the counts behind it. `source_usage` is non-nullable and follows §7.13; on disposition `refuse` it is present with an empty source list, like `claims`.

The record is the audit surface: every claim traces to grounds, every grounds pointer resolves to a real vault id, and the trajectory shows how retrieval got there. It is written once per run and is read by eval #1 (output) and eval #3 (process). On disposition `refuse`, `claims` is empty and the answer carries the refusal.

### 7.4 The claim (a/b/c kind, grounds, confidence) — Principle II **[FIRM]**

The unit of the analysis. Each claim:
`{claim_id, text, kind, grounds[], confidence, names_touched[]}`.
- `kind` — exactly one of `a` (**source-says**), `b` (**tool-infers-across-sources**), `c` (**speculation**), per charter Principle II. The (b) seam is the product's whole value and its whole risk: it is the new knowledge, and it is the claim least able to be checked against an answer key. It is **always** marked as the tool's inference, never voiced as if a source said it.
- `grounds` — a list of `{ref_type, ref_id}` pointers, where `ref_type` is `chunk` or `artifact` and `ref_id` is a real vault id (`chunk_id` or `artifact_id`). **Required non-empty for every (a) and (b) claim.** A (c) claim may carry partial or empty grounds but must be marked speculation.

**Chunk grounds resolve through a short opaque handle, never the real id (issue #410).** The synthesis prompt (`axial.analyze.synthesis.compose_prompt`) never shows the model a real `chunk_id` at all: each evidence chunk it lists is offered under a short, per-call handle (`[c3]`), assigned fresh for that one prompt and returned alongside it, never persisted and never reused across a later call. `parse_synthesis_response` resolves a cited handle back to the real id by **exact lookup in that map alone** — no fuzzy match, no suffix repair, nothing left to fuzz. A handle the model invents, or a real `chunk_id` it reproduces instead of the handle it was shown, is `UnresolvableGroundError`, exactly as an unresolvable id always was. This removes a real failure mode rather than repairing it after the fact: post-DEC-42 ids run to ~200 characters, and under long-context load a real 30-brief benchmark run twice blended two similar sources' ids into one that pointed at the wrong scholar's work (issue #410, `ayubi-1995-*` / `batatu-1999-*`). A component-matching repair of a blended id was scoped and deliberately rejected, because it would resolve the citation uniquely and silently manufacture a claim whose prose credits one scholar and whose evidence is another's — `source_id` is never fuzzed, not author, not year, not digest. With handles there is no long id in the prompt for the model to transcribe, truncate, or blend in the first place.

**Artifact grounds keep exact match first, a unique suffix then a unique prefix repairs a truncated citation, ambiguity or absence is still a hard error.** Artifacts are never offered under a handle (an artifact ground has always resolved against its real vault id directly), so this repair still applies to them, and unchanged to the counter-position section's own chunk grounds (§7.8), whose smaller, already-whitelisted candidate prompt still shows real chunk ids. After DEC-42, `source_id` (and so `chunk_id`/`artifact_id`) carries the source's raw download filename, running to ~200 characters in the real corpus. A model occasionally echoes only part of a long id — DEC-42's own stated general lesson is that any id-keyed artifact is fragile to a filename change, and this is that fragility surfacing at citation time. **Both ends truncate, so both are repaired** (issue #524). A `ref_id` that fails to resolve exactly is retried first against every real vault id ending with it (`str.endswith`), then, if that finds no single match, against every real vault id starting with it plus a trailing `_` (`str.startswith(f"{ref_id}_")`); if **exactly one** real id matches, the claim's `grounds` entry is repaired to carry that **full, real id** (never the truncated string) and the repair is logged with which end matched. If **zero or two-or-more** ids match at both ends, resolution still fails and `UnresolvableGroundError` still aborts the run, exactly as an exact-match failure always has — this is not a loosening of anti-confabulation. A hallucinated id cannot accidentally match exactly one real one at either end: a cited tail carries the source's 12-hex content digest plus the chunk's order key, slug and index, and a cited head carries the digest and order key. **The prefix carries the component separator.** The trailing `_` is what makes the boundary a component boundary rather than a character offset, so a citation naming section 18 can never reach section 180 — the head-truncated case that killed a live brief (`caspersen-2012-fbc0efe4fffc_18`) after 998.6s of paid work. Both searches are over an id index built from note **frontmatter**, never over filenames (§7.5) — a note whose on-disk filename was shortened, or a stale duplicate note left under an earlier filename for the same id, must not inflate one real id into a false ambiguity, and a shortened filename that drops the very tail the model cited must not make a real id undiscoverable either.
- `confidence` — exactly one of three discrete bands: `high`, `medium`, `low`. Never a numeric score. Enforced at generation (`axial.analyze.synthesis.parse_synthesis_response`, issue #402): a claim outside this closed vocabulary (e.g. a model-emitted `medium-high`) is a parse error, the same treatment `kind` already gets, not a value the calibration gate (§10) discovers is unscoreable after the record is already persisted.
- `names_touched` — the union of the canonical names the claim's grounds notes are members of, so coverage (§7.7) is computable from the claim graph. A grounds note's own `names` answers are surface forms; each is resolved to a canonical name through the alias map, and a surface the index does not carry is dropped rather than invented. **Through the alias map alone** (`axial.query.names.canonical_name_for_surface`), never through `find_names`' fourth, embedding tier: a nearest-neighbour hit would land the claim on a plausible neighbouring name and fabricate coverage the corpus does not have. Computed in code from the resolved grounds, never trusted from the model, and an artifact ground names nothing of its own so it contributes nothing.

**The evidence a claim is drawn from is the interrogation's own answers (issue #489).** `compose_prompt` lists, per evidence chunk, its source's author and title, then that note's substantive §7.15 answers — what it claims, what it is doing in the argument, whose position it is and what that position is, who it argues against, who it cites and with what stance, the mechanism, the evidence, the comparison, what it defines versus uses, what it concedes, what it assumes, and every name it names — and then its verbatim prose. It replaces the five closed-vocabulary tag axes the prompt used to carry, every one of which rendered empty against the v1 vault. Two rules bind the rendering: an abstained or absent field is **omitted entirely**, so a question the passage did not support never reaches the model as an answer, and the answers are labelled as another reading of the same passage rather than a second source, with the prose authoritative where they differ.

**The order synthesis walks the assembled evidence set in is source round-robin, not first-seen (issue #517 slice 2).** `assemble_evidence_ids` (§4) deduplicates the §7.6 trajectory's ids in call order, then reorders the deduplicated set grouped by `source_id` ascending, one id per source in rotation, each source's own ids kept in their existing first-seen order. Plain first-seen order is not used because the prompt's own char budget admits only a prefix of the assembled set, and a first-seen prefix is whichever tool the model happened to call first — a live run reached 137 notes across 12 sources but read two single-source `get_name` pages before its first cross-source call, so a first-seen prefix reached 3 of those 12 sources where round-robin reaches all 12. **Both the §7.6 trajectory and `get_name`'s own page order (§7.5, [FIRM]) are unchanged**: this reorders only the later, separate reduction over the already-deduplicated evidence set.

> **STRUCK (D1, D2).** `polities_touched` was this field's v0 name and its v0 source: the union of the grounds chunks' `polities_touched` facets. Phase A v1 deleted that facet, and 0 of the vault's ~6,100 prose notes carry it, so the field computed empty and the coverage map it fed was empty with it. `names_touched` is the same job over the substrate that exists. **This is the one field of §7.4 that v1 changes**; `kind`, `grounds`, `confidence`, the handle-resolution rules and the band vocabulary are untouched.

**The confidence vocabulary is three bands, and the reasoning binds everywhere confidence appears in this phase (§7.3, §7.7, §7.10).** A model emitting `0.73` is not computing a probability. It is producing a number that looks like confidence. That is manufactured precision, and dressing an unmeasured guess as a measurement is exactly what charter Principle V's honest-confidence requirement forbids. Bands are also far cheaper to calibrate: three buckets need far less scarce referee judgment to check than a continuous scale does.

**A band is never rendered instead of the counts that justify it.** Every confidence disclosure, per-claim and overall, appears alongside the real coverage counts from §7.7: `medium` confidence, grounded in N evidence notes drawn from a name page holding M member notes. The count is the honest signal; the band is the summary of it. A band shown alone is the manufactured-precision failure in another costume.

**Band targets [TENTATIVE].** Each band carries a stated expected-correctness rate, so the band means something checkable and the calibration gate (§10) has something to measure against: `high` ≥ 0.85, `medium` 0.60–0.85, `low` < 0.60. These are tunable starting hypotheses in the sense of charter §2, tuned on the first judged runs; that they are stated at all is FIRM.

`claim_id` is stable and deterministic within a run. **Unrequested, corpus-grounded analogues** the brief did not ask for are permitted, and are always emitted as (b) claims grounded in real corpus material, never as a training-memory analogy dressed as a finding (charter §3, Principle II).

### 7.5 The vault query API (deterministic, LLM-free) **[FIRM]**

The foundation slice: a small, fixed, deterministic tool set over the vault (`data/vault/prose/`, `data/vault/artifacts/`, `data/vault/names/`; markdown + YAML frontmatter) and the name-layer artifacts under `data/names/`. It makes **zero LLM calls**, so it is fully unit-testable without any LLM client. Each tool returns auditable ids plus the metadata and text needed to reason.

**The determinism contract, unchanged and binding on every tool below: the same query over the same pinned vault returns the same ids in the same order.** Order is never left to filesystem enumeration; every tool sorts explicitly, and every ranked tool states its full tie-break so the order is total.

#### Retired tools

> **STRUCK (D1).** `query_by_tag` returned 0 on every axis: `field`, `claim_type`, `empirical_scope`, `role_in_argument` and `theory_school` were deleted with the tag pass (`specs/PRODUCT.md` §7.1, D4/D9), so no note carries a value to filter on. Replaced by `find_names` + `get_name`.

> **STRUCK (D1).** `query_by_polity` returned 0: `polities_touched` was deleted with the same pass, and 0 of the vault's ~6,100 prose notes carry it. A polity is now a name whose `kind` is `country/state/place`, reachable through `find_names`/`get_name` like any other name. Nothing special-cases it.

> **STRUCK (D5).** `follow_backlinks` returned `[]`: `artifact_refs` and `cited_by` were the cross-reference pass's output and are retired with it (`specs/PRODUCT.md` §7.2). Replaced by two traversals the interrogation actually produced: `name_neighbors` and `who_cites`.

Deleting the code behind these three is slice 02's job (#487); no builder implements them, and no test pins them.

#### The name layer (new, D1 and D5)

- **find_names(query, limit)** → a ranked list of `{canonical, kind, aliases[], member_count, matched_on, tier}`, where `tier` is one of `exact` / `alias` / `folded` / `embedding` and `matched_on` is the surface form that matched. `member_count` is the name page's own; it is `null`, never `0`, when the vault holds no page for a name the index carries — an index/vault mismatch is reported, not filled in with a count that would read as real, thin coverage. **Resolution is tiered, never string equality**, because exact lookup fails on the names briefs actually use. The index holds `Charles Tilly`, `Giorgio Agamben` and `Uğur Ümit Üngör`; briefs say Tilly, Agamben, Ungor. The tiers, in order, each exhausted before the next is tried:
  1. `query` equals a canonical name in `index.json`;
  2. `query` equals an alias of a node in `alias_map.json`;
  3. `query` equals either under the fold Phase A already applies to surface forms (case, whitespace, and punctuation, with a hyphen folded to a space; `specs/PRODUCT.md` §7.16, issue #463);
  4. nearest neighbours among the name vectors Reconcile persisted (`data/names/embeddings.lance`, table `names`, one row per inventory surface form), each hit mapped back through the alias map to its canonical name and de-duplicated.
  A query that resolves to nothing returns `[]`. **That is a real answer and must be reported as one**, and a brief that needs such a name should surface an honest resolution failure, not silence.
  **The `AANES` case is a name-layer gap, not a `find_names` behaviour (measured 2026-07-30, `data/logs/2026-07-30-name-query-487/`).** The corpus **holds** the entity: `Autonomous Administration of North and East Syria` is an exact hit, 2 members, `kind: institution/group`, carrying the alias `Autonomous Administration of Northeast Syria (AANS)`; a separate, fragmented `AANS` node with 1 member never folded into it. The acronym `AANES` reaches neither, because the store's MiniLM model scores an acronym against its own expansion below every piece of lexical noise — an embedding model is not a string matcher. No tier here fixes that and no acronym tier is added; the gap is filed against Phase A's name layer with these numbers.
  **Tier 4 carries a similarity floor, and it is a stated tunable [TENTATIVE].** A nearest-neighbour search always has a nearest neighbour, so without a floor an unresolvable query comes back carrying the nearest name in the corpus instead of the empty result the paragraph above requires. A neighbour whose cosine similarity to the query is below the floor is therefore not an answer. It is `0.5` (`axial.query.names.MIN_EMBEDDING_SIMILARITY`).
  **Inspected on the real distribution (same run), which is what a stated tunable owes.** 14 of 17 real brief-shaped queries never reach tier 4 at all: `Tilly` → `Charles Tilly` (146 members), `Agamben`, `Bayat`, `Batatu` and `Caspersen` all resolve through the alias map, and `Kalyvas` / `SDF` / `Rojava` / `PYD` / `state of exception` / `bare life` are exact. Of the two that do reach it, `Ungor` reaches `Uğur Ümit Üngör` at **0.7752** as its top hit; `Charles Tilly`'s own variant surfaces score **0.8502–0.8345** against an exact **1.0000**; unrelated text (`zzqqx nonexistent scholar`) tops out at **0.4518** and is cut, returning `[]`. The five wrong names `AANES` reaches top out at **0.7062**.
  **The (0.7062, 0.7752] window that would cut those five was rejected, not adopted.** It is a 0.07 band read off two cases — a constant fitted to its own evidence, the tripwire this repo names explicitly — and it would also make the engine deny an entity the corpus actually holds. What `0.5` claims is exactly what was measured: it cuts unrelated text and admits every transliteration seen. It does not claim to separate a right name from a plausible wrong one, which no floor on this model does. That some floor exists, and that its value is stated and inspected rather than asserted, is FIRM.
  **Determinism:** tiers 1–3 are exact lookups over committed data, ordered by canonical ascending, then by the matched surface form; one canonical appears once, since a query can fold onto both a canonical and one of that same canonical's aliases. Tier 4 reads a persisted vector table and embeds only the query string, with the same local sentence-transformer the store names in its own `similarity_manifest.json` (`model_name`, currently `sentence-transformers/all-MiniLM-L6-v2`) — the table and the encoder are each loaded at most once per process, the encoder from local files only, so a retrieval loop calling `find_names` repeatedly neither re-reads the table nor rebuilds the model, and no query-time path reaches the network; results are ordered by score descending, ties broken by canonical name ascending, and truncated at `limit`, with `matched_on` the best-scoring surface form for that canonical (ties by surface form ascending). The same query at the same pin returns the same canonicals in the same order. Every tier is truncated at `limit`.

- **get_name(canonical, limit)** → `{canonical, kind, aliases[], member_count, members: [{chunk_id, source_id, author, year, claim}], disagreement}`. `member_count` and the member list are the name page's own (`data/vault/names/`, `specs/PRODUCT.md` §7.17); each member's `author`, `year` and one-sentence `claim` are that note's own values, never a paraphrase. `disagreement` is `{text, names[]}` when Gather wrote a section for this name and `null` otherwise: a null finding writes no section, and the two are distinguishable. The `canonical` argument is resolved through the same three exact tiers `find_names` and `name_neighbors` use (canonical, alias, fold — never tier 4) before the page lookup, so an alias or a folded variant of a name reaches the same page as its canonical; matching is against every surface form the alias map folds into it, never string equality against the canonical alone. **Determinism:** members in the page's own order, which is the order Materialize wrote and is itself deterministic, truncated at `limit`. **`member_count` is never truncated** — it stays the page's own true total regardless of `limit`, so a capped call still carries the honest denominator.

- **name_neighbors(canonical, limit)** → `[{canonical, kind, shared_note_count}]`: the names that co-occur with this one in some note's own `names` answers, ranked by shared note count weighted by each neighbour's inverse document frequency (issue #521). This is the cheapest real edge the interrogation produced: two names on one note are two things one author discussed together. The `canonical` argument is resolved through the same three exact tiers `find_names` uses (canonical, alias, fold — never tier 4) before it is matched, so an alias or a folded variant of a name reaches the same neighbours as its canonical, matching how the note side's own surface forms are already resolved. **Ranked by count times idf, not raw count**: raw `shared_note_count` put every anchor's corpus-wide hub names (the ones that co-occur with almost anything) at the top of its neighbour list, answering what the corpus is about rather than what this author discusses alongside `canonical`. Each neighbour's count is multiplied by `ln(N / df)`, `df` the neighbour's own `member_count` and `N` the number of prose notes carrying a `names` answer at all — so a name specific to this anchor outranks a hub name with a higher raw count. `shared_note_count` itself is always the true, unweighted count; only the order changes. **Determinism:** `shared_note_count * idf` descending, ties broken by canonical ascending, truncated at `limit`.

- **who_cites(canonical, limit)** → `([{chunk_id, source_id, cited, stance, about}], total)`: every prose note whose `citations[].cited` resolves to this name, carrying the author's own stance (`support` / `foil` / `authority`) and the `about` clause (`specs/PRODUCT.md` §7.15), truncated at `limit`, plus `total` — the true pre-cap count. These are **author-stated cross-book edges** and they are the closest thing the corpus has to a citation graph. The argument is a canonical name; matching is against every surface form the alias map folds into it, never string equality against the canonical alone. **Determinism:** sorted by `chunk_id` ascending, then by the cited surface form, stance and `about` — one note can cite the same name twice, under two surfaces, so `chunk_id` alone is not a total order; the truncated prefix is the head of that same order.

- **who_argues_against(canonical, limit)** → `([{chunk_id, source_id, arguing_against, position, claim}], total)`: every prose note whose `arguing_against` answers name this name, carrying that note's own stated position and one-sentence `claim` so the opposition is legible without a second fetch, truncated at `limit`, plus `total` — the true pre-cap count. `position` is the note's own `position` answer where it has one and its `position_of` answer otherwise — the corpus is a mixed frame and stays one (`specs/PRODUCT.md` §7.15, issue #496), so every reader branches on key presence. Same alias-map matching as `who_cites`. **Determinism:** sorted by `chunk_id` ascending, then by the matched `arguing_against` string, for the same reason `who_cites` needs a second key; the truncated prefix is the head of that same order.

- **where_names_meet(canonical, other, limit)** → `([{chunk_id, source_id, author, year, claim}], total)`: the notes that are members of BOTH name pages, plus `total` — the true pre-cap intersection size (issue #517). This is the co-occurrence edge `name_neighbors` already computes, returned as the shared notes themselves rather than as a ranked name list. It exists because a brief's `case` anchor is specified to be a polity (§7.1) and a polity page is often the largest one in the corpus; intersecting it with the intellectual name the brief is actually about turns a huge, single-source hub read into a small, source-diverse set, with no diversity heuristic needed at all — the anchor filters, the intellectual name carries the query. Both `canonical` and `other` are resolved through the same three exact tiers `get_name` uses (canonical, alias, fold — never tier 4) before either page is read. A name that resolves to no page raises the same `NameNotFoundError` `get_name` raises, naming whichever argument failed first. **An empty intersection is a real answer, `([], 0)`, never an error** — both pages existing and sharing no member is honest information about the corpus. Reads both pages' full, uncapped member lists (never `get_name`, whose own `limit` would truncate a page before the intersection could see it), and never touches the whole-corpus `_answers_index` scan `name_neighbors`/`who_cites`/`who_argues_against` pay for: reading two name pages is O(pages), not O(corpus). Shares `limit`, defaulting to `DEFAULT_LIMIT`, like every tool above.

  **Determinism, and why it is not `chunk_id` ascending.** The intersecting members are grouped by `source_id`, the groups ordered by `source_id` ascending, members within a group ordered by `chunk_id` ascending, then emitted one member per group in rotation until every group is exhausted, truncated at `limit` — a total order. Plain `chunk_id` ascending is not used here because a `chunk_id` begins with its own `source_id`, so ascending order **is** alphabetical-by-source: a large intersection truncated that way collapses onto a handful of sources instead of spanning the ones it actually has, which is the exact defect this tool exists to avoid. It is a new tool, so it states this order in its own right rather than inheriting `get_name`'s page-order contract.

**All six signatures above share `limit`, defaulting to `DEFAULT_LIMIT` (10, `axial.query.names.DEFAULT_LIMIT`), with no separate tunable per tool (issue #505).** Before this, `get_name`/`who_cites`/`who_argues_against` were unbounded and returned every matching row: one `get_name` call on `Syria` (962 members) put 962 ids into a retrieval loop's prompt, which then re-sent that list on every later turn — 21 model calls, ~374,000 prompt tokens, prompt stuck at ~72,000 characters, all billed at full price (`axial.llm` sends no `cache_control`). Measured over the 49,674 live name pages (`member_count`: median 1, p90 4, p99 25, max 962), a cap of 10 leaves 1,616 pages (3.25%) over it, hiding 41,379 of 140,602 member rows (29.4%) — a real but small fraction of the corpus, and the ones it hides are exactly the hub pages a naive full read would otherwise flood a prompt with.

**A capped result is never silent about being one.** `who_cites`/`who_argues_against`/`where_names_meet` return `(edges_or_members, total)` rather than a bare list so the true pre-cap count travels with the truncated prefix; `get_name`'s `member_count` already is that true total, uncapped by construction, so no shape change was needed there. At the tool-calling boundary (§7.6), the true total reaches the model through `axial.retrieve.dispatcher.ToolResult.total`, stated in the next turn's prompt feedback when it exceeds the returned count ("N of M total — re-ask with a larger limit for more") exactly the way `ToolResult.error` already rides beside the trajectory rather than inside it. **§7.6's trajectory shape is unchanged**: still exactly `{step, tool, args, result_ids, result_count}`, and `result_count` is still the honest count of ids actually returned — `total` is never a sixth field.

**Three tools ride `ToolResult.detail` the same way (issue #517).** `find_names` carries each hit's `kind`, `member_count` and `tier`, because a bare canonical string cannot tell the model an exact/alias hit apart from a weak embedding guess. `get_name` and `where_names_meet` carry how many distinct sources the returned members span (`"N notes across M sources"`), because a bare `chunk_id` list cannot tell the model a page or an intersection is one book rather than several — the same blindness, one level down, and the reason a model told to intersect only a *large* resolved name instead avoided the tool by resolving narrow, single-book names (measured on a live corpus run: `Syrian nationalism`, 24 members, 83.3% one source). All three state it in the next turn's prompt feedback exactly like `total` and `error` — never a sixth §7.6 field. Every other tool leaves `detail` `None`.

- **coverage_count()** → `{canonical: member_count}` for every name in the index, read off the name pages' own `member_count`. The raw material of the §7.7 coverage map. Read off the name PAGES, which are the same set as the index by construction — Materialize writes one page per surviving canonical and deletes any page whose canonical no longer survives — so a name the index carries but no page exists for has no honest count to report and is absent rather than carried at a fabricated `0`. A vault with no name pages at all (never materialized) returns `{}`. **Determinism:** a mapping built in ascending-canonical order.

  **Not registered as a model-facing tool (issue #505's own follow-up, decided after the #505 fix's own corpus re-run).** It stays part of the deterministic query API — §7.7's coverage map is its real, model-free consumer (`axial.validators.coverage`) — but on a paid corpus run the retrieval-loop's own model chose to call it unprompted (nothing scripted the call) and it returned all 49,674 canonical names in one result: the prompt jumped 3,862 → 1,204,509 characters (350,923 prompt tokens) and held there for 14 turns, 4,947,176 prompt tokens for that run alone — thirteen times the flood the #505 fix above exists to prevent. §7.2 already ruled out exactly this shape for the interrogation pre-pass ("rendering the whole index instead is out of the question: measured 2026-07-30 at 62,821 rows, 2.08 MB, ~500k tokens"); the retrieval tool carried the identical hazard, unguarded. A `limit` would bound the tokens without making the tool useful — the alphabetical head of 49,674 names answers no retrieval question — and the model already has the count it can act on: `member_count` per name, from `find_names` and `get_name`. This is the mirror of D1/D5 (`query_by_tag`/`query_by_polity`/`follow_backlinks`, struck above): those returned nothing useful; this one returned far too much.

  > **STRUCK (D2).** `coverage_count` previously returned substantive chunks per polity from `polities_touched`, and returned 0 entries against the v1 vault, which pinned `confidence.overall_band` to `low` by §7.7's own derivation rule on every run. The per-name count above replaces it and is strictly wider.

#### Surviving unchanged

- **query_by_source / get_envelope** — the per-source envelope (`thesis`, nested `toc`, `scope`, `stated_argument`) and the notes of a given source. Untouched by Phase A v1; measured working. (`all_chunk_ids`, a plain enumeration of every prose id in `chunk_id` order, briefly survived here as the honest name for what `query_by_tag` with no filters did. Its only caller was the record's `schema_version` read, and it was deleted with that field — issue #524.)
- **get_chunk(chunk_id, limit) / get_artifact(artifact_id)** — a note or artifact by id, with its frontmatter and text. The frontmatter a prose note now carries is the interrogation answer block (`specs/PRODUCT.md` §7.15, Appendix H): `claim`, `move`, `position_of`, `position`, `arguing_against`, `names`, `citations` and the rest, in place of the retired axes. Every field the new tools above read is read from there. **The block is a mixed frame** (§7.15, issue #496): a note interrogated before frame 0.2 carries `position_of` and no `position` key, a note interrogated after carries both, and no re-run is planned. A consumer reads `position` when the key is present and falls back to `position_of` otherwise — never branching on `frame_version`.
  **`get_chunk` reads a BATCH: `chunk_id` is a list of ids (issue #542).** It returns them together, in the order asked for, so several notes cost one call instead of one call per note. Measured by replaying the seven persisted smoke records with zero model calls: `get_chunk` was called 44 times, contributed **zero** new ids to the assembled evidence set on every one of them (the id had always already been surfaced by the `get_name` that listed it), and 24 of the 44 sat in a run of consecutive `get_chunk` calls that one batched call collapses. A bare string is still accepted — the model will emit both forms and a hard schema error on the old one costs a full model turn to say nothing — while the tool schema a provider is shown advertises the array, since a string/array union is what strict function-calling modes reject. **The batch shares `limit`, defaulting to the same `DEFAULT_LIMIT` (10) every bounded tool above uses**, and does not invent a second cap: an unbounded id list is the identical "one call pulls the index into the prompt" hazard #505 fixed for the name tools. `total` is the count of ids the call **asked for**, so a truncated batch reaches the model as "N of M total" exactly like a capped name page. An id that resolves to no note fails the whole call, unchanged from the single-id behaviour — across all 44 real calls, none ever hit one. **One call is still one §7.6 entry**, carrying every returned id in that entry's `result_ids`; nothing downstream counts ids where it used to count calls.

  **`get_chunk` exposes the WHOLE answer block, raw, and the abstention predicate travels with it (issue #489).** A live note carries 21 answer keys and the reader reached seven, which left `about`, `ranges_over`, `stops_holding`, `mechanism`, `evidence`, `comparison`, `defines`, `uses`, `concedes`, `assumes` and `position_of_nearest` unreachable through the note layer at all. Every one of them is now a field on `ChunkNote`, and every one is returned **exactly as the record holds it**: each field is in one of §7.15's three states — an answer, the explicit abstention, or absent — and only the raw value distinguishes them. So the reader never coerces one into another, `[]` stays the answer it is ("the passage names none of that"), and an absent key stays distinguishable from `[]`. **One predicate decides**, `axial.query.reader.is_abstention`, covering all three forms (the bare string, the object with a reason, and either alone inside a one-element list); it is the same function the write side applies, imported rather than reimplemented, and every consumer applies it before showing an answer to a model. This is load-bearing, not defensive. Measured over the 6,148 answer records on disk: 1,451 notes (23.6%) abstain on `position_of`, so an abstention read as an answer would reach the model on nearly a quarter of the evidence. `arguing_against` splits the other way and is the reason the two states must stay distinguishable: 301 notes (4.9%) abstain, while 1,184 (19.3%) answer `[]`, a real reading that the passage names no opponent. Collapsing those 1,184 onto the abstention would discard a fifth of the corpus's answers on that field.

#### D4 — a Gather finding is a retrieval hint, never a citation **[FIRM]**

`get_name` returns a name's disagreement section, and that text is a **pointer, not evidence**. The agent may read one to decide where to look; it then follows that name's own `chunk_ids` to the real notes and cites **only those**. No claim's `grounds` ever points at a disagreement, a name page, or a Gather record.

Three reasons this is a rule and not a preference. Grounds stay anchored to passages, so charter Principle II is untouched. A wrong Gather finding costs a wasted hop rather than a bad citation. And the 575 findings have never been scored (`axial gather-eval` exists and has never run, DEC-55), so the engine must not depend on their accuracy. This rule is what makes Phase B independent of whether that score ever happens.

The same rule binds §7.8's contested detection and counter-position generation, and §7.15's `disagreement_reuse` metric, which measures whether a run *reached* a note a finding also cites, never whether it repeated the finding.

**The synthesis prompt states the rule, not only the code (issue #489).** It tells the model plainly that retrieval may have reached this evidence by following a disagreement another pass wrote, that such a finding is that pass's own reading and is neither quotable nor citable, and that its grounds are the chunk handles and artifact ids listed and nothing else. The mechanical half is unchanged and independent of the wording: `ref_type` is `chunk` or `artifact`, and a third value is a parse error.

**A note's on-disk filename is a display artifact, not its id.** A source whose readable title would push a note's path over Windows' MAX_PATH gets its filename shortened at write time (the writer's own budgeting rule); `chunk_id`/`artifact_id` themselves never change. `chunk_id`/`artifact_id` in a note's frontmatter is the sole authoritative id — never the filename, never assumed equal to it. `get_chunk`/`get_artifact` resolve a note's real on-disk path through the **same** deterministic naming function the writer used (`axial.paths.chunk_note_path`/`artifact_note_path`, the one shared copy of the budgeting rule), trying the direct `<id>.md` path first and falling back to the budgeted name only on a miss, so a note whose filename was shortened is still reachable by its real, correct id.

**Id lookup — exact, suffix or prefix — is always over frontmatter ids, never over filenames.** The budgeting rule above can shorten a note's filename anywhere: the readable source stem, then the section slug, whichever order the overage requires — so the discriminating tail a caller cites can be dropped from the filename while remaining part of the real `chunk_id`/`artifact_id`. A candidate scan keyed on filenames therefore misses notes it should find. The truncation-repair fallbacks (`find_chunk_ids_ending_with`/`find_artifact_ids_ending_with` and their `_starting_with` counterparts, used by the grounds-resolution repair above) instead discover candidates from a `chunk_id`/`artifact_id` → path index built once from note frontmatter and cached for the process lifetime, built lazily on first repair lookup — never on import, and never on `get_chunk`/`get_artifact`'s own direct/budgeted-name fast path, which stays index-free.

### 7.6 The retrieval trajectory log **[FIRM]**

Appended by stage 3, one entry per tool call, in call order:
`{step, tool, args, result_ids[], result_count}`.
It is the eval #3 (process axis) raw material and the audit trail for how retrieval reached its evidence. It records the full path including re-queries after thin results, so a right answer reached by a lucky guess over a broken path is distinguishable from one reached by sound retrieval (eval #3). Its storage format inside the record is fixed here; a richer standalone trajectory store is an Open Question.

**One entry per CALL, not per id.** A batched `get_chunk` (§7.5, issue #542) returns several notes in one call and writes one entry carrying every returned id in that entry's `result_ids`, with `result_count` the honest count of them. Everything computed off this log therefore keeps counting what it already counted: `assemble_evidence_ids` walks entries, and §7.15's `evidence_tool_calls` and `turns_without_new_evidence` are per-entry figures, so a batch is one turn that added evidence if any one of its ids was new.

**The loop is told its own evidence set's composition (issue #542).** After every step, the next turn's prompt states how many notes the run's assembled evidence set holds, how many distinct sources they span, and which sources — computed mechanically from this log by `axial.retrieve.loop.evidence_set_composition`, appended to the tool feedback exactly the way `ToolResult.total` and `.detail` already ride beside it (§7.5), and never a sixth field in the entry itself.

Why sources, and why at all: replaying seven persisted brief runs step by step, **the assembled prefix synthesis actually reads changes exactly when a new SOURCE arrives** — identical step for step in 6 of the 7 runs, with the seventh carrying one extra change where an existing source's bucket deepened enough to shift the round-robin rotation. Reaching another book is the loop's productive act; reaching another note in a book it already holds is not. The loop could see neither, and spent a model round trip per turn adding ids to a set it had no view of at all.

**It states composition and nothing else — never a budget, a cap, a maximum or a remaining allowance.** #505's own finding is that a cap a model can SEE gets widened on purpose, and `synthesis.evidence_char_budget` (§7.4) is exactly such a cap: it decides which prefix of the assembled set reaches the model, and it is disclosed to the retrieval loop in **no** form, direct or derived. What the set holds is a fact about the corpus reached; what would still fit is a target to fill.

### 7.7 The per-name coverage map (Principle V, charter §3; D2) **[FIRM]**

Computed deterministically from the name layer, never asked of a model. For each name the answer is about:
`canonical -> {corpus_note_count, evidence_note_count, coverage_band}`.
- `corpus_note_count` — the name page's **own `member_count`** (`specs/PRODUCT.md` §7.17), read through `coverage_count`. The denominator already exists and is written by Materialize; nothing recomputes it. It is `null`, never a fabricated `0`, for a name the index carries and the vault holds no page for (§7.5's own rule; `Revolution` is a live example).
- `evidence_note_count` — how many of *this run's* grounds notes are members of that page. It is the intersection of the run's grounds with the page's member list, never a re-query and never a recount off the notes' own `names` answers.
- `coverage_band` — a disclosed band (dense / moderate / thin) derived from `corpus_note_count` against a stated tunable threshold, proven via inspection in the spirit of the Phase-A note band (PRODUCT.md §7.7). A `null` denominator reads `thin`, the most conservative band, and the `null` travels with it.

**The map's scope is the names the answer is ABOUT: a name this run retrieved on that at least one claim's grounds note is a member of** (issue #490). "Retrieved on" is read off the run's own §7.6 trajectory — the `canonical` argument of `get_name` / `name_neighbors` / `who_cites` / `who_argues_against`, and every canonical `find_names` resolved. Both halves bind: a name the run looked at and no claim then used is not part of the answer, and a name the evidence merely mentions is not either.

**Why not `names_touched` alone, measured (2026-07-30, `data/logs/2026-07-30-slice-05-coverage/`).** §7.4's `names_touched` is every canonical a claim's grounds notes are members of, and a live note's `names` answer lists every person, place, date and organisation the passage mentions — a median of 21 per note. Over ten real 24-note evidence sets the union came to **423 distinct canonical names on average** (663 for a Charles Tilly set, 810 for a Hanna Batatu one). Keyed on all of them the map is a several-hundred-row table whose least-covered entry is always some one-member mention, so the derivation below returns `low` on **10 of 10** measured sets at every cut point tried — the same "confidence computed over nothing" this section's own STRUCK note describes, in a new costume. D2's worked example ("a brief about the state of exception now gets coverage disclosed for `state of exception` and `Giorgio Agamben`") describes the retrieved-name scope, and §7.2 already calls it "the names *this brief* is about".

**The cut points, inspected on the real distribution.** `coverage_bands.moderate_floor` 20 and `dense_floor` 100 (`config/pipeline.yaml`). Over the 30 real brief-shaped names that resolve against the live index they split **15 thin / 9 moderate / 6 dense**: `bare life` 1, `AANES` 2, `Rojava` 3, `state formation` 5, `SDF` 7, `Giorgio Agamben` 9, `Stathis Kalyvas` 11, `PYD` 14, `N. Caspersen` 17, `Asef Bayat` 18 | `state of exception` 27, `Hanna Batatu` 30, `Idlib` 30, `Bashar al-Assad` 33, `Ba'th Party` 43, `sovereignty` 48, `Civil War` 61 | `Charles Tilly` 146, `Michael Mann` 378, `Iraq` 445, `Lebanon` 507, `Syria` 962. Unchanged from #260's starting hypothesis because the measurement supports them, not because nobody looked.

**This is strictly wider than the per-polity map it replaces.** A polity is one `kind` of name; the map now also discloses coverage of concepts, scholars, institutions, movements and events, which is what a comparative-historical brief is usually about. `state of exception` and `Charles Tilly` each get a coverage number, which the polity map could never give.

> **STRUCK (D2).** The v0 map was `polity -> {corpus_chunk_count, evidence_chunk_count, coverage_band}`, computed from `polities_touched`. That facet is deleted, `coverage_count` returned 0 entries against the v1 vault, and the map was empty on every run, which pinned `confidence.overall_band` to `low` by the derivation rule below. Same job, same three-field shape, substrate that exists.

A claim about a thinly-covered name is disclosed as thin and feeds the calibration layer (Principle V): it is not stated with the confidence of a claim over a densely-covered one. The map is where the counts behind every confidence band live (§7.4): `coverage_band` and the confidence bands travel with `corpus_note_count` and `evidence_note_count`, never in place of them.

**`confidence.overall_band` derivation (issue #400), shape unchanged.** Computed deterministically from `coverage_map`: the LEAST-covered name in the map sets the ceiling (`dense` → `high`, `moderate` → `medium`, `thin` → `low`), and `rationale` names every mapped name's own band and counts. This satisfies the release gate's `confidence_exceeds_coverage` check (§7.9) by construction — the top band can never accompany a `thin` coverage_map entry, because a `thin` entry is exactly what would have produced `low`. An empty `coverage_map` (a `refuse` disposition, or a run that never retrieved on a name any claim then used) still discloses `low` with a plain rationale, since `confidence` is never nullable (§7.3).

### 7.8 The counter-position section (Principle IV) **[FIRM]**

`{present, stance, grounds[], corpus_one_sided, one_sided_reason}`.
On a **contested** brief the section either states the opposing school at its strongest from corpus grounds (`present: true`, non-empty `grounds`, `stance` marked as counter-position), or explicitly discloses that the corpus is one-sided here (`corpus_one_sided: true`, `one_sided_reason` naming why and attributing the one-sidedness to the corpus). Absence of both on a contested brief is a **red flag, not a clean result**, and fails the counter-position validator (§7.9). What makes opposing material findable is now the `arguing_against` answer and the name pages the opposed names get: a relation the author stated, not a label a tagger picked (`specs/PRODUCT.md` Appendix F, D5).

**Contestedness comes from what the notes say (D3).** Whether a brief is contested is determined from corpus signal, not the brief's wording. It is contested when either holds over this run's own resolved evidence:

1. **The notes disagree in their own words** (signal `opposed_positions`). Two grounds notes are two different sides, and one of them NAMES the other's side in its `arguing_against`: the other's stated position, the other's author, or a name that other note itself names. A note's stated position is its `position` answer where it has one and its `position_of` answer otherwise (`specs/PRODUCT.md` §7.15, issue #496) — the corpus is a mixed frame and stays one. Two notes are different sides when their stated positions differ **or** they come from different sources; the second disjunct is what makes the clause usable at all, since 76% of notes answer `position_of` with "the author" and "the author" of one book is a different person from "the author" of another. Naming alone is not enough either: a passage arguing with its own book's position is not two sides.
2. **Gather found a disagreement at a name the answer rests on** (signal `gather_disagreement`). A name in the §7.7 coverage scope — retrieved on by this run and touched by a claim's grounds — whose page carries a disagreement section (`specs/PRODUCT.md` §7.18) marks the brief contested. Not any name in `names_touched`: a real evidence set's notes name 423 distinct canonicals on average, and a finding at a name the answer merely brushed past says nothing about whether the answer is contested.

The corpus **states** the disagreement instead of a tag implying it. Path 2 is a **hint only, per D4**: it decides that the brief is contested and points at where opposition lives; it never supplies a ground.

**The two clauses are not equal, and the rule reflects the measurement (2026-07-29, on #490).** `position_of` is free text with 90% singletons, so "positions differ" is true of 99% of names and discriminates nothing; no count threshold rescues it, and it survives here only as the guard against a note counting as its own opponent. The `arguing_against` clause separates at 1.9x–2.4x over a 0.26 base rate, but **only implemented literally** — read loosely as "an `arguing_against` exists" it is a 1.00x no-op, which is why "names the other side" above is a real match against real strings, resolved through the alias map alone and never through `find_names`' embedding tier. Name size is the dominant confound and is deliberately not counted as evidence here: thinness is already disclosed through `member_count` under §7.7.

**Recall caps at 0.35–0.59, and contested stays a boolean.** A disagreement the corpus states only implicitly is not seen. That is a stated limit of this validator — it requires a counter-position exactly where the predicate sees the disagreement and nowhere else — not a case for grading the flag: two contracts block on the boolean (the presence check below and #405's one-sided outcome), and grading it would not recover a disagreement the predicate never saw.

> **STRUCK (D3).** The v0 rule was "evidence spans two or more distinct **substantive** `theory_school` values, or carries `role:counter-position` material", with the `not-applicable` and `unlisted` sentinels (PRODUCT.md Appendix E) excluded from the comparison because neither is a position. All of it is retired: the axis, the tag, the sentinel vocabulary and the exclusion rule that softened them are gone with the tag pass (`specs/PRODUCT.md` §7.1, D4/D9), so the rule matched nothing and no exclusion was left to make. Its `contested_detection.min_distinct_theory_schools` config knob goes with it: the rule above either fires or it does not.

**Generation, not just validation (issue #399), re-based on the new signal.** `axial.analyze.synthesis.generate_counter_position` reuses the counter-position validator's own contested detection verbatim, over the just-produced claim graph's own resolved evidence — zero model calls on an uncontested brief. On a contested brief it offers the model a whitelist of real vault notes already in hand, never a fresh retrieval, and makes one bounded follow-up call under its own pass name (`COUNTER_POSITION_GENERATE_PASS_NAME`, still the generating model, routed to the same tier as synthesis). The whitelist, in this order:

1. **Both sides of every stated opposition among this run's own grounds notes** — the same pairs path 1 reads — plus any grounds note whose stated position differs from the majority among that evidence. The majority clause alone comes up empty on the real corpus, where nearly every note answers "the author".
2. **The notes `who_argues_against` returns** for a name in the §7.7 coverage scope.
3. **The member notes of a Gather finding** at such a name. This clause is what #490 owes this section. Contested can fire on path 2 while (1) and (2) find nothing, and the empty-candidates guard then wrote `one_sided_reason: "none of the underlying grounds chunks resolved in the vault"` — which is false: they resolved and simply carry no opposing position. Per D4 the finding points at its page's member notes and those notes are what gets cited, so they belong on the whitelist; the guard's reason is re-derived per path, and on `gather_disagreement` it now says the corpus offers no opposing material rather than that nothing resolved. The finding's own TEXT is never offered, quoted or cited.

**The candidate pool is capped at 20 notes** (`axial.analyze.synthesis.MAX_COUNTER_POSITION_CANDIDATES`). Sources 2 and 3 are unbounded on the real corpus — `Syria`'s page alone carries 962 members — and the first real `brief examine` already blew one prompt to 72,000 characters by re-sending such a list (issue #505). This is a bound on prompt size, not a quality knob: the ordering above puts the run's own grounds notes first, so what the cap ever drops is the vault-wide tail, never evidence the answer already cites.

A `present: true` response may cite grounds only from that whitelist; the model is told the one-sided disclosure is the correct, honest answer whenever the candidates do not cash out to a real opposing stance, never a failure.

### 7.9 The validators (deterministic post-passes) **[FIRM]**

Three validators run after synthesis, outside the model's control. Each is **mechanical wherever the property is mechanically checkable**; a bounded, separate model call is used only where it is not, and never by the generating model.

- **Attribution validator (mechanical presence/resolution + bounded model honesty, issue #258).** Mechanically: every claim carries a `kind` in `{a,b,c}`; every (a)/(b) claim carries at least one `grounds` pointer that resolves to a real vault id through the query API (`get_chunk`/`get_artifact`) -- a well-formed pointer to an id the vault does not contain is a failure, not a shape check. Bounded model check, under its own `pass_name` and never the generating model: no (b) claim is phrased as a source assertion. Either half failing blocks release.
- **Grounding check (bounded model, sampled or full).** For (a) claims, does the cited chunk actually support the claim text? Judged by an independent model anchored to the cited chunk's text, never the generating model. Feeds the grounding gate (§10).
- **Counter-position validator (mechanical presence + bounded model quality).** On a contested brief, the §7.8 section is present-or-disclosed (mechanical), and its steelman is not a strawman (bounded model, anchored to the counter-position grounds).
- **Coverage/confidence validator (mechanical, issue #260).** A `coverage_map` entry exists for every name in the §7.7 scope -- retrieved on by this run's own `trajectory` and touched by a claim's grounds; a `confidence` disclosure is present with a non-blank `overall_band` and a non-empty `rationale`; and `confidence.overall_band` is never the top band while `coverage_map` discloses a `thin` name -- an unjustified confidence disclosure. Any of the three blocks release. This gate is a pure presence/coherence check over the record's own `coverage_map`/`confidence` fields, as persisted; the map's CONTENT is computed separately and deterministically from the name layer (§7.7), never by this gate itself.

### 7.10 The rendered markdown answer **[FIRM]**

Alongside the JSON record, stage 6 renders a human-readable markdown answer. It presents the claims with their kind visible ((a)/(b)/(c) legible to the reader, since those carry different weight, Principle II), the counter-position section, the coverage map, the confidence disclosure, and the source-usage disclosure (§7.13). **Every confidence band it renders carries its counts next to it** (§7.4): the overall band next to the coverage counts named in its rationale, and each name's coverage band next to that name's corpus and evidence note counts. A band rendered bare is a rendering failure. On refusal it states the refusal and its reason. Rendering is deterministic: the same record renders the same markdown. This is plain rendering only; venue/length/style adaptation is Phase D (§3).

### 7.11 Per-pass model tiering & reasoning **[TENTATIVE]**

Model choice and reasoning are per-pass settings, carried in the existing `model_by_pass` / `reasoning_by_pass` config seams (PRODUCT.md §7.9), never hardcoded. Tentative starting assignments, tunable like Phase A's:
- **Analysis / synthesis (stage 4)** — **high tier, reasoning ON**. This is the judgment-heavy, once-per-brief call whose output every downstream validator checks.
- **Brief interrogation (stage 1)** and the **bounded validator model checks (stage 5)** — a cheaper tier may suffice; reasoning per pass as measured.
- **The agentic query loop (stage 3)** — tier chosen for tool-use reliability, measured on the smoke set. **Currently `production_high`** (issue #517), moved off the default low tier on a one-brief measurement: retrieval's real work is a judgment — which two names to intersect — and on P3-01 (then in the smoke set, now history under `config/briefs/sim/` after the 2026-07-30 rebuild — §9.0) the low tier called `where_names_meet` once, on a name only one book uses, assembling 24 notes from 2 sources, while the high tier called it five times and assembled 137 from 12. The deciding signal was in the low tier's own prompt either way (`find_names`' `member_count`, and each result's source span through `ToolResult.detail`), and two prompt revisions did not change what it did with it. **One brief, one draw**: the smoke set (§9) is what turns this into the measurement this bullet asks for, and it has not run yet.

Which pass runs at which tier is proven by measurement on the smoke and eval sets (§9), not asserted here.

### 7.12 The corpus-pin manifest (owned here) **[FIRM]**

Scores only compare against a pinned corpus (eval charter, shared constraint 1). Because all of `data/` is gitignored (DEC-23), the pin is a **manifest + hashes, not a commit**. The format is owned by eval #1 ([`docs/eval/01-answer-quality.md`](../docs/eval/01-answer-quality.md)); **nothing else owns it, so implementing it is part of this phase.** Minimum fields, per eval #1:
- **source list** — the ~30 sources, each with a content hash of the ingested input.
- **ingest-code SHA** — the commit the Phase-A pipeline ran at.
- **vault snapshot hash** — a hash over what retrieval actually reads (below).

The manifest is committed under `evals/corpus_pin/` (safe: ids + hashes only). Every analysis record (§7.3) records the `corpus_pin` it was produced against; two runs are comparable only if their pins match. The pin is reused by eval #3 unchanged.

**The vault snapshot hash covers the prose ids and the name layer (D6; this answers #484).** One sha256 over two things, in a stated order:

1. every `data/vault/prose/*.md` note's `chunk_id`, sorted ascending;
2. the **name-layer index**: `index.json`'s canonical name set, `alias_map.json`'s `version`, and the count of non-null disagreement records in `data/names/disagreements.jsonl`.

> **STRUCK (D6).** The v0 projection was `(chunk_id, tags)` pairs over a fixed `TAG_AXES` tuple. The axes are deleted, so the tags half of every pair is empty and the projection had silently degraded to ids alone. Retired rather than left in place looking like it still tracks something.

**Why the name layer belongs in the hash, stated plainly, because it looks like noise and is not.** The name layer is **retrieval substrate now**: `find_names`, `get_name`, `name_neighbors`, `who_cites` and `who_argues_against` all read it, and the coverage map's denominator is a name page's own `member_count`. Two runs over identical prose notes but different alias maps can reach different evidence, so they are **not** comparable, and a pin that called them comparable would be wrong. It follows that the hash **moves when a Gather run changes what the engine can find**, for example when the 130 findings Materialize cleared are restored (slice 01, #486). That is correct behaviour, not a spurious invalidation: the engine really can find something it could not find before.

**The hash covers the index; the manifest never carries the names themselves.** A canonical name is a surface form a source wrote. A hash of it is safe to commit; a list of them is source-derived content and stays under gitignored `data/`, exactly as DEC-23 requires for chunk text.

**Exactly one live manifest, always.** `resolve_pin_id` (`axial.eval.corpus_pin`) requires exactly one `*.json` directly under `evals/corpus_pin/`: zero is `MissingCorpusPinError`, more than one is `AmbiguousCorpusPinError` -- reconciling multiple simultaneously-live pins is out of scope, left to a later, measured decision. When a corpus rebuild retires a pin (DEC-42: the old pin is **kept as history**, never rewritten, and a fresh pin is generated alongside it), the retired manifest moves to `evals/corpus_pin/archive/` rather than staying beside the live one or being deleted. `resolve_pin_id` globs non-recursively, so `archive/` is invisible to it by construction: an archived pin is never a candidate for resolution and never counts toward the one-live-pin invariant, it is simply retained for history.

**Source ids are filename-fragile, and the pin inherits that.** `compute_source_id` (`axial.envelope`) is `f"{path.stem}-{content_digest(path)[:12]}"`: the filename stem verbatim, with no normalisation, plus a short content hash. Re-adding a byte-identical source file under a different filename therefore produces a *different* `source_id` while its content hash is unchanged. Everything keyed on `source_id` then stops resolving, silently: the pin's own source list, a sim case's `required_citation_source_ids` (§9.3), and every citation in an already-written analysis record. This bit the project during a corpus rebuild, so it is recorded here rather than rediscovered. Two consequences are **[FIRM]**. First, source filenames are part of the pinned corpus's identity; renaming a source file is a re-ingest, not a tidy-up, and invalidates the pin. Second, a `source_id` named by a pin, a case, or a record that the vault does not hold is a **named failure that names the missing ids**, never a silently empty retrieval result, in the same spirit as §7.9's rule for unresolvable grounds pointers.

### 7.13 The source-usage disclosure (bias investigation) **[FIRM]**

**What it is.** Every analysis record discloses what proportion of its evidence came from each source, **and the denominator alongside it**: how much of the material that source had *available* across the names this run actually queried. A source contributing 60% of the grounds while holding 22% of the member notes at those names is a signal. The contribution figure alone is not, because on its own it cannot separate a thin corpus, where that source is genuinely the only coverage, from over-selection, where the run reached past alternatives that existed.

**Why it exists.** All five rung-3 gates of §10 can pass on an analysis that draws most of its evidence from one book. Attribution is complete, grounds resolve, a counter-position is present, coverage is disclosed, confidence is banded, and the result is a **well-attributed monoculture**: one author's worldview presented as synthesis. Nothing else in this phase detects it. The founder's bias-investigation intent is the framing here, and the name layer makes it tractable: a name page's members carry their source ids, so a source weighing consistently heavier at certain names is measurable rather than merely suspected. The disclosure is diagnostic in a specific sense: it narrows the cause to one of three, which are then separable by inspection.

- **The corpus.** That source really is the only substantive coverage at those names. Its available share is high too, and the ratio is near 1.
- **The retrieval logic.** The query API's ordering favors it. The same skew reappears across briefs with unrelated requests.
- **The model.** The agent kept choosing it when alternatives were there. The trajectory log (§7.6) shows alternatives returned and passed over.

**Shape.** A field on the record (§7.3), non-nullable:

```
source_usage: {
  names_queried: [ {tool, args} ],     # union of the name queries this run made, from the trajectory (§7.6)
  denominator_by_name: { canonical: member_note_count },  # each queried name's own contribution
  sources: [ {
    source_id,
    evidence_chunk_count,               # notes of this source appearing in claim grounds
    evidence_share,                     # of all grounds notes in the run
    available_chunk_count,              # notes of this source among the member notes of names_queried
    available_share,                    # of all member notes across names_queried, corpus-wide
    usage_ratio                         # evidence_share / available_share; null when available_share is 0
  } ]
}
```

> **STRUCK (D1).** `filters_observed` was the union of tag filters queried, and the tools that produced it (`query_by_tag`, `query_by_polity`) are retired. `names_queried` is the same field doing the same job over the retrieval surface that exists. The field's shape and its `tool`-alongside-`args` rule are unchanged. Implemented in issue #491 (`axial.answer.source_usage.derive_names_queried`); `axial brief usage` joins on it, so the cross-run report is keyed on names rather than tag filters.

`names_queried` entries keep `tool` alongside `args` (issue #265 slice 01): `get_name`, `name_neighbors`, `who_cites` and `who_argues_against` all take a canonical name under the same arg key and are different queries, so the tool that produced an entry travels with it rather than being collapsed away. A `find_names` call is a name query too and is recorded with its `query` arg. `sources` lists one entry per distinct `source_id` actually appearing in the claim grounds -- never a source that only turns up in the denominator query but was never drawn on -- so `evidence_share` always sums to 1.0 across it on any run with grounds; it is empty on disposition `refuse`, and on any run whose claims carry no grounds. `names_queried` and `denominator_by_name` are populated in both cases: what the run looked at is a fact about the run whether or not it then cited anything. `usage_ratio` near 1 means the source was drawn on in proportion to what it had; well above 1 means it was drawn on harder than its availability explains.

**The names the denominator counts over are the CANONICALS those queries reached**, not the query strings: the `canonical` argument of every name-layer traversal plus every canonical `find_names` resolved (`axial.validators.coverage.retrieved_names`, the same read §7.7's coverage scope uses, imported rather than restated so the two cannot drift). `names_queried` discloses the queries; the denominator is computed over the names they landed on.

**`denominator_by_name` is why one hub name cannot hide (issue #491).** Measured over the live vault 2026-07-30: `Syria` carries 962 member notes, 15.6% of the 6,148 prose notes, and `United States`, `United Kingdom`, `France` and `Egypt` follow at 14.7%, 14.0%, 14.0% and 11.0%. **P3-04 is the smoke set's one Syria brief and is retained for exactly this reason** (§9.0, set rebuilt 2026-07-30): one place name can dominate the union and flatten `usage_ratio` and both §7.15 concentration figures toward zero regardless of how well the run selected, and P3-04 is the only brief in the set that can produce that. The five S-0N briefs anchor between 5 and 22 sources by design, so they measure the opposite end — whether a union built from mid-sized names is wide enough to flatten every ratio toward 1 on its own. The per-name contribution is therefore recorded alongside the total, so an inflated denominator is visible as data rather than only in the ratios it flattens. **No `kind` exclusion and no per-name cap is applied**: either would be a constant fitted before any measurement, and the inspection below is what decides whether one is needed.

**The denominator is a stated tunable, and the smoke set is where it is proven.** Under tags, `available_chunk_count` was that source's share of the union of chunks matching any observed filter. Under names the natural analogue -- and what v1 specifies -- is **the union of member notes across the names queried**, a note that is a member of two queried names counting once, re-queried over the pinned vault, never derived from this run's own evidence, so a source the run under-drew on still gets an honest, non-zero denominator when the corpus held it. That analogue is a hypothesis, not a proof: names overlap far more than tag filters did, so the union may be wide enough to flatten every ratio toward 1 and hide the very skew this field exists to catch. **The distribution is inspected on the smoke set (§9) before any concentration figure is read as meaning anything.** This is the same discipline §7.7's coverage band and §7.8's contested rule follow: state the tunable, prove it by inspection, then set it.

**How it is computed. No model call.** Deterministically, from data the record already holds: claim grounds resolve to vault ids, every `chunk_id` embeds its `source_id` (a parse -- `axial.query.reader.source_id_from_chunk_id`), an `artifact` grounds pointer resolves through the artifact's own `source_id` frontmatter, and the trajectory log records every name query, which the deterministic `get_name` tool (§7.5) re-runs to count the denominator over the pinned vault. A note that is a member of two queried names counts once in the union and in full under each name's own contribution. `get_name`'s members are capped at `limit` (issue #505), which a denominator cannot accept -- a member past the cap would silently shrink the corpus -- so a page over the cap pays one extra call at its own true `member_count`, the same rule §7.7's `evidence_note_count` follows. This is the same architectural family as the §7.7 coverage map: a count over data already written, never a judgment asked of a model. Implemented at `axial.answer.source_usage.compute_source_usage`, called from `build_record` (`axial.answer.record`) so every record `axial brief run` writes carries it.

**Scope discipline: diagnostic, not gating.** There is no defensible concentration threshold yet. What counts as too concentrated depends on corpus composition and on how broad the question is, and a narrow question over a corpus with one specialist source *should* concentrate. So the field is disclosed and recorded; it gates nothing.

**The promotion condition, stated concretely.** Source usage becomes a sixth rung-3 gate (§10) when, and only when, inspection across at least the smoke and eval sets (§9) over a single pinned corpus yields a `usage_ratio` distribution in which a candidate threshold separates runs the founder judges over-concentrated from runs judged legitimately concentrated, without flagging the latter. Until that inspection has happened, no threshold is asserted.

**Design for the aggregate.** One run's distribution is weak evidence. The signal appears across many runs: a source drawing several times its available share *whenever* queries touch a given name. The per-run shape above is therefore designed to aggregate cleanly, keyed on `source_id` and joinable on `names_queried`, so per-source usage ratios can be pooled across every record sharing a corpus pin. A cross-run inspection affordance over `data/analyses/` is in scope for this phase (P0-13).

### 7.14 Per-pass token usage and cost (benchmark support) **[FIRM]**

**What it is.** A field on the record (§7.3), the token/dollar-cost analogue of `model_by_pass`: for each pass that ran, the tokens it consumed and the resulting dollar cost, summed to a run total. It exists to give a benchmark sweep across many brief runs (issue #362) a cost column to read directly off `data/analyses/<brief_id>.json`, without re-deriving anything.

**Shape**, nullable only at `usd`/`total_usd`:

```
cost: {
  by_pass: {
    <pass_name>: { prompt_tokens, completion_tokens, total_tokens, usd }
  },
  total_usd
}
```

`by_pass` names exactly the passes `model_by_pass` names (empty on disposition `refuse` beyond the interrogation pass, mirroring `model_by_pass` itself). Token counts come from the OpenRouter `usage` object every `/chat/completions` response carries, read off the same response `complete()`/`complete_with_tools()` already parse — no second call. `usd` is computed against a static, in-code `$/1k-token` price table (`axial.llm.PRICE_TABLE_USD_PER_1K`) covering the models the brief pipeline currently routes to; a model id absent from that table resolves `usd` to `null` — never zero, never a failed run — and logs the gap once. `total_usd` sums whatever per-pass `usd` figures ARE known and is itself `null` only when none of them are, so one unpriced or uncaptured pass does not blank out an otherwise-real total.

**Scope discipline.** The price table is a static snapshot, not a live pricing API or an auto-refreshed table — updating it as models change is a manual, occasional edit, not a mechanism. Token/cost capture is scoped to the brief pipeline's passes (interrogate, retrieve, synthesize, counter-position); no ingestion pass is instrumented by this field. Nothing renders `cost` in the markdown answer (§7.10) or gates on it — a human-readable cost report is the run report's job (§7.15), this field only carries the raw number.

### 7.15 The run report (D9) **[FIRM]**

**What it is.** One report per brief run, written by stage 6 alongside the record at `data/runs/<brief_id>.json`, **keyed on `brief_id` and `corpus_pin` so runs join**. It is computed, not measured twice: every figure below is derived from the record (§7.3) except per-pass wall clock, which only the running process holds. Implemented at `axial.answer.run_report.build_run_report`, called from `run_brief` (issue #491).

It is a separate artifact rather than a field, because §7.3's record shape is locked and the report is a derived view. A record is the audit surface; a report is what a run's numbers are read off. Nothing gates on the report.

**Operational.**

| metric | definition |
|---|---|
| dollars and tokens | total and per pass, read off `cost` (§7.14) |
| wall clock | total and **per pass**; per-pass latency is new, since §7.14's cost capture has no time analogue |
| `model_by_pass` | which model and reasoning setting each pass ran at, off the record |
| disposition | `proceed` / `proceed_bounded` / `refuse` (§7.2) |
| trajectory | step count, tool calls, refused tool calls, empty-result calls, and **turns that added no new evidence**, off the trajectory log (§7.6) |

**Wall clock is captured per pass and the total is their SUM**, never a second stopwatch around the whole run, which would silently absorb vault I/O and disagree with its own parts. `axial.answer.run_report.PassClock` accumulates it as `run_brief` drives each stage; evidence assembly is timed under the synthesis pass it feeds, since it makes no model call and has no pass name of its own. A pass named in `model_by_pass` always carries a figure; a pass that was timed but never named (the counter-position pass on an uncontested brief) is not reported. `axial brief sweep` already times each `(brief, draw)` pair (`DrawOutcome.latency_seconds`), and with per-pass figures on the report that number becomes a cross-check on their sum rather than a competing source of truth.

**"Turns that added no new evidence" is the convergence signal §7.6 does not carry.** `get_chunk` returns one id, `assemble_evidence_ids` dedupes, and the model's own reasoning text is never persisted, so a turn re-fetching an already-seen id changes nothing downstream -- #505's run 2 made 9 such calls in 20 turns. It is counted only over turns that could have added evidence at all (a tool whose `returns_chunk_ids` is true), reported alongside that denominator, so a resolution call like `find_names` is not miscounted as a wasted turn.

**Failed tool calls are reported as a lower bound, and the report says so.** §7.6's shape is [FIRM] at `{step, tool, args, result_ids, result_count}` with no error field, so only a call naming a tool the registry does not hold is unambiguously a refusal. A registered tool rejected for malformed args is indistinguishable here from a valid call that legitimately returned nothing; both land in the reported `empty_result_calls`, which is the honest superset. An empty result is a real answer (§7.5) and is never counted as a failure.

**Accuracy.** Exactly the four measures of D8 (§10), each reported separately and never summed into one number: attribution completeness and retrieval hit (mechanical); grounding-support rate and instant-dismissal violations (judged, each under its own pass name, never by the generating model).

**The two mechanical numbers are computed with zero model calls; the two judged numbers are opt-in and are otherwise reported as not-scored with a stated reason** -- never as a 0 that reads like a measurement, and never as a silent pass. That is the same three-state discipline §10 states for a gate metric, applied to a report that gates nothing. `retrieval_hit` scores against the `required_citation_source_ids` of the §9.3 case joined to the run; the join is the brief file's own stem (`config/briefs/smoke/S-01.yaml` scores against `evals/cases/sim/S-01.json`), and a brief with no case file has no oracle, which the report states rather than scoring as 0. `grounding_support_rate` reuses the rung-3 grounding gate wholesale rather than opening a second judge seam.

**Response quality.**

| metric | definition |
|---|---|
| sources cited | distinct `source_id`s in claim grounds |
| per-source share | `source_usage.evidence_share` (§7.13) |
| concentration | top-1 share and HHI over those shares: one number for monoculture |
| usage ratio | `source_usage.usage_ratio`; its denominator re-bases onto names queried (§7.13) |
| claim mix | count and share of (a) / (b) / (c) |
| **cross-source rate** | **the headline.** Share of (b) claims whose grounds span two or more distinct sources |
| grounds per claim | mean and median; share of claims with ≥2 grounds |
| retrieval precision | distinct notes cited ÷ distinct notes retrieved (`assemble_evidence_ids`' own fold, so it measures the selection the run made) |
| name reach | distinct name pages touched; share of grounds notes that are members of a name the answer is about |
| disagreement reuse | did the run reach a note a Gather finding also cites (a hint hit, per D4; never whether the finding was repeated) |
| coverage bands | count of names disclosed thin / moderate / dense (§7.7) |
| answer size | claim count, rendered word count |

**Why the cross-source rate is the headline (D9).** Phase A v1's whole premise is cross-book meeting points, and a (b) claim grounded in one book has produced no synthesis however well it is attributed. It is the one number that says whether the graph did any work. Every other metric here can look healthy on a well-attributed single-book summary. It keys on distinct `source_id`s in a claim's grounds, not on the name that led there, so **nothing in §7.13's denominator caveat weakens it** -- worth stating, so it and `name reach` are not read as measuring the same thing. A run with no (b) claim at all reports `null` with a reason rather than a vacuous 0 or 1.

**`name reach`'s membership denominator is the §7.7 coverage scope, not every name the evidence mentions.** Measured over the live vault 2026-07-30: 67.2% of the 62,704 name pages touch exactly one note, 64.3% of the note-to-note joins come from the top 20 names (17 of them countries, regions, cities or world wars), and the average note "meets" 1,069 others. So "a member of some name page" is true of nearly every note and would read high for trivial reasons. The raw count of name pages the claims touch is still disclosed on its own -- it runs to ~423 per real evidence set, and that size is itself the signal.

**No threshold is asserted on any of these.** They are disclosed and joined across runs; §10 owns what gates. A metric here becomes a gate only under the discipline §7.13 states: inspect the distribution, find a threshold that separates what the founder judges good from what he judges bad, then set it.

---

## 8. Requirements

### Must-Have (P0)

**P0-1 Brief intake & interrogation pre-pass (charter Principle III).**
- [ ] Reads a versioned brief (§7.1) and emits a structured interrogation result (§7.2) carrying premises found, bounds proposed, and a refusal-or-null.
- [ ] A deterministic wrapper sets `disposition` to exactly one of `proceed` / `proceed_bounded` / `refuse` from the structured result; the model does not decide release on its own.
- [ ] Bounding and refusal are first-class completed runs: on `refuse`, the record is written, the answer states the refusal and its reason, and no synthesis call is made. Observable: a brief whose premise the corpus contradicts yields a `refuse` or `proceed_bounded` disposition with the premise named, never a confident synthesis over the smuggled premise.

**P0-2 Vault query API, deterministic and LLM-free (charter Principle I substrate; the foundation slice).**
- [ ] Exposes the §7.5 tool set over the vault and the name layer, making **zero LLM calls**. Observable: the full tool set is exercised in tests with no LLM client present.
- [ ] Every tool returns auditable vault ids (`chunk_id` / `artifact_id` / canonical name) plus the metadata and text needed to reason. `find_names` resolves through the alias map and the persisted name vectors, never string equality; `who_cites` and `who_argues_against` read the notes' own `citations` and `arguing_against` answers.
- [ ] Determinism: the same query over the same pinned vault returns the same ids in the same order. Every ranked tool states a total order, tie-break included.
- [ ] **The embedding-model bar is relaxed to an LLM bar, and only for `find_names` (D10).** Its fourth tier embeds the query string with the local sentence-transformer named in `data/names/similarity_manifest.json`, against vectors Reconcile already persisted. No network call, no LLM, no chunk index. Observable: tiers 1–3 are exercised with no encoder loaded at all, and tier 4 is exercised against a stub encoder. The encoder itself is built **at most once per process and from local files only** (issue #524) — a construction per call reached huggingface.co on every semantic query to re-check weights already on disk, which is the network call this line rules out.
- [ ] A query that resolves to no name returns an empty result the caller can report as an honest resolution failure — never an error, never silence. Observable: a query the corpus genuinely does not hold returns `[]` distinguishably from an error, while `find_names("SDF")` does not. Measured 2026-07-30: `zzqqx nonexistent scholar` is cut at 0.4518 and returns `[]`; `SDF` is an exact hit. (The earlier `AANES` observable is retired — the corpus holds that entity under its full name, so it tests a name-layer fragmentation gap, not resolution failure. See §7.5.)

**P0-3 Retrieval planning & the agentic query loop (charter §3, Principle I).**
- [ ] A model-driven agent plans retrieval from the interrogation result and case anchor, calls only the stage-2 tools, and **re-queries when results are thin** — the behaviour a fixed pipeline cannot express.
- [ ] **Case-as-anchor, not case-as-fence**: the agent may retrieve corpus-grounded material about other polities that bears on the case. Observable: a country-case brief can surface cross-polity evidence, and a brief answered only from case-scoped chunks is not by construction preferred.
- [ ] Every tool call and every returned chunk id is appended to the retrieval trajectory log (§7.6), in call order. The loop runs under a bounded step budget (a stated tunable).

**P0-4 Evidence assembly & analysis emitting the claim graph (charter Principles I, II).**
- [ ] The retrieved evidence set is assembled and inspectable **before** the synthesis call (inspect-before-spend, P0-9).
- [ ] The synthesis pass applies the named lens and axial coding across the evidence and emits the claim graph (§7.4): **every claim is marked (a)/(b)/(c)** and every (a)/(b) claim carries at least one grounds pointer to a real vault id. Observable: no claim in the record has an unmarked kind, and no (a)/(b) claim has empty grounds.
- [ ] Claims are **grounded by construction**: the synthesis reasons over the retrieved grounds, and the prompt forbids asserting from parametric memory or the open web. A (b) cross-source inference is never voiced as a source assertion.
- [ ] Unrequested corpus-grounded analogues, when raised, are emitted as (b) claims with real grounds, never as unlabeled findings (charter §3).

**P0-5 Attribution validator (charter Principle II).**
- [ ] A **deterministic** validator confirms every claim has a `kind` in `{a,b,c}` and every (a)/(b) claim has at least one `grounds` pointer that resolves to a real vault id. A failure blocks release. Observable: a record with an unmarked or unresolvable-grounds claim fails the validator.
- [ ] The (b) seam is honest: no claim marked (b) is phrased as a source assertion; where mechanical detection is not possible, a bounded independent model check (never the generating model) flags it. This is the first thing the attribution-fidelity gate checks (§10, charter Principle II).

**P0-6 Counter-position validator (charter Principle IV).**
- [ ] On a **contested** brief, the record carries a counter-position section that is either present with non-empty grounds or an explicit corpus-one-sided disclosure with a reason (§7.8). Absence of both fails the validator.
- [ ] Contested-ness is determined from corpus signal, not the brief's wording (§7.8, D3): grounds notes whose stated positions differ (`position` where the note carries it, `position_of` otherwise — §7.5, issue #496) **and** where one names the other in `arguing_against`, or a touched name whose page carries a Gather disagreement. A stated tunable, proven on the smoke set. Observable: a brief over a genuinely contested question with no counter-position and no one-sided disclosure is rejected as a red flag, not passed as clean; a brief whose evidence merely holds two different position values with no `arguing_against` pointing between them is not flagged contested on that basis alone.
- [ ] **A Gather finding never becomes a ground (D4).** Observable: no `counter_position.grounds` entry, and no claim's `grounds` entry, points at a name page or a disagreement record; every one resolves to a prose note or artifact through `get_chunk`/`get_artifact`.

**P0-7 Coverage & confidence disclosure (charter Principle V, §3).**
- [ ] A **per-name coverage map** is computed deterministically from the name layer (§7.7) for every name the claims touch, carrying `corpus_note_count` (the page's own `member_count`), `evidence_note_count` and a disclosed coverage band. Observable: given a brief whose claims touch a thinly-covered name, that name is disclosed as thin; and the map covers concepts and scholars, not only polities.
- [ ] Every answer carries a disclosed `confidence` with a rationale; a claim over a thinly-covered name is not disclosed with dense-case confidence. A missing coverage map or confidence disclosure blocks release (§7.9).
- [ ] Confidence is one of the three bands `high` / `medium` / `low`, per-claim and overall, never a numeric score (§7.4). Observable: no record carries a numeric confidence value, and every rendered band appears next to the coverage counts that justify it (§7.10).

**P0-8 Analysis record & rendered answer (output contract).**
- [ ] One analysis-record JSON per brief run at `data/analyses/<brief_id>.json`, carrying the full §7.3 shape (brief, corpus_pin, lens, interrogation, claims, counter_position, coverage_map, confidence, source_usage, trajectory, model_by_pass, cost). No field nullable except as stated in §7.3–§7.8, §7.13, and §7.14.
- [ ] A deterministic markdown answer is rendered from the record (§7.10), with claim kinds legible to the reader. The same record renders the same markdown.
- [ ] Each record records the `corpus_pin` it was produced against. (A `schema_version` field sat beside it until issue #524: the value was read off a note field zero live prose notes carry, so every record wrote `null`. The pin resolves to a manifest carrying `vault_snapshot_hash`, an exact content hash of the vault, which is strictly stronger.)

**P0-9 CLI surface with inspect-before-spend.**
- [ ] `axial brief run <brief_file>` runs the full engine (stages 1–6) and writes the analysis record and answer.
- [ ] `axial brief examine <brief_file>` runs the interrogation and retrieval and reports the assembled evidence set — retrieved note ids with each note's own one-sentence `claim`, a plain count of assembled notes per name, and the interrogation result — **without the expensive synthesis call**, analogous to `axial chunk examine` (PRODUCT.md §7.7). Observable: `examine` makes zero stage-4 synthesis calls and its cost is bounded to interrogation + retrieval.
  **That per-name figure is an inspection count, not the §7.7 coverage map (issue #489).** No band, no corpus denominator, no confidence: the §7.7 map is computed from `names_touched` over the claim graph, which does not exist before the call this command exists to precede. One banded map, one inspection count — shipping two per-name computations with different denominators is how a disclosure stops meaning anything. An abstained field never appears in this report either, for the same reason it never reaches the prompt.

**P0-10 Corpus-pin manifest (owned here; eval #1 format).**
- [ ] Implements the corpus-pin manifest of §7.12 to eval #1's format (source list + content hashes, ingest-code SHA, vault snapshot hash over prose note ids **plus the name-layer index**, never chunk_text and never a name list per DEC-23), committed under `evals/corpus_pin/`. Nothing else in the product owns this format, so it lands as part of this phase.
- [ ] Every analysis record references its pin; two records are comparable only if their pins match.
- [ ] Observable (D6, #484): restoring a Gather section that was cleared, with no prose note changed, moves the vault snapshot hash and so requires a fresh pin.

**P0-11 Brief sets landed as versioned data.**
- [ ] Six short briefs under `config/briefs/smoke/` and five hard briefs under `config/briefs/eval/`, real files in the §7.1 shape (§9, D7). Observable: both sets are readable from the repo and drive the harness runs with no Academic dependency.
- [ ] The six smoke briefs run on every slice; the five hard briefs run when the engine is stable. Each smoke brief has a case file under `evals/cases/sim/`; the one new hard brief lands with a case file authored alongside it or that slot has no mechanical oracle.
- [ ] `config/briefs/sim/` is retained untouched as history and is no longer swept. `config/briefs/dev/` holds small fixture briefs for tests and is not a brief set. The 26 parked Academic research questions are **not coming** (#250, closed not planned), so these sets are permanent rather than a stand-in.

**P0-12 Rung-3 eval-gate harnesses built and dry-runnable (charter §2 rung 3).**
- [ ] The five rung-3 gate harnesses of §10 (attribution fidelity, grounding, synthesis quality, calibration, adversarial brief red-teaming) are implemented as **pass/fail gates**, each with a named metric and a tunable starting threshold, and are **dry-runnable** against the smoke set and synthetic cases (their process-side oracles are programmatic; eval charter, sequencing). Their fixtures read the §7.3 record and the §7.5 tool set as v1 defines them.
- [ ] The four accuracy measures of §10.0 are computed and reported separately, never summed. Observable: the run report (§7.15) carries four accuracy figures, and no field anywhere holds a single "accuracy" number.
- [ ] The gates read the analysis record (§7.3) and the trajectory log (§7.6). All five are **corpus-anchored** and report in the trusted tier once a pin resolves over the full rebuilt corpus; **no gate's `trusted` flag depends on academic-authored cases existing** (§9.1, §9.2). Observable: with a resolved pin over the full corpus and an empty `evals/cases/`, every gate reports `trusted: true`.
- [ ] Answer quality (eval #1) is measured by the §9.4 reviewer panel, an **offline instrument run on a sample**, not a gate and not a pipeline stage. It consumes the rendered analysis plus resolved chunk text, never an academic-authored case file, and reports only in the refereed tier with its ceiling and sampling frame disclosed. Observable: a full brief run makes zero reviewer calls, and no analysis record or gate report carries a panel-derived score.

**P0-13 Source-usage disclosure (bias investigation; diagnostic, not gating).**
- [ ] Every analysis record carries the §7.13 `source_usage` field: per source, its evidence note count and share, **and the denominator** — the count and share of that source's notes available across `names_queried`, the names the run actually queried — plus the `usage_ratio` between them. Observable: a record whose grounds come disproportionately from one source shows that source's share above its available share, and the two figures are always present together.
- [ ] It is computed **deterministically, with zero model calls**, from the claim grounds, the `source_id` embedded in each `chunk_id`, and the trajectory log's recorded name queries, re-counted over the pinned vault through the §7.5 tools. Observable: the field is produced in tests with no LLM client present, and the same record over the same pinned vault yields the same figures.
- [ ] It is **disclosed and recorded, and gates nothing**: no threshold on `usage_ratio` blocks release, and no rung-3 gate reads it (§10). The promotion condition to a sixth gate is stated in §7.13 and is not met by this phase.
- [ ] The union-of-member-notes denominator is **inspected on the smoke set before any concentration figure is read as meaning anything** (§7.13). Observable: the smoke run reports the `usage_ratio` distribution, and a distribution flat at 1 across every source is reported as a denominator problem rather than as an absence of skew.
- [ ] A cross-run inspection affordance `axial brief usage` reads the records under `data/analyses/` sharing a corpus pin and reports per-source usage ratios aggregated across runs and broken down by name, so a source that draws several times its available share whenever queries touch a given name is visible. Consistent with the inspect-before-spend `examine` precedent (P0-9), it makes **zero model calls**. Observable: over a set of recorded runs, the command names the heaviest-weighing sources and the names at which they weigh heaviest.
- [ ] The rendered answer (§7.10) shows the disclosure alongside the coverage map.

**P0-14 The run report (D9).**
- [ ] One report per brief run at `data/runs/<brief_id>.json`, keyed on `brief_id` and `corpus_pin`, carrying the operational, accuracy and response-quality metric sets of §7.15. Observable: two runs of the same brief at the same pin join on those two keys.
- [ ] **Per-pass wall clock is captured**, not just the run total. Observable: a report names an elapsed time for every pass `model_by_pass` names. This is the one figure the record cannot supply.
- [ ] The **cross-source rate**, the share of (b) claims whose grounds span two or more distinct sources, is reported as the headline quality number (D9). Observable: a run every one of whose (b) claims is grounded in a single book reports a cross-source rate of 0, however well attributed it is.
- [ ] Everything else in the report is derived from the analysis record with **zero model calls** and no second measurement. Observable: the report is regenerable from a persisted record alone, latency excepted, and gates nothing.

### Nice-to-Have (P1)

- **P1-1** A standalone trajectory store richer than the in-record log, if eval #3 needs replay across runs.
- **P1-2** Calibration reporting via a three-bar band reliability diagram (observed correctness rate per band against its target, §7.4) in addition to the headline pass/fail of the band-wise gate.
- **P1-3** A per-brief run log capturing agent judgment calls (re-queries, dead-ends recovered), mirroring PRODUCT.md P1-3.

### Future Considerations (P2 — design for, don't build)

- **P2-1** A **chunk** embedding / vector retrieval index, **reopened only on demonstrated recall failure** on the hard briefs (§3 non-goal 4, D10, Open Questions). The name vectors `find_names` already reads are not this.
- **P2-2** Second-domain briefs proving the engine is domain-portable by schema and lens data, no code change (mirrors PRODUCT.md P2-1).
- **P2-3** Cross-brief caching / batching, once single-brief quality is proven.

---

## 9. Referee data & the answer-quality seam

**No academic input is coming, and none is needed.** Issues #250 (the 26 parked research questions) and #295 (simulated-path teardown) were closed as *not planned* on 2026-07-24. The AI-simulated path DEC-29 opened as an interim stand-in is now the permanent one. DEC-29's "interim and throwaway" framing is **superseded**: nothing under `config/briefs/sim/` or `evals/cases/sim/` is torn down, nothing is re-run on real academic input, and no gate waits on a human referee.

**Brief and case sources.**

- **Smoke briefs** — `config/briefs/smoke/`, six short briefs in the §7.1 shape, run on every slice (§9.0, P0-11).
- **Eval briefs** — `config/briefs/eval/`, five hard briefs, run when the engine is stable (§9.0, P0-11).
- **Adversarial seeded briefs** — `config/briefs/adversarial/`, authored in-repo, each carrying its own declared premise. The seed is the answer key (§10).
- **Sim hard cases** — `evals/cases/sim/`, retained permanently, with the field-by-field contract of §9.3.
- `config/briefs/sim/` is the v0 30-brief pool, kept as history. `config/briefs/dev/` holds small fixture briefs for tests. Neither is a brief set.

### 9.0 The two brief sets (D7) **[FIRM]**

> **STRUCK (D7).** The 30-brief backlog under `config/briefs/sim/` was the phase's one brief set, and the sweep across it was the phase's one measurement. It is retired as a running set: 30 briefs is a slow, expensive loop that measured six gate metrics of which only three carried ranking signal (#362, closed superseded). Two small named sets replace it. Nothing under `config/briefs/sim/` is deleted, torn down, or rewritten; it stays as history.

Two sets, real files rather than a manifest over a pool. **The eval brief is the one that counts**, so it is authored, not selected.

**Smoke — six short briefs, six retrieval shapes, run on every slice.**

| brief | chars | shape it exercises | anchor spread |
|---|---|---|---|
| P3-04 | 183 | hub anchor at the corpus's centre of gravity | `Syria` 962 notes / 22 sources |
| S-01 | 189 | scholar against scholar over a densely covered question | Tilly 154/20, Mann 377/15 |
| S-02 | 197 | a concept several books use in incompatible ways | `nationalism` 158/18 |
| S-03 | 194 | a concept whose own book is in the corpus | `quasi-states` 51/**5** |
| S-04 | 189 | thin coverage | `Transnistria` 36/**2** |
| S-05 | 179 | single-source concentration | `Somaliland` 52/**1** |

All six have case files under `evals/cases/sim/`, joined on the file stem, so each smoke run scores the mechanical retrieval-hit oracle (§9.3). **No P1 or P5 brief is in this set**: both personas write long compound questions by construction, which is why they carry the hard set instead.

**The set was rebuilt on 2026-07-30 (founder decision) and is no longer Syria-concentrated.** All five original briefs were Syria briefs, which left most of the corpus unexercised: 25 of the 31 sources are not about Syria, and the name layer's widest meeting points are `Charles Tilly` (20 sources), `Max Weber` (19), `nationalism` (18) and `World War I` (19). S-01 through S-05 were authored against the measured index by a model with no access to this repo, then verified anchor by anchor before landing; spreads above are measured over the live index 2026-07-30. `config/briefs/sim/` still holds the originals as history.

**P3-04 is retained as the set's one Syria brief, and the reason is §7.13.** The denominator inspection this phase owes is stated in terms of a hub name swamping the union of member notes. Every S-0N anchor is mid-sized by design (5 to 22 sources, 36 to 377 notes), so a Syria-free set would leave that inspection with nothing to bite on.

**S-04 and S-05 do not name the finding they probe.** Both measure whether a run *notices* thin evidence and single-source concentration unprompted, so a question that says the evidence is thin, or that every note comes from one book, would make a pass prove only instruction-following. The disclosure requirement sits in the §9.3 rubric instead.

**`axial brief smoke` runs the set** (issue #491): six briefs, one draw each, **mechanical checks only** -- the record validates against the §7.3 shape and every grounds pointer resolves; `disposition` is one of the three; the coverage map is non-empty (the empty-map regression #490 exists to fix must be loud, and only a refusal legitimately skips it); no unhandled exception and no tool call the dispatcher had to refuse; and a per-brief cost and latency budget. Nothing there is a quality judgment. It is a thin front end over `run_sweep` -- resume, one fresh client per draw, per-draw latency and per-pass cost aggregation already live there -- with three deliberate differences: the checks and budgets, **a non-zero exit on any mechanical failure** (`axial brief sweep` returns 0 even with failed draws, mirroring `axial run`'s loop rule; smoke inverts that because it is a gate), and **gate scoring off** through one boolean seam, because the four rung-3 gates are a quality judgment and a model bill that would make the cost budget measure the judge instead of the run.

**The budgets are stated tunables set from the first real runs of the set, never guessed in advance, and until then they are UNSET.** `smoke.max_usd_per_brief` and `smoke.max_seconds_per_brief` (`config/pipeline.yaml`) are present and explicitly `null`, with no code-level fallback: an unset budget **skips** its check rather than passing vacuously or failing for a number nobody measured, and the command's own output says `UNMEASURED` where the figure would be.

**Which names a run reached is printed, not asserted.** Whether a run silently substituted a nearest-neighbour name is a judgment, and a brief-specific rule in `src/` would be domain content as code. So the command prints the names each run queried and the founder reads them. **The name-layer fragmentation case left the set with P4-04** (the corpus holds `Autonomous Administration of North and East Syria` with 2 members plus an unmerged `AANS` node, and the acronym `AANES` reaches neither — measured 2026-07-30, §7.5, filed against Phase A as #498). Nothing in the rebuilt set replaces it. That is a known cut, not an oversight: no mechanical check ever asserted on it, so what was lost is one printed read, and the brief survives in `config/briefs/sim/`.

**Eval — five hard briefs, five theory clusters, run when the engine is stable.**

| brief | what it tests |
|---|---|
| **new** — Bayat vs Tilly | organized challengers against revolution-without-revolutionaries, over the same object |
| P1-02 | White × Batatu, a causal chain across two books that barely overlap |
| P5-01 | Kalyvas control logic mapped onto observed violence; 5 required sources, 4 dismissal criteria |
| P5-04 | victim and perpetrator discourse, a different corpus region entirely |
| P4-01 | juridical against empirical sovereignty, Jackson versus Caspersen |

The new brief, drafted:

```yaml
case: "Syria, 2011–2024"
request: "Tilly makes organized challengers and their accumulated resources the
  mechanism that converts a revolutionary situation into a revolutionary outcome.
  Bayat argues the 2011 uprisings were revolutions without revolutionaries — mass
  mobilization uncoupled from the organization and ideas that conversion is
  supposed to require. Which account better explains sustained Syrian mobilization
  without a revolutionary outcome? Where the two disagree about what organization
  is for, is Bayat describing a case Tilly's model excludes, or a failure of the
  model itself?"
```

Its last clause cannot be answered by summarising either book, so it forces a cross-source (b) claim, which is exactly what §7.15's headline metric measures. **It needs a case file authored alongside it or that slot loses its mechanical oracle.** Proposed `required_citation_source_ids`: `bayat-2017-ce6bb0643cfb`, `tilly-1978-f908c910464c`, `beshara-2011-8410a9059300`, `vignal-2021-c7005c2bf8ef`, `kao-2025-ab19e646ab7d`. All five resolve against `data/envelopes/`.

**P1-01 moves to the adversarial set.** It asks about "Tilly's coercive-extraction cycle", which is *Coercion, Capital and European States*. The corpus holds Tilly 1978, *From Mobilization to Revolution*. That is a smuggled premise the interrogation pre-pass should catch, so the brief is worth keeping: as a seeded adversarial case with `kind: smuggled_premise` (§10), not as a synthesis eval.

### 9.1 The dependency, stated narrowly **[FIRM]**

Earlier versions of this spec said the rung-3 gates could not produce trusted numbers until the vault, the pin, and academic-authored hard cases existed together. That claim was over-stated and is corrected here. **All five rung-3 gates of §10 are corpus-anchored: every judgment each asks for is anchored to material the repo or the vault already holds, so none of them needs a human referee.**

- **Attribution fidelity.** Mechanical completeness scoring, plus the (b)-seam check `validate_attribution` already runs. Nothing external.
- **Adversarial red-teaming.** Scored against briefs authored in-repo whose `seeded` block states the premise plainly. The seed *is* the answer key.
- **Grounding.** An independent model judges whether the resolved chunk text a claim cites supports that claim. It judges support against material in the vault, not correctness against an expected answer.
- **Calibration.** Judges each claim against its own resolved grounds, reusing grounding's resolution path. Same anchor, same self-grading guard.
- **Synthesis quality.** Counter-position presence reuses the counter-position validator wholesale; steelman quality uses that validator's own steelman/strawman check against the counter-position's own grounds.

The genuinely narrow thing the Academic was needed for is **eval #1's answer-quality referee**: the `expected_answer` ground truth, and the rubric bar §10's table names for steelman quality. That is one question, not five.

So the honest dependency is: **the five gates produce real numbers as soon as the full ~30-source vault and the pinned corpus manifest (P0-10) exist.** Answer quality has no human referee and never will. §9.4 replaces it with an offline eval instrument, sampled and periodic rather than wired into any run.

### 9.2 Two-tier reporting **[FIRM]**

Every rung-3 number lands in exactly one of two tiers, and the tier travels with the number.

**Trusted tier: the five gates of §10.** A gate report is `trusted: true` when two conditions hold: the corpus pin resolves unambiguously (§7.12), and the vault scored is the full rebuilt corpus that pin names. **The presence of academic-authored cases is not a condition and must not be treated as one.** Numbers in this tier are reported plainly, with no simulated-data caveat, because nothing simulated enters them: the briefs are inputs, not answer keys, and every judgment is anchored to real corpus text.

*Observable:* with a resolved pin over the full corpus and zero files under `evals/cases/`, all five gates report `trusted: true`.

**What the trusted-tier report scores.** The four record-based gates (`attribution-fidelity`, `grounding`, `synthesis-quality`, `calibration`) score **one draw per brief**, never every draw. Repeat draws of one brief are the same question asked again, so pooling them inflates `n` with pseudo-replicates and lets a brief that happened to run more often weigh heavier than one that ran once. The fifth gate, `adversarial`, never scores these records at all: it takes seeded briefs whose `expected_disposition` is the answer key (`config/briefs/adversarial/`), so it scores its own seeds and lands in the same tier by the same two conditions. Per-brief gate scores computed across a brief's own draws are a **different artifact** owned by the benchmark sweep (issue #368); they feed its performance-tier bucketing and are not this report.

**Refereed tier: answer quality, measured offline and periodically (eval #1).** Answer quality is measured by the §9.4 peer-reviewer panel, which runs **offline against a sample**, not per run. A number in this tier belongs to a **measurement run** and its stated sampling frame; it never belongs to a single analysis.

Three consequences are **[FIRM]**, and each is separately observable:

- **No analysis record carries a panel verdict.** The §7.3 record shape is closed and gains no reviewer field. A brief run neither triggers a panel nor waits for one.
- **No gate report waits on a panel.** A gate is complete and `trusted` on its own terms (the paragraph above). A gate report that names a missing panel verdict as a reason for being untrusted is wrong, because most runs will never receive one by design.
- **Every panel number is reported with a disclosed ceiling** naming its referee and its frame: that the referee is a model panel, how many reviewers ran, which vendors they came from, the spread across them, the sample the run scored, and the corpus pin it scored at.

**No number in this tier may ever be reported, aggregated, cited, or promoted as "measured quality against human expert judgment."** There is no human expert in this product's loop. A model-refereed score relabelled as a human-validated one is the manufactured-precision failure §7.4 forbids, wearing a different costume, and it is the one way this phase can launder its own limits.

*Observable:* an answer-quality report that omits the referee disclosure or its sampling frame, or that attributes its score to a human adjudicator, is invalid and must not be released. An analysis record or gate report carrying a panel-derived score is likewise invalid.

### 9.3 The sim case set (permanent) **[FIRM]**

`evals/cases/sim/` (21 committed cases) is retained permanently, **unchanged by v1**. Its shape is unchanged (`case_id`, `question`, `answer_kind` ∈ {`expected_answer`, `rubric`}, `required_citation_source_ids`, `rubric`, `instant_dismissal_criteria`; ids only, safe per DEC-23). Three fields carry very different weight:

- **`required_citation_source_ids` stays a first-class oracle, and Phase A v1 did not break it.** It is **mechanical**: did this run's claim grounds reach the sources the case names? That question needs no judgment, no referee and no model call, so it keeps its role in eval #3's retrieval-hit reporting and in §7.15's accuracy set. It inherits §7.12's source-id fragility: a case's citation ids only resolve against a corpus whose `source_id`s still match, and a case naming an id the vault does not hold is a named failure. **Verified 2026-07-29: every `source_id` named by the 21 cases resolves against `data/envelopes/`.** 28 distinct ids across 97 references, all present. This is the one mechanical accuracy oracle the phase has, and it survived the rebuild intact.
- **`instant_dismissal_criteria` is non-empty on all 21 cases and is WIRED as of issue #491.** It was a real judged oracle sitting unused -- no code anywhere in `src/` referenced it. `axial.answer.dismissal.judge_instant_dismissal` now runs it: one bounded call per criterion against the run's own **rendered answer** (§7.10, which is what a dismissal criterion is about), under its own pass name `axial.llm.INSTANT_DISMISSAL_PASS_NAME`, behind the same self-grading guard the grounding gate carries -- the judge must resolve to a different model than `SYNTHESIZE_PASS_NAME`, and the guard raises before any call is made. The result is a violation COUNT and rate on the run report (§7.15), never inverted into a score, and **it is not a sixth gate** (§10.0): no violation rate has ever been observed, so promotion follows §7.13's stated discipline. A case stating no criterion reports `null`, never a vacuous 0 out of 0.

  **Both oracle fields are read through one reader** (`axial.eval.cases.load_case`), which deliberately does **not** expose `expected_answer`: the bullet below retires it as the referee and forbids putting it in a reviewer packet, and a reader that handed it back would invite exactly that. A missing or malformed case file yields `None` rather than an error -- a case set is an oracle a run is scored against, not a precondition of the run.
- **`expected_answer` is retired as the primary referee.** It is one model's opinion of a good answer, written before the corpus was rebuilt, and scoring against it measures agreement with that opinion rather than quality. It is retained as a case-authoring artifact and a human reading aid. It is **never placed in a reviewer packet** (§9.4): showing a reviewer a pre-written answer anchors it to that answer, which is the failure the panel exists to avoid.
- **`expected_answer` is retired as the primary referee.** It is one model's opinion of a good answer, written before the corpus was rebuilt, and scoring against it measures agreement with that opinion rather than quality. It is retained as a case-authoring artifact and a human reading aid. It is **never placed in a reviewer packet** (§9.4): showing a reviewer a pre-written answer anchors it to that answer, which is the failure the panel exists to avoid.

`origin: simulated` stays on every case. It is now a permanent provenance fact, not a countdown to teardown.

### 9.4 The sealed-packet peer-reviewer panel: an offline eval instrument **[FIRM]**

Founder-settled 2026-07-24. Phase B owns eval #1, so the design is specified here; Phase C cites this section rather than restating it.

**What it is not.** The panel is **not part of the production pipeline**. It is not a seventh stage, not a validator, not a rung-3 gate, and not a referee wired into per-run execution. **No production analysis run receives a panel verdict**, and nothing in the engine blocks, waits on, or reads one. A brief run is complete when stage 6 has written its record and rendered its answer (§5), exactly as before this section existed.

**What it is.** An **eval method for measuring answer accuracy**, run **offline, on a sample**. It is the instrument that answers "how good are the answers" at a point in time, over a chosen set of cases and model combinations. It produces a measurement of the system, not a score attached to any one analysis.

**Sampling design.** A panel run scores a deliberately chosen sample, not everything:

- **Across performance tiers.** Cases are picked to span the observed range, not just the good ones. A panel run over only strong outputs measures nothing useful; the tiers are what make the measurement honest.
- **Across model combinations.** The same case is reviewed across the model wirings under comparison, so the measurement can separate the analysis engine from the model driving it.

Which cases and which combinations is the sampling frame's own question, set per measurement run and recorded with the result. What is FIRM is that a panel run states its frame: which cases, drawn from which tiers, under which model combinations, at which corpus pin.

**Cadence.** A panel run is an occasional, deliberate act: after a corpus rebuild, after a model rewiring, or when a benchmark sweep needs a quality axis. It is never triggered by an ordinary brief run.

**The seven integrity properties below are unchanged by any of that.** They govern *how* a reviewer is guarded, not how often it runs.

1. **A stranger to the repo.** Each reviewer is a frontier model that has never seen this repository, its specs, its prompts, its lens vocabulary, or its cases. It reads the analysis the way a journal referee reads a submission: on what is in front of it, with no access to how it was made.

2. **A sealed packet, enforced by tooling.** A reviewer receives exactly one self-contained packet: the rendered analysis (§7.10), plus the resolved text of every chunk and artifact every claim cites. Nothing else. The reviewer runs with **no file-reading, no repository access and no web tools**, and that restriction is enforced by the tool surface it is given, never by an instruction in its prompt. An agent holding file tools will read the repo whatever the prompt tells it, and a reviewer that has read the prompt which generated the analysis is not a referee. *Observable:* the assembled packet contains no path into the repo, and the reviewer call is made with an empty tool registry.

3. **A different vendor, not merely a different model.** Each reviewer must resolve to a model from a **different vendor** than the model that generated the analysis. This is deliberately stricter than the `SelfGradingError` guard the five gates already carry, which requires only a different model id. Shared training priors survive within a model family, so a family-mate's agreement is weak evidence. A vendor collision is an error raised **before any reviewer call**, exactly as the existing guard is.

4. **N ≥ 3 independent reviewers, and the spread is the error bar.** Each reviews the same packet without seeing the others' verdicts. The report carries every reviewer's verdict, the aggregate, **and the spread**. A mean without a spread is not reportable: three reviewers splitting 1/3/5 and three agreeing on 3 are different results and must never render identically.

5. **A structured verdict, never free prose.** Each reviewer returns a fixed shape scoring eval #1's dimensions separately (factual correctness, citation grounding, completeness), each as an ordinal band, plus a list of named defects with the claim ids they attach to. Free prose is unparseable, unaggregable, and invites exactly the fluency this phase is built to distrust. A response that does not parse to the shape is a failed reviewer call, never a silently imputed score.

6. **A positive control, mandatory before trust.** The panel produces **no reportable number** until it has been run against packets carrying **planted, known defects** and has caught them. The minimum plant set is three: a **mis-grounded claim** (cited chunk does not support the claim), a **strawmanned counter-position**, and an **overconfident band** (a `high`-band claim over a polity the coverage map discloses as thin). LLM judges are systematically generous and are moved by confident prose, so a panel that waves a defective packet through is measuring nothing, and its clean verdicts on real packets are worthless until it is fixed. **No live positive control exists anywhere in this repo today (issue #323); this is the first.** The control's own results are reported alongside the panel's, so a reader can see which defects the referee is known to catch and which it is not.

7. **Packets are assembled at runtime and never committed.** A packet carries resolved chunk text from copyrighted books. All of `data/` is gitignored for exactly that reason (DEC-23), and the rule extends here without exception: packets are built at run time, sent, and not written into the repository. What may be committed is the **verdict**: scores, named defects, reviewer model ids and vendors, and the ids of the chunks cited, never their text.

**Cost is bounded by construction.** N ≥ 3 frontier reviewers is expensive per packet and would be indefensible per run. Sampling is what makes it affordable: a panel run scores a handful of cases across tiers and model combinations, occasionally, rather than every analysis the engine ever produces. There is no per-run cost line to budget, and none is added to §7.14's `cost` field, which stays scoped to the brief pipeline's own passes.

**The benchmark seam (issue #362).** The benchmark sweep is the panel's natural consumer and is specified there, not here. #362 measures cost, latency, self-consistency and gate scores, and has **no true answer-quality referee**; the panel is exactly that missing axis. Its slice 1 buckets brief runs into performance tiers, and its slice 2 runs a brief per tier across model combinations, which is the §9.4 sampling frame already. So Phase B owes it a **seam, not a mechanism**:

- The panel consumes what a sweep already has: a rendered analysis (§7.10) plus the resolved text of the chunks its claims cite, resolvable from the record's grounds through the §7.5 tools. It needs nothing the record does not already carry.
- It emits a structured verdict per reviewer (property 5), keyed on `brief_id` and the corpus pin, so a sweep can join a quality column onto the cost/latency/gate columns it already reports.
- Nothing about tier bucketing, model-combination selection, or sweep reporting belongs in this spec. #362 owns its own scope.

**Where it lives (issue #385, settled).** `src/axial/panel/`, invoked by `axial panel run --records <dir> --control-record <path>`. One module per property that has to hold: `packet` (assembly, the content half of the seal, never writing to disk), `vendor` (the different-training-lab bar, where an undeclared model id is a hard error rather than an assumed-distinct default), `review` (N ≥ 3 dispatch, structured verdicts, the spread), `control` (the three plants and the trust condition), and `run` (control first, and its verdict is what `trusted` means).

Two implementation facts the properties imply but do not state, recorded so they are not re-litigated:

- **The tool half of the seal is structural.** Reviewers dispatch through the plain completion seam (`complete_json`), which has no `tools` parameter to pass — so a reviewer cannot be handed a tool registry even by mistake. A reviewer must never be routed through `complete_with_tools`.
- **Verdicts are not written into the repo by default.** Property 7 permits committing a verdict, but a reviewer's free-text defect `note` is model prose that can quote the source text it just read. `axial panel run` therefore writes nothing unless `--out` names a path, and that path belongs under gitignored `data/`, never `evals/`. Scores, defect kinds, claim ids, reviewer models and vendors are all safe; the note is the hazard.

---

## 10. Success metrics & eval gates (rung 3)

These are the **rung-3 ship-blocking eval gates** for the layers Phase B builds (charter §2). **Trust composes multiplicatively across layers**: the system is only as trustworthy as its weakest rung, and a flawless synthesis over a mis-attributed substrate is worthless (charter Principle V). Phase A's substrate layer is rung 1 beneath these; its own quality measure is deliberately undecided (PRODUCT.md §10, DEC-55), which is a stated limit on every number here, not a gap this phase fills. The principles behind each gate are **FIRM**; the numeric thresholds are **TUNABLE** starting hypotheses (charter §2). Each gate names a metric and a starting threshold to be tuned on the first real runs.

### 10.0 There is no single accuracy number (D8) **[FIRM]**

The phase does not compute one and must not invent one. **Accuracy decomposes into four measures, two mechanical and two judged**, each reported on its own in the run report (§7.15) and never summed, averaged or headlined as one figure. That is charter Principle V's compositional-trust rule applied to accuracy itself: a single number lets a strong rung average away a weak one.

| measure | how | where the oracle lives |
|---|---|---|
| **attribution completeness** | mechanical | the record itself: every claim's `kind` and every (a)/(b) claim's resolvable grounds (P0-5) |
| **retrieval hit** | mechanical | `required_citation_source_ids` on the sim cases (§9.3): did this run's grounds reach the sources the case names |
| **grounding-support rate** | judged | an independent model anchored to the cited note's text, on (a) claims |
| **instant-dismissal violations** | judged | `instant_dismissal_criteria` on the sim cases (§9.3): did the answer do a thing the case declares disqualifying |

**Both judged measures run under their own pass name and never by the generating model**, the same self-grading guard the five gates below already carry. A judge that graded its own output is an error raised before any judge call is made.

**Instant-dismissal was the gap this names, and issue #491 closed it.** The criteria are authored, non-empty on all 21 cases, and nothing in the product read them until that slice. They are the sharpest oracle the case set holds, since a case says plainly what would get the paper rejected on sight. The judge is `axial.answer.dismissal` (§9.3); **it is not a sixth gate**, because no violation rate has ever been observed and a threshold asserted before measurement would be a guess. It is measured, reported, and promoted under the same discipline §7.13 states for source usage.

**Retrieval recall becomes measurable here for the first time.** The share of a case's `required_citation_source_ids` a run's grounds actually reach is the first real recall number this product has had, and it is also the signal §3 non-goal 4 names as the condition for reopening the chunk index.

### 10.1 The five gates **[FIRM principles, TUNABLE thresholds]**

| Gate | Charter | Metric | Starting threshold [TENTATIVE] |
|------|---------|--------|--------------------------------|
| **Attribution fidelity** | Principle II | attribution-completeness = share of claims with a valid kind + resolvable (a)/(b) grounds; plus (b)-seam mislabel rate | completeness = **1.00** (mechanical hard gate); (b) mislabel rate **≤ 0.05** on judged sample |
| **Grounding** | Principle I | grounding-support rate = share of (a) claims whose cited grounds substantively support the claim, judged by an independent model anchored to the note text | **≥ 0.90** |
| **Synthesis quality (counter-position present)** | Principle IV | counter-position-presence rate on the contested-brief subset (present-or-disclosed), plus judged steelman-quality | presence **≥ 0.95**; steelman-quality **≥ 0.90** (the counter-position validator's own steelman verdict; no academic rubric is coming, §9) |
| **Calibration** | Principle V | **band-wise reliability**: for each of `high` / `medium` / `low`, the observed judged-correctness rate of the claims in that band, against the band's stated target (§7.4) | every band within **0.15** of its target rate, and the observed rates strictly ordered high > medium > low |
| **Adversarial brief red-teaming** | Principle III | premise-catch rate on a seeded set of briefs carrying smuggled premises / thin-coverage asks | **≥ 0.80** |

- The attribution-fidelity mechanical portion is a **hard 100% gate**, not a sampled rate: it is mechanically checkable, so any unmarked or unresolvable-grounds claim fails outright (P0-5).
- **The judge is independent, and independence is enforced in code.** For these five gates, each judged check runs under its own `pass_name` and must resolve to a different model than the pass it grades; the guard raises before any judge call is made. Eval #1's answer quality is not scored here at all: it is measured offline on a sample by the §9.4 panel, which is sealed from the repo, drawn from a **different vendor** than the generating model, and trusted only after its positive control catches planted defects. No gate in this table waits on it. The generating model never grades its own output.
- **These five gates need no human referee** (§9.1). Each is anchored to material the repo or vault already holds: seeded briefs that state their own answer key, and resolved note text. They report in the trusted tier (§9.2) once a pin resolves over the full rebuilt corpus.
- **No self-grading on softballs**: gates are scored on hard cases the system cannot already ace (the anti-Üngör principle, eval charter constraint 4). The five hard briefs of §9.0 are that set.
- **A Gather finding is never an oracle either (D4).** No gate scores an answer against a disagreement section, and no gate credits a run for repeating one. The 575 findings have never been scored (`axial gather-eval` exists and has never run, DEC-55), so nothing here may depend on their accuracy. The one thing a gate may read is §7.15's `disagreement_reuse`, which records whether the run *reached a note* a finding also cites: a retrieval fact, not a quality verdict.
- **Calibration is measured band-wise, not as error over a continuous score.** The question is whether `high`-band claims actually hold up at the rate `high` implies, and likewise for `medium` and `low`. Expected calibration error and Brier score both presuppose a numeric confidence the three-band vocabulary deliberately does not produce (§7.4), so they are inapplicable here rather than merely unchosen. The gate needs enough judged claims per band to mean anything: a band below the minimum sample size is excluded from the deviation and strict-ordering computation (its `n`/`observed` are still reported, flagged `scoreable: false`), and if every band falls short the metric reports **not-scoreable** rather than a verdict built on nothing (issue #402). The minimum is a stated tunable, `calibration.min_band_n` (config/pipeline.yaml, code fallback **5** — the standard rule-of-thumb minimum cell count from categorical statistics, the same "expected count ≥ 5" bar a chi-square test applies), set from the first judged run's own evidence (a single high-band claim was generating a verdict with two of three bands empty) rather than tuned to that run's pass/fail counts.
- **A gate metric computed on a sample too small to mean anything reports a third, distinct `not-scoreable` state — never a silent pass or a silent fail (issues #401/#402).** `MetricResult.passed` (and `GateReport.passed`, the conjunction one level up) is tri-state: `true`/`false` is a real verdict, `null` means the metric never had enough to evaluate. A metric that vacuously "passes" on zero observations reads as a green light for a check that never ran; a metric that "fails" an input it never had anything to evaluate sends a reader debugging the wrong thing — both are worse than saying plainly that nothing was measured. Every caller that folds a gate's `passed` into a further aggregate (a sweep's per-brief console summary, a corpus-wide tally) must keep the three states distinguishable; collapsing `not-scoreable` back into a boolean anywhere downstream defeats the point. This is a general harness property (`axial.gates.harness.not_scoreable_metric`/`compare`), not a one-off fix to either gate below. **`not-scoreable` blocks release** (exit non-zero, `overall: NOT-SCOREABLE`): a claim of "passed" requires having actually measured something, and a gate that never fully ran cannot claim that, even though it also did not fail anything it checked. The CLI's binary exit code cannot itself carry three states, so it treats `not-scoreable` the same as `false` for that one purpose (non-zero) while `axial.gates.harness.format_report` still renders the report text distinctly (`NOT-SCOREABLE`, never `FAIL`) so a reader is never told the check failed when it simply never ran.
- **Not-applicable is a fourth condition, but not a fourth `passed` value (issue #405, a #401 follow-up).** A metric can have legitimately nothing to measure for a reason a SIBLING metric already accounts for — `steelman_quality` has nothing to judge when every contested record was cleanly **disclosed** as one-sided (§7.8: disclosure is an equal-standing clean outcome, not a degraded one) and `counter_position_presence_rate` already scored that as a pass. That is not the same emptiness #401 complained about, where the absence was unaccounted for (neither present nor disclosed) and genuinely unmeasured. Not-applicable is a real pass (`passed: true`, never blocks release) carrying a distinct `detail.not_applicable: true` marker and a reason naming the disclosure, not a success — `axial.gates.harness.not_applicable_metric`/`metric_verdict_text` render it as `PASS (not applicable)`, never folded silently into an ordinary pass and never regressed into #401's original vacuous `passed: true` on a check that simply never ran for no accounted reason. The rule composes with the state above: when the sibling metric itself failed or was not-scoreable, the empty metric stays **not-scoreable**, not not-applicable — the absence is unaccounted for either way.
- **Report shape (issue #263, revised #401/#402/#405).** `synthesis-quality` reports two metrics, `counter_position_presence_rate` and `steelman_quality`, both reusing the counter-position validator (§7.9) wholesale rather than re-deriving contested detection or the presence-or-disclosure check; `steelman_quality`'s judge IS that validator's own steelman/strawman check. That check is now the **permanent** operational bar, not a stand-in: no academic rubric is coming (§9), and the check is corpus-anchored to the counter-position's own grounds, so it needs none. `counter_position_presence_rate` reports **not-scoreable** (not a vacuous pass, not a manufactured fail) when the CONTESTED subset itself is empty — its reason names that condition explicitly, since the records scored may well carry claims (the empty thing is the contested subset, not the claim set). `steelman_quality` reports, when no counter-position was present-with-grounds to judge, **not-applicable** if `counter_position_presence_rate` itself passed (every contested record was disclosed, so the absence is accounted for and the gate is clean) or **not-scoreable** if presence failed or was itself not-scoreable (the absence is unaccounted for, mirroring #401's own slice-1 evidence: `present: false`, `corpus_one_sided: false` — neither present nor disclosed). `calibration` reports one metric, `band_reliability` (value = the largest per-band deviation from that band's target among bands meeting `min_band_n`, `passed` also requires the strict high>medium>low ordering over those same bands); its per-band breakdown (`observed`, `target`, `n`, `scoreable`) and the confidence-vocabulary/target-tunability note live under the metric's own `detail`. Per-band target rates are a config seam (`calibration.band_targets`, code fallback high 0.85 / medium 0.725 / low 0.60 — the 0.60-0.85 range's midpoint), distinct from the harness's own `gates.band_reliability` tolerance (0.15) and from `calibration.min_band_n` above. The tolerance comparison itself is float-representation-safe (`axial.gates.harness.compare`): a value that lands exactly on its threshold is never lost to a single float ULP.
- **Source usage (§7.13), the cross-source rate (§7.15) and the instant-dismissal violation rate (§10.0) are deliberately not gates.** Their absence from this table is a decision, not an oversight. Each is disclosed and recorded from the first run, and each is promoted only under §7.13's stated condition: inspect the distribution, find a threshold that separates what the founder judges good from what he judges bad, then set it. Asserting a threshold before that inspection would flag legitimately concentrated, legitimately single-source or legitimately blunt analyses.
- Eval **#3 (agentic trajectory)** scores the retrieval trajectory (§7.6) with mostly programmatic oracles (retrieval-hit against required-citation sets, step efficiency, tool-call validity). Eval **#2 (hybrid-tagging distillation)** was a cost track over a tagging pass that no longer exists and is **out of scope** (mentioned only to bound it out).
- **The adversarial brief red-teaming gate's oracle (issue #264).** No oracle for "did the pre-pass interrogate the brief" exists anywhere else, so this gate ships one: a versioned **seeded set** under `config/briefs/adversarial/`, each file the §7.1 brief shape (`case`, `request`, optional `lens`) plus a `seeded: {kind, premise, expected_disposition}` block -- `kind` one of `smuggled_premise` / `thin_coverage_ask`, `premise` the plainly-stated answer key, `expected_disposition` one of `proceed_bounded` / `refuse`. The `seeded` block is read only by the gate and is **stripped before the remaining fields ever reach the brief loader or the interrogation prompt** -- a brief that leaks its own answer key measures nothing. A seeded brief that comes back a clean `proceed` is a miss by definition, regardless of what the pre-pass's `premises_found` contains. A found premise **catches** the seed when an independent judge -- `axial.llm.PREMISE_MATCH_PASS_NAME`, a distinct pass from `INTERROGATE_PASS_NAME`, under the same same-model self-grading guard the grounding gate (§10 above) established -- finds it corresponds to the declared premise; matching is judged correspondence of meaning, never string equality. Run via `axial gate run adversarial --dry-run --briefs <dir>` (the gate's own input is a directory of seeded briefs, not analysis records, so it takes `--briefs` where `attribution-fidelity`/`grounding` take `--records`).

---

## 11. Build phases

The build proceeds bottom-up, so each layer stands on a tested one beneath it. **The contract moves before the code, and the pin before every run that has to be reproducible.**

1. **The contract and the pin.** This spec at v2 (slice 00). Then restore the disagreement sections Materialize cleared — Gather's records are on disk, so the restoring run makes no model call — and re-cut the corpus pin per §7.12 (slice 01). LLM-free.
2. **Vault query API (P0-2).** The deterministic, LLM-free foundation slice: `find_names`, `get_name`, `name_neighbors`, `who_cites`, `who_argues_against`, per-name `coverage_count`, and the four surviving tools. Fully testable without an LLM.
3. **The retrieval loop rewired (P0-3)** onto step 2's tools: tool registry and dispatcher, trajectory log unchanged, step budget re-proven.
4. **Evidence assembly & analysis (P0-4)** rebuilt around `claim` / `position_of` / `position` / `arguing_against` / `citations`, with Gather findings as hints per D4; the inspect-before-spend `examine` affordance (P0-9).
5. **Coverage, counter-position and the metrics** — the per-name map, confidence derivation, contested detection (P0-6, P0-7), then source usage re-based and the run report (P0-13, P0-14).
6. **The smoke harness (P0-11).** `config/briefs/smoke/` and six briefs behind mechanical gates plus a cost and latency budget. Built early on purpose: it is the feedback loop everything above and below is checked against.
7. **The gates and the eval run (P0-12).** Gate fixtures re-pointed at the new record, `config/briefs/eval/` landed with the new brief and its case, and the instrumented run executed and reported. These are trusted-tier numbers (§9.2).
8. **The reviewer panel and its positive control.** Stand up the §9.4 sealed-packet panel, run the mandatory positive control against planted defects, and only then report any answer-quality number, in the refereed tier with its ceiling and sampling frame disclosed. This is an offline measurement step, not a pipeline stage: steps 1 to 7 ship a complete engine without it, and it runs occasionally against a sample thereafter. No academic step precedes or replaces it.

---

## 12. Dependencies, preconditions & tech stack

**Preconditions for trusted-tier numbers (§9.2), not for the build:**
- **The full ~30-source vault, with its name layer complete.** The Phase-A operational rollout, including every disagreement section Gather produced. The engine builds and dry-runs against whatever vault exists; a trusted-tier number needs the full corpus.
- **The pinned corpus manifest** (P0-10), implemented here since nothing else owns the format. Source filenames are part of the pin's identity, and so is the name-layer index (§7.12).

That is the whole list. Academic-authored hard cases are **not** a precondition and are no longer expected (#250 and #295, closed not planned, 2026-07-24; §9.1). The five gates are corpus-anchored and need no human referee.

**Preconditions for a refereed-tier number (§9.2):** the §9.4 reviewer panel, standing up with N ≥ 3 reviewers from a vendor other than the generating model's, plus a passing positive control against planted defects, plus a stated sampling frame. No answer-quality number is reportable before that control runs. **None of this is a precondition for shipping the engine or for a trusted-tier number**: the panel is an offline measurement instrument, so nothing in the build or in a brief run depends on it existing.

**Stack.** Python, driven through the `axial` CLI. **Inference:** API-based via the existing provider clients (OpenRouter, NVIDIA), through the existing `model_by_pass` / `reasoning_by_pass` config seams (PRODUCT.md §7.9, §12): analysis/synthesis wants the high tier with reasoning ON; interrogation and the validator model checks may run cheaper; tier assignments are **[TENTATIVE]** and proven on the smoke set. **Retrieval:** the deterministic query API over the vault and the name layer. **No new embedding dependency:** `find_names` reuses the `sentence-transformers` + `lancedb` path Phase A already installed and the vectors it already wrote (D10); **no chunk embedding index is built** (§3 non-goal 4). **Substrate consumed read-only:** the Phase-A vault (`data/vault/prose/`, `data/vault/artifacts/`, `data/vault/names/`, markdown + YAML frontmatter), the name-layer artifacts (`data/names/`: `index.json`, `alias_map.json`, `embeddings.lance`, `disagreements.jsonl`), the per-source envelopes (`data/envelopes/`), and the domain frame (`config/domains/syria/`). Phase B adds no new inference dependency beyond what Phase A already carries, though the existing provider clients gain **native tool-calling** (`tools` / `tool_calls`) to drive the stage-3 agentic loop, rather than a hand-rolled JSON tool protocol over the text-completion seam.

**Out of scope, stated so it is not smuggled in.** Any change to Phase A: the vault is read-only here, and a gap found in the index routes to a Phase A issue under the DEC-55 rule. Scoring the 575 Gather findings: `axial gather-eval` is Phase A's instrument and Phase A is closed — D4 is what makes this phase independent of whether that score ever runs. The reviewer panel: `src/axial/panel/` stands as specified in §9.4, an offline instrument on a sample, and nothing here triggers or waits on one. The frontier-versus-hybrid model comparison: unsettled since PR #361, and it re-files against the five hard briefs once they produce numbers, not before.

**Owned elsewhere:** the Phase-A quality question is a Phase-A concern (PRODUCT.md §10) and does not gate anything here.

---

## Open Questions

Genuinely unresolved; everything else in this document is settled.

- **[eval]** Judge-model protocol, **largely answered** by the §9.4 reviewer panel: a sealed packet enforced by tooling, a different vendor, N ≥ 3 independent reviewers reported with their spread, a structured verdict, and a mandatory positive control before any number is trusted. The adjudication format is settled too: the keyed `answer_kind` shape of §9.3 is the permanent sim-case contract. Two sub-questions remain genuinely open: how many reviewers past three buy anything measurable, and how panel verdicts aggregate across a sample into a headline figure without hiding the spread. **Panel cost is not among them**: the panel is sampled and offline (§9.4), so its cost is bounded by construction and adds nothing to any per-run budget. *The judge-vs-academic agreement-sampling protocol is **closed, not deferred**: there is no academic (#250, #295, closed not planned), and the positive control replaces it as the panel's own check.*
- **[engineering]** Trajectory-log storage format beyond the in-record log — whether eval #3 needs a richer standalone store for cross-run replay (§7.6, P1-1).
- **[engineering]** The chunk-index reopening condition, now half-answered. **How recall is measured is settled**: the share of a case's `required_citation_source_ids` a run's grounds reach (§10.0), the first real recall number this product has had. What remains open is the *level* at which a miss is a retrieval failure rather than an answer that legitimately went elsewhere. *A chunk embedding index is built only on demonstrated recall failure, never speculatively (§3 non-goal 4, D10).*
- **[corpus]** How much the name layer's known dirt costs a real brief. Bibliography-shaped names sit in the index (#482), fragmentation leaves `Charles Tilly` and `C. Tilly 1975` apart (#460), and diacritics are deliberately unfolded so `Üngör` and `Ungor` do not meet (`specs/PRODUCT.md` §7.16). All three were closed against a 5% bar with no failure to aim them. **A brief that visibly misses evidence because of one is exactly the trigger their bodies name**, and this phase is the first thing able to produce that evidence. This is a Phase A question that only Phase B can answer, and it routes back as a Phase A issue.
