# System-level evaluation — answer quality

**Status:** foundation. The sealed-packet reviewer panel is the sole end-to-end
product eval.

## What this is

One evaluation of the **product** — Axial's ingest → interrogate → retrieve →
answer path, end to end:

| Eval | Axis | Question it answers | Referee |
|------|------|---------------------|---------|
| [Answer quality](01-answer-quality.md) | output | Is the answer right? | Sealed-packet reviewer panel (PHASE-B §9.4) |

It measures whether the output is correct, independent of cost or process
quality, and is graded by a sealed external panel (N >= 3), never by the model
that produced the answer.

Two sibling evals were retired on 2026-08-06 —
`02-hybrid-tagging-distillation.md` measured a tag pass that no longer exists,
and `03-agentic-trajectory.md` was a stub nothing was built from. Both are in
`docs/_archive/` with `04-frozen-tag-distribution.md`.

## Shared constraints

1. **Freeze and version the corpus.** Scores only compare against a pinned corpus.
   Because all of `data/` is gitignored (DEC-23), the pin is a **manifest + hashes**,
   not a commit: source list, ingest-code SHA, and a vault snapshot hash. Defined in
   [answer-quality](01-answer-quality.md) and implemented (`axial pin write`,
   PHASE-B §7.12).
2. **Keep the judge independent.** The model's family does not grade its own
   homework. The five rung-3 gates enforce a different model id in code; the
   reviewer panel is stricter still — a different **vendor**, sealed from the repo by
   tooling, N >= 3 with the spread reported as the error bar. There is no
   judge-vs-human agreement check, because there is no human: a **positive control**
   against planted defects replaces it (DEC-40, DEC-43).
3. **Define the adjudication contract before collecting cases.** Per case: an expected
   answer plus the citations it should rest on. A bare question
   is not an eval. Settled: the keyed `answer_kind` shape of PHASE-B §9.3, permanent.
4. **No self-grading on softballs.** The anti-Üngör principle (see the #115
   postmortem): grade on hard cases the system cannot already ace, not on questions
   chosen because they pass.

## Files

- `01-answer-quality.md` — output axis. Originated the shared corpus-pin format.
