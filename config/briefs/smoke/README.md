# config/briefs/smoke/ — the six-brief smoke set

The build's smoke alarm, run on every slice (`axial brief smoke`, specs/PHASE-B.md
§9.0, D7). **Nothing here is a quality judgment**: the command asserts mechanical
checks plus a cost and latency budget, and it is not an eval.

Real files rather than a manifest over another directory, so this set is the one that
counts. Each file keeps its own provenance comments; each has a case file under
`evals/cases/sim/` of the same stem, which is the join `axial brief smoke` uses to
score the mechanical retrieval-hit oracle (§9.3).

| brief | the retrieval shape it exercises | anchor spread |
|---|---|---|
| P3-04 | hub anchor at the corpus's centre of gravity | `Syria` 962 notes / 22 books |
| S-01 | scholar against scholar over a densely covered question | Tilly 154/20, Mann 377/15 |
| S-02 | a concept several books use in incompatible ways | `nationalism` 158/18 |
| S-03 | a concept whose own book is in the corpus | `quasi-states` 51/**5** |
| S-04 | thin coverage | `Transnistria` 36/**2** |
| S-05 | single-source concentration | `Somaliland` 52/**1** |

Spreads measured over the live index 2026-07-30.

**The set was rebuilt on 2026-07-30 and is no longer Syria-concentrated.** The
original five were all Syria briefs, which left most of the corpus unexercised — 25
of the 31 sources are not about Syria, and the name layer's widest meeting points are
Tilly, Weber, Marx, `nationalism` and the two world wars. S-01 through S-05 were
written against the measured index by a model with no access to this repo, then
checked anchor by anchor before landing. The originals stay in `../sim/` as history.

**P3-04 is kept deliberately, as the only Syria brief.** §7.13's denominator
inspection is stated in terms of a hub name swamping the union of member notes, and
`Syria` at 962 notes across 22 books is that case. Every S-0N anchor is mid-sized by
design, so without P3-04 the inspection this slice owes would have nothing to bite on.

**S-04 and S-05 do not tell the run what they are testing.** An earlier draft asked
about "the library's thin evidence on Transnistria" and how to qualify conclusions
"when every note comes from one book". Both probes measure whether the run *notices*
thinness and single-source concentration on its own, so naming the finding in the
question would have made a pass prove only that the model follows instructions. The
disclosure requirement lives in the rubric instead.

**S-04 is a thin-coverage probe, not a fragmentation probe.** The old P4-04 tested
name-layer fragmentation — an acronym reaching neither the full name nor an unmerged
variant — and that gap is filed against Phase A as #498. Nothing in this set replaces
it, because no mechanical check ever asserted on it: it was read by eye off the names
each run printed. Said here so its absence is a known cut rather than an oversight.

No P1 or P5 brief is here: both personas write long compound questions by
construction, so they carry the hard set (`../eval/`) instead.
