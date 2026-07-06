# feat(schema-loader): CLI walking skeleton — `axial --version` [slice 01]

**Spec:** specs/PRODUCT.md §6, §11.1 · **Plan:** plans/schema-loader/01-cli-skeleton.md
**Depends on:** none
**Labels:** sub:ingestion-v0

## Deliverable

The `axial` package exists under `src/axial` with a console-script entry point:
`uv run axial --version` prints the version declared in pyproject.toml and exits
0. This walking skeleton proves packaging, CLI, tests, and CI end to end; every
later slice builds on it.

## Acceptance criterion

```gherkin
Given the repo with dependencies installed (uv sync)
When  the user runs `uv run axial --version`
Then  it exits 0 and prints the version declared in pyproject.toml
```

## Out of scope

Any subcommand (schema show/validate arrive in slices 02–03); config loading;
pipeline stages.
