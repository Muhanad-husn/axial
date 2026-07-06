---
name: safe-cleanup
description: Use to safely clean up stale LOCAL feature branches left behind by the TDD harness once their slices have shipped — both merged branches and abandoned (closed-PR) branches. Phase 5 maintenance and the cleanup companion to safe-pr. It reports first, confirms before deleting, never force-deletes unmerged work, never touches the remote, and never deletes main, the current branch, or any branch with an open PR. Trigger on 'clean up merged branches', 'delete stale feature branches', 'tidy up branches', 'prune local branches', or after a PR merges. Records every deleted branch's SHA so anything is recoverable.
---

# Safe Cleanup — Tidy Stale Local Branches (Phase 5)

Remove the per-slice `feat/<feature>/<NN>-<slice>` branches that pile up after slices ship — **safely**. Same posture as `safe-pr`: report first, confirm before deleting, never force away unmerged work, keep everything recoverable. **Scope is LOCAL branches only** by design; this skill never deletes anything on the remote.

The deterministic classification (cross-referencing git merge status and `gh` PR state) lives in `scripts/classify-branches.mjs`. It defaults to dry-run and deletes nothing without `--apply --yes` plus the category you approve.

## What counts as what

| Bucket | Meaning | Default action |
|---|---|---|
| **merged** | Commits already in the base (ancestor), or PR merged **and** `git cherry` confirms every commit is present in the base | Eligible to delete (after you confirm) |
| **ahead-of-merged-pr** | PR merged, but the branch carries extra commits **not** in the base (reused branch name, or commits pushed after the merge) | **Never delete** — report only |
| **abandoned** | PR was closed **without** merging — carries commits not in the base | Delete only if the user explicitly opts in; recoverable via reflog / the log only |
| **open-pr** | Has an open PR — active work (wins even if the branch is an ancestor of the base) | **Never delete** |
| **local-only** | Unmerged local commits, no PR (possible WIP) | **Never auto-delete** — report only |
| **protected** | base / `main`/`master`/`develop`/`release`, the current branch | **Never delete** |

If `gh` or the remote is unavailable, PR-based buckets (squash-merged, abandoned) can't be detected — only **git-merged** branches are eligible, and the report says so. That is the safe default.

## Procedure

1. **Freshen `main` first** (so "merged into main" is accurate). If there's a remote, `git fetch origin` and fast-forward `main`. Then run from the repo root, ideally with `main` checked out (the current branch is always protected, so checking out `main` lets a feature branch become eligible). The script **refuses to run on a detached HEAD**, since the current branch must be well-defined to protect it.

2. **Dry-run report.** Run the classifier — it deletes nothing:

   ```
   node "${CLAUDE_SKILL_DIR}/scripts/classify-branches.mjs"
   ```

   Show the user the table and the summary (how many merged / abandoned / kept).

3. **Confirm with the founder — approval is the only gate.** Explain the buckets
   in plain terms:
   - The **merged** branches are safe to delete — their work is in `main` (or their PR merged).
   - The **abandoned** branches carry commits that are **not** in `main`; deleting them drops that work (recoverable only via `git reflog` for a limited window). Only proceed with these if the founder explicitly says so.
   - **open-pr** and **local-only** branches are kept untouched.
   Get an explicit "approved" for the merged set, and a **separate** explicit
   approval for the abandoned set. On approval the **orchestrator** (main
   session) runs the deletion itself — never a build subagent (branch deletion
   is hook-blocked for them), and never the founder's own terminal.

4. **Apply.** Delete only the approved categories, writing a recovery log:

   ```
   node "${CLAUDE_SKILL_DIR}/scripts/classify-branches.mjs" --apply --yes --delete-merged
   ```

   A recovery log (`.tdd-branch-cleanup.log` at repo root by default, or `--log <path>`) is written **before** any deletion, and the run aborts if it can't be written. Add `--delete-abandoned` **only** if the user approved removing abandoned branches. Add `--protected name1,name2` to shield extra branches, or `--base <branch>` if the base branch isn't auto-detected.

5. **Report.** Tell the user which branches were deleted and surface the recovery block (each `branch → SHA`). Restoring any of them is just `git branch <name> <sha>` (or via `git reflog`). The recovery log persists this for later.

6. **Optional bookkeeping.** If a deleted branch's slice plan still says in-progress, update `plans/<feature>/<NN>-<slice>.md` / the feature README to reflect that the slice is merged and its branch cleaned.

## Safety rules (non-negotiable)

- **Local only.** Never run `git push origin --delete` or otherwise touch remote branches from this skill. Removing a shared remote branch is a deliberate, separate action the user must drive themselves.
- **Never delete** `main`/the default branch, the current branch, protected branches, or any branch with an **open PR**.
- **Never force-delete unmerged local work** (`local-only` with unique commits) — report it and let the user decide per-branch.
- **Use the safe delete** (`git branch -d`) for git-merged branches; fall back to `-D` only for branches confirmed merged via their PR, or for abandoned branches the user explicitly approved — and always log the SHA first.
- **Dry-run is the default.** Never pass `--apply` until the user has seen the report and confirmed.
- **Merged-safe means genuinely merged.** A branch is only treated as deletable-merged if its commits are truly in the base — an ancestor, or `git cherry` confirms every commit is patch-present. A branch with extra commits beyond its merged PR is kept, never force-deleted (this defeats branch-name reuse and post-merge commits). Force-deletes are re-verified at the moment of deletion.
- **Refuses to run on a detached HEAD**, so the current branch is always well-defined and protected.
- Confirm before deleting, exactly as `safe-pr` confirms before pushing.

## When to run

After PRs merge — e.g. straight after `safe-pr` reports a merge, or periodically to tidy up. It pairs with `safe-pr`: `safe-pr` opens the PR for a slice; `safe-cleanup` retires the branch once that PR is done. You can also schedule it with the `loop` or `schedule` skills if you want routine tidying.
