# Run: real-corpus validation of the run-log spend field (#734)

2026-08-11. The credit-diff check issue #734 asks for, run against PR #738's
branch code before the PR is merged. It found two defects the 2,196-test suite
could not see, and it settled what the ground truth for a cost figure actually
is.

**Result: the field works for the first source of a pass and records `null` for
every source after it. And `estimate_cost` is not the number we should be
logging — the provider hands us the real one on every response.**

## Command

```
cd D:\axial
$env:PYTHONPATH   = "D:\axial\.claude\worktrees\734-runlog-spend\src"
$env:AXIAL_LOGS_ROOT = "data/logs/2026-08-11-runlog-spend-734"
uv run axial run envelope --worklist <2 sources> --ledger <own>
```

Branch code confirmed loaded before the run (`axial.run.__file__` resolved into
the worktree, `LLMClient.calls_for_pass` present). The envelope pass was chosen
because it is model-bearing, priced, one call per source, and costs cents;
`smith-2009` and `zaum-2007` had their cached envelopes moved aside so the pass
could not take its cache-hit path, and the originals were restored afterwards.
**The corpus is byte-identical to before this run.**

## What the run recorded

| source | model | prompt | completion | usd |
|---|---|---|---|---|
| smith-2009 | deepseek/deepseek-v4-pro | 4129 | 5453 | 0.006540225 |
| zaum-2007 | deepseek/deepseek-v4-pro | **null** | **null** | **null** |

The console shows zaum's call plainly — `prompt_tokens=3476 completion_tokens=7284`
— so the null is not a missing usage object. It is defect 1.

`report.json` total: `0.014389365`. Credit diff across the run window:
`0.030918933`.

## Defect 1 — every source after the first records null

`OpenRouterClient.usage_for_pass` returns `self._usage_by_pass[pass_name]`, the
live dict `_accumulate_usage` mutates **in place**. So the "before" snapshot
`run_pass` takes is an alias of the "after" one, not a copy. For source 1 the
comparison works (before is `None`, no entry yet); from source 2 on,
`usage_after == usage_before` is trivially true, which the new code reads as
"a call happened but carried no usage" and writes as null.

Snapshotting a copy fixes it.

This aliasing is **older than #734**. The pre-existing line
`model = client.model_for_pass(pass_name) if usage_after != usage_before else None`
has the same bug, which means every run log this project has ever written
records `model: null` for every source after the first of each pass. #738's
switch to `calls_for_pass` fixed that by accident. Worth checking a shipped run
log before assuming any per-source model attribution was ever real.

## Defect 2 — `estimate_cost` is not the ground truth, and does not need to be

Every OpenRouter response carries its own charge in the `usage` object:

```
usage.cost                                 2.001e-05
usage.cost_details.upstream_inference_cost 2.001e-05
usage.completion_tokens_details.reasoning_tokens
```

`_accumulate_usage` reads `prompt_tokens`/`completion_tokens`/`total_tokens` off
that same object and drops `cost`.

Two controlled single calls, same model, against `estimate_cost` on the tokens
the provider itself reported:

| call | prompt | completion | reasoning | `usage.cost` | `estimate_cost` | est/real |
|---|---|---|---|---|---|---|
| A | 11 | 25 | 22 | 2.57725e-05 | 2.6535e-05 | 0.97 |
| B | 11 | 6 | 0 | 2.001e-05 | 1.0005e-05 | **0.50** |

The price table is not stale — the live `/api/v1/models` prices for
`deepseek/deepseek-v4-pro` match `PRICE_TABLE_USD_PER_1K` to the digit. The
estimate still lands anywhere from 3% high to 100% low per call. Call B's real
charge looks like a per-request floor (~$0.00002); call A's does not. The run's
own 2.15x gap between the logged `0.0144` and the `0.0309` credit diff is
consistent with the same effect at scale.

**Log `usage.cost`.** It is exact, it is free, it is already in the object being
parsed, and it retires the "runs ~14% high" caveat instead of inheriting it.
Keep `estimate_cost` for pre-flight estimates and for any provider that reports
no cost; that is the case the `null` rule already covers.

## Defect 3 (minor) — the credits endpoint lags

A before/after diff around one call returned the *previous* call's charge, 8
seconds later. `/api/v1/credits` settles too slowly to validate a short run, and
`/api/v1/activity` is 403 on this key. Summing `usage.cost` per response is both
more precise and more attributable than a balance diff — the convention
`data/logs/2026-08-05-623-new-books/credits-*.txt` used should retire with this.

## Spend

$0.031 on the envelope pass, plus ~$0.00005 on the two probe calls.

## Round 2 — the same validation against the fixed branch

Both defects fixed on `feat/runlog/734-spend` (a copied usage snapshot; a third
per-pass accumulator carrying the provider's own `usage.cost`, with
`estimate_cost` kept only as the fallback). Same command, same two sources,
envelopes moved aside and restored again.

| source | model | prompt | completion | usd |
|---|---|---|---|---|
| smith-2009 | deepseek/deepseek-v4-pro | 4129 | 6785 | 0.0074778275 |
| zaum-2007 | deepseek/deepseek-v4-pro | 3476 | 10751 | 0.010553205 |

```
summed run.jsonl usd : 0.018031032
credit diff          : 0.018031032   (75s settle window)
logged / credit-diff : 1.0000
```

**The logged figure equals the provider's own ledger to nine decimal places.**
Both rows carry real numbers; the second source is no longer null. That is the
issue's validation bullet met — and it is exact, not "within 14%", because the
number is no longer an estimate.

Completion tokens moved between the two runs (5453→6785, 7284→10751) on
byte-identical input, so the *cost* is not reproducible run to run even though
the *accounting* is now exact. A before/after comparison of spend needs a margin
wider than that variance, the same way Gather's does.

## Residue

`report.json`'s `total_usd` still reads `0.018564495` — 3% high — because it
comes from `llm.usage_and_cost_by_pass`, which still prices from
`estimate_cost`. That function is shared with `paper/record.py` and
`answer/record.py` and was left alone as out of scope. So a finished run's
`report.json` and its own `run.jsonl` now disagree by a few percent, and
`report.json` is the wrong one. Worth its own issue.

## Next steps

1. Merge #738 on CI green (founder's call).
2. File: move `usage_and_cost_by_pass` onto the provider's real cost so
   `report.json` stops disagreeing with `run.jsonl`.
3. File: audit whether `model: null` in shipped run logs was the aliasing bug —
   if so, no run log before this fix carries per-source model attribution past
   each pass's first source.

## Spend

$0.031 round 1 + $0.018 round 2 + ~$0.00005 in probe calls = **$0.049 total.**
