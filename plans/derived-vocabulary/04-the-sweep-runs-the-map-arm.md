# Slice 04: The sweep runs the map arm

- **Feature:** derived-vocabulary
- **Issue:** [#808](https://github.com/Muhanad-husn/axial/issues/808)
- **Slice slug:** the-sweep-runs-the-map-arm
- **Branch:** feat/derived-vocabulary/04-the-sweep-runs-the-map-arm
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial brief sweep` accepts `--map` and runs its whole worklist through the
argument-map retrieval path, the way `brief run` and `brief smoke` already can.

## Why this slice exists

The sweep is the only scored instrument in the repo — it runs every brief N
times and scores four rung-3 gates plus a self-consistency figure per brief.
`brief run --map` and `brief smoke --map` both exist. `brief sweep` does not
take the flag, so the one instrument that produces comparable numbers cannot
run the arm this feature needs to compare against. That is the single piece of
missing code between the census and the decision.

## INVEST check

- **Independent:** touches only the sweep and depends on no other slice, so it
  can be built at any point in the feature. `independence.mjs` clears it to run
  beside slice 03 — the only parallel-safe pair in the feature — but not beside
  01, 02 or 05, which share `src/axial/cli.py` with it.
- **Valuable:** on its own it makes the map arm measurable with the existing
  instrument — useful whatever this feature concludes.
- **Small:** a flag threaded from the parser through `run_sweep` to the
  per-draw brief run. The path it selects already exists and is already tested.
- **Testable:** the observable behaviour is which retrieval path each draw took,
  recorded in the draw's own record.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  a worklist of briefs
When   an operator runs `uv run axial brief sweep <worklist> --draws 1 --sweep-dir <dir> --map`
Then   every draw runs through the argument-map retrieval path rather than the
       name-layer loop
And    each draw's persisted record says which path it took, so two sweep
       directories can later be told apart without reading the command that
       made them
And    the same command without `--map` still runs the name-layer loop
       unchanged
```

- **Boundary / endpoint:** CLI — `uv run axial brief sweep ... --map`
- **e2e test type:** CLI integration test with a stubbed brief runner that
  records which path it was asked for
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

- [ ] `run_sweep` passes the map flag through to each `(brief, draw)` run.
- [ ] The flag defaults to off, and a sweep run without it is byte-identical in
      behaviour to today's.
- [ ] Each draw's persisted record carries which retrieval path produced it.
- [ ] The sweep's own summary carries the arm, so a report reading the
      directory does not have to infer it from a draw.
- [ ] Resuming an interrupted sweep keeps the arm it started with, and refuses
      rather than silently mixing arms if asked to resume into the other one.

## Design notes for the executor

- **Copy `brief smoke`'s flag, exactly.** `smoke` already has `--map` with the
  same `dest="use_map"` and the same help text shape. Match it rather than
  designing a second spelling.
- **The mixed-arm refusal is the part worth care.** A sweep directory holding
  draws from both arms would produce a comparison number that is quietly
  meaningless. Fail closed.
- **Do not change what the sweep scores.** Same four gates, same
  quorum-accuracy figure. Only the retrieval path moves.

## Out of scope for this slice (deferred)

- Comparing the two arms. That is slice 05.
- Any change to the gates, the scoring, or the sweep's concurrency.
- Wiring the slice-03 tool into the map path — the map arm here is the argument
  map as it stands today.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **One real sweep run per arm** on a small worklist in `D:/axial`,
      confirming the arms are distinguishable from the persisted records alone.
      This costs model calls — run it detached, journal it, checkpoint it, and
      log to `data/logs/<YYYY-MM-DD>-sweep-map-arm/`.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## Status / progress log

- 2026-08-27 planned.
