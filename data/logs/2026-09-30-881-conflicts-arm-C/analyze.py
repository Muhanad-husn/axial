"""#881 (arm D = arm C with the conflict block) against #879 A/B/C: what each corridor state puts into cited answers. Zero model calls.

Per (brief, draw) record of arms A/B/C:
  sources     distinct sources (books) the claims cite
  cited_cor   corridor positions with a passage in a cited claim
  by kind     those split by the kinds of the relations joining them to the
              landed set: conflict > qualification > support > other (a
              position joined by several kinds counts under the first)
  counter     cited chunks from corridor positions joined by a conflict
  crossbook   cited corridor positions sharing no source with the landed set
  via_profile cited corridor positions joined to the landed set only through
              a profile relation (arm C only)

Kinds come from the relation build for every arm, restricted to the relations
that arm's corridor could walk (A/B: relations.jsonl; C: both files), so arm A
is classified although it ran in count order.

Spread: an arm's draw-to-draw range per brief. A difference between arms on a
brief counts only when the two arms' draw ranges do not overlap."""

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

DATA = Path("D:/axial-runs/data")
MAP = DATA / "map/9b796b3a6312b329"
ASSIGN = DATA / "vocabulary/relation/assignments.jsonl"
ARMS = {**{arm: DATA / f"runs/879-arm-{arm}" for arm in "ABC"}, "D": DATA / "runs/881-arm-C"}
ORDER = ("conflict", "qualification", "support")


def read_jsonl(path):
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


positions = {p["position_id"]: p for p in read_jsonl(MAP / "positions.jsonl")}
base = read_jsonl(MAP / "relations.jsonl")
profile = read_jsonl(MAP / "profile_relations.jsonl")
kind_of = {}
for a in read_jsonl(ASSIGN):
    if not a["refused"]:
        kind_of[a["from_position_id"], a["to_position_id"], a["relation"]] = a["category_id"]


def edges(relations):
    out = defaultdict(set)
    for r in relations:
        k = kind_of.get((r["from_position_id"], r["to_position_id"], r["relation"]), "other")
        k = k if k in ORDER else "other"
        out[frozenset((r["from_position_id"], r["to_position_id"]))].add(k)
    return out


base_pairs = {frozenset((r["from_position_id"], r["to_position_id"])) for r in base}
EDGES = {"A": edges(base), "B": edges(base), "C": edges(base + profile), "D": edges(base + profile)}


def measure(arm, rec):
    m = rec["map_retrieval"]
    landed = [x["position_id"] for x in m["landed"]]
    cited = {
        g["ref_id"]
        for c in rec["claims"]
        for g in c.get("grounds", [])
        if g["ref_type"] == "chunk"
    }
    sources = {cid.split("_", 1)[0] for cid in cited}
    row = defaultdict(int, sources=len(sources), claims=len(rec["claims"]),
                      corridor=len(m["corridor"]), cost=rec["cost"]["total_usd"] or 0.0)
    for c in m["corridor"]:
        pid = c["position_id"]
        hit = set(positions[pid]["chunk_ids"]) & cited
        if not hit:
            continue
        row["cited_cor"] += 1
        pairs = [frozenset((pid, l)) for l in landed if frozenset((pid, l)) in EDGES[arm]]
        kinds = set().union(*(EDGES[arm][p] for p in pairs)) if pairs else set()
        group = next((k for k in ORDER if k in kinds), "other")
        row[group] += 1
        if "conflict" in kinds:
            row["counter"] += len(hit)
        joined_authors = {
            a for p in pairs for other in p - {pid} for a in positions[other]["authors"]
        }
        if pairs and not set(positions[pid]["authors"]) & joined_authors:
            row["crossauthor"] += 1
        if pairs and not any(p in base_pairs for p in pairs):
            row["via_profile"] += 1
    return row


COLS = ("sources", "cited_cor", "conflict", "qualification", "support", "other",
        "counter", "crossauthor", "via_profile", "corridor", "claims", "cost")
rows = defaultdict(dict)  # rows[brief][arm] = [row per draw]
gates = defaultdict(dict)
for arm, root in ARMS.items():
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    for b in summary["briefs"]:
        gates[b["brief_stem"]][arm] = "".join(
            "P" if g["passed"] else "F" for _, g in sorted(b["gate_reports"].items())
        )
        rows[b["brief_stem"]][arm] = [
            measure(arm, json.loads((Path("D:/axial-runs") / d["record_path"]).read_text(encoding="utf-8")))
            for d in b["draws"]
            if d["status"] == "OK"
        ]

print("per brief: mean over draws [min-max]; gates attribution/calibration/grounding/synthesis")
for brief in sorted(rows):
    print(f"\n{brief}  gates " + " ".join(f"{a}={gates[brief].get(a, '-')}" for a in ARMS))
    for col in COLS:
        cells = []
        for arm in ARMS:
            vals = [r[col] for r in rows[brief].get(arm, [])]
            if not vals:
                cells.append(f"{arm}: -")
            elif col == "cost":
                cells.append(f"{arm}: ${mean(vals):.3f}")
            else:
                cells.append(f"{arm}: {mean(vals):5.1f} [{min(vals)}-{max(vals)}]")
        print(f"  {col:13} " + "   ".join(cells))

print("\nall briefs: mean per answer; 'separated' = briefs where the arm's draw range "
      "sits wholly above (+) or below (-) arm A's")
for col in COLS:
    line = []
    for arm in ARMS:
        vals = [r[col] for brief in rows for r in rows[brief].get(arm, [])]
        cell = f"{arm}: {mean(vals):6.2f}" if vals else f"{arm}: -"
        if arm != "A" and vals and col != "cost":
            up = down = 0
            for brief in rows:
                a = [r[col] for r in rows[brief].get("A", [])]
                x = [r[col] for r in rows[brief].get(arm, [])]
                if a and x:
                    up += min(x) > max(a)
                    down += max(x) < min(a)
            cell += f" (+{up}/-{down})"
        line.append(cell)
    print(f"  {col:13} " + "   ".join(line))
total = {arm: sum(r["cost"] for brief in rows for r in rows[brief].get(arm, [])) for arm in ARMS}
print("\ncost by arm: " + "  ".join(f"{a}=${c:.3f}" for a, c in total.items()))
