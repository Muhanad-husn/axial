# Feature: Source-usage disclosure — contribution against its denominator

Every analysis record discloses what share of its evidence came from each source
**and how much that source had available** under the tag filters the run actually
queried (§7.13, P0-13). Contribution alone cannot separate a thin corpus, where a
source genuinely is the only coverage, from over-selection, where the run reached
past alternatives that existed; the ratio between contribution and availability
can. The feature exists because all five rung-3 gates of §10 pass on a
well-attributed monoculture — attribution complete, grounds resolving, a
counter-position present, coverage disclosed, confidence banded, and one author's
worldview presented as synthesis — and nothing else in the phase detects it. Slice
01 puts the per-run `source_usage` field on the record; slice 02 aggregates it
across runs sharing a corpus pin so the skew that only shows up over many briefs
becomes visible. Both are deterministic and make zero model calls. The founder
benefits: the bias question stops being a suspicion and becomes a number that
travels with every run.

- **Slug:** source-usage
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** no (a new computation module plus one `axial brief` subcommand
  on the existing CLI; the record and the query API are already built beneath it)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [per-run-source-usage](01-per-run-source-usage.md) | [#265](https://github.com/Muhanad-husn/axial/issues/265) | Every analysis record carries the §7.13 `source_usage` field — `filters_observed[]` from the trajectory plus per source its evidence count and share, its available count and share under those filters, and the `usage_ratio` between them — computed deterministically with zero model calls, gating nothing | ☐ todo | TBD |
| 02 | [cross-run-usage-report](02-cross-run-usage-report.md) | [#266](https://github.com/Muhanad-husn/axial/issues/266) | `axial brief usage` aggregates per-source usage ratios across the records in `data/analyses/` that share a corpus pin, broken down by tag filter, so a source drawing several times its available share whenever queries touch a given tag is visible | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- Slice 01 depends on `analysis-record` slice 01 (#257) — there must be a §7.3 record to carry the field, with claim grounds to
  count and a trajectory log to read `filters_observed` from — and on
  `vault-query` slice 02 (#251), whose `query_by_tag` /
  `query_by_polity` tools count the denominator over the pinned vault.
- Slice 02 depends on slice 01 (#265) — there must be a
  `source_usage` field to aggregate — and on `analysis-foundation` slice 02
  (#248), the corpus-pin manifest that decides
  which records are comparable (§7.12).
- Both slices are **LLM-free by construction**: no model call and no embedding
  call on any path. The acceptance tests assert it mechanically, with the
  `explode` provider installed and never firing.
- Nothing depends on this feature. No rung-3 gate reads `source_usage` in v0
  (§10), by decision.

## Out of scope (whole feature)

- **Gating on concentration.** No threshold on `usage_ratio` blocks release, and
  no rung-3 gate reads the field (§7.13, §10, P0-13). A concentrated run is
  disclosed, never blocked. The promotion condition to a sixth gate is stated in
  §7.13 and is not met by this phase.
- **Choosing that threshold.** There is no defensible concentration cut point yet;
  asserting one before the inspection §7.13 describes would flag legitimately
  concentrated analyses. Slice 02 is the affordance that makes the inspection
  possible; running it across the 26 dev briefs is founder-run operational work.
- Diagnosing *which* of §7.13's three causes — corpus, retrieval logic, model —
  produced an observed skew. The disclosure narrows the cause to one of three; the
  separating inspection uses the trajectory log (§7.6) and is founder judgment,
  not code.
- Any change to the record shape (§7.3) or the `source_usage` shape (§7.13). Both
  are locked and [FIRM]. A shape that seems wrong is a spec-drift issue.
- Rendering the disclosure into the markdown answer (§7.10). `analysis-record`
  slice 02 owns rendering; this feature computes the field it renders.
- The query API's own performance work. See the denominator note below: caching or
  indexing the vault scan is a `vault-query` concern.
- Comparing records across different corpus pins. §7.12 says two runs are
  comparable only if their pins match; slice 02 partitions on the pin rather than
  reconciling across pins.

## Notes / open questions

- **Denominator cost, and the answer to it.** Counting `available_chunk_count`
  re-runs the run's filters over a ~17k-chunk vault. That is deterministic and
  model-free, but it is not free in wall time. Two things make it acceptable. It
  happens once per brief run, downstream of an expensive synthesis call, so it is
  noise by comparison. And it can share a single vault walk with `coverage_count`
  (§7.7), which already needs one. The implementer should note that the query API
  likely wants a cached frontmatter index rather than repeated full-vault walks —
  and that this is a `vault-query` concern, not a `source-usage` one. This feature
  calls the tools; it does not optimise them.
- **Gates nothing in v0, on purpose.** §7.13 states the promotion condition and
  §10 states the deliberate absence from the gate table. Say it plainly in review:
  a concentrated run is disclosed and recorded, and it still releases. Slice 02 is
  what makes the promotion condition checkable later.
- **`source_id` comes from the `chunk_id`, not from a lookup.** Every `chunk_id`
  is `{source_id}_{page_start}_{page_end}-{section_label}_{seq}`, so resolving a
  grounds pointer to its source is a parse, not a query. Artifact grounds
  (`ref_type: artifact`) carry `source_id` in their frontmatter. Slice 01 should
  pin the artifact-grounds handling with a test rather than leaving it implied.
- **`filters_observed` is a union, and its shape needs pinning.** §7.13 defines it
  as the union of the tag filters queried this run, read from the trajectory log's
  `args` (§7.6). The trajectory records `query_by_tag` and `query_by_polity` calls
  with their arguments; deriving a stable, deduplicated, deterministically ordered
  filter list from those args is slice 01's first unit test. It is also the join
  key slice 02 aggregates on, so its ordering and normalisation matter beyond one
  record.
- **Empty is a valid answer.** `sources` is empty on disposition `refuse` and on
  any run whose claims carry no grounds (§7.13). `usage_ratio` is null when
  `available_share` is 0. Neither is an error; both are asserted.
- **Designed for the aggregate.** One run's distribution is weak evidence (§7.13).
  The per-run shape is keyed on `source_id` and joinable on `filters_observed`
  precisely so slice 02 can pool it. Any slice-01 choice that breaks that join —
  unstable filter ordering, a source key that varies by run — is a bug in slice 01
  even though slice 01's own tests would pass.
