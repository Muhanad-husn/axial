"""#883: conflict pairs with both / one end cited, per arm and brief. Zero calls.

A pair is a relation filed under the conflict kind with both positions holding
a passage in the composed prompt (assembled_chunk_ids[:composed_count]), the
same definition as #881's `contested_pairs` (PR #882), inlined here because
that branch was closed. Each arm uses the relation set its corridor walked.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "D:/axial-runs/src")
from axial.argmap.ask import _load_relations, load_map_relations, load_relation_kinds  # noqa: E402

R = Path("D:/axial-runs")
MAP = R / "data/map/9b796b3a6312b329"
kinds = load_relation_kinds(R / "data/vocabulary")
positions = {
    p["position_id"]: p
    for p in (json.loads(line) for line in (MAP / "positions.jsonl").open(encoding="utf-8"))
}
ARMS = {"A": ("data/runs/883-arm-A", _load_relations(MAP)),
        "C": ("data/runs/883-arm-C", load_map_relations(MAP))}

print("arm  brief  answers  pairs-shown  both-ends-cited  one-end-cited  answers-with-both")
for arm, (root, relations) in ARMS.items():
    conflicts = [r for r in relations if kinds.kind_of(r) == "conflict"]
    total = defaultdict(int)
    s = json.loads((R / root / "summary.json").read_text(encoding="utf-8"))
    for b in s["briefs"]:
        row = defaultdict(int)
        for d in b["draws"]:
            if d["status"] != "OK":
                continue
            r = json.loads((R / d["record_path"]).read_text(encoding="utf-8"))
            order = r["map_retrieval"]["assembled_chunk_ids"]
            comp = set(order[: r["evidence"]["composed_count"]])
            cited = {g["ref_id"] for c in r["claims"] for g in c.get("grounds", [])
                     if g["ref_type"] == "chunk"}
            both = 0
            for rel in conflicts:
                a = set(positions[rel["from_position_id"]]["chunk_ids"])
                b_ = set(positions[rel["to_position_id"]]["chunk_ids"])
                if not (a & comp and b_ & comp):
                    continue
                row["shown"] += 1
                ca, cb = bool(a & cited), bool(b_ & cited)
                both += ca and cb
                row["one"] += ca != cb
            row["both"] += both
            row["with_both"] += both > 0
            row["n"] += 1
        for k, v in row.items():
            total[k] += v
        print(f"{arm}    {b['brief_stem']}  {row['n']:7}  {row['shown']:11}  {row['both']:15}  "
              f"{row['one']:13}  {row['with_both']}")
    print(f"{arm}    ALL    {total['n']:7}  {total['shown']:11}  {total['both']:15}  "
          f"{total['one']:13}  {total['with_both']}")
