import json, random

D = "data/logs/2026-08-29-consolidation-pass/repair/"
maps = {
    "before": "data/map/9b796b3a6312b329-category/positions.jsonl",
    "after": D + "positions.selective.jsonl",
}
items = []
for label, path in maps.items():
    ps = [json.loads(l) for l in open(path, encoding="utf-8")]
    folded = [p for p in ps if len(p.get("folded_from") or []) >= 2]
    rng = random.Random(830)
    for p in rng.sample(folded, 18):
        items.append({
            "label": label,
            "sentence": p["argument"],
            "members": [m["argument"] for m in p["folded_from"]],
        })
random.Random(1).shuffle(items)
with open(D + "audit_items.md", "w", encoding="utf-8") as h:
    for i, it in enumerate(items, 1):
        h.write(f"### {i}\n**stands for:** {it['sentence']}\n\n")
        for m in it["members"]:
            h.write(f"- {m}\n")
        h.write("\n")
with open(D + "audit_key.json", "w", encoding="utf-8") as h:
    json.dump([it["label"] for it in items], h)
print("wrote", len(items))
