---
name: sprint-plan
description: Decompose a subproject (a lifecycle stage of the product spec) into a sprint backlog of GitHub issues, each linked to its plans/<feature>/ slice files. Drafts issue bodies to local files for founder review BEFORE filing anything. Use at the start of a sprint or when the founder says 'plan the sprint', 'build the backlog', or 'turn this spec section into issues'.
---

# Sprint Plan — Subproject → Issue Backlog

Run from the **main session (orchestrator)**. Turn one subproject into a reviewed,
filed sprint backlog. GitHub issues are the system of record (DEC-4); a slice
without an issue does not exist.

## Procedure

1. **Scope the subproject.** Read the spec (`specs/`) section the founder names.
   Optionally dispatch the **triage** role to size the work against the current
   code. Restate the subproject's outcome in two sentences and confirm it with
   the founder if at all ambiguous.

2. **Slice.** Run `tdd-plan` for each feature in the subproject — it writes
   `plans/<feature-slug>/` with a README index and one plan per slice. Thin
   vertical slices, INVEST-checked; a walking-skeleton slice first when
   infrastructure doesn't exist yet.

3. **Draft the issues locally — file nothing yet.** For each slice, write a
   draft body to `plans/<feature-slug>/issues/<NN>-<slice-slug>.issue.md`:

   ```markdown
   # <type>(<feature-slug>): <slice goal> [slice NN]

   **Spec:** specs/<file>#<section> · **Plan:** plans/<feature-slug>/<NN>-<slice-slug>.md
   **Depends on:** #<issue> (or "none")
   **Labels:** sub:<subproject-slug>[, ...]

   ## Deliverable
   <one paragraph: the observable behaviour this issue ships>

   ## Acceptance criterion
   <the Given/When/Then from the slice plan — this becomes the locked outer test>

   ## Out of scope
   <deferred items from the plan>
   ```

4. **⛔ Founder reviews the drafts.** Present the backlog as a table (issue
   title, dependency, size) plus the draft files. Plan approval is one of the
   three human moments — file nothing until the founder approves.

5. **File on approval.** Create the issues **through the GitHub plugin's issue
   tools** (`issue_write`; raw `gh issue create` only as fallback), with labels:
   the `sub:<subproject-slug>` namespace label plus any status labels. Then
   back-fill each slice plan's **GitHub issue** field and the plans README with
   the real issue numbers, and put the issue↔plan cross-links in both directions
   (issue body already carries the plan path).

6. **Report.** `DONE` + the filed issue list. Recommend `/sprint-start` to begin
   the first issue.

## Labels (create once per repo if missing)

`spec-drift`, `blocked`, `needs-context`, `done-with-concerns`, plus one
`sub:<subproject-slug>` per subproject. Check with the plugin's label tools or
`gh label list`; create missing ones with `gh label create`.

## Rules

- **Nothing is filed before founder approval of the drafts.**
- Every issue links its plan file and spec section; every plan links its issue.
- Dependencies are explicit (`Depends on:`) — `/sprint-start` picks by them.
- Issues are scoped to one slice each. An issue that needs "and" is two issues.
