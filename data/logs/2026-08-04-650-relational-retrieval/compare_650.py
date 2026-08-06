"""#650 paired-run comparison: old surface (main) vs new (branch)."""

import json
from collections import Counter
from pathlib import Path

OLD = Path("D:/axial/data/analyses")
NEW = Path("D:/axial/.claude/worktrees/650-relational-retrieval/data/analyses")
IDS = ["6678f15a71f15ac0", "080d9e472fc56a34", "dae632c369c18ffc"]

DOOR = {
    "find_names",
    "get_name",
    "name_neighbors",
    "where_names_meet",
    "who_cites",
    "who_argues_against",
}
RELATION = {"find_notes", "names_arguing_against", "opposition_pairs", "positions_on"}


def summarize(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    traj = d.get("trajectory") or []
    tools = Counter(s["tool"] for s in traj)
    zero = sum(1 for s in traj if (s.get("result_count") or 0) == 0)
    cited = d.get("source_usage", {}).get("sources") or []
    cited_ids = {s.get("source_id") for s in cited if s.get("cited_count", s.get("cited", 0))}
    claims = d.get("claims") or []
    kinds = Counter(c.get("kind") for c in claims)
    cost = d.get("cost") or {}
    return {
        "case": (d.get("brief") or {}).get("case", "")[:38],
        "steps": len(traj),
        "door": sum(tools[t] for t in DOOR),
        "relation": sum(tools[t] for t in RELATION),
        "zero_result_steps": zero,
        "tools": dict(tools),
        "assembled": d.get("evidence", {}).get("assembled_count"),
        "composed": d.get("evidence", {}).get("composed_count"),
        "sources_cited": len(cited_ids) if cited_ids else len(cited),
        "claims": len(claims),
        "kinds": dict(kinds),
        "band": (d.get("confidence") or {}).get("overall_band"),
        "cost_usd": cost.get("total_usd") if isinstance(cost, dict) else cost,
    }


def main():
    rows = []
    for bid in IDS:
        for arm, root in (("old", OLD), ("new", NEW)):
            p = root / f"{bid}.json"
            if not p.is_file():
                print(f"MISSING {arm} {bid}")
                continue
            s = summarize(p)
            s["arm"] = arm
            s["brief_id"] = bid
            rows.append(s)

    hdr = [
        "brief_id",
        "arm",
        "steps",
        "door",
        "relation",
        "zero_result_steps",
        "assembled",
        "composed",
        "sources_cited",
        "claims",
        "band",
        "cost_usd",
    ]
    print("\t".join(hdr))
    for r in rows:
        print("\t".join(str(r.get(h)) for h in hdr))

    print("\n== tool mix ==")
    for r in rows:
        print(f"{r['brief_id'][:8]} {r['arm']:>3}  {r['case']}")
        print(f"     {r['tools']}")
        print(f"     kinds={r['kinds']}")

    print("\n== totals ==")
    for arm in ("old", "new"):
        a = [r for r in rows if r["arm"] == arm]
        if not a:
            continue
        print(
            f"{arm}: steps={sum(r['steps'] for r in a)} door={sum(r['door'] for r in a)} "
            f"relation={sum(r['relation'] for r in a)} zero={sum(r['zero_result_steps'] for r in a)} "
            f"composed={sum(r['composed'] or 0 for r in a)} cited={sum(r['sources_cited'] for r in a)} "
            f"claims={sum(r['claims'] for r in a)} cost=${sum(r['cost_usd'] or 0 for r in a):.3f}"
        )


if __name__ == "__main__":
    main()
