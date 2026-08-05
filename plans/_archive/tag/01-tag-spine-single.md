# Slice 01: Tag spine — `role_in_argument`, schema-driven, hard-error, versioned

- **Feature:** tag
- **Slice slug:** tag-spine-single
- **GitHub issue:** #27
- **Branch:** feat/tag/01-tag-spine-single
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial tag <file>` runs the argumentative-chunking pass internally and, for each prose
chunk, makes one LLM call (`pass_name="tag"`) to assign the `role_in_argument` axis —
a single-value, closed-set axis whose vocabulary is **loaded from the domain schema**,
not hardcoded. Any returned value absent from the schema's `role_in_argument` tag set
raises a hard error (P0-6). Each tagged record carries the chunk's provenance plus the
schema `version` it was tagged under, and is emitted to stdout. This is the tagging
spine: schema load → codebook-driven prompt → LLM tag call → validate-against-schema →
versioned record.

## INVEST check

- **Independent:** consumes chunk records (via `run_chunk`) and the loaded schema; adds
  a new `axial tag` subcommand alongside `axial chunk`, changing no existing pass.
- **Valuable:** the first tag any chunk carries, and the first enforcement of the
  load-bearing P0-6 guarantee (no tag outside the schema, versioned).
- **Small:** one axis, one cardinality (single), one validator, one prompt composer.
- **Testable:** run `axial tag` on a fixture with the stub provider; assert one record
  per chunk, each with an in-schema `role_in_argument` value and a `schema_version`.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source with a stored envelope and its chunk records, and AXIAL_LLM_PROVIDER=stub
When  the user runs `axial tag <fixture>`
Then  it exits 0 and emits one tagged record per chunk as JSON
And   each record carries a `role_in_argument` value drawn from the schema's role_in_argument axis
And   each record carries the `schema_version` it was tagged under, plus its chunk_id and section provenance
```

- **Boundary / endpoint:** CLI command `axial tag <file>` (default domain `config/domains/syria`, `--domain` override)
- **Outer test type:** pytest integration test (subprocess; stub provider)
- **Outer test file (planned):** tests/test_tag.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] the tagger lists the prose axes from the schema (those whose `applies_to` includes `prose`): field, claim_type, empirical_scope, theory_school, role_in_argument
- [ ] composes a tagging prompt for `role_in_argument` from the codebook (each tag's definition + positive/negative example)
- [ ] parses the model's response into an axis→value assignment
- [ ] a `role_in_argument` value present in the schema validates; one absent raises `TagNotInSchemaError` (hard error, names the axis + offending tag)
- [ ] single cardinality: exactly one `role_in_argument` value — zero or multiple is an error
- [ ] each tagged record carries `schema_version`, `chunk_id`, `section`, and `chunk_text` (provenance preserved from the chunk record)
- [ ] a source whose chunking yields zero chunks yields zero tagged records without an LLM tag call

## Out of scope for this slice (deferred)

- **All other axes** — `empirical_scope`/`country` (slice 02), `field`/`claim_type`/`theory_school` (slice 03).
- **Vault persistence** — records are emitted to stdout only (like `axial chunk`); writing axis frontmatter into prose notes is slice 04.
- **Artifact and cross-reference tagging** — the `artifacts` and `xref` features.
- **Model-per-pass selection** — the tag pass uses the same `get_client` seam as chunking.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-08 planned.
