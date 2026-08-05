# Slice 01: Artifact classification — one `artifact_role` per artifact node

- **Feature:** artifacts
- **Slice slug:** artifact-classify
- **GitHub issue:** #30
- **Branch:** feat/artifacts/01-artifact-classify
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial artifacts <file>` runs structural extraction, collects the non-text artifact nodes
(tree nodes typed `artifact`) with their enclosing-section provenance, and assigns each
exactly one `artifact_role` from the schema's closed Appendix D taxonomy via one LLM call
(`pass_name="artifacts"`). A returned role absent from the schema is a hard error. Each
tagged artifact record — stable `artifact_id`, `artifact_role`, source/section provenance
— is emitted to stdout. This is the routing decision that separates artifacts from prose
(P0-5).

## INVEST check

- **Independent:** consumes the extraction tree (via `extract`) and the loaded schema;
  new `axial artifacts` subcommand, no existing pass touched.
- **Valuable:** the first classification of non-text material — the moment tables and
  figures stop being lost in prose and become a routable, role-tagged pool.
- **Small:** collect artifact nodes, one closed single-value axis, one prompt composer,
  the schema hard-error validator (reused from `tag`).
- **Testable:** run `axial artifacts` on a fixture containing a table/figure; assert one
  record per artifact node with an in-schema `artifact_role` and provenance.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source containing at least one artifact node (a table or figure), and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial artifacts <fixture>`
Then  it exits 0 and emits one record per artifact node as JSON
And   each record carries a stable `artifact_id`, an `artifact_role` drawn from the schema's artifact_role axis, and source/section provenance
And   a stub returning a role absent from the schema exits non-zero with a clear error
```

- **Boundary / endpoint:** CLI command `axial artifacts <file>` (default domain `config/domains/syria`, `--domain` override)
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_artifacts.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] collect the artifact nodes (`type == "artifact"`) from the extraction tree, each paired with its enclosing section's verbatim heading
- [ ] build a stable, deterministic `artifact_id` (`<source_id>_art_<order>`) from the node's unique `order`
- [ ] compose an artifact-classification prompt from the codebook's `artifact_role` entries (definition + examples)
- [ ] parse the role response; exactly one value; in-schema validates, out-of-schema raises the shared `TagNotInSchemaError`
- [ ] `discard` is a valid role and classifies normally (the non-retrievable flag is slice 02)
- [ ] a source with zero artifact nodes emits zero records without an LLM call or an error

## Out of scope for this slice (deferred)

- **Routing to the artifact pool** — records are emitted to stdout only; writing notes to `data/vault/artifacts/` is slice 02.
- **The `field` tag on artifacts** and the `discard` non-retrievable flag — slice 02.
- **Cross-reference backlinks** — the `xref` feature.

## Definition of done

- [x] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [x] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [x] Refactor pass complete with the bar green.
- [x] Slice's tests run in CI.
- [x] Reviewer's two-stage review passed.
- [x] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
- 2026-07-08 red outer test committed `2ab07ed` (locked); implementation `2f158dd` (189 passed); evidence `46264f9`. Reviewer two-stage pass clean. PR #36 opened into `main`; awaiting founder approval.
