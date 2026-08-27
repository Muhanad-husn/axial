# Slice 05: The two arms are compared

- **Feature:** derived-vocabulary
- **Issue:** [#809](https://github.com/Muhanad-husn/axial/issues/809)
- **Slice slug:** the-two-arms-are-compared
- **Branch:** feat/derived-vocabulary/05-the-two-arms-are-compared
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

One command reads two sweep directories — the name-layer arm and the map arm —
and reports, per brief and per arm, how well the answers were grounded and how
many sources they reached. The founder decides the name layer's future on that
table.

## Why this slice exists

The comparison is the point of the feature, and it is the step most likely to
be read wrongly if done by eye. Two known misreadings are already on record in
this repo: a drop in sources cited is not a regression, and a margin narrower
than the model's own run-to-run variance is not a finding. A command that
encodes both rules cannot make either mistake twice.

## INVEST check

- **Independent:** reads two directories that already exist by the time it
  runs. Changes no pipeline behaviour.
- **Valuable:** it produces the decision. Nothing else in the feature does.
- **Small:** a reader over persisted gate reports and a formatter. No model
  call, no retrieval, no new measurement — every number it prints was already
  computed by the sweep.
- **Testable:** given two fixture sweep directories with known contents, the
  table is deterministic.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  two sweep directories, one produced with `--map` and one without, over
       the same worklist and the same number of draws
When   an operator runs `uv run axial eval layers --name-arm <dir> --map-arm <dir>`
Then   the report gives, per brief, each arm's grounding gate results and the
       count of distinct sources its answers cited
And    it states the per-brief spread across draws alongside each figure, so a
       difference smaller than that spread is visible as such
And    it refuses, naming the mismatch, if the two directories do not cover the
       same briefs and the same draw count
And    it never presents a lower source count as a regression on its own
```

- **Boundary / endpoint:** CLI — `uv run axial eval layers`
- **e2e test type:** CLI integration test over two fixture sweep directories
- **e2e test file (planned):** `src/axial/eval/test_layers.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 05-the-two-arms-are-compared
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: src/axial/eval/layers.py
creates: src/axial/eval/test_layers.py
depends-on: 04-the-sweep-runs-the-map-arm
depends-on: 03-two-notes-meet-at-a-shared-group
```

## Inner loop — initial unit test list

- [ ] Reading one sweep directory yields, per brief, its per-draw gate results
      and the distinct sources its answers cited.
- [ ] Two directories over different brief sets are refused, naming which
      briefs are missing from which arm.
- [ ] Two directories over different draw counts are refused on the same terms.
- [ ] Every reported figure carries the spread across that brief's own draws.
- [ ] Source count is reported as a plain count with no better/worse marking,
      and the report says in words that a lower count is not a regression.
- [ ] A brief that failed to produce a record in one arm is reported as missing
      for that arm, never averaged over or quietly dropped.

## Design notes for the executor

- **Compute nothing new.** The sweep already scores its four rung-3 gates per
  `(brief, draw)`. This slice reads those records. If a number is not already
  in them, either the sweep should produce it or the comparison does not need
  it — resist adding a second scoring path.
- **Per stratum, never pooled.** The `eval coherence` command already refuses
  to report a pooled system-wide mean. Hold the same line: per brief, with its
  spread, not one number for the corpus.
- **The variance floor is real and measured.** Gather does not reproduce 36.1%
  of its own recorded disagreements on byte-identical input, and merge
  disagrees with itself at 13.3% on groups of three or more. A one-run
  difference smaller than a brief's own draw spread is noise. Print the spread
  next to every figure so this is impossible to miss.
- **Name what the founder has to decide, in the report itself.** The last line
  of the output should state the question — whether the map arm's grounding
  justifies demoting the name layer — not answer it.

## Out of scope for this slice (deferred)

- Acting on the result. Removing, demoting or rewiring the name layer is
  separate work, filed after the founder rules.
- Any new gate, or any change to how the existing four are scored.
- Cost and latency comparison between the arms. Worth knowing, not what this
  decision turns on.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **Both arms run for real** in `D:/axial` over the same worklist and the
      same draw count, detached and journalled, and the comparison run over the
      two directories. This is the expensive step in the feature — checkpoint
      what is bought. Log to `data/logs/<YYYY-MM-DD>-layer-comparison/` with
      `run.jsonl`, `console.log` and `summary.md`, and copy the per-brief
      records into the log **before** the runs, since re-asking overwrites its
      own record.
- [ ] The report handed to the founder with the decision stated as a question,
      not pre-answered.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## Status / progress log

- 2026-08-27 planned.
