# Plan templates

This file holds two templates. Copy the relevant block, fill every `<placeholder>`, and write the result into `plans/<feature-slug>/`. Delete guidance in _italic HTML comments_ from the output.

The **slice plan is the contract** shared across the whole harness: `red-green-refactor` executes it and ticks its status log; `tdd-ci` records the CI workflow in it; `safe-pr` records the PR URL in it. Keep it current.

---

## TEMPLATE A — Feature index → write to `plans/<feature-slug>/README.md`

```markdown
# Feature: <Feature title>

<One-paragraph description of the outcome the user wants and who benefits.>

- **Slug:** <feature-slug>
- **Created:** <YYYY-MM-DD>
- **Status:** planning | in-progress | done
- **New system?** yes (first slice is a walking skeleton) | no
- **Project directory:** <path from the repo root where the app + its package manifest/tests live; `.` if the repo root itself. e.g. `.`, `services/api`, `sandbox/cli-calculator`. All phases run install/test/build from here; the git branch is still cut at the repo root.>

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [<slice-slug>](01-<slice-slug>.md) | <what observable behaviour it delivers> | ☐ todo | — |
| 02 | [<slice-slug>](02-<slice-slug>.md) | <…> | ☐ todo | — |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Out of scope (whole feature)

- <Things explicitly NOT being built, to bound the work.>

## Notes / open questions

- <Anything the team should decide or revisit.>
```

---

## TEMPLATE B — Slice plan → write to `plans/<feature-slug>/<NN>-<slice-slug>.md`

```markdown
# Slice <NN>: <Slice title>

- **Feature:** <feature-slug>
- **Slice slug:** <slice-slug>
- **GitHub issue:** #<NN — the issue this slice delivers; required, issues are the system of record>
- **Branch:** feat/<feature-slug>/<NN>-<slice-slug>
- **Project directory:** <path from repo root where install/test/build run; `.` if repo root>
- **Status:** ☐ todo | ◐ in-progress | ✅ done
- **Walking skeleton?** yes | no

## Goal — the minimum testable behaviour

<One or two sentences. State the single observable behaviour this slice delivers and the value it provides. If you need the word "and", split the slice.>

## INVEST check

- **Independent:** <why it can stand alone>
- **Valuable:** <the user/stakeholder-visible value>
- **Small:** <why it fits well within a day>
- **Testable:** <how "done" is verified>

## Acceptance criterion (outer loop — the failing e2e/integration test)

Written in the user's language. This becomes the **first failing test** of the slice and the definition of done. Name the **real external endpoint** (URL / API call / CLI invocation) — never an internal function.

```gherkin
Given <starting context / state>
When  <the user interacts through the real boundary: e.g. visits /reset, POSTs to /api/x, runs `cli foo`>
Then  <the externally observable outcome>
And   <additional observable outcome, if any>
```

- **Boundary / endpoint:** <CLI command | library entry point | HTTP route | web page at URL>
- **Outer test type:** pytest integration/acceptance test (default) | Playwright (web slices only)
- **Outer test file (planned):** <path under tests/, e.g. tests/test_<feature>_<slice>.py — authored by the test-author role, committed red, then locked (DEC-1)>

## Inner loop — initial unit test list

Seed for the implementer's inner red-green-refactor cycles (unit tests live
co-located under `src/`, e.g. `src/**/test_*.py` — never in `tests/`, which holds
only the locked outer contract). This is a **living list** — `red-green-refactor`
will add to it as design emerges. Order from simplest behaviour to most general.

- [ ] <unit behaviour 1 — e.g. "TokenGenerator produces a 32-char url-safe token">
- [ ] <unit behaviour 2 — e.g. "ResetService rejects an expired token">
- [ ] <unit behaviour 3 — …>

## Out of scope for this slice (deferred)

- <Edge cases, variations, performance, and polish pushed to later slices. This is how the slice stays thin.>

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (with the founder-approved `.claude/allow-red-commit` flag), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete (no duplication, clear names) with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed (spec compliance, then quality).
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits founder approval.

## Status / progress log

<!-- red-green-refactor appends here as it works, one line per behaviour/cycle, so the plan is an audit trail. -->

- <YYYY-MM-DD> planned.
```

---

## Filling guidance

- **Acceptance criterion first.** It is the most important field — it gates the slice. If you can't write a concrete Given/When/Then through a real endpoint, the slice is too vague or horizontal; re-slice.
- **Keep the unit list short and concrete.** Three to six behaviours is typical for a thin slice. Don't try to enumerate everything — the loop discovers more.
- **Out-of-scope is load-bearing.** Explicitly deferring things is what keeps the slice small and prevents gold-plating during development.
- **One slice file per vertical slice.** If a file starts listing two unrelated behaviours, split it into two files and add a row to the README.
- **Set the project directory.** If the app lives in a subfolder (a monorepo package, a `services/<x>` dir, a `sandbox/` smoke-test), record that path so `red-green-refactor`, `tdd-ci`, and `safe-pr` run install/test/build there and CI sets `working-directory` + `cache-dependency-path` correctly. Use `.` when the app is at the repo root. The git branch is always cut at the repo root regardless.
