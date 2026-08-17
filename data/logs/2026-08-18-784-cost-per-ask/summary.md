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
  them changes the cost figures above, but the citation mode does change the
  companion length measurement below.

---

## Companion measurement: how long is the essay, next to the claim list?

Zero model calls — both renders run over paper records already on disk.
Measured on the six single-record papers in `data/papers/`, which are the
shape an ask produces (one analysis record in, one paper out).

| paper | essay words | claim-list words (`locator`) |
|---|---|---|
| `273aea05` | 3,935 | 1,690 |
| `408378f2` | 2,067 | 1,666 |
| `5d866ef2` | 2,263 | 1,416 |
| `9f449f41` | 1,611 | 1,133 |
| `a1039fad` | 1,483 | 1,162 |
| `f5ae5ff2` | 1,595 | 983 |

**The comparison that matters is against `passage`, the mode a fresh install
now resolves to.** DEC-72 measured the reader-facing answer at about **31,000
words** per answer once every ground is quoted in full — 22× the `locator`
figures above, and about 95% quoted book text. This run was made with
`AXIAL_CITATION_MODE=locator` set in the shell (leaked from the local compose
stack, alongside `DATABASE_URL` and a mangled `AXIAL_SECRETS_PATH`), so the
right-hand column is the small version.

So the essay is **1,500–3,900 words of argued prose** where the default answer
is a **31,000-word claim list**. That is the case #784 makes, in one number.

The essay's own in-text citations are book-level (`Vignal 2021, ch. 30`), so
it is short in either citation mode; the quoted passages stay with the claim
list beneath it.

**One caveat on the essay column.** These six papers were drafted from
hand-written declarative theses, not from an ask's question. The arcs a
question plans are the same size (5–8 sections against these papers' 5–10, see
`data/logs/2026-08-17-784-question-as-thesis/`), so the word counts should
carry — but they were not measured on a question-thesis paper.
