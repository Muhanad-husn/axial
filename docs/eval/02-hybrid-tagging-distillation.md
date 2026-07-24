# Eval 2 — hybrid-tagging distillation (cost axis)

**Status:** stages 5a–5e all shipped. 5e (issue #353), the outer quality-per-
dollar verdict, is measured and recorded below: **hybrid**, mixed by
construction (`empirical_scope` never graduated, #349) but a real win on the
four axes that did. This is a measurement/eval artifact only, same as every
stage before it — nothing here is wired into `axial.tag.run_tag`; whether to
actually build the hybrid tagger is separate spec drift for the founder to
adjudicate (DEC-32). Stages 5a–5b shipped first; 5d classifiers shipped for
the two blind axes (#351/#352) and the two dense-embedding axes, `field`
(#350) and `role_in_argument` (#348), both reconciled into one module
(`src/axial/distill/classify_embedding.py`). **5d (`claim_type`/`theory_school`, issues
#351/#352, DEC-37/DEC-38):** `src/axial/distill/classify.py` (`axial distill
classify claim_type|theory_school`) implements the ONE technique DEC-38
measured as beating dense embeddings for these two axes — `TfidfVectorizer`
(`max_features=20000`, `ngram_range=(1,2)`, `min_df=2`,
`stop_words="english"`) + `LogisticRegression(max_iter=2000)`, trained
directly on the corpus's own existing best-of-3 production tags (no fresh
LLM relabel needed, DEC-37), excluding the gold-sampled chunk_ids
(leakage-free) and any class with fewer than 6 training examples (too few to
learn a stable boundary). Evaluated against the independent gold sheet
(`data/gold/labels/label_sheet.xlsx`) — never against the tagger's own
labels — at full coverage and across a confidence-threshold sweep
(0.5/0.6/0.7/0.8), each threshold standing in for HDBSCAN's `-1` as the
automate/defer-to-LLM split. DEC-38's real-corpus measurement: full-coverage
accuracy 45.7% (`claim_type`)/47.4% (`theory_school`), both below the
teacher's own gold agreement (56.0%/54.3%); at `conf≥0.6`, accuracy-on-covered
climbs to 75.0%/70.0% at 27.6%/34.5% coverage — the confident subset clears
the teacher, the full set does not. The manifest
(`data/distill/classify_<axis>_manifest.json`) records the corpus-pin
provenance, the pinned config, train/gold chunk counts, dropped classes, and
the teacher's own gold agreement when `data/gold/labels/eval_report.json`
exists (loaded, never required). **This is a measurement/eval artifact
only** — like 5b's readiness map, it is never wired into
`axial.tag.run_tag` or any production tagging path; whether to build the
automate-if-confident path for real is separate spec drift for the founder
to adjudicate (DEC-32). The other stage-5d candidate axes
(`field_primary`/`role_in_argument`/`empirical_scope_value`) use a
different, already-measured technique (the embedding classifier, DEC-39) and
are not this module's job — a future slice per axis, not a generalized
multi-technique abstraction here. Not independently re-validated against the
real corpus/gold sheet by the builder session that shipped this slice (no
`data/` in a fresh worktree) — see the PR body.

**5d (`field`, issue #350, DEC-39):** `src/axial/distill/classify_embedding.py`
(`axial distill classify field`) implements DEC-39's own measured-best
technique for this axis — a plain multinomial `LogisticRegression`
(`max_iter=2000`) trained directly on the dense vectors 5a already persisted
(no re-embedding), reading `field_primary` straight from the LanceDB
metadata columns, gold chunks excluded. **Gold-column wrinkle:** the
original gold sheet's `field` column was a rubber-stamped copy of the
tagger's own pre-fill (DEC-37) — DEC-39 re-labeled this axis blind into a
new `field_gold` column, so this module reads `field_gold` for the
independent judgment and computes `teacher_gold_agreement` **fresh**, from
`field` (pre-fill) vs `field_gold` over the gold sheet's own rows — never
from `data/gold/labels/eval_report.json`'s `per_axis_agreement`, which for
this axis still holds the stale rubber-stamped 1.0. **Independently
re-validated against the real corpus** (junctioned `data/` into the builder
worktree — the previous slice's gap): `train_chunk_count=18290` (18,410
`field`-tagged chunks minus the 120 gold chunks), `dropped_classes=[]`
(`state`/`ideology`/`violence` all comfortably above the floor),
`full_coverage_accuracy=75.8%`, `teacher_gold_agreement=76.7%` (reproduces
DEC-39's cited figure exactly, confirming the fresh-computation fix is
correct) — at `conf≥0.6`: **78.0% accuracy at 83.3% coverage**, clearing the
teacher; DEC-39's own notebook run cited 79.0% at 87.5% coverage for the
same technique (a different one-off script, not this shipped module — the
two are close, both clear the teacher, and 78.0% sits inside DEC-39's cited
90% CI [72.3–85.3%]). Same manifest shape, same measurement-artifact-only
status, same never-wired-into-`axial.tag.run_tag` posture as 5d's other
modules.

**5d (`role_in_argument`, issue #348, DEC-39):** same module
(`src/axial/distill/classify_embedding.py`, `axial distill classify
role_in_argument`), same technique, same `AXIS_METADATA_COLUMNS` dict —
`role_in_argument` is already a flat column in the 5a metadata (no nested
`primary`, unlike `field`), and the gold sheet's answer-key column is
`role_in_argument_gold`. **Independently re-validated against the real
corpus** (same 18,410-chunk vault, 120-gold sample, junctioned `data/`):
`full_coverage_accuracy=49.2%`, `teacher_gold_agreement=None` (the real
gold sheet carries no plain `role_in_argument` pre-fill column for this
axis, only `_gold` — unlike `field`, so there is nothing to compare against;
DEC-39's cited 53.3% teacher-agreement figure is from the decision log's
earlier probe, not surfaced automatically by this manifest) — at
`conf≥0.6`: **63.9% accuracy at 50.8% coverage**, clearing that cited
53.3% baseline at every threshold checked (53.8%@75.8%, 63.9%@50.8%,
68.3%@34.2%, 81.3%@13.3%). **Noted plainly, not hidden:** this lands on a
different point of the coverage/accuracy curve than DEC-39's originally
published probe for this axis (57.3% at 62.5% coverage) — same technique,
same full-coverage number in the same ballpark, but not a bit-for-bit
reproduction of the earlier headline figure. This axis also has no
independent SELF/INTER reliability figure the way the blind axes do
(DEC-30), and 53.3% is itself a mediocre teacher baseline — treat this as a
real but weaker automate-if-confident candidate than `field`, not a settled
graduation call. Same manifest shape, same measurement-artifact-only
status, same never-wired-into-`axial.tag.run_tag` posture as 5d's other
modules.

**5a (issue #296): every
prose chunk in the frozen vault is embedded once (local sentence-transformer,
`sentence-transformers/all-MiniLM-L6-v2`) and persisted in a LanceDB vector
store (`data/distill/embeddings.lance`, `src/axial/distill/embed.py`,
`axial distill embed`), keyed by `chunk_id` with a flattened, filterable
metadata projection (`source_id` + each single-valued tag axis) — never
`chunk_text` (DEC-23). The embedding manifest
(`data/distill/embedding_manifest.json`) records the corpus-pin id and
`vault_snapshot_hash` this pass ran against; `axial.distill.staleness`
(`check_staleness`) is the small, reusable seam every later stage-5
artifact (5b's clusters, 5c/5d's classifiers) reuses to tell "still matches
production" from "corpus moved, re-derive."

**5b (issue #297): the readiness map.** `src/axial/distill/readiness.py`
(`axial distill readiness-map`) reads every persisted vector from 5a, over
zero LLM spend, and clusters them: L2-normalise (cosine geometry) →
standardise → **PCA** (`n_components=93`, deterministic `svd_solver="full"`;
UMAP stays notebook-only per DEC-35, never a production representation) →
**HDBSCAN** (`min_cluster_size=15`, `min_samples=5`,
`cluster_selection_method="leaf"`, `allow_single_cluster=True`). Every one
of these constants was measured directly against the real, frozen
18,410-chunk vault (not a synthetic guess) after the first version's pinned
defaults (`eom`, PCA=50) produced a degenerate 1-cluster readiness map —
`eom` (HDBSCAN's own implicit default) always collapses this corpus to
exactly one cluster regardless of PCA dims; `leaf` surfaces 17–42 real
clusters instead, which is the real driver of a usable readiness signal,
not PCA dimensionality. PCA=93 is the Kaiser criterion (eigenvalue > 1) on
the standardized embedding matrix. HDBSCAN's own `-1` label — never cluster
`0` — passes through unrelabelled as the LLM-routed noise tail; real
clusters start at `0`. The emitted `data/distill/readiness_manifest.json`
records the corpus-pin provenance (`axial.distill.staleness`), the pinned
config, and, per tag axis per tag value, the noise fraction (over the tag's
total chunk count) and the dominant-cluster id/share (over the tag's
non-noise chunk count only — a founder-approved redefinition, #358: under
`leaf`'s realistic ~90%+ corpus-wide noise rate, a share computed over total
count would make almost every tag unable to ever read "tight") feeding a
`"tight"` / `"noise"` readiness call (`DEFAULT_READY_DOMINANT_SHARE = 0.5`)
— plus the full `chunk_id → cluster_id` assignment 5c's cluster-stratified
sampling reads. Measured end to end on the real corpus: 41 clusters,
noise_fraction 0.927; `claim_type`/`theory_school` (the blind axes) surface
far more "tight" values (11/22, 15/30) than the head axes `field`/
`role_in_argument`/`empirical_scope` (0/3, 0/7, 1/5) — the density signal
finds the blind axes more separable in embedding space, the opposite of
what teacher-label-quality intuition might suggest; flagged for 5c/5d.
5c (stratified teacher labels) onward is not yet built.
**Depends on:** full 24-source re-run (tag distribution) + P0-10 gold set (referee).
**Subject doc:** the exploration this evaluates lives at
`docs/exploration/hybrid-tagging-classifier.md`.

**5e (outer eval, issue #353): measured, verdict `hybrid`.**
`src/axial/distill/verdict.py` (`axial distill tag-cost-probe`, `axial
distill drift-check`, `axial distill verdict`) combines the four already-
shipped 5d manifests, a live dollar-cost probe, and a drift-monitor dry run
into one `data/distill/quality_per_dollar_manifest.json`. Real numbers,
measured against the real corpus pin `sim-2026-07-23` (18,410 chunks,
120-chunk gold set), 2026-07-24:

- **Cost, live-measured, not modeled.** Issue #363/PR #367 shipped
  `estimate_cost` + a per-pass usage accumulator the day *after* the real
  production retag ran (2026-07-23), so there is no historical token log for
  that run. `tag-cost-probe` fires 10 real, non-gold vault chunks through the
  real production tag prompt against the real `deepseek/deepseek-v4-flash`
  model at `votes=3` (production's own config) and reads the real dollar
  cost back off the client: **$0.0015034/chunk** at votes=3 (146,982 prompt +
  3,212 completion tokens over 30 real completions). The structural saving
  this eval counts: `votes=3` exists *solely* to majority-vote
  `BLIND_AXES` (`claim_type`, `theory_school`, DEC-31) — every other axis
  already takes its first draw unvoted. Both blind axes graduate here, so a
  hybrid pipeline handing them to their classifiers has nothing left needing
  multi-draw voting; the remaining LLM call (still required every chunk,
  because `empirical_scope` never graduated, #349) drops to `votes=1` —
  **$0.0005011/chunk**, the real total divided by sample×votes, not an
  assumed 1/3 split. Extrapolated over the real corpus's 18,410 chunks (5a's
  own `embedding_manifest.json` chunk count): **$27.68 baseline vs. $9.23
  hybrid, a 66.7% dollar reduction** — conservative, since it still assumes
  the hybrid LLM call asks about every axis in one prompt (no dynamic
  per-chunk axis trimming for confidently-classified `field`/
  `role_in_argument`, which is itself production wiring, out of scope here).
  **Worth flagging plainly: the absolute dollars are small.**
  `deepseek-v4-flash` is cheap enough that one full-corpus tag pass costs
  ~$28 either way — the 66.7% reduction is ~$18 saved per full re-tag, not a
  budget-changing number at this corpus size. The saving is real and
  structural, but "worth building" should weigh $18/run against the ongoing
  cost of maintaining four classifiers (retraining on drift, monitoring),
  not just the percentage.
- **Quality, at the same `conf≥0.6` operating point every 5d manifest above
  already cites.** Per axis, `hybrid_accuracy = coverage × accuracy_on_covered
  + (1 − coverage) × teacher_gold_agreement` (the confident subset uses the
  classifier, the low-confidence tail falls back to the LLM, assumed to
  perform at its own overall gold agreement on that tail — a simplifying,
  explicitly-flagged assumption, not a fresh measurement of the tail alone):
  `claim_type` 61.3% vs. teacher 56.0% (measured); `theory_school` 59.7% vs.
  54.3% (measured); `field` 77.8% vs. 76.7% (measured); `role_in_argument`
  58.7% vs. 53.3% (**cited** — DEC-39's decision-log figure, not a fresh
  gold-column comparison; this module records the source as `"cited"`,
  never silently as `"measured"`). All four clear their teacher at this
  operating point — unweighted mean across the four graduated axes: **64.4%
  hybrid vs. 60.1% baseline**, i.e. the hybrid pipeline is not just cheaper
  here, it is *more* accurate on average, because the confidence threshold
  lets each classifier pass only its strongest predictions while ceding the
  rest back to the LLM. `empirical_scope` (#349, never graduated) is
  identical in both pipelines by construction and is excluded from this
  average for that reason, not omitted from the manifest.
  Quality-per-dollar ratio: **3.21×** (0.0698 hybrid vs. 0.0217 baseline,
  quality/$).
- **Drift-monitor dry run** (DEC-32/#296's own anticipated mechanism,
  exercised here for the first time): 25 non-gold corpus chunks (seeded,
  reproducible), each already-trained-on-the-corpus classifier's prediction
  compared against a **fresh**, single-draw LLM tag (today's model, not the
  historical cached tag the classifier trained on) — a dry run, not a
  production drift monitor, and deliberately far short of the issue's own
  "a few hundred" suggestion (DEC-32 already established no full-corpus
  all-LLM pass is needed for this eval; 25 is enough to see a gross signal,
  not a tight interval). One of 25 chunks hit a fresh-LLM parse error and
  was excluded (best-effort, not fatal). Agreement: `field` 79.2%,
  `theory_school` 79.2%, `role_in_argument` 50.0%, `claim_type` **45.8%** —
  notably the weakest, consistent with `claim_type` also carrying the
  lowest teacher-gold-agreement (56.0%) of the four; a single fresh draw
  naturally disagrees with a classifier trained on the historical
  best-of-3-voted label more often than the vote itself would. Not a gate on
  the verdict above (a dry run, per the issue) — a real, if noisy, first
  data point for whatever production drift-monitoring mechanism gets built
  later.

**Verdict, per axis (mixed, as expected going in):** `claim_type` **graduate**,
`theory_school` **graduate**, `field` **graduate**, `role_in_argument`
**graduate** (weaker margin, cited baseline), `empirical_scope` **stay-llm**
(#349, never graduated). Overall: **hybrid** — real, measured dollar savings
at real, measured quality parity-or-improvement on the four axes that
graduated. As with every prior stage-5 artifact, this is a measurement
artifact only: `verdict.py` is never called from `axial.tag.run_tag` or any
production tagging path, and building the real hybrid tagger — routing
`field`/`role_in_argument`/`claim_type`/`theory_school` through a classifier
in production, with real drift-retraining — is separate spec drift for the
founder to adjudicate, not decided by shipping this eval.

## Question

Does distilling the high-frequency (head) tags off the LLM onto a cheap classifier —
LLM as teacher, classifier as bulk labeller, LLM kept for the rare/contested tail —
save enough to justify the accuracy given up and the time+cost of the exploration
itself?

This is **not** a query-time synthesis eval. It is a cost-quality justification of the
hybrid tagger. It is inherently **comparative**: meaningless without the all-LLM
baseline to beat.

## Two layers

### Inner — the graduation decision (which tags to hand off)

Mechanism, lives inside the exploration. Tags graduate one at a time; a classifier is
only as trainable as its rarest class.

1. **Readiness map (OPTICS / HDBSCAN).** Density clustering shows which tags sit in a
   tight, learnable region vs. which smear as noise. The noise/outlier set — label
   **`-1`** in HDBSCAN/OPTICS, not cluster 0 — *is* the low-confidence tail routed
   back to the LLM. (Cluster IDs start at 0 for the first real cluster; the off-by-one
   here is a real train/route-split bug if missed.)
2. **Per-class example floor.** ~100–300 labeled chunks/class for a confident
   boundary; under ~50 is noise. Which tags have crossed ~100–200 instances?
3. **Learning-curve saturation.** Train on 25/50/75/100% of labels against a fixed
   held-out set; a flattened agreement curve means enough for that axis.
4. **Parity with the teacher.** Hand off a tag only when the classifier's agreement
   with the **gold set** is within noise of the LLM's own agreement with gold on that
   tag. Referee = P0-10 harness.

### Outer — the justification eval (was distilling worth it)

What earns the spend. Run the resulting hybrid pipeline head-to-head against the
all-LLM baseline on a held-out slice.

- **Metric: quality per dollar**, not raw accuracy — accuracy *given up* vs. tokens
  *saved*.
- **Verdict shapes:** hybrid ties baseline quality at a fraction of cost → proven.
  Hybrid loses accuracy the head tags can't afford → the exploration's honest answer
  is "stay all-LLM," and that is still a successful eval.

The inner layer says *what* to distill; the outer layer says *whether* distilling was
worth it at all.

**Measured (issue #353):** see the "5e (outer eval...)" paragraph above the
"## Question" heading for the real numbers — verdict `hybrid`.

## Cost model (from the exploration doc)

Per tag: `savings ≈ volume × LLM_cost/call × automation_fraction` vs.
`training + retraining_on_drift + accuracy_given_up`. Head tags carry almost all the
volume and the most training data, so automating the top handful captures most of the
saving. The recurring cost is **retraining on drift**, not training — so this is a
post-schema-freeze move.

## Open threads

- Held-out slice definition and how it relates to the gold frame.
- "Within noise" — the concrete parity threshold and its confidence interval.
- Whether per-cluster local classifiers beat one global head (the doc's instinct).
- LLM-as-oversampler for the tail: measure whether it actually grows trainable tail
  classes or just adds cost.
