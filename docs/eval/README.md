# System-level evaluation — charter

**Status:** foundation. Scope and structure agreed; each eval is stubbed in its own
file and gets fleshed out from there. Nothing here is a spec or a slice yet.

## What this is

Three end-to-end evaluations of the **product** (Axial's ingest → tag → retrieve →
answer path), as opposed to component-level measurement. They sit on three different
axes and must not be conflated:

| # | Eval | Axis | Question it answers | Referee |
|---|------|------|---------------------|---------|
| 1 | [Answer quality](01-answer-quality.md) | output | Is the answer right? | Sealed-packet reviewer panel (PHASE-B §9.4) |
| 2 | [Hybrid-tagging distillation](02-hybrid-tagging-distillation.md) | cost | Does distilling head tags off the LLM earn its spend? | P0-10 gold set |
| 3 | [Agentic trajectory](03-agentic-trajectory.md) | process | Did the query agent get there *well*? | Trajectory scoring + programmatic oracles |

Each axis catches a failure the others hide. #1 misses "right answer, broken
retrieval." #3 misses "efficient path, wrong answer." #2 measures neither quality
alone nor process — it measures **quality per dollar** against a baseline.

## Explicitly out of scope: re-litigating P0-10

The P0-10 gold-set eval (component-level tagger scoring, shipped PR #136; its label
sheets were lost with `data/gold/` and are re-derivable by the dispatch in
`docs/sim-academic/`, no longer by an academic) is **not** one of these three. But eval #2 *uses* P0-10
as its measuring stick — using an instrument and evaluating that instrument are
different acts. P0-10 is the ruler here, not the subject.

## Shared constraints (bind all three)

1. **Freeze and version the corpus.** Scores only compare against a pinned corpus.
   Because all of `data/` is gitignored (DEC-23), the pin is a **manifest + hashes**,
   not a commit: source list, ingest-code SHA, and a vault snapshot hash. Defined once
   in [answer-quality](01-answer-quality.md), now implemented
   (`axial pin write`, PHASE-B §7.12), and reused by #2 and #3.
2. **Keep the judge independent.** The model's family does not grade its own
   homework. The five rung-3 gates enforce a different model id in code; eval #1's
   reviewer panel is stricter still — a different **vendor**, sealed from the repo by
   tooling, N >= 3 with the spread reported as the error bar. There is no
   judge-vs-human agreement check, because there is no human: a **positive control**
   against planted defects replaces it (DEC-40, DEC-43).
3. **Define the adjudication contract before collecting cases.** Per case: an expected
   answer plus the citations it should rest on, or an explicit rubric. A bare question
   is not an eval. Settled: the keyed `answer_kind` shape of PHASE-B §9.3, permanent.
4. **No self-grading on softballs.** The anti-Üngör principle (see the #115
   postmortem): grade on hard cases the system cannot already ace, not on questions
   chosen because they pass.

## Sequencing — one shared gate

```
rebuilt corpus ──▶ pin resolves ──▶ { #1 rich corpus + panel positive control
                                    { #2 tag distribution + P0-10
                                    { #3 rich corpus (distractors)
```

The corpus rebuild is the single critical-path event. Nothing meaningful *runs*
before it, though every harness can be built and dry-run against synthetic cases
first — no oracle here waits on a person.

## The scarce resource

There isn't one any more. The academic was the bottleneck for #1's hard cases and
P0-10's labels; #250 and #295 closed *not planned* on 2026-07-24, so nothing in this
directory waits on a human. #1's referee is now a model panel that is trusted only
after its own positive control catches planted defects.

## Files

- `01-answer-quality.md` — output axis. Originated the shared corpus-pin format.
- `02-hybrid-tagging-distillation.md` — cost axis. The "exploratory process."
- `03-agentic-trajectory.md` — process axis. The product's query agent (path *a*).
