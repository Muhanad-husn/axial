# The merge pass's noise floor (#677, standing question)

2026-08-05. Main at `16152aa`. 150 re-asks, 475s, **$0.034**.

```
uv run python scratchpad/noise_floor.py --sample 150 --workers 12
```

## What this bought

#677 slice A found that 896 of 1,355 residual merge re-asks (66%) exist only
because issue #449's `(in <sources>)` evidence suffix is folded into the
rendered member line `MergeBatch.key` hashes. A new book mentioning a known
name rewrites the suffix; the merge judgment never changed.

A free pass over `merge_decisions.jsonl` found 888 member-sets decided twice
under *different* evidence, of which 145 (16.3%) flipped. That number was
unusable on its own: the pass runs at temperature 1, the log dedupes by
`batch_key` (33,337 records, 33,337 distinct keys), so no same-input repeat
exists anywhere in the data already bought. **No control arm.**

This run buys it. 865 of the same 888 member-sets are still decided at current
evidence; 150 were sampled by stride over key order and re-asked with
byte-identical rendered input. Every disagreement is sampling noise.

## Result

**Noise floor = 14/150 = 9.3%.** 0 failures.

Pre-registered rule (set before the run): `>=12%` drop the suffix from the key,
`<=5%` close the question, in between leave it. **9.3% lands in the middle
band, so the rule stands: leave the evidence suffix in `MergeBatch.key` and
re-ask the question at 100 sources.**

## The size-matched comparison, which is the honest one

The headline pair (16.3% vs 9.3%) mixes two different populations. Split by
member count:

| members | treatment (evidence changed) | control (identical input) | gap |
|---|---|---|---|
| 2 | 47/506 = **9.3%** | 2/86 = **2.3%** | 7.0 pp, z=2.18, p≈0.03 |
| 3+ | 98/382 = **25.7%** | 12/64 = **18.8%** | 6.9 pp, z=1.19, p≈0.24 |
| all | 145/888 = 16.3% | 14/150 = 9.3% | |

That the treatment's size-2 rate and the control's overall rate are both 9.3%
is a coincidence of the size mix. Read the rows, not the total.

**On two-member batches — 57% of the population — evidence changes the answer
above noise.** A pairwise judgment is otherwise almost perfectly reproducible
(2.3%), so the 7-point lift is the provenance actually doing work. This is
DEC-51 holding up: source provenance was the one evidence tier that helped, and
it is still helping. Dropping the suffix from the key would reuse decisions
better provenance would have changed.

**On three-or-more-member batches, no evidence effect is separable**, because
the pass disagrees with *itself* on 18.8% of them.

## The finding that is not about caching

**The merge pass disagrees with itself on 9.3% of batches, and on 18.8% of
batches with 3+ members, given byte-identical input.**

| members | n | self-disagreement |
|---|---|---|
| 2 | 86 | 2.3% |
| 3 | 32 | 19% |
| 4 | 19 | 16% |
| 5 | 6 | 33% |
| 6+ | 7 | 14% |

A pairwise same-or-different judgment is stable. A *partition* of three or more
surfaces is close to a coin flip on which grouping comes back. That is a
product-quality fact about the alias map, independent of incremental cost, and
it is the ceiling on any reproducibility claim the merge pass can make. Filed
separately.

## Files

- `run.jsonl` — one record per re-ask: members, recorded nodes, re-ask nodes, verdict.
- `baseline.jsonl` — the 150 recorded decisions, snapshotted **before** the first
  call. `_decide_batch` never writes to disk, so `merge_decisions.jsonl` was not
  touched, but a re-ask that can overwrite its own baseline is how a measurement
  destroys itself (#649).
- `console.log` — raw output.

## Notes

- One model throughout: `deepseek/deepseek-v4-flash`, reconcile pass.
- Tail latency was bad: 12 workers, 475s wall, single calls up to 330s. Fine at
  150 calls; would matter at corpus scale.
- Sample sizes are small at 3+ members (64). The per-size control rates above 4
  members are indicative, not measured.
