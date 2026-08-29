# D2's assignment-instability floor — the `position` column drawn a second time

Founder ruling, 2026-08-29 (#831): recompute D2 over the second model's draw, so
the `position` assignment's two-model agreement — a **rate** — becomes a floor in
D2's own units, **purity points**.

## Commands, verbatim

Routing: `config/pipeline.yaml`'s `llm.model_by_pass.vocabulary_build` was moved
from `production_vocabulary_examine` (deepseek-v4-flash, draw A) to
`production_vocabulary_examine_check` (gpt-5.6-luna) for the run and **reverted
immediately after**. The pre-edit file is `pipeline.yaml.orig` in this directory;
`git diff config/pipeline.yaml` is clean as of the end of this run. There is no
per-run model flag on `vocabulary build` — that is the only seam.

    AXIAL_SECRETS_PATH=secrets/secrets.toml uv run axial vocabulary build \
        --columns position --vocabulary-dir data/vocabulary-draw-b

Ran detached in `D:/axial` (main checkout). `AXIAL_SECRETS_PATH` was overridden
because the ambient value points at the container path `/secrets/secrets.toml`.
Draw A's artifact under `data/vocabulary/position/` was not touched; draw B
landed in `data/vocabulary-draw-b/position/`.

The analysis is `d2.py` in this directory; its output is `d2-output.txt`. Offline,
seeded (seed 831, 20 permutation trials), zero model calls.

## What it cost

**$0.1878, 62 calls, gpt-5.6-luna.** Under three minutes wall clock at the
default 12 workers, ~9.5 s a call.

That is **2.5x the ~$0.075 quoted when the ruling was made.** The estimate was
taken from the claim column's measured rate on deepseek-v4-flash; luna is the
dearer model and the estimate should have been scaled for it before the number
was put in front of the founder. The work is done and the figure stands as
measured.

## Draw B, the column

| | draw A (deepseek-v4-flash) | draw B (gpt-5.6-luna) |
|---|---|---|
| answered values | 6,176 | 6,176 |
| assigned to a category | 5,797 (93.9%) | 5,871 (95.1%) |
| refused ("none") | 379 | 305 |
| excluded (abstention/`[]`/empty) | 666 | 666 |
| out-of-scheme | 0 | 0 |
| scheme | `2026-08-29-position-v1`, 9 categories | same |
| answers pin | `98e10d46cf610c6a` | same |

Both draws file the same corpus against the same committed scheme. Draw B
assigns slightly more.

## D2, measured on the default build

Held-out `position`-axis purity of the default build's 1,937 positions, scored
over positions with 2+ categorised members, against a size-matched permutation
null (20 seeded trials; the null moved 0.016–0.017 across trials).

| | draw A | draw B |
|---|---|---|
| categorised placed chunks | 5,257 of 5,596 (93.9%) | 5,319 of 5,596 (95.1%) |
| positions scored | 1,121 | 1,125 |
| member slots scored | 4,914 | 4,992 |
| **member-weighted purity** | **0.7597** | **0.7266** |
| null | 0.4019 | 0.3987 |
| **lift** | **1.890** | **1.823** |
| per-position mean purity | 0.7804 | 0.7510 |
| per-position null / lift | 0.4648 / 1.679 | 0.4600 / 1.633 |

**D2's assignment-instability floor:**

| reading | floor |
|---|---|
| member-weighted purity, \|D2(A) − D2(B)\| | **0.0331** |
| per-position mean, \|D2(A) − D2(B)\| | 0.0294 |
| lift, \|lift(A) − lift(B)\| | 0.068 |
| null spread within one draw (20 trials) | 0.0159 (A), 0.0170 (B) |

So a variant-versus-default D2 gap **at or under about 3.3 purity points is not
readable**, and the floor is about twice the permutation null's own trial
spread — it is the assignment, not the null estimate, that dominates.

Full-column label agreement between the two draws: **73.0%** where both assigned
(5,581 chunks), 66.9% over the 6,087 either assigned. The n=84 sample figure in
#838 was 73.8%; the full population confirms it.

## Two findings the founder should see before the bar is used

### 1. The 0.349 clause is not on D2's scale, and never binds

#831's bar reads "D2 above **0.349**, and above the default build's value". Now
that the default build's value is measured, **0.7597**, the 0.349 clause is
slack by 41 purity points and can never be the binding condition.

It is also not the same quantity. 0.349 (#838, correction 2) is the weighted
conditional purity of `position` **within a `claim` category** — nine groups of
several hundred passages each. D2 is purity **within a position** — 1,121 groups
of median size 2. Purity falls with group size mechanically, which is exactly
why D2 is size-matched against its own null. Comparing a position-level purity
against a category-level number compares two different scales.

The guard correction 2 was reaching for is real: grouping on `claim` inflates
`position` purity because the axes correlate at lift 1.78. **The size-matched
null already carries that guard**, and it carries it at the variant's own
position sizes. Recommendation: keep 0.349 in the issue as the reason the
correlation matters, drop it as a threshold, and let D2 be decided by
(a) exceeding the default build's 0.7597, (b) by more than the 0.0331 floor and
2x the replicate gap, with (c) lift above 1.00 as the outright-fail line.
**Founder's call — the bar is yours and I have not changed it.**

### 2. Correction 2's blind spot is model-specific, not corpus-structural

Correction 2 read draw A's refusals as structural: `vignal-2021` 39.8%,
`batatu-1999` 38.0%, `tilly-1978` 34.1%, explained by two categories excluding
single-country material in a geographically concentrated corpus.

Draw B refuses on **none of them**:

| source | draw A refused | draw B refused |
|---|---|---|
| `vignal-2021` | 39.8% | 2.3% |
| `batatu-1999` | 38.0% | 8.6% |
| `tilly-1978` | 34.1% | 4.3% |

And draw B's own worst three are different books entirely — `chouliaraki-2024`
71.4% (draw A: 5.2%), `gellner-1981` 19.8%, `kao-2025` 11.9%. **The overlap
between the two worst-three sets is empty.**

A structural property of the corpus would show in both draws. This does not.
The refusal concentration is a property of the model, so "D2 is systematically
blinder on those books" is not established — and the per-source coverage line
the bar asks for should be read per draw, never as a fixed corpus fact.

What survives: the *rate* of refusal is similar (6.1% vs 4.9%), it is
concentrated in both draws, and which books it lands on is not stable. Neither
draw is the true one.

## Artifacts

- `data/vocabulary-draw-b/position/{assignments.jsonl,manifest.json}` — draw B.
- `data/vocabulary/position/` — draw A, untouched.
- `console.log` — the build's own output, verbatim.
- `d2.py`, `d2-output.txt` — the analysis and its output.
- `pipeline.yaml.orig` — the config as it stood before the routing edit.

## Next

- Founder decides on finding 1 (the 0.349 clause) and finding 2 (correction 2's
  blind-spot claim). Both change wording in #831, neither changes a number
  already measured.
- The floor **0.0331 purity points** is now available to slice 06 and does not
  need re-measuring.
