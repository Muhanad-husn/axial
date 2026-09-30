# 2026-09-30 — #878: the vault reads the profile relations

**Reading: the vault's position pages now carry all 2,020 relations (1,472 +
548 from #858), every one a link on both endpoints, and isolated positions
fall 432 to 321. Zero model calls.**

## Command

```
cd D:/axial-runs
D:/axial-878/.venv/Scripts/python.exe data/logs/2026-09-30-878-position-pages/check.py
```

Branch `feat/878-profile-relations-downstream` at `c1f7363`, run with the
worktree's venv from the runs checkout, over map `9b796b3a6312b329` and the
runs checkout's vocabulary. `check.py` calls `write_position_pages` (the
position-page step of `axial names materialize`) and counts links.

## Result

| | before (#854) | after |
|---|---:|---:|
| relations on pages | 1,472 | 2,020 |
| position pages | 1,937 | 1,937 |
| isolated positions | 432 | 321 |
| relations missing a link on either end | 0 | 0 |
| relation lines carrying a kind | 2,922 of 2,944 | 4,012 of 4,040 |

- 564 profile relations minus 16 pairs `relations.jsonl` already holds gives
  the 548 added; the loader keeps the `relations.jsonl` row for those 16.
- The 28 kindless lines are the 14 relations the kind build refused, on both
  ends.
- Only the position-page step ran; prose notes and `notes.db` were not
  rebuilt, as they do not read relations.

## Next

#879: the answer measurement, three arms at three draws, on the founder's go.
