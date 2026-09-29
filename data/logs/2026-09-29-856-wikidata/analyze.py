"""Offline analysis of the #856 pass: canary, per-kind rates, and a what-if
acceptance rule measured on the same cached responses (zero API calls)."""

import collections
import json
from pathlib import Path

N = Path("D:/axial-runs/data/names")
LOG = Path("D:/axial-runs/data/logs/2026-09-29-856-wikidata")
report = json.loads((N / "wikidata/report.json").read_text(encoding="utf-8"))
res = [json.loads(line) for line in (N / "wikidata/resolutions.jsonl").read_text(encoding="utf-8").splitlines()]
cache = {}
for line in (N / "wikidata/responses.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    cache[(r["query"], r["type"])] = r["result"]

from axial.wikidata import type_for_kind  # noqa: E402

out = []
p = out.append
p(f"band {report['band']}  resolved {report['resolved']} ({report['resolution_rate']:.1%})")
p(f"tested {report['tested']}  agrees {report['agrees']} ({(report['agreement_rate'] or 0):.1%})")
p(f"merged_apart {len(report['merged_apart'])}  kept_apart {len(report['kept_apart'])}")

p("\n## canary")
for r in res:
    if "ba'th" in r["canonical"].lower() or "baath" in r["canonical"].lower():
        p(f"  {r['canonical']}: {r['qid']} {r['verdict']} {r['surface_qids']}")

p("\n## by kind (match flag)")
by = collections.defaultdict(lambda: [0, 0])
for r in res:
    by[r["kind"]][0] += 1
    by[r["kind"]][1] += bool(r["qid"])
for k, (n, ok) in sorted(by.items(), key=lambda x: -x[1][0]):
    p(f"  {k}: {ok}/{n} ({ok / n:.0%})")

# What-if: canonical's top candidate when it scores 100 (ties allowed).
p("\n## what-if: top candidate of the canonical at score 100")
top_ok = 0
samples = []
for r in res:
    cands = cache[(r["canonical"], type_for_kind(r["kind"]))]
    if cands and cands[0]["score"] >= 100:
        top_ok += 1
        if not r["qid"]:
            samples.append((r["canonical"], r["kind"], cands[0]["id"], cands[0]["name"]))
        elif r["qid"] != cands[0]["id"]:
            samples.append((r["canonical"], r["kind"], f"match={r['qid']} top={cands[0]['id']}", cands[0]["name"]))
p(f"  would resolve {top_ok}/{len(res)} ({top_ok / len(res):.1%}); {len(samples)} beyond the match flag")
p("  every 25th of those, for audit:")
for s in samples[::25]:
    p(f"    {s}")

p("\n## merged_apart (first 30)")
for m in report["merged_apart"][:30]:
    p(f"  {m['canonical']}: {m['surface_qids']}")
p("\n## kept_apart (first 30)")
for k in report["kept_apart"][:30]:
    p(f"  {k['qid']}: {k['canonicals']}")

text = "\n".join(out)
(LOG / "analysis.txt").write_text(text + "\n", encoding="utf-8")
print(text)
