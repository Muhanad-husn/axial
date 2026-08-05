# Slice 02: Synthesis-quality and calibration gates

- **Feature:** rung3-gates
- **Slice slug:** synthesis-quality-and-calibration-gates
- **GitHub issue:** #263
- **Branch:** `feat/rung3-gates/02-synthesis-quality-and-calibration-gates`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** slice 01 (the gate harness, the config threshold seam, the JSON
  report, the dry-run mode, the self-grading guard); `analysis-validators` slice
  02 (contested detection + the §7.8 section); `analysis-validators` slice 03 (the
  coverage map + confidence disclosure)

## Goal — the minimum testable behaviour

Two more gates land on the slice-01 harness.

**Synthesis quality — counter-position present** (charter Principle IV, §10).
Metric `counter_position_presence_rate` = share of the **contested-brief subset**
whose record is present-or-disclosed: `present: true` with non-empty `grounds`,
or `corpus_one_sided: true` with a non-empty `one_sided_reason`. Threshold
**≥ 0.95**. The contested subset is selected by `analysis-validators` slice 02's
contested-detection rule, not by re-deriving it here; an uncontested record is
excluded from the denominator, not counted as a pass. A second metric,
`steelman_quality`, scores the stated counter-position against the **eval #1
rubric bar** via an independent judge anchored to the counter-position `grounds`,
under its own `pass_name` and the slice-01 self-grading guard.

**Calibration** (charter Principle V, §10). Metric `calibration_error` between the
disclosed `confidence` and judged correctness. Threshold **≤ 0.15**.

> **The calibration metric choice is a live spec Open Question** — expected
> calibration error vs Brier score vs a reliability-diagram summary — and it is
> **tied to the unsettled confidence vocabulary** (discrete bands vs a numeric
> score, §7.4). **This slice does not decide it.** It lands the gate against
> §10's threshold behind a **named, swappable metric function** selected by a
> config key (`calibration.metric`), ships one clearly-labelled provisional
> implementation so the harness is runnable, and **flags the choice for founder
> adjudication**. Picking the metric inside an implementation slice would be the
> quiet spec change the process exists to prevent. The implementer who hits a
> forced choice here raises it, not resolves it.

## INVEST check

- **Independent:** extends the slice-01 harness with two more gates and changes
  nothing in it. Independent of slice 03.
- **Valuable:** these two catch the failures the first two gates cannot see. A
  perfectly attributed, perfectly grounded answer can still be one-sided, and it
  can still be confidently wrong. Presence-or-disclosure and calibration are the
  only numbers that surface those.
- **Small:** two metrics on an existing gate shape — one a fold over a filtered
  record subset, one a judged loop plus a metric function behind a config key.
- **Testable:** hand-built record sets with a known contested/uncontested split
  and a known confidence-vs-correctness spread, plus a scripted judge. No LLM.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a directory of 20 analysis records of which 10 are contested by the
      analysis-validators contested-detection rule
  And 10 of those 10 contested records are present-or-disclosed
  And config gate threshold counter_position_presence_rate of 0.95
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the report records metric "counter_position_presence_rate" with value 1.00,
      threshold 0.95, passed true, n 10
  And the 10 uncontested records are excluded from n, not counted as passes
  And the command exits 0

Given the same directory with two contested records carrying
      {present: false, grounds: [], corpus_one_sided: false}
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the metric value is 0.83, passed is false, the command exits non-zero,
      and the report names both failing brief_ids

Given a directory of contested records with a stated counter-position
  And a scripted judge that scores each against the eval #1 rubric bar
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the report also records metric "steelman_quality" with its rubric-bar
      threshold and pass/fail
  And each judge call was anchored to the record's counter_position grounds text
  And the judge ran under a pass_name distinct from the synthesis pass

Given a directory of records carrying disclosed confidence bands
  And a scripted judge supplying judged correctness per record
  And config {calibration.metric: "<provisional>", calibration_error: 0.15}
When  `axial gate run calibration --dry-run --records <dir>` runs
Then  the report records metric "calibration_error" with the configured metric
      NAME, its computed value, threshold 0.15, and pass/fail
  And the report carries an `open_question` note naming the unresolved metric
      choice and the confidence vocabulary it depends on
  And swapping calibration.metric in config selects a different metric function
      with no code change
```

- **Boundary / endpoint:** CLI — `axial gate run synthesis-quality|calibration
  --dry-run --records <dir>`; the gate report at `evals/reports/<run>.json`; the
  `calibration.metric` config key.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_synthesis_and_calibration_gates.py`
  — authored by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Contested subset selection delegates to `analysis-validators` slice 02's
      rule; it is not re-derived here (a fake asserts the call).
- [ ] Uncontested records are excluded from the denominator; a set with zero
      contested records reports `n: 0` and does not vacuously pass.
- [ ] Present-or-disclosed counting: `present: true` + non-empty grounds counts;
      `corpus_one_sided: true` + non-empty reason counts; `present: true` with
      empty grounds does not; neither does not.
- [ ] Presence rate arithmetic at the threshold boundary — 19/20 = 0.95 passes,
      18/20 = 0.90 fails.
- [ ] `steelman_quality` judge calls are anchored to the counter-position grounds
      text and skipped where `corpus_one_sided: true` (nothing to steelman).
- [ ] The steelman judge honours the slice-01 self-grading guard.
- [ ] `calibration.metric` selects the metric function by name from a registry;
      an unknown name errors clearly rather than falling back silently.
- [ ] The metric NAME is written into the report, so a number is never readable
      without knowing which metric produced it.
- [ ] The report carries the `open_question` note whenever the calibration gate
      runs.
- [ ] Calibration over records with no disclosed confidence errors rather than
      imputing a band.
- [ ] Both gates inherit slice 01's `trusted` flag semantics — false without pin
      and academic cases.

## Out of scope for this slice (deferred)

- **Deciding the calibration metric.** Flagged for founder adjudication; a spec
  Open Question, resolved by the spec-author in a deliberate pass, never here.
- **Settling the confidence vocabulary** (§7.4 Open Question). The gate reads
  whatever the record discloses.
- The reliability diagram (P1-2). A nice-to-have reporting surface, not a gate.
- Authoring the eval #1 rubric. The gate reads the rubric bar as data; the rubric
  is the Academic's and swaps in without a code change (§9).
- Re-implementing contested detection, the coverage map, or the counter-position
  presence check. All three are `analysis-validators`; this slice measures rates
  over them.
- Tuning either threshold. §10's 0.95 and 0.15 land as TUNABLE config defaults.
- The adversarial red-teaming gate — slice 03.

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
