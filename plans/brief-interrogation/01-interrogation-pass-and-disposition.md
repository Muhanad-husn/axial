# Slice 01: Interrogation pass and deterministic disposition

- **Feature:** brief-interrogation
- **Slice slug:** interrogation-pass-and-disposition
- **GitHub issue:** #252
- **Branch:** `feat/brief-interrogation/01-interrogation-pass-and-disposition`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** yes (thinnest end-to-end thread through stage 1: brief
  in → model pass → parsed result → deterministic disposition → persisted)
- **Depends on:** `analysis-foundation` slice 01 (brief loader),
  `vault-query` slice 02 (`coverage_count` / `query_by_polity`)

## Goal — the minimum testable behaviour

A bounded model pass reads a loaded brief (§7.1) and emits the interrogation
result (§7.2): `{premises_found[], bounds_applied[], refusal, disposition}`,
where `premises_found` is a list of `{premise, assessment}` and `assessment` is
exactly one of `supports` / `contradicts` / `silent`. A **deterministic wrapper**
sets `disposition` from those fields to exactly one of `proceed`,
`proceed_bounded`, `refuse`; a `disposition` emitted by the model is discarded.
The pass tests premises against real corpus coverage by reading the vault query
API, not by asking the model to recall coverage. On `refuse` the run is a
COMPLETED run: the result is persisted and no synthesis call is made.

## INVEST check

- **Independent:** reads the brief record and the query API; writes only the
  interrogation result. Nothing downstream of stage 1 exists yet to entangle it.
- **Valuable:** this is Principle III in code — the gate that stops the engine
  from answering a question built on a premise the corpus contradicts. It is the
  whole of P0-1's observable.
- **Small:** one prompt, one parse, one pure disposition function, one write.
- **Testable:** hermetic end to end — a fixture vault for the coverage counts, a
  canned model response via the `record` provider, and assertions on both the
  emitted prompt text and the parsed result.

## Acceptance criterion (outer loop — the failing e2e/integration test)

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
      read from the vault query API, so the assessment is made against numbers
  And the command exits 0

Given the same brief and a canned response carrying a non-null `refusal`
When  `axial brief interrogate <brief_file>` runs
Then  `disposition` is exactly "refuse"
  And the interrogation result is persisted
  And zero synthesis calls are made (the run is COMPLETED, not an error;
      exit code 0)

Given a canned response with empty premises_found, empty bounds_applied and a
      null refusal, but which nonetheless emits `disposition: "refuse"`
When  `axial brief interrogate <brief_file>` runs
Then  `disposition` is "proceed" — the wrapper decides, the model does not
```

- **Boundary / endpoint:** CLI — `axial brief interrogate <brief_file>`
  (argparse subparser under the `brief` command group); the persisted
  interrogation result.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_brief_interrogation.py` — authored
  by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Result parsing: a well-formed model JSON parses into
      `{premises_found[], bounds_applied[], refusal, disposition}`; each
      `premises_found` entry is `{premise, assessment}`.
- [ ] Parse rejects an `assessment` outside `{supports, contradicts, silent}`
      rather than passing it through.
- [ ] Disposition rule (pure function, table-driven): non-null `refusal` →
      `refuse`; any `contradicts` premise → `proceed_bounded`; non-empty
      `bounds_applied` → `proceed_bounded`; otherwise → `proceed`.
- [ ] The disposition rule ignores any model-supplied `disposition` value.
- [ ] Disposition is always exactly one of the three legal values — never null,
      never absent.
- [ ] Coverage lookup: a premise naming a polity with a low `coverage_count` is
      carried into the prompt as a thin-coverage finding; the counts come from
      the query API, not from the model.
- [ ] The pass registers its `pass_name` constant so `model_by_pass` /
      `reasoning_by_pass` can route it (§7.11).
- [ ] Malformed model JSON is a clean, named failure, not a silent `proceed`.

## Out of scope for this slice (deferred)

- Retrieval planning and the agentic loop (P0-3, `retrieval-loop`).
- Synthesis, claim graph, validators, rendering (P0-4 … P0-8).
- The full §7.3 analysis record. This slice emits the `interrogation` block;
  embedding it in the record belongs to `analysis-foundation`.
- The §10 premise-catch-rate gate harness (P0-12).
- Bounded re-ask on a malformed interrogation response (the Phase-A #241
  pattern). Fail cleanly in v0; revisit if measured variance warrants it.
- Choosing the model tier for this pass (§7.11 [TENTATIVE], proven on dev
  briefs). Wire the seam, do not pick.

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
