# Three hard glm-5.2 passes, re-run on gpt-5.6-luna

2026-08-05. Run from `D:\axial`, main at `16152aa`. **Result: a split, and the
split is by pass, not by model.** Luna wins synthesis, loses counter-position
and paper drafting, and costs 6–12x less on every one of them.

Nothing was merged and no config moved. The luna arm ran against a copy of
`secrets.toml` in the scratchpad via `AXIAL_SECRETS_PATH`; the repo's own
wiring is untouched.

## What was swapped

`z-ai/glm-5.2` → `openai/gpt-5.6-luna` on exactly three tiers:

| pass | tier | reasoning |
|---|---|---|
| `synthesize` | `production_synthesis` | high |
| `counter_position_generate` | `production_counter_position` | high |
| `paper_draft` | `production_paper_draft` | default |

The fourth glm pass, `note_interrogate`, is the ~6,000-call per-note pass with
reasoning OFF — volume work, not a judgment call — and was left alone.

Everything else held: intake, retrieval, arc planning and the shape check all
stayed on `deepseek-v4-pro` in both arms.

## How each pass was isolated

The model is the only variable in all three comparisons.

- **synthesize** — the evidence set is rebuilt from a persisted record's
  trajectory (`assemble_evidence_ids` → `assemble_evidence`, both LLM-free) and
  the SAME `EvidenceSet` object is handed to both arms. No retrieval runs, so
  retrieval's own run-to-run variance cannot leak in. The rebuild is exact:
  24/24, 34/34 and 83/83 notes against what each record originally assembled.
- **counter_position_generate** — both arms are handed the same baseline claim
  graph and the same trajectory, so this measures the counter-position call and
  not each arm's own upstream answer.
- **paper_draft** — intake and arc planning ran ONCE per paper on
  `deepseek-v4-pro`, and both arms drafted every section from that identical
  plan.

Both models were warmed with a throwaway call before anything was timed
(glm-5.2 always cold-starts).

Three samples per pass: records `124f7ba6` (24 notes), `080d9e47` (34) and
`fd0c2636` (83) for the two brief passes; the three dev paper briefs for
drafting.

## Cost and latency

| pass | | glm-5.2 | gpt-5.6-luna | |
|---|---|---|---|---|
| **synthesize** | mean $ | $0.0653 | **$0.0107** | **6.1x cheaper** |
| | mean s | **32.1s** | 53.4s | 1.7x slower |
| | out tokens | 14,060 | 18,178 | |
| **counter_position** | mean $ | $0.0173 | **$0.0030** | **8.6x cheaper** |
| | mean s | **17.6s** | 43.0s | 1.6x slower |
| **paper_draft** | mean $ | $0.0886 | **$0.0075** | **11.9x cheaper** |
| | mean s | 578.6s | **102.6s** | **5.6x faster** |
| | out tokens | 91,238 | 29,182 | |

List price is $0.76/$2.42 per M for glm-5.2 against $0.10/$0.60 for luna, so the
cost gap is the price gap — luna is not winning it by being terse. It writes
*more* on synthesis (18,178 output tokens against 14,060) and still costs a
sixth as much.

The latency reversal on drafting is glm's verbosity: 91,238 output tokens across
three papers against luna's 29,182, one section call that took 928s on its own,
and 3 retries. Per output token the two are close on drafting (19ms vs 10.5ms)
and close on synthesis (6.8ms vs 8.8ms).

**Total spend: $1.48** — $0.514 the glm arm, $0.060 the luna arm, $0.011 arc
planning, $0.891 the judges.

## Quality: 24 blind ballots

Three judges from three labs, none of them either model under test
(`deepseek-v4-pro`, `gemini-3.5-flash`, `claude-sonnet-5`). Each saw the pair
relabelled A/B with the assignment flipped between units, no model names, and
grounds resolved to real passage text so grounding is checkable. Judged on
grounding, completeness, argument and attribution.

