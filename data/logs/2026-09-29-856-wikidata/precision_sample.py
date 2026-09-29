"""A seeded random sample of 60 resolved band names, each with the label and
description of the item its QID names, for a by-eye precision audit."""

import json
import random
from pathlib import Path

N = Path("D:/axial-runs/data/names")
res = [json.loads(l) for l in (N / "wikidata/resolutions.jsonl").read_text(encoding="utf-8").splitlines()]
item = {}
for line in (N / "wikidata/responses.jsonl").read_text(encoding="utf-8").splitlines():
    for c in json.loads(line)["result"]:
        item.setdefault(c["id"], (c["name"], c.get("description", "")))
resolved = [r for r in res if r["qid"]]
random.seed(856)
for r in random.sample(resolved, 60):
    name, desc = item.get(r["qid"], ("?", ""))
    print(f"{r['canonical']!r:40} {r['kind']:20} {r['qid']:11} {name} -- {desc[:60]}")
