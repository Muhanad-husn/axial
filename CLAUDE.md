# Axial Engineering Handbook

## What this is

A one-operator AI software enterprise. The founder (the human running the main
session) specifies and decides; tool-locked role subagents build and check; two
deterministic hook gates hold the line. The product currently being built is Axial
(see `specs/PRODUCT.md`), but nothing in this handbook is specific to it.

Two rules answer most questions:

1. **Who may merge?** Nobody merges without founder approval, and no subagent merges
   at all. When a branch's work is complete, the founder says "approved"; the
   *orchestrator* (the main session, not a subagent) then runs the merge and the
   branch cleanup itself. Approval is the gate, not founder execution: the founder
   never has to run commands, and the orchestrator never merges unasked.
2. **Who may edit specs, and when?** Only the spec-author role, and only outside
   implementation. While an issue is being implemented, `specs/` is frozen by a hook.
   If the build reveals the spec is wrong, nobody patches it in place: raise a
   `spec-drift` issue, the founder adjudicates, and the spec-author fixes it in a
   separate, deliberate pass.

## Hierarchy

Work flows top-down: **product → subproject → sprint → issue → behavioral slice.**
A subproject is a lifecycle stage of the product. A sprint is a planned batch of
GitHub issues. An issue is one deliverable with an acceptance test. A slice is the
unit an implementer takes from red to green. GitHub issues and PRs are the system of
record; there are no session notes or handoff documents.

## Roles & authority

| Role | Does | Never |
|------|------|-------|
| Founder (human) | Sets architecture, approves plans, adjudicates spec drift, approves merges and cleanup | Executes routine build work |
| Orchestrator (main session) | Dispatches work to roles; on founder approval, runs merges, pushes to `main`, branch cleanup | Merges without explicit approval |
| Triage / PM | Turns ideas into scoped GitHub issues; reads code to size work | Writes code |
| Spec author | Writes behavioral contracts under `specs/` | Writes outside `specs/`; edits frozen specs |
| Test author | Writes the outer acceptance test under `tests/`, committed red | Writes outside `tests/` |
| Implementer | Greens slices via inner unit red→green→refactor cycles | Touches `tests/` outer contracts or `specs/`; merges |
| Reviewer | Two-stage review: spec compliance first, then code quality | Writes anything (read-only by construction) |

Role boundaries are enforced by each subagent's locked tool set and by path-guard
hooks, not by trust. A role that needs something outside its boundary asks the
orchestrator, which routes the work to the right role or to the founder.

## The behavior-first loop

The **outer acceptance test is the locked behavioral contract** for its issue. The
test author writes it from the spec and commits it red before any implementation
exists. From that moment it is locked: the implementer may not edit it, weaken it, or
skip it. The implementer works underneath it in inner unit-test cycles (red → green →
refactor) until the outer test passes. If the outer test itself seems wrong, that is
spec drift: stop and raise the issue, never adjust the contract to fit the code.

A green outer test plus a reviewer pass earns a PR. It never earns a merge; merges
wait for the founder.

## Spec discipline

Specs are frozen during implementation, enforced by a hook on `specs/`. Spec-authoring
happens in deliberate windows: the founder enables spec mode, the spec-author writes
or revises, the freeze returns. Drift found mid-build routes to a `spec-drift` GitHub
issue for the founder to adjudicate. The point is that the contract everyone builds
against cannot quietly change under their feet.

## The gates

Two rules are hooks with exit-code enforcement, not advice:

1. **Subagents never merge.** Every role subagent is hook-blocked from `git merge`,
   `gh pr merge`, pushes to `main`, and the GitHub plugin's merge tool. The plugin
   merge tool is blocked globally. Server-side branch protection backstops this: PRs
   are required and direct pushes to `main` are rejected. The orchestrator's own
   merge path stays open, used only on founder approval.
2. **No commit on a red suite.** A pre-commit hook runs the test suite (`uv run
   pytest` in this repo) and blocks the commit if it fails. The only intended red
   commit is the outer acceptance test itself, committed by the test author before
   implementation starts.

If a gate fires, the answer is to fix the cause, never to bypass the hook.

## Model tiering

Haiku for mechanical and triage work. Sonnet for implementation and integration.
Opus for design and the hardest review or implementation slices. Escalate a slice to
Opus only when its complexity warrants it; note the escalation in the issue.

## Statuses

Every dispatched task reports exactly one of: `DONE`, `DONE_WITH_CONCERNS`,
`BLOCKED`, `NEEDS_CONTEXT`. Concerns and blockers go in the issue thread, not in
private notes.

## Writing conventions

Plain, direct prose; no filler, no ceremony. Short sentences over long ones. At most
two em dashes per 500 words. Code comments only where the code cannot say it itself.
