import json
from axial.argmap import consolidate as C
from axial.argmap.build import assign_position_ids

MAP = "data/map/9b796b3a6312b329-category/positions.jsonl"
REP = "data/logs/2026-08-29-consolidation-pass/repair/repair_reads.jsonl"
ps = [json.loads(l) for l in open(MAP, encoding="utf-8")]
recs = {r["key"]: r for r in (json.loads(l) for l in open(REP, encoding="utf-8"))}

out = []
kept = taken = resent = 0
for p in ps:
    if len(p.get("folded_from") or []) < 2:
        out.append(p)
        continue
    r = recs[C._re_read_key(tuple(C._members_of(p)))]
    new = r["positions"]
    shattered = len(new) == r["shown"] and all(
        len(q.get("folded_from") or []) < 2 for q in new
    )
    if shattered:
        out.append(p)
        kept += 1
    else:
        out.extend(new)
        taken += 1
        resent += bool(r.get("resentenced"))
st = assign_position_ids(out)
print("kept original (full shatter):", kept, "| accepted repair:", taken,
      "| of which resentenced:", resent)
print("positions", len(st))
f = [q for q in st if len(q.get("folded_from") or []) >= 2]
print("folded", len(f), "folds", sum(len(q["folded_from"]) - 1 for q in f))
print("sum consolidated_from", sum(q.get("consolidated_from", 1) for q in st))
with open("data/logs/2026-08-29-consolidation-pass/repair/positions.selective.jsonl",
          "w", encoding="utf-8") as h:
    for q in st:
        h.write(json.dumps(q, ensure_ascii=False) + "\n")
