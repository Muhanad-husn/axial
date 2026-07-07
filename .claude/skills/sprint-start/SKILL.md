---
name: sprint-start
description: Start executing the next sprint issue - selects the next unblocked issue by dependency, then drives the role subagents through the TDD harness for it - test-author commits the red outer test, implementer greens inner cycles, reviewer runs the two-stage review, safe-pr prepares the PR - and stops at the prepared PR for founder approval. Use when the founder says 'start the sprint', 'next issue', or 'continue the sprint'.
---

# Sprint Start — Drive One Issue Through the Roles

Run from the **main session (orchestrator)**, ideally fresh (`/clear` first —
sprints replace sessions; the issue and its plan carry all context). Take exactly
**one issue** from selection to a prepared PR. No manual git by the founder, no
merge by anyone until the founder approves.

The session is **bookended by two briefs the orchestrator writes to the founder** —
a kickoff before any code, a wrap-up at the pause. Each is short and dual-register:
a plain-language part the founder can follow without reading code, and a technical
part with the real names and mechanics. These are the founder's window into a
session that otherwise runs mostly inside subagents.

## Procedure

1. **Select the issue.** List open sprint issues via the GitHub plugin
   (`list_issues`, filtered on the `sub:<subproject>` label). Pick the first one
   whose `Depends on:` issues are all closed and which carries no `blocked` /
   `needs-context` label. Confirm the pick with the founder if more than one
   candidate is equally next.

2. **Load the contract.** Read the issue, its linked slice plan
   `plans/<feature>/<NN>-<slice>.md`, and the spec section it cites. If the spec
   contract is missing or stale, stop: that is spec-author work in a
   founder-opened spec-mode window — report `NEEDS_CONTEXT`.

3. **Kickoff brief.** Before cutting the branch, write the founder a short brief on
   what this session will build. Two registers, no ceremony:
   - **In plain language** (2-3 sentences, no jargon): what capability the product
     gains and why it matters — the behavior a user would notice.
   - **Technically:** the issue number and title, the slice, the behavioral change,
     the key files/modules it will touch, and the shape of the acceptance test that
     will pin it down.
   - **Done when:** the acceptance criterion, in one line.

4. **Cut the branch** from fresh `main`: `feat/<feature-slug>/<NN>-<slice-slug>`.

5. **Outer test (test-author).** Dispatch the **test-author** subagent: write the
   outer acceptance test in `tests/` from the spec + acceptance criterion, watch
   it fail for the right reason. Then, **with founder approval**, the
   orchestrator sets `.claude/allow-red-commit`, has the red contract committed
   (`test(<feature>): red outer acceptance test [slice NN]`), and removes the
   flag. The contract is now locked — this commit must precede every
   implementation commit.

6. **Implement (implementer).** Dispatch the **implementer** subagent with the
   `red-green-refactor` skill: inner unit cycles (tests co-located under `src/`)
   until the outer test is green, full suite green, green-only commits. If it
   reports the contract looks wrong: file a `spec-drift` issue, label this issue
   `blocked`, and stop for founder adjudication.

7. **CI.** Ensure `.github/workflows/ci.yml` covers the suite (it does by
   default; `tdd-ci` only if something new is needed) and the Actions run on the
   branch is green.

8. **Review (reviewer).** Dispatch the **reviewer** subagent: two-stage review —
   spec compliance (including "does the outer test encode the spec's intent, and
   was it untouched since its red commit?") then code quality. Findings ≥ 80
   confidence go to the issue thread. Route fixes back to the implementer;
   re-review until stage 1 passes and stage 2 findings are addressed or logged.

9. **Prepare the PR** with `safe-pr`: transcripts collected, secret-scanned,
   committed; PR body generated; branch pushed; PR opened into `main` with
   `Closes #<issue>`. **The pipeline stops here.**

10. **Wrap-up brief, then report and pause.** Before the status line, write the
    founder a short close-out brief that mirrors the kickoff — same two registers:
    - **In plain language:** what the product can now do that it couldn't at the
      session's start, framed as the observable behavior.
    - **Technically:** what was actually built — the acceptance test now green, the
      files/modules added or changed, notable design choices, and any review
      findings or concerns carried on the issue.
    - **State:** did the plan hold, or did the build diverge (spec drift raised,
      slice narrowed, follow-up filed)? Name it plainly.

    Then post the PR link to the issue and report `DONE` with the PR URL. The
    founder reviews. On the founder's explicit **"approved"** — and only then — the
    orchestrator merges (`gh pr merge`) and, after a separate approval, runs
    `/safe-cleanup` on the merged branch.

## Invariants

- **No implementation commit precedes the slice's red outer test commit** — the
  audit trail must show red first.
- One issue = one branch = one PR. Never batch.
- **Both briefs are mandatory** — a kickoff before the branch is cut, a wrap-up at
  the pause. Each carries a plain-language part and a technical part. No session
  runs dark.
- Roles report DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT; concerns and
  blockers go to the issue thread, not private notes.
- Subagents never merge (hook-enforced); the orchestrator merges only on the
  founder's word. If any step tries to bypass a gate, fix the cause, never the
  hook.
- Label discipline: `blocked` / `needs-context` / `done-with-concerns` /
  `spec-drift` reflect reality on the issue at all times.
