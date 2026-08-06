# Fixing LLM tagging reliability with a vote, not a better prompt

*A method note on how Axial diagnosed and repaired its tag pass, July 2026.*

> **Status caveat.** Every number in this paper was measured against a *simulated*
> gold set (DEC-29): frontier AI models standing in for human academic labelers. The
> **mechanism** documented here — best-of-N majority voting on the contested tag axes
> — is real and shipped (spec §7.14, DEC-31, DEC-33). The **figures are provisional
> permanently.** Issues #250 and #295 were closed *not planned* on 2026-07-24: no
> academic input is coming, the simulated path is the permanent one, and there will be
> no teardown and no re-derivation on real labels (DEC-44). Read the numbers as "this
> is the size and shape of the effect," never as a final score, and never promote one.

---

## Part I — The plain-language version

### What Axial does, and where the problem was hiding

Axial reads academic books and articles and attaches tags to every passage: what
*field* it belongs to, what *kind of claim* it makes, which *theoretical school* it
speaks from, and so on. Those tags are the whole point. They turn a pile of PDFs into
a knowledge graph you can query.

For months the tags *looked* fine. A model would read a passage, emit a sensible tag,
and move on. Nobody had ever actually measured whether the tags were *right*, because
measuring requires an answer key — a "gold set" of passages labeled by experts — and
we didn't have one yet. The scoring tool had only ever run against placeholder labels.

The uncomfortable truth turned out to be this: a confident model on a genuinely
ambiguous question gives you one reasonable-looking answer and hides the fact that it
could just as easily have given you a different one. The pipeline asked once, got one
answer, wrote it down, and the doubt never showed up anywhere.

### Step 1 — Build an answer key when your experts are unavailable

We needed a gold set, and the academics who would normally build it were unavailable —
at the time we thought temporarily; they never became available, so this stand-in is
now permanent. We took two different frontier AI models on two
different platforms (GLM 5.2 and GPT-5.6), gave them the same neutral "expert coder"
instructions, and had each one label the same 120 passages independently. Two
independent labelers means we can measure **agreement**: how often do they pick the
same tag? If two careful readers can't agree, the tag itself is in trouble.

The first result was alarming. On the two hardest axes — kind-of-claim and
theory-school — the two models agreed only **49% of the time**. Our internal bar for
keeping a tag axis at all is 60% agreement. Both were underwater.

The obvious reactions were all wrong, and we caught ourselves before acting on them:

- **"The models are just bad, use a smarter one."** We checked. Our cheap production
  tagger agreed with GLM *more* than the two expensive frontier models agreed with
  each other. Upgrading the model was not the lever.
- **"The tag definitions are vague, rewrite them."** Reasonable guess. We'll come back
  to it — it was measured, and it did nothing.

### Step 2 — Switch to an in-house labeler so we could run real experiments

Here's the pivotal, unglamorous decision. Labeling by hand-driving two commercial chat
websites is slow, unrepeatable, and expensive. You can't run the same experiment ten
times. You can't hold one thing fixed and vary another. Science needs controls, and
external chat models don't give you cheap controls.

So we moved the labeling *inside* Axial's own harness and ran it with dispatched
Sonnet 5 agents. Same task, but now programmable, repeatable, and cheap enough to run
many times. That single change is what unlocked the actual diagnosis, because it let us
run four carefully controlled conditions and repeat them.

Three things fell out immediately:

1. **Half of any "improvement" from switching labelers was fake.** When we asked *one*
   model family to label the same passages twice, agreement jumped from 49% to about
   73% — with no change to anything else. Asking the same kind of model twice
   flatters the number, because two instances of Sonnet think more alike than Sonnet
   and GPT do. Lesson: only ever compare agreement *within one model family*. If we
   hadn't controlled for this, we'd have announced a fake victory.

2. **The ceiling was the model arguing with itself.** We gave the *same* coder the
   *exact same passage and instructions* twice. On theory-school it reproduced its own
   earlier answer only **73% of the time**. Read that again: not two different
   labelers — the *same* labeler, disagreeing with itself on a re-read one time in
   four. Two labelers can never agree more than one labeler agrees with itself, so 73%
   wasn't a floor we could push through by trying harder. It was a ceiling.

