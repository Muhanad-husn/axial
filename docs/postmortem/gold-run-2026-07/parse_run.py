"""Forensic parser for the 2026-07 gold ingestion run logs (issue #115, task 1).

Parses data/gold/ingest.w*.log START/END blocks into per-source attempt
records, classifies every fatal error line, and emits markdown tables.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

LOGDIR = Path(sys.argv[1] if len(sys.argv) > 1 else ".")

START_RE = re.compile(r"^=== (?P<src>\S+) START (?P<ts>\S+) ===$")
END_RE = re.compile(
    r"^=== (?P<src>\S+) END intake=(?P<intake>\w+) extract=(?P<extract>\w+) "
    r"envelope=(?P<envelope>\w+) vault=(?P<vault>\w+) notes=(?P<notes>\d+) "
    r"(?P<secs>\d+)s ===$"
)

ERROR_CLASSES = [
    ("content_filter", re.compile(r"finish_reason='content_filter'")),
    ("truncation_length", re.compile(r"finish_reason='length'")),
    ("empty_completion", re.compile(r"empty completion")),
    ("wallclock_deadline", re.compile(r"wall-clock|deadline", re.I)),
    ("invalid_json", re.compile(r"not valid JSON|Expecting|Invalid control|delimiter")),
    (
        "transport",
        re.compile(r"WinError|connection|Connection|timed out|ReadTimeout|RemoteProtocolError"),
    ),
    ("envelope_validation", re.compile(r"envelope field")),
    ("tag_vocab", re.compile(r"not in the schema|out-of-vocab|axis value")),
    ("http_status", re.compile(r"status code|HTTPStatusError|429|5\d\d ")),
]


def classify(line: str) -> str:
    for name, rx in ERROR_CLASSES:
        if rx.search(line):
            return name
    return "other"


attempts = []  # dicts: worker, src, ts, statuses..., notes, secs, errors[]
for logfile in sorted(LOGDIR.glob("ingest.w*.log")):
    worker = logfile.stem.split(".")[-1]
    cur = None
    for raw in logfile.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        m = START_RE.match(line)
        if m:
            if cur is not None:
                cur["unterminated"] = True
                attempts.append(cur)
            cur = {
                "worker": worker,
                "src": m["src"],
                "ts": m["ts"],
                "errors": [],
                "unterminated": False,
                "intake": "?",
                "extract": "?",
                "envelope": "?",
                "vault": "?",
                "notes": 0,
                "secs": 0,
            }
            continue
        m = END_RE.match(line)
        if m and cur is not None:
            if m["src"] != cur["src"]:
                cur["errors"].append(f"MISMATCHED END: {line}")
            cur.update(
                intake=m["intake"],
                extract=m["extract"],
                envelope=m["envelope"],
                vault=m["vault"],
                notes=int(m["notes"]),
                secs=int(m["secs"]),
            )
            attempts.append(cur)
            cur = None
            continue
        if cur is not None and line.startswith("error:"):
            cur["errors"].append(line[len("error:") :].strip())
    if cur is not None:
        cur["unterminated"] = True
        attempts.append(cur)

# ---- aggregate per source ----
per_src: dict[str, dict] = defaultdict(
    lambda: {
        "attempts": 0,
        "ok": 0,
        "fail": 0,
        "unterminated": 0,
        "secs": 0,
        "notes_best": 0,
        "err_classes": defaultdict(int),
        "err_lines": [],
        "workers": set(),
    }
)
for a in attempts:
    s = per_src[a["src"]]
    s["attempts"] += 1
    s["secs"] += a["secs"]
    s["workers"].add(a["worker"])
    if a["unterminated"]:
        s["unterminated"] += 1
    elif a["vault"] == "OK":
        s["ok"] += 1
        s["notes_best"] = max(s["notes_best"], a["notes"])
    else:
        s["fail"] += 1
    for e in a["errors"]:
        s["err_classes"][classify(e)] += 1
        s["err_lines"].append((a["worker"], a["ts"], e))

# ---- output ----
print(f"total attempt blocks: {len(attempts)}  sources: {len(per_src)}\n")

print("## Per-source attempt table\n")
print(
    "| source | attempts | vault OK | vault FAIL | unterminated | total h | best notes | fatal error classes |"
)
print("|---|---|---|---|---|---|---|---|")
for src in sorted(per_src, key=lambda s: -per_src[s]["secs"]):
    s = per_src[src]
    ec = ", ".join(f"{k}x{v}" if v > 1 else k for k, v in sorted(s["err_classes"].items())) or "-"
    landed = "OK" if s["ok"] else ("?" if s["unterminated"] and not s["fail"] else "FAIL")
    print(
        f"| {src} | {s['attempts']} | {s['ok']} | {s['fail']} | {s['unterminated']} | {s['secs'] / 3600:.1f} | {s['notes_best']} | {ec} |"
    )

print("\n## Fatal error class histogram (run-wide)\n")
hist: dict[str, int] = defaultdict(int)
for s in per_src.values():
    for k, v in s["err_classes"].items():
        hist[k] += v
print("| class | fatal events |")
print("|---|---|")
for k, v in sorted(hist.items(), key=lambda kv: -kv[1]):
    print(f"| {k} | {v} |")

print("\n## All fatal error lines (worker, source-start ts, message)\n")
for src in sorted(per_src):
    for w, ts, e in per_src[src]["err_lines"]:
        print(f"- `{src}` [{w} @ {ts}]: {e}")

print("\n## Unterminated blocks (source attempt started, no END line — kill/hang)\n")
for a in attempts:
    if a["unterminated"]:
        print(f"- `{a['src']}` [{a['worker']} @ {a['ts']}]")

print("\n## Wasted-work summary\n")
tot_h = sum(s["secs"] for s in per_src.values()) / 3600
ok_first_try = sum(1 for s in per_src.values() if s["attempts"] == 1 and s["ok"] == 1)
redundant = sum((s["attempts"] - 1) for s in per_src.values() if s["ok"])
print(
    f"- total logged compute: {tot_h:.1f} h across {len(attempts)} attempts / {len(per_src)} sources"
)
print(f"- sources landing first-try: {ok_first_try}/{len(per_src)}")
print(f"- extra attempts beyond the first for eventually-OK sources: {redundant}")
