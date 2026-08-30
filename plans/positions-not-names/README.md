> ## Closed 2026-08-30 — no-go on the rebuild
>
> Slice 06's structural comparison ran and the re-formed map did not clear the
> bar: **D2 failed** (held-out purity 0.6620 against 0.7597), **D4 failed**
> (8.5% of passages reaching no position against a 6.9% ceiling), D1 and D3
> came back not resolved at this sample, and D5 was not run because a veto
> cannot rescue two failures. Failure conditions 2 and 4 of
> [#831](https://github.com/Muhanad-husn/axial/issues/831) are met.
>
> The founder shelved the direction the same day. **Slices 07–09 are retired
> unbuilt** — they were gated on a go that never came — and **nothing was
> demolished**: the name pages, gather, the residue pass and the retrieval loop
> all stand, and the default build path is untouched.
>
> What the rebuild did deliver is book-spread — positions reaching across many
> more books, in every size band. What it could not show is any improvement in
> whether a position is one argument, and it lost more passages doing it.
>
> Full log: `data/logs/2026-08-30-map-structural-comparison/`. What stays in
> the codebase: `axial vocabulary build`, `axial map purity`,
> `axial map grouping-report` and `axial map compare` — all offline, all
> reusable, none of them wired into the default path.

# Feature: Positions, not names — the map re-formed on categories

The argument map is re-formed so that passages meet at shared categories
instead of shared wording, positions gain a category profile that ranks where
relations are asked and gives retrieval an address, and the name-page layer is
demolished only after the re-formed map has been measured against the current
one. The approach and its evidence: `docs/approach-positions-not-names.md`
(§13 is this plan's source) and `docs/approach-positions-not-names-review.md`.

- **Slug:** positions-not-names
- **Created:** 2026-08-28
- **Status:** closed — slices 01–06 built, slice 06 returned **no-go**, slices 07–09 retired unbuilt (2026-08-30)
- **New system?** no
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 [#826](https://github.com/Muhanad-husn/axial/issues/826) | [claim-vocabulary-committed](01-claim-vocabulary-committed.md) | The claim column has a founder-committed category scheme and the corpus is filed against it | ☑ merged | [#834](https://github.com/Muhanad-husn/axial/pull/834) |
| 02 [#827](https://github.com/Muhanad-husn/axial/issues/827) | [bag-purity-crosstab](02-bag-purity-crosstab.md) | `axial map purity` measures how badly wording bags shred any categorised axis — the go/stop check on the diagnosis | ☑ merged | [#836](https://github.com/Muhanad-husn/axial/pull/836) |
| 02b [#838](https://github.com/Muhanad-husn/axial/issues/838) | *(no plan file — filed from #831's bar)* | The held-out `position` column is built, before slice 03, so D2 has a baseline chosen without seeing the result | ☑ merged | [#839](https://github.com/Muhanad-husn/axial/pull/839) |
| 03 [#828](https://github.com/Muhanad-husn/axial/issues/828) | [inner-split-chosen](03-inner-split-chosen.md) | The two candidate inner splits are computed offline over real data and the founder picks one | ☑ merged | [#843](https://github.com/Muhanad-husn/axial/pull/843) |
| 04 [#829](https://github.com/Muhanad-husn/axial/issues/829) | [reformed-build-groups](04-reformed-build-groups.md) | `axial map build --grouping category` runs extraction over category groups into a variant artifact, current build untouched | ☑ merged | [#844](https://github.com/Muhanad-husn/axial/pull/844) |
| 05 [#830](https://github.com/Muhanad-husn/axial/issues/830) | [category-consolidation](05-category-consolidation.md) | A second extraction pass per category reunites per-group namings; embedding merge demoted to cross-category folding | ☑ merged | [#845](https://github.com/Muhanad-husn/axial/pull/845) |
| 06 [#831](https://github.com/Muhanad-husn/axial/issues/831) | [structural-comparison](06-structural-comparison.md) | `axial map compare` decides on D1–D5 — book-spread ratio, held-out `position` purity, coherence floor, unplaced share, blind paired hand-sample — against a forced replicate's error bar; the founder's go/no-go on everything after | ☑ merged — **no-go** | [#846](https://github.com/Muhanad-husn/axial/pull/846) |
| 07 | [profiles-and-ranked-relations](07-profiles-and-ranked-relations.md) | Positions carry a category profile and relation neighbourhoods are proposed from profile rank | ✗ retired unbuilt | — |
| 08 | [retrieval-address-arm](08-retrieval-address-arm.md) | A question enters through the axis intersection — question → region → positions → relations → passages — as a sweep arm | ✗ retired unbuilt | — |
| 09 | [demolition](09-demolition.md) | Name pages, gather, the name-walking loop, the residue pass, the category join (#825, absorbed) and the dead eval code are deleted, each deletion citing the slice that made it safe | ✗ retired unbuilt | — |
| 10 [#850](https://github.com/Muhanad-husn/axial/issues/850) | [category-code-deleted](10-category-code-deleted.md) | The shelved category-grouping code (modules, build branch, CLI surface) is deleted in one PR; the record, the data and the default path stay | PR open | [#851](https://github.com/Muhanad-husn/axial/pull/851) |

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

- **Filed 2026-08-28:** slices 01-06 as #826-#831. Slices 07-09 were drafted
  in `issues/` and deliberately NOT filed until slice 06's go/no-go verdict.
  **The verdict came back no-go on 2026-08-30, so they were never filed and
  are now retired.** Their drafts stay in `issues/` as the record of what the
  direction would have built.
- **Closed 2026-08-30:** the founder shelved the direction after slice 06. The
  one thing worth carrying forward is that category grouping does spread
  positions across books far better than wording similarity does — it just
  cannot be shown to keep a position to one argument, and it drops more
  passages. Any future attempt starts there, and at the passages the
  extraction model declines to place, which is where the loss is concentrated.
- **#825 folds into slice 09** (founder ruling, 2026-08-28): the category
  join's deletion rides the demolition slice; the slice-09 PR closes #825.
- **Slice 06's bar is settled** (founder ruling, 2026-08-29, #831): five
  deciding metrics D1–D5, a forced variant replicate (~$0.42) supplying the
  error bar, and the held-out `position` column built first (~$0.075, shipped
  as slice 02b). The bar is stated in full in #831; the plan file and approach
  §13 both point at it. Position count, size, single-passage share and the raw
  cross-book rate are **context lines, never the verdict** — they move by
  arithmetic when 113–207 extraction calls replace 679, and the cross-book
  null is 96% at size two. **D2's floor was measured 2026-08-29** by drawing the
  `position` column a second time under the second model ($0.1878,
  `data/logs/2026-08-29-position-draw-b/`): default build D2 **0.7597**,
  assignment-instability floor **0.0331** purity points. That draw also retired
  two things — the 0.349 threshold, which never binds and is not on D2's scale,
  and the claim that D2 is blind on three particular books, which the second
  draw contradicts. Roughly 5% of the column is refused and which passages
  varies by model.

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