3. **Every attempt to raise that ceiling by talking to the model failed.** We rewrote
   the tag definitions from circular to genuinely discriminating (cost: 55% more tokens
   on every call) — no improvement. We added an explicit rule about what unit of text
   to judge — nothing. We fed the model a summary of the book the passage came from —
   *negative*, it got slightly worse. Three sensible prompt fixes, three duds.

### Step 3 — The insight: it's a sampling problem, not a knowledge problem

If the model disagrees with itself on a re-read, then each answer is really a **draw**
from a little cloud of defensible answers. The passage genuinely has a most-likely
correct tag, but any single reading might land next to it instead of on it.

We checked, and this is exactly what was happening: for **97% of passages a clear
favorite answer exists**; a single reading hits that favorite about 88% of the time.
The other 12% of the time it lands on a neighbor. Two independent readings therefore
agree about 0.88 × 0.88 ≈ 77% of the time, which is almost exactly the agreement we
kept measuring. The math closed.

So the fix isn't to make the model smarter. It's to stop trusting a single roll of the
dice.

### Step 4 — Best-of-N: draw three times and take the majority

Instead of tagging each passage once, tag it **three times** and keep the answer that
wins two out of three votes. This is the whole trick.

The result:

| Axis | Tag it once | Best-of-3 vote |
|---|---|---|
| theory-school | 0.757 | **0.918** |
| kind-of-claim | 0.796 | **0.866** |

The stuck axis jumped 16 points, and — this is the important part — **0.918 is past
the 0.73 ceiling of a single reading.** That's not a contradiction. Voting doesn't make
the coder smarter; it recovers the favorite answer that each single reading was
scattering around. We predicted about 0.92 from the sampling math before we ran it, and
measured 0.918.

**What does voting cost?** Sometimes all three readings disagree, and there's no
majority. That happens on about **8.8%** of passages for theory-school. But instead of
treating that as a failure, we treat it as a **feature**: when three careful readings
can't agree, the honest output is "this passage is genuinely contested," not a
coin-flipped tag pretending to be certain. We flag it and move on. (Wanting fewer
flags? Vote five times instead of three; the undecided rate drops to about 1%.)

There's a bonus. Occasionally a single reading produces an outright invalid tag. The
vote quietly outvotes it. Invalid-tag rate went from 0.56% on a single draw to **0% at
best-of-3**. The vote self-repairs.

### Why this is worth writing down

The instinct when an LLM gives shaky output is always to *talk to it better* — rewrite
the prompt, add context, upgrade the model. We tried all three and measured all three
at roughly zero. The one thing that worked was the thing nobody reaches for first:
**accept that the model is sampling, and sample it deliberately.** Three cheap calls
and a majority vote beat a 55%-bigger prompt, beat added context, and beat a more
expensive model — combined.

The second idea worth keeping is **abstention as a first-class output.** A tagger that
says "I genuinely can't decide" on the 9% of passages that are actually contested is
more trustworthy than one that always answers. We route that uncertainty into a flag a
human can review, rather than burying it in a confident-looking tag. That is the
project's calibrated-confidence principle applied at the smallest unit of work.

---

## Part II — The technical version

### 2.1 Setup

**Corpus and sample.** A 120-chunk gold sample drawn by `axial gold sample` across the
ingested corpus, stratified by field × scope × role. Each chunk carries the production
tagger's own output (stored in `data/gold/chunks/*.json`), which later let us check
labelers against the pipeline's guess.

