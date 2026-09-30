"""#879 follow-up: where conflict-joined positions drop. Zero model calls.

compose_prompt keeps a deterministic PREFIX of the assembled order under the
evidence char budget, and assemble_evidence preserves that order, so the
composed chunks are assembled_chunk_ids[:composed_count] (checked: the
record's assembled_count equals len(assembled_chunk_ids))."""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("D:/axial-runs")
MAP = ROOT / "data/map/9b796b3a6312b329"
pos = {}
for line in (MAP / "positions.jsonl").open(encoding="utf-8"):
    p = json.loads(line)
    pos[p["position_id"]] = set(p["chunk_ids"])

print("arm  group     positions  assembled  composed  cited   first-rank(median, of assembled)")
for arm in "ABC":
    summary = json.loads((ROOT / f"data/runs/879-arm-{arm}/summary.json").read_text(encoding="utf-8"))
    t = defaultdict(lambda: [0, 0, 0, 0, []])
    mismatch = 0
    for b in summary["briefs"]:
        for d in b["draws"]:
            if d["status"] != "OK":
                continue
            r = json.loads((ROOT / d["record_path"]).read_text(encoding="utf-8"))
            m = r["map_retrieval"]
            order = m["assembled_chunk_ids"]
            mismatch += r["evidence"]["assembled_count"] != len(order)
            composed = set(order[: r["evidence"]["composed_count"]])
            rank = {c: i for i, c in enumerate(order)}
            cited = {g["ref_id"] for c in r["claims"] for g in c.get("grounds", []) if g["ref_type"] == "chunk"}
            groups = [("landed", x["position_id"], set()) for x in m["landed"]]
            groups += [("corridor", c["position_id"], set(c.get("kinds") or [])) for c in m["corridor"]]
            for kind, pid, kinds in groups:
                g = kind if kind == "landed" else ("conflict" if "conflict" in kinds else "other-cor")
                chunks = pos[pid]
                row = t[g]
                row[0] += 1
                row[1] += bool(chunks & set(order))
                row[2] += bool(chunks & composed)
                row[3] += bool(chunks & cited)
                ranks = [rank[c] for c in chunks if c in rank]
                if ranks:
                    row[4].append(min(ranks))
    for g, (n, a, c, ci, ranks) in t.items():
        ranks.sort()
        med = ranks[len(ranks) // 2] if ranks else "-"
        print(f"{arm}    {g:9} {n:9} {a:10} {c:9} {ci:6}   {med}")
    print(f"{arm}    assembled_count mismatches: {mismatch}")
