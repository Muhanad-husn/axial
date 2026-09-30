# 2026-09-30 — #858: relation candidates from the vocabulary profile

**Reading: the profile pass adds 235 cross-author relations to the map's 629
(+37%), almost none of them already known (16 overlap), for $0.90.** It asserts
a relation on 20% of the pairs it proposes (255 of 1,277), against 26% for the
neighbourhood pass, and 92% of what it asserts crosses authors, against 43%.

## Command

```
python watch_run.py  D:\axial-runs\.venv\Scripts\python.exe -m axial.cli map relate-profile
```

Run from `D:/axial-runs` on `feat/858-profile-relation-candidates` at `cf2b90e`
(PR #872 rebased onto `bcfb293`, #875). Detached under `watch_run.py`, cap
$2.50, 40 workers (the default). Over the baseline build `9b796b3a6312b329`.
Model `deepseek/deepseek-v4.1-flash`; `position_relate` reasoning `medium` from
`config/pipeline.yaml`.

## Cost and run

- $0.90 by OpenRouter key usage, 1,054s wall clock (about 5 minutes for 286
  calls, then 12 minutes on the last one: one 600s deadline, succeeded on the
  second attempt). 287 calls, 0 failed reads.
- The manifest says `cost_usd: 1.57`. The key delta is the true figure; the
  gap is the price table, not reconciled here.
- The manifest says `reasoning=high`. That is a stale label: `build.py`'s
  `POSITION_RELATE_REASONING = "high"` mirrors the config for the manifest only
  and was not updated by #875. The calls ran at the config's `medium`.

## Result

| | neighbourhood pass (baseline) | profile pass |
|---|---|---|
| pairs shown | 5,707 | 1,277 (of 1,469 proposed) |
| relations asserted | 1,472 | 255 |
| asserted per pair | 26% | 20% |
| cross-author | 629 (43%) | 235 (92%) |
| distinct labels | 504 | 189 |
| overlap with the other pass | | 16 pairs |
| off-proposal relations dropped | | 618 |

- **Off-proposal: 618.** The model related 618 pairs it was not asked about
  (positions sharing a call but not proposed as a pair), more than the 255 it
  asserted on proposals. They are dropped by design and counted only.
- **No replicate noise.** `map.json`'s `runs: 3` counts launches of one
  relations pass, not three replicate runs, so there is no error bar to quote
  these against. The PR's acceptance assumed one existed.
- Kind spread (#855) needs `axial vocabulary build --column relation`, a paid
  step not run here.

## Next

The founder reads this and decides #872. Open questions: whether the 618
off-proposal relations should be kept rather than dropped, and whether to fix
the stale reasoning label (one line in `build.py`, both constants).
