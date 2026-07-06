# GitHub Actions Guide — Running TDD Tests in CI

Reference for the `tdd-ci` skill. Covers workflow anatomy, triggers, caching, Playwright-in-CI, artifact upload, and branch protection. Adapt the templates in `assets/workflows/` to the real project; don't ship placeholders.

> Action major versions (`actions/checkout@v4`, `actions/setup-node@v4`, `actions/upload-artifact@v4`, …) and runner images move over time. Verify the current versions with `find-docs`/`ctx7` or the GitHub Actions docs before committing.

## 1. Anatomy

A workflow is a YAML file in `.github/workflows/`. Key parts:

```yaml
name: CI                      # shows in the Actions tab and as the check name
on:                           # triggers
  push:
  pull_request:
    branches: [main]          # the gate: every PR into main runs this
jobs:
  unit:                       # one job = one status check
    runs-on: ubuntu-latest    # runner image
    steps:
      - uses: actions/checkout@v4
      - ...                   # setup, install, test
```

Each **job** reports its own status check on the PR. Keep **unit** and **e2e** as separate jobs so reviewers see two distinct green/red signals.

## 2. Triggers

- `push:` — run on every push to any branch for fast feedback while developing a slice.
- `pull_request: branches: [main]` — the enforcement gate; this is what branch protection makes *required*.
- Optionally scope with `paths:` to skip CI on docs-only changes, but don't prematurely optimise.

## 3. Caching & speed

- `actions/setup-node@v4` with `cache: 'npm'` (or `pnpm`/`yarn`) caches the package store keyed on the lockfile.
- `actions/setup-python@v5` with `cache: 'pip'`.
- Cache the Playwright browser binaries keyed on the Playwright version to avoid re-downloading (see template). Falls back to a fresh `install --with-deps` on a cache miss.

## 4. Playwright in CI

The non-obvious bits that make e2e reliable in CI:

- **Install browsers with system deps:** `npx playwright install --with-deps` (the `--with-deps` pulls the OS libraries headless Chromium needs on the Ubuntu runner).
- **Start the app under test.** Either rely on Playwright's `webServer` config (it boots the app and waits for the URL) or start it in a prior step. `webServer` is simplest and keeps local and CI consistent.
- **Headless by default** on CI — no extra config needed.
- **Upload artifacts even on failure** so the report/screenshots/videos survive a red run:

```yaml
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() }}        # upload on pass AND fail
        with:
          name: playwright-report
          path: |
            playwright-report/
            test-results/
          retention-days: 14
```

These artifacts are what reviewers download from the Actions run, and what `safe-pr` references alongside the committed evidence.

## 5. Matrix (optional)

Run across versions/browsers when it adds value:

```yaml
    strategy:
      fail-fast: false
      matrix:
        node: [20, 22]
```

Don't add a matrix reflexively — it multiplies cost. Use it when the project genuinely supports multiple runtimes/browsers.

## 6. Secrets & safety

- Never commit secrets. Use repo or environment secrets: `${{ secrets.MY_TOKEN }}`.
- The default `GITHUB_TOKEN` is sufficient for status checks; grant least privilege via `permissions:` if the workflow needs more.
- Pin third-party actions to a major version (or SHA for high-security repos).

## 7. Branch protection (make checks required)

So a PR can't merge while CI is red, make the jobs **required status checks** on `main`. Via the UI: Settings → Branches → add a rule for `main` → "Require status checks to pass before merging" → select the `unit` and `e2e` checks.

Via the API — **confirm with the user first; this changes repo settings.** Pass the rules as a JSON body (portable across shells, and correctly typed — the nested booleans/arrays must not be sent as `-f` raw strings, which the API rejects). Write `protection.json`:

```json
{
  "required_status_checks": { "strict": true, "contexts": ["unit", "e2e"] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
```

then apply, verify, and (if needed) undo:

```bash
gh api -X PUT repos/{owner}/{repo}/branches/main/protection --input protection.json
gh api repos/{owner}/{repo}/branches/main/protection --jq '.required_status_checks.contexts'   # read-back
gh api -X DELETE repos/{owner}/{repo}/branches/main/protection                                   # undo
```

`enforce_admins` is `false` here so a solo maintainer can't lock themselves out; set it to `true` only when the team wants admins held to the same gate. The example requires no approving reviews (`required_pull_request_reviews: null`) — add `{ "required_approving_review_count": 1 }` if the team wants mandatory review. Treat all of this as opt-in: it's an organisational policy decision, not something to apply unprompted.

## 8. Projects in a subdirectory (monorepo / sandbox)

The harness builds apps that aren't always at the repo root — a monorepo package, a `services/<x>` dir, or a `sandbox/` app. The plan's **Project directory** field names that path. Map it into the workflow carefully, because two different path conventions are in play:

- **`run:` steps** honour `defaults.run.working-directory` (set it once at the top of the workflow, or per-job). So `npm ci`, `npm test`, `pytest`, `npx playwright test` all execute in the app dir.
- **`uses:` actions do NOT** honour `working-directory` — their path inputs resolve from the **repo root**. The ones that bite:
  - `actions/setup-node` / `actions/setup-python` **`cache-dependency-path`** → must include the subfolder, e.g. `services/api/package-lock.json`. Without it the cache key is wrong (or the action errors that it found no lockfile).
  - `actions/upload-artifact` **`path:`** → must include the subfolder, e.g. `apps/web/playwright-report/`. Otherwise the evidence upload silently captures nothing.

```yaml
defaults:
  run:
    working-directory: apps/web          # run: steps only
jobs:
  e2e:
    steps:
      - uses: actions/setup-node@v4
        with:
          cache: npm
          cache-dependency-path: apps/web/package-lock.json   # repo-root-relative
      - run: npm ci                                            # runs in apps/web
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() }}
        with:
          path: |
            apps/web/playwright-report/                        # repo-root-relative
            apps/web/test-results/
```

For a root-level app, omit `defaults:` and the subfolder prefixes entirely. Keep the workflow's test command identical to what `red-green-refactor` ran locally from the same project directory.

## 9. Non-web (CLI / API / service) slices in CI

Not every slice has a browser. When the slice's outer loop is an integration test (CLI subprocess, HTTP request against a started service, a consumed queue message) rather than Playwright:

- The **e2e/acceptance job is just another test run** — no `playwright install`, no browser cache, no `webServer`. Often the unit and integration tests run under the same runner (`npm test`, `pytest -q`) in one job; split them into two jobs only if you want two distinct status checks.
- There are **no screenshots/videos** to upload. If the integration test writes useful output (a JUnit/JSON report, a captured request/response log), upload that as the artifact instead, again with `if: ${{ !cancelled() }}`. `safe-pr` attaches captured terminal transcripts as the review evidence for these slices.

## 10. Checklist before committing a workflow

- [ ] Triggers include `pull_request` → `main`.
- [ ] Unit job runs the **same** command the tests run locally (from the project directory).
- [ ] For a subdirectory app: `working-directory` set for `run:` steps, and `cache-dependency-path` + any `upload-artifact` `path:` prefixed with the subfolder (repo-root-relative).
- [ ] Web slice: e2e job installs browsers `--with-deps`, starts the app, runs Playwright, uploads report + `test-results/` with `if: ${{ !cancelled() }}`. Non-web slice: integration test runs without browser steps.
- [ ] Dependency (+ browser, for web) caching configured.
- [ ] No placeholders, no secrets, correct runtime versions.
- [ ] YAML validated (lint / `actionlint` / `gh workflow view`).
