# Fixing LLM labeling reliability with a vote, not a better prompt

*A method note on diagnosing and repairing an unreliable LLM tagging pass.*

> **A note on the numbers.** The agreement figures below were measured against a
> *stand-in* answer key: strong AI models labeling passages in place of the human
> experts we were waiting on. Treat the numbers as the size and shape of the effect,
> not as final scores. The **method** — best-of-N majority voting on the contested
> label axes — is what generalizes, and it is what we now run in production.

---

## Part I — The plain-language version

### The problem was hiding in plain sight

Our system reads academic books and articles and attaches labels to every passage:
what *field* it belongs to, what *kind of claim* it makes, which *theoretical school*
it argues from, and so on. Those labels are the whole point. They turn a pile of PDFs
into a knowledge graph you can query.

For months the labels *looked* fine. A model would read a passage, emit a sensible
label, and move on. Nobody had ever measured whether the labels were actually *right*,
because measuring requires an answer key — a set of passages labeled by experts — and
we didn't have one yet.

The uncomfortable truth turned out to be this: a confident model, faced with a
genuinely ambiguous question, gives you one reasonable-looking answer and hides the
fact that it could just as easily have given a different one. The pipeline asked once,
got one answer, wrote it down, and the doubt never surfaced anywhere.

### Step 1 — Build an answer key when your experts are unavailable

We needed an answer key, and the experts who would normally build it weren't available.
So we built a stand-in — intended as temporary, and in the end permanent, because the
experts never became available. We took two different frontier AI models, gave them
the same neutral "expert coder" instructions, and had each one independently label the
same 120 passages. Two independent labelers means we can measure **agreement**: how
often do they choose the same label? If two careful readers can't agree, the label
itself is in trouble.

The first result was alarming. On the two hardest axes — kind-of-claim and
theoretical-school — the two models agreed only **49% of the time**. Our bar for
keeping a label axis at all is 60% agreement. Both were underwater.

The obvious reactions were all wrong, and we caught ourselves before acting on them:

- **"The models are just weak, use a smarter one."** We checked. Our cheap production
  tagger agreed with one frontier labeler *more* than the two frontier labelers agreed
  with each other. Model strength was not the lever.
- **"The label definitions are vague, rewrite them."** A reasonable guess. We'll come
  back to it — it was measured, and it did nothing.

### Step 2 — Move labeling in-house so we could run real experiments

Here is the pivotal, unglamorous decision. Labeling by hand-driving two commercial chat
tools is slow, unrepeatable, and expensive. You can't run the same experiment ten
times. You can't hold one thing fixed and vary another. Science needs controls, and
hand-driven chat tools don't give you cheap controls.

So we moved the labeling into our own pipeline and ran it with a scripted, API-driven
model. Same task, but now programmable, repeatable, and cheap enough to run many times.
That single change unlocked the actual diagnosis, because it let us run several tightly
controlled conditions and repeat them.

Three things fell out immediately:

1. **Half of any "improvement" from switching labelers was fake.** When we asked *one*
   model family to label the same passages twice, agreement jumped from 49% to about
   73% — with no other change. Asking the same *kind* of model twice flatters the
   number, because two instances of the same model think more alike than two different
   models do. Lesson: only ever compare agreement *within one model family*. Without
   this control we'd have announced a fake victory.

2. **The ceiling was the model arguing with itself.** We gave the *same* model the
   *exact same passage and instructions* twice. On theoretical-school it reproduced its
   own earlier answer only **73% of the time**. Read that again: not two different
   labelers — the *same* labeler, disagreeing with itself on a re-read one time in four.
   Two labelers can never agree more than one labeler agrees with itself, so 73% wasn't
   a floor we could push through by trying harder. It was a ceiling.

3. **Every attempt to raise that ceiling by talking to the model failed.** We rewrote
   the label definitions from circular to genuinely discriminating (cost: 55% more
   tokens on every call) — no improvement. We added an explicit rule about which unit of
   text to judge — nothing. We fed the model a summary of the book each passage came
   from — *negative*, slightly worse. Three sensible prompt fixes, three duds.

### Step 3 — The insight: it's a sampling problem, not a knowledge problem

