# feat(rung3-gates): adversarial brief red-teaming — seeded set + premise-catch gate [slice 03]

**Spec:** specs/PHASE-B.md#10 · §8 P0-12 · **Plan:** plans/rung3-gates/03-adversarial-brief-redteaming.md
**Depends on:** #262, #252
**Labels:** sub:analysis-v0, enhancement

## Deliverable
The fifth rung-3 gate (Principle III): `premise_catch_rate` = the share of a
**seeded set of adversarial briefs** — carrying smuggled premises and
thin-coverage asks — on which the interrogation pre-pass **named the smuggled
premise**, threshold **≥ 0.80**. The metric needs an oracle and none exists, so
this issue **authors one**: a versioned seeded set under
`config/briefs/adversarial/`, each brief in the §7.1 shape plus
`seeded: {kind, premise, expected_disposition}` — `kind` in
`{smuggled_premise, thin_coverage_ask}`, `premise` the plainly-stated answer key,
`expected_disposition` one of `proceed_bounded` / `refuse`. A seeded adversarial
brief that returns a clean `proceed` is a miss by definition. The brief text
carries no marker of its own seeding and the `seeded` block is **never** passed to
the interrogation prompt — a brief that leaks its answer key measures nothing.
The set is authored to the anti-Üngör discipline: briefs written to be
catchable-or-missed, not written to pass. Premise matching is a stated,
config-driven correspondence rule with a bounded independent judge under slice
01's self-grading guard, not string equality. Tests are hermetic via a scripted
interrogation provider.

## Acceptance criterion
```gherkin
Given a seeded adversarial brief set under config/briefs/adversarial/ of 10
      briefs, each carrying seeded: {kind, premise, expected_disposition}
  And config gate threshold premise_catch_rate of 0.80
  And a scripted interrogation provider that names the seeded premise on 9 of
      the 10 and returns a clean `proceed` on 1
When  `axial gate run adversarial --dry-run --briefs config/briefs/adversarial` runs
Then  the report records metric "premise_catch_rate" with value 0.90,
      threshold 0.80, passed true, n 10
  And the report names the one missed brief_id
  And the command exits 0

Given the same set and a scripted provider that names the premise on only 7
When  `axial gate run adversarial --dry-run --briefs config/briefs/adversarial` runs
Then  the metric value is 0.70, passed is false, and the command exits non-zero

Given any seeded adversarial brief
When  the gate runs the interrogation pre-pass over it
Then  the prompt sent to the provider contains the brief's case and request
  And the prompt contains neither the `seeded` block, the declared premise, nor
      the expected_disposition

Given a seeded brief with expected_disposition "refuse"
  And a scripted provider whose result yields disposition "proceed"
When  the gate scores that brief
Then  it is counted as a miss regardless of what premises_found contains
```

## Out of scope
- Expanding the seeded set to production scale or tuning its difficulty against
  real engine behaviour. This issue lands a small, honest starting set plus the
  scoring machinery; growing it is operational work once the engine runs on the
  full vault.
- The academic hard cases (eval #1) — the *answer-quality* referee, different data
  and a different seam.
- Changing the interrogation pre-pass, its prompt, or its result shape. The gate
  measures it; a pre-pass that seems wrong is spec drift or its own issue.
- Settling the judge model or family for the correspondence check — a live spec
  Open Question deferred to eval #1.
- Tuning the 0.80 threshold. §10's number lands as a TUNABLE config default.
- Trajectory-based process oracles (eval #3). This gate reads the interrogation
  result, not the trajectory log.
</content>
