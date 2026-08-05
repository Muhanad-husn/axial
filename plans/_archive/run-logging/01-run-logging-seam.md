# Slice 01: Run-logging seam — `run_context`, stdlib `logging`, `run.jsonl`, proven through `extract`

- **Feature:** run-logging
- **Slice slug:** run-logging-seam
- **GitHub issue:** #270
- **Branch:** feat/run-logging/01-run-logging-seam
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes

## Goal — the minimum testable behaviour

A new `src/axial/runlog.py` provides one seam: a `run_context(name, *, root,
clock)` context manager that creates a run directory `data/logs/<name>-<ts>/`,
attaches a stdlib `logging.FileHandler` so everything written to the run logger
is teed to `console.log`, and exposes a `record(...)` method that appends one
JSON line per unit of work to `run.jsonl`. Each record carries `source_id`,
`pass`, `model` (nullable), `status`, `duration_sec`, and `error` — **ids and
values only, never source text (DEC-23)**.

The `extract` pass is wired to open a `run_context("extract")`, run its existing
work per source **with its existing `print()` output unchanged**, and append one
record per source: `status="ok"` with a `duration_sec` on success, `status="error"`
with a short `error` string on failure. `extract` has no LLM call, so its records
carry `model: null` — the skeleton proves a model-free record round-trips before
slice 02 adds the model-bearing passes.

This is the whole thread: open run dir → configure logging → run pass → append
records → close. Console output is added-to, not changed.

## INVEST check

- **Independent:** `runlog.py` is a new module; the only edit to an existing pass
  is wrapping `extract` in the context manager. No other pass, no other command,
  no CLI-surface change.
- **Valuable:** the first machine-readable record any run leaves, and the seam
  #277 (runner) imports and #288 (rates) reads. Nothing downstream can be built
  without it.
- **Small:** one module, one context manager, one record shape, one pass wired.
- **Testable:** run `extract` over a fixture with an injected run dir and clock;
  assert the run dir exists with `run.jsonl` + `console.log`, one record per
  source, correct fields, `model: null`, and no source text anywhere in the file.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture source and a run-logging seam given an explicit run directory and a fixed clock
When  the extract pass runs over the fixture through `run_context("extract")`
Then  the run directory contains run.jsonl, console.log, and a summary.md stub
And   run.jsonl holds exactly one JSON record for the source
And   that record carries source_id, pass="extract", model=null, status="ok", a numeric duration_sec, and error=null
And   run.jsonl contains no source text — only ids, values, and status (DEC-23)
And   the pass's existing stdout is unchanged (the record is added, not substituted)
```

- **Boundary / endpoint:** the `run_context` seam driving the `extract` pass over
  a fixture; assertions read the files under the injected run directory.
- **Outer test type:** pytest integration test (in-process; injected run dir +
  clock; stub provider not required — extract is model-free).
- **Outer test file (planned):** tests/test_runlog.py — test-author, red, locked (DEC-1)

### How the outer test stays deterministic

The run directory name embeds a timestamp, which would make wall-clock the
oracle. The test defeats this two ways, both injected at the seam:

1. **Explicit run dir.** The test passes `root=<tmp_path>` and a fixed
   sub-name, so the assertions read a known path — they never glob for
   "whatever dir got made now."
2. **Injected clock.** `run_context(..., clock=lambda: FIXED_TS)` fixes the
   timestamp used in the dir name and any record time. Production passes no
   clock and gets `time`/`datetime.now`. `duration_sec` is asserted as *a
   number ≥ 0* (or a monotonic delta the fixed clock makes exact), never a
   specific wall-clock value.

No global monkeypatch of `datetime`; the seam owns its clock so the test owns it
too.

## Inner loop — initial unit test list

- [ ] `run_context(name, root=..., clock=...)` creates `data/logs/<name>-<fixed-ts>/`
      under the injected root and yields a handle
- [ ] the handle's `record(...)` appends one JSON line per call to `run.jsonl`,
      with keys `source_id`, `pass`, `model`, `status`, `duration_sec`, `error`
- [ ] a record with `model=None` serializes as JSON `null` (model-free pass)
- [ ] on context exit the `logging.FileHandler` is flushed and detached — no
      handler leaks into later runs or tests
- [ ] `console.log` receives what the run logger emits; the pass's own `print()`
      to real stdout is untouched (added-to, not rerouted)
- [ ] a `summary.md` stub (header only) is created; the seam never writes the
      narrative body (operator-authored)
- [ ] `record(...)` rejects / has no parameter for chunk text — the shape cannot
      carry a source passage (DEC-23 guard)
- [ ] a per-source failure records `status="error"` with a short `error` string
      and the loop continues; the record for a healthy source is unaffected

## Out of scope for this slice (deferred)

- **The other three passes** — `envelope`, `tag`, `eval` are slice 02. This
  slice wires `extract` only.
- **Model-bearing records** — `model` is nullable and exercised as `null` here;
  populating it from a per-source LLM call lands with the model-bearing passes in
  02.
- **The corpus runner** — #277 opens one `run_context` around a whole corpus
  loop. This slice proves the seam on a single pass; it does not build the loop.
- **Rate reporting** — #288 reads `run.jsonl`. Not this slice.
- **`summary.md` content** — operator-authored; the seam writes at most a stub
  header.
- **Retention / GC of run dirs** — #291's concern.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-21 planned.
