# Slice 05: The three arms are compared

- **Feature:** derived-vocabulary
- **Issue:** [#809](https://github.com/Muhanad-husn/axial/issues/809)
- **Slice slug:** the-two-arms-are-compared
- **Branch:** feat/derived-vocabulary/05-the-two-arms-are-compared
- **Project directory:** .
- **Status:** ☑ built and measured, PR #824 open for approval
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`uv run axial eval layers` reads the sweep directories for the three arms and
prints one table: per brief, per arm, the grounding gate results and the count
of distinct sources cited, each with that brief's own spread across draws.

## Why this slice exists

Two questions, one table:

- **Does the argument map beat the name layer?** Arm `name` against arm `map`.
- **Does the derived vocabulary add anything?** Arm `map` against arm
  `map+vocab`.

The second is the one this feature exists to answer, and an earlier draft of
this plan could not answer it — both arms were layers that already existed.
Three arms is the founder's ruling of 2026-08-27, taken after review and
independent verification landed on that gap separately.

## INVEST check

- **Independent:** reads directories that already exist by the time it runs.
  Changes no pipeline behaviour.
- **Valuable:** it produces the decision. Nothing else in the feature does.
- **Small:** a reader over persisted gate reports and a formatter. No model
  call, no retrieval, no new measurement — every number it prints was computed
  by the sweep.
- **Testable:** given fixture sweep directories with known contents, the table
  is deterministic.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  three sweep directories, one per arm, over the same worklist and the
       same number of draws, all built at the same commit
When   an operator runs `uv run axial eval layers --arm-dir <name-dir> --arm-dir <map-dir> --arm-dir <vocab-dir>`
Then   the report gives, per brief and per arm, the grounding gate results and
       the count of distinct sources that brief's answers cited
And    each figure carries that brief's spread across its own draws
And    it refuses, naming the mismatch, if the directories do not cover the
       same briefs, the same draw count, and the same commit
And    a brief missing from one arm is reported as missing for that arm, never
       averaged over or dropped
```

- **Boundary / endpoint:** CLI — `uv run axial eval layers`
- **e2e test type:** CLI integration test over fixture sweep directories
- **e2e test file (planned):** `src/axial/eval/test_layers.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 05-the-two-arms-are-compared
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: src/axial/eval/layers.py
creates: src/axial/eval/test_layers.py
depends-on: 03-two-notes-meet-at-a-shared-group
depends-on: 04-the-sweep-runs-the-map-arm
```

## Inner loop — initial unit test list

- [ ] Reading one sweep directory yields, per brief, its per-draw gate results
      and the count of distinct sources cited.
- [ ] Directories over different brief sets are refused, naming which briefs
      are missing from which arm.
- [ ] Directories over different draw counts are refused on the same terms.
- [ ] Directories built at different commits are refused, naming both.
- [ ] Every reported figure carries the spread across that brief's own draws.
- [ ] Source count is reported as a plain count with no better/worse marking.
- [ ] A brief that failed to produce a record in one arm is reported missing
      for that arm, never averaged over.
- [ ] Two arms are accepted as well as three, so the command is usable before
      the third arm exists.

## Design notes for the executor

- **Compute nothing new.** The sweep scores its four rung-3 gates per
  `(brief, draw)` and, from slice 04, records distinct sources cited. This
  slice reads those records. Do not add a second scoring path.
- **Per stratum, never pooled.** `eval coherence` already refuses to report a
  pooled system-wide mean. Hold that line: per brief, with its spread.
- **The report states figures; the interpretation lives in the run log.** Two
  known misreadings apply and both are stated in the Definition of Done's
  summary rather than generated as prose by the command. A unit test asserting
  that a particular sentence appears in output pins editorial copy in a test,
  and the reader of this table is a person who can be told the rules once.
- **The vocabulary of the sweep.** "Rung-3 gates", "quorum-accuracy" and which
  gate is the grounding gate are defined in `specs/PHASE-B.md` and
  `src/axial/brief/sweep.py`, not in this plan. Read them before starting.

## Run sizing, decided here rather than left open

- **Worklist:** the five-brief smoke set (`SMOKE_BRIEFS_DIR`), the same set the
  repo already treats as its standing comparison sample.
- **Draws:** **3 per brief per arm**. The whole safeguard of this slice is the
  per-brief spread across draws, and a spread needs more than two points to
  mean anything. Fewer than three makes the central figure decorative.
- **Total:** 5 briefs × 3 draws × 3 arms = 45 runs. This is the expensive step
  in the feature, and it is bounded: a five-brief measurement, not a corpus
  pass. Priced against the recorded $0.0417 and 9m46s for a single ask, that is
  roughly **$1.90 and about 2.5 hours** at the sweep's default of 3 workers.
  Raising `--workers` is the lever on the clock; the cost does not move.
- **If the clock matters more than the spread**, cut draws to 2 and say so in
  the run log. Do not cut below 2: with a single draw the per-brief spread is
  degenerate and the variance argument this slice rests on has nothing behind
  it.

## Two known misreadings, carried into the run log

Both are on the record here and both would be easy to repeat by eye.

- **A drop in sources cited is not a regression.** The argument map was
  validated at *strong* grounding against the name layer's *adequate*, on four
  sources against eight.
- **A margin narrower than the model's own variance is not a finding.** Gather
  does not reproduce 36.1% of its recorded disagreements on byte-identical
  input (#700); merge disagrees with itself at 13.3% on groups of three or more
  (#695). Every figure carries its draw spread so this cannot be missed.

## Out of scope for this slice (deferred)

- Acting on the result. Removing, demoting or rewiring the name layer is
  separate work, filed after the founder rules.
- Any new gate, or any change to how the existing four are scored.
- Cost and latency comparison between arms. Worth knowing, not what this
  decision turns on.
- Generated interpretive prose in the command's output.

## Definition of done

- [x] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [x] All seeded unit behaviours covered; fast tier green locally (2512 passed,
      1 skipped), CI green for the rest — all six checks.
- [x] Refactor pass complete with the bar green.
- [x] `uv run ruff check` clean.
- [x] Slice's tests run in CI (`tdd-ci`).
- [x] **All three arms run for real** in `D:/axial` at one commit, over the same
      worklist and draw count above, detached and journalled, then the
      comparison run over the three directories. Checkpoint what is bought.
      Log to `data/logs/<YYYY-MM-DD>-layer-comparison/` with `run.jsonl`,
      `console.log` and `summary.md`. Copy the per-brief records into the log
      **before** the runs start, since re-asking overwrites its own record. The
      summary states both misreadings above in the founder's own words.
- [x] The table handed to the founder with the two questions named and neither
      answered.
- [x] Evidence collected and PR opened into the default branch (`safe-pr`) —
      [#824](https://github.com/Muhanad-husn/axial/pull/824).

## Status / progress log

- 2026-08-27 planned.
- 2026-08-28 built, measured and opened as PR #824. All three arms ran at commit
  `b18f95b`: 45 draws, 45 landed, 0 failures, $5.12 against the ~$1.90 estimate.
  Review and independent verification both ran before the PR reached the
  founder; both reached the same finding — the pooled gate figure sat beside a
  draw count in the same shape as a per-draw mean — and every finding was
  applied. Run log: `data/logs/2026-08-28-layer-comparison/`.
- 2026-08-27 revised after review and independent verification, both of which
  found the derived vocabulary reached neither measured arm. Founder ruling the
  same day: three arms. Run sizing, the commit refusal, and the removal of
  generated interpretive prose landed in the same pass.
