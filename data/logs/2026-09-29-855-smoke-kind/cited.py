"""Does the kind-aware corridor get conflict positions into the answer?

For each brief in the #853 count-order run and the #855 kind-order run: the
corridor positions, split by whether any relation joining them to a landed
position is a conflict, and how many of each put a passage into assembly and
into a cited claim. Kinds come from the relation build for both runs, so the
count-order run is classified the same way although it ran without them."""

import json
from collections import defaultdict
from pathlib import Path

MAP = Path("D:/axial-runs/data/map/9b796b3a6312b329")
ASSIGN = Path("D:/axial-runs/data/vocabulary/relation/assignments.jsonl")
RUNS = {
    "853 count order": Path("D:/axial-runs/data/runs/853-smoke-map"),
    "855 kind order": Path("D:/axial-runs/data/runs/855-smoke-kind"),
}

chunks = {}
for line in (MAP / "positions.jsonl").open(encoding="utf-8"):
    p = json.loads(line)
    chunks[p["position_id"]] = set(p["chunk_ids"])
kinds = defaultdict(set)
for line in ASSIGN.open(encoding="utf-8"):
    a = json.loads(line)
    if not a["refused"]:
        kinds[a["from_position_id"], a["to_position_id"]].add(a["category_id"])
        kinds[a["to_position_id"], a["from_position_id"]].add(a["category_id"])

for label, root in RUNS.items():
    print(f"\n== {label}")
    print("brief  corridor  conflict:n/assembled/cited  other:n/assembled/cited  cited-chunks-from-conflict")
    tot = defaultdict(int)
    for path in sorted(root.glob("analyses/S-0*/draw0/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        m = rec["map_retrieval"]
        landed = [x["position_id"] for x in m["landed"]]
        assembled = set(m["assembled_chunk_ids"])
        cited = {g["ref_id"] for c in rec["claims"] for g in c.get("grounds", []) if g["ref_type"] == "chunk"}
        row = {"conflict": [0, 0, 0], "other": [0, 0, 0]}
        cited_conflict_chunks = set()
        for c in m["corridor"]:
            pid = c["position_id"]
            k = set().union(*(kinds.get((pid, l), set()) for l in landed))
            group = "conflict" if "conflict" in k else "other"
            row[group][0] += 1
            row[group][1] += bool(chunks[pid] & assembled)
            row[group][2] += bool(chunks[pid] & cited)
            if group == "conflict":
                cited_conflict_chunks |= chunks[pid] & cited
        for g in row:
            for i in range(3):
                tot[g, i] += row[g][i]
        print(f"{path.parts[-3]}   {len(m['corridor']):3}      {'/'.join(map(str, row['conflict'])):14}"
              f"           {'/'.join(map(str, row['other'])):14}         {len(cited_conflict_chunks)} of {len(cited)}")
    print(f"total  conflict {tot['conflict', 0]}/{tot['conflict', 1]}/{tot['conflict', 2]}"
          f"  other {tot['other', 0]}/{tot['other', 1]}/{tot['other', 2]}")
