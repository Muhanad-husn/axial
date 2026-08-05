# feat(rung3-gates): gate harness + attribution-fidelity and grounding gates [slice 01]

**Spec:** specs/PHASE-B.md#10 · §8 P0-12 · **Plan:** plans/rung3-gates/01-gate-harness-attribution-grounding.md
**Depends on:** #258
**Labels:** sub:analysis-v0, enhancement

## Deliverable
A common **gate** shape: each gate declares a `name`, a `metric` name, a **tunable
starting threshold read from config** (never a literal), a comparison direction,
and writes a JSON report at `evals/reports/<run>.json` carrying
`{gate, metric, value, threshold, passed, n, corpus_pin, trusted}`. An
`axial gate run <gate> --dry-run --records <dir>` mode scores gates over a
directory of analysis records — dev-brief or hand-built — without the full vault,
the pin, or the academic cases; `trusted` is false unless all preconditions are
met, so a dry-run number can never be mistaken for a trusted one (§9). Two gates
ship on it. **Attribution fidelity** (Principle II): `attribution_completeness` =
share of claims with a valid kind **and** resolvable (a)/(b) grounds, a **hard
100% mechanical gate, not a sampled rate** — one bad claim fails it outright —
plus `b_seam_mislabel_rate` ≤ 0.05 on a judged sample. **Grounding** (Principle
I): `grounding_support_rate` = share of (a) claims whose cited grounds
substantively support the claim, judged by an **independent model anchored to the
resolved chunk text, from a different model family than the generating model**,
threshold ≥ 0.90. The judge runs under its own `pass_name` and the harness errors
loudly if it resolves to the synthesis model. The generating model never grades
its own output. All tests hermetic — fake vault, scripted judge,
`stub`/`record`/`explode` providers.

## Acceptance criterion
```gherkin
Given a directory of analysis records in which all 20 claims across 4 records
      carry a valid kind and resolvable (a)/(b) grounds
  And config gate thresholds of {attribution_completeness: 1.00,
      b_seam_mislabel_rate: 0.05, grounding_support_rate: 0.90}
When  `axial gate run attribution-fidelity --dry-run --records <dir>` runs
Then  the report records metric "attribution_completeness" with value 1.00,
      threshold 1.00, passed true, n 20
  And the report's `trusted` field is false (no corpus pin, no academic cases)
  And the command exits 0

Given the same directory plus one record carrying a claim of kind "a" whose
      grounds point at a chunk_id absent from the vault
When  `axial gate run attribution-fidelity --dry-run --records <dir>` runs
Then  the metric value is below 1.00, passed is false, the command exits
      non-zero, and the report names the failing claim_id

Given a directory of records carrying 10 (a) claims whose grounds resolve
  And a scripted judge answering "supports" for 9 and "does not support" for 1
When  `axial gate run grounding --dry-run --records <dir>` runs
Then  the report records metric "grounding_support_rate" with value 0.90,
      threshold 0.90, passed true, n 10
  And each judge call received the claim text and the resolved chunk text
  And the judge ran under a pass_name distinct from the synthesis pass

Given a config in which the grounding judge pass resolves to the same model as
      the synthesis pass
When  `axial gate run grounding --dry-run --records <dir>` runs
Then  the command exits non-zero with an error naming self-grading, and zero
      judge calls are made (the `explode` provider never fires)
```

## Out of scope
- The other three gates (synthesis quality, calibration, adversarial red-teaming)
  — slices 02 and 03.
- Authoring the academic hard cases. The harness reads `evals/cases/` as data when
  they exist; nobody here writes them (§9).
- Settling the judge model family or the agreement-sampling protocol — a live spec
  Open Question deferred to eval #1. This slice lands the seam and the
  self-grading guard.
- Wiring a failing gate into a blocking CI check. The gates report; enforcement is
  a later deliberate decision.
- Tuning the thresholds. §10's numbers land as TUNABLE config defaults.
</content>
