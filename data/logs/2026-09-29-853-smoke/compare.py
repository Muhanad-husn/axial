"""Compare the #853 smoke run against #809's map arm (3 draws, pre-#853 code):
cost, latency, sources cited, gate verdicts and the grounding value, and
whether each record still carries its source-usage disclosure."""

import json
from pathlib import Path

RUNS = {"809 map (3 draws)": "data/runs/809-arm-map", "853 map (1 draw)": "data/runs/853-smoke-map"}

for label, root in RUNS.items():
    summary = json.loads(Path(root, "summary.json").read_text(encoding="utf-8"))
    print(f"\n== {label}  commit={summary.get('commit', '')[:7]}  ok={summary['ok_count']}"
          f" fail={summary['fail_count']}")
    total = 0.0
    for b in summary["briefs"]:
        cost = b["cost"]["total_usd"] or 0.0
        total += cost
        gates = b["gate_reports"]
        grounding = next(m["value"] for m in gates["grounding"]["metrics"])
        verdicts = "".join("P" if g["passed"] else "F" for _, g in sorted(gates.items()))
        disclosures = []
        for d in b["draws"]:
            rec = json.loads(Path(d["record_path"]).read_text(encoding="utf-8"))
            usage = rec.get("source_usage") or {}
            disclosures.append(
                f"{len(usage.get('sources') or [])}src/"
                f"{'denom' if usage.get('denominator_by_name') else '-'}"
            )
        print(
            f"{b['brief_stem']}  ${cost:.4f}"
            f"  lat={[round(d['latency_seconds'] or 0) for d in b['draws']]}"
            f"  cited={[d['distinct_sources_cited'] for d in b['draws']]}"
            f"  grounding={grounding:.3f}  gates(attr,cal,grd,syn)={verdicts}"
            f"  usage={disclosures}"
        )
    print(f"total ${total:.4f}")
