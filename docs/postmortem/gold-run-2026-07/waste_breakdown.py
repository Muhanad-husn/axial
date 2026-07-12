"""Waste breakdown for the 2026-07 gold run (issue #115): where did 182h go?"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

LOGDIR = Path(sys.argv[1])
START_RE = re.compile(r"^=== (?P<src>\S+) START (?P<ts>\S+) ===$")
END_RE = re.compile(
    r"^=== (?P<src>\S+) END intake=\w+ extract=\w+ envelope=\w+ "
    r"vault=(?P<vault>\w+) notes=(?P<notes>\d+) (?P<secs>\d+)s ===$"
)

attempts = []
for logfile in sorted(LOGDIR.glob("ingest.w*.log")):
    cur_src = None
    for raw in logfile.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        m = START_RE.match(line)
        if m:
            cur_src = m["src"]
            continue
        m = END_RE.match(line)
        if m and cur_src == m["src"]:
            attempts.append((m["src"], m["vault"], int(m["notes"]), int(m["secs"])))
            cur_src = None

first_ok_seen: set[str] = set()
buckets = defaultdict(lambda: [0, 0.0])  # class -> [count, hours]
for src, vault, notes, secs in attempts:
    h = secs / 3600
    if vault == "OK" and notes > 0 and src not in first_ok_seen:
        first_ok_seen.add(src)
        buckets["productive (first OK with notes)"][0] += 1
        buckets["productive (first OK with notes)"][1] += h
    elif vault == "OK":
        buckets["redundant re-run of completed source (OK, 0 new notes)"][0] += 1
        buckets["redundant re-run of completed source (OK, 0 new notes)"][1] += h
    else:
        buckets["failed attempt (vault=FAIL)"][0] += 1
        buckets["failed attempt (vault=FAIL)"][1] += h

print("| bucket | attempts | hours | share of logged compute |")
print("|---|---|---|---|")
total_h = sum(b[1] for b in buckets.values())
for name, (n, h) in sorted(buckets.items(), key=lambda kv: -kv[1][1]):
    print(f"| {name} | {n} | {h:.1f} | {100 * h / total_h:.0f}% |")
print(
    f"| **total (terminated attempts)** | {sum(b[0] for b in buckets.values())} | {total_h:.1f} | 100% |"
)
