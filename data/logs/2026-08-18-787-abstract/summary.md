# 787 slice 04 — the abstract, measured over every persisted paper

**Date:** 2026-08-18
**Branch:** `feat/787-venue-length-house-style/04-every-paper-carries-an-abstract` (`fd37703`)
**Command:**

```
AXIAL_SECRETS_PATH="D:/axial/secrets/secrets.toml" \
  uv run python data/logs/2026-08-18-787-abstract/run_abstracts.py \
  > data/logs/2026-08-18-787-abstract/console.log 2>&1
```

Run in the main checkout `D:/axial`, never a worktree — `data/` does not exist
in one.

## What was measured, and why this substrate

The feature README records that the nine dev briefs cannot discriminate on a
judged property of the writing: slice 01 drafted all nine twice on both arms
and `shape.band` came back `strong` on 35 of 35. Slice 04's plan originally
asked for "three real dev briefs read by eye", which walks straight into that.

The abstract call reads only the plan's `thesis_statement` and the drafted
section prose, and both are already persisted. So the measurement is a harness
over **all 10 records in `data/papers/`** — which include papers drafted from
real analyst questions through `axial ask`, not only the easy dev briefs. **No
drafting call, no retrieval, no record written back, no re-key.**

The 10 records were copied into this directory before the harness ran. They are
gitignored (they carry quoted book text); only this write-up, `run.jsonl` and
the script are committed.

## Result

| | |
|---|---|
| Abstracts generated | **10 of 10**, zero failures |
| Model | `openai/gpt-5.6-luna` (`paper_abstract` → `production_paper_abstract`) |
| Cost | **$0.0257 total**, ~$0.0026 each |
| Wall clock | **35s total**, 3.5s each |
| Words | 202–229, mean **214** against a 200-word target |
| Claim markers | **0** across all 10 |
| Parenthetical citations | **0** across all 10 |

## The bar: does it state the argument, or describe the sources?

**10 of 10 state the paper's own argument and verdict.** Not one is a tour of
the literature, and not one names a scholar. Every abstract opens on the
paper's position, states what the argument rests on, names where the paper
concedes the opposing account has force, and closes on the verdict — which is
what the prompt asks for, in that order.

Quoted in full, `ca17d6077c1a7f5e` — the paper drafted from a real analyst
question, not a dev brief:

> This paper argues that the distribution of power in Syria after 2011 was
> determined primarily by the consolidated Baathist-Assad apparatus rather than
> by mandate-era institutions. Mandate rule mattered as an inherited condition:
> it organized communal categories and helped shape access to military and
> political possibilities. Yet the Baathist coup and Assad's subsequent
> consolidation transformed those possibilities into a state-centered system
> that controlled the institutions through which authority, protection, and
> resources were allocated. […] This conclusion is deliberately limited: the
> apparatus did not autonomously determine the war or every political outcome.
> External actors materially enabled and constrained domestic leaders, and
> mandate structures continued to shape the political field. Nevertheless, in
> the comparison at issue, political centrality had shifted from inherited
> institutional conditions to the state apparatus that most directly preserved
> rulers and excluded those beyond its channels of recognition.

The concession sentence is the part worth noting: the abstract carries the
paper's own limits, not a summary flattened into confidence.

**This is the first draw of a judged property.** A clean 10 of 10 is not proof
the prompt is good — #695 and #700 both established that a single draw of a
judged metric is not a measurement. What it does establish is that the failure
this slice was built to look for does not appear on any of the 10 papers this
product has actually produced.

## Two observations that are not failures

- **Every abstract opens with the identical five words, "This paper argues
  that" — 10 of 10.** The prompt does not ask for that phrase; the model
  converges on it. It is not a defect against this slice's bar, but it is
  exactly the kind of thing slice 05 (house style as domain data) exists to
  govern, and it is the first stylistic uniformity in this product visible
  across every paper at once.
- **The word count runs over, never under:** 202–229 against a 200-word
  target, mean 214, +7%. Consistent with slice 02's ruling that a length target
  is a target and never a cut — nothing here truncates or pads. Worth knowing
  before anyone reads "about 200 words" as a bound.

## Files

- `run.jsonl` — one record per paper: thesis, model, cost, word count, elapsed,
  and the abstract itself.
- `console.log` — raw output, including every `llm_call_request` /
  `llm_call_response` line.
- `run_abstracts.py` — the harness. Re-runnable; it appends, so truncate
  `run.jsonl` first.
- `*.json` (gitignored) — the 10 paper records as they stood before the run.

## Next steps

- Open the PR for slice 04 (`aeo:safe-pr`).
- Slice 05 is the last of #787, and the "This paper argues that" uniformity is
  a concrete thing for it to hold an opinion about.
