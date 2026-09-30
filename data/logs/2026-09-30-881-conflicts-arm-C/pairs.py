"""#881: conflict pairs with both / one end cited, per arm. Arms B/C (#879)
never saw the block; their pairs are recomputed offline with the same
`contested_pairs` the branch uses, over each arm's own relation set."""

import json
from pathlib import Path

from axial.argmap.ask import _load_relations, contested_pairs, load_map_relations, load_relation_kinds

R = Path("D:/axial-runs")
MAP = R / "data/map/9b796b3a6312b329"
kinds = load_relation_kinds(R / "data/vocabulary")
positions = {json.loads(l)["position_id"]: json.loads(l) for l in open(MAP / "positions.jsonl", encoding="utf-8")}
ARMS = {"B": ("data/runs/879-arm-B", _load_relations(MAP)),
        "C": ("data/runs/879-arm-C", load_map_relations(MAP)),
        "D": ("data/runs/881-arm-C", load_map_relations(MAP))}
print("arm  answers  pairs-shown  both-ends-cited  one-end-cited  answers-with-a-both-ends-pair")
for arm, (root, relations) in ARMS.items():
    s = json.load(open(R / root / "summary.json"))
    n = shown_t = both_t = one_t = with_both = 0
    for b in s["briefs"]:
        for d in b["draws"]:
            if d["status"] != "OK":
                continue
            r = json.loads((R / d["record_path"]).read_text(encoding="utf-8"))
            order = r["map_retrieval"]["assembled_chunk_ids"]
            comp = set(order[: r["evidence"]["composed_count"]])
            cited = {g["ref_id"] for c in r["claims"] for g in c.get("grounds", []) if g["ref_type"] == "chunk"}
            pairs = contested_pairs(relations, kinds, positions, order)
            shown = [p for p in pairs if set(p.from_chunk_ids) & comp and set(p.to_chunk_ids) & comp]
            both = sum(1 for p in shown if set(p.from_chunk_ids) & cited and set(p.to_chunk_ids) & cited)
            one = sum(1 for p in shown if bool(set(p.from_chunk_ids) & cited) != bool(set(p.to_chunk_ids) & cited))
            n += 1; shown_t += len(shown); both_t += both; one_t += one; with_both += both > 0
    print(f"{arm}    {n:7}  {shown_t:11}  {both_t:15}  {one_t:13}  {with_both}")
