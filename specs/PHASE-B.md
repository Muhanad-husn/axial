# PRD — Axial: Phase B Analysis Engine (Syria v0)

**Project:** Axial · **Version:** 1.1 · **Status:** Ratified · **Owner:** Operator (single-operator system)

**Inherits.** This PRD is the Phase-B phase spec under [`specs/CHARTER.md`](CHARTER.md), the product-wide behavioural constitution; its P0 criteria are the analysis-layer instance of the charter's five principles. Its substrate is Phase A, specified in [`specs/PRODUCT.md`](PRODUCT.md); Phase A is consumed here, never modified here. This spec does not restate or override the charter (charter §4).

**On the name.** Phase B is the **Analysis Engine**. Phase A built the faceted corpus; Phase B is the first reasoning layer that stands on it. Given a *case* and a *request for analysis* (together, a **brief**), it produces a grounded analytical answer: it interrogates the brief, retrieves from the corpus anchored on the case, applies a theoretical lens and axial coding across sources, and emits claims each marked for what kind of claim it is, with a per-polity coverage map and disclosed, calibrated confidence. The output is an **analysis, not a research paper**. Paper authorship is Phase C; format adaptation is Phase D.

**Self-sufficiency note.** This document is the complete build specification for Phase B v0. Everything required to scaffold and build the analysis engine — the architecture, the stages, the output contract, the query API, the acceptance criteria, and the eval gates — is contained here. Its single parent is the behavioural constitution in [`specs/CHARTER.md`](CHARTER.md), which governs *why* the engine is built as it is; beyond that one charter and the Phase-A substrate contracts it consumes, it references no external file. Where a decision is genuinely unresolved it is listed under **Open Questions**; everything else is settled and should be built as written. Status flags mark tentative content: **[FIRM]** build as-is · **[TENTATIVE]** likely to shift after the first real briefs · **[CONTESTED]** to be resolved before ship.

---

## 0. What this is, in one paragraph

Phase B is a single-operator analysis engine driven through the `axial` CLI. It takes a brief — a case plus a request for analysis — and returns a grounded analytical answer over the tagged corpus Phase A produced (~30 processable sources, ~17k prose chunks, a separate artifact pool with bidirectional links, one envelope per source). The middle of the engine is a **model-driven query agent** that plans and re-plans retrieval over a small, deterministic, model-free query API. Around that agent sit **deterministic hard gates**: a brief-interrogation pre-pass that may bound or refuse the request, and post-pass validators that check attribution, counter-position, and coverage before an answer is released. The load-bearing artifact is a structured **analysis record** in which every claim is marked source-says, tool-infers-across-sources, or speculation, carries auditable pointers into the vault, and carries disclosed confidence. Correctness has no answer key at the frontier of a synthesis; the enforced standard is **accountability to grounds, with honest confidence** (charter §0).

---

## 1. Problem statement & context

Phase A solved substrate fidelity: clean text, structural trees, bounded chunks, multi-axis tags scored against a gold set. It deliberately built no reasoning. A tagged vault is not an answer. The value the operator wants is the charter's framing: give the system a case and a request, and get back original comparative-historical analysis that no single source made (charter §0).

Two failure modes govern this phase, and both are invisible in fluent prose. First, **ungrounded assertion**: an LLM asked for scholarship writes a confident claim from parametric memory and dresses it as a finding, laundering unvetted content into vetted-looking output (charter Principle I). Second, **generate-then-cite**: the model writes the synthesis first and hunts for citations after, so the citation decorates rather than founds the claim (charter Principle II). Both produce output that looks like success and is worthless. The cost of not solving them compounds: an analysis trusted because it reads well, resting on a claim the corpus never made, is worse than no analysis.

The engine's whole design follows from making those seams visible and checkable. This PRD covers **Phase B (analysis) only**. It does not cover paper authorship (Phase C), format adaptation (Phase D), or any change to the corpus or schema (Phase A owns ingestion).

---

## 2. Goals

1. **Grounded analytical answers, by construction.** Produce an analysis assembled from grounded moves, never generated then back-fitted with citations. Every claim is marked as one of the three kinds and carries auditable grounds (charter Principle II).
2. **The brief is interrogated, not obeyed.** A deterministic pre-pass surfaces smuggled premises, tests them against corpus coverage, and may bound or refuse the request. Bounding and refusal are first-class outputs, not errors (charter Principle III).
3. **Tags-first retrieval, measured for recall.** Retrieval is structured query over the substrate Phase A built for exactly this: the tag axes, the many-valued `polities_touched` facet, `role_in_argument`, artifact roles, backlinks, and the per-source envelope. No embedding index ships in v0; recall is *measured* on real briefs (§3, Open Questions).
4. **Case-as-anchor, not case-as-fence.** A case anchors retrieval without fencing analysis to it. Corpus-grounded material about other polities that bears on the case is in scope, always labeled as the tool's cross-source inference (charter §3, Principle II).
5. **Disclosed, calibrated confidence and per-polity coverage.** Every answer discloses how well the corpus covers each polity it touches, computed from `polities_touched`, and feeds that into a calibrated confidence disclosure (charter Principle V, §3).
6. **Buildable and dry-runnable without the Academic in the loop.** The engine builds and dry-runs against versioned **dev briefs**; the Academic's hard cases are the rung-3 answer-quality referee and swap in as data, never a code change (mirrors PRODUCT.md §11).

---

## 3. Non-goals

