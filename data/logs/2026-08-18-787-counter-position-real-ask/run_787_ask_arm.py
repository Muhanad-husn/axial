"""One arm of the #787 slice-01 measurement, run against the input that
actually produced the defect.

Kept here rather than at the repo root because it is the method behind this
run's `summary.md`, and slice 02's plan points at it as the shape to reuse
for any measurement of a judged property of the writing.

The first attempt measured nine curated dev paper briefs and returned a null:
`shape.band` was `strong` on 35 of 35 drafts across both arms (see
`../2026-08-18-787-counter-position-steelman/summary.md`). The defect this
slice exists to fix was never in those briefs. It is in
`data/papers/ca17d6077c1a7f5e.json`, drafted end to end by `axial ask` from a
real analyst question, which came back `shape: weak` with a named
counter-position defect.

So this driver asks that exact question, repeatedly, on whatever code is
checked out. One `run.jsonl` line per draw, fsynced, and every persisted paper
record copied aside before the next draw can overwrite it -- two runs of this
were killed mid-arm and neither lost anything already bought.

Two things to fix before reusing it:

- It captures each ask's output only on completion, so a draw in flight shows
  no progress at all and a watcher has to fall back to process CPU.
- It restarts from draw 1, and the journal appends, so a resumed arm re-buys
  every draw it already paid for.

Run it detached with `Start-Process`, not through a foreground shell: an ask is
about 14 minutes and a three-draw arm is most of an hour.

Usage: uv run python run_787_ask_arm.py <arm-name> <draws>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RUN_DIR = Path("data/logs/2026-08-18-787-counter-position-real-ask")

# Verbatim from `data/logs/2026-08-18-784-cost-per-ask/run.ps1` -- the run
# whose paper carried the defect. Changing either string measures a
# different question.
CASE = "Syria, 1920-2024 -- state formation and who the arrangement favoured"
QUESTION = "Did the mandate-era institutions or the Baath decide who held power in Syria after 2011?"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def journal(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def counter_position_sections(record: dict) -> list[str]:
    plan = record.get("plan") or {}
    return [
        str(section.get("section_id"))
        for section in (plan.get("sections") or [])
        if section.get("role") == "counter-position"
    ]


def main() -> int:
    arm, draws = sys.argv[1], int(sys.argv[2])
    records_dir = RUN_DIR / f"{arm}-records"
    records_dir.mkdir(parents=True, exist_ok=True)
    journal_path = RUN_DIR / "run.jsonl"
    console = RUN_DIR / f"{arm}-console.log"

    head, branch = git("rev-parse", "HEAD"), git("rev-parse", "--abbrev-ref", "HEAD")
    print(f"arm={arm} draws={draws} branch={branch} head={head[:12]}", flush=True)

    for draw in range(1, draws + 1):
        started = time.time()
        label = f"{arm}/draw{draw}"
        print(f"--- {label}", flush=True)
        # One-shot: question and --case both supplied, so #790's fix means
        # the intake fork is recorded unanswered rather than blocking on a
        # stdin this process does not have.
        proc = subprocess.run(
            ["uv", "run", "axial", "ask", QUESTION, "--case", CASE],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with console.open("a", encoding="utf-8") as handle:
            handle.write(f"\n===== {label} (exit {proc.returncode})\n")
            handle.write(proc.stdout or "")
            handle.write(proc.stderr or "")

        entry: dict = {
            "arm": arm,
            "draw": draw,
            "branch": branch,
            "head": head,
            "exit_code": proc.returncode,
            "elapsed": round(time.time() - started, 1),
        }

        papers = sorted(Path("data/papers").glob("*.json"), key=lambda p: p.stat().st_mtime)
        if proc.returncode == 0 and papers:
            latest = papers[-1]
            record = json.loads(latest.read_text(encoding="utf-8"))
            shutil.copy(latest, records_dir / f"draw{draw}.json")
            shape = record.get("shape") or {}
            cp_sections = counter_position_sections(record)
            defect_sections = {
                str(defect.get("section_id")) for defect in (shape.get("defects") or [])
            }
            entry.update(
                {
                    "paper_brief_id": record.get("paper_brief_id"),
                    "band": shape.get("band"),
                    "defect_count": len(shape.get("defects") or []),
                    "defect_sections": sorted(defect_sections),
                    "counter_position_sections": cp_sections,
                    "counter_position_flagged": bool(defect_sections & set(cp_sections)),
                    "defect_notes": [
                        defect.get("note") for defect in (shape.get("defects") or [])
                    ],
                    "section_count": len((record.get("plan") or {}).get("sections") or []),
                }
            )
        else:
            entry["error"] = (proc.stderr or "")[-2000:]

        journal(journal_path, entry)
        print(
            f"    band={entry.get('band')} "
            f"cp_flagged={entry.get('counter_position_flagged')} "
            f"defects={entry.get('defect_count')} {entry['elapsed']}s",
            flush=True,
        )

    print(f"arm {arm} complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
