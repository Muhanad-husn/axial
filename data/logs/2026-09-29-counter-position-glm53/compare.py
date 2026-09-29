"""Counter-position on glm-5.2 (the #855 kind-order run) against glm-5.3 (this
run), same five briefs, one draw each: latency and tokens from the console log,
cost from the record, and the stance itself written to stances.md for reading
side by side. The two runs' evidence differs (each drew its own decomposition),
so the prompt each model saw is not identical."""

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
RUNS = {
    "glm-5.2": (Path("D:/axial-runs/data/runs/855-smoke-kind"),
                Path("D:/axial-runs/data/logs/2026-09-29-855-smoke-kind/console.log")),
    "glm-5.3": (Path("D:/axial-runs/data/runs/cp-glm53"), HERE / "console.log"),
}
CALL = re.compile(r"pass=counter_position_generate model=(\S+) outcome=(\S+).*?elapsed=([\d.]+)s"
                  r"(?:.*?prompt_tokens=(\d+) completion_tokens=(\d+))?.*?run_id=(S-0\d)")

stances = {}
for label, (root, console) in RUNS.items():
    calls = {}
    for m in CALL.finditer(console.read_text(encoding="utf-8", errors="replace")):
        calls.setdefault(m[6], []).append(m)
    print(f"\n== {label}")
    total = 0.0
    for path in sorted(root.glob("analyses/S-0*/draw0/*.json")):
        brief = path.parts[-3]
        rec = json.loads(path.read_text(encoding="utf-8"))
        usd = next((p.get("usd") for name, p in (rec["cost"].get("by_pass") or {}).items()
                    if name == "counter_position_generate"), None)
        total += usd or 0.0
        cp = rec["counter_position"] or {}
        tries = calls.get(brief, [])
        last = tries[-1] if tries else None
        print(f"{brief}  calls={len(tries)} outcomes={','.join(t[2] for t in tries)}"
              f"  elapsed={last[3] if last else '-'}s  prompt={last[4] if last else '-'}"
              f"  completion={last[5] if last else '-'}  usd={usd}"
              f"  present={cp.get('present')}  grounds={len(cp.get('grounds') or [])}"
              f"  words={len((cp.get('stance') or '').split())}")
        stances.setdefault(brief, {})[label] = cp
    print(f"total counter-position usd {total:.4f}")

out = ["# Counter-positions, glm-5.2 against glm-5.3\n"]
for brief, by in sorted(stances.items()):
    out.append(f"\n## {brief}\n")
    for label, cp in by.items():
        out.append(f"\n**{label}** (present={cp.get('present')}, grounds={len(cp.get('grounds') or [])})\n\n"
                   f"{cp.get('stance') or cp.get('one_sided_reason') or '-'}\n")
(HERE / "stances.md").write_text("".join(out), encoding="utf-8")
