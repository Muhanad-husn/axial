# ⚠ Simulated academic inputs — INTERIM, THROWAWAY, re-run on real input

> **This whole folder and everything it produces is simulated.** Five frontier AI
> models, each in a distinct scholarly persona, stand in for the academic inputs that
> Phase B is otherwise blocked on. It exists so engine development proceeds during the
> academic pause. **Nothing here is a result.** When the app is stable, delete every
> simulated artifact and re-run the pipeline from scratch on the real academic input
> before anything is promoted or published. See `docs/DECISIONS.md` DEC-29.

## What is being simulated, and where it lands

| Academic deliverable | Real seam (never touched here) | Simulated stand-in | Committable? |
|---|---|---|---|
| Research questions (#250) | `config/briefs/dev/*.yaml` | `config/briefs/sim/*.yaml` | yes — info about sources only |
| Hard cases (eval #1) | `evals/cases/*` | `evals/cases/sim/*.json` | yes — chunk/source ids only |
| Gold labels | `data/gold/labels/label_sheet.xlsx` | `data/sim/gold/labels/<model>/label_sheet.xlsx` | no — gitignored (source text) |

Isolation is the whole point: the real seams stay empty until real input arrives, so
the real `axial eval` and the real #250 conformance test always measure real data.
Teardown is `rm -rf data/sim config/briefs/sim evals/cases/sim`.

## Model × persona × workstream

| Model | Interface | Persona | Research briefs | Hard cases | Gold labels |
|---|---|---|---|---|---|
| KIMI K3 | kimi.com | [P1](personas/P1.md) | ✓ | ✓ | — |
| GLM 5.2 | z.ai | [P2](personas/P2.md) | ✓ | ✓ | ✓ (labeler A) |
| GPT-5.6 Terra | perplexity.ai | [P3](personas/P3.md) | ✓ | ✓ | ✓ (labeler B) |
| Grok 4.5 | perplexity.ai | [P4](personas/P4.md) | ✓ | ✓ | — |
| Opus 4.8 | claude.ai (memory excluded) | [P5](personas/P5.md) | ✓ | ✓ | — |

Gold labeling is restricted to GLM and GPT — two independent models on two platforms,
which gives inter-annotator agreement. Their gold prompt is persona-neutral (a shared
expert-coder role) so disagreement reflects coding ambiguity, not persona divergence.

## How to run a workstream

1. Open the model's prompt package in [`prompts/`](prompts/) (`kimi-P1.md`,
   `glm-P2.md`, `gpt-P3.md`, `grok-P4.md`, `opus-P5.md`; gold uses
   [`gold-coder.md`](prompts/gold-coder.md)).
2. Attach the files the package lists (persona card, `corpus-bibliography.md`,
   `about-axial.md`, `_output-formats.md`; gold adds `codebook.yaml` + the chunk sheet).
3. **Turn on the model's deep-research / extended-thinking mode before it starts.**
4. Paste the perspective prompt. Ask for structured downloadable output.
5. Save the outputs to the landing paths above, then record the run in the tracker.

Gold input prep (once): `uv run axial gold sample` → `uv run axial gold sheet`
produces `data/gold/label_sheet.xlsx`; export its rows (chunk_id, source, section,
chunk_text, and the pre-filled `field`/`empirical_scope`/`polities_touched`) to a CSV
to attach. After a labeler returns `glm.json`/`gpt.json`, run
`python docs/sim-academic/merge_gold_labels.py <model> <labels.json>`.

## Run tracker

| Date | Model | Persona | Workstream | Mode confirmed | Output | Status |
|---|---|---|---|---|---|---|
| 2026-07-21 | **Gemini 3.1 Pro** (substituted for KIMI K3) | P1 | briefs + hard cases | not stated in output | `P1-01..06.yaml`, `P1-01..04.json` | ✅ landed — **prose output, hand-mapped** |
| 2026-07-21 | GLM 5.2 | P2 | briefs + hard cases | extended-thinking | `P2-01..06.yaml`, `P2-01..04.json` | ✅ landed |
| 2026-07-21 | GPT-5.6 Terra | P3 | briefs + hard cases | extended-thinking | `P3-01..06.yaml`, `P3-01..04.json` | ✅ landed |
| 2026-07-21 | Grok 4.5 | P4 | briefs + hard cases | extended | `P4-01..06.yaml`, `P4-01..04.json` | ✅ landed |
| 2026-07-21 | Opus 4.8 | P5 | briefs + hard cases | extended-thinking | `P5-01..06.yaml`, `P5-01..05.json` | ✅ landed |
| 2026-07-21 | GLM 5.2 | (neutral coder) | gold labels | extended-thinking | `data/sim/gold/labels/glm/` | ✅ **120/120**, 0 out-of-vocab |
| 2026-07-21 | GPT-5.6 Terra | (neutral coder) | gold labels | extended-thinking | `data/sim/gold/labels/gpt/` | ✅ **120/120** (re-run; first pass truncated at 54) |

**Totals landed:** 30 briefs (5 personas × 6, all load, 30 unique `brief_id`s) · 21 hard cases (all schema-valid, all `source_id`s resolve).

**Deviations from plan.**
- **Gemini 3.1 Pro ran P1 in place of KIMI K3.** It ignored the output format and returned a long-form essay with briefs/hard cases embedded in prose (no fenced blocks, markdown-escaped JSON). Hand-mapped into schema. Its `case` values were *thematic titles* rather than the polity anchor PHASE-B §7.1 requires; corrected to polity+period, with the original title preserved as a `# theme:` YAML comment. Its reasoning mode was never stated, recorded honestly as `not-stated-in-output`.
- **GPT-5.6's gold pass truncated at 54/120 on the first attempt.** A full re-run returned all 120 rows (clean JSON, zero out-of-vocab) and supersedes it. Its `_meta` came back empty, so provenance was restored on landing.

## Inter-annotator agreement (GLM vs GPT, all 120 rows)

| Axis | Agreement | Kind |
|---|---|---|
| `field` | 0.76 | pre-labeled (same starting guess) |
| `empirical_scope` | 0.72 | pre-labeled |
| `polities_touched` | 0.54 | pre-labeled free-text |
| **`claim_type`** | **0.49** | **blind** |
| **`theory_school`** | **0.49** | **blind** |

**Both blind axes fall below the §10 ≥0.6 tag-survival threshold.** The earlier 0.59 measured on GPT's truncated 54 rows was optimistic — those were the early, easier rows.

**The disagreement is diffuse, not concentrated.** `claim_type` has 61 disagreements spread over **45 distinct tag pairs** (largest single pair: 5 — `state-capacity` ↔ `state-society-relations`); `theory_school` has 61 over 42 pairs. No small set of confusable tags explains it.

**Most likely cause: the placeholder codebook, not the axes.** `config/domains/syria/codebook.yaml` still carries auto-generated definitions whose examples are circular ("A passage substantively discussing state capacity" / "A passage with no bearing on state capacity") and carry no discriminating content — the file's own header says they are placeholders to be swapped after the gold-set eval. Two strong models agreeing only ~half the time from scratch is the expected result of that. Corroborating: `theory_school`'s single largest confusion cluster is the *absence* boundary — ~17 disagreements pair a real school against `not-applicable` — and the two labelers used `unlisted` very differently (GLM 1×, GPT 10×), which is a definitional-clarity problem, not a judgment one.

**So what.** This is a simulated, model-vs-model number and decides nothing (DEC-29, §10 — provisional signal only).

## ⚠ Correction to the table above (2026-07-21)

Two of the numbers above do not mean what they appear to, and the first diagnosis
drawn from them was wrong. Both errors were found by checking the labels against the
production tagger's own output, which `axial gold sample` already stores in
`data/gold/chunks/*.json`.

**1. The pre-labeled agreement figures are not annotator agreement.** GLM kept the
pipeline's pre-filled guess on `field` **0.99**, `empirical_scope` **1.00**,
`polities_touched` **1.00** — it rubber-stamped rather than labelled. GPT genuinely
corrected them (0.75 / 0.72 / 0.54). So "field 0.76" was measuring roughly *GPT versus
the pipeline's guess*, with GLM contributing nothing. **Discard the pre-labeled row of
the table above.** Any future labelling run must check each labeler's correction rate
against the pre-fill before its agreement number is trusted.

**2. "The tagger never marks absence" was an artifact, not a behaviour.**
`not-applicable` entered the schema at 2026-07-20 21:08 (`02c29b6`), and **112 of the
120 gold chunks were tagged before that** — the tagger could not emit a value that did
not exist. Where the marker *was* available it uses it sensibly: `mann-v2` 15%,
`ugur` 28%, against the frontier labelers' 34–36%.

**3. The model tier is not the lever.** Fair comparison (restricted to chunks where the
labeler named a real school, removing the marker asymmetry):

| | PROD (`deepseek-v4-flash`) vs GLM | PROD vs GPT | GLM vs GPT |
|---|---|---|---|
| `theory_school` | 0.38 | 0.30 | 0.56 |
| `claim_type` | **0.56** | 0.35 | **0.49** |

On `claim_type` the cheap production tagger agrees with GLM **more** than the two
frontier models agree with each other. It is not an outlier.

**Revised conclusion.** The ceiling is a property of the **axis**, not of the model
tier and not of the codebook prose: two frontier models sharing a codebook agree 0.56
even when both commit to a real school. A confident model on an underdetermined task
emits one defensible tag and the variance stays invisible, which is why the output
"looks fine" and has never been measured — `axial eval` has only ever run against
placeholder labels. Codebook v2's +55% token spend was therefore aimed at the wrong
cause and is **on hold pending the BASE/CTX result** below.

## In-harness Sonnet 5 labeling experiment (2026-07-21)

The external chat-model roster was dropped for gold labeling in favour of dispatched
Sonnet 5 subagents, which made controlled arms cheap enough to run. Four conditions,
codebook v2 held constant throughout, so each comparison isolates one variable.
Raw labels under `data/sim/gold/sonnet/` (gitignored).

| Arm | codebook v2 | unit rule | source context | isolates |
|---|---|---|---|---|
| NOUNIT | ✓ | — | — | replicates the GLM/GPT framing → same-family inflation |
| BASE | ✓ | ✓ | — | vs NOUNIT: the unit-of-analysis rule |
| BASE-R | ✓ | ✓ | — | identical re-run of BASE-L1 → **intra-annotator ceiling** |
| CTX | ✓ | ✓ | ✓ | vs BASE: source `title`/`thesis`/`stated_argument` |

### Finding 1 — most of the apparent improvement was same-family inflation

NOUNIT gets the *exact* framing GLM and GPT received; only the model family differs.

| | GLM vs GPT (cross-family) | NOUNIT (same-family) | inflation |
|---|---|---|---|
| `claim_type` | 0.49 | 0.75 | **+0.26** |
| `theory_school` | 0.49 | 0.72 | **+0.23** |

Roughly half the jump from moving to Sonnet agents is the artifact of asking one model
twice. Without this control the headline would have been a spurious "0.87 fixes it".

### Finding 2 — both blind axes sit at the intra-annotator ceiling

Same coder, identical prompt, same 60 chunks, run twice (BASE vs BASE-R):

| axis | SELF (ceiling) | INTER observed | headroom |
|---|---|---|---|
| `field` | 0.95 | 0.98 | none |
| `empirical_scope` | 0.90 | 0.87 | none |
| `claim_type` | 0.78 | 0.77 (all 120) | **none** |
| `theory_school` | **0.73** | **0.73** | **zero** |

A coder reproduces its own `theory_school` label only 73% of the time. Two independent
coders agree 73%. **Inter-annotator agreement cannot exceed intra-annotator
reliability**, and it has already reached it. Roughly a quarter of chunks get a
different answer on a re-roll — invisible in production because the pipeline draws once.

### Finding 3 — every intervention against that ceiling was null

| intervention | cost | `theory_school` | `claim_type` |
|---|---|---|---|
| codebook v2 (circular → discriminating definitions) | +55% tokens per tag call | ~0 | ~0 |
| unit-of-analysis rule | one sentence | **+0.02** | +0.12 (b1 only) |
| source context (`title`/`thesis`/`stated_argument`) | a code change to `compose_multi_axis_tag_prompt` | **−0.01** | **+0.03** |

Context measured **+0.12 on batch2 alone but +0.03 across all 120** — the batch-level
gain was noise. `claim_type`'s batch-to-batch variance is 0.20 (b1 0.87 vs b2 0.67),
larger than any effect measured, so no intervention gain is established on either axis.

### Finding 4 — the variance is recoverable by sampling, not by prompting

Three independent draws of the same task (`base-L1`, `baseR-L1`, `base-L2`), n=60:

| axis | unanimous 3/3 | majority 2/3 | no majority |
|---|---|---|---|
| `claim_type` | 0.75 | 0.23 | **0.02** |
| `theory_school` | 0.67 | 0.30 | **0.03** |

Only 3% of chunks are genuinely irreducible for `theory_school`. For the other **97%**
a clear modal label exists — a single draw simply samples around it. The arithmetic is
consistent: a single draw hits the mode ~0.88 of the time, so two draws agree ≈ 0.88²
≈ 0.77, which is the 0.72–0.77 measured.

**So the axis is not intrinsically unreliable — the pipeline samples it once.**
Best-of-N majority voting is the only intervention aimed at the measured cause, and it
costs ~3× on a pass that already runs on the cheap tier.

### Consequences

- **The model tier is not the problem.** `deepseek-v4-flash` sits inside the same
  variance band as two frontier models (see the correction section above). Nothing
  about the production tagger is broken.
- **Codebook v2's +55% token spend was unjustified** by measurement, and was
  **trimmed to v3** (2026-07-21): the discriminating definitions, the theory_school
  group anchors, and the near-miss `negative_example` pattern are kept; the volume is
  cut. Rendered block **19,793 chars (+24% over v1, −21% against v2)**. Tag ids
  unchanged, all seven axes cross-check consistent, 998 tests green. The residual +24%
  buys non-circular definitions over placeholders that carried no information — a
  readability argument, explicitly *not* a measured agreement gain.
- **Do not wire source context into the tag prompt.** It buys `theory_school` −0.03.
- **The only lever aimed at the real cause is sampling, not prompting** — now measured,
  see Finding 5.
- **`theory_school` is [CANDIDATE] (Appendix E) and this is the §10 keep/cut/rename
  evidence.** With best-of-3 it reaches 0.918, so the cut case is weak — **keep it,
  with best-of-N** (DEC-31).

### Finding 5 — best-of-N works, and it breaks the single-draw ceiling

Six independent draws of the same task on the same 60 chunks (Panel A: `base-L1`,
`baseR-L1`, `base-L2`; Panel B: `panelB-D1..D3`). N=1 is the mean over all 15 draw
pairs; N=3 enumerates all 10 disjoint 3/3 splits, majority-votes each half and compares
half against half. Deterministic, no sampling.

| axis | N=1 | N=3 | gain |
|---|---|---|---|
| **`theory_school`** | 0.757 | **0.918** | **+0.162** |
| **`claim_type`** | 0.796 | **0.866** | +0.070 |
| `polities_touched` | 0.897 | 0.946 | +0.049 |
| `empirical_scope` | 0.893 | 0.939 | +0.045 |
| `field` | 0.968 | 0.980 | +0.012 |

The largest gain lands on the axis that was stuck, and **0.918 is past the 0.73
single-draw ceiling**. That confirms the diagnosis: the ceiling was a property of
*drawing once*, not of the axis. Voting does not make the coder smarter — it recovers
the modal answer a single draw was sampling around. (Predicted ~0.92 from a 0.88
single-draw hit rate; measured 0.918.)

**Abstention is the cost.** A majority-of-3 is undecided when all three draws differ.
The earlier "only 3% irreducible" was one lucky panel; the true rate:

| axis | N=3 | N=5 |
|---|---|---|
| `theory_school` | **8.8%** | 1.1% |
| `claim_type` | 3.3% | 0.0% |
| `empirical_scope` | 1.2% | 0.0% |

So 0.918 is measured on the ~91% that decide. Two notes: the undecided chunks are **not
short** (median 1145 ch vs 1307 decided), so this is genuine contestedness rather than
thin input; and abstention is arguably a **feature** — it flags ambiguous chunks instead
of coin-flipping them, which is the charter's calibrated-confidence principle at the tag
layer. It is a *different* signal from `not-applicable` ("no theory here") and would
need its own treatment.

**The vote also self-repairs.** `baseR-L1`'s invalid `power-typology` values were
outvoted: `theory_school` invalid rate **0.0056 single draw → 0.0000 at N=3**.

**Cost comparison across everything tried:**

| | cost | `theory_school` gain |
|---|---|---|
| codebook rewrite (kept, trimmed) | +24% tokens | 0 |
| source context (rejected) | a code change | −0.01 |
| **best-of-3** | **3× calls, cheap tier** | **+0.162** |

**Limitations, stated plainly.**
- The ceiling rests on **one replicate at n=60**. A second should land before it is
  treated as settled, though six independent measurements have converged on 0.67–0.76.
- `baseR-L1` was the only run with invalid values: 2 rows used `power-typology` (a
  **claim_type** tag) for `theory_school` — a cross-axis leak worth watching. Excluding
  them moves the ceiling 0.73 → 0.76 against an observed 0.73, so headroom is at most
  ~0.03 and the conclusion is unchanged.
- Batch-level variance on `claim_type` (0.20) exceeds every intervention effect
  measured, so that axis needs a larger sample before any claim about it is trusted.

### Vocabulary gaps surfaced

`unlisted` usage was consistent and deliberate across arms (7–11 per 120). **Six chunks
were independently marked `unlisted` by both CTX labelers** — the strongest candidates
for the promotion queue. Reported gaps include ethno-symbolism, primordialism,
Keynesian macroeconomics, and kinship-structured paramilitarism. Ethno-symbolism is
notable: Smith's *Ethno-symbolism and Nationalism* is in the corpus, yet `theory_school`
has no tag for it. Per the established convention this is a **promotion queue, never a
gate**.

## Codebook v2 — superseded by the experiment above

`config/domains/syria/codebook.yaml` was rewritten 2026-07-21 in response to the
above. **Tag ids are byte-identical across all seven axes** (verified); only the prose
changed, and `axial schema validate` reports every axis consistent.

What changed:
- Circular placeholder examples ("A passage substantively discussing X" / "A passage with no bearing on X") replaced throughout. Every `negative_example` is now a **near miss that names the tag to use instead**, since that is what actually teaches a boundary.
- Every `theory_school` definition names its **group** (state / violence / ideology). Several names — `structuralist`, `constructivist`, `materialist`, `systematic`, `discursive` — read as generic without it.
- `historical-sociological` now says explicitly that it concerns **theories of ideology**, and is *not* a general label for historical-sociological writing. It was the single biggest source of confusion with `not-applicable`.
- `not-applicable` carries an explicit decision order (ask *first* whether the passage does explanatory work at all) and restates that it marks absence **of theory**, not absence of a matching label. `unlisted` restates the converse.
- The `empirical_scope` precedence rule (most specific level that claims actually rest on; comparison wins when cases are genuinely compared) is stated on the axis's entries.

**Cost:** the rendered block in every tag prompt grew from ~15,960 to ~24,853 chars (~3,990 → ~6,213 tokens, **+55%**). On a full 17k-chunk re-tag that is roughly +38M tokens. It is only worth paying if agreement actually improves.

**Baseline to beat** (v1 labels archived at `data/sim/gold/baseline-v1/`):

| Axis | v1 (placeholder codebook) | v2 target |
|---|---|---|
| `claim_type` (blind) | 0.49 | > 0.60 |
| `theory_school` (blind) | 0.49 | > 0.60 |
| `field` | 0.76 | ≥ 0.76 |
| `empirical_scope` | 0.72 | ≥ 0.72 |
| `polities_touched` | 0.54 | ≥ 0.54 |

**To re-measure:** re-run [`gold-coder.md`](prompts/gold-coder.md) on GLM 5.2 and GPT-5.6 attaching the **new** `config/domains/syria/codebook.yaml` and the unchanged `data/sim/gold/chunk_sheet.csv` (chunk ids are unchanged, so the sheet does not need regenerating). Land the returned JSONs and the agreement delta decides whether v2 stays, gets trimmed, or reverts.

## Teardown checklist (when the app is stable)

- [ ] Real academic inputs received (research questions, gold labels, hard cases).
- [ ] `rm -rf data/sim config/briefs/sim evals/cases/sim`.
- [ ] Land real inputs in the real seams (`config/briefs/dev/`, `evals/cases/`,
      `data/gold/labels/`).
- [ ] Re-run the pipeline from scratch on the real corpus + real inputs.
- [ ] Re-run `axial eval` for the real, non-provisional numbers.
- [ ] Mark this folder archived (or remove it) and note the teardown in DEC-29.
