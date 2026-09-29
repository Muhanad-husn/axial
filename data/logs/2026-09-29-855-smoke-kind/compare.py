"""Compare the #855 kind-corridor smoke run against the #853 count-order run
(same five briefs, one draw each): cost, gates, grounding, sources cited, and
the corridor's order and kind counts as the record carries them."""

import json
from pathlib import Path

RUNS = {
    "853 count order": "D:/axial-runs/data/runs/853-smoke-map",
    "855 kind order": "D:/axial-runs/data/runs/855-smoke-kind",
}

for label, root in RUNS.items():
    summary = json.loads(Path(root, "summary.json").read_text(encoding="utf-8"))
    print(f"\n== {label}  commit={summary.get('commit', '')[:7]}  ok={summary['ok_count']}")
    total = 0.0
    for b in summary["briefs"]:
        cost = b["cost"]["total_usd"] or 0.0
        total += cost
        gates = b["gate_reports"]
        grounding = next(m["value"] for m in gates["grounding"]["metrics"])
        verdicts = "".join("P" if g["passed"] else "F" for _, g in sorted(gates.items()))
        for d in b["draws"]:
            rec = json.loads(Path(d["record_path"]).read_text(encoding="utf-8"))
            usage = rec.get("source_usage") or {}
            kinds = (rec.get("map_retrieval") or {}).get("relation_kinds") or {}
            corridor = kinds.get("order", "count (no kinds)")
            counts = " ".join(f"{k}={n}" for k, n in (kinds.get("kind_counts") or {}).items())
            print(f"{b['brief_stem']}  ${cost:.4f}  gates={verdicts}  grounding={grounding:.3f}"
                  f"  sources={len(usage.get('sources') or [])}  corridor={corridor}"
                  f" {counts} unassigned={kinds.get('unassigned', '-')}")
    print(f"total ${total:.4f}")
