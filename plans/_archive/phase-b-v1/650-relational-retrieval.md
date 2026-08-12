# #650 — Retrieval walks the relations; names become filters (DEC-62)

Governing decision: DEC-62. Evidence:
`data/logs/2026-08-04-relational-join-ceiling/summary.md`.

## The move

The retrieval loop's tools stop being "find a name page, read the name page"
and become queries over the relational store shipped in #648
(`axial.query.store`): notes, concepts, argument-map positions, and
`arguing_against` opposition edges are the targets you retrieve; names,
dates, places and sources are WHERE clauses on those targets.

`find_names` / `get_name` survive as the SQL forms #648 already proved
reproduce the door layer row-for-row. They stop being the entry point.

## Why

The measurement: 43,101 high-confidence cross-source opposition pairs across
343 named scholars and works exist in the notes, and the name-page surface
reaches effectively none of them. Every retrieval patch since Phase B (tier
stops, IDF, transliteration folds, numeric weights) tuned a projection that
had already discarded the relations.

## Shape

- Loop tools over the store; the loop keeps its shape — turns, evidence
  assembly, round-robin by source, budgets, disclosure.
- The argument map's positions become a first-class retrieval target (#572
  measured the map stronger on citation grounding than the name layer).
- Intake's `ForkConstraint` (#649, merged as #656) is honored here: dropped
  sources, per-source caps, per-turn guidance.

## Bar

Paired live runs on the standing hard-question set, old surface vs new,
judged blind by sealed peer-reviewer packets — the #572 recipe. Report
grounding and coverage. A drop in sources-cited is not a regression
(measured, #572). Costed before running.
