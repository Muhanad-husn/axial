# Slice 02: Route artifacts to the pool, with `field` + provenance + discard flag

- **Feature:** artifacts
- **Slice slug:** artifact-pool-write
- **GitHub issue:** #32
- **Branch:** feat/artifacts/02-artifact-pool-write
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial vault write <file>` additionally writes one artifact note per classified artifact
to `data/vault/artifacts/` — a surface separate from `data/vault/prose/` — with
frontmatter carrying `artifact_role`, `field` (one primary + zero-or-more secondary,
reusing the `tag` cardinality validator), and source/section provenance. A `discard`-roled
artifact is retained in the pool but flagged `retrievable: false`. This completes the
artifact routing of P0-5 and the artifact-pool half of P0-8.

## INVEST check

- **Independent:** extends `run_vault_write` to also emit artifact notes; consumes the
  slice-01 classification and reuses the `tag` slice-03 `field` validator.
- **Valuable:** the artifact pool becomes a real, independently queryable Obsidian surface
  — the separation of prose and artifacts (PRD goal 4) made durable on disk.
- **Small:** classify `field` alongside `artifact_role`, serialize an artifact note, add
  the `retrievable` flag; the prose path is untouched.
- **Testable:** run `axial vault write` on a fixture with artifacts incl. one `discard`;
  assert artifact notes under `data/vault/artifacts/`, a `retrievable: false` on the
  discard, prose notes unchanged.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with artifacts including one classified `discard`, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial vault write <fixture>`
Then  one artifact note per artifact appears under data/vault/artifacts/ (a separate surface from data/vault/prose/)
And   each carries `artifact_role`, `field`, and source/section provenance in its frontmatter
And   the `discard`-roled artifact note is present but flagged `retrievable: false`
And   the prose notes are unaffected and re-running is idempotent
```

- **Boundary / endpoint:** CLI command `axial vault write <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_vault_artifacts.py — test-author, red, locked

## Inner loop — initial unit test list

- [ ] classify `field` (primary + ≥0 secondary) for an artifact, reusing the `tag` slice-03 `primary_plus_secondary` validator
- [ ] write an artifact note at `data/vault/artifacts/<artifact_id>.md` with `artifact_role` + `field` + provenance frontmatter
- [ ] a `discard` role sets `retrievable: false`; a non-discard role sets `retrievable: true`
- [ ] the artifact pool and prose pool are distinct directories with shared metadata conventions (P0-8)
- [ ] re-running overwrites an artifact note idempotently rather than duplicating it

## Out of scope for this slice (deferred)

- **`cited_by` backlinks** on artifact notes — the `xref` feature writes these.
- **Prose-note axis frontmatter** — that is `tag` slice 04.
- **Retrieval semantics of `retrievable: false`** — this slice only records the flag; how a
  downstream retrieval pass honours it is out of scope for Phase A.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
