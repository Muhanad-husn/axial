# Slice 02: Counter-position validator — absence is a red flag, not a clean result

- **Feature:** analysis-validators
- **Slice slug:** counter-position-validator
- **GitHub issue:** #259
- **Branch:** `feat/analysis-validators/02-counter-position-validator`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** `analysis-record` slice 01 (the §7.3 record carrying the §7.8
  counter-position section and the evidence the contested test reads)

## Goal — the minimum testable behaviour

A validator decides whether a brief is **contested** from corpus signal, and on a
contested brief requires the record's §7.8 counter-position section
`{present, stance, grounds[], corpus_one_sided, one_sided_reason}` to be either
present with non-empty `grounds`, or an explicit corpus-one-sided disclosure with
a non-empty `one_sided_reason`. **Absence of both fails the validator** and blocks
release. This is the point of the check: a contested question answered from one
side with no acknowledgement is a red flag, not a clean pass (§7.8, P0-6).

Contested-ness is determined **from corpus signal, never the brief's wording**
(§7.8). The starting rule, a **stated tunable proven on the dev briefs**, lands in
config as `contested_detection`:

- the run's evidence chunks span **two or more distinct `theory_school` values**,
  **or**
- any evidence chunk carries `role_in_argument: counter-position`.

Either signal marks the brief contested. Neither, and the brief is uncontested and
the section is not required. The rule is a hypothesis, not a finding: it lives in
config so tuning it on the dev briefs is a config change, and the record persists
which signal fired so the tuning has evidence to work from.

A **bounded model steelman-quality check**, anchored to the counter-position
`grounds` and run under its own `pass_name` (never the generating model), judges
whether the stated counter-position is the opposing school at its strongest or a
strawman. In this slice the quality check reports; only the mechanical presence
check blocks release.

## INVEST check

- **Independent:** reads a finished record's evidence and counter-position
  section. Independent of slice 01 and slice 03; touches no upstream stage.
- **Valuable:** Principle IV's whole enforcement. Without it, one-sidedness is
  invisible in fluent prose — the answer reads complete precisely because the
  missing side is missing. The explicit corpus-one-sided escape hatch keeps the
  gate honest rather than forcing a fabricated counter-position.
- **Small:** one contested predicate over the evidence set, one presence-or-
  disclosure check over a fixed-shape section, one bounded model call.
- **Testable:** hand-built records — contested with a real counter-position,
  contested with a one-sided disclosure, contested with neither, uncontested with
  neither — plus a scripted judge. No LLM, no network.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an analysis record at data/analyses/DEV10.json whose evidence chunks carry
      two distinct theory_school values
  And its counter_position is
      {present: true, stance: "...", grounds: [{ref_type: "chunk",
       ref_id: "syr-0042"}], corpus_one_sided: false, one_sided_reason: null}
When  `axial brief validate DEV10` runs
Then  the command exits 0
  And the report records the brief as contested with signal "theory_school_spread"
  And the counter-position validator reports pass

Given an analysis record at data/analyses/DEV11.json whose evidence chunks carry
      two distinct theory_school values
  And its counter_position is
      {present: false, stance: null, grounds: [], corpus_one_sided: false,
       one_sided_reason: null}
When  `axial brief validate DEV11` runs
Then  the command exits non-zero
  And the report reason is "contested_without_counter_position"
  And no answer is released for DEV11

Given an analysis record at data/analyses/DEV12.json whose evidence is contested
  And its counter_position is
      {present: false, stance: null, grounds: [], corpus_one_sided: true,
       one_sided_reason: "corpus carries no state-capacity school on this case"}
When  `axial brief validate DEV12` runs
Then  the command exits 0
  And the counter-position validator reports pass by explicit one-sided disclosure

Given an analysis record at data/analyses/DEV13.json whose evidence chunks carry
      a single theory_school and no role_in_argument counter-position
When  `axial brief validate DEV13` runs
Then  the command exits 0
  And the report records the brief as uncontested
  And the counter-position section is not required
```

- **Boundary / endpoint:** CLI — `axial brief validate <brief_id>`; the record's
  `counter_position` section and its evidence chunks; the
  `contested_detection` config block.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_counter_position_validator.py` —
  authored by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Contested predicate, signal A: evidence spanning two distinct
      `theory_school` values is contested; a single value is not; zero values is
      not.
- [ ] Contested predicate, signal B: one evidence chunk with
      `role_in_argument: counter-position` is contested on its own, even with a
      single `theory_school`.
- [ ] The predicate reads **evidence**, never the brief's `request` text — a
      brief whose wording sounds adversarial over single-school evidence is
      uncontested.
- [ ] The rule's thresholds come from config, not literals: overriding
      `contested_detection` in config changes the outcome with no code change.
- [ ] The fired signal is persisted in the report (`theory_school_spread` /
      `role_counter_position`) so the tunable can be tuned on evidence.
- [ ] Presence check: `present: true` with non-empty `grounds` passes;
      `present: true` with empty `grounds` fails (a stance with no grounds is not
      a counter-position).
- [ ] Disclosure check: `corpus_one_sided: true` with a non-empty
      `one_sided_reason` passes; `corpus_one_sided: true` with an empty or absent
      reason fails.
- [ ] Neither present nor disclosed on a contested brief fails with
      `contested_without_counter_position`.
- [ ] The steelman-quality model check runs only when `present: true`, is anchored
      to the counter-position `grounds` text, and runs under a `pass_name`
      distinct from the synthesis pass (`explode` provider proves zero calls on
      the one-sided-disclosure and uncontested paths).
- [ ] A scripted judge returning "strawman" is recorded in the report as a
      concern and does **not** block release in this slice.

## Out of scope for this slice (deferred)

- Making steelman quality a **blocking** check. It is a judged rate scored at the
  gate level in `rung3-gates` slice 02, against the eval #1 rubric bar.
- The counter-position-presence *rate* over the contested-brief subset (§10) —
  also `rung3-gates` slice 02.
- Retrieving or generating a counter-position when one is missing. The validator
  reports and blocks; it never patches the record.
- Tuning the contested rule against the real dev briefs. This slice lands the
  rule as a config-driven starting hypothesis plus the persisted signal that
  makes tuning possible; the tuning pass is founder-run operational work once the
  dev briefs and full vault are in hand.
- Any change to the §7.8 section shape. It is locked; a shape that seems wrong is
  spec drift.

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
