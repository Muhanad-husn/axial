# Feature: Minimal ingestion pipeline

PRD build phase 2 (§11): the thinnest end-to-end ingestion thread — intake →
structural extraction (docling, Unstructured fallback) → structural envelope →
argumentative chunking → Obsidian prose-pool write — running entirely on the
committed placeholder Syria schema/codebook with **no Academic dependency**.
Covers §5 stages 1–4 + the prose half of stage 7, and requirements P0-1, P0-2,
P0-3, P0-4, P0-8. Axis *tagging* (P0-5/6/7, artifacts, cross-refs) is phase 3 and
out of scope here; these slices produce structurally-chunked prose notes that
phase 3 will tag.

- **Slug:** minimal-ingestion
- **Created:** 2026-07-06
- **Status:** planning
- **New system?** no (phase-1 walking skeleton already ships the package, CLI, test harness, and CI)
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR. Each adds
one CLI stage subcommand and builds on the previous stage's output.

| # | Slice | Goal (one line) | Status | Issue | PR |
|---|-------|-----------------|--------|-------|----|
| 01 | [intake](01-intake.md) | `axial intake <file>` accepts PDF/DOCX with a real text layer, rejects everything else with a logged reason | ☑ in review | [#13](https://github.com/Muhanad-husn/axial/issues/13) | [#19](https://github.com/Muhanad-husn/axial/pull/19) |
| 02 | [structural-extraction](02-structural-extraction.md) | `axial extract <file>` runs docling → a hierarchical tree separating prose from artifacts | ☐ todo | [#14](https://github.com/Muhanad-husn/axial/issues/14) | — |
| 03 | [extraction-fallback](03-extraction-fallback.md) | on docling failure/degenerate output, `axial extract` falls back to Unstructured, logged | ☐ todo | [#15](https://github.com/Muhanad-husn/axial/issues/15) | — |
| 04 | [structural-envelope](04-structural-envelope.md) | `axial envelope <file>` makes one LLM call/source → an envelope JSON, written once | ☐ todo | [#16](https://github.com/Muhanad-husn/axial/issues/16) | — |
| 05 | [argumentative-chunking](05-argumentative-chunking.md) | `axial chunk <file>` chunks prose with the stored envelope + surrounding sections in context, stable chunk_ids + provenance | ☐ todo | [#17](https://github.com/Muhanad-husn/axial/issues/17) | — |
| 06 | [vault-write](06-vault-write.md) | `axial vault write <file>` writes prose-pool notes with source+section+chunk frontmatter (axis tags deferred to phase 3) | ☐ todo | [#18](https://github.com/Muhanad-husn/axial/issues/18) | — |

## Out of scope (whole feature)

- **All axis tagging** — claim-type/field/empirical-scope/theory-school/role-in-argument
  tags on chunks (P0-6), artifact classification & routing (P0-5), and the
  cross-reference pass (P0-7). These are phase 3. Phase-2 vault notes carry
  structural frontmatter only; the axis-tag frontmatter fields are added by phase 3.
- **Gold-set generation and the eval harness** (P0-9/P0-10) — phases 4 and 6.
- **Google Drive source connector** (P0-11) — sources are read from a local path
  in phase 2; the Drive front-end is a later slice/feature.
- **Live API calls in tests** — inference is API-based (§3/§12) but every outer and
  unit test runs against a fake/stub LLM client selected via config; CI never
  touches the network.
- **A single `axial ingest` orchestrator** chaining all stages — each stage is its
  own subcommand in v0 (mirroring `schema show`/`validate`); an end-to-end
  orchestrator can come later once the stages are proven.
- **Long-section handling (P1-1), κ metrics (P1-2), batch/resume (P1-4)** — nice-to-haves.

## Notes / open questions

- **LLM client seam (slices 04–05).** Envelope and chunking need API-based
  inference. Slice 04 introduces the client interface plus a fixture-backed
  **stub** provider used by all tests; a thin real provider (OpenRouter) sits
  behind the same interface, unit-tested with a mocked transport, never called
  live in CI. Slice 05 reuses the interface — it does not rebuild it.
- **`config/pipeline.yaml`** (providers, model-per-pass, paths) is introduced in
  slice 04 when the first stage needs provider config; earlier stages need no config.
- **Vault frontmatter completeness.** Phase-2 notes deliberately omit the
  chunk-level axis tags and `schema_version` stamp — those are recorded at tagging
  time in phase 3 (§7.1). Slice 06 writes source-level + section-level metadata,
  `chunk_id`, `chunk_text`, and section provenance only.
- **Fixtures.** Slices need small born-digital fixture files (a text-layer PDF, a
  DOCX, an image-only/no-text PDF, an unsupported file, and a PDF carrying a table
  or figure for the prose/artifact split). The test-author creates them under
  `tests/fixtures/`.