If the model disagrees with itself on a re-read, then each answer is really a **draw**
from a small cloud of defensible answers. The passage genuinely has a most-likely
correct label, but any single reading can land next to it instead of on it.

We checked, and that is exactly what was happening. For **97% of passages a clear
favorite answer exists**; a single reading hits that favorite about 88% of the time.
The other 12% of the time it lands on a neighbor. Two independent readings therefore
agree about 0.88 × 0.88 ≈ 77% of the time, which is almost exactly the agreement we kept
measuring. The math closed.

So the fix is not to make the model smarter. It is to stop trusting a single roll of
the dice.

### Step 4 — Best-of-N: draw three times and take the majority

Instead of labeling each passage once, label it **three times** and keep the answer
that wins two votes out of three. That is the whole trick.

| Axis | Label it once | Best-of-3 vote |
|---|---|---|
| theoretical-school | 0.757 | **0.918** |
| kind-of-claim | 0.796 | **0.866** |

The stuck axis jumped 16 points, and — this is the important part — **0.918 is past the
0.73 ceiling of a single reading.** That is not a contradiction. Voting doesn't make the
model smarter; it recovers the favorite answer that each single reading was scattering
around. We predicted about 0.92 from the sampling math before running it, and measured
0.918.

**What does voting cost?** Sometimes all three readings disagree and there is no
majority. That happens on about **8.8%** of passages for theoretical-school. But instead
of treating that as a failure, we treat it as a **feature**: when three careful readings
can't agree, the honest output is "this passage is genuinely contested," not a
coin-flipped label pretending to be certain. We flag it and move on. (Want fewer flags?
Vote five times instead of three; the undecided rate drops to about 1%.)

There is a bonus. Occasionally a single reading produces an outright invalid label. The
vote quietly outvotes it. Invalid-label rate went from 0.56% on a single draw to **0% at
best-of-3**. The vote self-repairs.

### Why this is worth writing down

The instinct when an LLM gives shaky output is always to *talk to it better* — rewrite
the prompt, add context, upgrade the model. We tried all three and measured all three at
roughly zero. The one thing that worked was the thing nobody reaches for first: **accept
that the model is sampling, and sample it deliberately.** Three cheap calls and a
majority vote beat a 55%-bigger prompt, beat added context, and beat a more expensive
model — combined.

The second idea worth keeping is **abstention as a first-class output.** A tagger that
says "I genuinely can't decide" on the small fraction of passages that are actually
contested is more trustworthy than one that always answers. We route that uncertainty
into a flag a human can review, rather than burying it in a confident-looking label.

---

## Part II — The technical version

### 2.1 Setup

**Sample.** 120 passages, stratified across the label axes. Each passage also carried
the production tagger's own output, which later let us check labelers against the
pipeline's existing guess.

**Axes.** Two axes are *blind* — the labeler assigns from scratch: `claim_type` and
`theory_school`. The rest ship the pipeline's guess and the labeler corrects it: `field`,
`empirical_scope`, and a free-text `polities` axis.

**Metric.** Per-axis exact-match agreement between two independent label sets over the
shared rows. Our retention bar is ≥ 0.60 inter-annotator agreement for a blind axis to
be kept.

### 2.2 Phase 1 — external cross-family baseline

Two frontier models from different providers, same persona-neutral coder prompt, initial
(placeholder) label definitions.

| Axis | Labeler A vs Labeler B | Kind |
|---|---|---|
| `claim_type` | **0.49** | blind |
| `theory_school` | **0.49** | blind |

Both blind axes below the 0.60 bar. Two corrections to the naive reading, both found by
checking labels against the stored production output:

1. **The pre-labeled agreement figures were not annotator agreement.** One labeler
   rubber-stamped the pipeline's pre-fill (0.99 / 1.00 / 1.00) rather than labeling. Any
   labeling run must verify each labeler's *correction rate* against the pre-fill before
   trusting its agreement number.

2. **"The tagger never marks absence" was an artifact.** The `not-applicable` value
   entered the schema *after* most gold passages were already tagged, so the tagger
   literally could not emit it. Where it was available it used it sensibly.

**Model tier exonerated.** Restricting to passages where both labelers named a real
school (removing the absence-marker asymmetry):

