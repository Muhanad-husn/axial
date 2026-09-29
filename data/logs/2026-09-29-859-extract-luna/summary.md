# 2026-09-29 — #859: extraction on gpt-6-luna, same 660 bags, judged by map compare

**Reading: the bagging is the ceiling, not the extraction model.** A stronger
extraction model left book-spread (D1) where it was, band for band. What moved
is coverage: luna declined fewer passages, so fewer passages reach no position
(D4, 6.9% to 4.3%). Per the issue, a small move on the bagging-bound property
says the opposition-seeded lever (#860) is next. No rebuild is promoted.

## Command

```
python watch_run.py  D:\axial-runs\.venv\Scripts\python.exe -m axial.cli map build --extract-model openai/gpt-6-luna
uv run axial map compare data/map/9b796b3a6312b329 data/map/9b796b3a6312b329-variant-openai-gpt-6-luna --vocabulary-dir data/vocabulary
```

Run from `D:/axial-runs`, detached with `Start-Process`, under `watch_run.py`
(OpenRouter key usage sampled every 30s to `spend.jsonl`, tree killed at a cap).
Bags reused byte-identically from `9b796b3a6312b329/bag_state.json`. Extraction
reasoning high, as in the baseline. Relations on `deepseek/deepseek-v4-flash`,
unchanged. Compare: zero model calls, seed 831, 20 trials.

Model choice: Sonnet 5.5 (~$10-30 estimated) and glm-5.3 (~$9.5 projected,
capped at $4 after 287 reads, discarded) were rejected on cost by the founder;
see `../2026-09-29-859-extract-glm53/summary.md`.

## Cost and run

| stage | model | calls | prompt tok | completion tok | spend |
|---|---|---|---|---|---|
| extraction | openai/gpt-6-luna | 679 | 611,435 | 1,803,471 | $1.02 |
| relations | deepseek-v4-flash (+1 content-filter fallback to v4-pro) | 386 neighbourhoods | 222,425 | 2,561,000 | ~$2.52 |
| **total** | | | | | **$3.54** |

- Spend is the key-usage delta, which counts anything else on the key in that window.
- Relations cost far more than their tokens price at (~$0.40): 30+ calls hit the 600s deadline and were retried up to three times; timed-out reasoning appears to be billed. Two neighbourhoods failed all three attempts (baseline: one).
- The first launch was capped at $3.00 at 379/386 neighbourhoods; a resume under a $0.50 cap finished the last 7 in 31 min. `map.json` records only the resumed process's cost (#830 accumulation cannot see a killed run that never wrote a manifest); the table above is the true figure.
- Wall: extraction 10 min, relations ~69 min in total.

## Result (A = baseline 9b796b3a6312b329, B = luna variant)

| metric | A | B | against the bar |
|---|---|---|---|
| D1 book-spread ratio by band (2 / 3-5 / 6-10 / 11+) | 0.59 / 0.37 / 0.24 / 0.14 | 0.59 / 0.37 / 0.21 / 0.14 | **failed**, verbatim: "0.369 in the plurality band 3-5 is under 2x the baseline's 0.374". Unmoved, not worse |
| D2 held-out `position` purity (member-weighted) | 0.7597 | 0.7918 | **not resolved**: +0.0321 against the 0.0331 floor; lift -0.065 against 0.068, also inside |
| D3 member coherence margin by band | | +0.059 / +0.094 / +0.117 / +0.142 | **passed**, every band |
| D4 passages reaching no position | 414 of 6,010 = 6.9% (373 declined, 35 in failed reads) | 256 = 4.3% (256 declined, 0 failed reads) | **passed** |
| D5 blind hand-sample | | | not run |

Context: B has 2,185 positions against 1,937, median size 2 in both, p75 3 against 4;
cross-book share of 2+ positions 20.1% against 24.7%; 1,839 relations against 1,472
(777 cross-author against 629) over 386 neighbourhoods against 340.

The report's closing line "no-go on slices 07-09" is compare's fixed wording from
#831; here it means only that D1 did not clear its bar.

## What this says

- **D1 did not move.** Which books a position draws from is set by which passages share a bag, and the bags are identical. A better reader of the same bag cannot widen it. That is the #859 question answered: the book-spread ceiling is bag-bound.
- **D4 did move.** luna places 158 more passages, all from fewer declines (373 to 256) and no failed reads. That is a model effect on coverage, and the only one.
- **D2 and D3 are at or inside noise.** A smaller-positions build has a mechanical purity and coherence advantage; neither margin is readable as quality at this sample.
- No replicate was run, so D1 and D2 carry no replicate error bar; D1's gap is zero in three of four bands, which needs none.

## Next

#860 (opposition-seeded bagging) runs, because the bagging is the lever D1 depends on.
The variant directory `data/map/9b796b3a6312b329-variant-openai-gpt-6-luna/` is kept as provenance.
Same day, after this run: `production_low` switched from `deepseek-v4-flash` to
`deepseek-v4.1-flash` in both secrets files (founder, no measurement: measured
equal earlier). Every build after this relates on v4.1-flash.
