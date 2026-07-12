# PRD — Axial: Phase A Corpus Ingestion Pipeline (Syria v0)

**Project:** Axial · **Version:** 1.0 · **Status:** Ready to build · **Owner:** Operator (single-operator system)

**On the name.** *Axial* names the mechanism and the tradition in one word: the system tags every chunk along multiple **axes** (field, claim-type, empirical-scope, artifact-role, theory-school), and *axial coding* is the grounded-theory move — native to this corpus through Malešević — of relating categories to one another along dimensions. The Python package is `axial`.

**Self-sufficiency note.** This document is the *complete* build specification. It references no external file. Everything required to scaffold and build the pipeline — architecture, pipeline stages, config contracts, the full v0 tag set, and acceptance criteria — is contained here, including appendices. Claude Code should be able to start from this file alone. Where a decision is genuinely unresolved, it is listed under **Open Questions** (§12); everything else is settled and should be built as written.

---

## 0. What this is, in one paragraph

Axial is a single-operator pipeline that turns a corpus of born-digital academic sources (PDF and DOCX) into a tagged Obsidian knowledge graph, and validates the tagging against a small human-labeled **gold corpus** so tagging reliability becomes a measured number rather than an assumption. The corpus is ~11 GB / ~120 sources in comparative-historical political sociology, heavily weighted toward Syria and the surrounding literature (Mann, Kalyvas, Brubaker, Hinnebusch, Migdal, Skocpol, Tilly, Wedeen, Malešević). The pipeline is **domain-general in mechanism, Syria-specific in content**: no country-specific logic in code; all domain content lives in a swappable, versioned schema.

---

## 1. Problem statement & context

The value of every downstream research pass depends on one thing: the quality of what enters the knowledge graph at ingestion. A corpus of ~120 sources is small enough that infrastructure is not the constraint — ingestion judgment is. Chunk a book by arbitrary page breaks and retrieval returns fragments that cut arguments in half; tag chunks with a vocabulary nobody validated and every later query inherits silent, unmeasured error.

Two problems follow. First, **argument-blind chunking**: splitting prose without regard to where a passage sits in the source's argument produces chunks that retrieve badly. Second, **unvalidated tagging**: applying a controlled vocabulary that was never tested against real passages means we cannot distinguish a good tagger from a plausible-looking one. The cost of not solving these is compounding: 120 sources tagged against a bad scheme is 120 sources to re-ingest later.

This PRD covers **Phase A (ingestion) and the gold-corpus / evaluation loop only**. It does not cover the downstream research-paper, format-adaptation, or lens-application phases.

---

## 2. Goals

1. **Structure-aware ingestion.** Produce Obsidian notes whose chunk boundaries follow the source's argument, using full structural context (thesis, table of contents, surrounding sections) rather than isolated-section splitting.
2. **Multi-axis tagging from a swappable schema.** Tag every prose chunk and artifact against a versioned domain schema loaded at runtime — never hardcoded — so the same pipeline runs on a new country by editing the schema.
3. **Measured tagging reliability.** Generate a stratified gold corpus of ~100–120 human-labeled chunks and score the automated tagger against it, per axis, producing an agreement number that decides which contested tags survive.
4. **Separation of prose and artifacts.** Route non-text artifacts (tables, figures, block quotes, typologies) to a distinct retrievable pool, pre-tagged for role, with bidirectional links back to citing prose.
5. **Buildable without the Academic in the loop.** The pipeline runs end-to-end on a placeholder codebook; the Academic's labeling is a data swap plus an eval run, never a code change.

---

## 3. Non-goals

Each is excluded deliberately; documenting them prevents scope creep and protects the architecture.

1. **No plugin framework, no multi-tenancy, no arbitrary-user configurability.** "General" means *domain/country portability via schema extension or versioning* — nothing wider. Building for hypothetical future users is speculative generality and is out of scope.
2. **No OCR / no scanned documents.** Born-digital PDF and DOCX only. Scanned files are rejected at intake. This is a deliberate corpus boundary, not a limitation to work around later in v0.
3. **No local model hosting.** Inference is API-based (OpenRouter, NVIDIA developer APIs). A ~11 GB one-time ingestion does not justify local infrastructure.
4. **No downstream phases (B–E).** Brief intake, research-paper production, format adaptation, and lens application are separate initiatives. The 26 Academic research questions are parked (see §12), not built here.
5. **No full-corpus run until the eval closes.** v0 processes only the sample needed to build and score the gold set. Generalizing to all ~120 sources waits on a passing eval.
6. **No bottom-up / embedding-clustering vocabulary discovery for v0.** The schema is explicit and human-authored; clustering may return later as a discovery tool once the corpus is large enough to mean something.

