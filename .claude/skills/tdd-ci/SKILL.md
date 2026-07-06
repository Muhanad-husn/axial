---
name: tdd-ci
description: Use once a slice is built and green locally and its unit plus acceptance tests (end-to-end Playwright for web, or integration tests for CLI and API slices) should run automatically in Continuous Integration. Phase 3 of the TDD harness — it detects the stack and the project directory and writes a correct GitHub Actions workflow (for web slices installing Playwright browsers and uploading the report, screenshots, and videos as artifacts; for non-web slices running the integration test; handling subdirectory apps via working-directory), validates it, and commits it. Trigger on 'add a GitHub Actions workflow', 'set up CI', 'run the tests on every PR', 'wire up continuous integration', or 'make these a required check'. Run after red-green-refactor and before safe-pr.
---

# TDD CI — Promote Tests to GitHub Actions (Phase 3)

Once a slice is green locally, make its tests run automatically in CI. This is the enterprise step that turns "passes on my machine" into "the team's main branch is protected by these tests." Keep it a deliberate, separate phase: CI config is infrastructure and deserves its own review.

For the anatomy of a workflow, caching, Playwright-in-CI specifics, and branch-protection guidance, read `references/github-actions-guide.md`. Ready-to-customise templates are in `assets/workflows/`.

> Confirm exact, current `actions/*` versions and runner images with `find-docs`/`ctx7` — action major versions move.

## Preconditions

- The slice's full suite (unit + e2e) passes **locally** first. Do not promote red or unrun tests to CI.
- A git remote on GitHub exists (`git remote -v`). If not, tell the user CI will only take effect once the repo is pushed to GitHub; still write the workflow so it's ready.

## Procedure

1. **Detect the stack, the project directory, and the test commands.** This
   repo's default profile is **Python 3.13 + `uv` + `pytest`** — the test command
   is `uv run pytest -q` and it covers both layers (outer contracts in `tests/`,
   inner unit tests under `src/`). For anything else, reuse the detection from
   `red-green-refactor`'s `references/test-strategy.md`. Read the plan's
   **Project directory** field — if the app lives in a subfolder, the workflow
   must run there (see step 3).

2. **Choose a template** from `assets/workflows/`:
   - `python-ci.yml` — **this repo's default**: uv + pytest (+ ruff), one job
     covering outer contracts and inner unit tests. Non-web slices need nothing
     more.
   - `node-ci.yml` — Node/TS unit tests, if a Node component ever appears.
   - `playwright-e2e.yml` — only for a **web** slice: installs browsers with
     `--with-deps`, runs Playwright, uploads report/screenshots/videos as
     artifacts.

3. **Customise it** to the real project: correct Node/Python version, the actual install + test commands, the e2e start command / `webServer` (web only), and the trigger (push to any branch + `pull_request` targeting `main`). Remove anything that doesn't apply. Don't leave template placeholders behind.

   **If the app is in a subdirectory** (plan's *Project directory* ≠ `.`): set `defaults.run.working-directory` to that path so `run:` steps execute there, and — because `uses:` actions resolve from the repo root — prefix the subfolder on `cache-dependency-path` and on any `upload-artifact` `path:`. The templates carry inline comments showing both; the guide's "Projects in a subdirectory" section explains why. Keep the test command identical to what ran locally from that directory.

4. **Write** the file to `.github/workflows/` with a clear name (e.g. `ci.yml`, or `unit.yml` + `e2e.yml`). Keep unit and e2e as separate jobs (or files) so a reviewer sees both signals distinctly.

5. **Validate.** Check the YAML parses and the syntax is sound (a YAML lint, or `gh workflow view` / `actionlint` if available). Sanity-check that the commands match how the tests actually run locally. If `act` is installed and the user wants a local dry-run, offer it — otherwise validation is static.

6. **Record & commit.** Note the workflow file in the slice plan's Definition-of-Done. Commit with `ci: add GitHub Actions workflow running unit + e2e tests [slice NN]`. **Confirm before pushing** — pushing is outward-facing; `safe-pr` will handle the push as part of opening the PR, so you can leave the commit local and hand off.

7. **Branch protection (founder approval required).** Once the workflow has a
   green run, propose adding it as a *required status check* on `main` (branch
   protection already requires PRs; the check closes the loop so PRs can't merge
   red). Changing branch protection requires founder approval — present the
   `gh api` command and wait for "approved"; then the orchestrator runs it.

## What "good CI for a slice" looks like

- Runs on **push** (fast feedback) and on **pull_request → main** (the gate).
- A **unit job** and an **acceptance job**, each reporting its own status check (a non-web slice may run both in one job if you don't need separate checks).
- For a **web** slice, the Playwright job installs browsers with `--with-deps`, runs headless, and **uploads the HTML report + screenshots + videos** as artifacts even on failure (`if: always()` / `if: ${{ !cancelled() }}`) so reviewers and `safe-pr` can reference them. A **non-web** slice runs its integration test with no browser steps, uploading any captured report/log if useful.
- Correct **working-directory** + repo-root-relative `cache-dependency-path`/artifact paths when the app is in a subdirectory.
- Dependency caching so the pipeline is fast.
- No secrets committed; environment via repo/Actions secrets.

## Hand-off

Once the workflow is committed and valid, recommend `safe-pr` to open the pull request — it will push the branch (triggering this workflow) and assemble the evidence-rich PR. If running under `tdd-harness`, return to the orchestrator.
