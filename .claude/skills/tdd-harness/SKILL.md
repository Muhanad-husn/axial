---
name: tdd-harness
description: Use whenever a feature, bugfix, or change should be taken from idea to a reviewable pull request through the role-driven TDD pipeline — spec contract, red outer acceptance test, inner unit cycles, two-stage review, evidence-rich PR, all under the merge and tests-green gates. Coordinates the tdd-plan, red-green-refactor, tdd-ci, and safe-pr skills across the role subagents. Triggers on 'build X with TDD', 'take this idea to a PR', or 'run the harness'.
---

# TDD Harness — Role-Driven Orchestration

Run from the **main session (orchestrator)**. Shepherd one issue through the
pipeline, dispatching each stage to its role subagent and **enforcing the gate
between stages**. You do not write feature code ad hoc; you drive the pipeline.

If you have not internalised the discipline this session, read
`red-green-refactor/references/red-green-refactor-philosophy.md` first.

## The pipeline (roles in bold)

```
 idea → GitHub issue (triage)
   → behavioral contract in specs/            (**spec-author**, spec-mode window)
   → plans/<feature>/ slice plans             (tdd-plan, orchestrator)
   → outer acceptance test, committed RED     (**test-author**, allow-red-commit flag)
   → inner red→green→refactor cycles          (**implementer**, red-green-refactor skill)
   → CI workflow                              (tdd-ci, once per repo/feature)
   → two-stage review                         (**reviewer**: spec compliance, then quality)
   → evidence-rich PR into main, NOT merged   (safe-pr)
   → founder approval → orchestrator merges → safe-cleanup on approval
```

| Stage | Who | Gate before advancing |
|---|---|---|
| Issue exists | triage / founder | Issue scoped with acceptance criteria |
| Spec contract | spec-author (founder opens the spec-mode window) | Founder approves the contract |
| Slice plans | orchestrator via `tdd-plan` | Founder signs off the slice list |
| Outer test red | test-author; orchestrator sets `.claude/allow-red-commit` for that one commit, with founder approval, and removes it after | Outer test committed, seen red for the right reason, now **locked** |
| Implement | implementer via `red-green-refactor` | Outer test green; full suite green locally |
| CI | orchestrator via `tdd-ci` | Workflow valid, committed, Actions run green |
| Review | reviewer (read-only, two-stage) | Stage 1 (spec compliance) passed; findings addressed or logged |
| PR | `safe-pr` | PR open with evidence; **not merged** |
| Merge + cleanup | **orchestrator, only on the founder's explicit "approved"** | — |

## Gates you must enforce (do not skip)

- **No code before a plan; no plan before a spec; no implementation before the
  red outer test.** The commit history must show the red contract preceding any
  implementation commit.
- **The outer test is locked once committed red** (DEC-1). If the implementer
  says it looks wrong, that is spec drift: file a `spec-drift` issue for the
  founder; never let anyone adjust the contract to fit the code.
- **No CI promotion before local green. No PR before green + review.**
- **Subagents never merge** — the hooks make this physical, not advisory. The
  PR stops the pipeline; only founder approval resumes it, and then the
  orchestrator itself runs the merge and, after a separate approval, cleanup.
- **One slice at a time.** One slice = one branch = one PR.

## Conventions (single source of truth)

- **Plans:** `plans/<feature-slug>/README.md` + `<NN>-<slice-slug>.md`, each
  linked to its GitHub issue.
- **Branches:** `feat/<feature-slug>/<NN>-<slice-slug>`, cut from fresh `main`.
- **Outer tests:** `tests/` (test-author only). **Inner unit tests:**
  `src/**/test_*.py` (implementer).
- **Evidence:** `docs/tdd-evidence/<feature-slug>/<NN>-<slice-slug>/`.
- **Commits:** small, green-only (hook-enforced), Conventional style,
  `[slice NN]` suffix.
- **Statuses:** every dispatched role reports DONE / DONE_WITH_CONCERNS /
  BLOCKED / NEEDS_CONTEXT; concerns go to the issue thread.

## When the user only wants one phase

Each phase skill is self-sufficient (`/tdd-plan`, `/red-green-refactor`,
`/tdd-ci`, `/safe-pr`, `/safe-cleanup`) — honour a direct invocation and don't
force the whole pipeline. Role boundaries and gates still apply; they are hooks,
not conventions.
