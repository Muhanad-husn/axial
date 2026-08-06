# Exploration — hybrid LLM + classifier tagging (cost at scale)

**Status:** exploration only. No code, no tests, no issues yet. This note captures a
direction to evaluate *after* the full corpus re-run completes. If the study proves
the possibility is real, it becomes spec drift and is raised as issues for the
founder to adjudicate — not built off this note.

## The idea

v0 tags every prose chunk with the LLM against the gold-validated schema. That is
correct and stays correct: per `specs/PRODUCT.md` §9–§10 the gold corpus is a
**measurement instrument** (an answer key that scores the tagger and decides which
contested tags survive), not training data, and embedding-clustering vocabulary
discovery is an explicit v0 non-goal (§4, Non-goal 6).

At corpus scale the LLM tag call becomes the dominant recurring cost. The
exploration: distill a **hybrid** tagger. The LLM is the teacher; a cheap classifier
takes over the high-frequency (head) tags where it can match the teacher; the LLM
keeps the rare, contested, and out-of-distribution tail. "AI is great, but resources
are greater" — automate the confident bulk, defer the rest.

## Trigger

Run this study **after the full cold re-run on all sources completes**. Scope is now
**24 sources** (the original 22 + 2 new) and is expected to produce a **larger**
corpus than the wound-down run's 13,175 notes — the two added sources outweigh the
new harness's back-matter/quarantine trimming.

The 6-source canary run (the `#121` pipeline-ready gate) is **not** the trigger. Tag
distribution can only be read off the full corpus, not a readiness subset.

## When is there enough to distil? (per-tag, not per-corpus)

A classifier is only as trainable as its rarest class, so tags graduate one at a
time — never the whole tagger at once. Three signals, in increasing order of trust:

1. **Per-class example floor.** On top of frozen embeddings, ~100–300 labeled chunks
   per class gives a confident boundary; under ~50 is noise. First filter: which
   tags have crossed ~100–200 instances?
2. **Learning-curve saturation.** Fix a held-out set, train on 25/50/75/100% of
   available labels, plot agreement vs. size. A flattened curve means enough for that
   axis; still climbing means not yet.
3. **Parity with the teacher.** A tag is ready to hand off when the classifier's
   agreement with the **gold set** is within noise of the LLM's own agreement with
   gold on that tag. This reuses the P0-10 eval harness as referee.

## How (where the OPTICS/per-cluster instinct fits)

- **Representation:** a good text embedding of the chunk, then a light classifier
  head. No training from scratch, no local model hosting (§4, Non-goal 3 stands).
- **Clustering as diagnostic + decomposition, not labeller.** Density clustering
  (OPTICS / HDBSCAN) shows which tags occupy a tight, learnable region vs. which are
  smeared as noise — a readiness map. Its explicit "noise" points are exactly the
  low-confidence tail to route back to the LLM. Per-cluster local models give each a
  cleaner, more balanced sub-problem than one global model on skewed, multi-modal
  text.
- **Imbalance levers, ranked for this system:**
  1. **LLM as free oversampler for the tail** — find chunks near a rare tag by
     embedding similarity, run the LLM on them, manufacture minority examples on
     demand. The luxury normal imbalanced-learning doesn't have; use before SMOTE
     (which is weak on high-dim embeddings).
  2. Class weighting / focal loss over synthetic resampling.
  3. **Abstention.** A calibrated per-class confidence threshold turns imbalance from
     an accuracy problem into a coverage problem: automate the confident fraction,
     defer the rest. This is what makes the hybrid safe.

## Economics and the hidden cost

- Per tag: `savings ≈ volume × LLM_cost/call × automation_fraction` vs.
  `training + retraining_on_drift + accuracy_given_up`. Head tags carry almost all
  the volume and have the most training data, so automating the top handful captures
  most of the savings — the economics and the trainability point the same way.
- **The recurring cost is retraining on drift, not training.** A new country, shifted
  emphasis, or schema change invalidates the classifier. So this is a
  **post-schema-freeze move**: only once the vocabulary stops moving does the
  classifier's shelf life exceed its training cost. Keep the LLM on a small live
  sample as a drift monitor — falling LLM-vs-classifier agreement on fresh chunks
  signals it's time to retrain.

## Expected shape of the result

The harness makes the corpus cleaner but does not grow the tail, so the likely read
is: **head tags are classifier-ready, tail stays on the LLM**, with LLM-as-oversampler
the only lever that grows the tail. A hybrid, not a replacement.

## If it proves out

The change touches the tagging pipeline and schema handling, so it is **spec drift**:
raise issues, the founder adjudicates, the spec-author revises `specs/PRODUCT.md` in a
deliberate spec pass, then the TDD harness builds it. Nothing here shortcuts that.
