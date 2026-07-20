# Slice 01: Per-run source usage — contribution disclosed with its denominator

- **Feature:** source-usage
- **Slice slug:** per-run-source-usage
- **GitHub issue:** #265
- **Branch:** `feat/source-usage/01-per-run-source-usage`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** `analysis-record` slice 01 (the §7.3 record that carries the
  field, its claim grounds, and its §7.6 trajectory log); `vault-query` slice 02
  (`query_by_tag` / `query_by_polity`, which count the denominator over the pinned
  vault)

## Goal — the minimum testable behaviour

Every analysis record carries the §7.13 `source_usage` field, non-nullable,
computed **deterministically with zero model calls**:

```
source_usage: {
  filters_observed: [ <tag_filter> ],   # union of the tag filters queried this run
  sources: [ {
    source_id,
    evidence_chunk_count,               # chunks of this source in claim grounds
    evidence_share,                     # of all grounds chunks in the run
    available_chunk_count,              # chunks of this source matching filters_observed
    available_share,                    # of all chunks matching filters_observed, corpus-wide
    usage_ratio                         # evidence_share / available_share; null when available_share is 0
  } ]
}
```

`filters_observed` is read from the trajectory log's recorded `args` (§7.6), the
filters the run *actually* queried — not the filters it might have queried.
`evidence_chunk_count` folds the claim grounds: each grounds pointer resolves to a
vault id, and every `chunk_id` embeds its `source_id`, so the fold is a parse, not
a lookup. `available_chunk_count` re-runs `filters_observed` over the pinned vault
through the §7.5 query tools, which is where the denominator comes from. The two
figures are **always present together**: a contribution share is never disclosed
without the availability it should be read against.

The field **gates nothing**. A record whose grounds all come from one source is
disclosed as such and still releases, exit 0 (§7.13, §10, P0-13).

Edge cases are part of the contract: `sources` is empty on disposition `refuse`
and on any run whose claims carry no grounds; `usage_ratio` is null when
`available_share` is 0.

## INVEST check

- **Independent:** reads a finished record plus the query API. Touches no upstream
  stage, no prompt, no model config.
- **Valuable:** the one thing in the phase that can see a well-attributed
  monoculture. All five rung-3 gates pass on one; this field is what makes the
  concentration visible at all.
- **Small:** one fold over grounds → sources, one filter-union derivation from the
  trajectory, one denominator query per source, three divisions.
- **Testable:** a fixture vault with a known per-source chunk distribution, a
  hand-built record whose grounds are deliberately lopsided, and a hand-built
  trajectory. Zero model calls anywhere on the path, asserted mechanically.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault holding 100 chunks matching the filter
      field:political-science + claim_type:causal, of which 22 belong to
      source_id "tilly" and 78 belong to other sources
  And a fixture brief DEV30 whose model passes are driven by the `stub` provider
  And the run's trajectory records query_by_tag calls with exactly that filter
  And the run's claims carry grounds over 10 distinct chunks, 6 of them from
      source_id "tilly"
When  `axial brief run briefs/DEV30.yaml` runs
Then  the command exits 0
  And data/analyses/DEV30.json carries a source_usage whose filters_observed
      contains that tag filter
  And source_usage.sources entry for "tilly" is
      {evidence_chunk_count: 6, evidence_share: 0.6,
       available_chunk_count: 22, available_share: 0.22,
       usage_ratio: <0.6/0.22>}
  And every entry carries evidence_share and available_share together — no entry
      has one without the other

Given a hand-built analysis record at data/analyses/DEV31.json whose claims'
      grounds all resolve to chunks of a single source_id "gellner"
When  the source-usage computation runs over that record and the fixture vault
      with the `explode` provider installed
Then  zero LLM calls are made (the `explode` provider never fires)
  And source_usage.sources has exactly one entry, for "gellner", with
      evidence_share 1.0 and its real available_share from the fixture vault
  And the record still releases — no failure, no non-zero exit, no validator
      reason reacts to the concentration

Given a hand-built analysis record at data/analyses/DEV32.json with disposition
      "refuse" and empty claims
When  the source-usage computation runs over that record
Then  source_usage is present with filters_observed from the trajectory and an
      empty sources list

Given a hand-built analysis record at data/analyses/DEV33.json whose trajectory
      filters match zero chunks of source_id "zaum" while its grounds cite one
When  the source-usage computation runs over that record
Then  the "zaum" entry has available_chunk_count 0, available_share 0, and
      usage_ratio null
```

- **Boundary / endpoint:** the `source_usage` field on the record at
  `data/analyses/<brief_id>.json`, written on the `axial brief run` path; the
  computation seam itself, callable over a record plus the query API with no LLM
  client present.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_source_usage.py` — authored by the
  test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] `filters_observed` derivation: the union of `query_by_tag` /
      `query_by_polity` filters in the trajectory's `args`, deduplicated and
      deterministically ordered; the same trajectory yields the same list every
      time.
- [ ] Trajectory entries for non-filter tools (`get_chunk`, `follow_backlinks`)
      contribute nothing to `filters_observed`.
- [ ] `source_id` resolution: a `chunk_id` parses to its `source_id`; an
      `artifact` grounds pointer resolves through the artifact's `source_id`
      frontmatter.
- [ ] Evidence fold: distinct grounds chunks are counted once even when two claims
      cite the same chunk; `evidence_share` denominators use the distinct set.
- [ ] `evidence_share` sums to 1.0 across sources on any run with grounds.
- [ ] Denominator: `available_chunk_count` comes from re-running
      `filters_observed` through the query API over the whole vault, not from the
      run's evidence — a fake query API asserts the call and its arguments.
- [ ] `available_share` is that source's count over the corpus-wide count of
      chunks matching `filters_observed`.
- [ ] `usage_ratio` is `evidence_share / available_share`, and is null — not 0,
      not an error — when `available_share` is 0.
- [ ] A source appearing in evidence but not in the filter results, and a source
      appearing in the filter results but not in evidence, are both handled
      without a KeyError.
- [ ] Empty `sources` on `refuse` disposition, and on a record whose claims carry
      no grounds; `filters_observed` still populated in both.
- [ ] Model-free by construction: the whole path runs with the `explode` provider
      installed and makes zero calls.
- [ ] Determinism: the same record over the same pinned vault yields byte-identical
      `source_usage`, including source ordering.
- [ ] Gates nothing: a record with `evidence_share` 1.0 on one source produces no
      failure, no non-zero exit, and no validator reason.

## Out of scope for this slice (deferred)

- **Aggregating across runs.** Slice 02 (`axial brief usage`). This slice writes
  one record's field.
- **Any threshold on `usage_ratio`,** and any gating behaviour. §7.13 and §10 are
  explicit: diagnostic, not gating, in v0. Introducing a threshold here would be
  spec drift.
- Rendering the disclosure into the markdown answer (§7.10) — `analysis-record`
  slice 02.
- Diagnosing which of §7.13's three causes (corpus, retrieval logic, model)
  explains an observed skew. That inspection reads the trajectory and is founder
  judgment.
- Optimising the denominator query. The wall-time answer is a cached frontmatter
  index in the query layer, shared with `coverage_count` (§7.7) — a `vault-query`
  concern, not this slice's.
- Any change to the §7.13 field shape or the §7.3 record shape. Both locked and
  [FIRM].

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
