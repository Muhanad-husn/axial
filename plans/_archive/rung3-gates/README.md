# Feature: Rung-3 eval gates — the five ship-blocking gates

Build the five rung-3 gates of §10 as real pass/fail gates: **attribution
fidelity**, **grounding**, **synthesis quality (counter-position present)**,
**calibration**, and **adversarial brief red-teaming**. Each names one metric and
carries a **tunable starting threshold** read from config, reads the analysis
record (§7.3) and the retrieval trajectory log (§7.6), and writes a JSON gate
report. All five are **dry-runnable now** against the dev briefs and synthetic
cases, because their mechanical checks and process-side oracles are programmatic
(§9). The answer-quality referee — the Academic's hard cases — swaps in **as data,
never a code change**. The operator (founder) benefits: the question "is this
engine good enough to ship" gets a numeric answer with a named metric behind it,
and every threshold is a config value to argue about rather than a number buried
in code.

**Trust composes multiplicatively.** These gates sit above Phase-A's κ/agreement
eval, which is rung 1 and only rung 1. A flawless synthesis over a mis-attributed
substrate is worthless (charter Principle V).

- **Slug:** rung3-gates
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** yes (a new gate-harness surface under `src/axial/eval/`; slice
  01 is the walking skeleton establishing the common gate shape, the config-read
  threshold, the JSON report, and the dry-run mode)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [gate-harness-attribution-grounding](01-gate-harness-attribution-grounding.md) | [#262](https://github.com/Muhanad-husn/axial/issues/262) | A common pass/fail gate shape (named metric, config threshold, JSON report, `--dry-run` over dev briefs) plus the first two gates: attribution fidelity as a hard 100% mechanical gate with a judged (b)-mislabel rate ≤ 0.05, and grounding-support rate ≥ 0.90 judged by an independent model anchored to the chunk text | ☐ todo | TBD |
| 02 | [synthesis-quality-and-calibration-gates](02-synthesis-quality-and-calibration-gates.md) | [#263](https://github.com/Muhanad-husn/axial/issues/263) | Counter-position-presence rate ≥ 0.95 on the contested-brief subset plus judged steelman-quality against the eval #1 rubric bar, and a calibration-error gate ≤ 0.15 whose **metric choice is a live spec Open Question flagged for founder adjudication** | ☐ todo | TBD |
| 03 | [adversarial-brief-redteaming](03-adversarial-brief-redteaming.md) | [#264](https://github.com/Muhanad-husn/axial/issues/264) | A versioned seeded adversarial brief set — each brief declaring the premise it smuggles — plus a premise-catch-rate gate ≥ 0.80 scoring whether the interrogation pre-pass named the declared premise | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## The honest dependency statement (read this before quoting a number)

Per §9: the gates cannot produce **trusted numbers** until three things exist
together — the full ~30-source tagged vault (the Phase-A operational rollout, in
flight), the pinned corpus manifest (P0-10, `analysis-foundation` slice 02), and
the academic-authored hard cases (eval #1's referee data, gated on the scarce
Academic).

**Building and dry-running the harnesses does not wait on any of them.** The
mechanical validators and the process-side oracles are programmatic: attribution
completeness, grounds resolution, counter-position presence, coverage-map
presence, premise-catch against a seeded oracle, trajectory hits, step counts.
Those run today against the dev briefs and synthetic cases, which is exactly why
these slices are buildable now.

So: **a dry-run number is not a trusted number.** A dry-run tells you the harness
computes the metric it claims and that the plumbing is sound. It does not tell you
the engine is good — the corpus is partial, the pin may be absent, and the
judged half has no academic referee behind it yet. Every gate report therefore
records its `corpus_pin` and a `trusted` flag that is false unless all three
preconditions are met, so nobody can mistake a scaffold run for a ship decision.
Do not quote a dry-run number in a ship argument.

## Dependencies

- **01 depends on `analysis-validators` slice 01.** The attribution gate measures
  the *rate* of the property that slice's validator checks per run; it reuses that
  check rather than re-implementing it.
- **02 depends on 01** (the harness) **and on `analysis-validators` slices 02 and
  03** — the contested-detection rule and the counter-position section for the
  presence rate, the coverage map and confidence disclosure for calibration.
- **03 depends on 01** (the harness) **and on `brief-interrogation` slice 01** —
  the premise-catch metric scores the interrogation result's `premises_found`
  against the seeded oracle, so the pre-pass must exist to be scored.
- All three read records produced by `analysis-record` and trajectories written by
  `retrieval-loop`; in dry-run they read hand-built and dev-brief records, so
  neither is a hard build blocker for the harness itself.
- `analysis-foundation` slice 02 (the corpus pin) is a **precondition for trusted
  numbers**, not for the build. The gate report records the pin when one exists
  and marks the run untrusted when it does not.

## Out of scope (whole feature)

- **Eval #2 (hybrid-tagging distillation).** A separate cost track, explicitly
  bounded out of the Phase-B spec (§10).
- **Eval #3 (agentic trajectory) as its own harness.** These gates read the
  trajectory log where a metric needs it; the full process-axis eval with
  retrieval-hit and step-efficiency oracles is its own piece of work.
- **Authoring the academic hard cases.** They are the Academic's, they swap in as
  data under `evals/cases/`, and the build does not wait on them (§9). Slice 01
  lands the data seam; nobody in this repo writes the cases.
- **Settling the judge-model protocol** — family, agreement-sampling, adjudication
  format. A live spec Open Question deferred to eval #1. These slices need a judge
  *seam* and a scripted judge in tests, not a settled protocol.
- **Tuning any threshold to a real number.** Every threshold here is §10's
  starting hypothesis, marked TUNABLE, landed in config. Tuning happens on the
  first real runs.
- **CI enforcement of the gates.** The gates are runnable and reportable; wiring
  a failing gate into a blocking CI check is a later, deliberate decision.
- Live LLM calls in any test path. Judged gates are tested with a scripted judge
  through the `stub` / `record` / `explode` providers.

## Notes / open questions

- **The calibration metric choice is a live spec Open Question** — expected
  calibration error vs Brier score vs a reliability-diagram summary — and it is
  tied to the unsettled confidence vocabulary (discrete bands vs numeric score,
  §7.4). Slice 02 **does not decide it**: it lands the gate against the §10
  threshold (error ≤ 0.15) behind a named, swappable metric function and **flags
  the choice for founder adjudication**. Picking it in an implementation slice
  would be exactly the quiet spec change the process exists to prevent.
- **The generating model never grades its own output** (§10, eval charter
  constraint 2). Every judged gate runs its judge under a distinct `pass_name`
  and the harness errors loudly if the configured judge model resolves to the
  same model as the pass it is judging.
- **No self-grading on softballs** (eval charter constraint 4, the anti-Üngör
  principle). The seeded adversarial set in slice 03 is authored to be caught-or-
  missed, not to pass; the same discipline applies when the academic cases land.
- **Reuse from Phase A.** `src/axial/eval.py` — the existing gold-set scorer — is
  the closest existing shape. Its **report scaffolding and per-polity folding are
  reusable**; its **data shape is not** (it scores gold labels against tagger
  output; these gates score analysis records). Read it before inventing new report
  plumbing, then write the Phase-B data shape fresh.
- **Where the gates live.** §6 puts them in `src/axial/eval/` alongside the
  existing Phase-A scorer. The implementer decides whether that means promoting
  `eval.py` to a package in slice 01; either way the Phase-A scorer's behaviour is
  unchanged and its tests stay green.
</content>
