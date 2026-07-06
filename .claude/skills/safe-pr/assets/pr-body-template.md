<!--
PR body template for the TDD harness. The collect-evidence.mjs script injects evidence at the EVIDENCE
marker in the Test evidence section below (the lone HTML comment reading EVIDENCE): for a WEB slice that
is embedded screenshots + recording/report links; for a NON-WEB slice (CLI / HTTP API / service) it is
the captured terminal transcripts embedded as code blocks. Fill every <placeholder>, delete the branch of
the "outer test" section that doesn't apply, and delete this guidance comment.
-->

## Summary

<One or two sentences: the slice's behaviour and the value it delivers, in plain language. From the slice plan's Goal.>

- **Feature:** <feature-slug> · **Slice:** <NN> — <slice title>
- **Plan:** `plans/<feature-slug>/<NN>-<slice-slug>.md` (this branch)
- **Type:** feature / bugfix / walking-skeleton

## What changed and why

<Bullet the key changes. Tie each to the behaviour it implements. Explain non-obvious design decisions.>

- <change 1>
- <change 2>

## Acceptance criterion (the outer test)

The slice is defined "done" by this end-to-end test, which was written first, watched fail, and is now green:

```gherkin
Given <…>
When  <… through the real endpoint …>
Then  <observable outcome>
```

- **Boundary exercised:** <URL / API route / CLI command>
- **Acceptance test:** `<path to spec — Playwright spec for web, or the integration/CLI test for non-web>`

## Test evidence

### Unit tests (inner loop)

```
<paste the real unit-test run summary: framework, counts, pass/fail, duration>
```

### Acceptance / end-to-end test (outer loop)

```
<paste the real outer-loop run summary — Playwright for web; the integration/CLI test run for non-web>
```

<!--
EVIDENCE block injected below by collect-evidence.mjs:
  • web slice     → embedded screenshots + links to the recording and HTML report
  • non-web slice → captured terminal transcripts (test run + real endpoint invocation) as code blocks
-->
<!-- EVIDENCE -->

## How to review

1. <Start the app / where to look.>
2. <The key behaviour to exercise.>
3. Read the acceptance test `<path>` — it documents the intended behaviour end-to-end.
4. CI runs the unit + acceptance jobs on this PR (for web slices the Playwright report is also uploaded as a CI artifact).

## Reviewer checklist

- [ ] The acceptance/e2e test exercises a **real external endpoint**, not internal code.
- [ ] Every production change is justified by a test.
- [ ] Unit + e2e suites are green locally and in CI.
- [ ] Code was refactored on green (no obvious duplication, clear names).
- [ ] Scope matches the slice — no gold-plating; deferred items are noted below.
- [ ] Evidence shows the feature actually working (screenshots + recording for web; test-run + real-invocation transcripts for non-web).

## Scope & risk

- **Deliberately deferred (out of scope for this slice):** <from the plan's out-of-scope>
- **Risk / rollout notes:** <migrations, flags, backward-compat, anything to watch>

---
🤖 Built with the red-green-refactor TDD harness. One slice = one red-green-refactor pass = one PR.