Each is excluded deliberately; documenting them protects the architecture.

1. **No paper authorship.** The output is an analysis record plus a rendered answer, not a research paper with narrative arc and apparatus. Authorship is **Phase C**.
2. **No format adaptation.** Rendering to a specific venue, length, or house style is **Phase D**. v0 renders one plain markdown answer.
3. **No UI beyond the CLI.** The phase is driven through `axial` like every other phase. No web app, no notebook, no server.
4. **No embedding / vector index in v0.** Retrieval is structured tag-and-facet query. An embedding index is a **named possible future addition, gated on demonstrated recall failure**: if measured recall on real briefs shows the tag surface misses material a good answer needs, the index is reopened as a scoped follow-up (Open Questions). It is not built speculatively.
5. **No corpus or schema modification.** Phase A owns ingestion, tagging, and the domain schema. Phase B reads the vault read-only. A schema gap found here routes through the existing gold/eval loop (PRODUCT.md §10–§11), never a Phase-B code patch.
6. **No multi-brief orchestration or batching** beyond what the CLI needs to run one brief and inspect it. Corpus-wide brief sweeps, scheduling, and caching across briefs are out of scope for v0.

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
2. **Vault query API (deterministic, model-free; the foundation slice).** A small fixed tool set over the tagged vault (§7.5): query by tag axis, by the `polities_touched` facet, by source/envelope; fetch a chunk or artifact by id; traverse backlinks; count coverage per polity. It calls **no model and no embedding model**, so it is fully testable without any LLM. Every tool returns auditable vault ids.
3. **Retrieval planning & the agentic query loop (model-driven over deterministic tools).** From the interrogation result and the case anchor, a model plans retrieval, calls stage-2 tools, inspects results, and **re-queries when results are thin**. Case-as-anchor, not case-as-fence: the agent may pull cross-polity material bearing on the case (charter §3). Every tool call and every returned chunk id is appended to the **retrieval trajectory log** (§7.6). The loop runs under a bounded step budget.
4. **Evidence assembly & analysis (model, high tier + reasoning; Principles I, II).** The retrieved evidence set is assembled and made inspectable *before* the expensive call (inspect-before-spend, §7 CLI). The synthesis pass applies the lens and performs axial coding across the evidence, emitting the **claim graph** (§7.4): each claim marked (a)/(b)/(c) with grounds pointers into the vault. Grounded by construction, not generate-then-cite.
5. **Validators (deterministic, with bounded model checks where unavoidable; Principles II, IV, V).** Post-passes outside the model's control (§7.9): the **attribution validator** confirms every claim has a kind and every (a)/(b) claim has resolvable grounds; the **counter-position validator** confirms a counter-position section is present or an explicit one-sided disclosure is made on a contested brief; the **coverage/confidence validator** confirms a per-polity coverage map (from `polities_touched`) and a confidence disclosure are present. A failed mechanical check blocks release.
6. **Rendering & persistence (deterministic).** Writes the structured **analysis record** (§7.3, one JSON per brief run) and a rendered **markdown answer** (§7.10). The record carries the interrogation result, claim graph, counter-position section, coverage map, confidence disclosure, **source-usage disclosure** (§7.13), trajectory log, and the corpus-pin the run was produced against. The source-usage disclosure is computed here by counting, with no model call, and in v0 it is recorded and rendered but gates nothing.

---

## 6. Repository structure

Scaffold to this shape; adjust only with reason. Extends the Phase-A layout (PRODUCT.md §6); Phase-A modules are unchanged.

```
src/axial/
  brief/        # brief intake + interrogation pre-pass (stage 1)
  query/        # deterministic, model-free vault query API (stage 2)
  retrieve/     # retrieval planning + agentic query loop (stage 3)
  analyze/      # evidence assembly + lens/axial-coding synthesis -> claim graph (stage 4)
  validate/     # attribution / counter-position / coverage validators (stage 5)
  answer/       # analysis-record + source-usage counting + markdown rendering + persistence (stage 6)
  eval/         # (existing) + the rung-3 gate harnesses (§10)
config/
  briefs/
    dev/        # the landed dev-brief backlog (the 26 parked questions), versioned
  lenses/       # lens vocabulary as data (swappable, no country logic in src/)
data/
  analyses/     # one analysis-record JSON per brief run (<brief_id>.json)
evals/
  corpus_pin/   # pinned-corpus manifests (committed; ids + hashes only, DEC-23)
  cases/        # academic-authored hard cases (swap-in referee data; ids only)
tests/
```

---

## 7. Data & configuration contracts

### 7.1 The brief (input contract) **[FIRM]**

A brief is the phase's input, supplied as a versioned file. Its shape:
`{brief_id, case, request, lens?}`.
- `case` — the anchor: a free-text polity or set of polities under the same faithful-naming rule as `polity`/`polities_touched` (PRODUCT.md Appendix C). It anchors retrieval; it does not fence it (Principle §3).
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

### 7.3 The analysis record (output contract) — the load-bearing artifact **[FIRM]**

One JSON per brief run at `data/analyses/<brief_id>.json`, the phase's analogue of the Phase-A envelope (PRODUCT.md §7.3). Shape is **locked**; no field is nullable except where stated:

