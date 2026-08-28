# feat(positions-not-names): `axial map purity` confirms or kills the diagnosis [slice 02]

**Spec:** docs/approach-positions-not-names.md#2-what-is-broken-and-what-is-not · **Plan:** plans/positions-not-names/02-bag-purity-crosstab.md
**Depends on:** #826
**Labels:** enhancement, sub:analysis-v0

## Deliverable

`axial map purity --column <c>` joins the current build's `bag_state.json`
against a built vocabulary column and reports bag purity (modal-category
share, share of pure bags, distinct categories per bag) and category scatter
(bags per category, min/median/max), with coverage gaps counted, never
dropped. Run on `claim`, it is the feature's kill switch: high purity there
means the central diagnosis is wrong and the feature stops. Mechanism-axis
baseline already measured: median purity 0.5, 13.9% pure, scatter median 92
bags.

## Mechanism

A pure-function module over two artifacts already on disk; zero model calls.
CLI wiring in `axial map`. Re-run unchanged after slice 05 to verify the
re-formed groups.

## Acceptance criterion

```gherkin
Given a map build directory with bag_state.json and a built vocabulary column
When  `uv run axial map purity --column claim` runs
Then  it prints, for bags with 2+ categorised members: bag count, median and
      mean purity, share of pure bags, and distinct categories per bag
And   the reverse table: per category, how many bags it is scattered across
      (min / median / max)
And   chunks missing from either side are counted and reported, never
      silently dropped
```

## Files

```aeo-independence
slice: 02-bag-purity-crosstab
creates: src/axial/argmap/purity.py
creates: src/axial/argmap/test_purity.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-claim-bag-purity/summary.md
depends-on: 01-claim-vocabulary-committed
```

## Out of scope

- Any grouping change; purity of re-formed groups (re-run after slice 05).
