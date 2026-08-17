# Cost per ask, measured — #784 slice 01

**Date:** 2026-08-18 · **Branch:** `feat/784-ask-ends-in-an-essay/01-essay-from-the-ask`

The issue's own bar: *"Cost per ask is measured and reported, not estimated."*

## Command

```
"1" | uv run axial ask "Did the mandate-era institutions or the Baath decide who held
power in Syria after 2011?" --case "Syria, 1920-2024 -- state formation and who the
arrangement favoured"
```

One real end-to-end run, 486 s wall clock, exit 0. `axial ask` runs the same
`axial.ask.paper.draft_paper_for_turn` this slice wired into the service
worker, so what is priced here is the composition, not a CLI-only path.
Artifacts: `data/analyses/dd7d4df350da80a3.json`,
`data/papers/ca17d6077c1a7f5e.json`.

## The number

| | USD | tokens |
|---|---|---|
| Phase B answer | 0.121133 | 288,528 |
| **Phase C essay** | **0.013070** | **19,265** |
| **Total** | **0.134203** | **307,793** |

**The essay is 9.7% of the ask — $0.0131, a 10.8% increase on the answer
alone.** The issue estimated **+$0.13**, ten times that, by carrying over
Phase C's release-bar figure of $0.12–0.16 per paper. That figure came from
multi-record papers: drafting scales with the claim inventory, and an ask is
one record. The six single-record papers already on disk cost $0.008–$0.019,
and this run lands inside that band.

Per pass:

| pass | USD | tokens | model |
|---|---|---|---|
| `retrieve` | 0.043237 | 152,091 | — |
| `counter_position_generate` | 0.044183 | 26,121 | — |
| `synthesize` | 0.028153 | 104,539 | — |
| `interrogate` | 0.005299 | 2,155 | — |
| `fork_check` | 0.000261 | 3,622 | — |
| `paper_draft` | 0.010317 | 14,515 | `openai/gpt-5.6-luna` |
| `paper_plan` | 0.001794 | 2,152 | `deepseek/deepseek-v4-pro` |
| `paper_shape` | 0.000959 | 2,598 | `deepseek/deepseek-v4-pro` |

Every `usd` is `axial.llm.PRICE_TABLE_USD_PER_1K`'s priced ceiling, which runs
about 14% high against at least one measured real invoice. No pass went
unpriced and no retry fired (`retries: {paper_plan: 0, paper_draft: 0}`).

## What the essay came out like

A real argued paper, not a claim list. Five sections, 16 claims cited:

```
[setup]             The Political-Economy Lens: Material Interests and Distributive Conflict
[counter-position]  The Counter-Position: The Mandate as Decisive Inheritance
[evidence]          The Pre-2011 Baathist Order: A Coercive-Distributive Regime
[claim]             Continuity Under Fire: The Baathist Core as Principal Post-2011 Power-Holder
[synthesis]         Adaptation and Constraint: The Limits of Central Control in a Fragmented War Economy
```

The planner took a side rather than echoing the question — thesis: *"The
post-2011 Syrian state was not an inheritance of colonial design but a
reassertion of the Baathist political economy…"* — which is the mechanism the
pre-measurement found (`data/logs/2026-08-17-784-question-as-thesis/`).

**The shape check came back `weak`, with one defect, and it is a real one:**

> The counter-position is introduced already diminished — "appears here as a
> background condition rather than the post-2011 decision-maker, limiting its
> explanatory force" — rather than being presented at its strongest before the
> paper's own response.

That is the strawman failure already on record for the argument map
(`argument-map-brief-b-dismissed-to-weak`), now visible in the writer.
`confidence` is `low`, correctly bounded by the thinnest name the paper cites
(`French Mandate Syria`, 19 corpus notes). The shape check reports and never
blocks (PHASE-C §7.16), so the run stands — **but the first real
question-thesis paper straw-manning its counter-position is a finding, and it
belongs to prompt quality (#787 or its own issue), which this slice put out of
scope on purpose.**

## Two operational notes

- **Attempt 1 hung and was killed** (`attempt-1-blocked-on-fork.log`). The
  intake fork check asked a clarifying question and `cli._fork_prompt` blocked
  on stdin a detached process does not have — after paying for the fork check
  and five retrieval turns. Filed as **#790**. The hosted path never prompts:
  `run_ask_job` passes no `on_fork`. The rerun pipes `"1"` in, choosing an
  option before the question is known.
- **This shell had `AXIAL_CITATION_MODE=locator`, `DATABASE_URL` and a mangled
  `AXIAL_SECRETS_PATH` leaked into it** from the local compose stack. None of
  them changes the cost figures above. The companion measurement below clears
  the variable and renders both modes explicitly rather than inheriting one.

---

## Companion measurement: how long is the essay, next to the claim list?

Zero model calls, both renders over records already on disk, resolved against
the real `data/vault/`. Seven single-record papers — the six that predate this
issue plus `ca17d607`, the one the cost run above drafted. Script:
`measure_lengths.py`.

**The first cut of this was wrong and the verifier caught it.** It rendered the
essay under `locator` and compared it against a `passage`-mode claim-list
figure quoted from DEC-72 — two different modes in one comparison — and called
the claim list "the thing it replaces" when nothing is replaced: both still
ship, and the export carries the essay *and* the claim list. All four cells are
rendered here instead.

| paper | essay, `locator` | answer, `locator` | essay, `passage` | answer, `passage` |
|---|---|---|---|---|
| `273aea05` | 4,038 | 1,711 | 4,038 | 41,529 |
| `408378f2` | 2,124 | 1,668 | 2,124 | 50,652 |
| `5d866ef2` | 2,344 | 1,539 | 2,344 | 26,340 |
| `9f449f41` | 1,762 | 1,262 | 1,762 | 22,445 |
| `a1039fad` | 1,596 | 1,306 | 1,596 | 18,537 |
| `ca17d607` | 1,287 | 824 | 1,287 | 19,393 |
| `f5ae5ff2` | 1,713 | 1,041 | 1,713 | 23,822 |
| **total** | **14,864** | **9,351** | **14,864** | **202,718** |

Three readings, all from the table:

1. **The essay is byte-identical in both modes — ×1.00.** Its in-text
   citations are book-level (`format_citation(form=SHORT)`), so `passage`
   resolution adds nothing to it. This is the measurement behind the sentence
   `docs/service-citation-mode.md` now carries; before this run that sentence
   was an unmeasured claim in a document a deployer acts on.
2. **The claim list grows ×21.68 under `passage`** (9,351 → 202,718 words over
   seven answers), which reproduces DEC-72's ×22 on an overlapping set.
3. **In the default mode, the answer is 13.6× longer than the essay** — 18,537
   to 50,652 words of claim list against 1,287 to 4,038 words of argued prose.

**In `locator` mode the essay is the longer of the two** (14,864 against
9,351, about ×1.6). That is the honest shape of it: the essay is a roughly
constant 1,300–4,000 words whatever the mode, and what moves is the claim list
underneath it.