```
{
  brief_id, brief,                     # the brief (§7.1), verbatim
  corpus_pin,                          # the pin id this run was produced against (§7.12)
  schema_version,                      # the domain schema version the vault was tagged under
  lens,                                # the lens applied (named), always recorded
  interrogation,                       # the interrogation result (§7.2)
  claims: [ <claim> ],                 # the claim graph (§7.4); may be empty only on refusal
  counter_position,                    # the counter-position section (§7.8)
  coverage_map,                        # per-polity coverage (§7.7)
  confidence: { overall_band, rationale },   # disclosed, calibrated (Principle V)
  source_usage,                        # per-source contribution vs. available share (§7.13)
  trajectory: [ <tool_call> ],         # the retrieval trajectory log (§7.6)
  model_by_pass                        # which model + reasoning setting each pass used
}
```

`confidence.overall_band` is exactly one of `high` / `medium` / `low`, the same three-band vocabulary as the per-claim field (§7.4). `confidence.rationale` states the coverage counts that justify the band, drawn from `coverage_map`, so the band is never disclosed without the counts behind it. `source_usage` is non-nullable and follows §7.13; on disposition `refuse` it is present with an empty source list, like `claims`.

The record is the audit surface: every claim traces to grounds, every grounds pointer resolves to a real vault id, and the trajectory shows how retrieval got there. It is written once per run and is read by eval #1 (output) and eval #3 (process). On disposition `refuse`, `claims` is empty and the answer carries the refusal.

### 7.4 The claim (a/b/c kind, grounds, confidence) — Principle II **[FIRM]**

The unit of the analysis. Each claim:
`{claim_id, text, kind, grounds[], confidence, polities_touched[]}`.
- `kind` — exactly one of `a` (**source-says**), `b` (**tool-infers-across-sources**), `c` (**speculation**), per charter Principle II. The (b) seam is the product's whole value and its whole risk: it is the new knowledge, and it is the claim least able to be checked against an answer key. It is **always** marked as the tool's inference, never voiced as if a source said it.
- `grounds` — a list of `{ref_type, ref_id}` pointers, where `ref_type` is `chunk` or `artifact` and `ref_id` is a real vault id (`chunk_id` or `artifact_id`). **Required non-empty for every (a) and (b) claim.** A (c) claim may carry partial or empty grounds but must be marked speculation.
- `confidence` — exactly one of three discrete bands: `high`, `medium`, `low`. Never a numeric score.
- `polities_touched` — the union of the `polities_touched` facets of the claim's grounds chunks, so coverage (§7.7) is computable from the claim graph.

**The confidence vocabulary is three bands, and the reasoning binds everywhere confidence appears in this phase (§7.3, §7.7, §7.10).** A model emitting `0.73` is not computing a probability. It is producing a number that looks like confidence. That is manufactured precision, and dressing an unmeasured guess as a measurement is exactly what charter Principle V's honest-confidence requirement forbids. Bands are also far cheaper to calibrate: three buckets need far less scarce Academic judgment to check than a continuous scale does.

**A band is never rendered instead of the counts that justify it.** Every confidence disclosure, per-claim and overall, appears alongside the real coverage counts from §7.7: `medium` confidence, grounded in N evidence chunks drawn from a corpus holding M substantive chunks on that polity. The count is the honest signal; the band is the summary of it. A band shown alone is the manufactured-precision failure in another costume.

**Band targets [TENTATIVE].** Each band carries a stated expected-correctness rate, so the band means something checkable and the calibration gate (§10) has something to measure against: `high` ≥ 0.85, `medium` 0.60–0.85, `low` < 0.60. These are tunable starting hypotheses in the sense of charter §2, tuned on the first judged runs; that they are stated at all is FIRM.

`claim_id` is stable and deterministic within a run. **Unrequested, corpus-grounded analogues** the brief did not ask for are permitted, and are always emitted as (b) claims grounded in real corpus material, never as a training-memory analogy dressed as a finding (charter §3, Principle II).

### 7.5 The vault query API (deterministic, model-free) **[FIRM]**

The foundation slice: a small, fixed, deterministic tool set over the tagged vault (`data/vault/prose/`, `data/vault/artifacts/`; markdown + YAML frontmatter). It calls **no model and no embedding model**, so it is fully unit-testable without any LLM. Each tool returns auditable ids plus the metadata and text needed to reason. The v0 tool set:

- **query_by_tag** — chunks matching a conjunction of tag-axis filters over the frontmatter axes: `field`, `claim_type` (incl. subtags), `empirical_scope` (incl. `polity`), `role_in_argument`, `theory_school`.
- **query_by_polity** — chunks whose `polities_touched` includes a given polity (the many-valued facet, PRODUCT.md Appendix C). This is the cross-case retrieval the single-valued scope axis cannot serve.
- **query_by_source / get_envelope** — the per-source envelope (thesis, nested toc, scope, stated_argument) and the chunks of a given source.
- **get_chunk / get_artifact** — a chunk or artifact by id, with its frontmatter and text.
- **follow_backlinks** — from a chunk to its `artifact_refs`, from an artifact to its `cited_by` (the bidirectional links Phase A wrote).
- **coverage_count** — the count of substantive chunks per polity across the vault, from `polities_touched`, the raw material of the coverage map (§7.7).

Retrieval in v0 is exactly these structured queries. No ranking model, no vector similarity. Determinism is a testable property: the same query over the same pinned vault returns the same ids.

### 7.6 The retrieval trajectory log **[FIRM]**