---

## 4. Architecture principle

**Mechanism-general, domain-portable-by-schema, single-operator.**

The pipeline stages carry no country-specific logic. Every piece of domain content — the field set, the claim-type vocabulary, the empirical-scope country list, the theory-school taxonomy, the artifact-role taxonomy, and the codebook definitions — is one **versioned domain schema** loaded at runtime. Porting to another country means extending or versioning that schema (adjusting tags, the country list, the examples); the pipeline code is untouched.

This principle is load-bearing for two reasons. It makes the pause/placeholder seam free: because the tagger reads its vocabulary from the schema file, the build proceeds on a placeholder schema and the Academic's validated labels simply replace it. And it de-risks the two live vocabulary questions — folding in the candidate theory-school axis, or covering a second country, is a schema edit that the eval harness then scores against whatever axes the schema declares.

What the principle does **not** mean: it is not user-facing flexibility, not a config surface for non-technical users, not an abstraction layer over arbitrary domains. One domain schema ships in v0: Syria.

---

## 5. System overview — the pipeline

Seven stages, each a discrete, independently testable module. Every stage reads the domain schema; none embeds domain content.

1. **Intake.** Accept PDF or DOCX. Verify a real text layer exists; reject scanned / no-text-layer files with a clear, logged message. No OCR path. Output: validated source + source metadata stub.
2. **Structural extraction.** Run docling to produce a hierarchical tree that separates prose sections from non-text artifacts. If docling fails or produces degenerate output on a source, fall back to Unstructured for that source. This tree is produced once per source, persisted, and reused by every later stage for that source (not re-extracted). Output: structural tree (persisted).
3. **Structural-envelope pass.** One API call per source extracts the author's stated thesis, table of contents, scope, and stated argument from intro/abstract/conclusion. This "envelope" is produced once and reused by every later stage for that source. Output: envelope (JSON).
4. **Argumentative chunking.** For each prose section, an API call decides chunk boundaries *with the envelope plus surrounding sections in context* — never the isolated section. Chunks reflect argumentative units (a claim and its support), not fixed sizes. Output: prose chunks.
5. **Artifact classification & routing.** Each non-text artifact receives a role tag from the artifact-role taxonomy and is routed to a separate artifact pool with metadata. A lightweight model suffices — this is feature-based routing, not deep reasoning. Output: tagged artifacts in the artifact pool.
6. **Tagging.** Each prose chunk is tagged on the axes the schema declares (claim-type, field, empirical-scope, and the candidate theory-school axis), plus a role-in-argument tag and three-level metadata. Output: fully tagged chunks.
7. **Cross-reference pass.** Detect prose→artifact references ("as Table 3 shows") and write bidirectional links into both sides' frontmatter. Then write everything to the Obsidian vault. Output: vault notes (prose pool + artifact pool) with backlinks.

The gold-corpus and eval loop wrap around stages 4–6: sampled chunks are emitted into a label sheet, labeled, and scored (see §9–§10).

---

## 6. Repository structure

Scaffold to this shape. Names are prescriptive enough to remove ambiguity; adjust only with reason.

