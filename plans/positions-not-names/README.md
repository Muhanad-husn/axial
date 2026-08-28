# Feature: Positions, not names — the map re-formed on categories

The argument map is re-formed so that passages meet at shared categories
instead of shared wording, positions gain a category profile that ranks where
relations are asked and gives retrieval an address, and the name-page layer is
demolished only after the re-formed map has been measured against the current
one. The approach and its evidence: `docs/approach-positions-not-names.md`
(§13 is this plan's source) and `docs/approach-positions-not-names-review.md`.

- **Slug:** positions-not-names
- **Created:** 2026-08-28
- **Status:** planning
- **New system?** no
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 [#826](https://github.com/Muhanad-husn/axial/issues/826) | [claim-vocabulary-committed](01-claim-vocabulary-committed.md) | The claim column has a founder-committed category scheme and the corpus is filed against it | ☑ PR open | [#834](https://github.com/Muhanad-husn/axial/pull/834) |
| 02 [#827](https://github.com/Muhanad-husn/axial/issues/827) | [bag-purity-crosstab](02-bag-purity-crosstab.md) | `axial map purity` measures how badly wording bags shred any categorised axis — the go/stop check on the diagnosis | ☑ PR open | [#836](https://github.com/Muhanad-husn/axial/pull/836) |
| 03 [#828](https://github.com/Muhanad-husn/axial/issues/828) | [inner-split-chosen](03-inner-split-chosen.md) | The two candidate inner splits are computed offline over real data and the founder picks one | ☐ todo | — |
| 04 [#829](https://github.com/Muhanad-husn/axial/issues/829) | [reformed-build-groups](04-reformed-build-groups.md) | `axial map build --grouping category` runs extraction over category groups into a variant artifact, current build untouched | ☐ todo | — |
| 05 [#830](https://github.com/Muhanad-husn/axial/issues/830) | [category-consolidation](05-category-consolidation.md) | A second extraction pass per category reunites per-group namings; embedding merge demoted to cross-category folding | ☐ todo | — |
| 06 [#831](https://github.com/Muhanad-husn/axial/issues/831) | [structural-comparison](06-structural-comparison.md) | `axial map compare` puts the two maps side by side, structurally; the founder's go/no-go on everything after | ☐ todo | — |
| 07 | [profiles-and-ranked-relations](07-profiles-and-ranked-relations.md) | Positions carry a category profile and relation neighbourhoods are proposed from profile rank | ☐ todo | — |
| 08 | [retrieval-address-arm](08-retrieval-address-arm.md) | A question enters through the axis intersection — question → region → positions → relations → passages — as a sweep arm | ☐ todo | — |
| 09 | [demolition](09-demolition.md) | Name pages, gather, the name-walking loop, the residue pass, the category join (#825, absorbed) and the dead eval code are deleted, each deletion citing the slice that made it safe | ☐ todo | — |

## Out of scope (whole feature)

- **Read-time category assignment.** Interrogation is untouched (approach §3,
  §4). Assignment is post-hoc via `vocabulary build`, always.
- **Dual category membership.** One passage, one category per axis (approach
  §10). The adjudication fallback for borderline assignments is a future
  decision, taken only if slice 06 shows misassignment dominating.
- **A new judged evaluation gate.** The smoke gate is saturated; slice 06 is
  structural on purpose. Designing a harder judged gate is separate work.
- **Unifying the codebook's five axes with the derived schemes** (approach
  §11) — nothing here requires it.
- **New interrogation questions / axes without an existing answer column.**
  The one-question re-ask path exists (`position_backfill`) but no slice
  needs it.

## Notes / open questions

- **Filed 2026-08-28:** slices 01-06 as #826-#831. Slices 07-09 are drafted
  in `issues/` but deliberately NOT filed until slice 06's go/no-go verdict.
- **#825 folds into slice 09** (founder ruling, 2026-08-28): the category
  join's deletion rides the demolition slice; the slice-09 PR closes #825.

- **Hard gates between slices.** Slice 02 can kill the feature (claim-axis
  purity high → diagnosis wrong). Slice 03 ends in a founder choice. Slice 06
  is the founder's go/no-go; slices 07–09 must not start before it is given.
  Slice 09 additionally waits for 07 and 08.
- **`src/axial/cli.py` is a hot file** — slices 02, 03, 04 and 06 all edit
  it. They are dependency-ordered anyway; do not dispatch 02 and 03 in
  parallel worktrees despite their disjoint modules.
- **Paid runs and their logs.** Slices 01, 04, 05 spend model calls; every
  run writes `data/logs/<date>-<run>/` per the run-logging convention, in the
  main checkout (`data/` does not exist in worktrees).
- **The mechanism vocabulary is already built** (`config/vocabulary.yaml`,
  `data/vocabulary/mechanism/`) and serves slice 02's fixture case and slice
  03's intersection candidate.
