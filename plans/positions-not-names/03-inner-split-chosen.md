# Slice 03: The inner split is computed both ways and chosen

- **Feature:** positions-not-names
- **Slice slug:** inner-split-chosen
- **Issue:** [#828](https://github.com/Muhanad-husn/axial/issues/828)
- **Branch:** feat/positions-not-names/03-inner-split-chosen
- **Project directory:** .
- **Status:** ☑ built — founder chose claim × mechanism
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial map grouping-report` computes, offline and with zero model calls, both
candidate groupings from approach §6 — claim × mechanism intersection, and
per-claim-category embedding sub-clustering — over the real corpus, and
reports group-size distributions, coverage lost, and projected extraction
slice counts, so the founder can choose one on numbers instead of taste.

## INVEST check

- **Independent:** reads selected passages and vocabulary assignments already
  on disk; the grouping functions it builds are exactly what slice 04 wires
  into the build, so nothing here is throwaway.
- **Valuable:** the load-bearing design decision of the whole feature is made
  on measurement.
- **Small:** two grouping functions (one a join, one reusing the existing
  encoder/clustering seams from `build.py`), one report.
- **Testable:** both groupings are deterministic given fixture passages and
  assignments (the embedding variant through the existing injectable
  encoder/cluster_fn seams).

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given data/vocabulary/claim/ and data/vocabulary/mechanism/ exist and the
      current build's selected passages are readable
When  `uv run axial map grouping-report` runs
Then  it prints, per candidate: group count, group-size min/median/max,
      passages left ungrouped (refusals compounded, for the intersection;
      no claim category, for the sub-clustering -- this module carries no
      noise-label convention of its own, so a residue label from an
      injected cluster_fn becomes a group like any other, not a carve-out),
      and projected extraction slices at EXTRACT_SLICE
And   the two candidates print side by side in one table
```

- **Boundary / endpoint:** CLI — `uv run axial map grouping-report`
- **e2e test type:** API/integration test (pytest, CLI-level, injected encoder/cluster fakes)
- **e2e test file (planned):** src/axial/test_cli.py (extended)

## Files (parallel-safety declaration)

```aeo-independence
slice: 03-inner-split-chosen
creates: src/axial/argmap/grouping.py
creates: src/axial/argmap/test_grouping.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-inner-split-choice/summary.md
depends-on: 02-bag-purity-crosstab
```

(Dependency on 02 is ordering, not data: both edit `src/axial/cli.py` — do
not build them in parallel worktrees.)

## Inner loop — initial unit test list

- [ ] `group_by_intersection`: passages sharing (claim category, mechanism
      category) land in one group; a passage refused on either axis is
      reported ungrouped, never silently dropped.
- [ ] `group_by_subcluster`: passages grouped by claim category, then split
      inside it through the injected cluster_fn; every passage with a claim
      category lands in exactly one group.
- [ ] Slice projection: a group of size n projects ceil(n / EXTRACT_SLICE)
      slices, summed per candidate.
- [ ] Group labels are deterministic across runs on identical input.

## Operational steps inside the slice

1. Run the report over the real corpus in the main checkout; write
   `data/logs/2026-08-28-inner-split-choice/`.
2. **Founder chooses the inner split.** Hard gate. The choice and the two
   tables go into the summary and into this plan's progress log; slice 04
   builds only the chosen variant.

## Out of scope for this slice (deferred)

- Wiring either grouping into `map build` (slice 04).
- Any model call.
- A third candidate — if both measure badly, that is a founder conversation,
  not an improvised variant.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Real-corpus report run, log written, founder's choice recorded.
- [ ] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
- 2026-08-29 built: `axial map grouping-report` computes both candidates offline,
  zero model calls. Real-corpus run in the main checkout at pin
  `9b796b3a6312b329`, 6,010 selected passages; log in
  `data/logs/2026-08-28-inner-split-choice/`.

  | | claim × mechanism | claim + subcluster |
  |---|---|---|
  | groups | 167 | 1,181 |
  | size min / median / max | 1 / 15.00 / 248 | 1 / 2.00 / 139 |
  | ungrouped | 797 | 17 |
  | projected slices (EXTRACT_SLICE=55) | 207 | 1,190 |

  The intersection arm's 797 ungrouped, per axis: 9 hold no claim category, 780
  no mechanism category, 8 neither.

  The subcluster arm's inner threshold was swept (0.50–0.90) before the
  comparison was read, because it inherits `BAG_DISTANCE_THRESHOLD` from
  corpus-wide bagging rather than being chosen for splitting inside a category.
  No setting produces balanced groups: 0.50–0.60 stay fragmented at median 2–3,
  0.70 gives median 5 with a 484-passage largest group, and 0.80–0.90 collapse
  to blobs of 1,577 and 1,648. The comparison is not a threshold artifact.

- 2026-08-29 **founder chose `claim` × `mechanism`.** Slice 04 (#829) builds only
  that variant. Accepted price: 797 passages, 13.3% of the universe, are missing
  a category on at least one axis and form no cell — the compounded refusal rate
  §6 predicted. 780 are missing only the mechanism axis, 9 only the claim axis,
  8 both, so the claim-only fallback slice 04 has to decide about covers 788 of
  them, not all 797.
  `group_by_subcluster` stays in `grouping.py` as the measured alternative,
  unwired.
- 2026-08-29 review pass: reviewer and verifier both DONE_WITH_CONCERNS, six
  findings fixed in `e55df01` and the report re-run over the same pin with no
  number moving. The load-bearing one was in this log: it attributed all 797
  ungrouped passages to a missing mechanism category, which the report had never
  measured per axis. Corrected above. The others were disclosure and dead code —
  the subcluster threshold now prints in the header, the slices row names
  `EXTRACT_SLICE`, the unreachable `NOISE_LABEL` branch is gone, the "zero
  network" claim is corrected to what the local encoder actually does, and
  `sweep.py` is committed as evidence.