| | production (cheap tier) vs A | production vs B | A vs B |
|---|---|---|---|
| `theory_school` | 0.38 | 0.30 | 0.56 |
| `claim_type` | **0.56** | 0.35 | **0.49** |

On `claim_type` the cheap production tagger agrees with Labeler A *more* than the two
frontier models agree with each other. The ceiling is a property of the axis, not the
model tier.

### 2.3 The pivotal move — labeling in-pipeline

The hand-driven external roster made controlled experiments unaffordable and
unrepeatable. Labeling was moved into the pipeline and run with a scripted API model,
which made controlled arms cheap. Four conditions, label definitions held constant so
each comparison isolates one variable; 10 labeler runs total.

| Arm | definitions | unit rule | source context | isolates |
|---|---|---|---|---|
| NOUNIT | v2 | — | — | replicates the external framing → same-family inflation |
| BASE | v2 | ✓ | — | vs NOUNIT: the unit-of-analysis rule |
| BASE-R | v2 | ✓ | — | identical re-run of BASE → intra-annotator ceiling |
| CTX | v2 | ✓ | ✓ | vs BASE: source title / thesis / stated argument |

**Operational note.** A 60-row labeling job sat near the model's output-token cap; 3 of
10 runs truncated there. Instruct labelers to read inputs once, never echo source text,
emit no per-row commentary, and write once. If a batch fails twice, split it in half.

### 2.4 Finding 1 — same-family inflation

NOUNIT gets the *exact* framing the two external labelers received; only the model
family differs.

| | cross-family (external A vs B) | NOUNIT (same-family) | inflation |
|---|---|---|---|
| `claim_type` | 0.49 | 0.75 | **+0.26** |
| `theory_school` | 0.49 | 0.72 | **+0.23** |

Roughly half the apparent jump from switching labelers is the artifact of asking one
model family twice. Cross-family and same-family agreement numbers are not comparable
(same-family runs ~+0.25 higher on identical instructions, with no design change).

### 2.5 Finding 2 — the intra-annotator ceiling

Same model, identical prompt, same 60 passages, run twice (BASE vs BASE-R):

| axis | SELF (test–retest ceiling) | INTER observed | headroom |
|---|---|---|---|
| `field` | 0.95 | 0.98 | none |
| `empirical_scope` | 0.90 | 0.87 | none |
| `claim_type` | 0.78 | 0.77 | none |
| `theory_school` | **0.73** | **0.73** | **zero** |

Inter-annotator agreement cannot exceed intra-annotator reliability, and it has already
reached it. A model reproduces its own `theory_school` label only 73% of the time.
Invisible in production because the pipeline draws once.

### 2.6 Finding 3 — every prompt-side intervention was null

| intervention | cost | `theory_school` | `claim_type` |
|---|---|---|---|
| richer definitions (circular → discriminating) | +55% tokens/call | ~0 | ~0 |
| unit-of-analysis rule | one sentence | +0.02 | +0.12 (one batch only) |
| source context (title / thesis / stated argument) | a code change | **−0.01** | +0.03 |

Source context measured +0.12 on one batch but +0.03 across all 120 — the batch-level
gain was noise. `claim_type`'s batch-to-batch variance (0.20) exceeds every effect
measured. Source context was rejected on measurement. The richer definitions were
*trimmed* (per-call block +24% over the placeholder version rather than +55%) and kept
for readability alone, explicitly not for a measured agreement gain.

### 2.7 Finding 4 — the variance is recoverable by sampling

Three independent draws of the same task, n=60:

| axis | unanimous 3/3 | majority 2/3 | no majority |
|---|---|---|---|
| `claim_type` | 0.75 | 0.23 | 0.02 |
| `theory_school` | 0.67 | 0.30 | 0.03 |

For 97% of passages a clear modal label exists; a single draw simply samples around it.
Arithmetic check: a single draw hits the mode ~0.88, so two draws agree ≈ 0.88² ≈ 0.77,
matching the 0.72–0.77 measured. The axis is not intrinsically unreliable — the pipeline
samples it once.

### 2.8 Finding 5 — best-of-N breaks the single-draw ceiling

Six independent draws on the same 60 passages. N=1 is the mean over all 15 draw pairs;
N=3 enumerates all 10 disjoint 3/3 splits, majority-votes each half, and compares half
against half. Deterministic, no sampling.

