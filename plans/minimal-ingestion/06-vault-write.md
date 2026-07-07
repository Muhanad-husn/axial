# Slice 06: Vault write — prose-pool notes with structural frontmatter

- **Feature:** minimal-ingestion
- **Slice slug:** vault-write
- **GitHub issue:** #18
- **Branch:** feat/minimal-ingestion/06-vault-write
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial vault write <file>` takes the chunk records for a source and writes one
Obsidian prose-pool note per chunk to `data/vault/prose/`, each carrying valid
YAML frontmatter with **source-level** metadata (from the envelope), the
**section-level** verbatim label, and **chunk-level** `chunk_id` + `chunk_text` +
section provenance. This closes the minimal end-to-end thread (§5 stage 7 prose
half / P0-8): a source goes in one end, structured prose notes come out the other.

## INVEST check

- **Independent:** consumes chunk records + the envelope; the terminal stage.
- **Valuable:** the first queryable artifact of the whole pipeline — a real
  Obsidian prose pool a human can open and browse.
- **Small:** a frontmatter serializer + a per-chunk file writer into the prose pool.
- **Testable:** run the full local thread on a fixture and assert note files exist
  in `data/vault/prose/` with well-formed three-level (minus tags) frontmatter.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and its chunk records, stub LLM provider
When  the user runs `axial vault write <fixture>`
Then  it exits 0 and writes one prose note per chunk under data/vault/prose/
And   each note has valid YAML frontmatter carrying source-level metadata, the section label, chunk_id, and chunk_text
And   the prose pool is a separate surface from data/vault/artifacts/ (which stays empty this phase)
```

- **Boundary / endpoint:** CLI command `axial vault write <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_vault_write.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] frontmatter serializer emits valid YAML for source-level fields (author, title, date, thesis, scope from the envelope)
- [ ] frontmatter carries the section-level verbatim label and chunk-level `chunk_id` + `chunk_text` + section provenance
- [ ] one file is written per chunk under `data/vault/prose/`, named by `chunk_id`
- [ ] the prose pool and the (empty) artifact pool are distinct directories with shared metadata conventions
- [ ] re-running overwrites/updates a chunk's note idempotently rather than duplicating it
- [ ] the note body contains the chunk text below the frontmatter (a readable Obsidian note)

## Out of scope for this slice (deferred)

- **All axis-tag frontmatter** (claim_type/field/empirical_scope/theory_school/
  role_in_argument) and the `schema_version` stamp — recorded by phase-3 tagging (§7.1).
- The artifact pool's *contents*, artifact notes, and `cited_by`/`artifact_refs`
  backlinks (phase-3 cross-reference pass, P0-7). This slice may create the empty
  artifact directory but writes nothing into it.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
