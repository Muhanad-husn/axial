# Slice 02: Write bidirectional backlinks into both pools

- **Feature:** xref
- **Slice slug:** xref-backlinks
- **GitHub issue:** #34
- **Branch:** feat/xref/02-xref-backlinks
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial vault write <file>` runs the cross-reference detection after both prose and
artifact notes are written, then materialises each detected reference as bidirectional
frontmatter: `artifact_refs: [artifact_id, ...]` on the referencing prose note and
`cited_by: [chunk_id, ...]` on the referenced artifact note. Every `artifact_refs` entry
has a matching `cited_by` and vice versa. Re-running adds no duplicates. This completes
P0-7 and the backlink half of P0-8, closing the phase-3 vault.

## INVEST check

- **Independent:** extends `run_vault_write` with a final backlink pass over the notes
  already written by `tag` slice 04 and `artifacts` slice 02; the detection is unchanged
  from slice 01.
- **Valuable:** the vault becomes a navigable graph — from a prose claim to the table it
  cites and back — the terminal deliverable of Phase-A ingestion.
- **Small:** run the slice-01 detection, then patch two list-valued frontmatter fields
  across two note sets.
- **Testable:** run `axial vault write` on a fixture whose chunk references an artifact;
  assert the prose note's `artifact_refs` and the artifact note's `cited_by` both name the
  other, and re-running does not duplicate.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture source whose chunk references an artifact, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  the referencing prose note's frontmatter carries `artifact_refs` including the artifact_id
And   the referenced artifact note's frontmatter carries `cited_by` including the chunk_id
And   a note with no references carries an empty or absent backlink field (never a dangling one)
And   re-running is idempotent — no duplicate backlink entries
```

- **Boundary / endpoint:** CLI command `axial vault write <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_vault_xref.py — test-author, red, locked

## Inner loop — initial unit test list

- [ ] add `artifact_refs` to a prose note's frontmatter for that chunk's detected references
- [ ] add `cited_by` to the referenced artifact note's frontmatter
- [ ] bidirectional consistency: every `artifact_refs` entry has a matching `cited_by` and vice versa
- [ ] the backlink pass runs only after both prose and artifact notes exist (ordering within `run_vault_write`)
- [ ] re-running does not duplicate entries in either list-valued field (idempotent, extending the phase-2 guarantee to list fields)

## Out of scope for this slice (deferred)

- **New detection logic** — reuses slice 01 unchanged.
- **A single `axial ingest` orchestrator** — `axial vault write` remains the terminal composition; no separate orchestrator command (phase-2 decision).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
