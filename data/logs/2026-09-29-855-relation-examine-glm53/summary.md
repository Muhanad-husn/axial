# Run: 855 relation examine, proposing-model experiment

Founder-requested: the same `axial vocabulary examine --column relation` as
`../2026-09-29-855-relation-examine/` (the baseline, deepseek-v4-flash), with
the proposing/assigning model swapped. Seed 0, so every arm drew the same
propose and held-out samples; the check model stayed gpt-5.6-luna in all
three. The two new arms ran concurrently, each detached with its own secrets
copy (`secrets/secrets.exp-ds41.toml`, `secrets/secrets.exp-glm53.toml`)
setting `production_vocabulary_examine`. The deepseek-v4.1-flash arm's own
console and memory log are in `../2026-09-29-855-relation-examine-ds41/`.

## Results

| | v4-flash (baseline) | v4.1-flash | glm-5.3-flash |
|---|---:|---:|---:|
| kinds proposed | 17 (3 empty) | 15 | 10 |
| kinds with 5+ members, cross-book | 11 | 11 | 10 |
| assigned, held-out (of 400) | 97.8% | 97.2% | **99.8%** |
| refused | 9 | 11 | 1 |
| largest kind share | 18.5% | 18.5% | 21.8% |
| agreement with check model (n=100) | 76.0% | 77.0% | **87.0%** |
| agreement where assigned | 78.4% (97) | 80.2% (96) | 87.9% (99) |
| conflict-type share of assigned | 12.3% (48/391, folded) | 12.9% (50/389: contradiction 43, critique 4, contrast 3) | 12.3% (49/399) |
| cost (examine + check) | $0.0059 | $0.0157 | $0.0453 |
| wall clock | 239s | 52s | 751s |
| reasoning | off | off | **low (mandatory)** |

## Notes

**glm-5.3-flash cannot run with reasoning off.** The first launch failed on
its first call: `400 Bad Request ... "Reasoning is mandatory for this endpoint
and cannot be disabled."` It was relaunched with `reasoning_by_pass:
vocabulary_examine: low` added to `config/pipeline.yaml` for the few seconds
it took the process to load its config, then removed; the deepseek arm had
already loaded its config and is unaffected. So this arm differs in two
things, model and reasoning, and the result cannot say which one did it.

**Its calls are slow and uneven**: 354s and 267s for two of five calls, the
latter emitting 31,371 completion tokens for a 100-value batch (reasoning
tokens), against 23-61s for the other three. Every call finished inside the
600s request deadline.

**Fewer kinds make agreement easier.** glm proposed 10 against 15-17, and two
models agree more often when there are fewer boxes to pick from, so part of
the 10-point agreement gain is the coarser scheme, not a better judge. Its
ten line up closely with the nine-kind flat scheme folded by hand from the
baseline (conflict, qualification, support, illustration, mechanism with
additional cause folded in, specification, extension, grounding, context),
plus one new kind, "convergence / redundancy" (8).

**One draw per arm.** #805 measured about 7 points of run-to-run noise in
the assignment rate on byte-identical input; the 10-point agreement gap is
larger than that but has not been replicated.

v4.1-flash reproduces the baseline within noise on every row, 4.6x faster.

## Repeat (founder-requested), same seed, same settings

Logs in `../2026-09-29-855-relation-examine-ds41-r2/` and `-glm53-r2/`.

| | v4.1-flash run 1 | v4.1-flash run 2 | glm-5.3-flash run 1 | glm-5.3-flash run 2 |
|---|---:|---:|---:|---:|
| kinds proposed | 15 | 10 | 10 | 10 (propose call ok, 9s) |
| assigned, held-out | 97.2% | 97.0% | 99.8% | **did not finish** |
| agreement (n=100) | 77.0% | 82.0% | 87.0% | - |
| agreement where assigned | 80.2% (96) | 89.0% (91) | 87.9% (99) | - |
| wall clock | 52s | 27s | 751s | stopped at 1,353s |

**glm-5.3-flash run 2 failed.** Batch 1 answered in 79s; batch 2 hit the 600s
request deadline twice (`outcome=error error=deadline_exceeded
elapsed=600.0s`) and was on its third and last attempt, with two batches still
to go, when it was stopped by hand at 22.5 min. Across both runs its single
calls took 267s, 354s, 600s+ and 600s+, one of them emitting 31,371 completion
tokens for a batch of 100 short labels. It is not reliable enough to assign
1,472 relations.

**The agreement gap was mostly the scheme's size.** v4.1-flash went from 77%
to 82% (89% where assigned) when its own proposal dropped from 15 kinds to 10,
the same size glm proposed. At ten kinds the two models are within noise of
each other, so glm's run-1 lead does not survive as a model effect.
