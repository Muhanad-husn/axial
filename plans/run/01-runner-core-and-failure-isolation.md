# Slice 01: Runner core — pass registry + per-source failure isolation

- **Feature:** run
- **Slice slug:** runner-core-and-failure-isolation
- **GitHub issue:** #277
- **Branch:** feat/run/01-runner-core-and-failure-isolation
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes

## Goal — the minimum testable behaviour

`axial run <pass> --worklist <file>` drives a single registered per-source pass
over every source path in a line-delimited worklist, one source at a time. A
**pass registry** — a plain dict mapping a pass name (`extract`, `envelope`,
`chunk`, `tag`, `artifacts`, `xref`, `vault-write`) to a small descriptor (the
pass's per-source callable plus the `*Error` base it raises) — is the whole pass
abstraction. For each source the runner computes the content-derived `source_id`
(`envelope.compute_source_id`), invokes the pass, and records an in-process
outcome. **Failure is isolated per source:** if the pass raises its declared
error base for one source, the runner records that source as FAIL and continues
to the next — one bad source never aborts the worklist. The loop exits 0 even
when some sources failed; it exits non-zero **only** when the loop itself cannot
run (an unreadable worklist, or an unknown pass name). This is the skeleton: read
the source set → run one pass on one source → isolate its failure → continue →
report an exit code. It generalizes `run_ingest`'s hard-wired `run_vault_write`
loop to any pass in the registry, and its `VaultError`-only catch to each pass's
declared error type.

## INVEST check

- **Independent:** adds a new `src/axial/run.py` and an `axial run` subcommand
  alongside `axial ingest`, changing no existing pass and not touching
  `ingest.py`. It reuses `compute_source_id` and the passes' public entrypoints.
- **Valuable:** the first command that drives *any* pass over a source set with
  real failure isolation — the retirement path for `ingest_worker.sh` and the
  bare-`except` loop wrapper (postmortem root cause D).
- **Small:** one input form (worklist), the loop, a dict registry, one catch-and-
  continue seam, an exit-code contract. No resume ledger (slice 02), no glob
  (slice 03).
- **Testable:** run `axial run <pass> --worklist <file>` with the stub provider
  over a small fixture worklist where one source is crafted to fail; assert the
  loop processed every source, recorded the failure, continued past it, and exited
  0; assert an unknown pass name and an unreadable worklist each exit non-zero.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a line-delimited worklist naming three fixture sources, the middle one crafted to make its pass raise that pass's declared error, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial run <pass> --worklist <worklist>`
Then  it exits 0
And   the runner attempts all three sources in worklist order
And   the middle source is recorded as FAIL with a short reason and the loop continues to the third
And   the first and third sources are recorded as OK

Given a worklist path that does not exist
When  the user runs `axial run <pass> --worklist <missing>`
Then  it exits non-zero and prints a fatal error naming the unreadable worklist, having attempted no source

Given a pass name absent from the registry
When  the user runs `axial run <unknown-pass> --worklist <worklist>`
Then  it exits non-zero and prints a fatal error naming the unknown pass, having attempted no source
```

- **Boundary / endpoint:** CLI command `axial run <pass> --worklist <file>`
  (positional pass name; `--worklist` names the source set; default domain
  `config/domains/syria`, `--domain` override, mirroring the other passes)
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_run.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] the pass registry resolves each known pass name to a descriptor carrying a
      callable and the pass's declared error base; an unknown name raises a fatal
      `UnknownPassError` before any source is touched
- [ ] the runner reads a line-delimited worklist (reusing `ingest.read_worklist`
      or the same contract): stripped non-blank lines, blank lines skipped
- [ ] each source's `source_id` is computed via `envelope.compute_source_id`; a
      source whose id cannot be computed is recorded FAIL and the loop continues
- [ ] a source that raises the running pass's declared error base is recorded as a
      FAIL outcome carrying a short reason; the loop proceeds to the next source
- [ ] a source that succeeds is recorded as an OK outcome
- [ ] the loop returns exit 0 when some sources failed but the loop ran to
      completion; it returns non-zero only for a fatal condition (unreadable
      worklist, unknown pass)
- [ ] an exception that is **not** the pass's declared error base propagates (a
      genuine bug is not swallowed as a recoverable per-source failure)
- [ ] the runner threads the shared LLM client and `config_path`/`domain_dir`
      into each pass invocation, constructing the client once for the whole run

## Out of scope for this slice (deferred)

- **The unified resume ledger and the done-predicate protocol** — slice 02. This
  slice records outcomes in process and does not skip already-done sources at the
  runner level (a pass's own file-exists idempotence still applies).
- **The corpus glob source set** and the polished end-of-run summary — slice 03.
  This slice reads a worklist only and needs no more than a minimal end-of-loop
  tally to prove the loop ran.
- **The run-log emitter / file format** (#270) and the not-applicable/unlisted
  rates report (#288). Named as seams in the feature README, built elsewhere.
- **Parallelism, cross-pass chaining.** One pass, sources in sequence.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-21 planned.
