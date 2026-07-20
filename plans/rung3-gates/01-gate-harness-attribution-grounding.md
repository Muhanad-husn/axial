# Slice 01: Gate harness + the attribution-fidelity and grounding gates

- **Feature:** rung3-gates
- **Slice slug:** gate-harness-attribution-grounding
- **GitHub issue:** #262
- **Branch:** `feat/rung3-gates/01-gate-harness-attribution-grounding`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** yes (establishes the common gate shape, the config-read
  threshold, the JSON gate report, and the dry-run mode that slices 02 and 03
  build on)
- **Depends on:** `analysis-validators` slice 01 (the attribution gate measures
  the rate of the property that validator checks; it reuses the check rather than
  re-implementing it)

## Goal — the minimum testable behaviour

A common **gate** shape lands: each gate declares a `name`, a `metric` name, a
**tunable starting threshold read from config** (never a literal), a comparison
direction, and produces a JSON gate report at `evals/reports/<run>.json` carrying
`{gate, metric, value, threshold, passed, n, corpus_pin, trusted}`. A
`axial gate run --dry-run` mode scores the gates over a directory of analysis
records — the dev-brief records, or hand-built synthetic ones — without needing
the full vault, the pin, or the academic cases. When the pin is absent or the
academic cases are absent, `trusted` is `false`. Two gates ship on that shape:

**Attribution fidelity** (charter Principle II, §10). Metric
`attribution_completeness` = share of claims with a valid `kind` **and**
resolvable (a)/(b) grounds. This is a **hard 100% mechanical gate, not a sampled
rate**: the property is mechanically checkable, so the threshold is exactly 1.00
and a single unmarked or unresolvable-grounds claim fails the gate outright
(§10, P0-5). The second half, `b_seam_mislabel_rate` — the share of (b) claims a
judge finds phrased as a source assertion — is a **judged sample** with threshold
≤ 0.05.

**Grounding** (charter Principle I, §10). Metric `grounding_support_rate` = share
of (a) claims whose cited grounds **substantively support** the claim, judged by
an **independent model anchored to the cited chunk's text**, from a **different
model family than the generating model**. Threshold ≥ 0.90. The judge receives
the claim text and the resolved chunk text and nothing else; it runs under its own
`pass_name`, and the harness **errors loudly** if that pass resolves to the same
model as the synthesis pass. The generating model never grades its own output.

## INVEST check

- **Independent:** reads finished records and the vault. It adds a measurement
  surface; it changes no engine stage. Slices 02 and 03 extend it without
  reshaping it.
- **Valuable:** turns the two most load-bearing charter principles into numbers
  with named metrics and arguable thresholds. The hard 100% attribution gate in
  particular converts "the model usually marks its claims" into a fact.
- **Small:** one gate abstraction, one JSON report, two metrics — one a reuse of
  the slice-01 validator over a set of records, one a bounded judged loop.
- **Testable:** a directory of hand-built records (all-clean, one-unmarked,
  one-unresolvable, mixed (a) claims) against a fake vault and a scripted judge.
  No LLM, no network.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a directory of analysis records in which all 20 claims across 4 records
      carry a valid kind and resolvable (a)/(b) grounds
  And config gate thresholds of
      {attribution_completeness: 1.00, b_seam_mislabel_rate: 0.05,
       grounding_support_rate: 0.90}
When  `axial gate run attribution-fidelity --dry-run --records <dir>` runs
Then  the report records metric "attribution_completeness" with value 1.00,
      threshold 1.00, passed true, n 20
  And the report's `trusted` field is false (no corpus pin, no academic cases)
  And the command exits 0

Given the same directory with one added record carrying a claim of kind "a"
      whose grounds point at a chunk_id absent from the vault
When  `axial gate run attribution-fidelity --dry-run --records <dir>` runs
Then  the metric value is below 1.00, passed is false, and the command exits
      non-zero
  And the report names the failing claim_id

Given a directory of records carrying 10 (a) claims whose grounds resolve
  And a scripted judge that answers "supports" for 9 and "does not support" for 1
When  `axial gate run grounding --dry-run --records <dir>` runs
Then  the report records metric "grounding_support_rate" with value 0.90,
      threshold 0.90, passed true, n 10
  And each judge call received the claim text and the resolved chunk text
  And the judge ran under a pass_name distinct from the synthesis pass

Given a config in which the grounding judge pass resolves to the same model as
      the synthesis pass
When  `axial gate run grounding --dry-run --records <dir>` runs
Then  the command exits non-zero with an error naming self-grading
  And zero judge calls are made (the `explode` provider never fires)
```

- **Boundary / endpoint:** CLI — `axial gate run <gate> --dry-run --records
  <dir>`; the gate report at `evals/reports/<run>.json`; the gate-threshold config
  block.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_gate_harness_attribution.py` —
  authored by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Gate shape: a gate declares name, metric name, threshold, and direction;
      the report carries `{gate, metric, value, threshold, passed, n,
      corpus_pin, trusted}`.
- [ ] Thresholds come from config, not literals — overriding
      `attribution_completeness` to 0.95 changes the pass/fail outcome with no
      code change.
- [ ] `trusted` is false when the corpus pin is absent; false when the academic
      cases directory is absent or empty; true only when both are present.
- [ ] Direction comparison: `≥` gates pass at exactly the threshold; `≤` gates
      pass at exactly the threshold.
- [ ] Empty record set: `n` is 0 and the gate reports `passed: false` with a
      reason, never a vacuous 1.00.
- [ ] `attribution_completeness` counts a claim as complete only when both kind
      validity and grounds resolution hold; each failure mode alone drops it.
- [ ] The attribution metric **reuses** the slice-01 validator check rather than
      duplicating the resolution logic.
- [ ] `b_seam_mislabel_rate` is computed over (b) claims only; a record set with
      no (b) claims yields `n: 0` and is reported, not silently passed.
- [ ] `grounding_support_rate` is computed over (a) claims only; (b) and (c)
      claims are excluded from the denominator.
- [ ] The grounding judge prompt carries the claim text and the **resolved chunk
      text** for each grounds pointer; an unresolvable pointer is a gate error,
      not a "does not support" judgement.
- [ ] Self-grading guard: a judge `pass_name` resolving to the synthesis model
      raises before any call is made.
- [ ] The report is deterministic for a fixed record set and scripted judge.

## Out of scope for this slice (deferred)

- The other three gates (synthesis quality, calibration, adversarial red-teaming)
  — slices 02 and 03.
- Authoring the academic hard cases. The harness reads them from `evals/cases/`
  as data when they exist; nobody here writes them (§9).
- Settling the judge model family or the agreement-sampling protocol. A live spec
  Open Question deferred to eval #1. This slice lands the seam and the
  self-grading guard.
- Wiring a failing gate into a blocking CI check. The gates report; enforcement is
  a later deliberate decision.
- Tuning the thresholds. §10's numbers land as config defaults, marked TUNABLE.
- Any eval #3 trajectory-scoring oracles beyond what these two metrics need.

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
