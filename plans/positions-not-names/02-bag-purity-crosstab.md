# Slice 02: `axial map purity` — the cross-tab that confirms or kills the diagnosis

- **Feature:** positions-not-names
- **Slice slug:** bag-purity-crosstab
- **Issue:** [#827](https://github.com/Muhanad-husn/axial/issues/827)
- **Branch:** feat/positions-not-names/02-bag-purity-crosstab
- **Project directory:** .
- **Status:** ☑ built, awaiting review/PR
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial map purity --column <c>` joins the current map build's bag assignments
against a built vocabulary column and reports how impure the wording bags are
on that axis and how widely each category is scattered across bags. Run on
`claim`, it is the feature's first kill switch: high purity there means the
central diagnosis is wrong and the feature stops.

## INVEST check

- **Independent:** reads two artifacts that already exist on disk
  (`bag_state.json`, `data/vocabulary/<column>/assignments.jsonl`); zero
  model calls.
- **Valuable:** turns the approach's central claim into a number per axis,
  before any paid rebuild; reused after slice 05 to verify the re-formed
  groups.
- **Small:** one pure-function module, one CLI wiring, fixtures.
- **Testable:** deterministic output over fixture bags and assignments.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a map build directory with bag_state.json and a built vocabulary column
When  `uv run axial map purity --column claim` runs
Then  it prints, for bags with 2+ categorised members: bag count, median and
      mean purity (share of a bag in its modal category), share of pure bags,
      and distinct categories per bag
And   the reverse table: per category, how many bags it is scattered across
      (min / median / max)
And   chunks missing from either side are counted and reported, never
      silently dropped
```

- **Boundary / endpoint:** CLI — `uv run axial map purity --column <c>`
- **e2e test type:** API/integration test (pytest, CLI-level, tmp fixture dirs)
- **e2e test file (planned):** src/axial/test_cli.py (extended)

## Files (parallel-safety declaration)

```aeo-independence
slice: 02-bag-purity-crosstab
creates: src/axial/argmap/purity.py
creates: src/axial/argmap/test_purity.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-claim-bag-purity/summary.md
depends-on: 01-claim-vocabulary-committed
```

## Inner loop — initial unit test list

- [ ] Purity of a bag: modal-category share over categorised members only.
- [ ] Bags with fewer than 2 categorised members are excluded from purity but
      counted in the coverage line.
- [ ] Category scatter: distinct bag count per category, min/median/max.
- [ ] A chunk present in bags but not in the vocabulary column (and vice
      versa) lands in the reported coverage gap, not in an exception.
- [ ] Latest-pin resolution: with no `--pin`, the newest map directory is
      used and named in the output.

## Operational steps inside the slice

1. Run against `claim` and `mechanism` on the current pin; write
   `data/logs/2026-08-28-claim-bag-purity/`.
2. Record the verdict in the summary. **Kill condition, stated up front:**
   if claim-axis median purity is high and scatter low — wording bags already
   respect the claim categories — stop the feature and take the finding back
   to the approach doc. (Mechanism-axis baseline, measured 2026-08-28:
   median purity 0.5, 13.9% pure, scatter median 92 bags.)

## Out of scope for this slice (deferred)

- Any grouping change (slice 03/04).
- Purity of re-formed groups (re-run of this command after slice 05).

## Definition of done

- [x] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [x] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [x] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`) -- pending push/PR.
- [x] Claim-axis run done, log written, kill condition explicitly judged in the summary.
- [ ] Evidence collected and PR opened into main (`safe-pr`) -- left to the orchestrator per this dispatch's own instructions (no PR opened from inside the build).

## Status / progress log

- 2026-08-28 planned.
- 2026-08-28 built: `src/axial/argmap/purity.py` + `test_purity.py` (14 unit
  tests), `axial map purity` wired into `cli.py`/`test_cli.py` (5 CLI-level
  tests), fast tier green (2,478 tests), ruff clean. Claim-axis run against
  `D:/axial/data` (pin `9b796b3a6312b329`): median purity 0.56, 17.3% pure,
  scatter median 141 bags -- kill condition NOT met (mechanism baseline:
  0.5 / 13.9% / 92). Log: `data/logs/2026-08-28-claim-bag-purity/`. The two
  #826 pairs rank 3rd and 5th of 36 claim-axis pairs by co-occurrence --
  flagged for the founder, no scheme edit made.
