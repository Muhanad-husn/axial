"""#883, free: does the composed prefix predict how many books an answer cites?

Part 1, smoke records (#879 A/B/C, #881 D): per answer, the composed chunks
(assembled_chunk_ids[:composed_count]) give books composed, the top book's
share, and the effective number of books (1 / sum of squared shares).
Compared against the books the answer cites.

Part 2, candidates: the same three figures from an offline assembly
(landing + corridor + assemble_map_evidence, cap 90), cut at the smoke
records' mean composed count. Both doors of dryrun.py.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

sys.path.insert(0, "D:/axial-runs/src")
from axial.argmap.ask import (  # noqa: E402
    assemble_map_evidence,
    build_corridor,
    land_arguments,
    load_map_relations,
    load_relation_kinds,
)
from axial.argmap.build import _default_encoder  # noqa: E402

HERE = Path("D:/axial-runs/data/logs/2026-09-30-883-brief-set")
ROOT = Path("D:/axial-runs")
MAP = ROOT / "data/map/9b796b3a6312b329"


def book(chunk_id):
    return chunk_id.split("_", 1)[0]


def spread(chunk_ids):
    counts = Counter(book(c) for c in chunk_ids)
    total = sum(counts.values())
    shares = [n / total for n in counts.values()]
    return len(counts), max(shares), 1 / sum(s * s for s in shares)


per_brief = {}
composed_counts = []
for arm in ("879-arm-A", "879-arm-B", "879-arm-C", "881-arm-C"):
    summary = json.loads((ROOT / f"data/runs/{arm}/summary.json").read_text(encoding="utf-8"))
    for b in summary["briefs"]:
        for d in b["draws"]:
            if d["status"] != "OK":
                continue
            rec = json.loads((ROOT / d["record_path"]).read_text(encoding="utf-8"))
            ids = rec["map_retrieval"]["assembled_chunk_ids"][: rec["evidence"]["composed_count"]]
            composed_counts.append(rec["evidence"]["composed_count"])
            cited = {
                g["ref_id"] for c in rec["claims"] for g in c.get("grounds", [])
                if g["ref_type"] == "chunk"
            }
            per_brief.setdefault(b["brief_stem"], []).append(
                (*spread(ids), len({book(c) for c in cited}))
            )

print("== smoke: composed prefix vs books cited, mean over all OK draws of four arms")
print("brief  n   books_composed  top_share  effective_books  books_cited")
for brief, rows in sorted(per_brief.items()):
    cols = list(zip(*rows))
    print(f"{brief}  {len(rows):2}  {mean(cols[0]):6.1f}  {mean(cols[1]):6.2f}  "
          f"{mean(cols[2]):6.1f}  {mean(cols[3]):5.1f} [{min(cols[3])}-{max(cols[3])}]")
cut = round(mean(composed_counts))
print(f"mean composed count {cut}")

positions = [json.loads(line) for line in (MAP / "positions.jsonl").open(encoding="utf-8")]
by_id = {p["position_id"]: p for p in positions}
relations = load_map_relations(MAP)
kinds = load_relation_kinds(ROOT / "data/vocabulary")
encode = _default_encoder()


def offline(asks, top_k):
    landed = land_arguments(asks, positions, encode, top_k=top_k)
    corridor = build_corridor(landed, by_id, relations, kinds=kinds)
    return spread(assemble_map_evidence((*landed, *corridor))[:cut])


print("\n== candidates, offline assembly cut at the mean composed count")
print("id    door     books_composed  top_share  effective_books")
out = {}
for c in json.loads((HERE / "candidates.json").read_text(encoding="utf-8")):
    for door, asks, k in (("proxy", c["asks"], 4), ("request", [c["request"]], 24)):
        n, top, eff = offline(asks, k)
        out.setdefault(c["id"], {})[door] = {"books": n, "top_share": top, "effective": eff}
        print(f"{c['id']}  {door:8} {n:6}  {top:6.2f}  {eff:6.1f}")
(HERE / "predictor.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
