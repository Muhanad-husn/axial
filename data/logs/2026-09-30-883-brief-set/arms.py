"""#883: the ten cross-book briefs, 3 draws each, on three corridor states, run in
sequence in the runs checkout. The arm is set by moving two files aside:

  A  count order, 1,472 relations: relation kinds and profile relations aside
  B  kind order,  1,472 relations: profile relations aside
  C  kind order,  2,020 relations: both in place (main after #880)

Both files are restored in `finally`, whatever happens. Resumable: a sweep
dir that already holds a (brief, draw) skips it."""

import subprocess
import sys
from pathlib import Path

ROOT = Path("D:/axial-runs")
PROFILE = ROOT / "data/map/9b796b3a6312b329/profile_relations.jsonl"
KINDS = ROOT / "data/vocabulary/relation/assignments.jsonl"
WORKLIST = ROOT / "data/logs/2026-09-30-883-brief-set/worklist.txt"
ARMS = {"A": (False, False), "B": (True, False), "C": (True, True)}  # (kinds, profile)


def aside(path: Path) -> Path:
    return path.with_name(path.name + ".883-aside")


def place(path: Path, wanted: bool) -> None:
    if wanted and not path.exists():
        aside(path).rename(path)
    if not wanted and path.exists():
        path.rename(aside(path))


arms = sys.argv[1:] or list(ARMS)
try:
    for arm in arms:
        kinds, profile = ARMS[arm]
        place(KINDS, kinds)
        place(PROFILE, profile)
        print(f"== arm {arm}: kinds={KINDS.exists()} profile={PROFILE.exists()}", flush=True)
        rc = subprocess.call(
            [sys.executable, "-m", "axial.cli", "brief", "sweep", str(WORKLIST),
             "--draws", "3", "--sweep-dir", f"data/runs/883-arm-{arm}",
             "--arm", "map", "--workers", "3"],
            cwd=ROOT,
        )
        print(f"== arm {arm}: exit {rc}", flush=True)
        if rc != 0:
            sys.exit(rc)
finally:
    place(KINDS, True)
    place(PROFILE, True)
    print(f"== restored: kinds={KINDS.exists()} profile={PROFILE.exists()}", flush=True)
