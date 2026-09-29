# Run: 855 relation build (runs checkout)

#855: `axial vocabulary build --column relation` assigns every relation in the
argument map to the committed flat scheme `2026-09-29-relation-v1`. Run in
`D:/axial-runs` at main `c67ead2`, against map `9b796b3a6312b329` (answers pin
`acf5f4a852d2dcbe`).

## Command

```
AXIAL_SECRETS_PATH=D:/axial-runs/secrets/secrets.toml
(cwd D:/axial-runs, detached with Start-Process, memory sampled by watch_run.py)
axial vocabulary build --column relation
```

Exit 0 in 15.1s, peak private memory 551 MB. **$0.0249** over 15 calls,
deepseek/deepseek-v4.1-flash. Output `data/vocabulary/relation/`
(`assignments.jsonl`, `manifest.json`).

## Result

1,472 relations, 0 excluded. **1,461 assigned (99.3%)**, 11 refused, 0 out of
scheme, 0 unanswered. Every kind spans 50+ sources.

Agreement is not re-measured by `build`; the examine runs put it at 77-82%
against gpt-5.6-luna for v4.1-flash (`../2026-09-29-855-relation-examine-glm53/`).

## Structural read

Cross-author means the two positions' author sets differ, as
`argmap/build.py` counts it; this map has 629, the same count as 6 August.

| kind | all | share | cross-author | share of cross | cross share of kind |
|---|---:|---:|---:|---:|---:|
| support | 276 | 18.8% | 124 | 19.7% | 45% |
| illustration | 250 | 17.0% | 114 | 18.1% | 46% |
| qualification | 216 | 14.7% | 92 | 14.6% | 43% |
| **conflict** | **196** | **13.3%** | **76** | **12.1%** | 39% |
| mechanism | 164 | 11.1% | 74 | 11.8% | 45% |
| grounding | 101 | 6.9% | 49 | 7.8% | 49% |
| additional-cause | 94 | 6.4% | 30 | 4.8% | 32% |
| extension | 85 | 5.8% | 28 | 4.5% | 33% |
| specification | 79 | 5.4% | 38 | 6.0% | 48% |
| refused | 11 | 0.7% | 4 | 0.6% | 36% |
| total | 1,472 | | 629 | | 43% |

Conflicts are 13.3% of relations, close to the 12.3% the examine sample
predicted. **76 cross-author conflicts** exist. Conflict is not more
cross-author than other kinds (39% against 43% overall): the map's
disagreements sit as often inside one author's work as between authors.

## Next

The five smoke briefs with the kind-aware corridor: `../2026-09-29-855-smoke-kind/`.
