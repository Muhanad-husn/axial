# Slice 03: Source-set inputs (corpus glob) + end-of-run summary

- **Feature:** run
- **Slice slug:** source-sets-and-run-summary
- **GitHub issue:** #277
- **Branch:** feat/run/03-source-sets-and-run-summary
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Two additions complete the runner. First, a second **source set**: besides
`--worklist <file>` (slice 01), `axial run <pass>` accepts the corpus glob and
runs over every source under `data/sources/` matching `*.pdf`/`*.docx`, in a
deterministic (sorted) order. Exactly one source set is required per run;
supplying both, or neither, is a fatal usage error. Second, an **end-of-run
summary**: after the loop, the runner emits a structured summary — total sources,
and counts of OK / FAIL / SKIP — followed by the per-source outcomes (source,
`source_id`, status, short reason for FAILs). The summary is a plain in-process
value the runner returns and prints, so a consumer (#270's log emitter, #288's
rates report) can attach to it without reaching into runner internals. This slice
defines the summary structure and leaves a named attachment point for #288's
not-applicable/unlisted rates; it does not compute those rates.

## INVEST check

- **Independent:** builds on slice 01's loop (and composes with slice 02's SKIP
  outcomes) by adding a source-set resolver and a summary step. Changes no pass.
- **Valuable:** makes the runner usable on the whole corpus with one flag instead
  of a hand-maintained worklist, and gives the operator the end-of-run signal
  (how many succeeded, failed, were skipped) that stage 4's re-tag reads. This is
  the reporting half of P1-4.
- **Small:** one glob resolver, one mutual-exclusivity check, one summary
  aggregation over outcomes the loop already produces.
- **Testable:** run `axial run <pass> --corpus` over a fixture `data/sources/`
  with mixed `.pdf`/`.docx` and an ignored `.txt`; assert the resolved set,
  sorted order, and the summary counts; assert `--worklist` + `--corpus` together,
  and neither, are usage errors.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture data/sources/ holding two .pdf, one .docx, and one ignored .txt, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial run <pass> --corpus`
Then  it exits 0
And   it processes exactly the three .pdf/.docx sources in a deterministic sorted order, ignoring the .txt
And   it prints an end-of-run summary reporting total=3 with OK/FAIL/SKIP counts that sum to 3
And   the summary lists each source with its source_id, status, and a short reason for any FAIL

Given both --worklist and --corpus, or neither
When  the user runs `axial run <pass>` with that argument combination
Then  it exits non-zero with a usage error naming the conflict, having attempted no source
```

- **Boundary / endpoint:** CLI command `axial run <pass>` with a mutually-
  exclusive source set: `--worklist <file>` (slice 01) or `--corpus` (this
  slice); the corpus root overridable for tests
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_run_corpus.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] the corpus resolver returns every `data/sources/*.pdf` and `*.docx`,
      ignoring other extensions, in sorted order (determinism, not filesystem
      enumeration order)
- [ ] exactly one source set is required: `--worklist` and `--corpus` together is
      a usage error; neither is a usage error; both attempt no source
- [ ] the summary aggregates the loop's outcomes into total + OK/FAIL/SKIP counts
      that sum to the total attempted
- [ ] the summary carries per-source rows (source, `source_id`, status, short
      reason for FAILs) and never carries source text (DEC-23)
- [ ] SKIP outcomes from slice 02's resume path are counted and listed distinctly
      from OK and FAIL
- [ ] the summary is returned as a structured in-process value (not only printed),
      exposing the attachment seam #288 and #270 consume
- [ ] a run over an empty source set exits 0 and reports total=0 with a clear
      "nothing to do" summary

## Out of scope for this slice (deferred)

- **The not-applicable / unlisted rates computation** (#288). This slice defines
  where that report attaches to the summary; #288 computes and fills it.
- **The structured run-log emitter and its file format** (#270). The runner hands
  #270 the summary value; #270 serializes it to `data/logs/<run>/`.
- **Progress rendering polish** (bars, ETAs). A per-source progress line is enough;
  richer progress UI is not P1-4.
- **Recursive or configurable corpus roots** beyond the single `data/sources/`
  glob. One corpus root, the two documented extensions.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-21 planned.
