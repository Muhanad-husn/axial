# Slicing Guide — Thin Vertical Slices for TDD

How to decompose any feature into the smallest end-to-end testable increments. This is the toolkit the `tdd-plan` skill applies. Read it when slicing anything non-trivial.

## Table of contents

1. Vertical vs horizontal slicing
2. Minimum testable behaviour
3. The INVEST quality bar
4. The walking skeleton (first slice of a new system)
5. Nine splitting patterns (+ the meta-pattern)
6. A worked example
7. Ordering slices
8. Smells that mean "slice again"

---

## 1. Vertical vs horizontal slicing

A **vertical slice** "delivers a valuable change in system behavior such that you'll probably have to touch multiple architectural layers to implement the change" (Humanizing Work). It cuts top-to-bottom through whatever layers it needs — UI, application logic, persistence — to make one observable thing happen.

Build **feature-by-feature, end-to-end**: "Implement A from end to end, then B, then C" — *not* "implement the database layer for A, B and C, then the logic, then the UI" (John Sonmez).

**Horizontal slices are forbidden** in this harness. "Build the data model", "wire up the repository layer", "create the API scaffolding" are not slices — none is independently valuable, none can be demonstrated end-to-end, and they push integration risk to the end where it is most expensive. If a proposed slice can't be exercised through a real external endpoint and shown to a user, it is horizontal. Re-slice it.

## 2. Minimum testable behaviour

Decompose down to the **smallest observable change in system behaviour that delivers value and can be verified** — the single tiny goal for one red-green-refactor pass. Examples: "an empty cart shows £0.00 total", "POST /login with a valid password returns a session cookie", "the CLI prints the version when called with `--version`".

The rhythm of vertical slicing is: *acceptance test fails → minimum code makes it pass → next slice.* Each slice should make its failing acceptance test go green in hours, not days.

## 3. The INVEST quality bar

Every slice must pass INVEST:

- **I**ndependent — can be built and shipped without depending on a sibling slice (order is fine; entanglement is not).
- **N**egotiable — captures intent, not a rigid spec. "A story is not a contract; it IS an invitation to a conversation."
- **V**aluable — delivers something a user or stakeholder can perceive. "If a story does not have discernable value it should not be done. Period."
- **E**stimable — small and clear enough that effort is obvious.
- **S**mall — completable well within an iteration; for this harness, ideally under a day.
- **T**estable — you can write a failing test that defines "done" before you start.

If a slice fails **S** or **T**, split it again. If it fails **V**, drop or merge it.

## 4. The walking skeleton (first slice of a new system)

> "A walking skeleton is an implementation of the thinnest possible slice of real functionality that we can automatically build, deploy, and test end-to-end." — GOOS
>
> "A tiny implementation of the system that performs a small end-to-end function. It need not use the final architecture, but it should link together the main architectural components." — Alistair Cockburn

For any **new** system (no working build/test/deploy path yet), the **first slice is always a walking skeleton**. Its job is to de-risk architecture and infrastructure — project setup, the boundary that runs (a page that loads, an endpoint that responds, a CLI that prints), the test harness (unit runner + Playwright), and ideally the CI pipeline — *before* any real feature content. It carries almost no business logic on purpose; its value is a proven, testable end-to-end thread you can grow.

A canonical walking skeleton slice: "the app starts and serves a page (or endpoint) that returns a hardcoded greeting, proven by one passing unit test and one passing Playwright e2e test." Everything real grows from there.

## 5. Nine splitting patterns (Humanizing Work)

When a candidate slice is too big, split it with one of these:

1. **Workflow steps** — build the simplest straight-through path first; add middle steps and special cases as later slices. (Checkout: "place an order with one item, card payment, no discounts" first.)
2. **Operations / CRUD** — split "manage X" into Create, Read, Update, Delete — each its own slice.
3. **Business-rule variations** — one rule first (standard tax), other rules later (reduced/zero-rated).
4. **Variations in data** — handle one data shape first (a single-currency price), add more just-in-time.
5. **Data-entry methods** — the simplest input first (a plain text field), richer UI (autocomplete, validation) later.
6. **Major effort** — when several variations share a big chunk of work, do the first variation (which builds the shared machinery) as one slice, the rest as cheap follow-ups.
7. **Simple / complex** — extract the simplest version that has value; defer every edge case to its own slice. (Search: exact-match first; fuzzy/ranking later.)
8. **Defer performance / cross-cutting** — "make it work" first; "make it fast / secure / scalable / observable" as separate slices.
9. **Break out a spike** — if genuine uncertainty blocks slicing, time-box a spike to learn, then slice with what you learned. A spike produces knowledge, not shippable behaviour — keep it rare and bounded.

**Meta-pattern:** identify the core complexity → list all the variations of it → keep **just one** variation for the first slice, and push the rest to later slices.

## 6. A worked example

**Request:** "Users can reset their forgotten password."

Too big for one slice. Slice it (mostly by **workflow steps** + **simple/complex**):

- **01 — Request a reset link (happy path).** Given a registered email, when the user submits the reset form, then a reset email with a tokenised link is sent. *(e2e: submit form → assert a message is queued/visible; unit: token generation, email composition.)*
- **02 — Use a valid link to set a new password.** Given a valid, unexpired token, when the user submits a new password, then the password is updated and they can log in with it. *(e2e: follow link → set password → log in.)*
- **03 — Reject an expired or invalid token.** Variation by business rule. *(e2e: tampered/old token → error shown, password unchanged.)*
- **04 — Rate-limit reset requests.** Cross-cutting/deferred-performance slice. *(e2e: N rapid requests → throttled.)*

Each is vertical, valuable, testable end-to-end, and small. Slice 01 might also serve as the walking skeleton if the email subsystem is new (wire a fake/dev mailer first).

## 7. Ordering slices

- **Riskiest / most architecture-defining first.** The walking skeleton, then the slice that forces the major design decisions.
- **Each slice should build on the last** without requiring rework.
- **Value-first within equal risk** — deliver something demonstrable early.
- Prefer many small slices over a few big ones: more green checkpoints, more chances to re-plan.

## 8. Smells that mean "slice again"

- You can't write the acceptance criterion as a single concrete Given/When/Then.
- The slice names a layer ("the API", "the schema") rather than a behaviour.
- "And" appears in the slice's value statement (two behaviours hiding as one).
- You can't imagine finishing it in under a day.
- The only way to test it is through internal functions, not a real endpoint.
- It has no user-visible or stakeholder-visible value.
