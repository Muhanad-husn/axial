# feat(positions-not-names): retrieval enters through the map's address layer [slice 08]

**Spec:** docs/approach-positions-not-names.md#7-retrieval-and-where-the-time-comes-back · **Plan:** plans/positions-not-names/08-retrieval-address-arm.md
**Depends on:** slice 07 of this batch — **gated on the founder's go from slice 06**
**Labels:** enhancement, sub:analysis-v0

## Deliverable

A question is answered through the address walk — question → region (axis
intersection over profiles) → positions → relations → passages — with names
applied only as a terminal filter, wired as a sweep arm so it is recorded
with its commit and distinct-sources-cited count and tabled by `eval layers`
like every other arm. This arm has a real trajectory and records it step by
step. Assembly order is checked against citations, never assembled counts
(DEC-73's lesson, pinned by test).

## Mechanism

One address-resolution module over profiles; the existing arm registry,
per-arm sweep recording and `eval layers` comparison reused. An empty axis
intersection widens one axis at a time rather than returning nothing.

## Acceptance criterion

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

## Files

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

## Out of scope

- Demolition of the name-walking loop (slice 09) — both arms coexist here.
- A harder judged gate; the web client (CLI sweep only).
