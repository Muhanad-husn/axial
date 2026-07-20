# PRD — Axial: Phase A Corpus Ingestion Pipeline (Syria v0)

**Project:** Axial · **Version:** 1.0 · **Status:** Ready to build · **Owner:** Operator (single-operator system)

**Inherits.** This PRD is the Phase-A phase spec under [`specs/CHARTER.md`](CHARTER.md), the product-wide behavioural constitution; its P0 criteria are the substrate-layer instance of the charter's five principles.

**On the name.** *Axial* names the mechanism and the tradition in one word: the system tags every chunk along multiple **axes** (field, claim-type, empirical-scope, artifact-role, theory-school), and *axial coding* is the grounded-theory move — native to this corpus through Malešević — of relating categories to one another along dimensions. The Python package is `axial`.

**Self-sufficiency note.** This document is the *complete* build specification for Phase A. Everything required to scaffold and build the pipeline — architecture, pipeline stages, config contracts, the full v0 tag set, acceptance criteria, and appendices — is contained here, and Claude Code should be able to start the build from this file alone. Its single parent is the behavioural constitution in [`specs/CHARTER.md`](CHARTER.md), which governs *why* the pipeline is built as it is; beyond that one charter it references no external file. Where a decision is genuinely unresolved, it is listed under **Open Questions** (§12); everything else is settled and should be built as written.

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

1. **Structure-aware ingestion.** Produce Obsidian notes whose chunk boundaries follow the source's argument — found by a recursive/structural splitter that respects the prose's own separator hierarchy (paragraph → line → sentence → character) within each section — rather than arbitrary fixed-size or page-break splitting. Every chunk is bounded by construction, so no single unit blows a request deadline or token budget downstream.
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

The pipeline stages carry no country-specific logic. Every piece of domain content — the field set, the claim-type vocabulary, the empirical-scope polity examples, the theory-school taxonomy, the artifact-role taxonomy, and the codebook definitions — is one **versioned domain schema** loaded at runtime. Porting to another country means extending or versioning that schema (adjusting tags, the polity examples, the codebook examples); the pipeline code is untouched.

This principle is load-bearing for two reasons. It makes the pause/placeholder seam free: because the tagger reads its vocabulary from the schema file, the build proceeds on a placeholder schema and the Academic's validated labels simply replace it. And it de-risks the two live vocabulary questions — folding in the candidate theory-school axis, or covering a second country, is a schema edit that the eval harness then scores against whatever axes the schema declares.

What the principle does **not** mean: it is not user-facing flexibility, not a config surface for non-technical users, not an abstraction layer over arbitrary domains. One domain schema ships in v0: Syria.

---

## 5. System overview — the pipeline

Seven stages, each a discrete, independently testable module, with a **source-routing step folded into stage 2** (step 2b below) that classifies every tree block before any later stage consumes it. Every stage reads the domain schema; none embeds domain content.

1. **Intake.** Accept PDF or DOCX. Verify a real text layer exists; reject scanned / no-text-layer files with a clear, logged message. No OCR path. Sources are supplied by the Google Drive connector (§7.10, P0-11), which streams each file's bytes into intake and applies an English-only language gate to text-layer sources before the expensive extraction begins. A **holdings-completeness check** also runs here, reading the raw text layer already in hand to flag a source that carries only part of the work it names (§7.11, P0-1b). Deterministic pre-processing cleans that text — physical page count, running header and footer stripping — and a single model call then judges what kind of document this is and whether the file covers the extent the document claims. Unlike the text-layer check, it flags and reports only: it never rejects, and a flagged source proceeds unchanged. Intake also reads the source's **author, title and date** from the file itself rather than leaving them to the envelope pass (§7.13, P0-1d). Everything intake learns about the file is written to a persisted **source-metadata record** that survives envelope regeneration (§7.12, P0-1c). Output: validated source + its source-metadata record.
2. **Structural extraction, then source routing.** Run docling to produce a hierarchical tree that separates prose sections from non-text artifacts. If docling fails or produces degenerate output on a source, fall back to Unstructured for that source. At tree-build time, before the tree is persisted, a deterministic, model-free **text-normalization pass** repairs decoding defects in each block's `text` (soft-hyphens, whitespace damage, detached combining marks, known glyph-name leaks — full contract in §7.4) without altering the tree's shape or any block's `label`, `type`, or `order`; because normalization happens here, every downstream pass inherits clean text. This tree is produced once per source, persisted, and reused by every later stage for that source (not re-extracted). Output: structural tree (persisted, text-normalized).
   - **2b. Source routing.** Before any consumer reads the tree, a routing step classifies each tree block by its docling structural `label` (§7.4) and assigns it exactly one of three **routes** — **prose**, **artifact**, or **apparatus** (full contract in §7.8). Only prose-routed blocks reach the chunk stage (stage 4); artifact-routed blocks (tables, figures, captions) go to artifact classification (stage 5); apparatus-routed blocks (TOC / index, endnotes / footnotes, running heads, and reference / citation lists detected by content even when docling labelled them prose) are **dropped** — not chunked, not artifact-noted — and recorded with a reason. This is a *single, shared* classification: every downstream pass (chunk, artifact, tag, cross-reference) consumes the routed result rather than re-deriving the prose/non-prose decision for itself. The router runs over the persisted tree and triggers no re-extraction; it calls **no model for the `label`→route mapping**, its one exception being a single bounded per-block classification of the small set of content-flagged apparatus candidates (§7.8), which clean prose never reaches. Output: a route per block, plus the router-owned skip record for dropped blocks. *(Position chosen: folded into stage 2 as sub-step 2b rather than inserted as a new numbered stage, so the existing stage 3–7 numbering and every "stage N" cross-reference in this document stay coherent.)*
