# 2026-09-30 — #860: opposition-seeded bagging, judged by map compare

**Reading: opposition moves book-spread in the right direction, but by about a
fifth, not the 2x the bar asks, and it costs purity.** D1 rose in every band
(plurality band 3-5: 0.37 to 0.45; cross-book share of 2+ positions 24.7% to
35.7%). D2 purity fell 0.0215 (inside the 0.0331 floor on the member-weighted
scale, outside it on lift, -0.180 against 0.068). D4 improved (6.9% to 5.3%).
Per the issue's acceptance, a fail: recorded here, run directory kept, no
rebuild issue opened.

## Command

```
python watch_run.py  D:\axial-runs\.venv\Scripts\python.exe -m axial.cli map build --grouping opposition
uv run axial map compare data/map/9b796b3a6312b329 data/map/9b796b3a6312b329-opposition --vocabulary-dir data/vocabulary
```

Run from `D:/axial-runs` at `f0a24bd` (#874), detached with `Start-Process`
under `watch_run.py` (OpenRouter key usage every 30s to `spend.jsonl`, tree
killed at a cap). Extraction and relations both on `deepseek/deepseek-v4.1-flash`
(`production_low` since 2026-09-29); the baseline extracted and related on
`deepseek-v4-flash`. The founder ruled the two equal without a new measurement,
so the model change is a confound this run does not separate. Reasoning as
configured in `config/pipeline.yaml`, unchanged. Compare: zero model calls,
seed 831, 20 trials.

## Cost and run

| launch | cap | stopped at | spend |
|---|---|---|---|
| 1 | $4.00 | extraction 1,023/1,024 (last read on its 2nd deadline retry) | $4.00 |
| 2 | $1.50 | relations 283/404 | $1.51 |
| 3 | $0.90 | relations 115/121 remaining | $0.91 |
| 4 | $0.30 | finished | $0.10 |
| **total** | | | **$6.52** |

- 1,430 calls, 10.33M completion tokens. v4.1-flash averages about 6,700
  completion tokens per extraction read (luna: 2,650), mostly reasoning; it is
  fast (~177 tok/s per call, median call 23s) but verbose. That, plus 1,024
  reads against 679, is why the issue's ~$1.20 became $6.52.
- Seven calls hit the 600s deadline; zero failed reads in extraction or
  relations. Spend is the key-usage delta and counts anything else on the key.
- `map.json` records only the last launch's cost; the table is the true figure.

## Result (A = baseline 9b796b3a6312b329, B = opposition)

| metric | A | B | against the bar |
|---|---|---|---|
| D1 book-spread ratio by band (2 / 3-5 / 6-10 / 11+) | 0.59 / 0.37 / 0.24 / 0.14 | 0.65 / 0.45 / 0.28 / 0.17 | **failed**: 0.454 in plurality band 3-5 is under 2x the baseline's 0.374. Up in every band |
| D2 held-out `position` purity (member-weighted) | 0.7597 | 0.7382 | **failed** per compare (#831 condition 2, wrong direction); -0.0215 is inside the 0.0331 floor, lift -0.180 is outside 0.068 |
| D3 member coherence margin by band | +0.058 / +0.089 / +0.114 / +0.127 | +0.036 / +0.066 / +0.088 / +0.119 | **passed**, every band, margins lower than A's |
| D4 passages reaching no position | 414 = 6.9% | 321 = 5.3% (all declined, 0 failed reads) | **passed** |
| D5 blind hand-sample | | | not run |

Context: B has 2,282 positions against 1,937; median size 2 in both, p75 3
against 4; single-passage positions 43.1% against 39.4%; embedding merge folded
602 against 269. Relations 2,304 (1,045 cross-author) over 404 neighbourhoods,
against 1,472 (629) over 340. No replicate run, so D1 and D2 carry no
replicate error bar.

## What this says

- **The lever is real but short.** Every D1 band moved up, and the cross-book
  share rose by 11 points. Only 48% of passages could be reached (the rest
  argue against nothing that two passages share, and fall back to wording
  bags), so this caps how far D1 can move; a doubling was not available from
  this grouping on this corpus.
- **Purity paid for it.** Mixing books in a bag lowered held-out `position`
  purity and coherence. The lift drop is outside its floor; the member-weighted
  drop is not.
- **Coverage improved again**, as in #859: fewer declines, no failed reads.
  With the model change in play, this run cannot say whether that is the
  grouping or v4.1-flash.

## Next

No rebuild. The baseline stays. The run directory
`data/map/9b796b3a6312b329-opposition/` is kept as provenance. With #859 and
#860 both read, #858 (relation candidates from the vocabulary profile, draft
PR #872) is unblocked on the current baseline.
