# feat(brief-interrogation): interrogation pass and deterministic disposition [slice 01]

**Spec:** specs/PHASE-B.md#7.2 · §7.1 · §5 stage 1 · §8 P0-1 · **Plan:** plans/brief-interrogation/01-interrogation-pass-and-disposition.md
**Depends on:** #247, #251
**Labels:** sub:analysis-v0, enhancement

## Deliverable
`axial brief interrogate <brief_file>` runs a bounded model pass over a loaded
brief (§7.1) and emits the interrogation result (§7.2):
`{premises_found[], bounds_applied[], refusal, disposition}`, where each
`premises_found` entry is `{premise, assessment}` with `assessment` in
`{supports, contradicts, silent}`. A **deterministic wrapper** — not the model —
sets `disposition` to exactly one of `proceed` / `proceed_bounded` / `refuse`
from those fields, discarding any `disposition` the model emits. Premises are
tested against real corpus coverage read from the vault query API
(`coverage_count`, `query_by_polity`), so the assessment is made against counts
rather than model recall. On `refuse` the run is a COMPLETED run: the result is
persisted, no synthesis call is made, exit code 0. The behaviour this locks: a
brief whose premise the corpus contradicts comes back with that premise NAMED
under a `refuse` or `proceed_bounded` disposition, never a confident
pass-through.

## Acceptance criterion
```gherkin
Given a fixture vault whose chunks give polity "Tunisia" a coverage_count of 0
  And a brief file with case "Syria" and a request whose premise asserts
      "the Tunisian transition followed the same sequence"
  And AXIAL_LLM_PROVIDER=record with a canned interrogation response marking
      that premise assessment "contradicts"
When  `axial brief interrogate <brief_file>` runs
Then  the emitted interrogation result has premises_found containing an entry
      whose `premise` names the Tunisian-transition premise and whose
      `assessment` is "contradicts"
  And `disposition` is one of "refuse" or "proceed_bounded" — never "proceed"
  And the recorded prompt at AXIAL_LLM_RECORD_PATH contains the coverage counts
      read from the vault query API
  And the command exits 0

Given the same brief and a canned response carrying a non-null `refusal`
When  `axial brief interrogate <brief_file>` runs
Then  `disposition` is exactly "refuse", the result is persisted, zero synthesis
      calls are made, and the command exits 0

Given a canned response with empty premises_found, empty bounds_applied and a
      null refusal, but which nonetheless emits `disposition: "refuse"`
When  `axial brief interrogate <brief_file>` runs
Then  `disposition` is "proceed" — the wrapper decides, the model does not
```

## Out of scope
- Retrieval planning and the agentic query loop (P0-3, `retrieval-loop`).
- Synthesis, claim graph, validators, rendering (P0-4 … P0-8).
- The full §7.3 analysis record; this ships the `interrogation` block only.
- The §10 adversarial premise-catch gate harness (P0-12).
- Bounded re-ask on a malformed interrogation response — fail cleanly in v0.
- Picking the model tier for this pass (§7.11 [TENTATIVE]); wire the
  `model_by_pass` / `reasoning_by_pass` seam, do not choose the tier.
