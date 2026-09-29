# Run: counter-position on glm-5.3 against glm-5.2 (runs checkout)

Founder-requested model upgrade probe. The counter-position pass
(`counter_position_generate`) is the only pass still on glm-5.2. This run is the
same five smoke briefs as `../2026-09-29-855-smoke-kind/`, with only that pass
moved to `z-ai/glm-5.3` through a secrets copy
(`secrets/secrets.exp-cp-glm53.toml`, line `production_counter_position`).
glm-5.3-flash was ruled out earlier: it forces reasoning and hit the 600s
deadline twice (`../2026-09-29-855-relation-examine-glm53/`). A price row for
`z-ai/glm-5.3` ($0.0014 / $0.0044 per 1k, OpenRouter list price 2026-09-29) was
added to `PRICE_TABLE_USD_PER_1K`.

## Command

```
AXIAL_SECRETS_PATH=D:/axial-runs/secrets/secrets.exp-cp-glm53.toml
(cwd D:/axial-runs, detached with Start-Process, memory sampled by watch_run.py)
axial brief sweep data/logs/2026-09-29-counter-position-glm53/worklist.txt \
  --draws 1 --sweep-dir data/runs/cp-glm53 --arm map --workers 1
```

Exit 0 in 937s (the glm-5.2 run took 1,419s), 5/5 OK, peak 2.72 GB.
`compare.py` prints the table and writes `stances.md` (the ten stances side by
side, generated text over the corpus, no book passages).

## Result

| brief | glm-5.2 time | glm-5.3 time | glm-5.2 completion | glm-5.3 completion | glm-5.2 $ | glm-5.3 $ | words 5.2 / 5.3 | grounds 5.2 / 5.3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S-01 | 8.3s | 7.0s | 1,050 | 993 | 0.0076 | 0.0167 | 103 / 296 | 1 / 3 |
| S-02 | 27.7s | 3.7s | 3,079 | 873 | 0.0194 | 0.0287 | 125 / 310 | 6 / 5 |
| S-03 | 75.6s | 8.0s | 11,408 | 1,447 | 0.0577 | 0.0315 | 151 / 193 | 4 / 5 |
| S-04 | 17.5s | 7.7s | 2,638 | 1,135 | 0.0196 | 0.0146 | 47 / 213 | 1 / 3 |
| S-05 | 35.4s | 5.9s | 3,413 | 1,185 | 0.0179 | 0.0164 | 125 / 229 | 5 / 4 |
| total | 164s | 32s | | | 0.1222 | 0.1079 | | |

- **Five times faster and steadier.** glm-5.3 took 4-8s per call; glm-5.2 took
  8-76s, and its completion counts run far past its short stances (11,408
  tokens for 151 words on S-03), which is hidden reasoning.
- **Cost about the same**, $0.108 against $0.122 for the five, and no longer
  swung by one brief.
- **Stances read better.** glm-5.3 names who holds the opposing view (Hall and
  Schroeder against Mann, Smith, Caspersen), ties it to specific evidence, and
  says which primary claim it contests. glm-5.2's S-04 stance is one generic
  sentence on one ground. glm-5.3's are about twice as long.
- **One defect:** glm-5.3's S-03 stance pastes chunk ids into the prose
  (`jackson-1990..._22_a-new-sovereignty-game_003`). The grounds are carried
  separately, so the ids in the text are noise a reader sees.

Gates: 19/20 against 19/20. S-01 attribution-fidelity failed on a b-seam
mislabel in a synthesis claim, and S-05 calibration passed where it failed in
every earlier run. Neither gate reads the counter-position, and the evidence
each run assembled differs (its own decomposition), so both flips are run noise.

One draw per brief; the stance comparison is one reader's judgment, and no gate
measures it.

## Next

Move `production_counter_position` to `z-ai/glm-5.3` in the live secrets, and
commit the price row. The chunk-id leak is a prompt line in the counter-position
prompt if it recurs.
