# System-level evaluation — charter

**Status:** foundation. Scope and structure agreed; each eval is stubbed in its own
file and gets fleshed out from there. Nothing here is a spec or a slice yet.

## What this is

Three end-to-end evaluations of the **product** (Axial's ingest → tag → retrieve →
answer path), as opposed to component-level measurement. They sit on three different
axes and must not be conflated:

| # | Eval | Axis | Question it answers | Referee |
|---|------|------|---------------------|---------|
| 1 | [Answer quality](01-answer-quality.md) | output | Is the answer right? | Academic hard cases + LLM-as-judge |
| 2 | [Hybrid-tagging distillation](02-hybrid-tagging-distillation.md) | cost | Does distilling head tags off the LLM earn its spend? | P0-10 gold set |
| 3 | [Agentic trajectory](03-agentic-trajectory.md) | process | Did the query agent get there *well*? | Trajectory scoring + programmatic oracles |

Each axis catches a failure the others hide. #1 misses "right answer, broken
retrieval." #3 misses "efficient path, wrong answer." #2 measures neither quality
alone nor process — it measures **quality per dollar** against a baseline.

## Explicitly out of scope: re-litigating P0-10

The P0-10 gold-set eval (component-level tagger scoring, shipped PR #136, blocked on
the academic labeling pause) is **not** one of these three. But eval #2 *uses* P0-10
as its measuring stick — using an instrument and evaluating that instrument are
different acts. P0-10 is the ruler here, not the subject.

## Shared constraints (bind all three)

1. **Freeze and version the corpus.** Scores only compare against a pinned corpus.
   Because all of `data/` is gitignored (DEC-23), the pin is a **manifest + hashes**,
   not a commit: source list, ingest-code SHA, and a vault snapshot hash. Define this
   format once, in [answer-quality](01-answer-quality.md), and reuse it for #2 and #3.
2. **Keep the judge independent.** Anchor any LLM-as-judge to the academic's expected
   answer, consider a different model family as judge, and spot-check judge-vs-human
   agreement on a sample. The model's family does not grade its own homework.
3. **Define the adjudication contract before collecting cases.** Per case: an expected
   answer plus the citations it should rest on, or an explicit rubric. A bare question
   is not an eval.
4. **No self-grading on softballs.** The anti-Üngör principle (see the #115
   postmortem): grade on hard cases the system cannot already ace, not on questions
   chosen because they pass.

## Sequencing — one shared gate

```
canary #121 PASS ──▶ full 24-source cold re-run ──▶ { #1 rich corpus + academic cases
                                                     { #2 tag distribution + P0-10
                                                     { #3 rich corpus (distractors)
```

The full re-run is the single critical-path event. Nothing meaningful *runs* before
it. But the **harnesses for #2 and #3 can be built and dry-run now** against the
current small state or synthetic cases — their oracles (token/step counts,
parity-with-teacher, retrieval-hit checks) do not need the academic. Only #1's cases
need the scarce academic, so batch that ask with the P0-10 label request rather than
making a second round-trip.

## The scarce resource

The academic is the bottleneck: P0-10 labels and #1's hard cases are both asks of the
same person. Order of operations: canary PASS → full re-run → academic authors hard
cases on the frozen rich corpus. Build #2 and #3 in parallel while that waits.

## Files

- `01-answer-quality.md` — output axis. Also owns the shared corpus-pin format.
- `02-hybrid-tagging-distillation.md` — cost axis. The "exploratory process."
- `03-agentic-trajectory.md` — process axis. The product's query agent (path *a*).
