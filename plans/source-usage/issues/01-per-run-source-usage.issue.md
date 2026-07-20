# feat(source-usage): per-run source usage — contribution disclosed with its denominator [slice 01]

**Spec:** specs/PHASE-B.md#7.13 · §8 P0-13 · **Plan:** plans/source-usage/01-per-run-source-usage.md
**Depends on:** #257, #251
**Labels:** sub:analysis-v0, enhancement

## Deliverable
Every analysis record carries the §7.13 `source_usage` field, non-nullable and
computed **deterministically with zero model calls**: `filters_observed[]`, the
union of the tag filters the run actually queried, read from the §7.6 trajectory
log's recorded args; and per source `{source_id, evidence_chunk_count,
evidence_share, available_chunk_count, available_share, usage_ratio}`. The
numerator folds the claim grounds — each pointer resolves to a vault id and every
`chunk_id` embeds its `source_id`, so it is a parse, not a lookup. The denominator
re-runs `filters_observed` over the pinned vault through the §7.5 query tools. The
two figures are **always present together**: a contribution share is never
disclosed without the availability it should be read against, because contribution
alone cannot separate a thin corpus from over-selection. `sources` is empty on
disposition `refuse` and on any run whose claims carry no grounds; `usage_ratio` is
null when `available_share` is 0. The field **gates nothing** — a concentrated run
is disclosed and still releases (§7.13, §10). The path is LLM-free by
construction, asserted with the `explode` provider installed.

## Acceptance criterion
```gherkin
Given a fixture vault holding 100 chunks matching the filter
      field:political-science + claim_type:causal, of which 22 belong to
      source_id "tilly" and 78 belong to other sources
  And a fixture brief DEV30 whose model passes are driven by the `stub` provider
  And the run's trajectory records query_by_tag calls with exactly that filter
  And the run's claims carry grounds over 10 distinct chunks, 6 from "tilly"
When  `axial brief run briefs/DEV30.yaml` runs
Then  the command exits 0
  And data/analyses/DEV30.json carries a source_usage whose filters_observed
      contains that tag filter
  And its "tilly" entry is {evidence_chunk_count: 6, evidence_share: 0.6,
      available_chunk_count: 22, available_share: 0.22, usage_ratio: <0.6/0.22>}
  And no entry carries one of evidence_share / available_share without the other

Given a hand-built analysis record at data/analyses/DEV31.json whose claims'
      grounds all resolve to chunks of a single source_id "gellner"
When  the source-usage computation runs over that record and the fixture vault
      with the `explode` provider installed
Then  zero LLM calls are made
  And source_usage.sources has exactly one entry, for "gellner", with
      evidence_share 1.0 and its real available_share from the fixture vault
  And the record still releases — no failure, no non-zero exit, no validator
      reason reacts to the concentration

Given a hand-built record at data/analyses/DEV32.json with disposition "refuse"
      and empty claims
When  the source-usage computation runs over it
Then  source_usage is present with filters_observed populated and empty sources

Given a hand-built record at data/analyses/DEV33.json whose trajectory filters
      match zero chunks of source_id "zaum" while its grounds cite one
When  the source-usage computation runs over it
Then  the "zaum" entry has available_chunk_count 0, available_share 0, and
      usage_ratio null
```

## Out of scope
- Aggregating across runs — slice 02 (`axial brief usage`).
- **Any threshold on `usage_ratio` and any gating behaviour.** §7.13 and §10 are
  explicit: diagnostic, not gating, in v0. A threshold here would be spec drift.
- Rendering the disclosure into the markdown answer (§7.10) — `analysis-record`
  slice 02.
- Diagnosing which of §7.13's three causes (corpus, retrieval logic, model)
  explains a skew; that inspection reads the trajectory and is founder judgment.
- Optimising the denominator query. The answer is a cached frontmatter index in
  the query layer, shared with `coverage_count` (§7.7) — a `vault-query` concern.
- Any change to the §7.13 field shape or the §7.3 record shape. Both locked.
