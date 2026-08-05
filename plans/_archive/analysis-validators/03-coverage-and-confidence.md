# Slice 03: Coverage map & confidence disclosure — thin coverage is disclosed as thin

- **Feature:** analysis-validators
- **Slice slug:** coverage-and-confidence
- **GitHub issue:** #260
- **Branch:** `feat/analysis-validators/03-coverage-and-confidence`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** `analysis-record` slice 01 (the §7.3 record whose claims carry
  `polities_touched` and `grounds`); `vault-query` (`coverage_count`,
  `query_by_polity`)

## Goal — the minimum testable behaviour

A **per-polity coverage map is computed deterministically from
`polities_touched`, never asked of a model** (§7.7). For every polity the record's
claims touch, the map carries:

```
polity -> {corpus_chunk_count, evidence_chunk_count, coverage_band}
```

- `corpus_chunk_count` — from `coverage_count` over the **whole vault**, the
  count of substantive chunks engaging that polity.
- `evidence_chunk_count` — from **this run's** grounds: the count of grounds
  chunks whose `polities_touched` includes the polity.
- `coverage_band` — `dense` / `moderate` / `thin`, derived from the counts against
  a **stated tunable threshold, proven via inspection** in the spirit of the
  Phase-A chunk band (PRODUCT.md §7.7).

The starting cut points land in config as `coverage_bands`, not as literals:
`thin` below 20 corpus chunks, `moderate` from 20 to 99, `dense` at 100 and
above. These are a starting hypothesis over a ~17k-chunk vault, to be proven by
inspection against the real corpus — an `axial brief coverage <brief_id>` (or
equivalent inspection affordance) prints the per-polity counts and bands so the
founder can look at the distribution before the numbers are trusted, exactly as
`axial chunk examine` proved the chunk band.

The validator then enforces two things and **blocks release** on either: a
`coverage_map` entry exists for **every** polity the claims touch, and the record
carries a `confidence: {overall_band, rationale}` disclosure with a non-empty
rationale. Finally, a claim over a thinly-covered polity is not disclosed with
dense-case confidence: an overall confidence at the top band while the coverage
map contains a `thin` polity fails as an unjustified confidence disclosure.

## INVEST check

- **Independent:** reads a finished record plus the vault's coverage counts.
  Independent of slices 01 and 02; touches no upstream stage.
- **Valuable:** Principle V made mechanical. The corpus is uneven by construction
  — some polities have a shelf of sources, some have a paragraph — and an answer
  that does not say which is quietly overconfident. The map is the number the
  calibration gate later scores against.
- **Small:** one fold over claims → polities, two counts per polity, one band
  lookup, two presence assertions.
- **Testable:** a fake vault with a deliberately lopsided polity distribution, a
  hand-built record whose claims touch both a dense and a thin polity, and a
  configured band table. Zero model calls anywhere on the path.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a vault in which coverage_count reports 240 chunks for polity "Syria"
      and 6 chunks for polity "Yemen"
  And an analysis record at data/analyses/DEV20.json whose claims carry
      polities_touched ["Syria", "Yemen"] across their grounds
  And config coverage_bands of {thin: <20, moderate: 20-99, dense: >=100}
When  `axial brief validate DEV20` runs
Then  the command exits 0
  And the record's coverage_map["Syria"] is
      {corpus_chunk_count: 240, evidence_chunk_count: <n>, coverage_band: "dense"}
  And the record's coverage_map["Yemen"] is
      {corpus_chunk_count: 6, evidence_chunk_count: <m>, coverage_band: "thin"}
  And zero LLM calls were made building the map (the `explode` provider is
      installed and never fires)

Given an analysis record at data/analyses/DEV21.json whose claims touch "Yemen"
  And whose coverage_map has no "Yemen" entry
When  `axial brief validate DEV21` runs
Then  the command exits non-zero
  And the report reason is "missing_coverage_entry" naming "Yemen"
  And no answer is released for DEV21

Given an analysis record at data/analyses/DEV22.json with a complete coverage_map
  And whose confidence is {overall_band: null, rationale: ""}
When  `axial brief validate DEV22` runs
Then  the command exits non-zero
  And the report reason is "missing_confidence_disclosure"

Given an analysis record at data/analyses/DEV23.json whose coverage_map contains
      a "thin" polity
  And whose confidence.overall_band is the top band
When  `axial brief validate DEV23` runs
Then  the command exits non-zero
  And the report reason is "confidence_exceeds_coverage" naming the thin polity
```

- **Boundary / endpoint:** CLI — `axial brief validate <brief_id>` and the
  coverage inspection affordance; the record's `coverage_map` and `confidence`
  sections; the `coverage_bands` config block.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_coverage_and_confidence.py` —
  authored by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Polity fold: the polity set is the union of the claims' `polities_touched`;
      a polity appearing in five claims yields exactly one map entry.
- [ ] `corpus_chunk_count` comes from `coverage_count` over the whole vault, not
      from the run's evidence — a fake query API asserts the call.
- [ ] `evidence_chunk_count` counts distinct grounds chunks engaging the polity;
      the same chunk cited by two claims counts once.
- [ ] Band derivation at the boundaries: 19 → thin, 20 → moderate, 99 → moderate,
      100 → dense, with cut points read from config, not literals.
- [ ] Overriding `coverage_bands` in config changes the band with no code change.
- [ ] Determinism: the same record over the same pinned vault yields a
      byte-identical coverage map (ordering is stable).
- [ ] Model-free by construction: the whole map path runs with the `explode`
      provider installed and makes zero calls.
- [ ] Presence checks: a polity touched by claims but absent from the map fails;
      an absent, null, or empty-rationale `confidence` fails.
- [ ] Confidence-vs-coverage check: top-band confidence with a thin polity in the
      map fails; top-band confidence with no thin polity passes; a lower band
      with a thin polity passes.
- [ ] A `refuse`-disposition record with empty `claims` yields an empty coverage
      map and passes vacuously (§7.2).
- [ ] The coverage inspection affordance prints per-polity counts and bands for a
      record and makes zero model calls.

## Out of scope for this slice (deferred)

- The **calibration metric** (calibration error between disclosed confidence and
  judged correctness, §10). That is `rung3-gates` slice 02, and its metric choice
  is a live spec Open Question.
- Settling the **confidence vocabulary** — discrete bands vs a numeric score
  (§7.4, Open Questions). This slice reads whatever `confidence.overall_band` the
  record carries and checks it is disclosed and not inconsistent with thin
  coverage; it does not define the vocabulary.
- Per-claim confidence checking beyond the overall disclosure. The §7.4 per-claim
  `confidence` field exists; scoring it is a gate concern.
- Tuning the band cut points against the real corpus. The slice lands them as a
  config-driven starting hypothesis plus the inspection affordance that makes
  proving them possible; the proving pass is founder-run operational work on the
  full ~30-source vault.
- Any change to the §7.7 map shape or the §7.3 `confidence` shape. Both locked.

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
</content>
