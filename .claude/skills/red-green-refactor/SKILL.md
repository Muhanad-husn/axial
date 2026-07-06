---
name: red-green-refactor
description: Use to implement one slice test-first with disciplined double-loop TDD under the role system — a LOCKED outer acceptance test (authored by the test-author, committed red) wrapping inner unit-test red, green, refactor cycles driven by the implementer, worked outside-in until the acceptance test is green. Trigger on 'red green refactor', 'TDD this', 'implement slice NN', or working through a plan in plans/. Enforces the discipline literally — never write production code without a failing test, watch every test fail first, minimum code to green, refactor only on green, never touch the outer test.
---

# Red-Green-Refactor — Double-Loop TDD (role-adapted)

Develop **one slice** by driving it outside-in: a failing acceptance test sets the
goal, and inner unit-test red→green→refactor cycles build the code that makes it
pass. Both test layers grow together.

**Read `references/red-green-refactor-philosophy.md` now** if you have not this
session — it is the authoritative rulebook. For test-tooling detection across
stacks, read `references/test-strategy.md` (this repo's profile: Python 3.13 +
`uv` + `pytest`; run tests with `uv run pytest`).

## Role split (DEC-1 — this adaptation's core rule)

Upstream, one agent wrote both test layers. Here authorship is split and
hook-enforced:

| Layer | Where | Author | Locked? |
|---|---|---|---|
| Outer acceptance test | `tests/` | **test-author** role, from the spec | **Yes — committed red, then locked.** Nobody edits it afterward; the implementer is hook-blocked from `tests/` entirely. |
| Inner unit tests | co-located under `src/` (`src/**/test_*.py`) | **implementer** role, during inner cycles | No — they are the implementer's working tool. |

`tests/` holds only outer behavioral contracts. Inner unit tests live next to the
code they drive, under `src/`, where the implementer may write. pytest collects
both (`testpaths = ["tests", "src"]` in `pyproject.toml`).

The one intended red commit is the outer test itself: the test-author asks the
orchestrator, who (with founder approval) sets `.claude/allow-red-commit` for
exactly that commit and removes it immediately after.

## Input

A slice plan `plans/<feature-slug>/<NN>-<slice-slug>.md` (from `tdd-plan`, linked
to a GitHub issue) **and** a red outer acceptance test in `tests/` for this slice.

- No plan → stop; run `tdd-plan` first. **No code before a plan.**
- No outer test → stop; the orchestrator dispatches the **test-author** to write
  and commit it red first. The implementer never writes it.
- Work exactly one slice; never batch slices.

## Setup (once per slice)

1. **Read the plan and the outer test.** Internalise the goal, the acceptance
   criterion (Given/When/Then), and what's out of scope.
2. **Cut the branch** from an up-to-date `main`:
   `feat/<feature-slug>/<NN>-<slice-slug>`. Never develop on `main` (the
   commit-gate hook blocks commits there anyway).
3. **Watch the outer test fail** (`uv run pytest tests/ -q`). Confirm it fails
   *because the feature is absent*, with a readable diagnostic. It is your
   progress meter; it stays red until the slice is done. **If the outer test
   looks wrong — testing the wrong thing, tautological, contradicting the spec —
   STOP.** Report `BLOCKED` and raise a `spec-drift` issue. Never adjust the
   contract to fit the code, never work around it.

## The INNER loop (implementer's domain)

Repeat per behaviour, working inward from the boundary the acceptance test names.
Mock collaborators that don't exist yet to design their interfaces cheaply.

4. **THINK.** Pick the single smallest next behaviour that moves the outer test
   toward green. Add it to the plan's unit test list if new.
5. **RED.** Write one small failing unit test (~5 lines) **co-located under
   `src/`**. Run it; watch it fail for the right reason.
6. **GREEN.** Write the **minimum** code to pass — Fake It / hard-code if unsure.
   Run the unit suite (`uv run pytest src/ -q`) and confirm green. Implement
   nothing no test demands.
7. **REFACTOR (only on green).** Remove duplication, clarify names — without
   changing behaviour. Re-run tests after each small change. If a refactor
   reddens the bar, revert it; do not fix forward.
8. **Log it.** Append one line to the plan's status log; tick the unit-list box.
9. **Step sizing.** Obvious Implementation when confident; Fake It when unsure;
   Triangulate before generalising. On any unexpected red, shrink the step.

Repeat 4–9 until enough code exists for the outer test to pass.

## Close the OUTER loop

10. **Re-run the outer test.** Still red → back to the inner loop. Green → the
    slice's behaviour is demonstrably complete.
11. **Outer refactor** with the whole suite green: cross-module duplication,
    leaky abstractions, names. Re-run the full suite after each change.
12. **Full green check + commit.** `uv run pytest -q` (everything) green, then
    commit in small green-only commits, Conventional style:
    `feat(<feature-slug>): <goal> [slice NN]`. The commit-gate hook enforces
    green — if it blocks you, fix the cause, never bypass.
13. **Capture evidence for `safe-pr`:** redirect the passing outer-test run and a
    real endpoint invocation to transcript files (see `safe-pr`). This stack is
    non-web: transcripts are the evidence; Playwright applies only if a web slice
    ever appears.
14. **Update the plan** status and Definition-of-Done boxes.

## Invariants — must hold at all times

- **The outer test is untouchable.** The implementer never edits, weakens, skips,
  or deletes anything under `tests/` — hook-enforced, and spec drift routes to an
  issue, never an in-place fix.
- No production code without a failing test you watched fail first.
- The bar is green before and after every refactoring; never refactor on red.
- No new behaviour during a refactor.
- **Done = the outer acceptance test is green** and the full suite passes.
- When stuck or surprised by red: shrink the step and run the tests more.

## Hand-off

When the slice is green and committed, report `DONE` to the orchestrator and
recommend: `tdd-ci` (if the workflow doesn't exist yet), then the **reviewer**
role's two-stage review, then `safe-pr` to prepare the PR. The merge itself waits
for founder approval; neither this skill nor any subagent merges.
