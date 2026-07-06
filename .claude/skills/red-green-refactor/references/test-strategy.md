# Test Strategy — Detecting & Running Unit + E2E Tests

How the `red-green-refactor` skill discovers the project's test tooling, runs the two loops, and configures Playwright so that `safe-pr` has screenshots and recordings to attach. The harness is **stack-agnostic**: detect what the project uses, don't assume.

> When you need exact, current syntax for any framework here (Playwright config keys, a runner's flags), use the `find-docs` skill / `ctx7` rather than relying on memory — versions drift.

## Table of contents

1. The two test layers
2. Detecting the unit runner
3. Detecting / setting up the e2e layer (Playwright)
4. Playwright config for evidence (screenshots + video + trace)
5. Running the loops in practice
6. Watching a test fail for the right reason
7. Branching & commits
8. Non-web projects

---

## 1. The two test layers

| Layer | Purpose | Speed | Scope | Tooling |
|---|---|---|---|---|
| **Unit** (inner loop) | Drive & verify internal design, one behaviour at a time | milliseconds | a class/function, collaborators mocked | the project's unit runner |
| **Acceptance / e2e** (outer loop) | Prove the slice works end-to-end through a real endpoint; gate "done"; produce review evidence | seconds | whole system via its boundary, nothing mocked | Playwright (web) or an integration test against a running service |

Many fast unit tests at the base of the pyramid; a thin layer of e2e on top. Write the e2e test *first* (it defines done) but accumulate mostly unit tests.

## 2. Detecting the unit runner

Inspect the repo before assuming. Common signals:

| Stack | Detect via | Typical run command |
|---|---|---|
| Node / TS | `package.json` `scripts.test`, devDeps for `vitest` / `jest` / `mocha`; `node:test` | `npm test`, `npx vitest run`, `npx jest` |
| Python | `pyproject.toml` / `pytest.ini` / `setup.cfg`; `tests/` | `pytest -q` |
| Go | `*_test.go` | `go test ./...` |
| Ruby | `Gemfile` with `rspec`; `spec/` | `bundle exec rspec` |
| Java | `pom.xml` / `build.gradle` | `mvn -q test` / `./gradlew test` |
| .NET | `*.csproj`, `*Tests.csproj` | `dotnet test` |
| Rust | `Cargo.toml` | `cargo test` |
| PHP | `composer.json` with `phpunit` | `vendor/bin/phpunit` |

**Rule:** prefer the script the project already defines (`package.json` `test`, a `Makefile` target) over inventing a command — it encodes the project's intended invocation. If there is **no** unit runner and the project needs one, installing and wiring it is legitimate work for the slice (especially a walking skeleton). Always run a single test file/case during the inner loop for speed; run the **full** suite before committing.

## 3. Detecting / setting up the e2e layer (Playwright)

The harness standardises on **Playwright** for end-to-end web tests because it captures the screenshots, videos, and traces that make a PR reviewable.

- **Detect:** look for `playwright.config.(ts|js)`, a `@playwright/test` dependency, an `e2e/` or `tests/e2e/` folder.
- **Set up if missing** (web projects): `npm init playwright@latest` (or add `@playwright/test` and a config), then `npx playwright install --with-deps` to get browsers. Confirm exact current steps with `find-docs`/`ctx7`.
- Keep e2e specs in a dedicated folder (e.g. `e2e/`) separate from unit tests so the two suites run independently.

## 4. Playwright config for evidence (screenshots + video + trace)

Configure Playwright so failures *and* the proof-of-success artifacts are captured automatically. `safe-pr` collects these from `playwright-report/` and `test-results/`. A baseline `playwright.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',            // screenshots, videos, traces land here
  reporter: [['html', { outputFolder: 'playwright-report', open: 'never' }], ['list']],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:3000',
    screenshot: 'on',                      // capture a screenshot for every test (evidence of success too)
    video: 'on',                           // REQUIRED for the acceptance run — the harness attaches a recording to the PR; use 'retain-on-failure' only for large non-acceptance suites
    trace: 'on-first-retry',               // full trace for debugging flakes
  },
  // Start the app under test automatically for local e2e runs:
  webServer: {
    command: 'npm run start',              // or the project's dev/serve command
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
```

Notes:
- Set `screenshot: 'on'` (not just `'only-on-failure'`) when you want a screenshot of the **passing** acceptance scenario as positive evidence for the PR. For larger suites, prefer `'only-on-failure'` plus explicit `await page.screenshot(...)` at the key assertion in the acceptance spec.
- `video: 'on'` records every test — the recording of the **passing acceptance run is required** review evidence (`safe-pr` fails loudly when an acceptance slice has no recording). Keep `'on'` for the acceptance project; use `'retain-on-failure'` only for large, non-acceptance suites where artifact size matters.
- The `html` reporter writes a self-contained `playwright-report/` that `safe-pr` commits and links.
- `webServer.command` must be a **real script the project defines** (check `package.json`), not the placeholder shown — Playwright launches it via the OS shell (`cmd.exe` on Windows, `/bin/sh` elsewhere), so make sure it runs on the developer's platform.
- Always confirm the current config surface with `find-docs`/`ctx7` for the installed Playwright version.

In the acceptance spec, take a labelled screenshot at the decisive moment so the evidence is unambiguous:

```ts
test('user resets password and logs in', async ({ page }) => {
  // ... drive the real flow through the UI ...
  await expect(page.getByText('Password updated')).toBeVisible();
  await page.screenshot({ path: 'test-results/evidence/password-reset-success.png', fullPage: true });
});
```

## 5. Running the loops in practice

- **Project directory:** run all install/test/build commands from the plan's **Project directory** — the folder holding the app's package manifest and tests (`.` at the repo root, or a subfolder for a monorepo package / `services/<x>` / a `sandbox/` app). The git branch is still cut at the repo root, and evidence still lands under the repo-root `docs/tdd-evidence/`. Only the run commands change directory. This same path is what `tdd-ci` turns into the workflow's `working-directory` + `cache-dependency-path`.
- **Inner loop:** run just the unit test(s) for the behaviour under development for a fast red→green→refactor rhythm (e.g. `npx vitest run path/to/file` or `pytest path::test`). Run the **full unit suite** before each commit.
- **Outer loop:** run the single acceptance spec (`npx playwright test e2e/<slice>.spec.ts`) to check progress; run the **whole** e2e suite before closing the slice.
- **Full green check:** before committing the slice, run both suites end to end.

## 6. Watching a test fail for the right reason

Never skip the red step. After writing a test, run it and read the failure:
- A **good** red: the assertion fails because the behaviour/feature is genuinely absent (e.g. `expected "Password updated" to be visible`).
- A **bad** red: a compile error, missing import, wrong selector, or harness misconfiguration. Fix the test/harness until it fails for the *intended* reason, then proceed. "If you cannot articulate why a test fails, you do not yet understand the requirement."

## 7. Branching & commits

- One branch per slice: `feat/<feature-slug>/<NN>-<slice-slug>`, cut from an up-to-date `main` (`git switch -c feat/... main`).
- Commit only on green, in small steps. Conventional Commits: `test:` when adding the failing test, `feat:` for the implementation that greens it, `refactor:` for cleanup, `ci:` for workflow changes.
- Never commit a red bar. (Solo across sessions, you may *leave* a red test in the working tree as a resume marker — but don't commit it.)

## 8. Non-web projects

For services without a browser UI, the **outer loop** is an **integration/acceptance test through the real external endpoint** instead of Playwright:
- HTTP API → a test that starts the service and makes real requests (e.g. `supertest`, `pytest` + `httpx`, `requests`), asserting on status/body.
- CLI → a test that invokes the built binary/script as a subprocess and asserts on stdout/exit code.
- Message-driven → publish to the real broker (or a test container) and assert on the consumed result.

These still satisfy the "exercise the system only from the outside, through real endpoints" rule. For PR evidence on non-web slices, `safe-pr` attaches the captured request/response or terminal transcripts in place of screenshots. Use Playwright whenever a browser UI exists, because its recordings make review dramatically easier.
