"""Does any usable-band page fall OUT of the band when the merge pass flips?

Only 0.4% of usable-band notes change page (impact_695_pages_moved.py), but a
small movement can still matter if it pushes a page below the band -- under 30
notes, or under 5 sources -- because a page below the band produces no output at
all. That is the one path from "few notes move" to "material consequence", so it
is checked rather than assumed.

Free: no model calls, no writes outside the probe's own log dir.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path("data")
PROBE = DATA / "logs" / "2026-08-05-695-usable-band"

notes_of: dict[str, set[str]] = {}
for line in (DATA / "names" / "inventory.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        entry = json.loads(line)
        notes_of.setdefault(entry["surface"], set()).update(entry["chunk_ids"])

nodes = json.load((DATA / "names" / "alias_map.json").open(encoding="utf-8"))["nodes"]
page_of: dict[str, str] = {}
page_notes: dict[str, set[str]] = {}
for node in nodes:
    surfaces = [node["canonical"], *(node.get("aliases") or [])]
    chunks: set[str] = set()
    for surface in surfaces:
        page_of[surface] = node["canonical"]
        chunks |= notes_of.get(surface, set())
    page_notes[node["canonical"]] = chunks


def in_band(chunks: set[str]) -> bool:
    return 30 <= len(chunks) <= 200 and len({c.split("_", 1)[0] for c in chunks}) >= 5


usable = {name for name, chunks in page_notes.items() if in_band(chunks)}


def head(group: frozenset[str]) -> str:
    return max(sorted(group), key=lambda s: len(notes_of.get(s, ())))


rows = [
    json.loads(line)
    for line in (PROBE / "results-temp1.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]

# Every surface that leaves its recorded page, grouped by the page it leaves.
losses: dict[str, set[str]] = {}
for row in rows:
    if row["agrees"]:
        continue
    recorded = {m: frozenset(g) for g in row["recorded_partition"] for m in g}
    fresh = {m: frozenset(g) for g in (row["fresh_partition"] or []) for m in g}
    for surface in set(recorded) | set(fresh):
        before, after = recorded.get(surface), fresh.get(surface)
        if before is None or after is None or head(before) == head(after):
            continue
        page = page_of.get(surface)
        if page in usable:
            losses.setdefault(page, set()).update(notes_of.get(surface, ()))

report: list[str] = []
exits = 0
for page, lost in sorted(losses.items(), key=lambda kv: -len(kv[1])):
    before = page_notes[page]
    after = before - lost
    still = in_band(after)
    exits += 0 if still else 1
    report.append(
        f"  {page!r}: {len(before)} notes / {len({c.split('_', 1)[0] for c in before})} sources"
        f"  ->  {len(after)} / {len({c.split('_', 1)[0] for c in after})}"
        f"   {'stays in band' if still else 'LEAVES BAND'}"
    )

lines = [
    f"usable-band pages losing any note on a flip: {len(losses)} of {len(usable)}",
    f"pages that fall out of the band:             {exits}",
    "",
    *report,
]
(PROBE / "band-exit.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines[:4]))
print(f"\nfull listing: {PROBE / 'band-exit.txt'}")
