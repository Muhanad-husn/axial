# Run: 855 smoke briefs, kind-aware corridor (runs checkout)

#855 acceptance: the smoke set's five briefs on the map arm, with relation kinds
built (`../2026-09-29-855-relation-build/`), so the corridor runs in kind order
(conflicts first). Compared against the #853 run on the same briefs, which ran
in count order because no relation build existed then.

## Command

```
AXIAL_SECRETS_PATH=D:/axial-runs/secrets/secrets.toml
(cwd D:/axial-runs, detached with Start-Process, memory sampled by watch_run.py)
axial brief sweep data/logs/2026-09-29-855-smoke-kind/worklist.txt \
  --draws 1 --sweep-dir data/runs/855-smoke-kind --arm map --workers 1
```

Exit 0 in 1,419s, peak private memory 2.65 GB. 5/5 OK, **$0.330**.
`compare.py` prints the table below.

## Result

Gates in order attribution-fidelity, calibration, grounding, synthesis-quality.

| brief | 853 count order | 855 kind order | corridor kinds (855) |
|---|---|---|---|
| S-01 | PPPP, 4 sources, $0.033 | PPPP, 5 sources, $0.046 | conflict 7, support 7, qualification 5, extension 2, illustration 2, mechanism 1, specification 1 |
| S-02 | PPPP, 7 sources, $0.068 | PPPP, 6 sources, $0.076 | qualification 4, conflict 1, extension 1, mechanism 1, support 1 |
| S-03 | PPPP, 4 sources, $0.045 | PPPP, 9 sources, $0.092 | qualification 8, support 8, conflict 5, grounding 4, mechanism 4, additional-cause 3, extension 3, illustration 1, specification 1 |
| S-04 | PPPP, 1 source, $0.055 | PPPP, 1 source, $0.055 | qualification 9, conflict 8, support 8, extension 5, illustration 5, grounding 4, additional-cause 4, mechanism 3, specification 1 |
| S-05 | PFPP, 1 source, $0.037 | PFPP, 1 source, $0.061 | qualification 9, illustration 7, grounding 5, conflict 4, mechanism 4, support 4, extension 3, additional-cause 1, specification 1; 1 unassigned |

Every record carries `corridor: order=kind` with the scheme version and kind
counts, which is the acceptance line. Grounding 1.000 on all five in both runs.
S-05 fails calibration in both, as it did in #809 and #853.

**Cost rose $0.237 to $0.330, not because of the corridor.** The corridor makes
no model calls. The rise is output length on two briefs: S-03's counter-position
emitted 11,408 completion tokens ($0.058) and S-02's decomposition 15,355
($0.020). One draw each, so that is noise until repeated.

Sources cited rose on S-01 and S-03 (4 to 5, 4 to 9) and fell by one on S-02.
One draw per arm, and the smoke gate is saturated, so this does not show the
kind order is better; it shows the order runs and the gates hold.

## Do conflict positions reach the answer?

`cited.py` classifies each corridor position by whether a relation joining it
to a landed position is a conflict (kinds from the build, for both runs), then
counts how many put a passage into assembly and into a cited claim.

| run | conflict: corridor / assembled / cited | other: corridor / assembled / cited |
|---|---:|---:|
| 853 count order | 10 / 10 / 2 | 106 / 106 / 15 |
| 855 kind order | 25 / 25 / 5 | 107 / 107 / 22 |

Every corridor position is assembled in both runs, so the order never decides
whether a position gets in. Conflict positions are cited at the same rate
either way (20%), and at about the rate of the rest. The 855 corridors hold
more conflicts (25 against 10) because each run's decomposition landed on
different positions, not because of the order. The kind order is harmless and
reported, but on these five briefs it changes nothing an answer shows.

## Next

Import both run directories and `data/vocabulary/relation/` into the live
checkout (founder-run robocopy).
