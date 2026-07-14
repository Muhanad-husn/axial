---
name: fix
description: The fast lane for a bug or small change that does not warrant a full behavior-first slice. Classifies the work into non-behavioral, behavioral-bug, or feature-scale, routes it to the fixer alone or a stripped test-author->fixer loop, and prepares a PR that pauses for founder approval. Feature-scale work is bounced to /sprint-start. Use when the founder says 'fix this', 'quick fix', or hands over a bug or small change.
---

# Fix — The Fast Lane

Run from the **main session (orchestrator)**. This is the escape hatch from the full
behavior-first ceremony for work too small to warrant a slice: a bug fix, a refactor,
a rename, a config or dependency tweak, a copy change. It **skips the ceremony**
(spec, outer acceptance test, two-stage review) but **keeps every safety gate** — the
change still lands as a PR the founder approves, still runs under the commit gate, and
no one merges but the orchestrator on the founder's word.

Like `/sprint-start`, this is a founder-invoked command, not an auto-triggering
skill. It pauses at the prepared PR.

## Procedure

1. **Classify the work into one of three buckets.** This is the whole judgement call
   of the fix lane; get it right and the rest is mechanical.

   - **Non-behavioral** — no observable behavior changes (refactor, rename, comment,
     config/dependency tweak, formatting, a bug fix the existing suite already
     covers). The existing suite is the oracle.
   - **Behavioral bug** — a real behavior is wrong and no test currently pins the
     correct behavior. Needs one regression test committed red first.
   - **Feature-scale** — new behavior, a new module, many files, or a spec change.
     **Not fix-lane work.** Bounce it to `/sprint-start` (file/scope an issue) and
     stop. This bucket, plus the fixer's own BLOCKED-on-scope-creep report, is the
     guard that keeps the fast lane from becoming the default path.

2. **Cut the branch** from fresh `main`: `fix/<slug>`.

3. **Route it.**

   - **Non-behavioral →** dispatch the **fixer** subagent alone. It makes the change
     under `src/`, confirms the suite stays green, and commits on the `fix/` branch.
   - **Behavioral bug →** a stripped loop: dispatch the **test-author** to write one
     regression test that fails for the right reason, then — **with founder
     approval** — the orchestrator sets `.claude/allow-red-commit`, commits the red
     test, and removes the flag. Then dispatch the **fixer** to green it. The
     test-author clears any red marker on the verified pass. There is no spec pass and
     no two-stage reviewer pass — that is what makes this the fast lane.

4. **Stay in the lane.** If the fixer reports BLOCKED because the change is turning
   feature-scale, stop and route it to `/sprint-start`. Never grow the fix lane into
   a substitute for the pipeline.

5. **Prepare the PR** with `safe-pr`: suite green locally, evidence collected and
   secret-scanned, branch pushed, PR opened into `main`. **The lane stops here.**

6. **Report and pause.** Post the PR link, report `DONE` with the URL. The founder
   reviews. On the founder's explicit **"approved"** — and only then — the
   orchestrator merges (`gh pr merge`) and, on a separate approval, runs
   `/safe-cleanup` on the merged branch.

## Invariants

- The fix lane skips *ceremony*, never *gates*: the commit gate, spec-freeze, merge
  block, and branch protection all still bind. If a gate fires, fix the cause, never
  the hook.
- The fixer writes `src/` only — `tests/` and `specs/` stay hook-blocked, exactly as
  for the implementer. The fixer writes no tests; behavioral regression tests come
  from the test-author.
- One fix = one branch = one PR. Never batch, and never merge without founder
  approval.
- Feature-scale work goes to `/sprint-start`, not here. When in doubt, treat it as a
  slice, not a fix.
- Roles report DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT; concerns and
  blockers go to the PR or issue thread, not private notes.
