# Slice 02: Unified resume ledger + per-pass done-predicate

- **Feature:** run
- **Slice slug:** unified-resume-ledger
- **GitHub issue:** #277
- **Branch:** feat/run/02-unified-resume-ledger
- **Project directory:** .
- **Status:** ✅ done (merged)
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

The runner owns **one** resume ledger, and each registered pass declares a
**done-predicate** — a small function answering "is this `source_id` already done
for this pass?" At the top of the per-source loop the runner consults the ledger
and the pass's done-predicate; a source that is already done is skipped doing
**zero** pipeline work (not re-read, not re-run, not re-written), logging exactly
one `skip: <source> already done (<pass>)` line. Every non-skipped source runs and
appends one outcome row to the ledger — an APPEND, never an overwrite, so a
pre-existing OK row survives byte-for-byte (the property `run_ingest` already
guarantees). This replaces the three source-level resume mechanisms with one: the
`vault_status=OK` TSV rows (`ingest.py`), the output-file-exists checks
(`extract`/`envelope`), and the per-source xref-done signal all become *one
ledger the runner owns* plus *one done-predicate the pass declares*. A pass whose
natural done-signal is "output file exists" declares that as its predicate; a
pass whose signal is "an OK ledger row exists" declares that; the runner no longer
cares which — it asks the predicate and records the row.

## INVEST check

- **Independent:** builds on slice 01's registry and loop; adds a `done_predicate`
  field to the pass descriptor and a ledger read/append to the runner. Touches no
  pass's internal logic — a pass's predicate is a thin wrapper over the signal it
  already exposes (a tree/envelope file path, or a ledger lookup).
- **Valuable:** delivers P1-4's core promise — "re-running skips already-processed
  sources" — for *any* pass, from one mechanism instead of three divergent ones.
- **Small:** one ledger reader, one appender (reuse `ingest`'s TSV columns and
  append-not-overwrite discipline), one predicate field, one skip branch.
- **Testable:** run `axial run <pass>` twice over the same worklist; assert the
  second run skips every source that the first completed, does zero pass work for
  them (no LLM call, no output rewrite), appends no duplicate OK row, and that a
  FAIL source from run one is retried in run two.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a worklist of fixture sources and AXIAL_LLM_PROVIDER=stub, and a first `axial run <pass>` that completed with one source FAIL and the rest OK
When  the user re-runs `axial run <pass> --worklist <same worklist>`
Then  it exits 0
And   every source recorded OK in the first run is skipped, logging one skip line each and doing zero pipeline work for it
And   the previously FAILed source is attempted again
And   no duplicate OK row is appended for an already-done source, and the first run's rows survive unchanged

Given a pass whose done-signal is an output file (e.g. envelope) and a source whose output already exists on disk
When  the user runs `axial run <pass>` over a worklist naming that source
Then  the source is skipped via the pass's done-predicate without recomputing its output
```

- **Boundary / endpoint:** CLI command `axial run <pass> --worklist <file>`,
  re-run against a populated ledger; ledger path overridable for tests
  (`--ledger`/`results_path`-style seam, mirroring `run_ingest`)
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_run_resume.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] each pass descriptor carries a `done_predicate(source_id) -> bool`; the
      runner calls it (and/or reads the ledger) before invoking the pass
- [ ] a source the predicate reports done is skipped: no pass callable invocation,
      one skip line naming the source and pass
- [ ] the ledger read collects already-done `source_id`s keyed by `(pass,
      source_id)`; an absent ledger yields an empty done-set (nothing skipped)
- [ ] a completed source appends exactly one outcome row; re-running does not
      append a second row for it and does not rewrite the file's existing rows
- [ ] a source recorded FAIL is **not** in the done-set, so a later run retries it
- [ ] the file-exists done-predicate (extract/envelope) reports done when the
      persisted output exists and not-done when it is absent, without running the
      pass
- [ ] the ledger done-predicate (vault-write) reports done for a source carrying an
      OK row and not-done otherwise
- [ ] an unappendable ledger is a fatal error (non-zero exit), mirroring
      `ingest.ResultsFileError`

## Out of scope for this slice (deferred)

- **The corpus glob source set** and the end-of-run summary — slice 03. This slice
  still reads a worklist and reports only enough to prove skip/append behaviour.
- **The per-chunk `.jsonl` checkpoints inside tag/artifacts/xref.** These are a
  finer intra-pass granularity and stay the pass's own business; a pass's
  done-predicate may consult them internally, but this slice neither replaces nor
  reaches into them. Source-level resume only.
- **Migrating `axial ingest` onto the runner.** `run_ingest` keeps working
  unchanged; folding it in (or deprecating it) is a later, separately-reviewed
  move, not part of standing up the runner's ledger.
- **The run-log emitter** (#270) — the ledger is the runner's own resume record,
  distinct from #270's structured run log.

## Definition of done

- [x] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [x] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [x] Refactor pass complete with the bar green.
- [x] Slice's tests run in CI.
- [x] Reviewer's two-stage review passed.
- [x] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-21 planned.
- 2026-07-21 built and merged: PR #306 (`6047450`). Ledger at
  `data/logs/run/ledger.tsv` keyed by `(pass, source_id)`; extract/envelope
  declare a file-exists done-predicate, every other pass declares a ledger
  done-predicate. Spec P1-4 updated in the same PR. This status marker was
  left stale until 2026-07-24, when a redispatch of this slice found the
  work already on `main`.