Appended by stage 3, one entry per tool call, in call order:
`{step, tool, args, result_ids[], result_count}`.
It is the eval #3 (process axis) raw material and the audit trail for how retrieval reached its evidence. It records the full path including re-queries after thin results, so a right answer reached by a lucky guess over a broken path is distinguishable from one reached by sound retrieval (eval #3). Its storage format inside the record is fixed here; a richer standalone trajectory store is an Open Question.

### 7.7 The per-polity coverage map (Principle V, charter §3) **[FIRM]**

Computed deterministically from `polities_touched`, never asked of a model. For each polity the answer touches:
`polity -> {corpus_chunk_count, evidence_chunk_count, coverage_band}`.
- `corpus_chunk_count` — how many substantive chunks in the whole vault engage this polity (from `coverage_count`).
- `evidence_chunk_count` — how many chunks in *this run's* grounds engage it.
- `coverage_band` — a disclosed band (e.g. dense / moderate / thin) derived from the counts against a stated tunable threshold, proven via inspection in the spirit of the Phase-A chunk band (PRODUCT.md §7.7).

A claim about a thinly-covered polity is disclosed as thin and feeds the calibration layer (Principle V): it is not stated with the confidence of a claim over a densely-covered case. The map is where the counts behind every confidence band live (§7.4): `coverage_band` and the confidence bands travel with `corpus_chunk_count` and `evidence_chunk_count`, never in place of them.

### 7.8 The counter-position section (Principle IV) **[FIRM]**

`{present, stance, grounds[], corpus_one_sided, one_sided_reason}`.
On a **contested** brief the section either states the opposing school at its strongest from corpus grounds (`present: true`, non-empty `grounds`, `stance` marked as counter-position), or explicitly discloses that the corpus is one-sided here (`corpus_one_sided: true`, `one_sided_reason` naming why and attributing the one-sidedness to the corpus). Absence of both on a contested brief is a **red flag, not a clean result**, and fails the counter-position validator (§7.9). The `role:counter-position` tag Phase A writes per chunk (PRODUCT.md Appendix F) is what makes opposing material findable through the query API.

Whether a brief is "contested" is determined from corpus signal, not the brief's wording: a question whose retrieved evidence spans two or more distinct **substantive** `theory_school` values, or carries `role:counter-position` material, is contested. The `not-applicable` and `unlisted` sentinels (PRODUCT.md Appendix E) are excluded from this comparison — neither counts as a position, and neither counts as opposing another value, including another instance of itself. `not-applicable` asserts the chunk advances no theoretical position; a `not-applicable` chunk beside a `bellicist` chunk is not opposition, it is silence on one side. `unlisted` asserts a real school the vocabulary does not yet name; two `unlisted` chunks are not known to agree or oppose until their logged candidates (§7.1) are reviewed and named. The exact contested-detection rule is a stated tunable, proven on the dev briefs.

### 7.9 The validators (deterministic post-passes) **[FIRM]**

Three validators run after synthesis, outside the model's control. Each is **mechanical wherever the property is mechanically checkable**; a bounded, separate model call is used only where it is not, and never by the generating model.

- **Attribution validator (mechanical).** Every claim carries a `kind` in `{a,b,c}`; every (a)/(b) claim carries at least one `grounds` pointer that resolves to a real vault id; no (b) claim is phrased as a source assertion. A failure blocks release.
- **Grounding check (bounded model, sampled or full).** For (a) claims, does the cited chunk actually support the claim text? Judged by an independent model anchored to the cited chunk's text, never the generating model. Feeds the grounding gate (§10).
- **Counter-position validator (mechanical presence + bounded model quality).** On a contested brief, the §7.8 section is present-or-disclosed (mechanical), and its steelman is not a strawman (bounded model, anchored to the counter-position grounds).
- **Coverage/confidence validator (mechanical).** A `coverage_map` exists for every polity the claims touch, and a `confidence` disclosure is present. Missing either blocks release.

### 7.10 The rendered markdown answer **[FIRM]**

Alongside the JSON record, stage 6 renders a human-readable markdown answer. It presents the claims with their kind visible ((a)/(b)/(c) legible to the reader, since those carry different weight, Principle II), the counter-position section, the coverage map, the confidence disclosure, and the source-usage disclosure (§7.13). **Every confidence band it renders carries its counts next to it** (§7.4): the overall band next to the coverage counts named in its rationale, and each polity's coverage band next to that polity's corpus and evidence chunk counts. A band rendered bare is a rendering failure. On refusal it states the refusal and its reason. Rendering is deterministic: the same record renders the same markdown. This is plain rendering only; venue/length/style adaptation is Phase D (§3).

### 7.11 Per-pass model tiering & reasoning **[TENTATIVE]**

Model choice and reasoning are per-pass settings, carried in the existing `model_by_pass` / `reasoning_by_pass` config seams (PRODUCT.md §7.9), never hardcoded. Tentative starting assignments, tunable like Phase A's:
- **Analysis / synthesis (stage 4)** — **high tier, reasoning ON**. This is the judgment-heavy, once-per-brief call whose output every downstream validator checks.
- **Brief interrogation (stage 1)** and the **bounded validator model checks (stage 5)** — a cheaper tier may suffice; reasoning per pass as measured.
- **The agentic query loop (stage 3)** — tier chosen for tool-use reliability, measured on the dev briefs.

Which pass runs at which tier is proven by measurement on the dev briefs, not asserted here.

### 7.12 The corpus-pin manifest (owned here) **[FIRM]**

