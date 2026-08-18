# 787 slice 05 — house style, measured on a countable signal

**Date:** 2026-08-18
**Branch:** `feat/787-venue-length-house-style/05-house-style-is-domain-data` (`087230f`)
**Commands:**

```
AXIAL_SECRETS_PATH="D:/axial/secrets/secrets.toml" \
  uv run python data/logs/2026-08-18-787-house-style/run_abstracts_arms.py control \
  > data/logs/2026-08-18-787-house-style/console.control.log 2>&1

AXIAL_SECRETS_PATH="D:/axial/secrets/secrets.toml" \
  uv run python data/logs/2026-08-18-787-house-style/run_abstracts_arms.py styled \
  > data/logs/2026-08-18-787-house-style/console.styled.log 2>&1
```

Run in the main checkout `D:/axial`, never a worktree.

## Why this measurement can work where slice 01's could not

Slice 01 tried to measure a defect that occurs at roughly 1 in 4. Two arms were
run, both underpowered, and both were nulls — n=3 cannot separate any hypothesis
from any other at that base rate. That arithmetic is on record in the feature
README.

Slice 04 turned up something better: **10 of 10 abstracts opened with the
identical five words, "This paper argues that."** That is a count, not a judged
band, at a **100% base rate**. A before/after on it is decisive at n=10 — ten
out of ten going to zero out of ten is not a coin landing the same way twice.

No re-draft was needed for either arm. The abstract call reads only the thesis
statement and the drafted prose, both already persisted, so both arms run over
the same 10 records in `data/papers/` — which include papers drafted from real
analyst questions, not only the dev briefs.

**The block never names the string being counted.** `house_style.yaml` states
the convention the way a style guide states one — "Open with substance. A
paragraph begins with the point it makes about the subject, not with an
announcement of what is about to be done" — so the count is a consequence, not
the instruction restated. That constraint was written into the plan before the
slice was built, precisely so this number would mean something.

## Result

| | control | styled |
|---|---|---|
| Abstracts generated | 10 of 10 | 10 of 10 |
| **Open with "This paper argues that"** | **10 of 10** | **0 of 10** |
| `-ise`/`-isation` tokens | 6 (in 5 of 10) | **34 (in 9 of 10)** |
| `-ize`/`-ization` tokens | 29 | **5** |
| Words | 196–218, mean 209 | 195–233, mean 215 |
| Cost | $0.0259 | $0.0282 |
| Wall clock | 38s | 36s |

Two independent conventions in the block moved, and both moved the way the
block asks. The spelling convention is the stronger evidence of the two: nothing
in the measurement was designed around it, it was counted afterwards, and it
reverses a 29-to-6 split into a 34-to-5 one.

**The control reproduced slice 04's finding exactly** — 10 of 10, on a different
day, against the same records. The signal is stable, which is what makes the
styled arm's 0 of 10 readable.

## It did not simply swap one formula for another

The ten styled openings, first six words each:

```
Somaliland's statehood emerged through a political-economy
Transnistria's unrecognized statehood was built through
Sectarian exclusion in Syria after 2011
Nationalism is best understood as a
War remains the structural driver of
Syria's regime survival and wartime violence
Syria's material survival after 2011 rested
After 2011, the Baathist-Assad apparatus, rather
Syrian political economy is best understood
Sovereignty in quasi-states is neither a
```

Ten different openings, every one on the paper's subject. The failure worth
looking for here was a new uniformity replacing the old one; it did not happen.

## The abstract still does its job

Slice 04's bar — states the paper's own argument, not a description of the
sources — holds in the styled arm. From `ca17d6077c1a7f5e`, the real-ask paper:

> After 2011, the Baathist-Assad apparatus, rather than mandate-era
> institutions, became the principal domestic decider of who retained power in
> Syria because it controlled the security and administrative channels through
> which survival, impunity and material exclusion were distributed. […] The
> argument is deliberately limited: it concerns domestic control over the
> institutions that preserved power, not sole responsibility for the war or
> every political outcome. External actors substantially enabled and constrained
> domestic leaders, and the account therefore **leaves open** the broader
> question of how far the Baathist state determined outcomes beyond this
> narrower institutional comparison.

Note "organised" in its second sentence, and note the closing clause: slice 04's
open-question rule is holding there too.

## What this does not measure

- **Whether house style changed the sections.** The drafter carries the same
  block, but section prose has no countable signal comparable to the opening
  formula, and re-drafting to find out costs a paid run per brief. The block
  reaching `compose_draft_prompt` is pinned by test; its effect on section prose
  is not measured here and should not be claimed.
- **Whether these are the right conventions.** The block is content an analyst
  owns and edits. This measures that the mechanism carries it, not that its nine
  entries are the correct nine.
- **Anything at all about a second domain.** There is one domain frame, `syria`.

## Files

- `run.control.jsonl` / `run.styled.jsonl` — one record per paper per arm.
- `console.control.log` / `console.styled.log` — raw output.
- `run_abstracts_arms.py` — slice 04's harness plus an arm argument and the
  opening-formula counter.

## Next steps

- Open the PR for slice 05 (`aeo:safe-pr`). It closes #787.
