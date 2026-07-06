# Slice 01: CLI walking skeleton

- **Feature:** schema-loader
- **Slice slug:** cli-skeleton
- **GitHub issue:** #6
- **Branch:** feat/schema-loader/01-cli-skeleton
- **Project directory:** .
- **Status:** ◐ pr-prepared
- **Walking skeleton?** yes

## Goal — the minimum testable behaviour

`uv run axial --version` prints the package version and exits 0. Proves the
whole thread: installable `src/axial` package, console-script entry point, CLI
argument handling, tests in CI.

## INVEST check

- **Independent:** needs nothing but the repo.
- **Valuable:** establishes the runnable-package skeleton every later slice builds on; de-risks packaging + CI.
- **Small:** an afternoon at most.
- **Testable:** subprocess invocation, observable stdout + exit code.

## Acceptance criterion (outer loop)

```gherkin
Given the repo with dependencies installed (uv sync)
When  the user runs `uv run axial --version`
Then  it exits 0 and prints the version declared in pyproject.toml (e.g. "axial 0.1.0")
```

- **Boundary / endpoint:** CLI command `axial --version`
- **Outer test type:** pytest integration test (subprocess)
- **Outer test file (planned):** tests/test_cli_skeleton.py — authored by the test-author role, committed red, then locked (DEC-1)

## Inner loop — initial unit test list

(co-located under `src/`, e.g. `src/axial/test_cli.py`)

- [ ] `axial.__version__` matches the pyproject version (read via importlib.metadata)
- [ ] CLI parser recognises `--version` and returns the version string
- [ ] CLI main() returns exit code 0 for `--version`

## Out of scope for this slice (deferred)

- Any subcommand (`schema show` arrives in slice 02).
- Config loading, logging setup, pipeline stages.

## Definition of done

- [x] Outer acceptance test authored by the test-author, committed RED (with the founder-approved `.claude/allow-red-commit` flag), seen to fail for the right reason — then locked.
- [x] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [x] Refactor pass complete with the bar green.
- [x] Slice's tests run in CI.
- [x] Reviewer's two-stage review passed.
- [x] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-06 planned.
- 2026-07-06 red outer test committed (724dec6); implementation green (1ac5600); CI green; two-stage review passed (no findings ≥ 80); PR prepared: https://github.com/Muhanad-husn/axial/pull/10 — awaiting founder approval.
