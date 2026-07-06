---
name: triage
description: Thin entry point that dispatches the triage/PM role subagent - turn an idea into scoped GitHub issue proposals, groom the backlog, or size work against the code. Use when the founder says 'triage this', 'scope this idea', or 'groom the backlog'.
---

# Triage — Entry Point

Dispatch the **triage** role subagent (haiku, read-only + Bash) with the
founder's request and the relevant context (idea text, issue numbers, spec
sections). It reads code and the backlog through the GitHub plugin's issue
tools, proposes scoping/decomposition/priorities/labels, and returns a
four-status report.

The orchestrator relays the proposals to the founder. Issue creation itself
follows `/sprint-plan`'s draft-then-approve flow (or, for a single quick issue,
draft the body, show the founder, file on approval via `issue_write`). Triage
writes no code and files nothing on its own.