**Axes.** Seven tag axes. Two are *blind* (the labeler assigns from scratch):
`claim_type` and `theory_school`. The rest are *pre-labeled* (the sheet ships the
pipeline's guess and the labeler corrects it): `field`, `empirical_scope`,
`polities_touched`, plus `role_in_argument`.

**Agreement metric.** Per-axis exact-match agreement between two independent label
sets over the shared rows. The tag-survival bar (spec §10) is ≥ 0.60 inter-annotator
agreement for a blind axis to be kept.

### 2.2 Phase 1 — external cross-family baseline (GLM 5.2 vs GPT-5.6)

Two frontier models on two platforms, persona-neutral shared coder prompt
(`docs/sim-academic/prompts/gold-coder.md`), codebook v1 (placeholder definitions).

| Axis | GLM vs GPT | Kind |
|---|---|---|
| `claim_type` | **0.49** | blind |
| `theory_school` | **0.49** | blind |

Both blind axes below the 0.60 bar. Two corrections to the naive reading, both found
by checking labels against the stored production output:

1. **Pre-labeled agreement figures were not annotator agreement.** GLM rubber-stamped
   the pipeline's pre-fill (`field` 0.99, `empirical_scope` 1.00, `polities_touched`
   1.00) rather than labeling. Any labeling run must verify each labeler's *correction
   rate* against the pre-fill before trusting its agreement number.

2. **"The tagger never marks absence" was an artifact.** `not-applicable` entered the
   schema (`02c29b6`) after 112 of the 120 gold chunks were already tagged, so the
   tagger literally could not emit it. Where available it used it sensibly.

**Model tier exonerated.** Restricting to chunks where both labelers named a real
school (removing the absence-marker asymmetry):

| | PROD (`deepseek-v4-flash`) vs GLM | PROD vs GPT | GLM vs GPT |
|---|---|---|---|
| `theory_school` | 0.38 | 0.30 | 0.56 |
| `claim_type` | **0.56** | 0.35 | **0.49** |

On `claim_type` the cheap production tagger agrees with GLM *more* than the two frontier
models agree with each other. The ceiling is a property of the axis, not the model tier.

### 2.3 The pivotal move — labeling in-harness

The external chat-model roster made controlled experiments unaffordable and
unrepeatable. Labeling was moved in-harness to dispatched **Sonnet 5** subagents
(DEC-30), which made controlled arms cheap. Four conditions, codebook v2 held constant
so each comparison isolates one variable; 10 labeler runs total; raw labels under
`data/sim/gold/sonnet/`.

| Arm | codebook v2 | unit rule | source context | isolates |
|---|---|---|---|---|
| NOUNIT | ✓ | — | — | replicates the GLM/GPT framing → same-family inflation |
| BASE | ✓ | ✓ | — | vs NOUNIT: the unit-of-analysis rule |
| BASE-R | ✓ | ✓ | — | identical re-run of BASE → intra-annotator ceiling |
| CTX | ✓ | ✓ | ✓ | vs BASE: source `title`/`thesis`/`stated_argument` |

**Operational note.** A 60-row labeling job sits near the 64k output-token cap; 3 of 10
runs died there. Instruct labelers to read inputs once, never echo source text, emit no
per-row commentary, and write once. If a batch fails twice, split to ~30 rows.

### 2.4 Finding 1 — same-family inflation

NOUNIT gets the *exact* framing GLM and GPT received; only the model family differs.

| | GLM vs GPT (cross-family) | NOUNIT (same-family) | inflation |
|---|---|---|---|
| `claim_type` | 0.49 | 0.75 | **+0.26** |
| `theory_school` | 0.49 | 0.72 | **+0.23** |

Roughly half the apparent jump from switching labelers is the artifact of asking one
model family twice. Any labeling comparison must hold the model family fixed;
cross-family and same-family agreement numbers are not comparable (same-family runs
~+0.25 higher on identical instructions with no design change).

### 2.5 Finding 2 — the intra-annotator ceiling

Same coder, identical prompt, same 60 chunks, run twice (BASE vs BASE-R):

| axis | SELF (test–retest ceiling) | INTER observed | headroom |
|---|---|---|---|
| `field` | 0.95 | 0.98 | none |
| `empirical_scope` | 0.90 | 0.87 | none |
| `claim_type` | 0.78 | 0.77 | none |
| `theory_school` | **0.73** | **0.73** | **zero** |

Inter-annotator agreement cannot exceed intra-annotator reliability, and it has already
reached it. A coder reproduces its own `theory_school` label only 73% of the time.
Invisible in production because the pipeline draws once.

### 2.6 Finding 3 — every prompt-side intervention was null

