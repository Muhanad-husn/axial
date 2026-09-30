# 2026-09-30 — #881: synthesis told which passages contest which

**Reading: no measurable effect.** The conflict list reached the prompt (96 of
100 listed conflicts had both ends composed), and answers cited both ends of a
conflict at the same rate as before: 8% of shown pairs, against 8% (C) and 12%
(B) in #879's arms, which never saw a list. Sources cited, grounding and cost
are unchanged.

## Command

```
cd D:/axial-runs
python data/logs/2026-09-30-881-conflicts-arm-C/watch_run.py \
  D:/axial-881/.venv/Scripts/python.exe -m axial.cli brief sweep \
  data/logs/2026-09-30-881-conflicts-arm-C/worklist.txt --draws 3 \
  --sweep-dir D:/axial-runs/data/runs/881-arm-C --arm map --workers 3
python analyze.py > analysis.txt; python composed.py; D:/axial-881/.venv/Scripts/python.exe pairs.py
```

Branch `feat/881-synthesis-sees-conflicts` at `b29fa20`, run from the runs
checkout with #879's arm C state (kind order, 2,020 relations). This is arm D
below; arms A/B/C are #879's records, reused unchanged.

## Cost and run

$0.79 by key usage, 1,356s wall clock, cap $2. 14 of 15 draws OK. S-04
draw 0 failed on a door response that was not valid JSON.

## Result

Conflict pairs: a conflict relation with both positions in the composed
prompt. For B and C they are recomputed offline with the branch's own
`contested_pairs` (`pairs.py`).

| arm | answers | conflict pairs in prompt | both ends cited | one end cited | answers with a both-ends pair |
|---|---:|---:|---:|---:|---:|
| B kind order, 1,472 | 15 | 64 | 8 (12%) | 8 | 8 |
| C + #858, 2,020 | 13 | 76 | 6 (8%) | 21 | 6 |
| D = C + conflict list | 14 | 100 | 8 (8%) | 21 | 8 |

Per answer, over all draws (`analysis.txt`):

| measure | A | B | C | D |
|---|---:|---:|---:|---:|
| sources cited | 3.33 | 3.60 | 3.54 | 3.86 |
| corridor positions cited | 3.67 | 4.33 | 5.00 | 6.57 |
| conflict-joined corridor positions cited | 0.13 | 0.27 | 0.00 | 0.36 |
| cost | $0.061 | $0.057 | $0.056 | $0.049 |

- The corridor-position conflict figure rises from 0.00 to 0.36, inside the draw spread on every brief (5 of 66 positions cited against 0 of 48).
- #879 read "conflicts go uncited" off corridor positions only. Counting pairs among all composed passages, answers already cited both sides of a conflict in about half of them before the list existed.
- Corridor positions cited rise to 6.57, clear of arm A's spread on 3 briefs. The corridor itself was larger in this run (38.0 against 33.5 in C), and the list does not touch the corridor. One run cannot separate the list's effect from the door's variance.

## Next

The founder decides #881's PR. The list costs nothing measurable and moves nothing measurable.