```
axial/
  pyproject.toml
  README.md
  config/
    pipeline.yaml              # providers, model-per-pass, paths, batch sizes
    domains/
      syria/
        schema.yaml            # fields, axes, country list, versioning (Appendix G)
        codebook.yaml          # tag -> definition -> +/- example (labeling instrument)
  src/axial/
    __init__.py
    schema/                    # domain-schema loader + validation
    intake/                    # format + text-layer validation
    extract/                   # docling wrapper; unstructured fallback
    envelope/                  # source-level structural-envelope pass
    chunk/                     # argumentative chunking
    artifacts/                 # artifact classification + routing
    tag/                       # axis tagging
    xref/                      # prose<->artifact cross-reference pass
    vault/                     # Obsidian writer (prose pool + artifact pool)
    drive/                     # Google Drive source connector
    llm/                       # provider clients (OpenRouter, NVIDIA), retries
    eval/                      # gold-set scoring harness
  data/
    trees/                     # one JSON per source (persisted structural tree)
    envelopes/                 # one JSON per source
    vault/
      prose/                   # prose-pool notes (.md with frontmatter)
      artifacts/               # artifact-pool notes (.md with frontmatter)
    gold/
      chunks/                  # sampled gold chunks
      label_sheet.xlsx         # one row per chunk, one column per axis
      labels/                  # returned Academic labels + scoring outputs
  tests/
```

---

## 7. Data & configuration contracts

### 7.1 Domain schema & loader contract

The domain schema (`config/domains/syria/schema.yaml`) declares the axes and their controlled vocabularies. The codebook (`config/domains/syria/codebook.yaml`) adds, per tag, a one-line definition and one positive + one negative example — this is both the tagger's reference and the labeling instrument. The v0 Syria contents are specified in full in Appendices A–G.

Loader contract:
- The loader reads the schema and codebook and exposes: the axis list, each axis's cardinality (single vs. primary+secondary vs. one-value), each tag's status flag, and each tag's definition/examples.
- **Every tag applied by the tagger must exist in the loaded schema.** A tag absent from the schema triggers a bounded correction re-ask: the tagger is shown that axis's controlled vocabulary and must return a valid value or an explicit `NONE`. A tag still absent from the schema after that single bounded re-ask is a hard error — never a silent pass, and never a code-side guess or normalization of the value. Only the model self-corrects; the code never rewrites an out-of-vocabulary value into a valid one.
- The schema carries a `version` field; every note written records the schema version it was tagged under, so a later schema change is detectable per note.
- Swapping domains = pointing the loader at a different `domains/<name>/` directory. No code path branches on country.

### 7.2 Three-level metadata (chunk & artifact frontmatter)

Every prose note carries three metadata levels (example in Appendix H):
- **Source-level:** author, title, date, `fields` (primary + secondary), author's stated thesis, scope. Reused from the envelope.
- **Section-level:** the author's own section/chapter labels, kept verbatim as the source's self-description.
- **Chunk-level:** claim-type tag(s), empirical-scope value (+ `country` where applicable), theory-school tag(s) `[candidate]`, `role_in_argument`, and `artifact_refs`.

Artifact notes carry: `artifact_role`, `fields`, source/section provenance, and `cited_by` back-references to prose chunks.

### 7.3 Structural envelope

One JSON per source in `data/envelopes/`: `{source_id, author, title, date, thesis, toc[], scope, stated_argument}`. Produced once in stage 3; consumed by stages 4 and 6, and reusable by downstream phases outside this PRD.

### 7.4 Structural tree

One JSON per source in `data/trees/`, keyed by `source_id` (the same deterministic id used for the envelope — `axial.envelope.compute_source_id`): the hierarchical tree from stage 2 — a root with `children`, each node carrying a `type` (`prose` or `artifact`) and an `order`. The shape is exactly the extraction pass's output (whether from docling or the Unstructured fallback); this subsection adds persistence, not a new shape. Produced once in stage 2 and reused by every later stage for that source (stages 4–7 and the tag/vault/xref passes read the persisted tree). A source is re-extracted only when no persisted tree exists for its `source_id`.

### 7.5 Gold-set label sheet

`data/gold/label_sheet.xlsx`: **one row per chunk, one column per axis.** Columns: `chunk_id`, `source`, `section`, `chunk_text`, then one column per axis with **dropdown validation sourced from the codebook**. Hybrid labeling per §9. The same sheet, once returned, is the machine-readable answer key for scoring — no transformation step between labeling and eval.

---

## 8. Requirements

### Must-Have (P0)

**P0-1 Intake validation.**
- [ ] Accepts `.pdf` and `.docx`; rejects everything else with a logged reason.
- [ ] Detects absence of a text layer and rejects the file with a clear message.
- [ ] Given a scanned PDF, when intake runs, then the file is rejected and never silently passed downstream.