| intervention | cost | `theory_school` | `claim_type` |
|---|---|---|---|
| codebook v2 (circular → discriminating definitions) | +55% tokens/tag call | ~0 | ~0 |
| unit-of-analysis rule | one sentence | +0.02 | +0.12 (batch1 only) |
| source context (`title`/`thesis`/`stated_argument`) | code change to `compose_multi_axis_tag_prompt` | **−0.01** | +0.03 |

Source context measured +0.12 on batch2 alone but +0.03 across all 120 — the batch-level
gain was noise. `claim_type`'s batch-to-batch variance (0.20) exceeds every effect
measured. **Consequence:** source context is *not* wired into the tag prompt (rejected
on measurement). Codebook v2 was *trimmed* to v3 (rendered per-call block 15,960 → 24,853
→ **19,793** chars, i.e. +24% over v1 rather than +55%) — kept for readability, explicitly
not for a measured agreement gain. Tag ids unchanged across all seven axes.

### 2.7 Finding 4 — the variance is recoverable by sampling

Three independent draws of the same task, n=60:

| axis | unanimous 3/3 | majority 2/3 | no majority |
|---|---|---|---|
| `claim_type` | 0.75 | 0.23 | 0.02 |
| `theory_school` | 0.67 | 0.30 | 0.03 |

For 97% of chunks a clear modal label exists; a single draw simply samples around it.
Arithmetic check: single draw hits the mode ~0.88, so two draws agree ≈ 0.88² ≈ 0.77,
matching the 0.72–0.77 measured. The axis is not intrinsically unreliable — the pipeline
samples it once.

### 2.8 Finding 5 — best-of-N breaks the single-draw ceiling

Six independent draws on the same 60 chunks (Panel A: `base-L1`, `baseR-L1`, `base-L2`;
Panel B: `panelB-D1..D3`). N=1 is the mean over all 15 draw pairs; N=3 enumerates all 10
disjoint 3/3 splits, majority-votes each half, and compares half against half.
Deterministic, no sampling.

| axis | N=1 | N=3 | gain |
|---|---|---|---|
| **`theory_school`** | 0.757 | **0.918** | **+0.162** |
| **`claim_type`** | 0.796 | **0.866** | +0.070 |
| `polities_touched` | 0.897 | 0.946 | +0.049 |
| `empirical_scope` | 0.893 | 0.939 | +0.045 |
| `field` | 0.968 | 0.980 | +0.012 |

0.918 is past the 0.73 single-draw ceiling. Voting recovers the modal answer a single
draw was sampling around (predicted ~0.92 from a 0.88 hit rate; measured 0.918). The
largest gain lands on the axis that was stuck.

**Abstention is the cost** (all N draws differ → no plurality):

| axis | N=3 | N=5 |
|---|---|---|
| `theory_school` | **8.8%** | 1.1% |
| `claim_type` | 3.3% | 0.0% |
| `empirical_scope` | 1.2% | 0.0% |

0.918 is measured on the ~91% that decide. Undecided chunks are *not* short (median 1145
ch vs 1307 decided), so this is genuine contestedness, not thin input.

**Self-repair.** `theory_school` out-of-vocab rate 0.0056 (single) → 0.0000 (N=3);
invalid draws are outvoted.

**Cost comparison across everything tried:**

| | cost | `theory_school` gain |
|---|---|---|
| codebook rewrite (kept, trimmed) | +24% tokens | 0 |
| source context (rejected) | a code change | −0.01 |
| **best-of-3** | **3× calls, cheap tier** | **+0.162** |

Best-of-3 is the only spend in the entire investigation that bought anything.

### 2.9 What shipped