Scores only compare against a pinned corpus (eval charter, shared constraint 1). Because all of `data/` is gitignored (DEC-23), the pin is a **manifest + hashes, not a commit**. The format is owned by eval #1 ([`docs/eval/01-answer-quality.md`](../docs/eval/01-answer-quality.md)); **nothing else owns it, so implementing it is part of this phase.** Minimum fields, per eval #1:
- **source list** — the ~30 sources, each with a content hash of the ingested input.
- **ingest-code SHA** — the commit the Phase-A pipeline ran at.
- **vault snapshot hash** — a hash over the produced notes (chunk_ids + tags, never chunk_text, per DEC-23).

The manifest is committed under `evals/corpus_pin/` (safe: ids + hashes only). Every analysis record (§7.3) records the `corpus_pin` it was produced against; two runs are comparable only if their pins match. The pin is reused by eval #2 and #3 unchanged.

### 7.13 The source-usage disclosure (bias investigation) **[FIRM]**

**What it is.** Every analysis record discloses what proportion of its evidence came from each source, **and the denominator alongside it**: how much of the material that source had *available* under the tag filters this run actually queried. A source contributing 60% of the grounds while holding 22% of the chunks that matched those filters is a signal. The contribution figure alone is not, because on its own it cannot separate a thin corpus, where that source is genuinely the only coverage, from over-selection, where the run reached past alternatives that existed.

**Why it exists.** All five rung-3 gates of §10 can pass on an analysis that draws most of its evidence from one book. Attribution is complete, grounds resolve, a counter-position is present, coverage is disclosed, confidence is banded, and the result is a **well-attributed monoculture**: one author's worldview presented as synthesis. Nothing else in this phase detects it. The founder's bias-investigation intent is the framing here, and the vault makes it tractable: because tag coordinates sit on both the sources and the queries, a source weighing consistently heavier on certain tags is measurable rather than merely suspected. The disclosure is diagnostic in a specific sense: it narrows the cause to one of three, which are then separable by inspection.

- **The corpus.** That source really is the only substantive coverage under those filters. Its available share is high too, and the ratio is near 1.
- **The retrieval logic.** The query API's filtering or ordering favors it. The same skew reappears across briefs with unrelated requests.
- **The model.** The agent kept choosing it when alternatives were there. The trajectory log (§7.6) shows alternatives returned and passed over.

**Shape.** A field on the record (§7.3), non-nullable:

```
source_usage: {
  filters_observed: [ <tag_filter> ],   # union of the tag filters queried this run, from the trajectory (§7.6)
  sources: [ {
    source_id,
    evidence_chunk_count,               # chunks of this source appearing in claim grounds
    evidence_share,                     # of all grounds chunks in the run
    available_chunk_count,              # chunks of this source matching filters_observed
    available_share,                    # of all chunks matching filters_observed, corpus-wide
    usage_ratio                         # evidence_share / available_share; null when available_share is 0
  } ]
}
```

`sources` is empty on disposition `refuse`, and on any run whose claims carry no grounds. `usage_ratio` near 1 means the source was drawn on in proportion to what it had; well above 1 means it was drawn on harder than its availability explains.

**How it is computed. No model call.** Deterministically, from data the record already holds: claim grounds resolve to vault ids, every `chunk_id` embeds its `source_id`, and the trajectory log records the tag filters of every query, which the deterministic `query_by_tag` / `query_by_polity` tools (§7.5) re-run to count the denominator over the pinned vault. This is the same architectural family as the §7.7 coverage map: a count over facets already written, never a judgment asked of a model.

**Scope discipline: diagnostic, not gating, in v0.** There is no defensible concentration threshold yet. What counts as too concentrated depends on corpus composition and on how broad the question is, and a narrow question over a corpus with one specialist source *should* concentrate. So v0 discloses and records it; it gates nothing. This follows the discipline §7.7's coverage band and §7.8's contested-detection rule already follow: state the tunable, prove it by inspection, then set it.

**The promotion condition, stated concretely.** Source usage becomes a sixth rung-3 gate (§10) when, and only when, inspection across at least the full dev-brief backlog (P0-11, 26 briefs) over a single pinned corpus yields a `usage_ratio` distribution in which a candidate threshold separates runs the founder judges over-concentrated from runs judged legitimately concentrated, without flagging the latter. Until that inspection has happened, no threshold is asserted.

**Design for the aggregate.** One run's distribution is weak evidence. The signal appears across many runs: a source drawing several times its available share *whenever* queries touch a given tag. The per-run shape above is therefore designed to aggregate cleanly, keyed on `source_id` and joinable on `filters_observed`, so per-source usage ratios can be pooled across every record sharing a corpus pin. A cross-run inspection affordance over `data/analyses/` is in scope for this phase (P0-13).

---

## 8. Requirements

### Must-Have (P0)

**P0-1 Brief intake & interrogation pre-pass (charter Principle III).**
- [ ] Reads a versioned brief (§7.1) and emits a structured interrogation result (§7.2) carrying premises found, bounds proposed, and a refusal-or-null.
- [ ] A deterministic wrapper sets `disposition` to exactly one of `proceed` / `proceed_bounded` / `refuse` from the structured result; the model does not decide release on its own.
- [ ] Bounding and refusal are first-class completed runs: on `refuse`, the record is written, the answer states the refusal and its reason, and no synthesis call is made. Observable: a brief whose premise the corpus contradicts yields a `refuse` or `proceed_bounded` disposition with the premise named, never a confident synthesis over the smuggled premise.

