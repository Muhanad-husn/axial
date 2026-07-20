# feat(analysis-validators): per-polity coverage map & confidence disclosure — thin coverage disclosed as thin [slice 03]

**Spec:** specs/PHASE-B.md#7.7 · specs/PHASE-B.md#7.9 · §8 P0-7 · **Plan:** plans/analysis-validators/03-coverage-and-confidence.md
**Depends on:** #257, #251
**Labels:** sub:analysis-v0, enhancement

## Deliverable
A **per-polity coverage map computed deterministically from `polities_touched`,
never asked of a model** (§7.7). For every polity the record's claims touch the
map carries `{corpus_chunk_count, evidence_chunk_count, coverage_band}`:
`corpus_chunk_count` from `coverage_count` over the whole vault,
`evidence_chunk_count` from this run's grounds, and `coverage_band`
(`dense`/`moderate`/`thin`) derived from the counts against a **stated tunable
threshold, proven via inspection** in the spirit of the Phase-A chunk band. The
starting cut points land in a `coverage_bands` config block — `thin` below 20
corpus chunks, `moderate` 20–99, `dense` 100 and above — as a hypothesis over a
~17k-chunk vault, with an inspection affordance that prints per-polity counts and
bands so the founder can prove them before the numbers are trusted. The validator
then **blocks release** on a missing coverage entry for any polity the claims
touch, on a missing or empty-rationale `confidence` disclosure, and on top-band
confidence disclosed while the map contains a `thin` polity. The whole path is
model-free by construction: the `explode` provider is installed in tests and never
fires.

## Acceptance criterion
```gherkin
Given a vault in which coverage_count reports 240 chunks for polity "Syria"
      and 6 chunks for polity "Yemen"
  And an analysis record at data/analyses/DEV20.json whose claims carry
      polities_touched ["Syria", "Yemen"] across their grounds
  And config coverage_bands of {thin: <20, moderate: 20-99, dense: >=100}
When  `axial brief validate DEV20` runs
Then  the command exits 0
  And coverage_map["Syria"].coverage_band is "dense" with
      corpus_chunk_count 240
  And coverage_map["Yemen"].coverage_band is "thin" with corpus_chunk_count 6
  And zero LLM calls were made building the map (the `explode` provider never
      fires)

Given an analysis record at data/analyses/DEV21.json whose claims touch "Yemen"
  And whose coverage_map has no "Yemen" entry
When  `axial brief validate DEV21` runs
Then  the command exits non-zero, the report reason is
      "missing_coverage_entry" naming "Yemen", and no answer is released

Given an analysis record at data/analyses/DEV22.json with a complete coverage_map
  And whose confidence is {overall_band: null, rationale: ""}
When  `axial brief validate DEV22` runs
Then  the command exits non-zero with reason "missing_confidence_disclosure"

Given an analysis record at data/analyses/DEV23.json whose coverage_map contains
      a "thin" polity and whose confidence.overall_band is the top band
When  `axial brief validate DEV23` runs
Then  the command exits non-zero with reason "confidence_exceeds_coverage"
      naming the thin polity
```

## Out of scope
- The **calibration metric** (calibration error between disclosed confidence and
  judged correctness, §10) — `rung3-gates` slice 02, and its metric choice is a
  live spec Open Question.
- Settling the **confidence vocabulary** — discrete bands vs a numeric score
  (§7.4, Open Questions). This slice reads whatever `overall_band` the record
  carries.
- Per-claim confidence scoring beyond the overall disclosure.
- Tuning the band cut points against the real corpus; the slice lands the
  config-driven hypothesis and the inspection affordance, the proving pass is
  founder-run operational work on the full ~30-source vault.
- Any change to the §7.7 map shape or the §7.3 `confidence` shape. Both locked.
</content>
