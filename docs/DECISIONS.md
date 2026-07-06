# Decision Log

Locked decisions (DEC-1..7) come from the agentic-engineering-org brief and are hard
constraints. Later rows record divergences from the reference skeletons and resolved
ambiguities during the setup build.

| # | Date | Decision |
|---|------|----------|
| DEC-1 | 2026-07-06 | Test authorship is split: the outer acceptance test is the behavioral contract (spec/test-author writes it, committed red, then locked); the implementer drives inner unit cycles only and may not edit the outer test or the specs. |
| DEC-2 | 2026-07-06 | Roles are addressable subagent files in `.claude/agents/`, each with a locked `tools` set and a pinned `model`. |
| DEC-3 | 2026-07-06 | Two deterministic hook gates: *subagents-never-merge* and *tests-green-before-commit*. "Subagents" = role subagents + the GitHub plugin merge tool. The orchestrator (main session) merges and cleans up on explicit founder approval; no global hook blocks its merge path. Merge gate = subagent-scoped frontmatter hooks + a global block on the plugin merge tool only. Branch protection backstops server-side. |
| DEC-4 | 2026-07-06 | GitHub issues and PRs are the system of record. Sprints, not sessions. |
| DEC-5 | 2026-07-06 | One repository. Spec and build are separated by role and a spec-freeze hook, not by folder. |
| DEC-6 | 2026-07-06 | The behavior-first loop is the vendored `brainqub3/red-green-refactor` harness (MIT), adapted to the roles and gates. |
| DEC-7 | 2026-07-06 | GitHub work runs through the installed GitHub plugin (issue/PR tools), not raw `gh` in Bash; the merge gate therefore also matches the plugin's merge tool. |
| DEC-8 | 2026-07-06 | **Build target:** the org is built directly in `D:\axial` (existing repo, remote `Muhanad-husn/axial`), not a separate `ai-enterprise-template` repo. Axial is the first product; `PRODUCT.md` moved to `specs/PRODUCT.md`. Founder chose this at the pre-Phase-0 question. Consequence: `gh repo create` is skipped (remote exists); the Phase 0 "exactly one commit" verify criterion is adapted to "one setup commit on the branch" since the repo pre-existed with one commit. |
| DEC-9 | 2026-07-06 | **Stack profile:** Python 3.13+ / `uv` / `pytest` / `ruff` (the default profile, which is also the PRD's own stack). Test command: `uv run pytest`. Verified locally: uv 0.11.6, Python 3.13.14, Node 24.16 (harness), git 2.49, gh 2.87.3 authenticated. |
| DEC-10 | 2026-07-06 | **GitHub plugin tool names recorded (Phase 0):** namespace `mcp__plugin_github_github__*`. Merge-capable tool for the Phase-3 gate: `mcp__plugin_github_github__merge_pull_request`. Other write-capable tools that can touch `main` directly and must be considered by the gate: `create_or_update_file`, `push_files`, `delete_file` (all can target a branch, including `main`). Issue tools for Phase 5: `issue_write`, `issue_read`, `list_issues`, `search_issues`, `sub_issue_write`, `add_issue_comment`. PR tools: `create_pull_request`, `update_pull_request`, `pull_request_read`, `pull_request_review_write`, `list_pull_requests`. |
| DEC-11 | 2026-07-06 | **Branch protection shape (proposed at Checkpoint 0):** require a PR before merge with `required_approving_review_count = 0` — a solo founder cannot approve their own PR, so requiring 1 review would deadlock every merge; review authority lives in the reviewer subagent + founder approval instead. `enforce_admins = true` (blocks direct pushes to `main` even for the owner). `required_status_checks` deferred to Phase 4, when the `tdd-ci` Actions workflow exists to name as a required check. |
| DEC-12 | 2026-07-06 | `.gitignore` excludes `secrets/secrets.toml`, `.env`, caches, and build output, but **not** `data/` — the PRD's `data/gold/` will hold human-labeled answer keys that are likely worth committing; that call belongs to the sprint that builds gold-set generation. |

## Progress Tracker

| Phase | Status | Date | Notes |
|-------|--------|------|-------|
| 0 — Repository foundation | IN PROGRESS | 2026-07-06 | Skeleton + green baseline on `setup/00-foundation`; awaiting Checkpoint 0. |
| 1 — CLAUDE.md handbook | — | | |
| 2 — Role subagents | — | | |
| 3 — Hard gates (hooks) | — | | |
| 4 — Vendored TDD harness | — | | |
| 5 — Sprint & role wiring | — | | |
| 6 — Dry run & validation | — | | |
