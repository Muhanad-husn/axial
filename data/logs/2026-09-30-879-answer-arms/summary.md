# 2026-09-30 — #879: what DEC-75 did to answers, three arms at three draws

**Reading: answers are no broader. They cite as many sources as before (3.3 to
3.5 per answer, inside the draw spread on every brief). The #858 relations do
reach answers: on two of five briefs, 3 to 5.5 cited positions per answer
arrive only through them. The kind order (#855) moved nothing measurable, and
conflicts are not cited more often: 0.13 per answer before, 0.27 with kind
order, 0 with the new relations.**

## Command

```
cd D:/axial-runs
python data/logs/2026-09-30-879-answer-arms/watch_run.py \
  .venv/Scripts/python.exe data/logs/2026-09-30-879-answer-arms/arms.py
# arms.py, per arm:
axial brief sweep worklist.txt --draws 3 --sweep-dir data/runs/879-arm-<A|B|C> --arm map --workers 3
python data/logs/2026-09-30-879-answer-arms/analyze.py > analysis.txt
```

Main at `6c84095` (#880 merged), detached under `watch_run.py` with a $5 cap.
The five smoke briefs, 3 draws each, per arm. The arm is set by moving two
files aside (`arms.py`) and both were restored at the end:

| arm | corridor order | relations |
|---|---|---|
| A (before) | count | 1,472 |
| B | kind (#855) | 1,472 |
| C (after) | kind | 2,020 (+548 from #858) |

## Cost and run

$2.92 by key usage, 6,570s wall clock, peak process-tree memory 2.9 GB.
Per answer: A $0.061, B $0.057, C $0.056. There was no cost change.

43 of 45 draws are OK. Both failures are in arm C:
- S-02 draw 0: a claim cited `[c can]`, which is not a chunk id. The fail-closed citation check refused it.
- S-04 draw 2: the door call hit the 600s deadline on all 3 attempts.

Three more 600s deadlines on S-04 in arm B succeeded on retry. Arm C's S-02 and
S-04 therefore have 2 draws each.

## Result

Mean per answer over all draws (`analysis.txt` has every brief with its draw
range). "Separated" counts briefs where the arm's draw range sits wholly above
(+) or below (−) arm A's.

| measure | A before | B kind order | C + #858 | separated from A (B / C) |
|---|---:|---:|---:|---|
| sources cited | 3.33 | 3.60 | 3.54 | 0 / 0 |
| corridor positions cited | 3.67 | 4.33 | 5.00 | 0 / +1 (S-01) |
| … joined by conflict | 0.13 | 0.27 | 0.00 | 0 / 0 |
| … joined by qualification | 1.33 | 1.53 | 1.92 | 0 / +1 |
| … joined by support | 0.47 | 0.73 | 0.62 | 0 / 0 |
| cited chunks from conflict positions | 0.33 | 0.27 | 0.00 | 0 / 0 |
| cited positions, cross-author link | 0.93 | 0.53 | 1.31 | −1 / 0 |
| cited positions reached only via #858 | 0 | 0 | 1.54 | — / +2 |
| corridor size | 24.7 | 22.5 | 33.5 | 0 / +2 |
| claims | 10.5 | 10.6 | 10.8 | −1 / 0 |

- **Where #858 lands:** S-01 cites 3.0 positions per answer that only a profile relation reaches (range 2-4), and S-02 cites 5.5 (5-6). S-03, S-04 and S-05 cite none. On S-01 the cited corridor positions rise from 1.7 [0-3] to 5.0 [4-6], the one clean separation.
- **Why sources do not move:** S-04 and S-05 cite one or two books in every arm; their answers come from one book's own positions. Only three briefs have room to broaden.
- **Conflicts reach the evidence but not the answer.** Every conflict-joined corridor position puts a passage into assembly in both kind-order arms: 42 of 42 in B, 48 of 48 in C. Answers then cite almost none of them (0.27 and 0.00 per answer). The loss is after assembly: either in composition, which cuts the 90 assembled chunks to about 57 and whose ids the record does not keep, or in synthesis.
- **Gates:** they flip across arms without a pattern: S-02 A FPPF then PPPP, S-04 B FFPP, S-03 C now passes synthesis. Grounding passes on every brief in every arm. There is no regression.

## Next

Recorded on #879 with the plan report at `docs/reports/dec-75-outcome.md`.
Open question for the founder: conflicting positions reach assembly and go
uncited. Finding where they drop, composition or synthesis, needs the composed
chunk ids in the record, which is a small change. What to do about it is a
design call.
