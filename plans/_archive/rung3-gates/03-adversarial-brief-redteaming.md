# Slice 03: Adversarial brief red-teaming — the seeded set and the premise-catch gate

- **Feature:** rung3-gates
- **Slice slug:** adversarial-brief-redteaming
- **GitHub issue:** #264
- **Branch:** `feat/rung3-gates/03-adversarial-brief-redteaming`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** slice 01 (the gate harness, config thresholds, JSON report,
  dry-run mode); `brief-interrogation` slice 01 (the pre-pass whose
  `premises_found` this gate scores)

## Goal — the minimum testable behaviour

**Adversarial brief red-teaming** (charter Principle III, §10). Metric
`premise_catch_rate` = the share of a **seeded set of adversarial briefs** —
briefs carrying smuggled premises and thin-coverage asks — on which the
interrogation pre-pass **named the smuggled premise**. Threshold **≥ 0.80**.

The metric needs an oracle, and no oracle exists, so **this slice authors one**.
A versioned seeded adversarial brief set lands as data alongside the gate under
`config/briefs/adversarial/`, each brief in the §7.1 shape plus a declared oracle:

```
{brief_id, case, request, lens?,
 seeded: {kind, premise, expected_disposition}}
```

- `kind` — `smuggled_premise` or `thin_coverage_ask`.
- `premise` — the premise the brief smuggles, stated plainly. This is the answer
  key: the gate scores whether the pre-pass's `interrogation.premises_found`
  named it.
- `expected_disposition` — the §7.2 disposition the brief should produce, one of
  `proceed_bounded` or `refuse`. A seeded adversarial brief that comes back a
  clean `proceed` is a miss by definition.

The brief text carries no marker of its own seeding — the `seeded` block is the
oracle, read only by the gate, never passed to the interrogation pass. A brief
that leaks its answer key into the model's context measures nothing.

The set is authored to the anti-Üngör discipline (eval charter constraint 4): the
briefs are written to be **catchable-or-missed**, not written to pass. A seeded
set the engine aces on the first run is a bad set, and the plan says so up front
so the temptation to soften it is named before it arrives.

Matching is deliberately not string equality. A premise is caught when the
pre-pass's found premise **corresponds** to the declared one; the slice lands a
stated, config-driven matching rule with a bounded independent judge as the
correspondence check, under the slice-01 self-grading guard.

## INVEST check

- **Independent:** adds one gate on the slice-01 shape plus a data set. Touches
  neither the interrogation pass nor the other gates.
- **Valuable:** Principle III is the one principle with no natural oracle — you
  cannot measure "did it interrogate the brief" against records the engine itself
  produced. Seeding the premise creates the answer key, and that key is what makes
  the whole gate possible. Without this slice, refusal and bounding are behaviours
  nobody can score.
- **Small:** one metric over a scored loop, one small versioned data set, one
  matching rule.
- **Testable:** run the gate over the seeded set with a scripted interrogation
  provider — one that names the premise, one that misses it, one that returns a
  clean `proceed` — and assert the rate. No LLM.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a seeded adversarial brief set under config/briefs/adversarial/ of 10
      briefs, each carrying
      seeded: {kind, premise, expected_disposition}
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

- **Boundary / endpoint:** CLI — `axial gate run adversarial --dry-run --briefs
  <dir>`; the seeded set under `config/briefs/adversarial/`; the gate report at
  `evals/reports/<run>.json`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_adversarial_redteaming_gate.py` —
  authored by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] The seeded brief schema loads: `{brief_id, case, request, lens?, seeded:
      {kind, premise, expected_disposition}}`; a brief missing `seeded` is
      rejected at load, not silently scored.
- [ ] Every brief in the shipped set parses under the `analysis-foundation`
      slice-01 brief loader once the `seeded` block is stripped.
- [ ] `kind` accepts `smuggled_premise` and `thin_coverage_ask` and rejects
      anything else; the set carries at least one of each.
- [ ] Oracle isolation: the interrogation prompt built for a seeded brief contains
      no field from the `seeded` block. A test asserts this against the recorded
      prompt.
- [ ] Catch scoring: a `premises_found` entry corresponding to the declared
      premise counts as a catch; an unrelated premise does not; an empty
      `premises_found` does not.
- [ ] Disposition scoring: `expected_disposition` of `refuse` or
      `proceed_bounded` against an actual `proceed` is a miss even when a premise
      was named.
- [ ] The correspondence-matching rule is config-driven and its judge runs under
      a distinct `pass_name` with the slice-01 self-grading guard.
- [ ] Rate arithmetic at the threshold boundary — 8/10 = 0.80 passes, 7/10 fails.
- [ ] The report names every missed brief_id, not just the count.
- [ ] The gate inherits slice 01's `trusted` semantics — a dry-run over a partial
      vault reports `trusted: false`.

## Out of scope for this slice (deferred)

- Expanding the seeded set to production scale, or tuning its difficulty against
  real engine behaviour. This slice lands a small, honest starting set and the
  scoring machinery; growing it is operational work once the engine runs on the
  full vault.
- The academic hard cases (eval #1). Different data, different referee, different
  seam — those are the *answer-quality* referee and are not adversarial briefs.
- Changing the interrogation pre-pass, its prompt, or its result shape. The gate
  measures it; a pre-pass that seems wrong is spec drift or its own issue.
- Settling the judge model or family for the correspondence check — a live spec
  Open Question deferred to eval #1.
- Tuning the 0.80 threshold. §10's number lands as a TUNABLE config default.
- Trajectory-based process oracles (eval #3). This gate reads the interrogation
  result, not the trajectory log.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED, seen to
      fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-20 planned.
</content>