**P0-2 Structural extraction with fallback.**
- [ ] docling produces a hierarchical tree separating prose from non-text artifacts.
- [ ] On docling failure/degenerate output for a source, Unstructured runs as fallback for that source; the fallback is logged.
- [ ] The structural tree is written once per source (keyed by `source_id`) and read by later stages (not re-extracted); a source is re-extracted only when no persisted tree exists for its `source_id`.

**P0-3 Structural-envelope pass.**
- [ ] One envelope JSON per source containing thesis, TOC, scope, stated argument.
- [ ] The envelope is written once and read by chunking and tagging (not recomputed).

**P0-4 Argumentative chunking with context.**
- [ ] The chunking call receives the envelope + surrounding sections, not the isolated section.
- [ ] Output chunks carry stable `chunk_id`s and preserve section provenance.

**P0-5 Artifact classification & routing.**
- [ ] Each non-text artifact receives exactly one `artifact_role` from the taxonomy (Appendix D).
- [ ] Artifacts are written to the artifact pool, not embedded in prose notes.
- [ ] `discard`-tagged artifacts are retained in the pool but flagged non-retrievable.

**P0-6 Schema-driven tagging.**
- [ ] Tagger loads all axes/tags from the domain schema; no tag is hardcoded.
- [ ] Field = one primary + ≥0 secondary. Empirical-scope = exactly one value. Claim-type = one primary + optional secondary.
- [ ] A tag absent from the schema triggers a bounded correction re-ask showing that axis's controlled vocabulary; a tag still absent after that bounded re-ask raises a hard error (never a silent pass, never a code-side guess/normalization).
- [ ] Each note records the schema `version` it was tagged under.

**P0-7 Cross-reference pass.**
- [ ] Prose→artifact references produce bidirectional links in both notes' frontmatter.
- [ ] Runs after both chunking and artifact classification have completed.

**P0-8 Obsidian vault write.**
- [ ] Prose pool and artifact pool are separate, independently queryable surfaces sharing metadata conventions.
- [ ] Notes carry valid three-level frontmatter and backlinks.

**P0-9 Gold-set generation & label sheet.**
- [ ] Emits ~100–120 chunks from ~20–28 sources. Balancing strata are field × empirical_scope × role_in_argument: the sample includes ≥1 chunk for each represented value of each of these three axes. source-type (book/paper), claim_type, and theory_school are not balancing strata; they ride along descriptively on whatever is drawn, and each source-type present in the corpus contributes ≥1 chunk. Non-substantive back-matter (endnotes, references/bibliography, index, appendix, front-matter) is excluded from the sampling frame; the sampler draws only from substantive prose.
- [ ] Produces `label_sheet.xlsx` with one row per chunk, one column per axis, codebook-sourced dropdowns.

**P0-10 Eval harness.**
- [ ] Reads returned labels + tagger output, computes per-axis agreement.
- [ ] Reports per-tag application counts (to surface never-used tags) and disagreements (to surface inconsistent tags).

**P0-11 Google Drive source connector.**
- [ ] Lists/reads sources from the shared "Books" folder via `parentId` search with `pageToken` pagination.

### Nice-to-Have (P1)

- **P1-1** Long-section handling: sections beyond a token threshold chunked across multiple calls with a coherence strategy (overlap window or recursive summary).
- **P1-2** Cohen's / Krippendorff's κ in addition to raw agreement, per axis.
- **P1-3** Ingestion log capturing per-source judgment calls (fallbacks used, ambiguous tags).
- **P1-4** Batch/resume: re-running skips already-processed sources.

### Future Considerations (P2 — design for, don't build)

- **P2-1** Second domain schema (another country) proving the swap costs no code change.
- **P2-2** Theory-school promoted from candidate to first-class axis if the eval supports it.
- **P2-3** Re-ingestion/versioning strategy when the schema changes post-run (grandfather vs. reprocess).

---

## 9. Gold corpus & labeling protocol

The gold set is the measurement instrument, so its construction is specified, not left to build-time judgment.

