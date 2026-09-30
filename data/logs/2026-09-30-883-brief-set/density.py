"""#883, free: where the map is dense in cross-author relations and conflicts.

Joins relations.jsonl + profile_relations.jsonl (as the ask path loads them)
with the committed relation kinds, keeps cross-author relations, and groups
them into connected regions. Prints each region's books, kind counts and the
arguments of its most-connected positions, so briefs can be drafted from them.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "D:/axial-runs/src")
from axial.argmap.ask import load_map_relations, load_relation_kinds  # noqa: E402

MAP = Path("D:/axial-runs/data/map/9b796b3a6312b329")
VOCAB = Path("D:/axial-runs/data/vocabulary")

positions = {
    p["position_id"]: p
    for p in (json.loads(line) for line in (MAP / "positions.jsonl").open(encoding="utf-8"))
}
relations = load_map_relations(MAP)
kinds = load_relation_kinds(VOCAB)
print(f"positions {len(positions)}  relations {len(relations)}  kinds {kinds is not None}")

cross = []
for r in relations:
    a, b = positions.get(r["from_position_id"]), positions.get(r["to_position_id"])
    if not a or not b:
        continue
    if set(a["authors"]) & set(b["authors"]):
        continue
    cross.append((r, kinds.kind_of(r) if kinds else None))
print(f"cross-author relations {len(cross)}  kinds {Counter(k for _, k in cross)}")

# union-find over cross-author relations
parent: dict[str, str] = {}


def find(x: str) -> str:
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for r, _ in cross:
    parent[find(r["from_position_id"])] = find(r["to_position_id"])

regions: dict[str, list] = defaultdict(list)
for r, k in cross:
    regions[find(r["from_position_id"])].append((r, k))
print(f"regions {len(regions)}  sizes {sorted((len(v) for v in regions.values()), reverse=True)[:15]}")

# Degree within cross-author graph; conflicts per position
degree: Counter = Counter()
conflict_deg: Counter = Counter()
for r, k in cross:
    for pid in (r["from_position_id"], r["to_position_id"]):
        degree[pid] += 1
        if k == "conflict":
            conflict_deg[pid] += 1

# Report top positions by cross-author degree, with conflict count, authors, argument
print("\n== top 60 positions by cross-author degree")
for pid, d in degree.most_common(60):
    p = positions[pid]
    print(f"{pid} deg={d} conf={conflict_deg[pid]} authors={','.join(p['authors'])} size={p['size']}")
    print(f"    {p['argument'][:220]}")

# Author-pair conflict counts
pair_conf: Counter = Counter()
pair_all: Counter = Counter()
for r, k in cross:
    a = positions[r["from_position_id"]]["authors"][0]
    b = positions[r["to_position_id"]]["authors"][0]
    key = tuple(sorted((a, b)))
    pair_all[key] += 1
    if k == "conflict":
        pair_conf[key] += 1
print("\n== author pairs by conflicts (all cross relations)")
for key, c in pair_conf.most_common(40):
    print(f"{key} conflicts={c} all={pair_all[key]}")