| axis | N=1 | N=3 | gain |
|---|---|---|---|
| **`theory_school`** | 0.757 | **0.918** | **+0.162** |
| **`claim_type`** | 0.796 | **0.866** | +0.070 |
| `polities` | 0.897 | 0.946 | +0.049 |
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

0.918 is measured on the ~91% that decide. Undecided passages are *not* short (median
1145 characters vs 1307 for decided ones), so this is genuine contestedness, not thin
input.

**Self-repair.** `theory_school` out-of-vocabulary rate 0.0056 (single) → 0.0000 (N=3);
invalid draws are outvoted.

**Cost comparison across everything tried:**

| | cost | `theory_school` gain |
|---|---|---|
| richer definitions (kept, trimmed) | +24% tokens | 0 |
| source context (rejected) | a code change | −0.01 |
| **best-of-3** | **3× calls, cheap tier** | **+0.162** |

Best-of-3 was the only spend in the entire investigation that bought anything.

### 2.9 The production design

**Best-of-N voting on the blind axes.** The tag pass draws its per-passage call `N`
times and majority-votes the two blind axes. `N` is per-pass configuration, default 3
for the tag pass and 1 elsewhere; **`N = 1` is an exact no-op** — one draw, no voting
layer, the record shape unchanged. The pre-labeled axes take the first draw's value:
their gains from voting are real but small.

**Abstention is a per-axis flag, never a vocabulary value.** When an axis's `N` draws
hold no strict plurality, that axis records:

```yaml
theory_school: { primary: null, abstained: true, draws: [<distinct answers, draw order>] }
```

Abstention is kept structurally *outside* the label vocabulary. Each vocabulary value
says something about the *passage* (this school applies; the passage advances no
theoretical position; a real school this vocabulary is missing). Abstention says
something about the *draw distribution*: the draws disagree. A consumer checks
`abstained` before reading `primary`. The flag is per axis, not per record — a passage
routinely decides one blind axis while abstaining on the other. A decided axis is
byte-identical to the single-draw shape.

**Interaction with output validation.** Each draw runs the full parse → validate →
single bounded re-ask path independently. A draw that recovers a valid answer casts a
legal ballot; a draw still invalid after its own re-ask is a spoiled ballot the vote
ignores. The hard error stands only when *every* draw is invalid, which is what makes
the vote self-repairing on out-of-vocabulary output.

### 2.10 Limitations

- The ceiling rests on **one replicate at n=60**. Six independent measurements converged
  on 0.67–0.76, but a second replicate should land before it is treated as settled.
- One replicate leaked a `claim_type` value into `theory_school` on 2 rows — a cross-axis
  leak worth watching. Excluding those rows moves the ceiling 0.73 → 0.76 against an
  observed 0.73; the conclusion is unchanged.
- `claim_type`'s batch-to-batch variance (0.20) exceeds every intervention effect
  measured; that axis needs a larger sample before any strong claim about it.
- **All figures were measured against a stand-in answer key, and stay that way.** The
  human-labeled key never materialised, so these scores are not awaiting a re-derivation
  that will settle them — they are provisional permanently and should never be cited as
  final. What generalizes is the mechanism, not the specific numbers.

### 2.11 Reusable lessons

1. **Measure test–retest before you trust agreement.** An inter-annotator number is
   uninterpretable without the intra-annotator ceiling beside it. Agreement cannot
   exceed self-consistency.
2. **Compare only within one model family.** Same-family agreement runs materially
   higher than cross-family on identical instructions, with zero design change. Mixing
   families manufactures fake wins and fake losses.
3. **Verify the labeler actually labeled.** Check each labeler's correction rate against
   any pre-fill; a rubber-stamp at 0.99/1.00 silently voids the whole comparison.
4. **For an underdetermined generative task, sample — don't over-prompt.** When a model
   disagrees with itself on a re-read, each answer is a draw. Majority voting recovers
   the mode more cheaply and more reliably than prompt engineering or a model upgrade.
5. **Make abstention a real output.** Flagging the genuinely contested minority is more
   honest than a confident coin-flip, and it keeps a human in the loop exactly where the
   machine has no defensible answer.
