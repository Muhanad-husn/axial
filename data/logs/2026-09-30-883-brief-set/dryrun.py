"""#883, free: land and walk the corridor for each candidate brief, offline.

No model call. The door is replaced two ways:
  proxy    the stated arguments written with the draft (candidates.json);
           biased upward, since they were drafted from the map's own region.
  request  the request sentence alone as one ask, top_k 24 (about what a real
           door lands); a floor that owes nothing to the drafting.
The smoke briefs run too, on the real door asks their #879 arm-C records
hold, to check the filter against briefs known to cite one or two books.

Corridor, kinds and relations are loaded exactly as run_map_ask_for_brief
loads them. A candidate passes when its corridor reaches positions in 3 or
more books (sources) under both doors.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, "D:/axial-runs/src")
from axial.argmap.ask import (  # noqa: E402
    build_corridor,
    land_arguments,
    load_map_relations,
    load_relation_kinds,
)
from axial.argmap.build import _default_encoder  # noqa: E402

HERE = Path("D:/axial-runs/data/logs/2026-09-30-883-brief-set")
MAP = Path("D:/axial-runs/data/map/9b796b3a6312b329")
RUNS = Path("D:/axial-runs/data/runs/879-arm-C/analyses")

positions = [json.loads(line) for line in (MAP / "positions.jsonl").open(encoding="utf-8")]
by_id = {p["position_id"]: p for p in positions}
relations = load_map_relations(MAP)
kinds = load_relation_kinds(Path("D:/axial-runs/data/vocabulary"))
profile_pairs = {
    frozenset((r["from_position_id"], r["to_position_id"]))
    for r in relations
    if r.get("generator") == "profile"
}
encode = _default_encoder()


def walk(asks, top_k):
    landed = land_arguments(asks, positions, encode, top_k=top_k)
    corridor = build_corridor(landed, by_id, relations, kinds=kinds)
    landed_ids = {p.position_id for p in landed}
    landed_books = {s for p in landed for s in p.sources}
    corridor_books = {s for p in corridor for s in p.sources}
    via_profile = 0
    for c in corridor:
        pairs = {
            frozenset((c.position_id, near))
            for near in landed_ids
        }
        reached = [
            r for r in relations
            if frozenset((r["from_position_id"], r["to_position_id"])) in pairs
        ]
        if reached and all(r.get("generator") == "profile" for r in reached):
            via_profile += 1
    return {
        "landed": len(landed),
        "landed_books": len(landed_books),
        "corridor": len(corridor),
        "corridor_books": len(corridor_books),
        "corridor_new_books": len(corridor_books - landed_books),
        "conflict_positions": sum(1 for c in corridor if "conflict" in c.kinds),
        "via_profile_only": via_profile,
        "books": sorted(corridor_books | landed_books),
    }


def row(name, door, r):
    return (
        f"{name:5} {door:8} landed {r['landed']:3} ({r['landed_books']:2} books)  "
        f"corridor {r['corridor']:3} ({r['corridor_books']:2} books, "
        f"{r['corridor_new_books']:2} new)  conflict {r['conflict_positions']:2}  "
        f"profile-only {r['via_profile_only']:2}"
    )


results = {}
print("== smoke briefs, real door asks from #879 arm C (first draw on disk)")
for brief in sorted(p.name for p in RUNS.iterdir()):
    draws = sorted(d for d in (RUNS / brief).iterdir() if d.name.startswith("draw"))
    record = next(draws[0].glob("*.json"))
    asks = json.loads(record.read_text(encoding="utf-8"))["map_retrieval"]["asks"]
    r = walk(asks, 4)
    results[brief] = {"real": r}
    print(row(brief, "real", r))

print("\n== candidates")
for c in json.loads((HERE / "candidates.json").read_text(encoding="utf-8")):
    proxy = walk(c["asks"], 4)
    floor = walk([c["request"]], 24)
    ok = proxy["corridor_books"] >= 3 and floor["corridor_books"] >= 3
    results[c["id"]] = {"proxy": proxy, "request": floor, "pass": ok}
    print(row(c["id"], "proxy", proxy))
    print(row(c["id"], "request", floor), "PASS" if ok else "FAIL")

(HERE / "dryrun.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
