# Slice 01: Detect prose→artifact references, emit link pairs

- **Feature:** xref
- **Slice slug:** xref-detect
- **GitHub issue:** #33
- **Branch:** feat/xref/01-xref-detect
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial xref <file>` takes the source's prose chunks and its classified artifacts and
detects prose→artifact references ("as Table 3 shows") — one LLM call per chunk
(`pass_name="xref"`), given the chunk text and the source's artifact list — emitting the
detected `(chunk_id → artifact_id)` link pairs to stdout. A referenced `artifact_id` that
is not among the source's actual artifacts never becomes a pair (no dangling links). Runs
after chunking and artifact classification (P0-7).

## INVEST check

- **Independent:** consumes chunk records (via `run_chunk`) and classified artifacts (via
  the `artifacts` pass); new `axial xref` subcommand, no existing pass changed.
- **Valuable:** the detection that turns two disjoint pools into a linkable graph — the
  substance of P0-7, observable before any note is rewritten.
- **Small:** one detection prompt, one response parser, one validity filter against the
  known artifact-id set.
- **Testable:** run `axial xref` on a fixture whose chunk references an artifact; assert
  the emitted pair list contains that `(chunk_id, artifact_id)` and nothing dangling.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture source with prose chunks and classified artifacts, and AXIAL_LLM_PROVIDER=stub canned to reference one artifact
When  the user runs `axial xref <fixture>`
Then  it exits 0 and emits the detected (chunk_id, artifact_id) reference pairs as JSON
And   a referenced artifact_id not among the source's artifacts produces no pair (no dangling link)
And   a source with no detected references emits an empty pair list without error
```

- **Boundary / endpoint:** CLI command `axial xref <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_xref.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] compose a reference-detection prompt from a chunk's text + the source's artifact list (id + a label/caption)
- [ ] parse the model's response into a list of referenced artifact ids
- [ ] filter referenced ids against the actual artifact-id set — an unknown id yields no pair (dangling links impossible)
- [ ] assemble `(chunk_id, artifact_id)` pairs for the valid references
- [ ] a chunk with no references contributes no pairs; a source with none emits an empty list

## Out of scope for this slice (deferred)

- **Writing backlinks** — pairs are emitted to stdout only; writing `artifact_refs`/`cited_by` into notes is slice 02.
- **Non-citation relatedness** — only explicit textual references are detected (feature-level out-of-scope).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
