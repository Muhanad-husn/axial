# Slice 01: Gold-set scoring harness

- **Feature:** eval
- **Slice slug:** score-gold-set
- **GitHub issue:** #135
- **Branch:** feat/eval/01-score-gold-set
- **Project directory:** .
- **Status:** ☑ in review — PR #136 (awaiting founder approval)
- **Walking skeleton?** yes (introduces the `axial eval` subcommand + the `eval.py` module)

## Goal — the minimum testable behaviour

`axial eval` scores the pipeline's tagging against the Academic's returned labels,
offline. It reads the returned `label_sheet.xlsx` from `data/gold/labels/` (the answer
key) and the tagger's sampled chunk records from `data/gold/chunks/*.json`, joins them on
`chunk_id`, and writes a scoring report to `data/gold/labels/` carrying:

1. **Per-axis raw agreement** for `field`, `empirical_scope`, `claim_type`,
   `theory_school` — among chunks the Academic labeled on that axis, the fraction where
   tagger value == Academic value.
2. **Tag coverage** — per-tag application counts across the gold set, surfacing
   never-applied schema tags (compared against the loaded vocabulary).
3. **Disagreements** — a per-chunk listing (chunk_id, axis, tagger value, Academic value)
   of every mismatch.

Offline: no LLM call. Deterministic. This closes the §10 measurement loop and is the gate
the "no full-corpus run until the eval closes" rule (§4.5) depends on.

## INVEST check

- **Independent:** reads only what `gold sample` (#53) and the label sheet (#54) already
  wrote, plus the codebook vocab via the existing `gold._axis_vocabularies`. Introduces a
  new `axial eval` subcommand and `src/axial/eval.py`; touches no existing pass.
- **Valuable:** turns returned labels into the pipeline's self-measurement — per-axis
  agreement, cut candidates (never-used tags), and the disagreement list a schema revision
  reads from.
- **Small:** load xlsx (openpyxl, already a dep) → load chunk records → join on chunk_id →
  count/compare per axis → write report. No new network, no new heavy dependency.
- **Testable:** given a fixture returned sheet and matching chunk records with known
  agreements/disagreements and one never-applied tag, assert the report's agreement
  fractions, the named never-used tag, and the disagreement rows.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a returned label_sheet.xlsx under data/gold/labels/ whose four axis columns carry Academic labels
And   matching tagger chunk records under data/gold/chunks/ (some axes agreeing, some disagreeing, one schema tag never applied)
When  the user runs `axial eval`
Then  it exits 0 and writes a scoring report under data/gold/labels/
And   the report gives per-axis raw agreement for field, empirical_scope, claim_type and theory_school computed only over Academic-labeled chunks
And   the report gives per-tag application counts and names the schema tag that was never applied
And   the report lists each disagreeing chunk with its chunk_id, axis, tagger value and Academic value
And   with no returned sheet present under data/gold/labels/ it exits non-zero telling the operator to place the returned label_sheet.xlsx there
And   re-running is deterministic and makes no LLM call
```

- **Boundary / endpoint:** CLI command `axial eval`
- **Outer test type:** pytest integration test (subprocess; offline — no provider)
- **Outer test file (planned):** tests/test_eval.py — test-author, red, locked
- **Fixtures:** a synthetic returned `label_sheet.xlsx` + matching `data/gold/chunks/*.json`
  records, authored in the arrange step (or under `tests/fixtures/eval/`). No source text —
  synthetic prose only (copyright rule).

## Inner loop — initial unit test list

- [ ] read the returned label sheet (openpyxl) into per-chunk axis labels keyed by chunk_id; ignore provenance/`notes` columns
- [ ] load the tagger chunk records under `data/gold/chunks/` into per-chunk axis tags keyed by chunk_id
- [ ] join sheet ↔ records on chunk_id; a chunk missing from either side is reported, not silently dropped
- [ ] per-axis raw agreement: over chunks with a non-empty Academic label on that axis, fraction where tagger == Academic
- [ ] an empty Academic cell excludes that (chunk, axis) from the agreement denominator (unlabeled ≠ disagree)
- [ ] per-tag application counts across the gold set, per axis
- [ ] never-applied tags: schema vocab entries (via `gold._axis_vocabularies`) with zero applications, surfaced per axis
- [ ] disagreement rows: (chunk_id, axis, tagger value, Academic value) for each mismatch
- [ ] an Academic value outside the axis vocabulary is flagged as an addition candidate, not a plain mismatch (where cleanly detectable)
- [ ] write the report to `data/gold/labels/` (machine-readable + a readable summary); re-running overwrites in place, no stale files
- [ ] missing returned sheet → typed error → CLI non-zero exit with a message naming `data/gold/labels/`

## Out of scope for this slice (deferred)

- **κ / Cohen's / Krippendorff's** — P1-2; raw agreement only.
- **Contested/candidate keep-cut-rename decisions** — a founder judgment read *from* the
  report, not automated (§10).
- **`role_in_argument` agreement** — a stratum, not a labeled axis; nothing to score against.
- **Sheet delivery/fetch** — `axial gold deliver` handles handoff; the Academic returns the
  sheet to `data/gold/labels/` out of band.
- **Real Academic labels** — built and tested on a synthetic placeholder sheet (§11); the
  real run is a data-swap, no code change.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder approval.

## Status / progress log

- 2026-07-13 planned. Single slice per founder decision (agreement + coverage + disagreements share one join and one report).
- 2026-07-13 built: red outer test `a193ebc` → green impl `ddee573` → reviewer findings fixed `350cc0b` → PR **#136** into main. Full suite 655 passed; two-stage review passed (2 stage-2 findings fixed, re-review clean). Awaiting founder approval to merge.
