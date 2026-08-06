"""smoke-v6 -> smoke-v7: the per-brief before/after table.

Reads the run report each sweep wrote for draw 0 and prints one row per brief.
Before is the preserved copy under before/ (smoke-v6 + eval-v2), after is the
live sweep dir. Join is by case_id, never by path shape.
"""

import json
import sys
from pathlib import Path

LOG = Path(__file__).resolve().parent
ROOT = LOG.parents[2]

PAIRS = [
    ("smoke", LOG / "before/smoke-v6", ROOT / "data/runs/smoke-v7"),
    ("eval", LOG / "before/eval-v2", ROOT / "data/runs/eval-v3"),
]


def reports(sweep_dir: Path) -> dict[str, dict]:
    out = {}
    for path in sweep_dir.glob("analyses/*/draw0/runs/*.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        out[report["case_id"]] = report
    return out


def row(report: dict) -> dict:
    hit = report["accuracy"]["retrieval_hit"]
    ev = report["operational"]["evidence"]
    traj = report["operational"]["trajectory"]
    rq = report["response_quality"]
    usd = sum(p.get("usd", 0.0) or 0.0 for p in report["operational"]["cost"]["by_pass"].values())
    return {
        "pin": report.get("corpus_pin", "?"),
        "legs": f"{hit.get('numerator', '?')}/{hit.get('denominator', '?')}",
        "missed": ", ".join(hit.get("missed_legs") or []) or "-",
        "assembled": ev.get("assembled_count"),
        "composed": ev.get("composed_count"),
        "cited": rq["retrieval_precision"]["cited_note_count"],
        "sources": rq["sources_cited"],
        "commentary": rq["commentary_mix"].get("run_share", rq["commentary_mix"].get("share")),
        "claims": rq["answer_size"]["claim_count"],
        "steps": traj.get("steps"),
        "tools": traj.get("evidence_tool_calls"),
        "usd": usd,
    }


def fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


for label, before_dir, after_dir in PAIRS:
    before, after = reports(before_dir), reports(after_dir)
    cases = sorted(set(before) | set(after))
    if not cases:
        print(f"\n## {label}: nothing to compare yet", file=sys.stderr)
        continue
    cols = ["legs", "assembled", "composed", "cited", "sources", "claims", "steps", "tools", "usd"]
    print(f"\n## {label}  (before = {before_dir.name}, after = {after_dir.name})\n")
    print("| brief | " + " | ".join(f"{c} b->a" for c in cols) + " |")
    print("|" + "---|" * (len(cols) + 1))
    for case in cases:
        b = row(before[case]) if case in before else {}
        a = row(after[case]) if case in after else {}
        cells = [f"{fmt(b.get(c))} -> {fmt(a.get(c))}" for c in cols]
        print(f"| {case} | " + " | ".join(cells) + " |")
    for case in cases:
        if case in after:
            print(f"\n{case} missed legs after: {row(after[case])['missed']}", file=sys.stderr)
            print(f"{case} pin: {row(after[case])['pin']}", file=sys.stderr)
