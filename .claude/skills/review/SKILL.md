---
name: review
description: Thin entry point that dispatches the reviewer role subagent for the two-stage review - spec compliance first (does the change satisfy the spec, does the outer test encode its intent, was it untouched since red), then code quality. Use before a PR is prepared, or when the founder says 'review this' on a branch or diff.
---

# Review — Entry Point

Dispatch the **reviewer** role subagent (read-only by construction) against the
current branch's diff versus `main`, naming the issue, the slice plan, and the
spec section under review.

The reviewer runs its two stages strictly in order:

1. **Spec compliance** — change vs. spec; outer test encodes the spec's intent
   (would it fail if the behaviour were wrong?); outer test unmodified since its
   red commit; drift → `spec-drift` issue, not a code fix.
2. **Code quality** — correctness, edge cases, silent failures, clarity,
   inner-test quality, CLAUDE.md conventions. Findings ≥ 80 confidence only.

Relay the report to the founder and post findings to the issue thread. Fixes
route back to the implementer; the reviewer never edits anything. A passing
review earns `safe-pr` — never a merge.
