# feat(rung3-gates): synthesis-quality and calibration gates [slice 02]

**Spec:** specs/PHASE-B.md#10 · §8 P0-12 · **Plan:** plans/rung3-gates/02-synthesis-quality-and-calibration-gates.md
**Depends on:** #262, #259, #260
**Labels:** sub:analysis-v0, enhancement

## Deliverable
Two more gates on the slice-01 harness. **Synthesis quality — counter-position
present** (Principle IV): `counter_position_presence_rate` = share of the
**contested-brief subset** that is present-or-disclosed (`present: true` with
non-empty `grounds`, or `corpus_one_sided: true` with a non-empty
`one_sided_reason`), threshold **≥ 0.95**. The contested subset comes from
`analysis-validators` slice 02's detection rule, not re-derived here; uncontested
records are excluded from the denominator, never counted as passes. A second
metric, `steelman_quality`, scores the stated counter-position against the **eval
#1 rubric bar** via an independent judge anchored to the counter-position grounds,
under slice 01's self-grading guard. **Calibration** (Principle V):
`calibration_error` between disclosed confidence and judged correctness, threshold
**≤ 0.15**.

**The calibration metric choice is a live spec Open Question** — expected
calibration error vs Brier vs a reliability-diagram summary — and it is tied to the
unsettled confidence vocabulary (§7.4). **This issue does not decide it.** It
lands the gate behind a **named, swappable metric function** selected by a
`calibration.metric` config key, ships one clearly-labelled provisional
implementation so the harness runs, writes the metric NAME into every report, and
**flags the choice for founder adjudication**. An implementer who hits a forced
choice here raises it rather than resolving it.

## Acceptance criterion
```gherkin
Given a directory of 20 analysis records of which 10 are contested by the
      analysis-validators contested-detection rule
  And all 10 contested records are present-or-disclosed
  And config gate threshold counter_position_presence_rate of 0.95
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the report records metric "counter_position_presence_rate" with value 1.00,
      threshold 0.95, passed true, n 10
  And the 10 uncontested records are excluded from n, not counted as passes
  And the command exits 0

Given the same directory with two contested records carrying
      {present: false, grounds: [], corpus_one_sided: false}
When  `axial gate run synthesis-quality --dry-run --records <dir>` runs
Then  the metric value is 0.83, passed is false, the command exits non-zero, and
      the report names both failing brief_ids

Given a directory of contested records with a stated counter-position
  And a scripted judge scoring each against the eval #1 rubric bar
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

## Out of scope
- **Deciding the calibration metric.** Flagged for founder adjudication; a spec
  Open Question resolved by the spec-author in a deliberate pass, never here.
- Settling the confidence vocabulary (§7.4 Open Question). The gate reads whatever
  the record discloses.
- The reliability diagram (P1-2) — a reporting nicety, not a gate.
- Authoring the eval #1 rubric. The gate reads the rubric bar as data; it swaps in
  without a code change (§9).
- Re-implementing contested detection, the coverage map, or the counter-position
  presence check. All three are `analysis-validators`; this slice measures rates
  over them.
- Tuning either threshold. §10's 0.95 and 0.15 land as TUNABLE config defaults.
- The adversarial red-teaming gate — slice 03.
</content>