- **Size & stratification:** ~100–120 chunks from ~20–28 sources, ~4–6 chunks each. Balancing strata are field × empirical_scope × role_in_argument: every represented value of each of these three axes gets at least one chunk. source-type (book/paper), claim_type, and theory_school are not balancing strata; they are represented descriptively on whatever is drawn, and each source-type present in the corpus contributes at least one chunk. Non-substantive back-matter (endnotes, references/bibliography, index, appendix, front-matter) is excluded from the sampling frame; the sampler draws only from substantive prose.
- **Hybrid labeling** (bounds the Academic's effort where our guesses are reliable, gets clean signal where they are not):
  - **Blind** (Academic labels from scratch): `claim-type`, `theory-school`.
  - **Pre-labeled** (pipeline proposes, Academic corrects): `field`, `empirical-scope`.
- **Instrument:** the label sheet in §7.5. Dropdowns come from the codebook so the Academic never sees operator reasoning or free-types a tag.

---

## 10. Success metrics & eval

**Leading (measured as soon as the gold set returns):**
- **Per-axis agreement** between tagger and Academic labels. Report raw agreement for all axes; κ where P1-2 is built.
- **Tag coverage:** count of tags never applied across the gold set (removal candidates) and chunks the Academic tagged needing a value the schema lacked (addition candidates).
- **Contested-tag resolution:** each `[CONTESTED]` and `[CANDIDATE]` tag gets a keep/cut/rename decision from its gold-set behavior.

**Acceptance thresholds (starting hypotheses, tunable — see Open Questions):**
- A tag "survives" v0 if it is applied on ≥2 gold chunks *and* reaches ≥0.6 agreement on those chunks.
- Intake correctness: 100% of scanned/no-text-layer test files rejected, zero silent pass-through.
- Envelope reuse: chunking and tagging read the stored envelope (verified: no recompute).

**Lagging (post-v0):** reduction in re-ingestion churn on the full corpus; stability of the vocabulary across a second batch.

---

## 11. Build phases & the placeholder/pause seam

The config/data seam is the pause point. Because the tagger reads the codebook from a file, the build never blocks on the Academic.

1. **Scaffolding & schema loader** — repo per §6, schema/codebook loader, axes as config. *No Academic dependency.*
2. **Minimal ingestion** — intake → docling(+fallback) → envelope → chunking → vault write, on the **placeholder** Syria codebook (Appendices A–G). *No Academic dependency.*
3. **Tagging + artifact routing + cross-reference.**
4. **Gold-set generation** — run 2–3 on ~20–28 sampled sources; emit the label sheet. *Produces the Academic deliverable.*
5. **⏸ ACADEMIC LABELING** — Academic fills the sheet (hybrid, §9). *Pause here, or continue building 6–7 on placeholder labels.*
6. **Eval harness** — score, decide contested/candidate tags.
7. **Schema revision + second batch** — revise the schema from eval findings, re-run, compare. Only then consider the full ~120-source corpus (out of scope for v0).

---

## 12. Tech stack, dependencies & parked items

**Stack:** Python. **Parsing:** docling (baseline), Unstructured (fallback). **Inference:** API-based via OpenRouter and NVIDIA developer APIs; model-per-pass choice deferred (envelope and chunking want stronger reasoning; artifact routing wants a cheap model). **Source:** Google Drive shared "Books" folder (`parentId` + `pageToken`). **Output:** Obsidian vault (markdown + YAML frontmatter).

**Parked (not built here):** the 26 Academic research questions become the Phase B brief backlog; keep them on file, do not action them in Phase A.

---

## Open Questions

Genuinely unresolved; everything else in this document is settled.

- **[data]** Codebook config format detail — confirm YAML (assumed) vs. JSON, and the exact loader interface. *Non-blocking; YAML assumed for the build.*
- **[data/academic]** Theory-school as its own axis vs. claim-type sub-tags vs. Phase-C-only scaffolding. *Deferred to the eval (§10).*
- **[data]** Agreement metric + survival threshold: raw agreement vs. κ, and the exact cutoff. *Starting hypothesis in §10; tune after first gold set.*
- **[engineering]** Long-section chunking coherence across multiple calls (overlap window vs. recursive summary). *P1-1.*
- **[engineering]** Post-run schema-change handling: grandfather existing notes vs. reprocess. *P2-3; deferred until the first schema change is needed.*

---

# Appendices — Syria v0 Domain Schema (placeholder codebook)

Status flags: **[FIRM]** build as-is · **[TENTATIVE]** likely to shift after the gold set · **[CONTESTED]** the gold set must resolve this · **[CANDIDATE]** provisional axis, kept-or-cut by the eval · **[PROPOSED-CUT]** excluded, listed so it can be overruled.

## Appendix A — Field axis

Values: `state`, `violence`, `ideology`. Cardinality: one **primary** + zero-or-more **secondary**. Applies to prose chunks and artifacts. These are three distinct fields (lenses on organized political life), not sub-fields of one another; cross-field tags are deliberate, not emergent.

## Appendix B — Claim-type axis (prose chunks)

Cardinality: one primary + optional secondary. ~23 tags; sub-tags refine, they do not multiply the count.

**State domain**
- `state-formation` **[FIRM]** — how states form, consolidate, dissolve. Sub: `formation:bellicist` (Tilly, war-makes-states), `formation:colonial-import` (Badie, *État importé*), `formation:bottom-up` (Scott, Graeber/Sahlins), `formation:post-conflict` (statebuilding, Zaum).
- `state-capacity` **[FIRM]** — what a state can do. Sub: `capacity:infrastructural`, `capacity:despotic` (Mann's pair), `capacity:extractive`, `capacity:coercive`.
- `state-autonomy` **[FIRM]** — state independence from social forces (Skocpol). Distinct from capacity.
- `state-society-relations` **[CONTESTED]** — Migdal-style state/society co-shaping; strong-society/weak-state; the Syria literature (Heydemann, Hinnebusch, Dukhan, Akdedian). *Merge candidate with `state-capacity` — the gold set decides.*
- `legitimacy-and-legitimation` **[FIRM]** — how authority is justified/accepted/contested. Sub: `legitimacy:traditional`, `legitimacy:rational-legal`, `legitimacy:charismatic` (Weberian), `legitimacy:juridical-vs-empirical` (Jackson, Caspersen), `legitimacy:compliance-without-belief` **[CONTESTED]** (Wedeen — "acting as if"; note this is arguably a *critique* of legitimacy; the gold set decides whether to keep it under this umbrella or move Wedeen-style material to `role:counter-position`).
- `sovereignty-and-recognition` **[FIRM]** — sovereignty as norm/practice/contested; recognition; sovereign exception (Agamben).
- `statehood-gradations` **[TENTATIVE]** — statehood as non-binary: weak/failed/quasi/unrecognized/contracted (Jackson, Caspersen, Syria resilience literature). Overlaps sovereignty and capacity; watch for double-tagging.

**Violence domain**
- `violence-logic` **[FIRM]** — why violence takes its forms. Sub: `violence:selective-vs-indiscriminate` (Kalyvas — jointly produced by control + information; surface this in the tagging prompt), `violence:instrumental-vs-constitutive` (Üngör, Mann's *Dark Side*, Malešević).
- `violence-actors` **[FIRM]** — militaries, paramilitaries, insurgents, organized crime, civilians-as-perpetrators.
- `civilian-targeting` **[FIRM]** — violence against non-combatants: ethnic cleansing, genocide, mass atrocity (Downes, McDoom, Mann).
- `mobilization-and-recruitment` **[FIRM]** — how violent organizations recruit, retain, discipline (Weinstein).
- `war-and-state` **[CONTESTED]** — war-making ↔ state-making. *Drop candidate: may be covered by `state-formation:bellicist` + the state×violence field intersection. But a non-formation literature exists (Mann's *On Wars*, Heydemann). The gold set decides.*

**Ideology domain**
- `nationalism-theory` **[FIRM]** — what nationalism is/how it works. Sub: `nationalism:modernist` (Gellner, Anderson, Hobsbawm, Breuilly), `nationalism:ethno-symbolist` (Smith, Connor), `nationalism:practice-based` (Brubaker, Billig).
- `identity-and-group-formation` **[CONTESTED]** — how groups form/persist/dissolve; Brubaker's groupness as a *variable* (including failed mobilization). *Keep flat for v0, or add `groupness:high/failed-mobilization`? The gold set decides.*
- `ideology-as-system` **[FIRM]** — doctrines, codified beliefs, programmatic ideology.
- `ideology-as-practice` **[FIRM]** — ideology-in-action, banal nationalism, performative authoritarianism (Wedeen).
- `legitimating-narratives` **[CONTESTED]** — origin myths, golden-age and threat narratives. *Drop candidate: may be redundant with `ideology-as-practice` + `legitimacy-and-legitimation` co-tag. The gold set decides.*
- `religion-and-politics` **[TENTATIVE]** — religion's role in political order (Gellner on Islam; small corpus cluster). Could fold into `ideology-as-system`.

**Cross-cutting**
- `power-typology` **[FIRM]** — typologies of power forms; Mann's IEMP is the dominant case.
- `revolution-and-contention` **[FIRM]** — revolutions, movements, contentious politics (Skocpol, Tilly, Goldstone, Bayat; Arab Uprisings).
- `comparative-method` **[FIRM]** — methodological claims: case selection, comparative-historical approach.
- `normative-political-theory` **[TENTATIVE]** — explicitly normative rather than explanatory claims (Cohen on Marx, Agamben). Could instead be a `role:normative-claim`.

**[PROPOSED-CUT]** `institutional-design`, `political-economy`, `historical-memory` — excluded (near-empty in corpus, or better covered by existing tags). Overrule if wrong.

## Appendix C — Empirical-scope axis (prose chunks)

Cardinality: exactly one value.
- `scope:general` **[FIRM]** — theory with no specific empirical case (Mann on autonomy; Brubaker on groupness).
- `scope:comparative` **[FIRM]** — explicit cross-case comparison (Skocpol on France/Russia/China).
- `scope:regional` **[FIRM]** — a region without single-country focus (MENA, post-Soviet, post-colonial Africa).
- `scope:country-case` **[FIRM]** — a specific country; carries an additional `country` field. Most of the Syria literature (Hinnebusch, Akdedian). The model supplies `country` as free text: a non-empty string is required — a missing or empty value stays the hard error it is today — but the value is not validated against a fixed list. Values outside the schema's `country_list` are accepted and logged as candidate additions, never fatal in v0. The controlled list plus its aliasing layer returns as enforced vocabulary only at the post-eval schema revision (§11 step 7).
- `scope:sub-national` **[TENTATIVE]** — a city, sub-region, single rebel group, or institution. Rule of thumb: if the claim generalizes to the country, tag `country-case`; if it is about the sub-national unit's distinctiveness, tag `sub-national`.

Rationale for the axis: a brief like "does Mann's infrastructural power apply to post-2011 Syria" must retrieve `capacity:infrastructural × scope:general` (Mann) and `capacity:infrastructural × scope:country-case:Syria` (Hinnebusch, Akdedian) *separately*, then synthesize. Without scope, both fall in one undifferentiated bucket.

## Appendix D — Artifact-role axis (artifacts)

Cardinality: one value. Closed set.
- `case-study` **[FIRM]** — empirical/quantitative tables; structured evidence for a case or comparison.
- `framework-illustration` **[FIRM]** — conceptual diagrams expressing a framework visually.
- `quote-pool` **[FIRM]** — block-quoted primary-source material (interview excerpts, archival fragments, manifestos).
- `framework` **[FIRM]** — the author's own typologies/taxonomies/models. Sub: `framework:formal-model` for equations/formalisms.
- `reference-material` **[CONTESTED]** — glossaries, indexes, chronologies, maps (descriptive scaffolding). *Fold into `case-study` if these function as evidence in practice — the Academic decides.*
- `discard` **[FIRM]** — cover images, running heads, page numbers; retained but flagged non-retrievable.

## Appendix E — Theory-school axis (prose chunks) **[CANDIDATE]**

Provisional; kept-or-cut by the eval. Derived from the Academic's mind-map; orthogonal to claim-type (a `state-capacity` claim can come from a Bellicist *or* an Institutionalist school). Cardinality if kept: one primary + optional secondary. Grouped controlled vocabulary:

- **State:** `colonial-postcolonial`, `marxist-political-economy`, `cultural-ideational`, `bellicist`, `neo-bellicist`, `external-statebuilding`, `neo-marxist`, `modernization-developmental`, `institutionalist-state-centered`, `structuralist`, `state-in-society` (Migdal), `constructivist`.
- **Violence:** `opportunity-feasibility`, `constructivist-anti-essentialist`, `biological-evolutionary`, `structural-violence`, `civilizing-decline` (Eliasian), `state-centered-organizational` (Weberian/neo-Weberian, bellicist), `micro-sociological` (interactionist/situationist; micro-foundations, Kalyvas; micro-solidarity, Malešević), `interpretive-constructivist`, `marxist-critical-pol-econ`, `postcolonial-decolonial`, `criminological` (rational-choice, social-learning, traits, strain/anomie, routine-activity, feminist).
- **Ideology:** `materialist` (classical/neo-Marxism), `systematic` (structuralism, functionalism), `discursive` (post-Marxism, post-structuralism, discourse theory), `historical-sociological` (Mannheim; Malešević), `subject-centered` (identity-based, psychoanalytical).

Note the deliberate cross-field recurrence (Malešević, Brubaker, Mann, Tilly appear under multiple fields) — this is the faceting pressure the eval should watch: if theory-school tags co-vary too tightly with field or claim-type, the axis is redundant and gets cut.

## Appendix F — Role-in-argument axis (prose chunks) **[FIRM]**

Cardinality: one value. Not sent for Academic review — stable across the literature.
`role:setup`, `role:claim`, `role:evidence`, `role:counter-position`, `role:synthesis`, `role:methodological`, `role:digression`. (Add `role:normative-claim` only if `normative-political-theory` is dropped.)

## Appendix G — Example `schema.yaml`

```yaml
domain: syria
version: 0.1
axes:
  field:
    applies_to: [prose, artifact]
    cardinality: primary_plus_secondary
    values: [state, violence, ideology]
  claim_type:
    applies_to: [prose]
    cardinality: primary_plus_optional_secondary
    values:   # see Appendix B; each carries status + optional sub-tags
      - id: state-formation
        status: firm
        subtags: [formation:bellicist, formation:colonial-import, formation:bottom-up, formation:post-conflict]
      # ... remaining claim-type tags ...
  empirical_scope:
    applies_to: [prose]
    cardinality: single
    values: [scope:general, scope:comparative, scope:regional, scope:country-case, scope:sub-national]
    extra_fields:
      scope:country-case: { country: free_text }   # required non-empty; see Appendix C
  theory_school:
    applies_to: [prose]
    cardinality: primary_plus_optional_secondary
    status: candidate
    values: [...]   # Appendix E
  artifact_role:
    applies_to: [artifact]
    cardinality: single
    values: [case-study, framework-illustration, quote-pool, framework, reference-material, discard]
  role_in_argument:
    applies_to: [prose]
    cardinality: single
    values: [role:setup, role:claim, role:evidence, role:counter-position, role:synthesis, role:methodological, role:digression]
country_list: [Syria, Turkey, Lebanon, Iraq, Rwanda]   # known-corpus reference for logging/aliasing in v0, not a validation gate; becomes enforced vocabulary at §11 step 7
```

`codebook.yaml` mirrors this, adding `definition`, `positive_example`, `negative_example` per tag (the Appendix B–F text is the source for those).

## Appendix H — Example prose-chunk frontmatter

```yaml
---
chunk_id: hinnebusch2001_ch3_004
source: "Hinnebusch — Syria: Revolution from Above"
source_meta:
  author: "Raymond Hinnebusch"
  date: 2001
  fields: { primary: state, secondary: [ideology] }
  thesis: "Ba'athist state formation as authoritarian modernization from above."
section: "Chapter 3 — The Ba'athist State"
schema_version: 0.1
claim_type: { primary: state-capacity, secondary: state-society-relations, subtags: [capacity:infrastructural] }
field: { primary: state, secondary: [ideology] }
empirical_scope: { value: scope:country-case, country: Syria }
theory_school: { primary: institutionalist-state-centered, status: candidate }
role_in_argument: role:claim
artifact_refs: [hinnebusch2001_tbl_02]
---
```

## Appendix I — Label-sheet columns

`chunk_id | source | section | chunk_text | field (pre-labeled) | empirical_scope (pre-labeled) | claim_type (blind) | theory_school (blind) | notes`

Dropdowns on the four axis columns are generated from `codebook.yaml`. Pre-labeled columns arrive filled with the tagger's guess for the Academic to correct; blind columns arrive empty.
