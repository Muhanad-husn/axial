# Feature: Schema-driven axis tagging of prose chunks

PRD build phase 3 (§11), the tagging half: each prose chunk produced by phase-2
chunking is tagged on every axis the domain schema declares for prose —
`claim_type`, `field`, `empirical_scope` (+`country`), `theory_school` `[candidate]`,
and `role_in_argument` — with the vocabulary **loaded from the schema at runtime,
never hardcoded** (PRD §4, §7.1). Any tag the model returns that is absent from the
loaded schema is a hard error, not a silent pass (P0-6). Every tagged note records
the schema `version` it was tagged under. Runs entirely on the committed placeholder
Syria schema/codebook with the stub LLM in tests — **no Academic dependency, no live
network**, the same seam phase 2 established. Covers §5 stage 6 and requirement P0-6.

- **Slug:** tag
- **Created:** 2026-07-08
- **Status:** planning
- **New system?** no (the package, CLI, LLM client seam, schema/codebook loaders, and chunking pass all ship in phases 1–2)
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR. The slices
are organised around **cardinality machinery**, not one-axis-per-slice: because the
tagger reads its vocabulary from the schema, adding an axis of an already-handled
cardinality is data, not code. Each of slices 01–03 adds one `axial tag` behaviour;
slice 04 persists the tags into the vault frontmatter.

| # | Slice | Goal (one line) | Status | Issue | PR |
|---|-------|-----------------|--------|-------|----|
| 01 | [tag-spine-single](01-tag-spine-single.md) | `axial tag <file>` tags `role_in_argument` (single, closed) per chunk from the schema, hard-errors on any out-of-schema tag, stamps `schema_version`, emits records | ☐ todo | [#27](https://github.com/Muhanad-husn/axial/issues/27) | — |
| 02 | [scope-and-country](02-scope-and-country.md) | adds `empirical_scope` (exactly one) + the `scope:country-case`→`country` extra field from the controlled `country_list` | ☐ todo | [#28](https://github.com/Muhanad-husn/axial/issues/28) | — |
| 03 | [primary-secondary-axes](03-primary-secondary-axes.md) | adds `field`, `claim_type` (+subtags), `theory_school` `[candidate]` — the primary+(optional/≥0)secondary validator, data-driven across all three | ☐ todo | [#29](https://github.com/Muhanad-husn/axial/issues/29) | — |
| 04 | [tag-vault-frontmatter](04-tag-vault-frontmatter.md) | prose notes gain the chunk-level axis frontmatter + `schema_version` (Appendix H shape) | ☐ todo | [#31](https://github.com/Muhanad-husn/axial/issues/31) | — |

## Out of scope (whole feature)

- **Artifact tagging** (`artifact_role`, and `field` on artifacts) and its routing to
  the artifact pool — the `artifacts` feature (P0-5).
- **The cross-reference pass** (`artifact_refs`/`cited_by` backlinks) — the `xref`
  feature (P0-7).
- **Gold-set generation and the eval harness** (P0-9/P0-10) — phases 4 and 6. The
  tagger's per-axis output is what the eval will later score, but scoring is not built
  here.
- **Model-per-pass tuning** (a stronger model for tagging) — the tag pass talks to the
  same `LLMClient` interface as envelope/chunking; provider/model selection is
  config-driven and out of scope for these slices (tracked by issue #23).
- **Live API calls in tests** — every outer and unit test runs against the stub/record
  LLM client selected via `AXIAL_LLM_PROVIDER`; CI never touches the network.

## Notes / open questions

- **Domain-dir resolution.** The tagger needs a domain *directory* (schema + codebook).
  It resolves it from `config/pipeline.yaml` (`paths.domain_dir`, added in slice 01),
  defaulting to `config/domains/syria`, with a `--domain` CLI override — mirroring how
  `envelope`/`vault` read `paths.*` from pipeline.yaml. No code path branches on country
  (PRD §4).
- **Tag pass LLM seam.** The tag pass identifies itself to the stub/record client with
  `pass_name="tag"` (mirroring `CHUNK_PASS_NAME`), so the stub returns a tag-shaped
  canned response without any marker leaking into a real prompt. Slice 01 adds a
  `TAG_PASS_NAME` constant and the stub's canned tag response. The hard-error path
  (an out-of-schema tag) needs a test seam that injects a bad tag — either a second
  canned response keyed off a fault-injection env var or a dedicated stub; the
  test-author picks the mechanism. Unit tests cover the validator directly regardless.
- **Prompt is codebook-driven.** The tagging prompt for an axis is composed from
  `codebook.yaml` — each tag's `definition` + `positive_example` + `negative_example`
  (PRD §7.1, "both the tagger's reference and the labeling instrument"). Slice 01
  establishes the prompt-composition for one axis; later slices reuse it.
- **`vault write` composes the tagger.** In slice 04, `run_vault_write` runs the tagger
  internally (which runs the chunker), exactly as it runs the chunker today — the source
  goes in one end and tagged prose notes come out. No standalone `axial ingest`
  orchestrator is introduced (deferred, per the phase-2 feature notes).