**Spec §7.14 — best-of-N voting on the blind axes.** The tag pass draws its per-chunk
call `N` times and majority-votes `claim_type` and `theory_school`. `N` is per-pass
config (`config/pipeline.yaml`, `llm.votes_by_pass`), default 3 for the tag pass and 1
elsewhere; **`N = 1` is an exact no-op** (today's record shape unchanged). Head axes
(`field`, `empirical_scope`, `role_in_argument`, `polities_touched`) take the first
draw's value — the gains there are small and nothing has asked for it.

**DEC-33 — abstention is a per-axis flag, never a vocabulary value.** When an axis's `N`
draws hold no strict plurality, that axis records:

```yaml
theory_school: { primary: null, abstained: true, draws: [<distinct primaries, draw order>], status: candidate }
```

Kept structurally outside the value space because the three vocabulary assertions each
say something about the *passage* (`<school>` = this school applies; `not-applicable` =
the passage advances no theoretical position; `unlisted` = a real school this vocabulary
misses), whereas abstention asserts something about the *draw distribution* (the draws
disagree). A consumer checks `abstained` before reading `primary`. The flag is per axis,
not per record: a chunk routinely decides one blind axis while abstaining the other. A
decided axis is byte-identical to the single-draw shape and inherits `secondary` /
`subtags` from a draw that voted for the winner.

**Interaction with the bounded re-ask (§7.1 / P0-6).** Each draw runs the full parse →
validate → single bounded re-ask path independently. A `theory_school` draw that
soft-lands to `unlisted` casts a legal ballot. A draw still out of vocabulary after its
own re-ask is a spoiled ballot the vote ignores; the P0-6 hard error stands only when
*every* draw is invalid, preserving the schema-gap guarantee at the chunk level.

### 2.10 Limitations and what is still owed

- The ceiling rests on **one replicate at n=60**. Six independent measurements
  converged on 0.67–0.76, but a second replicate should land before it is treated as
  settled.
- One replicate (`baseR-L1`) leaked a `claim_type` tag (`power-typology`) into
  `theory_school` on 2 rows — a cross-axis leak worth watching. Excluding those rows
  moves the ceiling 0.73 → 0.76 against an observed 0.73; the conclusion is unchanged.
- `claim_type`'s batch-to-batch variance (0.20) exceeds every intervention effect
  measured; that axis needs a larger sample before any claim about it is trusted.
- **All figures are on the simulated gold set** (DEC-29/DEC-32) and are a provisional
  development signal. Best-of-N changes how every source is tagged in production (3×
  calls, new record shape on two axes) and has **not** been validated on the real
  corpus. That is the stage-4 frozen re-tag. The 0.918 / 0.866 figures do **not** get
  re-derived on real labels: there are none coming (#250/#295 closed not planned,
  DEC-44), so they stay provisional permanently.

### 2.11 Reusable lessons

1. **Measure test–retest before you trust agreement.** An inter-annotator number is
   uninterpretable without the intra-annotator ceiling beside it. Agreement cannot
   exceed self-consistency.
2. **Compare only within one model family.** Same-family agreement runs ~+0.25 over
   cross-family on identical instructions with zero design change. Mixing families
   manufactures fake wins and fake losses.
3. **Verify the labeler actually labeled.** Check each labeler's correction rate against
   any pre-fill; a rubber-stamp at 0.99/1.00/1.00 silently voids the whole comparison.
4. **For an underdetermined generative task, sample — don't over-prompt.** When a model
   disagrees with itself on a re-read, each answer is a draw. Majority voting recovers
   the mode more cheaply and more reliably than prompt engineering or a model upgrade.
5. **Make abstention a real output.** Flagging the genuinely contested minority is more
   honest than a confident coin-flip, and it keeps a human in the loop exactly where
   the machine has no defensible answer.

---

### References (internal)

- `docs/DECISIONS.md` — DEC-29 (simulated academic path), DEC-30 (in-harness Sonnet
  labeling + ceiling), DEC-31 (best-of-N measured), DEC-32 (Phase A completion plan),
  DEC-33 (abstention record shape).
- `docs/sim-academic/README.md` — full method, all raw tables, run tracker.
- `specs/PRODUCT.md` — the sections that specified best-of-N, the bounded re-ask and
  the tag survival bar were retired with the tag pass on 2026-08-06; see git history
  and `docs/DECISIONS.md`. Appendix E survives as prompt examples. What outlives the
  pass is §2.11's lesson 4, still applied in `src/axial/merge_names.py`.
- Issues: #294 (best-of-N implementation), #302 (abstention record, DEC-33). #250 and
  #295 (the academic backlog and the sim-path teardown) were closed **not planned** on
  2026-07-24 — see DEC-44.
