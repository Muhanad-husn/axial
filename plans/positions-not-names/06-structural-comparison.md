# Slice 06: `axial map compare` — the structural verdict and the go/no-go

- **Feature:** positions-not-names
- **Slice slug:** structural-comparison
- **Issue:** [#831](https://github.com/Muhanad-husn/axial/issues/831)
- **Branch:** feat/positions-not-names/06-structural-comparison
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

> **Bar rewritten 2026-08-29** to the one the founder approved in #831, with
> the three corrections from #838's held-out `position` build and the `placed`
> fix folded in. #831 is the full statement of the bar; this plan is the
> execution contract for it. Where they differ, #831 wins.

## Goal — the minimum testable behaviour

`axial map compare <dir-a> <dir-b>` puts two map builds side by side and
decides whether the re-formed map earned slices 07–09. Five metrics decide
(D1–D5); everything else printed is context. No judged gate, no model calls —
the smoke gate is saturated and is not trusted with this decision. This is the
feature's hard gate: slices 07–09 do not start until the founder says go.

## INVEST check

- **Independent:** reads two `positions.jsonl` / `map.json` / `reads.jsonl`
  triples already on disk, plus the `claim` and `position` vocabulary columns.
- **Valuable:** the decision the whole feature turns on gets made on evidence
  that cannot be moved by arithmetic alone.
- **Small:** one read-and-report module over artifacts with a stable shape,
  plus a seeded size-matched permutation null.
- **Testable:** deterministic tables over fixture position files.

## The deciding metrics (full statement in #831)

| id | metric | direction | default build |
|---|---|---|---|
| **D1** | book-spread ratio, size-matched: mean distinct `source_id` per position ÷ the same under a size-matched permutation of that build's own placed pool | up | 0.59 / 0.37 / 0.24 / 0.14 at sizes 2 / 3–5 / 6–10 / 11–48 |
| **D2** | held-out `position`-axis purity, size-matched — the axis is built and never grouped on (#838) | up | measured before slice 04; floor 0.349 |
| **D3** | member coherence, MiniLM `all-MiniLM-L6-v2`, band by band | floor only | 0.902 / 0.850 / 0.816 / 0.791; null 0.537 at 11–48 |
| **D4** | passages reaching no position, **distinct chunk ids in `positions.jsonl`** subtracted from selected | must not rise | 414 of 6,010 = 6.9% |
| **D5** | blind paired hand-sample, 12 positions per build, size-stratified, shuffled, judged before labels | veto | — |

**The bar:** D1 at least 2× the default in the plurality band, exceeding the
replicate gap by 2×, falling in no band. D2 above **0.349** and above the
default build's value by at least 2× the replicate gap; lift at or below 1.00
fails outright. D3 at or above the midpoint between the default's band value
and that band's null (11–48: **0.664**). D4 at or below **6.9%**. D5 at least
8 of 12 and at or above the default build.

**Reported, never deciding:** position count, size distribution,
single-passage share, the binary cross-book rate (with its null beside it —
96.2% at size 2, 100% above — or not at all), reads and units asked/reused,
cost, wall clock, consolidation folds, and both assignment-disagreement
figures. **Fewer, larger positions and a lower single-passage share are not
results**; they follow from 113–207 extraction calls replacing 679.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given the default build and the forced variant replicate for one corpus pin,
      one answers pin and one set of vocabulary scheme versions
When  `uv run axial map compare data/map/<pin> data/map/<pin>-category` runs
Then  it prints D1 book-spread ratio per size band for each build, observed
      over its own size-matched permutation null
And   it prints D2 held-out `position` purity per build over the same null,
      naming the categorised base (5,549 of 6,010 selected; 5,257 of 5,596
      placed on the default build) and the 0.349 conditional-purity floor
And   it prints D3 mean member coherence per size band per build with that
      band's null
And   it prints D4 passages reaching no position as distinct chunk ids in
      `positions.jsonl` subtracted from selected, never as a sum of position
      sizes
And   it prints the replicate gap on D1 and D2, and `units_reused` for the
      replicate build
And   it prints each build's context lines with their denominators named, and
      the cross-book rate only alongside its null
And   consolidation is reported as folds per final position, with the
      embedding merge's folds separate from the consolidation pass's own
And   the two builds appear side by side in one table naming the corpus pin,
      the answers pin, the vocabulary scheme versions and both artifact paths
And   comparing builds that disagree on any of those pins or versions refuses
      with a message naming which one differs
```

- **Boundary / endpoint:** CLI — `uv run axial map compare <dir-a> <dir-b>`
- **e2e test type:** API/integration test (pytest, CLI-level, tmp fixture dirs)
- **e2e test file (planned):** src/axial/argmap/test_compare.py

## Files (parallel-safety declaration)

```aeo-independence
slice: 06-structural-comparison
creates: src/axial/argmap/compare.py
creates: src/axial/argmap/test_compare.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: data/logs/2026-08-28-map-structural-comparison/summary.md
depends-on: 05-category-consolidation
```

## Inner loop — initial unit test list

- [ ] D1: mean distinct sources per position, per size band, over a fixture
      `positions.jsonl`.
- [ ] D1/D2/D3 null: a seeded permutation of the placed pool into positions of
      the same sizes reproduces the same figure twice from one seed.
- [ ] D2: modal-category share over **categorised** members only; a position
      whose members are all uncategorised is excluded and counted, not scored
      zero.
- [ ] D2 base reporting: categorised-of-selected and categorised-of-placed are
      both printed.
- [ ] D3: mean cosine to a position's own centroid, band by band; a member
      with no `claim` text is counted as missing, not as zero.
- [ ] **D4: passages reaching no position = selected minus distinct chunk ids
      in `positions.jsonl`.** A fixture where a chunk sits in two positions
      must not make the count negative — this is the `placed` bug at
      `build.py:1395` (slots over raw positions, 6,070 against 6,010 selected,
      printing -60).
- [ ] Context shares name their denominator: position-weighted and
      passage-weighted single-passage and cross-book figures both computed.
- [ ] Cross-book rate is never printed without its null.
- [ ] Consolidation reported as folds per final position; `consolidated_from`
      summed only when present, absent on the default build without error.
- [ ] The embedding merge's folds and the consolidation pass's folds are
      reported as two figures, not summed.
- [ ] `units_reused` is read from each manifest and printed; a replicate with
      `units_reused != 0` is flagged and its gap is not usable as an error bar.
- [ ] Comparing builds refuses on a mismatch of corpus pin, answers pin, or
      any vocabulary scheme version, naming which differs.

## Operational steps inside the slice

1. Run the comparison over the default build, the variant, and the **forced**
   variant replicate. The replicate runs in its own directory with prior-pin
   seeding off (`force=True` sets `prior_pin_dir = None`); confirm
   `units_reused == 0` before quoting any margin against the gap. Write
   `data/logs/2026-08-28-map-structural-comparison/` with `run.jsonl`,
   `console.log` and `summary.md`, in the main checkout — `data/` does not
   exist in a worktree.
2. **Blind paired hand-sample (D5).** Draw 12 positions from each build,
   stratified to the same size bands, shuffle the 24, judge "do these members
   make one argument" **before** the labels are revealed. Record the sampled
   ids, the judgments, and the unblinding, in that order.
3. Quote every margin against the **measured replicate gap**, not an assumed
   one. If the replicate gap on D1 or D2 exceeds half the variant-versus-
   default gap, the result is "not resolved at this sample" and the slice says
   so rather than passing. Quote the `claim` disagreement rate (~23%, #826) and
   the `position` two-model agreement (73.8% where assigned, n=84) next to the
   verdict, per approach §6's noise policy.
4. **Founder go/no-go on slices 07–09.** Recorded in the summary and in the
   feature README, against the numbered failure conditions in #831.

## Out of scope for this slice (deferred)

- Any judged (model-graded) comparison — needs a gate harder than the
  saturated smoke set, which is separate work.
- Any change to either build.
- Fixing the misleading `placed` log line at `build.py:1395`. `map compare`
  computes D4 correctly regardless; the log line is its own defect.
- Re-running slice 02's `map purity` against the variant's groups. It joins
  *bags* against a vocabulary column, so under the variant it reads 1.000 by
  construction and measures nothing. D2 is that arithmetic re-pointed from bags
  to positions, on a held-out axis.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Comparison run over all three builds, blind paired hand-sample done, log
      written, founder verdict recorded against #831's failure conditions.
- [ ] Evidence collected and PR opened into main (`safe-pr`).

## Status / progress log

- 2026-08-28 planned.
- 2026-08-29 bar rewritten to the approved ruling in #831; the three #838
  corrections and the `placed` fix folded in; the `map purity` re-run dropped.
