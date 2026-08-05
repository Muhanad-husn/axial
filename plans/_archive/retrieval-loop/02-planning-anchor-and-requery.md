# Slice 02: Planning from the interrogation result, case-as-anchor, re-query on thin

- **Feature:** retrieval-loop
- **Slice slug:** planning-anchor-and-requery
- **GitHub issue:** #254
- **Branch:** `feat/retrieval-loop/02-planning-anchor-and-requery`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** `retrieval-loop` slice 01 (the loop, dispatcher, budget,
  trajectory), `brief-interrogation` slice 01 (the §7.2 interrogation result)

## Goal — the minimum testable behaviour

The loop stops being scripted and starts judging. Retrieval is planned from the
interrogation result (§7.2) and the case anchor (§7.1 `case`), both carried into
the model's context, and the agent **re-queries when results are thin** — the
behaviour §4 says a fixed pipeline cannot express. And the anchor is an anchor,
not a fence (charter §3, P0-3): the agent may pull corpus-grounded material
about **other** polities that bears on the case, and a brief answered only from
case-scoped chunks is not by construction preferred.

Two observables lock it: a first query returning few or zero ids is followed by
a second, broadened query with **both** calls in the trajectory; and a
country-case brief surfaces cross-polity evidence via `query_by_polity`.

## INVEST check

- **Independent:** slice 01's registry, dispatcher, budget, and trajectory are
  unchanged. This adds the planning context and the thin-result branch above
  them.
- **Valuable:** this is the judgment the whole agentic architecture was chosen
  for (§4), and the half of P0-3 that a fixed pipeline could not deliver.
- **Small:** the interrogation result and case anchor into the prompt, a thin
  threshold read from config, a continue-vs-stop branch on it.
- **Testable:** a scripted model whose branch depends on the result it is fed
  makes re-query deterministic; the trajectory is the assertion surface.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault where query_by_tag{field: "state-formation",
      empirical_scope: "polity:Syria"} returns 0 chunk ids
  And a brief with case "Syria" and an interrogation result whose
      bounds_applied names the thin coverage
  And a scripted model that broadens to query_by_polity{polity: "Syria"} when
      it is handed a result with result_count 0
When  the retrieval loop runs with a thin-result floor of 3
Then  the trajectory log has at least 2 entries
  And entry 1 is the narrow query_by_tag call with result_count 0
  And entry 2 is the broadened query, and its result_ids are non-empty
  And the recorded prompt for step 2 carries the step-1 result_count, so the
      model re-queried on the thin signal rather than by luck

Given a brief whose case is "Syria"
  And a fixture vault whose chunks include material tagged
      polities_touched: ["Egypt"] that bears on the request
When  the retrieval loop runs
Then  the trajectory contains a query_by_polity call for a polity other than
      the case anchor
  And the assembled evidence set contains at least one chunk id whose
      polities_touched does not include "Syria"
  And that cross-polity chunk is not filtered out by any case-scope rule

Given the same brief and the interrogation result from brief-interrogation
When  the retrieval loop runs
Then  the recorded prompt for step 1 contains the brief's `case` and the
      interrogation result's premises_found and bounds_applied — retrieval is
      planned from them, not from the raw request alone
```

- **Boundary / endpoint:** the retrieval-loop entry point in
  `src/axial/retrieve/` taking a brief plus an interrogation result; the
  trajectory log (§7.6) and the assembled evidence set.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_retrieval_planning_requery.py` —
  authored by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] The planning prompt carries the brief `case` and the interrogation
      result's `premises_found` and `bounds_applied` (assert via the `record`
      provider's prompt file).
- [ ] Thin-result predicate: `result_count` below the configured floor is thin;
      at or above it is not. The floor is read from config, not hardcoded.
- [ ] A thin result is fed back to the model with its `result_count`, so the
      re-query decision is made on the signal.
- [ ] A non-thin result does not force a re-query — the model may stop.
- [ ] Re-query respects slice 01's step budget; a thin result near the budget
      halts cleanly rather than overrunning.
- [ ] Evidence assembly deduplicates chunk ids across calls while the trajectory
      still records every call, including the ones that returned duplicates.
- [ ] No case-scope filter is applied to the evidence set: a chunk whose
      `polities_touched` excludes the case anchor survives assembly.
- [ ] A `refuse` disposition (§7.2) short-circuits: the loop makes zero tool
      calls and returns an empty trajectory.

## Out of scope for this slice (deferred)

- Synthesis and the claim graph (P0-4) — this ends at the assembled evidence set.
- The `axial brief examine` inspect-before-spend surface (P0-9): it renders this
  evidence set, but the CLI affordance is its own slice.
- The per-polity coverage map (§7.7, P0-7). Cross-polity retrieval feeds it; the
  map is computed downstream.
- Tuning the thin-result floor. Ship a stated starting value; prove it on the
  dev briefs in an operational pass.
- Any ranking of the retrieved set. Order is the query API's deterministic order.
- Multi-turn planning strategies beyond broaden-on-thin (e.g. decomposing a
  request into sub-questions).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED, seen to
      fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-20 planned.