3. **Structural-envelope pass.** One API call per source extracts the author's stated thesis, a **reconstructed hierarchical table of contents** (grounded in the source's own printed TOC and detected headings), scope, and stated argument. It reads the source's intro / abstract / conclusion where those headings are present, and **widens to a substantive head-of-tree slice** of the source's prose when they are not — so the model is always grounded in real source text and never asked for a thesis over an empty evidence block, and the extraction is grounded only in the supplied text, never in the title or outside knowledge (§7.3, #201). This "envelope" is produced once and reused by the tagging stage (stage 6) for that source; the chunk stage does not consume it. Output: envelope (JSON).
4. **Chunking (recursive/structural, deterministic, LLM-independent).** For each prose section, the chunk stage finds boundaries with a **recursive/structural splitter** (#165, #191) — the sole chunk mechanism. It splits along the prose's own separator hierarchy — paragraph (`\n\n`) → line (`\n`) → sentence → character — descending to the next-finer separator only when a piece still exceeds the size band. The mechanism is deterministic and model-free: it calls **no embedding model and no text-generating LLM**. (The earlier embedding-based semantic mechanism was retired per #191 after a head-to-head over six real sources; recursive/structural is now the only mechanism, so the whole embedding apparatus leaves the chunk path.) Every chunk is **bounded by construction into a two-sided size band** `[min, max]`: the raw breakpoints bound size in neither direction on their own, so a deterministic guard pass wraps boundary detection and enforces the band around it. Below `min`, a sub-floor chunk is **merged into a same-section neighbour** — into its same-section *predecessor* where the merged result would still fit within `max`, otherwise *forward* into its same-section successor, and kept as-is only when it is the section's sole chunk with no neighbour to absorb it — never across a section boundary and never dropped (preventing small-chunk proliferation from short paragraphs, headers, and list items; §7.8 / P0-4); above `max`, a chunk is split at its next-best internal boundary (this is what guarantees no unit blows a request deadline or token budget). A section too large for one request — today up to ~143k characters — is therefore *split* into multiple in-band chunks rather than echoed whole through an API, dissolving the "monster section" problem at its source rather than band-aiding it. The detected breakpoints remain the **primary** boundary signal; the guard only enforces the band around them. The band is anchored on what the vault stores and works downstream today (~1–3k characters per chunk). Boundaries still track argumentative shifts (a boundary falls where the prose changes topic), not fixed sizes. The stage reads the **prose-routed** blocks of the persisted structural tree only — apparatus and artifact blocks are removed upstream by the source router (§7.8, step 2b), so they never enter the chunk path — and it needs no envelope (nothing in the chunking mechanism consumes one); its meaningful guarantee is that no generative LLM call sits in the chunk critical path, which subsumes any "no recompute" claim. It writes the chunk records to disk (§7.7) **before any downstream LLM spend**, so chunk quality is inspectable — the examine step, §7.7 — with zero inference cost. Type-detectable non-prose (TOC, index, endnotes, running heads) is dropped by the router by structural `label`, not by this stage; a residual size/garble rule (high non-alphabetic ratio) survives only as a **backstop** for garbled prose that slips type classification, and its skips are recorded in the same router-owned skip record (§7.8). That backstop runs at the *section* level, so a narrow **post-split fragment floor** (§7.8, #193, generalized in #197) runs after the splitter to drop any emitted chunk that is unambiguous non-content boilerplate — a blank-page notice or a low-alpha fragment whose alphabetic ratio is below the low-alpha threshold (currently 0.45) — recording each drop with its reason; a chunk whose alphabetic ratio is at or above the threshold is kept, so genuine section-tail sentences survive. A legitimate long section is split, never skipped, so no real prose is silently dropped. Output: on-disk prose chunks (§7.7), consumed by every later stage.
5. **Artifact classification & routing.** This pass is the **sole home** of tables, figures, and captions; it receives exactly the artifact-routed blocks from the source router (§7.8, step 2b) — never raw docling output and never apparatus. Each artifact receives a role tag from the artifact-role taxonomy and is routed to a separate artifact pool with metadata (`artifact_role`, provenance, `cited_by`); a caption attaches to its figure or table. A lightweight model suffices — this is feature-based routing, not deep reasoning. Output: tagged artifacts in the artifact pool.
6. **Tagging.** Each prose chunk is tagged on the axes the schema declares (claim-type, field, empirical-scope, and the candidate theory-school axis), plus a role-in-argument tag, the many-valued `polities_touched` facet (Appendix C, G), and three-level metadata. Empirical-scope aboutness stays single-valued (its `scope:country-case` value carries a free-text `polity`); `polities_touched` separately captures every polity the chunk substantively engages. Output: fully tagged chunks.
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
        schema.yaml            # fields, axes, polity examples, versioning (Appendix G)
        codebook.yaml          # tag -> definition -> +/- example (labeling instrument)
  src/axial/
    __init__.py
    schema/                    # domain-schema loader + validation
    intake/                    # format + text-layer validation
    extract/                   # docling wrapper; unstructured fallback
    envelope/                  # source-level structural-envelope pass
    chunk/                     # recursive/structural chunking + examine
    artifacts/                 # artifact classification + routing
    tag/                       # axis tagging
    xref/                      # prose<->artifact cross-reference pass
    vault/                     # Obsidian writer (prose pool + artifact pool)
    drive/                     # Google Drive source connector
    llm/                       # provider clients (OpenRouter, NVIDIA), retries
    eval/                      # gold-set scoring harness
  data/
    drive/                     # fetch-state manifest (fetch_state.json, §7.10)
    source_meta/               # one JSON per source (persisted source-metadata record, §7.12)
    trees/                     # one JSON per source (persisted structural tree)
    envelopes/                 # one JSON per source
    chunks/                    # one JSONL per source (persisted chunk artifact, §7.7)
    vault/
      prose/                   # prose-pool notes (.md with frontmatter)
      artifacts/               # artifact-pool notes (.md with frontmatter)
    gold/
      chunks/                  # sampled gold chunks
      label_sheet.xlsx         # one row per chunk, one column per axis
      delivery/                # dated Academic handoff bundles (sheet copy + README + manifest)
      labels/                  # returned Academic labels + scoring outputs
  tests/
```

---

## 7. Data & configuration contracts

### 7.1 Domain schema & loader contract

The domain schema (`config/domains/syria/schema.yaml`) declares the axes and their controlled vocabularies. The codebook (`config/domains/syria/codebook.yaml`) adds, per tag, a one-line definition and one positive + one negative example — this is both the tagger's reference and the labeling instrument. The v0 Syria contents are specified in full in Appendices A–G.

Loader contract:
- The loader reads the schema and codebook and exposes: the axis list, each axis's cardinality (single vs. primary+secondary vs. one-value), each tag's status flag, and each tag's definition/examples.
- **Every tag applied by the tagger must exist in the loaded schema.** A tag absent from the schema triggers a bounded correction re-ask: the tagger is shown that axis's controlled vocabulary and must return a valid value or an explicit `NONE`. A tag still absent from the schema after that single bounded re-ask is a hard error — never a silent pass, and never a code-side guess or normalization of the value. Only the model self-corrects; the code never rewrites an out-of-vocabulary value into a valid one. **Exception: `theory_school`** (Appendix E), whose vocabulary is derived from one expert's mind-map and does not yet cover every school a source may legitimately invoke — a value still out of vocabulary after the bounded re-ask lands as the `unlisted` sentinel instead of failing the source, with the model's proposed name logged for operator review (Appendix E). Every other axis (`field`, `claim_type`, `role_in_argument`, `empirical_scope`) keeps the hard-error contract above unchanged.
- The schema carries a `version` field; every note written records the schema version it was tagged under, so a later schema change is detectable per note.
- Swapping domains = pointing the loader at a different `domains/<name>/` directory. No code path branches on country.

### 7.2 Three-level metadata (chunk & artifact frontmatter)

Every prose note carries three metadata levels (example in Appendix H):
- **Source-level:** author, title, date, `fields` (primary + secondary), author's stated thesis, scope. Composed from two artifacts: `author`, `title` and `date` come from the source-metadata record (§7.12, §7.13); the thesis and scope come from the envelope (§7.3). The frontmatter key set is unchanged by that split.
- **Section-level:** the author's own section/chapter labels, kept verbatim as the source's self-description.
- **Chunk-level:** claim-type tag(s), empirical-scope value (+ `polity` where applicable), the `polities_touched` list, theory-school tag(s) `[candidate]`, `role_in_argument`, and `artifact_refs`.

Artifact notes carry: `artifact_role`, `fields`, source/section provenance, and `cited_by` back-references to prose chunks.

### 7.3 Structural envelope

One JSON per source in `data/envelopes/`: `{source_id, thesis, toc[], scope, stated_argument}`. Produced once in stage 3; consumed by stage 6 (tagging) — the chunk stage does not consume it — and reusable by downstream phases outside this PRD. The shape is **locked**: `thesis`, `scope`, and `stated_argument` are non-empty strings; `toc` is a **non-empty list of `{title, children[]}` objects**, each object's `title` a non-empty string and its `children` a list of strings (possibly empty), so parts hold chapters and chapters hold sections; and no field is nullable.

Two amendments changed this locked shape, both deliberate. #235 **changed the `toc` element shape** — a flat list of strings became this nested list of objects — adding and removing no field; that change was founder-approved directly. The second **removes `author`, `title` and `date` from the envelope entirely** (§7.13): those are facts about the file, they are now read at intake, and they live in the source-metadata record (§7.12). This removal follows from the founder's decision to read the three fields at intake rather than being separately ruled on: keeping them in the envelope as well would recreate the two-sources-of-truth problem that decision exists to end. The pass was never able to fill them honestly — `author` and `date` are null in all 30 envelopes and `title` is the filename slug title-cased, which is a fabrication, not a reading. Removing them makes the no-field-is-nullable rule true rather than aspirational. Neither amendment ripples into note shape or tagging and neither implies a re-tag: the vault's `source_meta` block keeps its five keys, now composed from both artifacts (§7.13), and nothing downstream consumes `toc` today — it is produced, validated, stored, and reused by later phases outside this PRD.

What the envelope is left holding is exactly what it is good at: what the model concludes about the *work* from reading its argument. Everything the file states about itself lives one artifact upstream.

**Evidence floor on the input.** The pass must never ask the model for a thesis over an empty or near-empty evidence block. Its input selection starts from the intro / abstract / conclusion heading heuristic. That heuristic matches nothing on a source whose top-level sections are titled by topic, and an empty evidence block is exactly what lets the model free-associate a plausible-but-wrong thesis (#201; the observed defect summarized Agamben's *State of Exception* as an internet-governance paper). So when the heuristic selects little or no text, the input **widens to a substantive head-of-tree slice**: a bounded prefix of the source's own prose, taken in tree order, large enough that the model always sees real source text before it is asked for a thesis. The slice proceeds in tree order but **skips a leading front-matter / apparatus prefix** — title page, copyright and ISBN block, publisher boilerplate, preface scaffolding — and begins counting at the first genuinely substantive body prose, so a source whose head-of-tree is a wall of front matter still yields real argument text (#222). It still reads in tree order; it just does not start the bounded count until real body prose begins. How much leading apparatus may be skipped before the count starts is a stated **tunable**, not a magic constant, bounded so the skip can never consume the whole source. The slice size is likewise a stated **tunable**, not a magic constant, proven via inspection in the spirit of the chunk band `[min, max]` (§7.7) and the low-alpha threshold (§7.8). The guarantee is an observable **minimum-evidence property**: the evidence assembled for the envelope call always carries **substantive argument prose** — never an empty or whitespace-only section block, and never a mis-sectioned bibliography that merely clears the character floor (below, #222) — for every source, including one whose top-level headings match none of intro / abstract / conclusion.

**Evidence is the full text of the selected sections.** The evidence for a matched section is that section's **own** prose together with its children's, not its children's alone. A flat intro whose text hangs directly on the matched node still yields real evidence; the matched node's direct text is never dropped.

**Bibliography-by-aggregate exclusion.** A matched intro / abstract / conclusion section is not always argument prose. docling sometimes **mis-attaches a source's bibliography under a body-section heading** — an "Introduction" or "Conclusion" heading whose descendants are in fact a reference list, fragmented into individual one-citation leaf nodes (#222; observed on the Tilly source, whose mis-sectioned reference wall runs to ~9k characters). That wall of citations clears the character-count evidence floor above, so without a further check the pass hands the model a bibliography instead of an argument and gets back a grounded-but-shallow thesis — the section heading echoed as prose. This is distinct from #201: the model does not confabulate, it correctly refuses to invent; it simply has no argument prose to work from. The envelope's matched-section selection therefore computes an **aggregate citation signal across the section's descendants** — the share of the section's leaf nodes that are single-citation / bibliographic entries (e.g. inverted author-name entries, "Lastname, F. …", and citation-list line structure, counted across children) — and when that aggregate share is high enough, treats the section as **non-prose apparatus and excludes it from the matched-section evidence before the evidence-floor check**. A bibliography-poisoned "Introduction" or "Conclusion" then no longer masks the floor, so the pass widens to the head-of-tree slice above and finds real body prose. The signal is deliberately an **aggregate across a section's descendants, not per-block density**: the §7.8 content-apparatus arm keys on citation density **within a single block**, and this bibliography's citations are fragmented one-per-leaf, each leaf below that per-block threshold, so the §7.8 arm flags zero of them (it still catches the same apparatus once chunked, because a chunk aggregates many citations into one dense block; the envelope reads pre-chunk tree leaves — a different granularity, which is why the envelope needs its own aggregate signal). The aggregate share that marks a section bibliographic is a stated **tunable**, not a magic constant, proven via inspection in the spirit of the §7.8 citation-density signal, the chunk band `[min, max]` (§7.7), and the low-alpha threshold (§7.8). Mirroring §7.8's **never-drop-on-uncertainty** principle, the detector is **conservative**: it fires only on a high-confidence bibliographic aggregate, never on ordinary argument prose that merely cites sources in passing; when the signal is uncertain, the section stays prose. The **minimum-evidence property** is thereby strengthened: the assembled evidence must be substantive argument prose, so a bibliography that clears the raw character floor does **not** satisfy it.

**Grounded by construction.** The prompt instructs the model to base `thesis`, `scope`, and `stated_argument` **only on the supplied source text**, and explicitly **not** to infer from the title, the filename, or outside knowledge. No envelope field may be derived from anything but the provided text. The `title` is read at intake and recorded in the source-metadata record (§7.12, §7.13); it is not an envelope field and is never a source for the extracted fields. Reasoning is **ON** for this call (§7.9): the extraction is judgment-heavy, once per source, and its metadata quality gates every tagged chunk downstream.

**Table of contents by two-signal reconstruction.** The `toc` is not thesis evidence and is not a flat dump of detected headings. The model **reconstructs** the source's real table of contents, within the **same single envelope call** (§5 keeps the envelope at one API call per source), grounded in exactly **two signals** read from the cached structural tree and nothing else — no title, no filename, no outside knowledge. **Signal A** is the source's opening pages, read as a front-matter-**inclusive** head-of-tree slice: it deliberately keeps the printed table-of-contents page when the source prints one, because that page is the best signal for a clean chapter list. This is a **distinct slice** from the front-matter-**skipped** evidence the thesis / scope / stated-argument extraction uses (the evidence-floor machinery above, #222 / #225): the printed TOC page is noise for the thesis but the source for `toc`, so it is kept out of the thesis evidence and fed only to the toc reconstruction, which resolves the dual role with no router change. **Signal B** is the flattened list of the tree's detected top-level headings; docling has flattened the heading hierarchy into one `section_header` level, mixing genuine chapter titles with subsection headings, OCR-garble fragments, and body sentences mislabelled as headings. From these two signals the model reconstructs the nested `{title, children[]}` hierarchy: it prefers the printed TOC in Signal A when present and legible, otherwise reconstructs from the genuine chapter / section headings in Signal B. It excludes subsection noise, OCR-garble, mislabelled body lines, and pure apparatus (index, bibliography, list of figures / tables) unless one is a genuine part. Grounding is **by construction**, the same guarantee "Grounded by construction" makes for the other fields: the prompt instructs the model to use ONLY the two supplied signals. If the reconstruction fails validation, the pass falls back deterministically to the tree's own detected heading list, preserving the non-empty guarantee (#235).

### 7.4 Structural tree

One JSON per source in `data/trees/`, keyed by `source_id` (the same deterministic id used for the envelope — `axial.envelope.compute_source_id`): the hierarchical tree from stage 2 — a root with `children`, each node carrying a `type` (`prose` or `artifact`), an `order`, and the docling structural **`label`** (the block type — e.g. `text`, `section_header`, `title`, `list_item`, `table`, `caption`, `footnote`, `document_index`, `picture`) preserved verbatim from extraction. The `label` is what the source router (§7.8) classifies on; it is a finer-grained signal than the two-value `type`. The shape is exactly the extraction pass's output (whether from docling or the Unstructured fallback); the tree's structure and every block's `label`, `type`, and `order` are preserved from extraction. This subsection adds persistence and a text-normalization pass (below) — not a new shape. Produced once in stage 2 and reused by every later stage for that source (stages 4–7 and the tag/vault/xref passes read the persisted tree). A source is re-extracted only when no persisted tree exists for its `source_id`.

**Post-extract text normalization.** The docling PDF text-layer *decoding* garbles glyphs a clean source renders correctly (this is not OCR — extraction runs with `do_ocr=False`; the defect is in decoding, not scanning). Before the tree is persisted, a **deterministic, model-free normalization pass applied at tree-build time** repairs those defects in each block's `text`. Because it runs here, once, every downstream pass (chunk, tag, xref, artifacts) inherits clean text, and a re-extraction regenerates the normalized tree. Normalization touches **only `text` values**: it never changes the tree's shape or any block's `label`, `type`, or `order`, so the source router (§7.8) classifies exactly as before. It is organized as **independent transforms, each a no-op when its target defect is absent** — a clean-font source (correctly decoded to begin with) passes through materially unchanged.

- **Whitespace (universal).** Strip soft-hyphens (U+00AD); collapse runs of whitespace to a single space; remove space-before-punctuation. This defect is near-universal and zero-risk.
- **Glyph repair (font-specific, no-op when absent).** Drop or reattach detached combining marks (Unicode category Sk — e.g. a detached macron, acute, diaeresis, or cedilla left stranded by decoding); decode Private-Use-Area offset glyphs where the offset is recoverable (e.g. `chr(c − 0xF700)`) and drop them where it is not; map a **curated allowlist** of known glyph-name leaks (`asper`→ayn `ʿ`, `lenis`→hamza `ʾ`, and `H####`/`Q##` font-internal codes → drop); normalize dotless-i. Each font-specific defect is isolated to one or two sources with disjoint glyph sets, so each transform stays a no-op on sources that lack it.
- **Small-caps letter-spacing repair (out of scope).** Small-caps rendering appears to insert spurious inter-letter spacing (e.g. `"I saw"`→`"Isaw"`), and this was projected as the one universal defect. Measured on the normalized trees, that projection was an artifact of pre-normalization double-spacing: after the whitespace transform runs, the residual is near-absent — zero in most books, and what remains is one book's front-matter cosmetics plus corrupted OCR-garbage tables. The dominant match in real prose is a legitimate article plus acronym (e.g. `a U.S. …`) that a merge would corrupt. No safe spacing-only repair exists, because a two-word small-caps run has identical spacing between its letters and between its words, so a length-gated merge concatenates across the word boundary. It is therefore **out of scope** for the normalization pass.

**Safety principle — curated allowlist, never a pattern strip.** Glyph-name repair matches only the specific leaked names on its allowlist; it must **never** strip slash-words as a class. Real prose contains legitimate slash-words in every corpus source — `and/or`, paired terms like `threat/opportunity`, URLs like `/reliefweb`, page-references like `/p111` — and a blanket `/word` strip would corrupt them. When a leaked name is not on the allowlist, the pass leaves the text unchanged rather than guessing.

**Explicitly out of scope (untouched).** Middle-dots (`·`, a legitimate notation), correctly-composed accents, and mathematical symbols are **not** normalization targets; the pass must not alter them.

### 7.5 Gold-set label sheet

`data/gold/label_sheet.xlsx`: **one row per chunk, one column per axis.** Columns: `chunk_id`, `source`, `section`, `chunk_text`, then one column per axis with **dropdown validation sourced from the codebook**, plus a `polities_touched` **pre-labeled, correctable** column that rides between the pre-labeled axes and the blind axes (after `empirical_scope`, before `claim_type`): it is pre-filled from the tagger's `polities_touched` list and corrected by the Academic where wrong, like the other pre-labeled columns; it is free-text, so it carries no dropdown, and it is not one of the four codebook dropdown axes — but it is a labeled field, not read-only provenance (Appendix I). Hybrid labeling per §9. The same sheet, once returned, is the machine-readable answer key for scoring — no transformation step between labeling and eval.

### 7.6 Gold-set delivery bundle

Once §7.5 has produced the sheet, `axial gold deliver` packages it into a self-contained handoff bundle for the Academic. Delivery is deliberately **local and offline**: no Drive, no email, no network. The bundle is a reviewable folder on disk.

- **Output folder:** `data/gold/delivery/<YYYY-MM-DD>/`, where the stamp is today's date in ISO form. The stamp is also the folder name.
- **Contents:** exactly three files, nothing else.
  - `label_sheet.xlsx` — a byte-identical copy of the generated `data/gold/label_sheet.xlsx`.
  - `README-for-academic.md` — human labeling instructions. Names the four axis columns (`field`, `empirical_scope`, `claim_type`, `theory_school`), states the blind vs. pre-labeled split per §9, and tells the Academic to return the filled sheet under `data/gold/labels/`.
  - `manifest.json` — machine-readable summary carrying: `sheet` (`"label_sheet.xlsx"`); `delivered` (the `YYYY-MM-DD` stamp, equal to the folder name); `chunk_count` (the number of labelable rows, the sheet's rows minus the header); `columns` (the label-sheet columns of Appendix I); `axes` (`["field", "empirical_scope", "claim_type", "theory_school"]`); `blind_axes` (`["claim_type", "theory_school"]`); `prelabeled_axes` (`["field", "empirical_scope"]`); `prelabeled_freetext` (the pre-labeled free-text columns the Academic corrects that are not codebook dropdown axes, `["polities_touched"]`); and `return_to` (the labels inbox, `data/gold/labels/`).
- **Idempotent per day:** re-running `axial gold deliver` overwrites the same dated folder in place, leaving no stale files — the folder holds exactly the three handoff files after any run.
- **Missing-sheet error:** running `axial gold deliver` with no generated sheet fails with a non-zero exit and a clear message telling the operator to run `axial gold sheet` first. No delivery folder is created in that case.

The bundle bridges build step 4 (emit the sheet) and step 5 (the Academic labeling pause) in §11: it is the offline handoff between them.

### 7.7 On-disk chunk artifact

The chunk stage (§5 stage 4) writes its prose chunks to disk as a cheap, inspectable artifact **before any LLM is called on them** — one JSONL file per source in `data/chunks/`, named `<source_id>.jsonl` and keyed by the same deterministic `source_id` used for the tree and envelope (`axial.envelope.compute_source_id`). One JSON object per line, one line per chunk, in section-then-position order. This artifact is the chunk stage's hand-off: tagging, artifact routing, cross-reference, and the vault writer all consume `data/chunks/<source_id>.jsonl` directly. The gold-sampling and eval flows are artifact-sourced but do **not** open `data/chunks/*.jsonl` themselves: the mandated invariant is that chunk boundaries are computed **once** by the chunk stage and **never re-derived** downstream, not that every consumer opens this file. Gold sampling reaches these chunks through the tagged vault prose (which carries each chunk's `text` and `chunk_id` verbatim from this artifact, joined with the tags its stratification needs); eval in turn reads gold's own sampled records.

Each chunk record carries at least:
- `chunk_id` — a stable, deterministic id of the form `<source_id>_<section order>_<section slug>_<NNN>`: no randomness, no timestamps, identical across re-runs on the same source bytes. This is the established `chunk_id` scheme; the redesign preserves it unchanged. The `section order` component keeps two distinct sections that share a heading from colliding.
- `section` — the section's own verbatim heading text (section-level provenance).
- `section_order` — the section node's `order` from the persisted structural tree (§7.4), which disambiguates repeated headings and lets a resume tell which sections are already persisted.
- `text` — the chunk's prose, a unit bounded into the two-sided size band `[min, max]` of §5 stage 4: **every record's `text` falls within the band** — no record exceeds `max` (so no single chunk can blow a request deadline or token budget downstream) and, save for the last chunk of a section or a section shorter than `min` in total, no record falls below `min` (a below-`min` chunk is merged into a same-section neighbour — its predecessor where the result stays within `max`, otherwise forward into its successor — never across a section boundary and never dropped; §7.8 / P0-4). Chunk size is measurable directly off this artifact, so the band is a testable property. The band is anchored on today's working chunk size (~1–3k characters).

Additional fields may be added (e.g. a character count) but the four above are the invariant contract. A block dropped upstream by the source router (apparatus — label-driven or content-detected, §7.8), a section skipped by the residual garble backstop, or an emitted candidate removed by the post-split fragment floor (§7.8, #193) contributes no chunk records; every such drop and its reason are recorded to the **router-owned skip record** — the single source of skip truth (§7.8), the generalization of the earlier per-source garbage-skip sidecar — so a reader can always distinguish a deliberate drop from a silent loss. Size never triggers a skip: a large but legitimate section is split into multiple in-band records, and a below-`min` chunk is merged into a same-section neighbour (§7.8 / P0-4), never dropped. An edited source (which yields a new content-hashed `source_id`) never reuses another source's stale artifact.

**Inspection (examine).** `axial chunk examine` reads the on-disk chunk artifact and reports chunk-quality stats with **zero LLM and zero embedding-model calls**: total and per-source chunk counts; the chunk-size distribution (min / max / mean / median), from which the two-sided band is verifiable before any LLM spend; a boundary-sanity summary — the count of chunks above `max` and the count below `min` (both expected to be zero under the band, modulo the section-tail exception), the count of sections split into multiple chunks, the count of sub-floor chunks merged into a same-section neighbour (§7.8 / P0-4) — a boundary change inspectable off the artifact with zero LLM spend — and the count of blocks the router dropped (apparatus, both label-driven and content-detected, plus any garble-backstop skips) with their reasons, read from the router-owned skip record (§7.8) — the single source of skip truth, not a per-pass guard; and an eyeball sample of chunk texts showing where boundaries fall. It runs entirely off the JSONL artifact, calls no inference or embedding model, and never mutates the artifact.

### 7.8 Routing decisions (source router)

At step 2b (§5), between structural extraction and the passes that consume the tree, a single **source router** classifies every tree block by its docling structural `label` (§7.4) into exactly one of three **routes**, and every downstream pass consumes that one classification rather than re-deriving a prose/non-prose decision. The router reads the persisted tree only and triggers no re-extraction. It calls **no model for the `label`→route mapping**; its one exception is a bounded per-block classification of content-flagged apparatus candidates (**Content-detected apparatus** and **Model-backed classification of flagged candidates**, below), which the overwhelming majority of blocks — all clean prose — never reach.

**Routes and the `label` → route mapping:**
- **prose** — `text`, `section_header`, `title`, and an in-body `list_item`. Routed to the chunk stage (§5 stage 4, §7.7). These are the only blocks that ever reach the chunk path.
- **artifact** — `table`, `picture`, `caption`. Routed to the artifact classification pass (§5 stage 5 / P0-5), which is their sole home; a `caption` attaches to its figure or table. Artifact blocks never enter the prose chunk path. (Note: `caption` is typed `prose` in the raw tree today and so leaks into chunking; routing reclassifies it to the artifact route so it no longer does.)
- **apparatus** — `document_index` (TOC / index), `footnote` (endnotes / footnotes), `page_header`, `page_footer`, and a `list_item` whose enclosing section is back-matter. **Dropped:** not chunked, not artifact-noted. Each drop is recorded with a reason.

**Founder decisions (charter #164):**
- Endnotes and footnotes are **dropped as apparatus** — not chunked and not sent to the artifact pass.
- Tables and charts **keep the artifact classification pass** — they route to the artifact pass (which adds `artifact_role`, provenance, and `cited_by`), not raw docling → vault. The pass adds role and provenance the raw block lacks, so bypassing it would lose information.

**`list_item` under back-matter.** A `list_item` is **prose by default**, so in-body lists are chunked; it is apparatus **only** when its enclosing section is back-matter (e.g. a bibliography or reference list rendered as list items). `document_index` already catches most TOC / index blocks; this rule covers the residual reference-list case.

**Unknown label fails open to prose.** A block whose `label` is absent, empty, or not in the mapping is routed to **prose**, never silently dropped. A misclassified block then surfaces as visible prose to be caught and corrected, rather than vanishing — the router never drops on uncertainty.

**Single source of skip truth.** Apparatus drops — both **label-driven** (the `label`→route mapping) and **content-detected** (the content arm above) — are recorded to the **router-owned skip record**, the generalization of the earlier per-source garbage-skip sidecar (§7.7), which now carries label-driven apparatus drops, content-apparatus drops, and any genuine-garble backstop skips, each with its own reason. This record is the one place a reader distinguishes a deliberate drop from a silent loss, and it is what `axial chunk examine` reads for its dropped-block report (P0-4b). The per-pass size/garble guard (`non_prose_skip_reason` — a `>30k chars` / `>40% non-alpha` heuristic formerly re-decided independently at each LLM entry in the tag, artifact, and cross-reference passes) is **demoted to a backstop** for genuinely garbled prose that slips type classification; it is no longer the primary prose/non-prose gate. It cannot see block *type*, which is why a clean TOC or a well-formed endnotes section sailed through it before routing existed.

**Post-split fragment floor (#193, generalized in #197).** The garble backstop above runs at the *section* level, on the joined body before the recursive splitter runs, so it cannot see a junk *tail chunk* a legitimate prose section leaves behind after splitting. A narrow floor closes that gap. After the chunk stage splits a section and applies the band guard (§5 stage 4), it drops an emitted candidate chunk — before the chunk is written to the artifact (§7.7) — when, and only when, the chunk is unambiguous non-content boilerplate of one of two shapes: (a) a **blank-page notice** — its text equals `this page intentionally left blank` after lowercasing and whitespace collapse; or (b) a **low-alpha fragment** — its **alphabetic ratio**, the count of alphabetic characters divided by the total character count, is below **the low-alpha threshold, currently 0.45**. The threshold is a tunable starting value proven via `axial chunk examine`, framed like the size band's `min`/`max`, not a magic number. This shape generalizes #193's zero-alphabetic-content rule, which is the ratio-0 special case: a fragment with only digits, punctuation, whitespace, or symbols (e.g. `6`, `200…`, `13).`) has ratio 0 and still drops, and citation and significance-star crumbs such as `∗ p < 0.` (ratio 0.12) or `Berman 1996: 78 ).` (ratio 0.33) now drop too. A blank-page notice is alpha-heavy — a high ratio — so shape (a) catches it, never shape (b). Each such drop is recorded to the router-owned skip record with its own distinct low-alpha-ratio reason, distinct from the apparatus and garble-backstop reasons, so it is a visible deliberate drop, never a silent loss. The floor acts **post-split, on individual emitted chunks**, not at the section level: the leaking crumbs are section *tails* whose parent section is legitimate prose, so a section-level filter never sees them.

**Genuine short prose is protected (#193).** This is a first-class invariant, not a side effect, and it stays primary. A chunk whose **alphabetic ratio is at or above the low-alpha threshold (≥ 0.45) is always kept**, however short — a real sentence such as `Yet, the U.S.` (ratio 0.62) or the interview quote `The Germans did not come to hurt us' (I25).` (ratio 0.66) survives. **Length alone never triggers a drop**, mirroring the "size never triggers a skip" principle (§7.7); only a low alphabetic ratio, or the blank-page shape, does. "Protected" means the chunk's **text** is never dropped — not that it survives as a **standalone chunk record**: a short sub-`min` chunk with a same-section predecessor is **merged backward** into it (§8 P0-4, respecting `max`), which preserves 100% of its text, so the sentence is still protected. The MIN-side section-tail exception keeps a sub-`min` chunk standalone **only** in the sole-chunk case — a section whose sole chunk is below `min`, with no same-section neighbour to merge into (§7.7, P0-4; reconciled with the §8 P0-4 predecessor-merge in #210, from the #207 rewrite). This protection (length never drops content) is the opposite of the fragment floor, which **drops** unambiguous junk regardless of merge. The threshold sits in a clean gap in the measured corpus: junk crumbs sit at ratio ≤ 0.33 and genuine short prose starts at ≥ 0.60, so 0.45 is mid-gap with roughly a 0.12 margin on either side. The stat-table and citation crumbs the earlier #193 floor left out of scope — significance-star splits like `∗ p < 0.` (0.12) and bare citations like `Berman 1996: 78 ).` (0.33) — are now **in scope**, dropped by the ratio test (generalized in #197). What stays out of scope is the **0.53–0.60 mid-band**: multi-citation crumbs interleaved with genuine quoted testimony that cannot be separated mechanically without false-dropping real content — the #193 trap — so the floor deliberately does not reach into it.

**Content-detected apparatus (the residual reference-list case).** The `label`→route mapping catches apparatus that docling *labels* as apparatus. It misses apparatus docling labels as plain **prose**: a reference list, bibliography, or endnote run mis-sectioned under a body heading (e.g. "Chapter Two", "Introduction") and emitted as `text`, so the `document_index` and back-matter `list_item` rules never see it. Heading and title matching cannot catch these — the heading lies — so only the block's *content* reveals it. The router therefore adds a **content arm**: a block the `label` mapping routed to prose is re-examined, and when it is **detectably reference / citation apparatus by content** — a dense run of bibliographic citations, e.g. inverted author-name entries ("Lastname, F. …") recurring past a threshold, and/or citation-list line structure — it is re-routed to **apparatus** and dropped like any other apparatus block, its reason recorded in the router-owned skip record with a distinct content-apparatus reason. The content arm is deliberately **conservative**: it fires only on high-confidence citation density, never on ordinary prose that merely cites a source or two in passing. It does not override the **unknown-label / never-drop-on-uncertainty** principle above: a block the content arm does not confidently identify as apparatus stays prose, so the router still never drops on doubt. Every content-apparatus drop preserves the invariant that no legitimate prose is silently dropped — each is recorded with its reason and is inspectable via `axial chunk examine` (§7.7, P0-4b) without LLM spend. This arm is **per-block**: it keys on citation density within a single block. A bibliography fragmented into one-citation-per-leaf nodes clears no single block's density threshold, so a separate **aggregate-across-descendants** signal is needed to catch it in the envelope's pre-chunk evidence selection (§7.3, #222); this per-block arm still catches the same apparatus downstream, once chunking aggregates its citations into one dense block.

**Model-backed classification of flagged candidates.** The content arm is two-stage so that clean prose never incurs model spend. First, a **cheap, deterministic pre-filter** — the citation-density signal above — flags candidate blocks; a block the pre-filter does not flag is never sent to a model and routes exactly as its `label` dictates. Second, **only the flagged candidates** are sent to a single, bounded classification call that returns one decision per block against the existing **prose / artifact / apparatus** taxonomy — the same spirit as tables / figures → artifact — resolving each flagged block to **apparatus** (drop, recorded in the skip sidecar with its reason) or **prose** (kept; reaches the chunk stage). This is the **only** point at which the router calls a model, and it is an explicit, bounded, per-block classification — not a free re-derivation of the tree — whose decision for each flagged block is recorded in the route / skip record. Because the pre-filter gates it, clean prose (every unflagged block) reaches the chunk stage with **zero** model spend, so the router keeps its model-free cost profile for the overwhelming majority of blocks. Reasoning is **ON** for this classification call (§7.9): the drop-or-keep decision is judgment-heavy and low-volume, so reasoning buys precision without a wall-clock cost.

**One shared classification.** The route is computed once and shared by every consumer (chunk, artifact, tag, cross-reference); no downstream pass re-derives the prose/non-prose decision. Whether the route is **persisted as an annotation on the tree** (§7.4) or **recomputed on read** from each block's `label` is an implementation choice — the contract **sanctions either** and does not mandate a persisted annotated tree; what it mandates is that all consumers share the one classification.

### 7.9 Per-pass model reasoning

Model **reasoning** (an extended chain-of-thought token budget on a call) is a **per-pass** setting, not a global switch. It was disabled globally after #147, when the `production_low` model pressed into service as a reasoner blew the wall-clock on the large tag / echo calls; that fix over-generalized, turning reasoning off even where judgment, not throughput, dominates. The contract restores it exactly where the decision is judgment-heavy and the call is small:

- **ON — structural-envelope pass (§5 stage 3 / P0-3).** The envelope's thesis / TOC / scope / stated-argument extraction is a single, once-per-source call whose metadata quality gates every tagged chunk downstream (#201); reasoning here pays for itself and does not scale with corpus size.
- **ON — content-apparatus classification gate (§7.8).** The drop-or-keep decision on a pre-filtered candidate block is judgment-heavy and low-volume (only flagged blocks reach it), so reasoning improves precision without a wall-clock cost.
- **ON — holdings-completeness check (§7.11 / P0-1b).** Same profile as the envelope: one call per source, over front matter only, deciding document kind and coverage. The acceptance bar is 0 false positives over 30 sources, so precision is the whole point and the volume is one call per ingested file.
- **OFF (unchanged) — the large, high-volume tag, artifact, and cross-reference calls.** These are the passes #147's wall-clock constraint was about; reasoning stays off for them.

The setting is carried per pass in the model configuration (`config/pipeline.yaml`, model-per-pass — §12); no pass hardcodes it, and turning reasoning on for one pass never turns it on for another.

### 7.10 Google Drive source contract

Sources are supplied by a Google Drive connector that streams the shared "Books" folder into the intake→extract pipeline. The connector is a first-class source provider: it enumerates the folder and pulls each file's bytes on demand, feeding the current intake→extract path (§5 stage 1, P0-11), with no operator-managed local staging step. Bytes may transit a temp/cache directory because docling needs a file path, but that cache is an implementation detail, not a staging contract.

**`[drive]` secrets.** Auth is a Google service account. `secrets/secrets.toml` carries a `[drive]` section, mirroring the existing `[openrouter]` pattern (§12, `secrets/secrets.example.toml`), with at least two keys: `service_account_json`, the filesystem path to the service-account JSON key file; and `books_folder_id`, the Drive folder id of the shared Books folder. The Books folder is shared with the service account's email out of band, so no interactive OAuth flow runs at connector time. Missing or incomplete `[drive]` secrets — an absent section, an absent or unreadable key path, or an absent folder id — raise a clear logged error and halt the connector before any network call. This is never a silent skip and never a partial run, mirroring the P0-1 intake reject discipline (§5 stage 1).

**File records returned by list.** The list operation returns a page of file records plus a `next_page_token`, and the connector paginates until the token is exhausted, so the enumeration covers the whole folder (P0-11). Each record carries at least: `id`, the Drive file id, which is the fetch-state key below; `name`, the filename, used for the `.pdf`/`.docx` filter and for provenance; `mimeType` or an equivalent format signal; and the change tokens `modifiedTime` and `md5Checksum`. The connector filters to `.pdf`/`.docx` candidates by name and mime type; final format and text-layer validation stays with P0-1 intake. The filter only narrows what is fetched, it does not replace intake's reject: a file that slips the name filter is still rejected at intake with a logged reason, so size or format never triggers a silent skip (§7.8, P0-1).

**Fetch-state manifest.** A persisted manifest records what has been fetched and ingested, keyed by Drive file `id`. Its location is `data/drive/fetch_state.json`, one manifest per run. Its shape is `id` → `{modifiedTime, md5Checksum, fetched_at}`: a change token per file. On re-run, a file present in the manifest whose listed `modifiedTime` and `md5Checksum` both match the manifest is skipped before download — its bytes are not pulled and it is not re-ingested. A file absent from the manifest, or whose change token differs from the manifest, is fetched. This pre-download skip composes with, and does not replace, the ingest-level `vault_status=OK` skip (P0-11b): the manifest saves the download plus the intake and extract work, the vault-status skip saves the downstream LLM work. The manifest is updated only after a file is successfully fetched and ingested, so an interrupted run re-fetches on the next pass rather than recording a false success. Observable: a second run over an unchanged folder fetches zero bytes and produces zero new sources.

**Language-gate tunables.** The English-only gate (P0-11c) detects language deterministically from a bounded text probe of the source, using a fixed-seed or otherwise deterministic detector (a `langdetect`- or `lingua`-style library, §12). It runs on every downloaded candidate, after download and before the source is handed to the ingest pipeline; intake's text-layer check (P0-1) runs later, inside that ingest handoff's extract stage, not before the gate. A probe that yields no detectable text — because the source is unparseable or carries no text layer — produces no language signal, and a no-signal probe is not a confident non-English verdict, so the gate does not reject it: such a source is passed through to the ingest handoff. The "never a silent pass-through" guarantee for a genuinely textless source is then held by the default ingest chain's intake check (P0-1), which rejects it with a logged reason before any docling conversion; a caller that injects its own ingest handoff owns that source's validation. Two tunables are stated here, not hardcoded magic constants, and are proven via inspection in the spirit of the chunk band `[min, max]` (§7.7) and the low-alpha threshold (§7.8): `language_probe_chars`, the size of the leading text probe drawn from the source in reading order, bounded large enough to detect reliably and small enough to stay cheap; and `language_accept_threshold`, the minimum detector confidence for the dominant detected language to be accepted as English. A source whose probe detects English at or above the threshold passes to the ingest handoff; a source whose probe is confidently detected as a non-English language, at or above the threshold for that language, is rejected before extraction and logged with a reason that names the detected language and confidence. A confidently non-English source is never silently passed (§5 stage 1, mirroring the P0-1 reject discipline).

**Injectable client (offline testability).** The Google Drive API sits behind a small injectable client protocol, roughly `list_files(folder_id, page_token) -> (records, next_page_token)` and `download(file_id) -> bytes`. The real implementation wraps the Google client library; the connector depends only on the protocol, so a test injects a fake that returns fixture records and fixture bytes, and no test touches the network. This is the same local-and-offline guarantee the gold-delivery bundle holds (§7.6, §11).

### 7.11 Holdings-completeness check

A **partial holding** is a source file that carries only part of the work it names: one volume of a multi-volume set, a truncated scan, an extract circulated as if it were the whole book. Two such sources sit in the current 30-source corpus. Nothing downstream detects them. The structural tree, the envelope, and the chunk artifact all describe the bytes that are present, faithfully, and say nothing about the bytes that are absent, so every later stage reports a partial holding as a healthy one. The check therefore belongs at intake (§5 stage 1), before extraction, and it reads the one artifact that still remembers the whole work: the source's own raw text layer.

The check reads **neither the structural tree nor the envelope**. That is load-bearing rather than incidental (see *Why not the tree*, below). It reads the raw text layer intake already builds for its text-layer check (P0-1), so the text costs nothing extra to obtain.

**The judgment is the model's.** An earlier design made the whole check deterministic — a printed-contents-page page-extent ratio, with a page-count-and-back-matter fallback for sources where no contents page was found. It was built, and it was measured, and it did not work. Recording why, so it is not rebuilt:

- **The document-kind distinction it could not make.** A research paper normally has no contents page at all. Neither does a chapter offprint. A rule keyed on the absence of a contents page cannot tell a complete paper from a truncated book, and the fallback arm therefore fired on `state-legitimacy`, a complete work: 2 true positives, **1 false positive**. Telling a paper from a book is a reading judgment, not a threshold.
- **The deterministic contents-page reader did not read contents pages.** Its entry matcher required dot leaders, which do not survive `pypdf` text extraction. It located **4 of 30** contents pages. Seventeen of the sources the design expected it to cover fell through to the fallback arm instead, and **26 of 30** sources in total were adjudicated by the arm the design had cast as the rare exception — the design inverted, the preferred signal becoming the scarce one. Those sources escaped false alarms only because their page counts exceeded the fallback's page ceiling, not because the fallback judged them. Three review rounds lifted the reader to **24 of 30**, with different membership than this document's earlier "21 of 30" figure — that figure is **corrected, not merely tightened**.
- **Tuning it toward the remaining cases makes it worse.** Widening the contents-region span far enough to reach `batatu`'s genuine five-page contents runs into its list of tables, where a line ending `…in Selected Years between 1963` parses as a page reference of 1963, collapsing the coverage ratio to 0.219 and firing falsely on a complete work. The obvious retune of a stated tunable produces exactly the failure the acceptance bar forbids.
- **Page furniture defeats literal matching.** `tilly`'s contents heading extracts as `viii Contents` — a running-header folio stitched onto the heading — which matches no literal `contents` rule. It scored clean only because the page ceiling protected it.

**Deterministic pre-processing, then one model call.** What is exact and cheap stays deterministic; what is a reading judgment goes to the model.

Deterministic, before the model sees anything:
- **Physical page count**, read from the file. This is the only reliable measure of how far the file actually runs.
- **Running header and footer stripping.** Lines that recur at the top or bottom of pages across the document — folios, running heads, running titles — are removed from the text before any of it is read for judgment. This is a **requirement, not an implementation detail**: it is what turns `viii Contents` back into `Contents`. A folio stitched to a heading must not survive into the text the model reads.

The model then makes **one judgment in one pass** over the cleaned front matter, plus whatever tail material the judgment needs. It is one judgment, not a set of independent signals scored separately, and it answers three things together:
- **What kind of document this is** — a book, a research paper, a chapter offprint, or a fragment.
- **What extent the document claims for itself**, where it states one: a printed contents page's last entry, a title page naming a volume of a set, a stated page range.
- **Whether the file covers that claimed extent**, given the physical page count.

**A research paper with no contents page is a normal, complete document and must not be flagged.** That distinction is the reason this check is model-adjudicated rather than deterministic; a paper is not a truncated book, and no threshold over page counts and back-matter density separates the two reliably.

**What the check produces.** A flag names what was concluded and carries the evidence for it, so an operator judges the finding rather than reading a bare boolean. The flag carries at least: the source it concerns; the **document kind** concluded; the **claimed extent**, where the document states one, with what stated it; the **observed extent** — the physical page count; and the **model's stated reason** for concluding the holding is partial. It **records its measurement**; it is never a bare boolean. A source judged complete produces no flag.

**What the check never does.** In v0 it **flags and reports only**. It never rejects a source, never halts intake, never repairs or re-fetches, and never alters what any later stage sees. A flagged source proceeds through extraction, envelope, chunking, tagging, and vault write exactly as an unflagged one does. This is deliberately unlike the P0-1 reject discipline: a missing text layer makes a source unusable, whereas a partial holding is usable and merely incomplete, and the call on what to do about it is the operator's.

**DOCX.** A DOCX file exposes no physical page count, so coverage against a claimed extent is not computable for it. The model can still read its front matter and tell a paper from a truncated book, so the check runs: it may flag a DOCX whose own front matter names it a part of a larger work (a volume, a stated page range the text plainly does not reach). It must not flag a DOCX for the absence of coverage evidence, since the evidence is unobtainable rather than damning. The earlier blanket DOCX exemption — no reading, no flag — is retired.

**Why not the tree.** Four candidate signals were proposed originally; a measurement pass over all 30 sources killed the tree-derived ones. Recording why matters, so they are not proposed again, and it holds for the model-adjudicated design exactly as it held for the deterministic one:
- **Printed TOC versus extracted tree cannot fire, by construction.** The router sends `document_index` to apparatus and discards its text (§7.8), and 198 such nodes corpus-wide carry no text. The envelope's `toc` is therefore a model reconstruction that truncates in lockstep with the tree it is reconstructed from. Measured, the two known truncated sources scored 0% missing while healthy sources scored up to 92%: the signal is inverted, not merely weak.
- **"Ends mid-sentence"** fires on 21 of 30 sources standalone and misses one of the two known instances entirely.
- **"An introduction with no subsequent chapters"** produces garbage on noisy and OCR'd trees.

Reading the raw text layer rather than the tree also keeps the check immune to the flattened and noisy-tree cases where tree-derived signals fail worst (Tilly, roughly 165 headings). That immunity is exactly what the rejected TOC-versus-tree signal lacked.

**The failure mode to watch.** No claim is made that this check degrades in a safe direction. An earlier version of this section asserted one, and it was false: routing a source from a primary signal to a fallback that fires on *absence* means degraded reading can produce a false alarm, not merely a miss (#282). The model-adjudicated check has its own version of the same exposure — a model can be confidently wrong about a document it read badly. There is no structural guarantee against it. What holds the line is the flag carrying its reason, so a wrong conclusion is visible rather than silent, and the corpus-level bar below, which is measured rather than argued.

**The bar is the contract; the mechanism is not.** Over the existing 30 sources the check flags exactly the two known partial holdings: **2 true positives, 0 false positives, 0 false negatives** (#267, #268). That bar is strict and it does not move. How the check reaches it — which prompt, which model, how much front matter and tail it reads — is free.

If the design needs a tunable at all it should be **at most a small number** of them, and they should be stated: plausibly the size of the front-matter window and the size of the tail window handed to the model. Their values are **to be set by measurement over the 30 sources**, not asserted here. No numeric threshold appears in this section that has not been measured.

### 7.12 Persisted source-metadata record

One JSON file per source at **`data/source_meta/<source_id>.json`**, keyed by the same deterministic `source_id` used for the tree (§7.4), the envelope (§7.3), and the chunk artifact (§7.7) — `{filename stem}-{first 12 hex characters of the sha256 of the source bytes}` (`axial.envelope.compute_source_id`). Written at intake (§5 stage 1), before extraction.

**Why it exists: it survives envelope regeneration.** The envelope is LLM-produced, nondeterministic, and regenerated routinely — the toc reconstruction rewrite (#235), the bounded re-ask (#241), a model trial, and more to come. Anything written into an envelope is therefore not a durable fact about the file; the next regen may change it, and a regen is a normal operation, not an incident. Facts about the *file* need a home a regen does not touch. Before this record existed, intake returned a metadata stub that was never persisted, and the only source-level metadata downstream could read was the envelope's — which is why the holdings flag (§7.11) had nowhere to live and reached no reader.

**What it holds.** Facts about the artifact:
- the **physical page count**, where the format exposes one;
- the **holdings flag** from §7.11, in full — the concluded document kind, claimed extent, observed extent, and the model's stated reason — or an explicit "no flag" for a source judged complete;
- the **file hash**, the full sha256 of the source bytes;
- the **bibliographic fields** read at intake: author, title, date (§7.13).

The file hash is already embedded in `source_id`, and storing it in full anyway is **deliberate**: the record should be self-describing, so a reader gets the hash by reading a field rather than by parsing the key and then discovering the key carries only a 12-character prefix.

**The boundary that keeps this from becoming a second envelope.** The rule is **the artifact versus the work**:
- **Here:** facts about the file as an artifact, obtained without interpreting the argument — byte hash, page count, format, and what the file's own front matter states about its identity and extent. A model may be used to *read* such a fact off the page (§7.11 and §7.13 both do); what makes the fact belong here is that it describes the artifact and does not change when the model is re-run against the same bytes.
- **The envelope:** what the model concludes about the *work* by reading its argument — thesis, scope, stated argument, reconstructed table of contents. These are interpretations, they are expected to improve as prompts and models improve, and their home is the artifact that gets regenerated.

Author, title and date sit on the artifact side of that line under §7.13, which is a move across the boundary and is intended: they are printed on the title page and stamped in the file's own metadata, and re-reading them does not depend on understanding the book.

**No source text.** Per DEC-23, this file carries no source text and no verbatim excerpts — not a title-page transcription, not a contents-page dump. It records values and short reasons. `data/` is gitignored, but the rule is about what the file contains, not where it lives.

The record is written once per source at intake and re-read, not recomputed, by later stages. Re-running intake on unchanged bytes yields the same `source_id` and overwrites the record with equivalent content; an edited source hashes to a new `source_id` and gets its own record, never inheriting a stale one.

### 7.13 Bibliographic metadata read at intake

`author`, `title` and `date` are read **at intake, from the PDF itself** — its embedded document metadata and its title page — and recorded in the source-metadata record (§7.12). They are not produced by the envelope LLM pass.

**What this replaces, and why.** Measured across the current corpus:
- `author` and `date` are **null in all 30 envelopes**, and both propagate into every vault chunk's `source_meta` — roughly 17,000 chunks advertising bibliographic metadata that is not there.
- `title` is **worse than null: it is fabricated.** In all 30 envelopes it is the filename slug, title-cased — `Mann Sources Of Social Power V2`, `Ugur Paramilitarism`, `Batatu Syrias Peasantry`. A wrong value that looks right is more dangerous than a blank, because nothing downstream can tell it from a real one. `title` is therefore in scope here even though the issue as filed (#278) named only `author` and `date`.

The #268 measurement pass established that `pypdf` reads front matter reliably enough to support this path on most sources.

**The filename is never a source for these fields.** Not for `title`, not for `author`, not for `date`. A filename is an operator's naming convention, not the document's self-description.

**Unavailable is recorded, and is distinguishable from not-yet-attempted.** This is the whole failure mode being fixed: today the hard case and the easy case produce identical output, so nothing downstream can tell "this book states no date" from "nobody looked". Each of the three fields is therefore in exactly one of three states in the record, and the states are distinguishable by reading the record:
1. **a value**, with a recorded **provenance** naming where it came from — the file's embedded metadata, or the title page;
2. **unavailable** — the read was attempted and nothing recoverable was found;
3. **not attempted** — no read has run for this source.

A value is never invented to avoid state 2. Embedded PDF metadata is often junk (a producer string, an empty author, a file-creation date that is not the publication date); a value that fails a plausibility read is recorded as unavailable, not passed through.

**Where these fields now live, and what happens to the envelope's.** There is one answer downstream, not two:
- The **source-metadata record (§7.12) is the sole origin** of `author`, `title` and `date`.
- The **envelope no longer carries them.** They are removed from its locked shape (§7.3), which becomes `{source_id, thesis, toc[], scope, stated_argument}`. This is a deliberate, founder-approved change to a previously locked shape, in the same spirit as the `toc` shape change (#235). It removes a field set the pass was never able to fill honestly: the envelope's own contract said no field is nullable, and the pass has been emitting nulls for two of these three on every source in the corpus.
- The vault's `source_meta` frontmatter block **keeps its five keys** (`author`, `title`, `date`, `thesis`, `scope`), so no downstream reader or note shape changes. The vault writer now composes it from two places: `author`, `title` and `date` from the source-metadata record, `thesis` and `scope` from the envelope. Where a bibliographic field is unavailable, the note records it as unavailable rather than as an empty-looking value indistinguishable from an unattempted read.

**The envelope's grounding guarantee is unaffected, and is strengthened.** §7.3 already forbids deriving `thesis`, `scope` or `stated_argument` from the title, the filename, or outside knowledge. Moving `title` out of the envelope removes the last reason the pass had to handle a title at all, so the envelope call reads source text and nothing else.

### Must-Have (P0)

**P0-1 Intake validation.**
- [ ] Accepts `.pdf` and `.docx`; rejects everything else with a logged reason.
- [ ] Detects absence of a text layer and rejects the file with a clear message.
- [ ] Given a scanned PDF, when intake runs, then the file is rejected and never silently passed downstream.

**P0-1b Holdings-completeness check (model-adjudicated, flag-only).**
- [ ] A check runs at intake on every accepted source and detects a **partial holding** — one volume of a set, a truncated scan, an extract circulated as the whole work (§7.11). It reads the raw text layer intake already builds (P0-1) and reads **neither the structural tree nor the envelope**. Observable: no tree or envelope file is read, and none needs to exist, for the check to run.
- [ ] **Deterministic pre-processing runs first.** The physical page count is read from the file, and **running headers and footers are stripped** from the text before any of it is read for judgment. Observable: on the `tilly` source, whose contents heading extracts as `viii Contents`, the text handed to the model carries the heading without the folio.
- [ ] **The judgment is one model call over the cleaned text** — the front matter plus whatever tail material the judgment needs — deciding together: the **document kind** (book / research paper / chapter offprint / fragment), the **extent the document claims** for itself where it states one, and **whether the file covers that extent** given the physical page count. It is one judgment, not separately-scored signals.
- [ ] **A research paper with no contents page is complete and is not flagged.** Observable: a complete research paper carrying no contents page passes with no flag. This distinction is the reason the check is model-adjudicated; no threshold over page counts and back-matter density separates a paper from a truncated book reliably.
- [ ] **Corpus-level accuracy — the bar, and it does not move.** Over the existing 30 sources the check flags exactly the two known partial holdings: **2 true positives, 0 false positives, 0 false negatives** (#267, #268). The mechanism reaching that bar — prompt, model, window sizes — is free; the bar is the contract.
- [ ] **The flag records its measurement**, never a bare boolean, so an operator judges the finding. It carries at least: the source; the **document kind** concluded; the **claimed extent** where the document states one, with what stated it; the **observed extent** (physical page count); and the **model's stated reason**. A source judged complete produces **no flag**.
- [ ] **Flag-only, never a reject.** The check never rejects a source, never halts intake, never repairs or re-fetches, and never alters what any later stage sees. Observable: given a flagged source, intake still succeeds and the source proceeds through extraction, envelope, chunking, tagging, and vault write exactly as an unflagged source does. This is deliberately unlike the P0-1 reject: a partial holding is usable but incomplete, and the call belongs to the operator.
- [ ] **DOCX.** The check runs on DOCX, which exposes no physical page count. It may flag a DOCX whose front matter names it a part of a larger work; it must **not** flag a DOCX merely for lacking coverage evidence, which is unobtainable rather than damning (§7.11).
- [ ] **Any tunable is stated and small in number**, plausibly the front-matter and tail window sizes, with values **set by measurement over the 30 sources** and not asserted in the spec. **No safe-direction-degradation guarantee is claimed**: the earlier one was measurably false (#282), and the flag's recorded reason plus the corpus bar are what hold the line instead.

**P0-1c Persisted source-metadata record.**
- [ ] Intake writes one JSON file per source at **`data/source_meta/<source_id>.json`**, keyed by the same deterministic `source_id` used for the tree, envelope, and chunk artifact (§7.12). It is written before extraction.
- [ ] It carries at least: the **physical page count** where the format exposes one; the **holdings flag** from §7.11 in full, or an explicit no-flag for a source judged complete; the **full sha256 file hash** (stored in full even though `source_id` embeds its 12-character prefix, so the record is self-describing); and the **author, title and date** read at intake (P0-1d).
- [ ] **It survives envelope regeneration.** Observable: regenerating a source's envelope leaves its source-metadata record byte-unchanged; deleting and regenerating the envelope does not lose the page count, the holdings flag, or the bibliographic fields.
- [ ] **Boundary rule.** The record holds facts about the **artifact** — obtained without interpreting the argument, and unchanged when a model is re-run against the same bytes. The envelope holds what the model concludes about the **work** (thesis, scope, stated argument, toc). A model may be used to read an artifact fact off the page without moving that fact into the envelope (§7.12).
- [ ] **No source text.** Per DEC-23 the record carries no source text and no verbatim excerpts — no title-page transcription, no contents-page dump; values and short reasons only.
- [ ] The holdings flag **reaches a downstream reader** through this record. Observable: a flagged source's flag is readable after intake without re-running the check.

**P0-1d Author, title and date read at intake.**
- [ ] `author`, `title` and `date` are read at intake **from the PDF itself** — its embedded document metadata and its title page — and recorded in the source-metadata record (§7.13). The envelope LLM pass does not produce them.
- [ ] **The filename is never a source** for any of the three. Observable: a source whose filename slug differs from its printed title yields the printed title, or `unavailable` — never the slug. This replaces the current behaviour, in which `title` is the filename slug title-cased in all 30 envelopes (`Mann Sources Of Social Power V2`).
- [ ] **Three distinguishable states per field**, readable off the record: a **value with recorded provenance** (embedded metadata, or title page); **unavailable** (read attempted, nothing recoverable); or **not attempted** (no read has run). Observable: a source whose date is genuinely unrecoverable is distinguishable from one that has not been processed. This is the defect being fixed — today `author` and `date` are null in all 30 envelopes, so the hard case and the unattempted case are identical downstream.
- [ ] **No value is invented to avoid `unavailable`.** Junk embedded metadata — a producer string as author, an empty author, a file-creation date that is not the publication date — is recorded as unavailable, not passed through.
- [ ] **One answer downstream.** The source-metadata record is the sole origin of these three fields; the envelope no longer carries them (§7.3). The vault's `source_meta` frontmatter block keeps its five keys (`author`, `title`, `date`, `thesis`, `scope`), composed from the record for the first three and the envelope for the last two, so no note shape changes and no re-tag is implied. An unavailable field is written as unavailable, not as an empty value indistinguishable from an unattempted read.

**P0-2 Structural extraction with fallback.**
- [ ] docling produces a hierarchical tree separating prose from non-text artifacts.
- [ ] On docling failure/degenerate output for a source, Unstructured runs as fallback for that source; the fallback is logged.
- [ ] The structural tree is written once per source (keyed by `source_id`) and read by later stages (not re-extracted); a source is re-extracted only when no persisted tree exists for its `source_id`.

**P0-2b Post-extract text normalization.**
- [ ] At tree-build time (stage 2), a deterministic, model-free normalization pass cleans each block's `text` before the tree is persisted. It alters no block's `label`, `type`, or `order` and does not change the tree's shape (§7.4); every downstream pass inherits the normalized text.
- [ ] Normalization is organized as independent transforms, each a no-op when its target defect is absent: a clean-font source passes through materially unchanged (only its `text` is eligible to change, and it does not).
- [ ] Whitespace (universal): soft-hyphens (U+00AD) are stripped, runs of whitespace collapse to a single space, and space-before-punctuation is removed.
- [ ] Glyph repair (font-specific, no-op when absent): detached combining marks (Unicode category Sk) are dropped or reattached; recoverable Private-Use-Area offset glyphs are decoded (e.g. `chr(c − 0xF700)`) and unrecoverable ones dropped; a curated allowlist maps known glyph-name leaks (`asper`→`ʿ`, `lenis`→`ʾ`, `H####`/`Q##` font codes → drop); dotless-i is normalized.
- [ ] Glyph-name repair is a curated allowlist, never a blanket `/word` strip: legitimate slash-words (`and/or`, `threat/opportunity`, `/reliefweb`, `/p111`) are preserved.
- [ ] Out of scope and left untouched: middle-dots (`·`), correctly-composed accents, and mathematical symbols.
- [ ] Small-caps letter-spacing repair is **not** performed by the pass: evaluated on the normalized trees, the defect is near-absent after the whitespace transform, and no safe spacing-only repair is possible because a two-word small-caps run concatenates across the word boundary under a length-gated merge — descoped (§7.4).

**P0-3 Structural-envelope pass.**
- [ ] One envelope JSON per source containing thesis, TOC, scope, stated argument.
- [ ] The envelope is written once and read by tagging (not recomputed).
- [ ] The envelope's locked shape is `{source_id, thesis, toc[], scope, stated_argument}`: `thesis` / `scope` / `stated_argument` are non-empty strings, `toc` a **non-empty list of `{title, children[]}` objects** (nested; each `title` a non-empty string, each `children` a possibly-empty list of strings), no field nullable, and no new field. `author`, `title` and `date` are **not envelope fields**: they are read at intake and live in the source-metadata record (§7.12, §7.13, P0-1d). Downstream is untouched — the vault's `source_meta` block keeps its five keys, now composed from both artifacts — and no re-tag is implied (§7.3).
- [ ] The pass never sends the model an empty or near-empty evidence block. When the intro / abstract / conclusion heading heuristic selects little or no text, input selection **widens to a substantive head-of-tree slice** — a bounded prose prefix in tree order — whose size is a stated tunable proven via inspection (§7.3). Observable: given a tree whose top-level headings match none of intro / abstract / conclusion, the assembled envelope evidence still carries substantive source text — the pass presents no empty section block.
- [ ] Envelope evidence for a matched section is the **full text of the selected sections** — the section's own prose plus its children's, not its children's alone (§7.3).
- [ ] A matched intro / abstract / conclusion section whose descendants are **overwhelmingly single-citation / bibliographic leaves** is detected by an **aggregate citation signal across the section's descendants** (not per-block density, §7.8) and **excluded from the matched-section evidence before the evidence-floor check**, so the pass widens to the head-of-tree slice and carries substantive body prose instead of the bibliography (§7.3, #222). The aggregate share that marks a section bibliographic is a stated tunable proven via inspection, and the detector is conservative — a section that merely cites sources in passing stays prose. Observable: given a tree whose matched intro / conclusion section is overwhelmingly single-citation bibliographic leaves (`data/trees/tilly-from-mobilization-to-revolution-*.json`), the assembled envelope evidence excludes that section and carries substantive body prose instead; given a normally-sectioned born-digital source, the assembled envelope evidence is unchanged.
- [ ] The head-of-tree widening slice proceeds in tree order but **skips a leading front-matter / apparatus prefix** (title page, copyright / ISBN, preface boilerplate) and begins at the first genuinely substantive body prose; the amount of prefix that may be skipped is a stated tunable, bounded so the skip can never consume the whole source (§7.3, #222).
- [ ] The `toc` is a **reconstructed nested `{title, children[]}` hierarchy** grounded only in **two signals** read from the cached tree (the front-matter-**inclusive** opening pages, including any printed TOC page, and the flattened detected top-level heading list), reconstructed within the same single envelope call (§7.3, #235). It carries genuine chapters / parts / sections and excludes subsection noise, OCR-garble, mislabelled body lines, and apparatus (index / bibliography / list of figures). It stays a **non-empty list**, with a deterministic fallback to the tree's detected heading list on reconstruction failure. The printed-TOC page is kept out of the thesis evidence (front-matter-skipped, above) yet still populates `toc` — the dual-role resolution. Observable: given the real Tilly tree (`data/trees/tilly-from-mobilization-to-revolution-*.json`), the reconstructed `toc` is a compact clean chapter hierarchy, not the ~165-entry flattened heading dump; given a clean born-digital control, the `toc` is unaffected.
- [ ] The extraction is **grounded by construction**: the prompt instructs the model to base `thesis` / `scope` / `stated_argument` only on the supplied source text, and not to infer from the title, filename, or outside knowledge (§7.3). Observable: the envelope prompt carries that grounding instruction.
- [ ] Model reasoning is **ON** for this pass (per-pass configurable, §7.9), and remains **OFF** for the high-volume tag, artifact, and cross-reference passes; the setting is carried per pass in `config/pipeline.yaml`, never hardcoded.

**P0-4 Chunking (recursive/structural, deterministic, LLM-independent).**
- [ ] Chunk boundaries are found by a **recursive/structural splitter** (#165, #191) — the sole chunk mechanism — that splits along the prose's separator hierarchy (paragraph → line → sentence → character), descending to the finer separator only when a piece still exceeds the band. The chunk critical path is deterministic and model-free: **zero embedding-model calls and no text-generating LLM call**.
- [ ] Every emitted chunk falls within a two-sided target size band `[min, max]`, enforced by a deterministic guard pass wrapped around the splitter's detected breakpoints — an observable property, since chunk sizes are measurable off the on-disk artifact (§7.7). MAX side: any chunk above `max` is recursively split at its next-best internal boundary, so no single unit can blow a request deadline or token budget, and a section larger than `max` (today up to ~143k chars) is split into multiple in-band chunks — never emitted whole, never skipped for size. MIN side: a chunk below the minimum-length floor `min` is **merged into a same-section neighbour — never dropped and never merged across a section boundary**. It merges into its **same-section predecessor** when one exists and the merged result would not exceed `max` (the MAX upper band is respected — a merge that would breach `max` is not performed); a sub-floor chunk with no eligible same-section predecessor merges **forward** into its same-section successor; a sub-floor chunk that is the section's sole chunk, with no same-section neighbour to absorb it, is **kept** as-is (the whole-section-shorter-than-`min` and section-tail cases remain below `min`, as before). `min` is a stated tunable, proven via `axial chunk examine` like the size band. This is a boundary change, not a skip — content is always preserved, size never triggers a drop (§7.7) — so it is consistent with the "size never triggers a skip" principle; the merge count is inspectable via `axial chunk examine` (P0-4b) with zero LLM spend.
- [ ] The chunk stage consumes a **prose-only routed tree** (§7.8): apparatus blocks (TOC / index, endnotes / footnotes, running heads) and artifact blocks (tables, figures, captions) are removed upstream by the source router and never enter the chunk path.
- [ ] Type-detectable non-prose is dropped by the router on structural `label`, not by the chunk stage; the residual high-non-alphabetic-ratio rule survives only as a backstop for garbled prose that slips type classification. A legitimate long section is split, not skipped — no legitimate prose is silently dropped, and every drop is recorded with a reason in the router-owned skip record (§7.8).
- [ ] The source router also drops **content-detected apparatus** (§7.8): a block docling labelled prose but that is a dense run of bibliographic citations (inverted author-name entries recurring past a threshold and/or citation-list line structure) is re-routed to apparatus and dropped, its reason recorded in the router-owned skip record with a distinct content-apparatus reason. The arm is two-stage — a cheap deterministic pre-filter flags candidates, and **only flagged candidates** are sent to a single bounded per-block classification call that resolves each against the prose / artifact / apparatus taxonomy (drop as apparatus, or keep as prose); clean prose (every unflagged block) reaches the chunk stage with **zero** model spend. The arm is conservative — it fires only on high-confidence citation density and never overrides the unknown-label / never-drop-on-uncertainty rule, so a block not confidently classified as apparatus stays prose. Reasoning is ON for this classification call (§7.9).
- [ ] A **post-split fragment floor** (#193, generalized in #197) drops an emitted candidate chunk, before it reaches the on-disk artifact (§7.7), only when it is unambiguous non-content boilerplate: a **blank-page notice** (text equals `this page intentionally left blank` after lowercasing + whitespace collapse) or a **low-alpha fragment** (**alphabetic ratio** — alphabetic characters divided by total characters — below the low-alpha threshold, currently **0.45**, a tunable starting value proven via `axial chunk examine`; this subsumes the earlier zero-alphabetic rule as the ratio-0 case). Measured off the artifact: **no emitted chunk is a blank-page notice or has an alphabetic ratio below 0.45**. Length alone never triggers the drop — any chunk with alphabetic ratio ≥ 0.45 has its text preserved, however short: a short sub-`min` chunk with a same-section predecessor is **merged backward** into it (§8 P0-4 MIN side), never dropped, and the §7.7 / P0-4 section-tail exception keeps such a chunk **standalone** only in the sole-chunk / no-same-section-neighbour case (reconciled with the predecessor-merge in #210, from the #207 rewrite) — and each fragment-floor drop is recorded with its own distinct low-alpha-ratio reason in the router-owned skip record (§7.8).
- [ ] Output chunks carry stable `chunk_id`s and preserve section provenance (verbatim section heading + section order).
- [ ] Chunk records are written to the on-disk artifact (§7.7) before any downstream LLM call, and are inspectable without LLM spend.
- [ ] The chunk stage reads the persisted structural tree only (it consumes no envelope) and makes no generative LLM call.

**P0-4b Chunk examine (inspection without LLM spend).**
- [ ] `axial chunk examine` reports chunk-quality stats from the on-disk artifact — total/per-source counts, size distribution (verifying the two-sided band), boundary sanity (chunks above `max`, chunks below `min`, sections split), and the count of sub-floor chunks merged into a same-section neighbour (§7.8 / P0-4) — making zero LLM and zero embedding-model calls.
- [ ] Its skipped/dropped-block report reads the **router's** decisions from the router-owned skip record (§7.8) — the single source of skip truth (label-driven apparatus drops, content-detected apparatus drops, any garble-backstop skips, and post-split fragment-floor drops (#193), each with a reason) — not a per-pass guard.
- [ ] Downstream tag, artifact, cross-reference, and vault stages consume the on-disk chunk artifact (§7.7).

**P0-5 Artifact classification & routing.**
- [ ] The artifact pass is the **sole home** of tables, figures, and captions and receives exactly the artifact-routed blocks from the source router (§7.8) — never raw docling output and never apparatus; a caption attaches to its figure or table.
- [ ] Each non-text artifact receives exactly one `artifact_role` from the taxonomy (Appendix D).
- [ ] Artifacts are written to the artifact pool, not embedded in prose notes.
- [ ] `discard`-tagged artifacts are retained in the pool but flagged non-retrievable.

**P0-6 Schema-driven tagging.**
- [ ] Tagger loads all axes/tags from the domain schema; no tag is hardcoded.
- [ ] Field = one primary + ≥0 secondary. Empirical-scope = exactly one value. Claim-type = one primary + optional secondary.
- [ ] A tag absent from the schema triggers a bounded correction re-ask showing that axis's controlled vocabulary; a tag still absent after that bounded re-ask raises a hard error (never a silent pass, never a code-side guess/normalization) — except `theory_school` (Appendix E), which soft-lands to the `unlisted` sentinel and logs the proposal for review instead of failing the source.
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
- [ ] `axial gold deliver` packages the emitted sheet into `data/gold/delivery/<YYYY-MM-DD>/` holding exactly three files — a byte-identical `label_sheet.xlsx`, `README-for-academic.md`, and `manifest.json` (§7.6). Re-running overwrites the same dated folder with no stale files. With no generated sheet it exits non-zero telling the operator to run `axial gold sheet` first and creates no delivery folder. Local and offline: no Drive, no network.

**P0-10 Eval harness.**
- [ ] Reads returned labels + tagger output, computes per-axis agreement.
- [ ] Reports per-tag application counts (to surface never-used tags) and disagreements (to surface inconsistent tags).

**P0-11 Google Drive source connector.**
- [ ] Auth is a Google **service account**: the connector reads the service-account JSON key path (`service_account_json`) and the Books folder id (`books_folder_id`) from a `[drive]` section in `secrets/secrets.toml`, mirroring the `[openrouter]` secrets pattern (§7.10, §12). Missing or incomplete `[drive]` secrets — absent section, absent/unreadable key path, or absent folder id — raise a clear logged error and halt the connector, never a silent skip (mirrors P0-1 reject discipline).
- [ ] Lists sources from the shared Books folder via `parentId` search with `pageToken` pagination, enumerating every page until the token is exhausted so the whole folder is covered.
- [ ] Filters listed files to `.pdf`/`.docx` candidates by name and mime type; **final format and text-layer validation is still delegated to P0-1 intake**, so a file that slips the filter is still rejected at intake with a logged reason. Size or format never triggers a silent skip (§7.8).
- [ ] **Streaming read**: each candidate file's bytes are pulled on demand and fed into the intake→extract pipeline, with no operator-managed local staging step. A temp/cache directory for docling's file-path need is an implementation detail, not a staging contract (§7.10).
- [ ] **Injectable client / offline test**: the Drive API sits behind a small injectable protocol (roughly `list_files(folder_id, page_token) -> (records, next_page_token)` and `download(file_id) -> bytes`); the real implementation wraps the Google client library, and the connector depends only on the protocol. Observable: a test injects a fake returning fixture records and fixture bytes, and no test touches the network (§7.10, the same offline guarantee as §7.6).

**P0-11b Incremental fetch-state.**
- [ ] A persisted **fetch manifest** keyed by Drive file `id` records, per fetched-and-ingested file, a change token — `modifiedTime` and/or `md5Checksum` — at `data/drive/fetch_state.json` (§7.10). The manifest is written only after a file is successfully fetched and ingested, so an interrupted run re-fetches rather than recording a false success.
- [ ] On re-run, a file present in the manifest whose change token is unchanged is **skipped before download** — not re-downloaded, not re-ingested. A file absent from the manifest, or whose change token differs, is fetched. This pre-download skip **composes with, and does not replace,** the ingest-level `vault_status=OK` skip (§7.10). Observable: a second run over an unchanged folder fetches **zero bytes** and processes **zero new sources**.

**P0-11c English-only gate.**
- [ ] Non-English sources are **rejected before the expensive extraction pipeline** and logged with a reason naming the detected language and confidence — never a silent pass-through (mirrors the P0-1 intake reject discipline).
- [ ] Language is detected **deterministically** from a **bounded text probe** of the source, using a fixed-seed or deterministic detector (a `langdetect`/`lingua`-style library, §12). The probe size (`language_probe_chars`) and the accept threshold (`language_accept_threshold`) are stated tunables proven via inspection (§7.10). Observable: a non-English source is rejected and logged and never ingested; an English source at or above the threshold passes.
- [ ] Interaction with P0-1: the language gate runs on **every downloaded candidate**, after download and before the ingest handoff; intake's text-layer check (P0-1) runs later, inside that handoff. A source whose probe yields **no detectable text** produces no language signal, which is **not** a confident non-English verdict, so the gate passes it through rather than rejecting it. A genuinely textless / no-text-layer source is then caught by the **default ingest chain's intake** (P0-1), which rejects it with a logged reason before extraction (§7.10).

### Nice-to-Have (P1)

- **P1-1** ~~Long-section handling: sections beyond a token threshold chunked across multiple calls with a coherence strategy (overlap window or recursive summary).~~ **SUPERSEDED by the P0-4 chunking redesign.** Deterministic long-section splitting was a band-aid on the LLM-echo chunker; the redesigned chunk stage (recursive/structural) bounds every unit by construction via its two-sided size band, dissolving the monster-section problem at its source. No longer live scope.
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
- Envelope reuse: tagging reads the stored envelope (verified: no recompute).

*Simulated labels (DEC-29) are a **provisional development signal only.** Eval may be run against an AI-simulated gold sheet during the academic pause to exercise the harness, but such a run never counts as the acceptance measurement — the real Academic-labeled gold set remains the instrument, and every provisional number is re-derived on real labels before promotion.*

**Lagging (post-v0):** reduction in re-ingestion churn on the full corpus; stability of the vocabulary across a second batch.

---

## 11. Build phases & the placeholder/pause seam

The config/data seam is the pause point. Because the tagger reads the codebook from a file, the build never blocks on the Academic.

1. **Scaffolding & schema loader** — repo per §6, schema/codebook loader, axes as config. *No Academic dependency.*
2. **Minimal ingestion** — intake → docling(+fallback) → envelope → chunking → vault write, on the **placeholder** Syria codebook (Appendices A–G), with sources streamed from the Google Drive connector (§7.10). *No Academic dependency.*
3. **Tagging + artifact routing + cross-reference.**
4. **Gold-set generation** — run 2–3 on ~20–28 sampled sources; emit the label sheet. *Produces the Academic deliverable.*
   - **4b. Delivery bundle** — `axial gold deliver` packages the emitted sheet into a dated, offline handoff folder (§7.6): the sheet copy, `README-for-academic.md`, and `manifest.json`. This is the concrete bridge across the pause seam — step 4 produces the sheet, delivery hands it off offline, step 5 is the Academic filling it.
5. **⏸ ACADEMIC LABELING** — Academic fills the sheet (hybrid, §9). *Pause here, continue building 6–7 on placeholder labels, or continue on **simulated** interim academic labels — an isolated, clearly-marked development path (`sim` namespaces only, torn down and re-run on real input before any promoted result; see DEC-29 and `docs/sim-academic/`).*
6. **Eval harness** — score, decide contested/candidate tags.
7. **Schema revision + second batch** — revise the schema from eval findings, re-run, compare. Only then consider the full ~120-source corpus (out of scope for v0).

---

## 12. Tech stack, dependencies & parked items

**Stack:** Python. **Parsing:** docling (baseline), Unstructured (fallback). **Intake-level PDF reading:** `pypdf`, for the physical page count, the raw text layer, the front matter the holdings check reads (§7.11), and the embedded document metadata the bibliographic read uses (§7.13) — this is separate from and upstream of the docling extraction path. **Inference:** API-based via OpenRouter and NVIDIA developer APIs; model-per-pass choice deferred (the envelope pass wants stronger reasoning; artifact routing wants a cheap model). Model **reasoning** is a per-pass setting (§7.9): ON for the structural-envelope pass, the content-apparatus classification gate, and the holdings-completeness check, OFF for the large tag / artifact / cross-reference calls. **Embeddings:** the chunk stage is model-free — its recursive/structural mechanism (§5 stage 4, §7.7) uses no embedding model and adds no embedding dependency (the earlier embedding-based semantic mechanism was retired per #191). **Source:** Google Drive shared "Books" folder (`parentId` + `pageToken`), via a service-account-authenticated connector (§7.10). This adds two dependency groups, both additive and both outside the chunk critical path: the **Google API client and auth libraries** (the `google-api-python-client` / `google-auth` family) that back the injectable Drive client protocol (§7.10, P0-11); and a **language-detection library** (`langdetect` or `lingua`-style) for the deterministic English-only gate (§7.10, P0-11c). Neither touches the chunk stage's model-free guarantee, which is unchanged. **Output:** Obsidian vault (markdown + YAML frontmatter).

**Parked (not built here):** the 26 Academic research questions become the Phase B brief backlog; keep them on file, do not action them in Phase A.

---

## Open Questions

Genuinely unresolved; everything else in this document is settled.

- **[data]** Codebook config format detail — confirm YAML (assumed) vs. JSON, and the exact loader interface. *Non-blocking; YAML assumed for the build.*
- **[data/academic]** Theory-school as its own axis vs. claim-type sub-tags vs. Phase-C-only scaffolding. *Deferred to the eval (§10).*
- **[data]** Agreement metric + survival threshold: raw agreement vs. κ, and the exact cutoff. *Starting hypothesis in §10; tune after first gold set.*
- **[engineering]** ~~Long-section chunking coherence across multiple calls (overlap window vs. recursive summary). *P1-1.*~~ *Resolved: obviated by the P0-4 chunking redesign, which bounds every chunk by construction via its two-sided size band (recursive/structural) — no multi-call long-section strategy is needed. No longer open.*
- **[engineering]** Post-run schema-change handling: grandfather existing notes vs. reprocess. *P2-3; deferred until the first schema change is needed.*
- **[architecture]** ~~Where a holdings-completeness flag (§7.11, P0-1b) lives once raised, and how it reaches a downstream reader; whether a persisted source-metadata record should exist independently of the envelope.~~ *Resolved by founder decision: yes. A persisted source-metadata record, one JSON per source at `data/source_meta/<source_id>.json`, written at intake and surviving envelope regeneration — see §7.12 and P0-1c. The flag lives there. No longer open.*

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
- `scope:country-case` **[FIRM]** — a specific polity; carries an additional `polity` field. Most of the Syria literature (Hinnebusch, Akdedian). The model supplies `polity` as free text: a non-empty string is required — a missing or empty value stays the hard error it is today — but the value is not validated against a fixed list. The schema's `polity_examples` are illustrations, not a closed menu: the tagger is instructed to name the true polity faithfully even when it is absent from the examples, historical, defunct, or supra-national (an empire, a mandate, a former union). Emitting a value outside the examples is the intended behaviour, not disobedience — consistent with the #77 free-text reality — and such values are accepted and logged as candidate additions, never fatal in v0. The field is named `polity`, not `country`, deliberately: a `country` field is a category error for an empire, a mandate, or a supra-national referent, whereas `polity` makes a non-nation-state referent a legal, honest value. A deterministic offline canonical normalization map (aliases plus historical polities folded to canonical referents), built from the run's collected verbatims, is applied downstream — no second LLM pass; non-fatal in v0. At the post-eval schema revision (§11 step 7) this becomes a living, operator-maintained normalization map applied downstream with graceful degradation, never a closed validation gate: canonicalization is applied to known verbatims, while any new or unmapped polity is always accepted and logged as a candidate for the operator to fold in over time, never rejected at tag time. Faithful naming at tag time is untouched.
- `scope:sub-national` **[TENTATIVE]** — a city, sub-region, single rebel group, or institution. Rule of thumb: if the claim generalizes to the country, tag `country-case`; if it is about the sub-national unit's distinctiveness, tag `sub-national`.

Rationale for the axis: a brief like "does Mann's infrastructural power apply to post-2011 Syria" must retrieve `capacity:infrastructural × scope:general` (Mann) and `capacity:infrastructural × scope:country-case:Syria` (Hinnebusch, Akdedian) *separately*, then synthesize. Without scope, both fall in one undifferentiated bucket.

**Polities-touched facet (prose chunks).** Separate from the empirical-scope axis, which stays single-cardinality aboutness. `polities_touched` is a many-valued list of every polity the chunk *substantively engages*, each a free-text value under the same faithful-naming and downstream-normalization rules as `polity` above. The bar is "engaged, not name-dropped": a polity earns a place only where the chunk reasons about it, compares it, or draws evidence from it — an incidental mention in passing does not qualify. A `scope:country-case` chunk names its case polity here too; a `scope:comparative` chunk lists all the cases it weighs. This facet feeds the Phase-B per-polity coverage map and cross-case filter-recall, which the single-valued scope axis cannot serve.

## Appendix D — Artifact-role axis (artifacts)

Cardinality: one value. Closed set.
- `case-study` **[FIRM]** — empirical/quantitative tables; structured evidence for a case or comparison.
- `framework-illustration` **[FIRM]** — conceptual diagrams expressing a framework visually.
- `quote-pool` **[FIRM]** — block-quoted primary-source material (interview excerpts, archival fragments, manifestos).
- `framework` **[FIRM]** — the author's own typologies/taxonomies/models. Sub: `framework:formal-model` for equations/formalisms.
- `reference-material` **[CONTESTED]** — glossaries, indexes, chronologies, maps (descriptive scaffolding). *Fold into `case-study` if these function as evidence in practice — the Academic decides.*
- `discard` **[FIRM]** — cover images and other retained-but-non-retrievable `picture` artifacts; retained in the pool but flagged non-retrievable. (Running heads and page numbers are **not** `discard` artifacts: they are `page_header`/`page_footer` apparatus, dropped by the source router (§7.8), so they never reach the artifact pool.)

## Appendix E — Theory-school axis (prose chunks) **[CANDIDATE]**

Provisional; kept-or-cut by the eval. Derived from the Academic's mind-map; orthogonal to claim-type (a `state-capacity` claim can come from a Bellicist *or* an Institutionalist school). Cardinality if kept: one primary + optional secondary. Grouped controlled vocabulary:

- **State:** `colonial-postcolonial`, `marxist-political-economy`, `cultural-ideational`, `bellicist`, `neo-bellicist`, `external-statebuilding`, `neo-marxist`, `modernization-developmental`, `institutionalist-state-centered`, `structuralist`, `state-in-society` (Migdal), `constructivist`.
- **Violence:** `opportunity-feasibility`, `constructivist-anti-essentialist`, `biological-evolutionary`, `structural-violence`, `civilizing-decline` (Eliasian), `state-centered-organizational` (Weberian/neo-Weberian, bellicist), `micro-sociological` (interactionist/situationist; micro-foundations, Kalyvas; micro-solidarity, Malešević), `interpretive-constructivist`, `marxist-critical-pol-econ`, `postcolonial-decolonial`, `criminological` (rational-choice, social-learning, traits, strain/anomie, routine-activity, feminist).
- **Ideology:** `materialist` (classical/neo-Marxism), `systematic` (structuralism, functionalism), `discursive` (post-Marxism, post-structuralism, discourse theory), `historical-sociological` (Mannheim; Malešević), `subject-centered` (identity-based, psychoanalytical).
- **None:** `not-applicable` — the chunk advances no theoretical position (tables, quantitative series, transitional narrative). An absence marker, not a school; excluded from the cross-field recurrence analysis below.
- **Open:** `unlisted` — a real theoretical school DOES apply to the chunk, but this vocabulary (derived from one expert's mind-map) does not yet cover it. Never a hedge: `unlisted` is only correct when a genuine school applies and none of the listed ones fit, and it must never be used interchangeably with `not-applicable` — conflating the two (e.g. laundering a real-but-unlisted school into `not-applicable` to avoid the sentinel) hides a genuine vocabulary gap instead of surfacing it.

The absence marker exists because the axis mandates a primary value. Without it, a chunk that carries no theoretical position leaves the tagger only two moves: fabricate an attribution, or emit an out-of-vocabulary value. `not-applicable` makes honest abstention a legal answer. This is not a hedge: where a school does apply, naming it is required.

Out-of-vocabulary `theory_school` is **not** source-fatal (unlike every other closed axis, §7.1/P0-6): a value still absent from the vocabulary after the bounded correction re-ask (§7.1) lands as `unlisted`, and the model's actual proposed name is logged to a persistent candidates queue (`data/tags/theory_school_candidates.jsonl`) with its source/chunk/section provenance, for an operator to review and, when warranted, promote into the controlled vocabulary. The vocabulary above was derived from a Syria-focused mind-map; a source outside that frame (e.g. a book on European/American state formation naming `pluralist` theories of the state) can legitimately invoke a real school this list does not yet cover — `unlisted` makes that an honest, non-fatal outcome instead of aborting the whole source over one axis's gap.

Note the deliberate cross-field recurrence (Malešević, Brubaker, Mann, Tilly appear under multiple fields) — this is the faceting pressure the eval should watch: if theory-school tags co-vary too tightly with field or claim-type, the axis is redundant and gets cut. `not-applicable` and `unlisted` are both excluded from this analysis — neither records a positioned school, and counting either would read as spurious recurrence. Each instead carries its own visible rate (an `unlisted` rate is itself a signal: a high rate means the vocabulary's frame has outgrown the corpus and warrants a deliberate revision pass, not a series of one-off promotions). Fabricated attributions would corrupt the same signal, which is the second reason the absence marker exists.

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
      scope:country-case: { polity: free_text }   # required non-empty; see Appendix C
  polities_touched:                                # separate facet, NOT part of empirical_scope
    applies_to: [prose]
    cardinality: many
    values: free_text   # every polity the chunk substantively engages ("engaged, not name-dropped"); see Appendix C
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
polity_examples: [Syria, Turkey, Lebanon, Iraq, Rwanda]   # known-corpus reference for logging/aliasing in v0, not a validation gate; at §11 step 7 these feed the operator-maintained normalization map applied downstream with graceful degradation, never a closed validation gate
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
empirical_scope: { value: scope:country-case, polity: Syria }
polities_touched: [Syria, Iraq]
theory_school: { primary: institutionalist-state-centered, status: candidate }
role_in_argument: role:claim
artifact_refs: [hinnebusch2001_tbl_02]
---
```

## Appendix I — Label-sheet columns

`chunk_id | source | section | chunk_text | field (pre-labeled) | empirical_scope (pre-labeled) | polities_touched (pre-labeled, free-text) | claim_type (blind) | theory_school (blind) | notes`

Dropdowns on the four axis columns are generated from `codebook.yaml`. Pre-labeled columns arrive filled with the tagger's guess for the Academic to correct; blind columns arrive empty. `polities_touched` is a **pre-labeled, correctable** free-text field: it arrives pre-filled with the tagger's guess (the raw polity strings, joined) for the Academic to correct where wrong. It is free-text, so it has no dropdown, and it is not one of the four codebook axes — but it is scored against the tagger the same way the pre-labeled axes are.
