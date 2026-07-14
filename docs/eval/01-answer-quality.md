# Eval 1 — answer quality (output axis)

**Status:** foundation stub. Approved in essence; design to be deepened.
**Depends on:** full 24-source re-run (rich corpus) + academic-authored hard cases.

## Question

Given a hard analytical query against a rich corpus, is the product's answer correct,
well-supported, and grounded in the right sources?

## Why "hard cases against a rich corpus" is the honest bar

- Retrieval quality only manifests at corpus scale — distractors, near-duplicates, and
  cross-source synthesis only exist when the vault is rich. So the full re-run is a
  precondition for this eval to mean anything.
- The academic authoring the cases removes self-grading bias: they write the question
  and can adjudicate a good answer.
- Anti-Üngör: no softballs the system can already answer (the #115 postmortem mistake).

## Adjudication contract (to settle)

Per case, one of:

- **Expected answer + required citations** — the answer the system should give and the
  source passages it must rest on. Judge scores both correctness and grounding.
- **Rubric** — for open questions with no single answer, a scored checklist of what a
  good answer must contain.

Open: which format, or a mix keyed by question type. A bare question is not an eval.

## Judge

LLM-as-judge, anchored to the academic's expected answer. Constraints:

- Consider a **different model family** as judge to avoid family self-grading.
- Spot-check **judge-vs-academic agreement** on a sample before trusting the judge at
  scale.
- Score dimensions separately: factual correctness, citation grounding, completeness.

## Corpus pin (shared format — owned here)

All of `data/` is gitignored (DEC-23), so the pinned corpus is a manifest, not a
commit. Minimum fields:

- **Source list** — the 24 sources, each with a content hash of the ingested input.
- **Ingest-code SHA** — the commit the pipeline ran at.
- **Vault snapshot hash** — a hash over the produced notes (chunk_ids + tags, never
  chunk_text, per DEC-23).

Reused by eval #2 and #3. Two runs are only comparable if their pins match.

## Open threads

- Adjudication format: expected-answer+citations vs. rubric vs. keyed mix.
- How many cases, across which strata (field × scope × role, per the gold frame).
- Judge model choice and the agreement-sampling protocol.
- Where cases live (safe to commit — questions + expected answers reference chunk_ids,
  not source text).
