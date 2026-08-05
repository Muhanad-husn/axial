# feat(source-usage): `axial brief usage` — cross-run usage ratios by source and tag filter [slice 02]

**Spec:** specs/PHASE-B.md#7.13 · §8 P0-13 · **Plan:** plans/source-usage/02-cross-run-usage-report.md
**Depends on:** #265, #248
**Labels:** sub:analysis-v0, enhancement

## Deliverable
`axial brief usage` reads the analysis records under `data/analyses/` and reports
per-source usage ratios **aggregated across runs and broken down by tag filter**
(P0-13), making **zero model calls** — consistent with the inspect-before-spend
`axial chunk examine` precedent (P0-9). Records are pooled only with records
sharing the same `corpus_pin`, since runs on different pins are not comparable
(§7.12); excluded records are counted and stated, never silently dropped, and
`--pin` selects the pin. Aggregation is keyed on `source_id` and joined on
`filters_observed`, exactly as slice 01's shape was designed for (§7.13, *Design
for the aggregate*): a pooled ratio per source, plus a ratio per
`(source_id, tag_filter)` pair over the records that queried that filter. That
second breakdown is the point — it makes "this source draws several times its
available share whenever queries touch a given tag" visible rather than suspected.
Every figure carries the record count behind it. The report **gates nothing**: no
threshold, no flag, no blocked release. It exists so §7.13's promotion condition
becomes checkable by the founder across the dev-brief backlog.

## Acceptance criterion
```gherkin
Given a fixture data/analyses/ holding five analysis records on corpus_pin
      "PIN-A" and one on corpus_pin "PIN-B"
  And in three of the PIN-A records, filters_observed contains
      theory_school:world-systems, and in those three source_id "tilly" shows
      usage_ratio 3.1, 2.8, and 3.4
  And in the other two PIN-A records, which do not query that filter, "tilly"
      shows usage_ratio 1.0 and 0.9
When  `axial brief usage` runs
Then  the command exits 0
  And the report covers the five PIN-A records and states that one record on
      PIN-B was excluded as not comparable
  And "tilly" is named among the heaviest-weighing sources, with the record
      count behind its pooled ratio
  And the per-filter breakdown shows "tilly" against theory_school:world-systems
      at a pooled ratio near 3 over 3 records, distinctly above its pooled ratio
      across all five
  And zero LLM calls were made (the `explode` provider never fires)

Given the same fixture
When  `axial brief usage --pin PIN-B` runs
Then  the report covers only the single PIN-B record and states its record count

Given a fixture data/analyses/ holding only records whose source_usage.sources
      is empty (refusals)
When  `axial brief usage` runs
Then  the command exits 0 and reports no source rows, without error

Given an empty data/analyses/
When  `axial brief usage` runs
Then  the command exits 0 and says there are no records to report on
```

## Out of scope
- **Any threshold, flag, or gate on the aggregated ratios.** Promotion to a sixth
  rung-3 gate happens only after the §7.13 inspection; asserting a cut point now
  is what the spec forbids.
- **Running the inspection.** Building the affordance is this slice; running it
  across the 26 dev briefs on a pinned corpus and judging the distribution is
  founder-run operational work.
- Reconciling records across different corpus pins (§7.12) — the report
  partitions, it does not reconcile.
- Attributing a skew to corpus, retrieval logic, or model (§7.13's three causes).
- Time-series or per-brief drilldown views, charts, and export formats beyond the
  plain report.
- Recomputing usage from the vault; the records already carry both numerator and
  denominator from slice 01.
