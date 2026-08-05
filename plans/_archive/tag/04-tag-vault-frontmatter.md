# Slice 04: Persist axis tags into prose-note frontmatter

- **Feature:** tag
- **Slice slug:** tag-vault-frontmatter
- **GitHub issue:** #31
- **Branch:** feat/tag/04-tag-vault-frontmatter
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial vault write <file>` runs the tagger internally (which runs the chunker) and
writes the chunk-level axis frontmatter into each prose note — `claim_type`, `field`,
`empirical_scope` (+`country`), `theory_school` `[candidate]`, `role_in_argument` — plus
the `schema_version` stamp, completing the three-level frontmatter of PRD §7.2 /
Appendix H. The phase-2 source-level and section-level metadata are preserved unchanged.

## INVEST check

- **Independent:** extends `run_vault_write` to compose the tagger (as it already composes
  the chunker) and to serialize the axis block; the tagger itself is unchanged.
- **Valuable:** the first vault a human (or a later retrieval pass) can open and see
  *tagged* prose — the phase-3 payoff made durable on disk.
- **Small:** swap `run_chunk` for `run_tag` inside `run_vault_write`, and extend
  `build_frontmatter` with the axis block + `schema_version`.
- **Testable:** run `axial vault write` on a fixture; assert each prose note's frontmatter
  now carries the axis block + `schema_version`, matching the Appendix H shape.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and chunks, AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  each prose note's frontmatter carries `schema_version` and a chunk-level axis block (claim_type, field, empirical_scope, theory_school, role_in_argument) matching Appendix H
And   the phase-2 source-level (`source_meta`) and section-level metadata are unchanged
And   re-running is idempotent (no duplicate or conflicting frontmatter)
```

- **Boundary / endpoint:** CLI command `axial vault write <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_vault_tag_frontmatter.py — test-author, red, locked

## Inner loop — initial unit test list

- [ ] `build_frontmatter` includes the chunk-level axis block + `schema_version` alongside the existing `chunk_id`/`section`/`chunk_text`/`source_meta`
- [ ] the axis block matches the Appendix H nesting (primary/secondary/subtags; `country` nested under `empirical_scope`; `theory_school` carries `status: candidate`)
- [ ] the phase-2 fields (`source_meta`, `section`, `chunk_id`, `chunk_text`) are preserved byte-for-byte in shape
- [ ] `run_vault_write` runs the tagger internally — one thread from source to tagged prose notes
- [ ] re-running overwrites a note idempotently rather than duplicating it (regression guard on the phase-2 behaviour)

## Out of scope for this slice (deferred)

- **The artifact pool's contents** — written by the `artifacts` feature.
- **Backlinks** (`artifact_refs`/`cited_by`) — the `xref` feature.
- **A single `axial ingest` orchestrator** — each stage remains its own subcommand (phase-2 decision).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
