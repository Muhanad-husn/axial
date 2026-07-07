# Slice 04: Structural envelope — one LLM call per source, written once

- **Feature:** minimal-ingestion
- **Slice slug:** structural-envelope
- **GitHub issue:** #16
- **Branch:** feat/minimal-ingestion/04-structural-envelope
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial envelope <file>` makes one LLM call per source over its intro/abstract/
conclusion (from the extraction tree) and writes an envelope JSON —
`{source_id, author, title, date, thesis, toc[], scope, stated_argument}` — to
`data/envelopes/`. Re-running for a source that already has an envelope reuses
the stored file rather than recomputing. This is §5 stage 3 / P0-3, and it
introduces the fake-able LLM client seam every downstream LLM stage reuses.

## INVEST check

- **Independent:** consumes an extraction tree; needs no chunking/vault.
- **Valuable:** the envelope is computed once and reused by chunking (and later
  tagging), the efficiency guarantee §10 verifies ("no recompute").
- **Small:** one subcommand + a prompt + the client seam + write-once caching.
- **Testable:** run against a fixture tree with a **stub** LLM client returning a
  canned envelope; assert the JSON file and its fields; assert a second run does
  not call the client again.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given an extracted fixture source and the LLM provider configured to the stub client
When  the user runs `axial envelope <fixture>`
Then  it exits 0 and writes data/envelopes/<source_id>.json with thesis, toc, scope, and stated_argument
And   running `axial envelope <fixture>` again reuses the stored envelope without a second LLM call
```

- **Boundary / endpoint:** CLI command `axial envelope <file>`
- **Outer test type:** pytest integration test (subprocess; stub provider selected via config/env)
- **Outer test file (planned):** tests/test_envelope.py — test-author, red, locked (DEC-1)

## Inner loop — initial unit test list

- [ ] an `LLMClient` protocol exposes a single completion call; a `StubLLMClient` returns fixture-canned output and records call count
- [ ] the provider is selected from `config/pipeline.yaml` (or env override); the stub is selectable without network
- [ ] the envelope pass composes its prompt from the source's intro/abstract/conclusion nodes only (not the whole source)
- [ ] the pass parses the model response into the envelope schema and validates required fields (typed error on malformed)
- [ ] the envelope is written to `data/envelopes/<source_id>.json` with a stable source_id
- [ ] a second run with an existing envelope file short-circuits — zero client calls
- [ ] (real provider) an OpenRouter-backed client builds the correct request; verified with a mocked transport, never called live

## Out of scope for this slice (deferred)

- Chunking's use of the envelope (slice 05); model-per-pass tuning; retries/backoff
  beyond a minimal shape; NVIDIA provider (OpenRouter suffices for v0). Live API
  calls are never made in tests.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (stub provider; no network).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
