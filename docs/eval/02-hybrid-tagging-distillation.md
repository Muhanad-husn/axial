# Eval 2 — hybrid-tagging distillation (cost axis)

**Status:** foundation stub, stage 5a shipped. **5a (issue #296): every prose
chunk in the frozen vault is embedded once (local sentence-transformer,
`sentence-transformers/all-MiniLM-L6-v2`) and persisted in a LanceDB vector
store (`data/distill/embeddings.lance`, `src/axial/distill/embed.py`,
`axial distill embed`), keyed by `chunk_id` with a flattened, filterable
metadata projection (`source_id` + each single-valued tag axis) — never
`chunk_text` (DEC-23). The embedding manifest
(`data/distill/embedding_manifest.json`) records the corpus-pin id and
`vault_snapshot_hash` this pass ran against; `axial.distill.staleness`
(`check_staleness`) is the small, reusable seam every later stage-5
artifact (5b's clusters, 5c/5d's classifiers) reuses to tell "still matches
production" from "corpus moved, re-derive." 5b (readiness map) onward is not
yet built.
**Depends on:** full 24-source re-run (tag distribution) + P0-10 gold set (referee).
**Subject doc:** the exploration this evaluates lives at
`docs/exploration/hybrid-tagging-classifier.md`.

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
