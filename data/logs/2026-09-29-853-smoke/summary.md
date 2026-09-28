# Run: 853 smoke (runs checkout)

The #853 acceptance check: `axial ask` on the five smoke briefs produces records
with the same grounding and source-usage disclosures as before, from `notes.db`
alone. Run in `D:/axial-runs` at main `959f736`, after
`../2026-09-29-853-materialize/` rebuilt the store with no `names/` directory.

## Command

```
AEO_DATA_ROOT=D:/axial-runs/data  AXIAL_SECRETS_PATH=D:/axial-runs/secrets/secrets.toml
(cwd D:/axial-runs, detached with Start-Process, memory sampled by watch_run.py)
axial brief sweep data/logs/2026-09-29-853-smoke/worklist.txt \
  --draws 1 --sweep-dir data/runs/853-smoke-map --arm map --workers 1
```

Worklist: S-01..S-05, the same five #809 swept. Baseline is #809's `map` arm
(`data/runs/809-arm-map`, commit `b18f95b`, 3 draws per brief).

## Result

5 of 5 draws OK, exit 0, 17.6 min wall clock, **$0.2370**. Peak private
memory of the process tree **2,750 MB**. `compare.py` prints the table below.

| brief | 809 cited (3 draws) | 853 cited | 809 grounding | 853 grounding | 809 gates | 853 gates |
|---|---|---:|---:|---:|---|---|
| S-01 | 4, 5, 5 | 4 | 1.000 | 1.000 | PPPP | PPPP |
| S-02 | 9, 6, 9 | 7 | 1.000 | 1.000 | FPPP | PPPP |
| S-03 | 4, 5, 5 | 4 | 1.000 | 1.000 | PPPP | PPPP |
| S-04 | 1, 1, 2 | 1 | 1.000 | 1.000 | PFPP | PPPP |
| S-05 | 1, 2, 2 | 1 | 0.800 | 1.000 | PFFP | PFPP |

Gates in order attribution-fidelity, calibration, grounding, synthesis-quality.
Every source count sits inside #809's own draw range. One draw against three
cannot show a difference smaller than that spread, and the smoke gate is
saturated anyway (#809); this reads as "no regression", not "better".

**S-05 calibration FAIL is pre-existing.** #809 failed it too (0.219); here
0.275, n=12, every medium-band claim held (observed 1.0 against target
0.725), so the band is under-confident, not over.

**S-04 counter-position absent** on this draw, as on all three #809 draws of
S-04.

## Source-usage disclosure: now filled, where it was empty

Every record carries the same four keys as before (`sources`,
`denominator_by_name`, `names_queried`, `weights`). The difference is that the
map-arm records from #809 had `denominator_by_name` and `names_queried`
**empty** (0 entries); these carry 126-142 names each. #853 re-pointed the
imbalance disclosure at `notes.db`'s `concept_sources`, and it now reports on
the map arm, which it never did while it read name pages.

## Cost note

Recorded cost $0.2370 for 5 draws against #809's $0.9919 for 15, the same
summary field in both: $0.047 against $0.066 per draw.