| pass | units | ballots | verdict |
|---|---|---|---|
| **synthesize** | luna 2, glm 1 | **luna 7–2** | **luna** |
| **counter_position** | glm 3, luna 0 | glm 5–1 | **glm** |
| **paper_draft** | glm 2, luna 1 | glm 6–3 | **glm** |

### synthesize — luna, on attribution

All three judges said the same thing without prompting: luna is more honest
about which claims are its own cross-source inference. deepseek: "B narrowly
wins on attribution and grounding due to A's mislabeling of cross-source claims
as single-source." sonnet-5: "B is more rigorous and honest in distinguishing
source claims from its own cross-source inferences."

That matters more than a preference — kind-(b) mislabelling is one of the rung-3
gates (`b_seam_mislabel_rate`), and the attribution ballots on this pass ran
luna 5, tie 3, glm 1. It also
writes far fewer claims per answer where glm inflates: 27 claims to luna's 14 on
`080d9e47`, the one unit glm won.

### counter_position — glm, decisively

A counter-position section has to state the rejected position in its strongest
form. Luna states it thinly. sonnet-5: "Section A is far more grounded,
complete, and argumentatively robust... Section B offers only a thin,
underdeveloped assertion." Luna's stances run 677–947 characters against glm's
1,070–1,947.

**And luna hard-failed one of the three.** On `080d9e47` it never returned a
valid grounds entry inside `complete_json`'s bounded re-ask budget:
`InvalidCounterPositionResponseError`. In a real run that is a section marked
failed in the persisted record. 1 schema failure in 3 calls on this pass; 0 for
glm.

### paper_draft — glm, but both arms repeat themselves

glm took two of three papers 3–0. Where luna won (`one-sovereign-or-several`,
2–1) the reason was glm repeating itself: gemini called that draft "severely
undermined by verbatim repetition of entire sentences and citation blocks across
all five sections."

The same criticism landed on luna in `the-long-arc`. **Verbatim repetition
across sections is a drafting-layer defect, not a model's tic** — it showed up in
whichever arm wrote long into a 5-section plan. Worth an issue against Phase C
regardless of which model runs it.

The shape check (`deepseek-v4-pro`, same judge for both arms) returned `strong`
for all six drafts and did not see the repetition either arm was pulled up on.

## What this does and does not support

**Supports:** moving `synthesize` to luna. It wins the pass on the axis the
gates measure, at a sixth of the cost. The 1.7x latency is 20 seconds on a
pass that runs once per brief.

**Does not support:** moving `counter_position_generate`. It loses the pass and
fails one call in three on schema. These two tiers are already separate in
config precisely so one can move without the other, so this is a one-line change.

**Undecided:** `paper_draft`. glm won 2 of 3 but at 11.9x the money and 5.6x the
wall clock, and the loss it took was for a defect (repetition) that luna also
shows. A second draw would be worth more here than anywhere else.

## Caveats

- **N=3 per pass, one draw each.** Nothing here has a variance estimate. This
  project has measured a single brief moving 39% between draws on unchanged code.
- **Sim corpus (DEC-29).** Every figure is provisional-on-sim.
- **The judges are models.** They agreed 21 of 24 ballots with their own panel
  majority, and the attribution finding was independently reached by all three,
  but no human read these outputs.
- **Luna is unpriced in `src/axial/llm.py`.** `PRICE_TABLE_USD_PER_1K` has no
  row for it, so a real run on this wiring reports null cost. Costs here were
  computed in the harness from OpenRouter's published rates. Adding the row is a
  prerequisite for promoting any of this.

## Reproduce

```
uv run python data/logs/2026-08-05-luna-vs-glm/experiment.py   # both arms
uv run python data/logs/2026-08-05-luna-vs-glm/judge.py        # blind panel
uv run python data/logs/2026-08-05-luna-vs-glm/repair.py       # re-ask truncated ballots
```

`run.jsonl` one record per unit, `judgments.jsonl` one per judged pair,
`outputs/` every answer, stance, plan and draft both arms produced.
