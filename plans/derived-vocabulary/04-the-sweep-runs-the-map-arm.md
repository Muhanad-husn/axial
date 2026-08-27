# Slice 04: The sweep runs any arm

- **Feature:** derived-vocabulary
- **Issue:** [#808](https://github.com/Muhanad-husn/axial/issues/808)
- **Slice slug:** the-sweep-runs-the-map-arm
- **Branch:** feat/derived-vocabulary/04-the-sweep-runs-the-map-arm
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial brief sweep` takes `--arm`, so the scored instrument can run whichever
retrieval arm exists, and every draw records which arm produced it.

## Why this slice exists

The sweep is the only scored instrument in the repo: it runs every brief N
times and scores four rung-3 gates plus a self-consistency figure per brief.
`brief run` and `brief smoke` can already select the argument-map path; the
sweep cannot. So the one instrument producing comparable numbers cannot run the
arm this feature needs to compare against.

Taking a named arm rather than a boolean is what lets slice 03 add a third arm
without either slice depending on the other.

## INVEST check

- **Independent:** touches only the sweep and the shared arm selector. Depends
  on no other slice and can be built at any point. Not parallel-safe with the
  others, because every slice in this feature touches `src/axial/cli.py`.
- **Valuable:** on its own it makes the argument-map path measurable with the
  existing instrument, which is useful whatever slice 01 reads.
- **Small:** an arm name threaded from the parser through `run_sweep` to the
  per-draw brief run, plus the record field. The paths it selects already exist
  and are already tested.
- **Testable:** the observable behaviour is which retrieval arm each draw took,
  recorded in the draw's own record.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  a worklist of briefs
When   an operator runs `uv run axial brief sweep <worklist> --draws 3 --sweep-dir <dir> --arm map`
Then   every draw runs through the argument-map retrieval path rather than the
       name-layer loop
And    each draw's persisted record names the arm that produced it, so two
       sweep directories can be told apart without reading the command that
       made them
And    the sweep's own summary names the arm and the commit it ran at
And    the same command with `--arm name` runs the name-layer loop unchanged
And    resuming a sweep directory with a different `--arm` is refused, naming
       the arm already in it
```

- **Boundary / endpoint:** CLI — `uv run axial brief sweep ... --arm <arm>`
- **e2e test type:** CLI integration test with a stubbed brief runner that
  records which arm it was asked for
- **e2e test file (planned):** `src/axial/brief/test_sweep.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 04-the-sweep-runs-the-map-arm
edits: src/axial/cli.py
edits: src/axial/test_cli.py
edits: src/axial/brief/sweep.py
edits: src/axial/brief/test_sweep.py
```

## Inner loop — initial unit test list

- [ ] `run_sweep` passes the named arm through to each `(brief, draw)` run.
- [ ] `--arm name` is the default, and a sweep run without the flag is
      byte-identical in behaviour to today's.
- [ ] `--map` keeps working as an alias for `--arm map` on the commands that
      already have it, so no existing invocation breaks.
- [ ] The sweep does not hold its own list of valid arms: an arm added
      elsewhere is accepted here with no edit to this module.
- [ ] Each draw's persisted record carries the arm that produced it.
- [ ] The sweep's summary carries the arm and the commit SHA it ran at, so a
      later comparison can refuse two directories built from different code.
- [ ] Resuming an interrupted sweep keeps the arm it started with, and refuses
      rather than silently mixing arms.

## Design notes for the executor

- **Do not change what the sweep scores.** Same four gates, same
  quorum-accuracy figure. Only the retrieval arm moves.
- **Record the commit.** Slice 05 compares directories, and two directories
  built from different code produce a difference that is not about the arms.
  The sweep is where that fact is known; recording it there is cheaper than
  reconstructing it later.
- **Check what the record already holds before slice 05 needs it.** Slice 05
  reports distinct sources cited per arm. If the per-draw record does not
  already carry that, **it is added here**. That is a field on a record the
  sweep already writes, not a second scoring path, and adding it here is what
  keeps slice 05 a pure reader. Say in the PR which of the two it turned out to
  be.
- **The mixed-arm refusal is the part worth care.** A sweep directory holding
  draws from two arms produces a comparison number that is quietly
  meaningless. Fail closed.

## Out of scope for this slice (deferred)

- Comparing arms. That is slice 05.
- Any change to the gates, the scoring, or the sweep's concurrency.
- Adding the `map+vocab` arm. That arrives with slice 03, and this slice only
  has to not stand in its way.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **One real sweep run per existing arm** on a small worklist in `D:/axial`,
      confirming the arms are distinguishable from the persisted records alone.
      This one costs model calls: run it detached, journal per event,
      checkpoint what is bought, never the foreground. Log to
      `data/logs/<YYYY-MM-DD>-sweep-arms/`.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## Status / progress log

- 2026-08-27 planned.
- 2026-08-27 revised after review and independent verification: the boolean
  `--map` became a named `--arm` so slice 03 can add a third arm without a
  dependency between the two slices; the sweep now records its commit; and the
  "does the record already carry sources cited" question, which the earlier
  draft left to whoever reached slice 05, is answered here instead.
