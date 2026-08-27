# Derived-vocabulary categorisation, all twelve columns

**Run:** 2026-08-27, issue #805 slice 01, branch
`feat/derived-vocabulary/01-the-sentence-columns-are-counted` at `c49d839`.
**Command**, once per column, twelve processes in parallel from the worktree
`D:/wt-805` against the main checkout's answer store:

```
AXIAL_SECRETS_PATH=D:/axial/secrets/secrets.toml \
  uv run axial vocabulary examine --columns <column> \
  --answers-dir D:/axial/data/answers
```

**Cost:** $0.1054 over 75 model calls. **Wall clock:** ~20 minutes in parallel;
the same work serially is about three hours, because each 100-value assignment
call spends 170–250s producing ~10k completion tokens.

**Models.** `deepseek/deepseek-v4-flash` proposes the scheme and assigns the
held-out sample; `openai/gpt-5.6-luna` re-assigns a 100-value subsample against
the same scheme. The two tiers must resolve to different models —
`axial.vocabulary.SelfConsistencyError` refuses the run otherwise.

**Method.** Per column: 400 values drawn at random propose a category scheme;
400 further values, disjoint from the first 400, are assigned against it. Every
rate below is measured on values the proposing model never saw.

## Per column

| column | categories | 5+ members | of those, cross-book | assigned (unseen) | largest | agreement where assigned | bar |
|---|---|---|---|---|---|---|---|
| move | 16 | 16 | 16 | 97.5% | 18.0% | 67.0% (n=97) | **passes** |
| about | 12 | 12 | 12 | 94.0% | 15.0% | 79.5% (n=88) | **passes** |
| evidence | 10 | 10 | 10 | 87.5% | 19.5% | 80.5% (n=87) | **passes** |
| claim | 10 | 10 | 10 | 75.0% | 11.8% | 81.8% (n=77) | **passes** |
| arguing_against | 10 | 10 | 10 | 71.8% | 8.8% | 61.0% (n=77) | **passes** |
| mechanism | 36 | 16 | 16 | 50.7% | 4.5% | 66.0% (n=53) | **passes** |
| assumes | 10 | 10 | 10 | 99.8% | 26.2% | 67.0% (n=100) | fails c2 |
| ranges_over | 11 | 11 | 11 | 95.2% | 25.5% | 85.3% (n=95) | fails c2 |
| concedes | 10 | 9 | 9 | 96.0% | 31.5% | 66.7% (n=93) | fails c2 |
| stops_holding | 7 | 7 | 7 | 96.0% | 33.2% | 73.7% (n=95) | fails c1, c2 |
| comparison | 8 | 7 | 7 | 98.8% | 52.5% | 59.0% (n=100) | fails c1, c2, c5 |
| position | 5 | 5 | 5 | 98.5% | 56.8% | 87.8% (n=98) | fails c1, c2 |

The bar (plan §"The bar for slice 02 to proceed"): c1 at least 8 categories
with 5+ members; c2 largest category under 25% of the assigned sample; c3 at
least half of the 5+ categories spanning 2+ sources; c4 at least half the
held-out sample assigned; c5 the second model agreeing on at least 60% where
the first model assigned. **Six of twelve clear all five. The bar asked for
one.**

## What the run says

**Every category that reaches five members crosses books. Twelve columns of
twelve, no exceptions — c3 was never in doubt anywhere.** That is the property
the feature exists for, and it holds even in the six columns that fail on other
grounds. Compare the recorded finding that only 40.5% of argument-map edges
reach another book.

**Every failure is c2, the blob condition. Nothing failed for lack of
structure.** `assumes` (26.2%) and `ranges_over` (25.5%) miss by roughly a point,
`position` (56.8%) and `comparison` (52.5%) badly. A scheme that came out too
coarse is a re-prompting problem, not evidence the column has no vocabulary —
and the residue probe below shows a second round is cheap.

**Coarseness and coverage trade off directly, and the model chooses where to
sit run to run.** `mechanism` named 36 categories here and assigned 50.7%; the
same prompt and the same model named 14 on 2026-08-27 and assigned 70.8%, and
a re-run of that 14-category scheme on the identical held-out 400 assigned
78.2%. So a single run's assignment rate carries roughly 7 points of noise, and
the scheme's granularity is not stable at all. **This is the open question
slice 02 inherits**: the number of categories has to be pinned, whether by
asking for a target count, by proposing from several samples and merging, or by
a second round over the residue.

**`claim` is the direct comparison against what is already built.** Argmap bags
by wording and names each bag: 1,937 positions, median size 2, 35.3% reaching a
second book. Read cold, the same column gives 10 categories, all ten crossing
books, placing 75% of unseen values, with the second model agreeing 81.8%.

## Residue probe (in `../2026-08-27-vocabulary-census/`)

Re-running the 14-category `mechanism` scheme left 87 of 400 unplaced. Asked
what those 87 are, the model named 5 further real categories covering 36 of
them (41.4%) and judged 51 genuinely one-off. A two-round scheme would reach
**87.2%** on that column. So the 29.2% that fit nothing in the first probe is
roughly four parts scheme-too-coarse to six parts genuine one-off.

## Caveats

- 400 + 400 per column against populations of 2,718 to 20,334. These are
  estimates with a sampling error, not census figures.
- The proposing model also does the bulk assignment; the second model checks
  only a 100-value subsample. `agreement where assigned` is the honest number —
  the overall agreement rate includes cases where both models placed nothing.
- One deadline-exceeded retry occurred in the residue probe (600s), recovered
  on attempt 2. No column run hit one.
- Nothing was persisted. The command writes no pipeline artifact; these
  category schemes exist only in this log directory.