**P0-2 Vault query API, deterministic and model-free (charter Principle I substrate; the foundation slice).**
- [ ] Exposes the §7.5 tool set over the tagged vault, calling **zero model and zero embedding-model calls**. Observable: the full tool set is exercised in tests with no LLM client present.
- [ ] Every tool returns auditable vault ids (`chunk_id` / `artifact_id`) plus the frontmatter and text needed to reason; `query_by_polity` reads the many-valued `polities_touched` facet, and `follow_backlinks` traverses `artifact_refs` / `cited_by`.
- [ ] Determinism: the same query over the same pinned vault returns the same ids in the same order.

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
- [ ] Contested-ness is determined from corpus signal — evidence spanning two or more distinct **substantive** `theory_school` values, or carrying `role:counter-position` material — a stated tunable proven on the dev briefs, not from the brief's wording. The `not-applicable` and `unlisted` sentinels are excluded from the values compared: neither is a position, so neither can oppose another value or itself (§7.8). Observable: a brief over a genuinely contested question with no counter-position and no one-sided disclosure is rejected as a red flag, not passed as clean; a brief whose evidence mixes only sentinel and single-school chunks is not flagged contested on that basis alone.

**P0-7 Coverage & confidence disclosure (charter Principle V, §3).**
- [ ] A **per-polity coverage map** is computed deterministically from `polities_touched` (§7.7) for every polity the claims touch, carrying corpus and evidence chunk counts and a disclosed coverage band. Observable: given a brief whose claims touch a thinly-covered polity, that polity is disclosed as thin.
- [ ] Every answer carries a disclosed `confidence` with a rationale; a claim over a thinly-covered polity is not disclosed with dense-case confidence. A missing coverage map or confidence disclosure blocks release (§7.9).
- [ ] Confidence is one of the three bands `high` / `medium` / `low`, per-claim and overall, never a numeric score (§7.4). Observable: no record carries a numeric confidence value, and every rendered band appears next to the coverage counts that justify it (§7.10).

**P0-8 Analysis record & rendered answer (output contract).**
- [ ] One analysis-record JSON per brief run at `data/analyses/<brief_id>.json`, carrying the full §7.3 shape (brief, corpus_pin, schema_version, lens, interrogation, claims, counter_position, coverage_map, confidence, source_usage, trajectory, model_by_pass). No field nullable except as stated in §7.3–§7.8 and §7.13.
- [ ] A deterministic markdown answer is rendered from the record (§7.10), with claim kinds legible to the reader. The same record renders the same markdown.
- [ ] Each record records the `corpus_pin` and `schema_version` it was produced against.

**P0-9 CLI surface with inspect-before-spend.**
- [ ] `axial brief run <brief_file>` runs the full engine (stages 1–6) and writes the analysis record and answer.
- [ ] `axial brief examine <brief_file>` runs the interrogation and retrieval and reports the assembled evidence set — retrieved chunk ids, the per-polity coverage map, and the interrogation result — **without the expensive synthesis call**, analogous to `axial chunk examine` (PRODUCT.md §7.7). Observable: `examine` makes zero stage-4 synthesis calls and its cost is bounded to interrogation + retrieval.

