# Slice 02: Cross-run usage report — the skew that only shows up over many runs

- **Feature:** source-usage
- **Slice slug:** cross-run-usage-report
- **GitHub issue:** #266
- **Branch:** `feat/source-usage/02-cross-run-usage-report`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** slice 01 (the per-run `source_usage` field there is to
  aggregate); `analysis-foundation` slice 02 (the corpus-pin manifest that decides
  which records are comparable, §7.12)

## Goal — the minimum testable behaviour

`axial brief usage` reads the analysis records under `data/analyses/` and reports
per-source usage ratios **aggregated across runs, broken down by tag filter**
(P0-13). It is the cross-run inspection affordance of §7.13, consistent with the
`axial chunk examine` / inspect-before-spend precedent (P0-9), and makes **zero
model calls**.

Two rules define what it aggregates:

- **Corpus pin partitions the report.** Records are pooled only with records
  carrying the same `corpus_pin`; two runs on different pins are not comparable
  (§7.12). Records on other pins are excluded and the exclusion is stated in the
  output, never silently dropped. The pin to report on defaults to the pin the
  most records share and is selectable with `--pin`.
- **Keyed on `source_id`, joined on `filters_observed`.** The per-run shape from
  slice 01 was designed for exactly this (§7.13, *Design for the aggregate*). The
  report gives, per source, its pooled usage ratio across all records on the pin;
  and per `(source_id, tag_filter)` pair, its usage ratio across the subset of
  records whose `filters_observed` contains that filter. That second breakdown is
  the point: it is what makes "this source draws several times its available share
  whenever queries touch `theory_school:X`" visible rather than merely suspected.

The output names the heaviest-weighing sources and the filters under which they
weigh heaviest, with the record count behind every figure so a ratio computed from
two runs is never mistaken for one computed from twenty.

The report **gates nothing**. It has no threshold, flags no run, and blocks no
release. It exists so the §7.13 promotion condition — a `usage_ratio` distribution
in which a candidate threshold separates over-concentrated runs from legitimately
concentrated ones — becomes checkable by the founder across the dev-brief backlog.

## INVEST check

- **Independent:** reads finished records off disk. Calls no stage, no model, and
  not even the vault — slice 01 already put the denominators in the records.
- **Valuable:** one run's distribution is weak evidence (§7.13). This is the
  affordance that turns a per-run number into the aggregate signal the bias
  investigation actually needs, and the only way the promotion condition ever gets
  tested.
- **Small:** a directory read, a pin partition, two folds, one sorted report.
- **Testable:** a fixture directory of hand-built records — several on one pin,
  one on another, with a deliberately skewed source under one tag filter. Zero
  model calls anywhere on the path.

## Acceptance criterion (outer loop — the failing e2e/integration test)

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
  And the per-filter breakdown shows "tilly" against
      theory_school:world-systems at a pooled ratio near 3, over 3 records,
      distinctly above its pooled ratio across all five
  And zero LLM calls were made (the `explode` provider is installed and never
      fires)

Given the same fixture
When  `axial brief usage --pin PIN-B` runs
Then  the report covers only the single PIN-B record and states its record count

Given a fixture data/analyses/ holding only records whose source_usage.sources
      is empty (refusals)
When  `axial brief usage` runs
Then  the command exits 0 and reports no source rows, without error

Given a fixture data/analyses/ that is empty
When  `axial brief usage` runs
Then  the command exits 0 and says there are no records to report on
```

- **Boundary / endpoint:** CLI — `axial brief usage`, with `--pin`; reads
  `data/analyses/*.json`, writes no file it did not already own.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_brief_usage_report.py` — authored by
  the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Pin partition: records are grouped by `corpus_pin`; the default pin is the
      one the most records share; `--pin` overrides it.
- [ ] Excluded records are counted and stated in the output, never silently
      dropped.
- [ ] Per-source pooling across records on one pin, keyed on `source_id`, with the
      contributing record count carried alongside every figure.
- [ ] Per-`(source_id, tag_filter)` pooling: a record contributes to a filter's
      breakdown only when its `filters_observed` contains that filter.
- [ ] A null `usage_ratio` (available_share 0, slice 01) is excluded from the pool
      rather than treated as 0, and the exclusion shows in the record count.
- [ ] Records whose `source_usage.sources` is empty contribute nothing and cause
      no error.
- [ ] An empty `data/analyses/` and a directory of unreadable/malformed records
      both exit 0 with a stated count rather than a traceback.
- [ ] Ordering is deterministic: the same fixture directory produces byte-identical
      report output across runs.
- [ ] Model-free by construction: the whole path runs with the `explode` provider
      installed and makes zero calls.
- [ ] Gates nothing: no exit code, flag, or blocking behaviour depends on any
      ratio value.

## Out of scope for this slice (deferred)

- **Any threshold, flag, or gate on the aggregated ratios.** §7.13 and §10: the
  promotion to a sixth rung-3 gate happens only after the founder's inspection
  across the dev-brief backlog, and asserting a cut point now is exactly what the
  spec forbids.
- **Running the inspection.** Building the affordance is this slice; running it
  across 26 dev briefs on a pinned corpus and judging the distribution is
  founder-run operational work.
- Reconciling records across different corpus pins. §7.12 says they are not
  comparable; the report partitions rather than reconciles.
- Attributing an observed skew to corpus, retrieval logic, or model (§7.13's three
  causes). The report surfaces the skew; separating the causes reads the
  trajectory log and is founder judgment.
- Time-series or per-brief drilldown views, charts, and any export format beyond
  the plain report. One inspection surface, in the `examine` spirit.
- Recomputing usage from the vault. The records already carry both numerator and
  denominator from slice 01; this slice never opens the vault.

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
