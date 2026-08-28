# Slice 08: Retrieval enters through the map's address layer

- **Feature:** positions-not-names
- **Slice slug:** retrieval-address-arm
- **Branch:** feat/positions-not-names/08-retrieval-address-arm
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Gated on:** founder go from slice 06.

## Goal — the minimum testable behaviour

A question is answered through the address walk — question → region (axis
intersection over profiles) → positions → relations → passages — with names
applied only as a terminal filter, wired as a sweep arm so it is recorded and
comparable like every other arm.

## INVEST check

- **Independent:** reads the variant map with profiles (slice 07); the arm
  registry, per-arm recording and `eval layers` comparison already exist and
  are reused.
- **Valuable:** the efficiency claim of the whole approach becomes runnable
  and measurable end to end.
- **Small:** one address-resolution module plus an arm wiring; assembly caps
  and citation mechanics stay as they are.
- **Testable:** address resolution is deterministic given fixture profiles;
  the arm records its walk the way the existing arms record theirs.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a variant map with profiles and relations, and a brief
When  the sweep runs the address arm over that brief
Then  the run record shows the walk: the axis values the question pinned,
      the region (candidate positions before any model call), the positions
      and relations followed, and the passages assembled
And   a name in the brief narrows the assembled result and never forms it
And   the arm is recorded with its commit and distinct-sources-cited count,
      so `eval layers` can table it against the map arm
```

- **Boundary / endpoint:** CLI — `uv run axial brief sweep` (address arm) over `config/briefs/smoke/`
- **e2e test type:** API/integration test (pytest, CLI-level, injected fake LLM client)
- **e2e test file (planned):** src/axial/argmap/test_address.py

## Files (parallel-safety declaration)

```aeo-independence
slice: 08-retrieval-address-arm
creates: src/axial/argmap/address.py
creates: src/axial/argmap/test_address.py
edits: src/axial/argmap/ask.py
edits: src/axial/argmap/test_ask.py
edits: src/axial/brief/sweep.py
edits: src/axial/brief/test_sweep.py
edits: src/axial/answer/record.py
creates: data/logs/2026-08-29-address-arm-smoke/summary.md
depends-on: 07-profiles-and-ranked-relations
```

## Inner loop — initial unit test list

- [ ] Address resolution: a question's pinned axis values intersect to a
      candidate position set before any model call; an empty intersection
      widens one axis at a time rather than returning nothing.
- [ ] Name-as-filter: a name narrows an assembled result; removing the name
      never changes which positions formed the region (approach §8, pinned
      by test).
- [ ] The walk is recorded step by step in the run record (this arm has a
      real trajectory; assert it, unlike the map arm's honest empty list).
- [ ] Assembly order: address evidence enters under the existing caps in an
      order that can reach citations, checked against citations, not
      assembled counts (DEC-73's lesson, pinned by test with a fake client).
- [ ] The arm records commit and arm name through the existing sweep
      recording, unchanged.

## Operational steps inside the slice

1. Run the smoke briefs through the address arm in the main checkout; write
   `data/logs/2026-08-29-address-arm-smoke/`.
2. Summary records wall time, cost and distinct sources cited beside the map
   arm's same-brief numbers — structure and speed only; the saturated
   grounding gate is not treated as a verdict.

## Out of scope for this slice (deferred)

- Demolition of the name-walking loop (slice 09) — both arms coexist here.
- A harder judged gate.
- The web client — CLI sweep only.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Smoke sweep run, log written, arm recorded and tabled by `eval layers`.
- [ ] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
