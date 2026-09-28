# Run: 853 materialize (runs checkout)

The #853 acceptance check that `axial names materialize` on the current pin
writes no `names/` directory. Run in the separate runs checkout `D:/axial-runs`
(main at `959f736`) over a robocopy of the production data taken 2026-09-29
00:07 (113,164 files, 0 failed).

## Command

```
AEO_DATA_ROOT=D:/axial-runs/data  (cwd D:/axial-runs)
python data/logs/2026-09-29-853-materialize/watch_run.py \
  .venv/Scripts/axial.exe names materialize
```

Detached with `Start-Process`; `watch_run.py` samples the process tree's
memory every 2s into `mem.jsonl`. Zero model calls, zero cost.

## Before the run

`data/vault/names/` (47,584 name pages) was deleted from the copy first.
`du -sh data/vault`: **299 MB before, 178 MB after** (121 MB; the issue
expected about 130 MB). `data/vault/names.jsonl` (6.2 MB, the retired door
index) is still on disk; nothing writes or reads it now.

## Result

Exit 0 in 158.5s, peak private memory **819 MB**. No `names/` directory
written.

| store table | 2026-08-06 build | this run |
|---|---:|---:|
| sources | 35 | 35 |
| notes | 6,842 | 6,842 |
| names | 47,584 | 47,584 |
| note_names | 137,276 | 137,276 |
| note_arguing_against | 13,998 | **13,981** |
| note_citations | 35,975 | 35,975 |
| note_opposed_position | 0 | 0 |

notes written 6,842, skipped 18 (no answer record), artifact notes 986.

**The 17-row drop in `note_arguing_against` is not #853.** The pre-#853 code
(`aea4714`, a side worktree, `old_store.py` here) builds the store over the
same inputs to **13,981** too. The inputs moved after the 2026-08-06 build;
the code change did not.

## The first attempt was killed

The first launch (a Claude Code background shell) was stopped by Claude
Code's low-memory reaper with an empty console log; nothing on disk had been
touched. The re-run shows materialize itself flat at ~550 MB private for most
of the run, 819 MB peak. The machine sat at 78% of 16 GB used before it
started (three Claude sessions ~1.9 GB, VS Code ~1.4 GB, browsers, Word), so
the reaper fired on system pressure, not on this command. Detaching with
`Start-Process` puts a run outside the reaper's reach.
