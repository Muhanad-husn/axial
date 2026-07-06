# Feature: Schema loader & scaffolding

The `axial` package exists, runs as a CLI, and loads the versioned Syria domain
schema + codebook from config with validation — PRD §11 build phase 1, covering
§6 (scaffold), §7.1 (loader contract), and Appendix G. Runs entirely on the
placeholder codebook; no Academic dependency.

- **Slug:** schema-loader
- **Created:** 2026-07-06
- **Status:** planning
- **New system?** yes (first slice is a walking skeleton)
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | Issue | PR |
|---|-------|-----------------|--------|-------|----|
| 01 | [cli-skeleton](01-cli-skeleton.md) | `uv run axial --version` works end to end (package + CLI + CI thread) | ☐ todo | — | — |
| 02 | [schema-load](02-schema-load.md) | `axial schema show <domain-dir>` lists the axes of the committed Syria schema | ☐ todo | — | — |
| 03 | [codebook-validate](03-codebook-validate.md) | `axial schema validate <domain-dir>` cross-checks schema ↔ codebook, hard-failing on mismatches | ☐ todo | — | — |

## Out of scope (whole feature)

- All pipeline stages (intake, extraction, envelope, chunking, tagging, xref, vault) — later subprojects.
- Schema *content* judgement calls — the placeholder codebook ships as written in PRD Appendices A–G; the gold-set eval revises it.
- Second-domain support beyond "loader takes a domain directory path" (P2-1).

## Notes / open questions

- PRD Open Question: YAML assumed for schema + codebook (confirmed non-blocking, §12).
