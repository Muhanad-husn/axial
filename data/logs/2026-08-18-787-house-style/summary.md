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

**The block never names the opening formula.** `house_style.yaml` states the
convention the way a style guide states one — "Open with substance. A paragraph
begins with the point it makes about the subject, not with an announcement of
what is about to be done" — so the count is a consequence, not the instruction
restated. That constraint was written into the plan before the slice was built,
precisely so this number would mean something.

That is true of the opening formula and of nothing else counted here. The
spelling count below is the opposite case, and is read as the opposite kind of
evidence.

## Result

| | control | styled |
|---|---|---|
| Abstracts generated | 10 of 10 | 10 of 10 |
| **Open with "This paper argues that"** | **10 of 10** | **0 of 10** |
| **Formula anywhere in the abstract** | **10 of 10** | **2 of 10** |
| `-ise`/`-isation` tokens | 6 (in 5 of 10) | **34 (in 9 of 10)** |
| `-ize`/`-ization` tokens | 29 | **5** |
| Words | 196–218, mean 209 | 195–233, mean 215 |
| Cost | $0.0259 | $0.0282 |
| Wall clock | 38s | 36s |

**The opening claim is exact, and it is narrower than "the formula is gone."**
No styled abstract opens with the formula. Two of the ten still contain it
later in the paragraph — displaced rather than removed. The move is large
either way, 10 of 10 to 2 of 10 on presence, but the honest headline is about
where the sentence starts, not about whether the phrase survives.

**The spelling count is not evidence that style changed how the prose reads.**
Convention 8 names the token: "Spelling and punctuation follow British
convention (-ise, organisation, judgement)". Counting `-ise` after the fact does
not undo the block naming the string — it measures instruction-following on a
literal the instruction supplies. What it does prove, and proves more cleanly
than anything else here, is **arrival**: the block's text physically reached the
model and was acted on. Take it as the arrival check and nothing more.

**The opening-formula count is therefore the sole evidence of a style effect
the block did not dictate word for word.** One count, one convention, n=10.

**One styled abstract kept American spelling entirely.** `408378f2e286fff2`
came back at 0 `-ise` against 5 `-ize` while the other nine switched. One of
the nine conventions did not land in 1 of 10 runs, and nothing in the system
catches that — there is no checker, by design. A blinded verifier, told nothing
about which arm was which, independently picked out that same abstract as the
one missing the spelling tell.

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

Ten different openings, every one on the paper's subject. Across papers, the
failure worth looking for — a new uniformity replacing the old one — did not
happen.

**Within one paper it did.** A blinded reader found it in the styled
`data/papers/a1039fad4da31320.md`: the abstract, the introduction and the first
section all open on the same frame applied to the same subject, and the
abstract and the first section share nine consecutive words. The old formula
was replaced by a new one — each prompt applies the convention blind to its
neighbours, so a good instruction became a tic. The unstyled openings at least
varied. Convention 2 has been amended to name that failure. **The two-arm
measurement above predates the amendment**; a separate confirmation run of the
styled arm alone was made afterwards, and is reported below rather than folded
into the table.

## Confirmation run, after convention 2 was amended

The amendment adds, to "open with substance": *"A stock frame applied to the
subject is still a formula: open on the particular thing being said here, not on
a shape that would fit any paragraph about this topic. Where consecutive
passages share a subject, they must not share an opening shape."*

It would otherwise ship without ever having been run. One styled arm, $0.0280,
10 of 10 generated. **This is a confirmation run, not the measurement** — the
table above is the measurement, and it was taken before anyone had read the
output.

| | pre-amendment | amended |
|---|---|---|
| **Opens with the formula** | **0 of 10** | **0 of 10** |
| Formula anywhere in the abstract | 2 of 10 | **4 of 10** |
| `-ise`/`-isation` tokens | 34 | 41 |
| `-ize`/`-ization` tokens | 5 | **1** |

**Mixed, and reported as mixed.**

- **The headline claim holds.** No abstract opens with the formula, in either
  version of the block.
- **The spelling hold-out closed.** `408378f2e286fff2` — the one abstract that
  kept American spelling entirely, which a blinded verifier picked out without
  being told — comes back with "unrecognised" this time, and `-ize` across the
  set drops from 5 tokens to 1. The amendment did not touch convention 8, so
  this is a different draw of the same instruction rather than a fix: read it as
  evidence that the 1-in-10 miss was variance, not that it is now solved.
- **The formula surviving deeper in the paragraph got worse, 2 of 10 to 4 of
  10.** The amendment targets the *shape* an opening takes, not the phrase, so
  the phrase migrating further down is a coherent thing to have happened. But it
  moved the wrong way and it should not be explained away: on 10 samples of a
  stochastic model, a 2-versus-4 difference is not a powered comparison, and
  nothing here separates "the amendment pushed it deeper" from "this is what a
  second draw looks like."

Whether the amendment is worth keeping on that evidence is the founder's call.
It is one line of domain data, editable by whoever owns the domain, and it is
not load-bearing for anything in `src/`.

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
- **Whether the conventions are worth their cost.** They cost something. Losing
  "This paper argues that" also loses the frame that marks a thesis as
  contested: the unstyled "This paper argues that sectarian exclusion… was
  produced through a struggle over political order" becomes the styled
  "Sectarian exclusion in Syria after 2011 functioned primarily as an
  instrument of political order" — a contested claim rendered as a flat
  assertion. That is a trade, not a defect, and it is the founder's to price.

**A blinded verifier called 10 of 10 pairs correctly**, 8 at high confidence, on
which member of each pair was written under the conventions. That is the
strongest evidence in this slice that the block reaches the writer. It is also
mechanical rather than judged: two regexes — the opening formula and `-ise`
against `-ize` — score 9 of the same 10 on their own. Read it as arrival
confirmed by a second, independent method, not as a reader preferring the
styled prose.

## Files

- `run.control.jsonl` / `run.styled.jsonl` — one record per paper per arm.
- `console.control.log` / `console.styled.log` — raw output.
- `run_abstracts_arms.py` — slice 04's harness plus an arm argument and the
  opening-formula counter.

## Next steps

- Open the PR for slice 05 (`aeo:safe-pr`). It closes #787.
