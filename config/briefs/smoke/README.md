# config/briefs/smoke/ — the five-brief smoke set

The build's smoke alarm, run on every slice (`axial brief smoke`, specs/PHASE-B.md
§9.0, D7). **Nothing here is a quality judgment**: the command asserts mechanical
checks plus a cost and latency budget, and it is not an eval.

Five real files, copied from `../sim/` rather than manifested over it, so this set is
the one that counts and the sim pool stays untouched as history (D7). Each file keeps
its own provenance comments; each has a case file under `evals/cases/sim/` of the same
stem, which is the join `axial brief smoke` uses to score the mechanical
retrieval-hit oracle (§9.3).

| brief | the retrieval shape it exercises |
|---|---|
| P3-01 | scholar against scholar over a densely covered question |
| P3-04 | concept anchor at the corpus's centre of gravity |
| P4-03 | a concept name page whose own book is in the corpus (Agamben) |
| P4-04 | thin coverage, and the **name-layer fragmentation** probe |
| P2-02 | single-book-heavy retrieval, the source-concentration probe |

**P4-04 is a fragmentation probe, not a resolution-failure case.** The corpus holds
`Autonomous Administration of North and East Syria` (2 members) with an unmerged
`AANS` node beside it, and the acronym `AANES` the brief writes reaches neither
(§7.5, measured 2026-07-30). A pass means the run either reaches what it can and
bounds the answer, or refuses. It must not silently substitute a nearest-neighbour
name — which is why `axial brief smoke` prints the names each run actually queried.

No P1 or P5 brief is here: both personas write long compound questions by
construction, so they carry the hard set (`../eval/`) instead.
