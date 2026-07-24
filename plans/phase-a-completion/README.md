# Feature: Phase A completion — close the ingestion pipeline, on what we have now

The consolidating plan that finishes Phase A. It reconciles the open
`sub:ingestion-v0` tail, the tag-quality work (DEC-31), and the recorded
hybrid-tagging exploration into one dependency-ordered sequence, and pins the
operating assumption for building **now**: the AI-simulated academic path
(DEC-29/30/31) is the referee we build against; the real academic inputs
re-measure the same seams when they arrive, and the sim path is torn down first
(#295). Nothing here waits on the Academic.

- **Slug:** phase-a-completion
- **Created:** 2026-07-21
- **Status:** planned
- **New system?** no for stages 0–4 (they land against existing modules); yes
  for stage 5 (a new `src/axial/distill/` tree + the first embedding pass)
- **Project directory:** `.`

## Operating assumption — build on what we have

Phase A's referee is the gold set (P0-9/P0-10). We do not have the human
Academic's labels yet. Per DEC-29/30/31 the simulated academic path stands in:
the gold sheet is labelled in-harness (Sonnet-5, DEC-30), and every measurement
below reads against those sim labels. This is a **development signal only**. When
the real labels land we re-run the same eval and re-measure; the sim artifacts
(under `sim` namespaces) are discarded and the pipeline re-run on real input
(#295, DEC-29 mandatory teardown). Building against sim now is explicitly
sanctioned — it mirrors the exposure the human labelling already accepts, at
research-quotation scale.

Consequence for this plan: "Phase A done" is measured against the sim gold set.
The number is provisional by construction; the *mechanism* it validates is not.

## Where Phase A ends

Phase A = the ingestion pipeline (`specs/PRODUCT.md`, "Phase A Corpus Ingestion
Pipeline"), defined by P0-1..P0-11c + live P1 items. It is **done** when:

1. the remaining P0-divergent code is reconciled to spec (#284, #285, #278),
2. the tagger's blind axes are at their measured ceiling via best-of-N (#294),
3. the corpus is produced by one tested, resumable runner (#277) with a queryable
   run record (#270), and re-tagged clean,
4. that corpus scores against the sim gold set (P0-10) and the schema is frozen
   — the `theory_school` [CANDIDATE] is KEPT with best-of-N per DEC-31, pending
   confirmation on the corpus-wide numbers.

Stage 5 (hybrid distillation) is the closing **eval** that Phase A's scope
already covers ("the gold-corpus / evaluation loop"). Its *build* outcome —
ship the hybrid tagger or stay all-LLM — is a separate gated decision (spec
drift, founder-adjudicated), not a P0 gate. Phase A can close at end of stage 4;
stage 5 is the exploration that earns the next spend.

## Stages

Develop top to bottom. Stages 1–2 change what the corpus carries and how it is
labelled, so they land **before** any re-tag. One slice = one red-green-refactor
pass = one PR (except stage 0 hygiene, which is fix-lane where noted).

### Stage 0 — Clean the shop (no corpus change)

Independent hygiene; can run in parallel with stage 1. Makes metrics honest
before we touch the corpus.

| # | Issue | Goal | Lane |
|---|-------|------|------|
| 0a | [#291](https://github.com/Muhanad-husn/axial/issues/291) | Safe GC for orphaned derived artifacts — `data/chunks/` holds ~56 files against 30 live sources, so `chunk examine` over-reports. Identify orphans by `source_id`-not-in-`data/sources/`, confirm, remove, log. | slice |
| 0b | [#270](https://github.com/Muhanad-husn/axial/issues/270) | Structured run logging — `data/logs/<run>/run.jsonl` + `console.log` + `summary.md`; stdlib `logging` + a run-context helper, wired into `extract`/`envelope`/`tag`/`eval` first. Every later run in this plan writes a queryable record. | slice |
| 0c | [#289](https://github.com/Muhanad-husn/axial/issues/289) | Verify the gold-sheet `theory_school` dropdown includes `not-applicable` and `unlisted`; add the guard test. Verify-first — likely already correct. | fix |

### Stage 1 — Fix what each chunk carries (metadata correctness)

Every chunk's `source_meta` is wrong or thin until these land. They must precede
the re-tag so the frozen corpus carries the right bibliographic facts. Planning
(`plans/intake-metadata/`) turned these three into **one ordered feature chain**
— they are not independent, because author/title/date ownership couples them:

| Slice | Issue | Goal |
|-------|-------|------|
| 01 | [#284](https://github.com/Muhanad-husn/axial/issues/284) | Rebuild the holdings check as model-adjudicated (§7.11 rewrite / P0-1b): drop the six tunables, add running header/footer stripping + one reasoning-ON call over cleaned front matter. `src/axial/holdings.py` is currently spec-divergent. |
| 02 | [#285](https://github.com/Muhanad-husn/axial/issues/285) | Persisted source-metadata record (§7.12 / P0-1c): one JSON per source at `data/source_meta/<source_id>.json`, written at intake, surviving envelope regen — page count, holdings flag, full sha256, and **author/title/date (P0-1d) — this record is their sole origin.** Depends on 01 (carries the holdings flag). |
| 03 | [#278](https://github.com/Muhanad-husn/axial/issues/278) | **Resolved: remove, not populate.** The envelope's author/date being null in all 30 is fixed by *dropping* those fields from the envelope entirely — intake/source-meta (slice 02) owns them per §7.12's boundary rule, and the vault writer composes `source_meta` from both sources. Depends on 02. Does **not** re-tag the ~17k — that flush is stage 4. |

> **Note the change from the first draft of this plan:** #278 was sketched as an
> independent `envelope.py`-only Wave-1 slice ("populate *or* remove"). §7.13/P0-1d
> settle it as *remove*, which couples #278 to #285 — so it is now the last link in
> the intake-metadata chain, not a parallel slice. Rationale in
> `plans/intake-metadata/README.md`. Founder should sanity-check the remove call.

### Stage 2 — Fix how chunks are labelled (tag quality)

| # | Issue | Goal |
|---|-------|------|
| 2a | [#294](https://github.com/Muhanad-husn/axial/issues/294) | Best-of-N majority voting on the blind axes (`claim_type`, `theory_school`), N configurable per pass, default 3 (DEC-31). Lifts `theory_school` 0.76→0.92, self-repairs out-of-vocab draws. Resolve the abstention representation (distinct from `not-applicable`). **This produces the teacher labels stage 5 trains on** — it lands before the re-tag. |
| 2b | [#288](https://github.com/Muhanad-husn/axial/issues/288) | Report `not-applicable`/`unlisted` rates per source at run end — the operator's signal to promote a candidate school or reconsider the axis. Reads the candidates log. |

### Stage 3 — One tested, resumable runner

| # | Issue | Goal |
|---|-------|------|
| 3 | [#277](https://github.com/Muhanad-husn/axial/issues/277) | `axial run <pass>` — one in-process loop that drives any per-source pass with resume (one ledger, not today's three), per-source failure isolation, progress, and an end-of-run summary. Generalizes `run_ingest`; retires `data/logs/loop_worker.py`'s bare-`except` wrapper. This is P1-4, and it makes the stage-4 re-run reproducible instead of ad-hoc. |

### Stage 4 — Produce the frozen corpus + validate (**Phase A closes here**)

Not a coding slice — an operation, run through the stage-3 runner with stage-0
logging.

1. Re-tag the corpus end to end with stages 1–2 in place (best-of-N labels,
   corrected `source_meta`, model-adjudicated holdings).
2. Score against the sim gold set (P0-10 eval harness).
3. Freeze the schema: ratify the `theory_school` KEEP (DEC-31, 0.918 ≫ §10's
   ≥0.6 bar) on the corpus-wide numbers; confirm no other axis regressed.
4. Record the frozen tag distribution (per-axis class frequencies) — the input
   stage 5 reads.

At this point every P0 criterion is met against what we have. **Phase A is
complete.** A DECISIONS entry records the freeze and the provisional-on-sim
caveat.

### Stage 5 — Hybrid distillation eval (the closing exploration)

The recorded track: `docs/exploration/hybrid-tagging-classifier.md` +
`docs/eval/02-hybrid-tagging-distillation.md`. Runs **on top of** a done Phase A.
Sized so it needs **no full-corpus LLM run** (see Notes). Scoping decisions —
vector store, dimensionality reduction, embedding model, staleness tracking,
notebook tooling, issue decomposition — are settled in **DEC-35**, not left open
here.

> ⚠️ **Mechanism pivoted 2026-07-24 (DEC-37), after DEC-35's scoping and after
> #297/PR #358 was built and real-corpus-validated.** Density clustering
> (HDBSCAN, 5b) does not recover any of the five tag axes on this corpus's
> embeddings (Adjusted Rand Index ≈ 0, exhaustively measured — not a tuning
> gap). A direct supervised classifier trained on the corpus's *existing*
> tags (stage 4 already tagged all 17,824 chunks; no fresh LLM relabel
> needed) strictly beats every clustering variant tried. But internal
> accuracy against the tagger's own labels is **not** a valid stand-in for
> accuracy against gold: checked against the (still-simulated) 120-chunk gold
> sheet, the classifier underperforms the teacher on both blind axes it can
> be checked against (`claim_type` 39.7% vs. teacher's 56.0%; `theory_school`
> 41.4% vs. 54.3%). A follow-up TF-IDF baseline (**DEC-38**) — prompted by an
> external search that otherwise re-confirmed decisions already made here —
> found a narrower positive: at a confidence threshold, TF-IDF (not
> embeddings) automates ~28–35% of chunks on those two axes at accuracy that
> clears the teacher's own gold agreement (bootstrap 90% CI, ~35 gold-sample
> evidence base). A follow-up gold-labelling pass (**DEC-39**) extended the
> same independent check to the three head axes — `field` is the strongest
> candidate in the whole investigation (79.0% @ 87.5% coverage, at parity
> with the teacher's own 76.7%), `role_in_argument` is a real but weaker
> candidate (57.3% vs. teacher's 53.3%, wide overlapping CI), `empirical_scope`
> does not clear the bar with embeddings (59.1% vs. 64.2%; TF-IDF untried
> there). The table below reflects the corrected plan; the original
> HDBSCAN-gated design is kept only as history in TRACKER.md. Full reasoning
> and every number: **DEC-37**, **DEC-38**, **DEC-39**.

| # | Slice | Issue(s) | Goal |
|---|-------|----------|------|
| 5a | embedding pass + vector store | [#296](https://github.com/Muhanad-husn/axial/issues/296) ✅ merged | Net-new: embed every chunk once (local sentence-transformer) and persist in **LanceDB** — 5c/5d/5e all issue nearest-neighbour queries. The v0 chunker is embedding-free by design (§7.5); this is a *different job* (distillation representation), not a chunking change. Also defines the corpus-pin staleness manifest convention every later stage-5 artifact reuses. Cheap and one-time. **DEC-37 candidate follow-up (not filed):** swap `all-MiniLM-L6-v2` for `e5-base-v2` — small, consistent accuracy lift measured on a fair 4,000-chunk subset, at the cost of a larger model. |
| 5b | readiness map (**demoted: diagnostic, not a gate**) | [#297](https://github.com/Muhanad-husn/axial/issues/297) ✅ merged (PR #358) | HDBSCAN over PCA-reduced chunk embeddings. Correctly implemented and real-corpus-validated (Kaiser-criterion PCA=93, `leaf` selection, non-noise-share "tight" definition) — but DEC-37 measured ARI≈0 against every tag axis, so its role changes from "gates 5c's sample" to "documented negative result / future OOD-triage candidate." **5c no longer depends on it.** |
| 5c | stratified teacher labels (**redirected deliverable — done, DEC-39**) | [#347](https://github.com/Muhanad-husn/axial/issues/347) | Original scope (LLM-label a cluster-stratified ~6–9k sample) was unnecessary — the corpus was already fully tagged by stage 4. Redirected scope (extend the DEC-29/30 gold check to `role_in_argument`/`empirical_scope`/`field`) is now **executed**, not just proposed: four fresh Sonnet-5 subagents independently labelled all 120 gold chunks blind to the pipeline's own tag, persisted in `data/gold/labels/label_sheet.xlsx`. Close as complete rather than leaving open. |
| 5d | head classifiers, one issue per axis | [#348](https://github.com/Muhanad-husn/axial/issues/348) `role_in_argument`, [#349](https://github.com/Muhanad-husn/axial/issues/349) `empirical_scope`, [#350](https://github.com/Muhanad-husn/axial/issues/350) `field`, [#351](https://github.com/Muhanad-husn/axial/issues/351) `claim_type`, [#352](https://github.com/Muhanad-husn/axial/issues/352) `theory_school` | **Technique revised (DEC-37, refined DEC-38); all five axes now gold-checked (DEC-39).** A plain per-axis classifier (logistic regression measured; kNN comparable) trained on existing tags, PCA dropped, confidence-threshold abstention replaces HDBSCAN `-1` as the automate/defer split. **#350 (`field`) — the strongest candidate of all five**: gold-checked at parity with the teacher (79.0% vs. 76.7%) at 87.5% coverage. **#348 (`role_in_argument`) — real but weaker**: clears the teacher's point estimate (57.3% vs. 53.3%) but with a wide, overlapping CI on a noisy axis. **#349 (`empirical_scope`) — does not clear the bar with embeddings** (59.1% vs. 64.2%); a TF-IDF check is the one lever untried before ruling it out. **#351/#352 (`claim_type`/`theory_school`) — do not build a full-coverage classifier**; a TF-IDF automate-if-confident slice (~28–35% coverage) clears the teacher on a thin ~35-sample base (DEC-38). `polities_touched` still excluded (many-valued, not a single-class problem); region-grouping high-cardinality sparse categoricals is a validated technique (tested on `polity`, not a current target axis) worth reconsidering if a similar axis is ever added. |
| 5e | quality-per-dollar verdict | [#353](https://github.com/Muhanad-husn/axial/issues/353) | eval-02 quality-per-dollar vs the all-LLM baseline, referee = the ~120-chunk gold set (provisional-on-sim per DEC-29); out-of-sample spot-check = drift monitor. All five 5d axes now have a gold verdict (DEC-38/DEC-39) — ready to run once the founder decides which candidates to actually build. Verdict decides build vs stay-all-LLM, per axis. |

#347–#353 are sub-issues of the tracking issue **[#298](https://github.com/Muhanad-husn/axial/issues/298)**
(no longer taken as a PR directly — it was decomposed 2026-07-23 so 5c/5d/5e each
land as their own PR and 5d's five axes can run concurrently).

Verdict → if it proves out, it is **spec drift**: raise the build issues, founder
adjudicates, spec-author revises PRODUCT.md, TDD harness builds it. If it does
not, "stay all-LLM" is a successful, honest eval and Phase A still closed at
stage 4.

**Session-start protocol for stage 5 (mirrors stages 0–3's parallel-lane
pattern).** A session picking up stage 5 reads this file and `TRACKER.md`'s
status board, then runs `gh issue list` (or the GitHub plugin equivalent) scoped
to the open sub-issues under #298 to see which are still unstarted. Anything
whose dependency column above is already satisfied and that has no open PR is a
candidate for immediate dispatch; when more than one such issue exists (as with
5d's five axis issues once #347 lands), spin one worktree per issue and dispatch
them concurrently rather than serially — the same lane pattern used for stage
0's four feature lanes.

## Dependencies

- **Stage 0 is independent** and parallel to stage 1 (hygiene, no corpus touch).
- **Stages 1 → 2 → 3 → 4 are ordered.** 1 and 2 change corpus content, so both
  precede the stage-4 re-tag. 3 is the vehicle stage 4 runs on. 2a (#294) is a
  hard predecessor of stage 5 — the classifier trains on the vote labels.
- **Stage 5 depends on stage 4** for the frozen corpus + tag distribution, and on
  5a→5b→5c→5d→5e internally. 5b needs only embeddings (5a), not LLM labels.
- Nothing here depends on the Phase B (`sub:analysis-v0`) issues; that track is
  out of scope for this plan.

## Execution — parallel feature lanes & worktrees

One slice = one red-green-refactor PR through the harness. A worktree writes its
red outer acceptance test (already spec'd and DEC-1-locked in each slice plan),
drives it green, self-reviews, and stops at a **prepared PR** — merges stay
founder-approved (DEC-3), so worktrees never merge.

Planning refined the shape: three features are **ordered slice chains**, not
independent one-shot slices. So the unit of parallelism is the **feature lane** —
one worktree per lane, slices sequential inside it, lanes concurrent. Every slice
below now has a written plan; see the tracker's plan-ready column.

### Lanes — run concurrently, disjoint modules

| Lane | Slices (in order) | Owns | Plan |
|------|-------------------|------|------|
| intake-metadata | #284 → #285 → #278 | `holdings.py`, intake, `data/source_meta/`, `envelope.py`, `vault.py` | `plans/intake-metadata/` |
| tag | #294 | `tag.py`, `config/pipeline.yaml` | `plans/tag/06-best-of-n.md` |
| run | #277 core → ledger → sources+summary | new `run` module, `cli.py` | `plans/run/` |
| reconcile | #291 | new `reconcile.py`, `cli.py` | `plans/reconcile/` |

Four lanes, four worktrees — within the ≤3–4 concurrent cap (reviewer bandwidth is
the limiter, not file conflict).

### Serialize / fix-lane — not lanes

| Item | Plan / lane | When |
|------|-------------|------|
| #270 run-logging | `plans/run-logging/` (2 slices) | slice 01 (seam + `extract`) can go early; **slice 02 fans out into `envelope`/`tag`/`eval` — land it after the intake-metadata and tag lanes or it conflicts.** The one true serialization point. |
| #288 rates report | fix-lane | after run slice 03 (attaches to its end-of-run summary) |
| #289 gold dropdown | fix-lane | anytime (verify-first) |

### Cross-lane conflict notes

- **`cli.py`** is registered into by both `run` and `reconcile` (a subcommand group
  each) — different lines, low-risk, but sequence the two registrations if a rebase
  bites.
- **#270 slice 02** is the real conflict: it edits `envelope`/`tag`/`eval`, which
  the intake-metadata and tag lanes also edit. Land it after those lanes.
- Everything else is module-disjoint.

### Then, serial (not worktrees)

- **Stage 4** — re-tag via the #277 runner → score vs sim gold → freeze. Phase A
  closes here.
- **Stage 5** — a fresh set of worktrees (#296 → #297 → #298), gated behind stage 4
  and its two deferred decisions.

## Out of scope (whole feature)

- All `sub:analysis-v0` (Phase B) work: briefs, vault-query, retrieval loop,
  synthesis, validators, rung-3 gates, source-usage (#250–#266, #281, #290).
- The **build** of the hybrid tagger. Stage 5 is the eval that decides whether to
  build it; building it is a later, founder-adjudicated spec pass.
- Promoting any sim artifact. Sim labels are a development signal; teardown +
  real re-run is #295, deferred to when the app is stable and real inputs land.
- Any new tagging vocabulary. The schema freezes at stage 4; stage 5 distils the
  frozen vocabulary, it does not discover new tags (§4 non-goal 6 stands).

## Notes / open questions

> **DEC-37 supersedes the clustering-specific claims below** (the HDBSCAN
> readiness map, cluster-stratified sampling, and the PCA/UMAP framing as
> stage-5's load-bearing lever). Kept as history — the reasoning for *why*
> stage 5 was sized to avoid a full-corpus LLM run is still correct, it's just
> achieved differently now (existing tags, not a fresh cluster-stratified
> sample). See the stage-5 table above and DEC-37 for the current mechanism.

- **Why no full 17k LLM run is needed for stage 5 — even more true now.**
  "Full run" bundles two costs ~1000× apart. **As originally conceived**, the
  unsupervised part (embed + cluster) was cents and ran on the whole corpus
  with no sampling loss, and the supervised part (fresh teacher labels) needed
  only ~6–9k cluster-stratified examples. **As actually built (DEC-37):** the
  supervised part needs **zero** new LLM calls at all — stage 4's retag
  already tagged every one of the 17,824 chunks, so 5d trains directly on
  that. The saving DEC-32 argued for is larger than DEC-32 itself assumed.
- **The referee is the ~120-chunk gold set, not a full LLM baseline.** The outer
  eval is comparative against gold (LLM-vs-gold vs classifier-vs-gold), so no
  all-LLM pass over the corpus is required for it either.
- **Distillation will succeed unevenly.** It works best where the teacher is
  already sharp (`field` 0.97, `empirical_scope` 0.89) and worst on
  `theory_school` (0.73 intra-annotator ceiling, DEC-30) — a classifier cannot be
  cleaner than its teacher. The blind axes likely stay LLM + best-of-N; the head
  axes are the distillation candidates. Expect a hybrid, not a replacement.
- **Current-corpus savings are modest.** Most of distillation's value is the next
  ~90 sources, not the 30 we have. Read stage 5 as buying the proof + the trained
  model, not primarily as saving money on this corpus. It is a post-schema-freeze
  move by design (recurring cost is retraining on drift, not training).
- **DEC-23 across the whole plan.** No source text in any committed artifact —
  not in source-meta records (1c), not in run logs (0b), not in the readiness
  map or classifier metadata (5b/5d). Ids, values, and short reasons only.
- **Vector store — decided (DEC-35): LanceDB.** Embedded/local, no server
  process, native metadata-filtered ANN, deterministic file persistence. Serves
  all three stage-5 nearest-neighbour mechanisms (LLM-as-oversampler, 5e's
  drift monitor, `-1` triage) and likely Phase B's retrieval loop (#253/#254)
  too — still net-new infra crossing v0's embedding-free boundary (§7.5), built
  at 5a (#296).
- **Feature engineering — decided (DEC-35): PCA for every production artifact,
  UMAP notebook-only.** Reduction is load-bearing, not cosmetic: HDBSCAN
  degrades in raw high-dim embedding space, so density clustering needs a
  reduction step first, and cleaner features saturate 5c's learning curve
  sooner. PCA is deterministic and pins cleanly, matching every other stage's
  reproducibility contract; UMAP produces better-separated clusters but is
  stochastic even seeded across library versions, so it is used only inside
  5b's notebook to *look at* cluster structure — never as the array a
  classifier or HDBSCAN actually trains on. L2-normalisation + standardisation
  precede reduction. Whether clustering (5b) and classification (5d) end up
  wanting different PCA dimensionality is a 5b/5d measurement, not decided here.
- **Embedding model — decided (DEC-35): local sentence-transformer.** No
  embedding client exists in `llm.py` today. A small CPU-friendly encoder is
  deterministic, has zero per-call cost at ~17k–80k chunks, and doesn't depend
  on the configured OpenRouter models exposing an embedding endpoint. Not the
  same "no local model hosting" concern as the LLM tagger (§4 non-goal 3 is
  about a local *generative* model).
- **Reproducibility / corpus-state staleness — decided (DEC-35): extend
  corpus_pin (#248), don't invent a parallel mechanism.**
  `src/axial/eval/corpus_pin.py` already hashes exactly what stage 5 needs to
  key artifacts on — `vault_snapshot_hash` (a sha256 over every
  `(chunk_id, tags)` pair, so it moves whenever corpus size/composition/tag
  distribution moves), per-source `content_hash`, and `ingest_code_sha`. Every
  stage-5 artifact (embedding manifest, cluster assignments, each trained
  classifier) records the pin id/hash it was built from; a `check-staleness`
  operation recomputes the current pin and diffs it, so an operator can tell
  "this still matches production" from "corpus moved, re-derive" without
  guessing. Defined once, at 5a, where the first artifact exists.
- **Notebook / visualization tooling — decided (DEC-35): new `distill`
  dependency group.** `pyproject.toml` had no `jupyter`/`ipykernel`/
  `matplotlib`/`plotly` before this scoping pass. Stage 5 is classical
  data-science work, not just pipeline code — embedding projections, HDBSCAN
  persistence/size/`-1`-share, the readiness map, teacher-label sample
  composition, per-axis confusion matrices, and quality-per-dollar comparisons
  all need a look-and-tune surface before a classifier locks in. Lives in its
  own group, not `dependencies` (not runtime pipeline) and not `dev` (not CI
  tooling), alongside the new runtime deps (`sentence-transformers`, `lancedb`,
  `scikit-learn`, `hdbscan`, `umap-learn`).
