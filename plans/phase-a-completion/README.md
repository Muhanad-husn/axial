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
the re-tag so the frozen corpus carries the right bibliographic facts.

| # | Issue | Goal |
|---|-------|------|
| 1a | [#278](https://github.com/Muhanad-husn/axial/issues/278) | `author`/`date` are null in all 30 envelopes and propagate empty into ~17k chunks. Populate them (P0-1d) or remove the fields so nothing downstream believes it has metadata it lacks. |
| 1b | [#284](https://github.com/Muhanad-husn/axial/issues/284) | Rebuild the holdings check as model-adjudicated (§7.11 rewrite / P0-1b): drop the six tunables, add running header/footer stripping + one reasoning-ON call over cleaned front matter. `src/axial/holdings.py` is currently spec-divergent. |
| 1c | [#285](https://github.com/Muhanad-husn/axial/issues/285) | Persisted source-metadata record (§7.12 / P0-1c): one JSON per source at `data/source_meta/<source_id>.json`, written at intake, surviving envelope regen — page count, holdings flag, full sha256, author/title/date. The durable home the holdings flag currently has nowhere to live. |

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
Sized so it needs **no full-corpus LLM run** (see Notes).

| # | Slice | Goal |
|---|-------|------|
| 5a | embedding pass | Net-new: embed every chunk once and persist the vectors. The v0 chunker is embedding-free by design (§7.5); this is a *different job* (distillation representation), not a chunking change. Cheap and one-time. |
| 5b | readiness map | HDBSCAN over **all** chunk embeddings (unsupervised — no LLM). Emit the readiness map: which tags sit in tight learnable regions vs. smear as noise; identify the `-1` noise set as the LLM-routed tail. Cluster ids start at 0 — the `-1`/route split is the load-bearing detail. |
| 5c | stratified teacher labels | LLM-label a **cluster-stratified ~6–9k** sample (not 17k): start ~6k, extend on the learning-curve saturation signal. Stratify by 5b's clusters so every dense region is represented — this is what makes generalization safe, not hopeful. |
| 5d | head classifiers | Light classifier head per graduated axis on frozen embeddings. A tag graduates only at parity with the teacher against the sim gold set (within noise). Abstention threshold per class; the confident fraction automates, the rest defers to the LLM. |
| 5e | outer eval | eval-02: quality-per-dollar of the hybrid vs the all-LLM baseline, referee = sim gold. Out-of-sample check: classifier predicts the untagged remainder, LLM spot-checks a few hundred (this is also the drift monitor). |

Verdict → if it proves out, it is **spec drift**: raise the build issues, founder
adjudicates, spec-author revises PRODUCT.md, TDD harness builds it. If it does
not, "stay all-LLM" is a successful, honest eval and Phase A still closed at
stage 4.

## Dependencies

- **Stage 0 is independent** and parallel to stage 1 (hygiene, no corpus touch).
- **Stages 1 → 2 → 3 → 4 are ordered.** 1 and 2 change corpus content, so both
  precede the stage-4 re-tag. 3 is the vehicle stage 4 runs on. 2a (#294) is a
  hard predecessor of stage 5 — the classifier trains on the vote labels.
- **Stage 5 depends on stage 4** for the frozen corpus + tag distribution, and on
  5a→5b→5c→5d→5e internally. 5b needs only embeddings (5a), not LLM labels.
- Nothing here depends on the Phase B (`sub:analysis-v0`) issues; that track is
  out of scope for this plan.

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

- **Why no full 17k LLM run is needed for stage 5.** "Full run" bundles two costs
  ~1000× apart. The unsupervised part (embed + cluster) is cents and runs on the
  whole corpus with no sampling loss. The supervised part (teacher labels) is the
  expensive one and needs only enough examples per *head* class: at the ~100–300
  floor, a cluster-stratified ~9k covers every class down to ~2–3% prevalence —
  which is where the head/tail line sits — and 17k buys almost nothing over it.
  The learning curve (train on 25/50/75/100% vs a fixed held-out set) decides the
  number empirically; start ~6k, extend only if the curve is still climbing.
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
