---
name: tdd-plan
description: Use at the START of any new feature, product, bugfix, or change, before writing code, to decompose it into thin vertical slices (each the smallest end-to-end testable behaviour that delivers value) and write a markdown execution plan per slice into the plans/ folder. Phase 1 of the TDD harness. Trigger on 'slice this up', 'what is the smallest first step', 'plan this test-first', 'write a TDD plan', or any request to build something where the slices should be identified first. Each plan becomes the contract the red-green-refactor skill then executes.
---

# TDD Plan — Slice & Plan (Phase 1)

Turn a request into a set of **thin vertical slices**, each captured as a markdown execution plan in `plans/`. A good slice is the smallest change in system behaviour that is independently valuable and testable end-to-end. The plan you write here is the contract the `red-green-refactor` skill executes next, and that `tdd-ci` and `safe-pr` later read — so make it precise.

**Slicing is the hardest and most valuable judgement in TDD.** "Sequencing the tests properly is a skill — pick tests that drive you quickly to the salient points in the design." Take your time here.

For the full slicing toolkit — vertical-vs-horizontal, INVEST, the walking skeleton, and nine concrete splitting patterns with a worked example — read `references/slicing-guide.md`.

## Procedure

1. **Understand the request.** Restate the feature/outcome in one or two sentences. Ask only the questions that change the slicing: who the user is, the externally observable behaviour, the boundary it goes through (web UI, HTTP API, CLI), and any hard constraints. Don't over-interrogate.

2. **Detect the context.** Is this a brand-new system or a change to an existing one? Look at the repo (build tooling, existing tests, frameworks). If there is **no working build/test/deploy path yet**, the first slice must be a **walking skeleton**: the thinnest end-to-end thread that builds, runs, and is tested through real infrastructure — it de-risks architecture and CI before any real feature content.

   Also note **where the app lives** relative to the repo root — the *project directory*. It is `.` for a single app at the root, or a subfolder for a monorepo package / `services/<x>` / a `sandbox/` smoke-test. Record it in every plan (see the template field): the later phases run install/test/build there and CI keys `working-directory` + `cache-dependency-path` off it. The git branch is always cut at the repo root regardless.

3. **Slice vertically.** Decompose into an ordered list of slices, each cutting through all the layers it needs (UI → logic → persistence) to deliver one observable behaviour. **Never slice horizontally** (a "build the DB layer" slice has no independent value and can't be tested end-to-end — reject it). Use the splitting patterns in the guide. Order slices so the earliest ones de-risk the most and each builds on the last.

4. **Validate every slice against INVEST** — Independent, Negotiable, Valuable, Estimable, Small, Testable. If a slice isn't Small and Testable, split it again. If it has no discernible value, drop it. Aim for slices a developer could finish in well under a day.

5. **Write the plans.** Create `plans/<feature-slug>/`:
   - A `README.md` index/status board from the **Feature index template** in `assets/plan-template.md`, listing all slices in order with status.
   - One `<NN>-<slice-slug>.md` execution plan per slice from the **Slice plan template** in the same file. `<NN>` is the zero-padded order (`01`, `02`, …).
   - **Link each plan to its GitHub issue** (the template's *GitHub issue* field). In this workflow, GitHub issues are the system of record: a slice plan without an issue is not schedulable. If the issues don't exist yet, `/sprint-plan` files them and back-fills the links.
   - Fill in every section. The crucial ones: the **acceptance criterion** written as a Given/When/Then that becomes the slice's failing outer acceptance test (authored by the **test-author** role, committed red, then locked — DEC-1), and the **initial unit test list** that seeds the implementer's inner loop (inner unit tests live co-located under `src/`, not in `tests/`). These don't have to be exhaustive — the test list is living — but they must pin down "done".

6. **Confirm and hand off.** Show the founder the slice list (titles + one-line goals + the proposed first slice). Get sign-off before any code is written — plan approval is one of the three human moments. Then the pipeline continues per `tdd-harness`: test-author commits the red outer test, the implementer runs `red-green-refactor` on slice `01`.

## What makes a plan good

- **One behaviour per slice.** If you can't state the slice's value in a single sentence, it's too big.
- **The acceptance criterion is concrete and observable** from outside the system — it names the real endpoint (a URL, a CLI invocation, an API call), not an internal function.
- **Out-of-scope is explicit.** Listing what a slice deliberately defers is how you keep it thin and stop gold-plating.
- **The plan is executable by someone else.** The `red-green-refactor` skill should be able to start solely from the plan file.

## Output

Plans only. Do not write production or test code in this phase — that is `red-green-refactor`'s job. The deliverable is `plans/<feature-slug>/` populated with a README index and one plan per slice, plus a short summary to the user of the slices and the recommended first one.
