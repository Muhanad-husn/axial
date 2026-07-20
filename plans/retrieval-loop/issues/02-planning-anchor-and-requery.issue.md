# feat(retrieval-loop): plan from the interrogation result, case-as-anchor, re-query on thin [slice 02]

**Spec:** specs/PHASE-B.md#5 stage 3 · §4 · §7.2 · §7.6 · §8 P0-3 · **Plan:** plans/retrieval-loop/02-planning-anchor-and-requery.md
**Depends on:** #253, #252
**Labels:** sub:analysis-v0, enhancement

## Deliverable
The judgment the loop exists for. Retrieval is planned from the interrogation
result (§7.2) and the case anchor (§7.1 `case`), both carried into the model's
context, and the agent **re-queries when results are thin** — the behaviour §4
says a fixed pipeline cannot express. Thin is a `result_count` below a
configured floor: a stated tunable, proven on the dev briefs; the agent deciding
to re-query on it is the firm behaviour. And the case is an **anchor, not a
fence** (charter §3, P0-3): the agent may pull corpus-grounded material about
other polities that bears on the case via `query_by_polity`, and a brief
answered only from case-scoped chunks is not by construction preferred — no
case-scope filter is applied to the assembled evidence set. Every call, narrow
and broadened alike, lands in the §7.6 trajectory log.

## Acceptance criterion
```gherkin
Given a fixture vault where query_by_tag{field: "state-formation",
      empirical_scope: "polity:Syria"} returns 0 chunk ids
  And a brief with case "Syria" and an interrogation result whose
      bounds_applied names the thin coverage
  And a scripted model that broadens to query_by_polity{polity: "Syria"} when
      it is handed a result with result_count 0
When  the retrieval loop runs with a thin-result floor of 3
Then  the trajectory log has at least 2 entries, entry 1 is the narrow
      query_by_tag call with result_count 0, entry 2 is the broadened query
      with non-empty result_ids
  And the recorded prompt for step 2 carries the step-1 result_count, so the
      model re-queried on the thin signal rather than by luck

Given a brief whose case is "Syria"
  And a fixture vault whose chunks include material tagged
      polities_touched: ["Egypt"] that bears on the request
When  the retrieval loop runs
Then  the trajectory contains a query_by_polity call for a polity other than
      the case anchor
  And the assembled evidence set contains at least one chunk id whose
      polities_touched does not include "Syria", unfiltered by any case-scope rule

Given the same brief and the interrogation result from brief-interrogation
When  the retrieval loop runs
Then  the recorded prompt for step 1 contains the brief's `case` and the
      interrogation result's premises_found and bounds_applied
```

## Out of scope
- Synthesis and the claim graph (P0-4); this ends at the assembled evidence set.
- The `axial brief examine` inspect-before-spend CLI surface (P0-9).
- The per-polity coverage map (§7.7, P0-7).
- Tuning the thin-result floor — ship a stated starting value.
- Any ranking of the retrieved set; order is the query API's deterministic order.
- Planning strategies beyond broaden-on-thin (e.g. sub-question decomposition).
