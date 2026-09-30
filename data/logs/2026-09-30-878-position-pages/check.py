"""#878 real-corpus check: rewrite vault/positions with the branch code and
count relation lines against relations.jsonl + profile_relations.jsonl."""
import json
import re
from pathlib import Path

from axial.argmap.ask import load_map_relations
from axial.position_pages import write_position_pages

data = Path("D:/axial-runs/data")
map_dir = data / "map" / "9b796b3a6312b329"
result = write_position_pages(
    map_dir=map_dir, vocabulary_dir=data / "vocabulary", vault_dir=data / "vault"
)
relations = load_map_relations(map_dir)
base = sum(1 for line in (map_dir / "relations.jsonl").open(encoding="utf-8") if line.strip())
link = re.compile(r"\[\[(pos-\d+)\]\]")
pages = {p.stem: p.read_text(encoding="utf-8") for p in (data / "vault" / "positions").glob("*.md")}
missing = [
    r for r in relations
    if r["to_position_id"] not in link.findall(pages[r["from_position_id"]])
    or r["from_position_id"] not in link.findall(pages[r["to_position_id"]])
]
body_lines = [l for text in pages.values() for l in text.split("---\n", 2)[2].splitlines() if link.search(l) and ("—" in l or ":" in l)]
print(json.dumps({
    **result,
    "relations_base": base,
    "relations_union": len(relations),
    "added_from_profile": len(relations) - base,
    "relations_missing_an_endpoint_link": len(missing),
}))
