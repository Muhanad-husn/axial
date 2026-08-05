# feat(analysis-validators): counter-position validator — absence is a red flag, not a clean result [slice 02]

**Spec:** specs/PHASE-B.md#7.8 · specs/PHASE-B.md#7.9 · §8 P0-6 · **Plan:** plans/analysis-validators/02-counter-position-validator.md
**Depends on:** #257
**Labels:** sub:analysis-v0, enhancement

## Deliverable
A validator decides whether a brief is **contested from corpus signal, never the
brief's wording**, and on a contested brief requires the §7.8 section
`{present, stance, grounds[], corpus_one_sided, one_sided_reason}` to be either
present with non-empty `grounds` or an explicit corpus-one-sided disclosure with a
non-empty `one_sided_reason`. **Absence of both fails and blocks release** — a
contested question answered from one side with no acknowledgement is a red flag,
not a clean pass. The contested rule is a **stated tunable proven on the dev
briefs**, landed in a `contested_detection` config block, not as literals; the
starting rule is: the run's evidence spans **two or more distinct `theory_school`
values**, **or** any evidence chunk carries `role_in_argument: counter-position`.
The fired signal is persisted in the report so the tunable can be tuned on
evidence. A **bounded model steelman-quality check**, anchored to the
counter-position `grounds` and run under its own `pass_name` (never the generating
model), judges strawman-vs-steelman; in this slice it reports and does not block.
All tests are hermetic — `stub`/`record`/`explode` providers and a scripted judge.

## Acceptance criterion
```gherkin
Given an analysis record at data/analyses/DEV10.json whose evidence chunks carry
      two distinct theory_school values
  And its counter_position is
      {present: true, stance: "...", grounds: [{ref_type: "chunk",
       ref_id: "syr-0042"}], corpus_one_sided: false, one_sided_reason: null}
When  `axial brief validate DEV10` runs
Then  the command exits 0, the report records the brief as contested with signal
      "theory_school_spread", and the counter-position validator reports pass

Given an analysis record at data/analyses/DEV11.json whose evidence chunks carry
      two distinct theory_school values
  And its counter_position is {present: false, stance: null, grounds: [],
      corpus_one_sided: false, one_sided_reason: null}
When  `axial brief validate DEV11` runs
Then  the command exits non-zero, the report reason is
      "contested_without_counter_position", and no answer is released for DEV11

Given an analysis record at data/analyses/DEV12.json whose evidence is contested
  And its counter_position is {present: false, stance: null, grounds: [],
      corpus_one_sided: true,
      one_sided_reason: "corpus carries no state-capacity school on this case"}
When  `axial brief validate DEV12` runs
Then  the command exits 0 and the validator reports pass by explicit one-sided
      disclosure

Given an analysis record at data/analyses/DEV13.json whose evidence chunks carry
      a single theory_school and no role_in_argument counter-position
When  `axial brief validate DEV13` runs
Then  the command exits 0, the report records the brief as uncontested, and the
      counter-position section is not required
```

## Out of scope
- Making steelman quality a **blocking** check. It is a judged rate scored against
  the eval #1 rubric bar in `rung3-gates` slice 02.
- The counter-position-presence *rate* over the contested-brief subset (§10) —
  also `rung3-gates` slice 02.
- Retrieving or generating a counter-position when one is missing. The validator
  reports and blocks; it never patches the record.
- Tuning the contested rule against the real dev briefs. This slice lands the
  config-driven starting hypothesis plus the persisted signal; the tuning pass is
  founder-run operational work.
- Any change to the §7.8 section shape. It is locked; a shape that seems wrong is
  spec drift.
</content>
