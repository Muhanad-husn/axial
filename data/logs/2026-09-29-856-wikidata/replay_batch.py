"""Replay the batch the pass is stuck on, one query at a time, to find which
query the service refuses."""

import json
from pathlib import Path

import httpx

from axial.wikidata import _load_cache, band_nodes, type_for_kind

N = Path("D:/axial-runs/data/names")
nodes = json.loads((N / "alias_map.json").read_text(encoding="utf-8"))["nodes"]
inventory = {
    r["surface"]: r
    for r in (json.loads(l) for l in (N / "inventory.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())
}
band = band_nodes(nodes, inventory)
queries = list(dict.fromkeys(
    (s, type_for_kind(n.get("kind"))) for n in band for s in (n["canonical"], *n.get("aliases", []))
))
cached = _load_cache(N / "wikidata" / "responses.jsonl")
missing = [q for q in queries if q not in cached][:10]
for text, type_ in missing:
    body = {"q0": {"query": text, **({"type": type_} if type_ else {})}}
    try:
        r = httpx.post(
            "https://wikidata.reconci.link/en/api",
            data={"queries": json.dumps(body)},
            timeout=120, follow_redirects=True,
            headers={"User-Agent": "axial-reconcile/1.0 (https://github.com/Muhanad-husn/axial)"},
        )
        print(r.status_code, repr(text), type_, r.text[:120].replace("\n", " ") if r.status_code != 200 else "")
    except Exception as e:
        print(type(e).__name__, repr(text), type_)