**P0-10 Corpus-pin manifest (owned here; eval #1 format).**
- [ ] Implements the corpus-pin manifest of §7.12 to eval #1's format (source list + content hashes, ingest-code SHA, vault snapshot hash over chunk_ids + tags, never chunk_text per DEC-23), committed under `evals/corpus_pin/`. Nothing else in the product owns this format, so it lands as part of this phase.
- [ ] Every analysis record references its pin; two records are comparable only if their pins match.

**P0-11 Dev-brief backlog landed as versioned data.**
- [ ] The 26 parked Academic research questions (PRODUCT.md §12; the files live with the founder, not yet in the repo) are landed under `config/briefs/dev/` as versioned dev briefs in the §7.1 shape. The engine builds and dry-runs against these. Observable: the dev briefs are readable from the repo and drive the harness dry-runs without any Academic dependency.

**P0-12 Rung-3 eval-gate harnesses built and dry-runnable (charter §2 rung 3).**
- [ ] The five rung-3 gate harnesses of §10 (attribution fidelity, grounding, synthesis quality, calibration, adversarial brief red-teaming) are implemented as **pass/fail gates**, each with a named metric and a tunable starting threshold, and are **dry-runnable now** against dev briefs and synthetic cases (their process-side oracles are programmatic; eval charter, sequencing).
- [ ] The gates read the analysis record (§7.3) and the trajectory log (§7.6); the answer-quality referee (eval #1) swaps in academic cases **as data, never a code change** (§9, §10).

**P0-13 Source-usage disclosure (bias investigation; diagnostic, not gating in v0).**
- [ ] Every analysis record carries the §7.13 `source_usage` field: per source, its evidence chunk count and share, **and the denominator** — the count and share of that source's chunks available under `filters_observed`, the tag filters the run actually queried — plus the `usage_ratio` between them. Observable: a record whose grounds come disproportionately from one source shows that source's share above its available share, and the two figures are always present together.
- [ ] It is computed **deterministically, with zero model calls**, from the claim grounds, the `source_id` embedded in each `chunk_id`, and the trajectory log's recorded filters, re-counted over the pinned vault through the §7.5 tools. Observable: the field is produced in tests with no LLM client present, and the same record over the same pinned vault yields the same figures.
- [ ] It is **disclosed and recorded, and gates nothing** in v0: no threshold on `usage_ratio` blocks release, and no rung-3 gate reads it (§10). The promotion condition to a sixth gate is stated in §7.13 and is not met by this phase.
- [ ] A cross-run inspection affordance `axial brief usage` reads the records under `data/analyses/` sharing a corpus pin and reports per-source usage ratios aggregated across runs and broken down by tag filter, so a source that draws several times its available share whenever queries touch a given tag is visible. Consistent with the inspect-before-spend `examine` precedent (P0-9), it makes **zero model calls**. Observable: over a set of recorded runs, the command names the heaviest-weighing sources and the filters under which they weigh heaviest.
- [ ] The rendered answer (§7.10) shows the disclosure alongside the coverage map.

### Nice-to-Have (P1)

- **P1-1** A standalone trajectory store richer than the in-record log, if eval #3 needs replay across runs.
- **P1-2** Calibration reporting via a three-bar band reliability diagram (observed correctness rate per band against its target, §7.4) in addition to the headline pass/fail of the band-wise gate.
- **P1-3** A per-brief run log capturing agent judgment calls (re-queries, dead-ends recovered), mirroring PRODUCT.md P1-3.

### Future Considerations (P2 — design for, don't build)

- **P2-1** An embedding / vector retrieval index, **reopened only on demonstrated recall failure** on real briefs (§3, Open Questions).
- **P2-2** Second-domain briefs proving the engine is domain-portable by schema and lens data, no code change (mirrors PRODUCT.md P2-1).
- **P2-3** Cross-brief caching / batching, once single-brief quality is proven.

---

## 9. Dev briefs & the academic-case seam

The build must not block on the Academic, exactly as Phase A did not (PRODUCT.md §11). Two brief sources sit on either side of that seam:

- **Dev briefs** — the 26 parked research questions, landed as versioned data (P0-11). They drive the build and every dry-run. Their process-side oracles are programmatic (trajectory hits, step/token counts, tool-call validity, attribution completeness), so the harnesses run against them today.
- **Academic hard cases** (eval #1) — the rung-3 **answer-quality referee**. They are authored by the Academic on the frozen rich corpus and **swap in as data, never a code change**. Each case is an expected answer plus required-citation ids, or a rubric (eval #1 adjudication contract), committed under `evals/cases/` (ids only, safe per DEC-23).

**Honest dependency statement.** The rung-3 gates cannot produce *trusted numbers* until three things exist together: the full ~30-source tagged vault (Phase-A operational rollout, in flight), the pinned corpus manifest (P0-10), and the academic-authored hard cases. **Building and dry-running the harnesses does not wait on any of them** — the mechanical validators and the process-side oracles are programmatic (eval charter, sequencing). The engine and its gates are built now; the trusted answer-quality number lands when the referee data lands.

**Simulated interim referee data (DEC-29).** During the academic pause, an isolated development path may stand in AI-simulated hard cases under `evals/cases/sim/` so the rung-3 harnesses have referee data to dry-run against. This pins a **provisional** hard-case shape (`case_id`, `question`, `answer_kind` ∈ {`expected_answer`, `rubric`}, `required_citation_source_ids`, `rubric`, `instant_dismissal_criteria`; ids only) — a working answer to the adjudication-format Open Question below, explicitly **non-binding** until real academic cases land. Simulated cases are marked, never mixed with `evals/cases/`, produce no trusted number, and are torn down and re-run on real input before promotion.

---

## 10. Success metrics & eval gates (rung 3)

These are the **rung-3 ship-blocking eval gates** for the layers Phase B builds (charter §2). **Trust composes multiplicatively across layers**: the system is only as trustworthy as its weakest rung, and a flawless synthesis over a mis-attributed substrate is worthless (charter Principle V). **Phase-A's κ / agreement eval (PRODUCT.md §10) is rung 1 beneath these**, and is only rung 1. The principles behind each gate are **FIRM**; the numeric thresholds are **TUNABLE** starting hypotheses, exactly as Phase A's κ cutoffs are (charter §2). Each gate names a metric and a starting threshold to be tuned on the first real runs.

| Gate | Charter | Metric | Starting threshold [TENTATIVE] |
|------|---------|--------|--------------------------------|
| **Attribution fidelity** | Principle II | attribution-completeness = share of claims with a valid kind + resolvable (a)/(b) grounds; plus (b)-seam mislabel rate | completeness = **1.00** (mechanical hard gate); (b) mislabel rate **≤ 0.05** on judged sample |
| **Grounding** | Principle I | grounding-support rate = share of (a) claims whose cited grounds substantively support the claim, judged by an independent model anchored to the chunk text | **≥ 0.90** |
| **Synthesis quality (counter-position present)** | Principle IV | counter-position-presence rate on the contested-brief subset (present-or-disclosed), plus judged steelman-quality | presence **≥ 0.95**; steelman-quality **≥** rubric bar (eval #1) |
| **Calibration** | Principle V | **band-wise reliability**: for each of `high` / `medium` / `low`, the observed judged-correctness rate of the claims in that band, against the band's stated target (§7.4) | every band within **0.15** of its target rate, and the observed rates strictly ordered high > medium > low |
| **Adversarial brief red-teaming** | Principle III | premise-catch rate on a seeded set of briefs carrying smuggled premises / thin-coverage asks | **≥ 0.80** |

- The attribution-fidelity mechanical portion is a **hard 100% gate**, not a sampled rate: it is mechanically checkable, so any unmarked or unresolvable-grounds claim fails outright (P0-5).
- The **judge is independent**: an LLM-as-judge anchored to the academic's expected answer, from a **different model family** than the generating model, spot-checked against academic agreement before trust (eval #1, eval charter constraint 2). The generating model never grades its own output.
- **No self-grading on softballs**: gates are scored on hard cases the system cannot already ace (the anti-Üngör principle, eval charter constraint 4).
- **Calibration is measured band-wise, not as error over a continuous score.** The question is whether `high`-band claims actually hold up at the rate `high` implies, and likewise for `medium` and `low`. Expected calibration error and Brier score both presuppose a numeric confidence the three-band vocabulary deliberately does not produce (§7.4), so they are inapplicable here rather than merely unchosen. The gate needs enough judged claims per band to mean anything; the minimum sample per band is a stated tunable set on the first judged runs.
- **Source usage (§7.13) is deliberately not a gate.** Its absence from this table is a decision, not an oversight. It is disclosed and recorded from day one, and it becomes a sixth rung-3 gate only when the §7.13 promotion condition is met: no defensible concentration threshold exists yet, and asserting one before inspection would flag legitimately concentrated analyses.
- Eval **#3 (agentic trajectory)** scores the retrieval trajectory (§7.6) with mostly programmatic oracles (retrieval-hit against required-citation sets, step efficiency, tool-call validity). Eval **#2 (hybrid-tagging distillation)** is a separate **cost track** and is **out of scope for this spec** (mentioned only to bound it out).

---

## 11. Build phases

The build proceeds bottom-up, so each layer stands on a tested one beneath it. The corpus-pin and dev briefs are landed early so every later dry-run is reproducible.

1. **Scaffolding, corpus pin, dev briefs.** Repo per §6; implement the corpus-pin manifest (P0-10); land the dev-brief backlog (P0-11). *No Academic dependency.*
2. **Vault query API (P0-2).** The deterministic, model-free foundation slice, fully testable without an LLM.
3. **Brief interrogation (P0-1)** and the **agentic query loop (P0-3)** over the stage-2 tools, with the trajectory log.
4. **Evidence assembly & analysis (P0-4)** emitting the claim graph; the inspect-before-spend `examine` affordance (P0-9).
5. **Validators (P0-5, P0-6, P0-7)** and **rendering & persistence (P0-8)**.
6. **Rung-3 gate harnesses (P0-12)**, built and dry-run against dev briefs and synthetic cases.
7. **⏸ ACADEMIC HARD CASES.** The Academic authors hard cases on the frozen rich corpus; they swap in as referee data (§9). Only then do the rung-3 gates produce trusted numbers.

---

## 12. Dependencies, preconditions & tech stack

**Preconditions (must exist for trusted rung-3 numbers, not for the build):**
- **The full ~30-source tagged vault** — the Phase-A operational rollout, in flight. The engine builds and dry-runs against whatever vault exists; trusted answer-quality scores need the full rich corpus (eval #1).
- **The pinned corpus manifest** (P0-10) — implemented here, since nothing else owns the format.
- **The academic-authored hard cases** (eval #1) — the answer-quality referee, swapped in as data.

**Stack.** Python, driven through the `axial` CLI. **Inference:** API-based via the existing provider clients (OpenRouter, NVIDIA), through the existing `model_by_pass` / `reasoning_by_pass` config seams (PRODUCT.md §7.9, §12): analysis/synthesis wants the high tier with reasoning ON; interrogation and the validator model checks may run cheaper; tier assignments are **[TENTATIVE]** and proven on the dev briefs. **Retrieval:** the deterministic query API over the tagged vault; **no embedding dependency in v0** (§3). **Substrate consumed read-only:** the Phase-A vault (`data/vault/prose/`, `data/vault/artifacts/`, markdown + YAML frontmatter), the per-source envelopes (`data/envelopes/`), and the domain schema (`config/domains/syria/`). Phase B adds no new inference dependency beyond what Phase A already carries, though the existing provider clients gain **native tool-calling** (`tools` / `tool_calls`) to drive the stage-3 agentic loop, rather than a hand-rolled JSON tool protocol over the text-completion seam.

**Parked / owned elsewhere:** eval #2 (hybrid-tagging distillation) is a separate cost track (eval charter); the Academic labeling pause is a Phase-A concern (PRODUCT.md §11).

---

## Open Questions

Genuinely unresolved; everything else in this document is settled.

- **[eval]** Judge-model protocol details — model family, the judge-vs-academic agreement-sampling protocol, and the exact adjudication format (expected-answer-plus-citations vs. rubric vs. a keyed mix). *Deferred to eval #1's open threads; not blocking the build. The simulated-academic path (§9, DEC-29) pins a **provisional** keyed-mix shape (`answer_kind` per case) to dry-run against; it is a working hypothesis, not the resolution.*
- **[engineering]** Trajectory-log storage format beyond the in-record log — whether eval #3 needs a richer standalone store for cross-run replay (§7.6, P1-1).
- **[engineering]** Recall measurement and the embedding-index reopening condition — how recall is measured on real briefs, and the concrete signal that reopens the deferred embedding index (§3 non-goal 4). *An embedding index is built only on demonstrated recall failure, never speculatively.*
