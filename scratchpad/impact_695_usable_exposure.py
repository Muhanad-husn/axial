"""Is the usable band even exposed to the merge pass's unstable decisions?

The sample in impact_695_material.py landed only 37 notes on usable-band pages,
so its 0% there is a thin zero. This asks the question directly of the full
decision log: of the notes on the 327 pages Axial actually produces output from,
how many arrive via a surface that a 3+-member merge batch decided -- the only
decisions measured unstable. A note whose surface never entered such a batch
cannot be moved by the instability, whatever its rate.

Free: no model calls, no writes.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path("data")

notes_of: dict[str, set[str]] = {}
for line in (DATA / "names" / "inventory.jsonl").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    entry = json.loads(line)
    notes_of.setdefault(entry["surface"], set()).update(entry["chunk_ids"])


def source_of(chunk_id: str) -> str:
    return chunk_id.split("_", 1)[0]


nodes = json.load((DATA / "names" / "alias_map.json").open(encoding="utf-8"))["nodes"]
page_surfaces = {n["canonical"]: [n["canonical"], *n["aliases"]] for n in nodes}
page_notes = {
    name: set().union(*(notes_of.get(s, set()) for s in surfaces)) if surfaces else set()
    for name, surfaces in page_surfaces.items()
}

usable = {
    name
    for name, chunks in page_notes.items()
    if 30 <= len(chunks) <= 200 and len({source_of(c) for c in chunks}) >= 5
}

# Every surface any 3+-member batch ruled on, and every surface any batch ruled on.
in_multi: set[str] = set()
in_any: set[str] = set()
sizes: dict[int, int] = {}
for line in (DATA / "names" / "merge_decisions.jsonl").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    record = json.loads(line)
    members = record.get("members") or []
    sizes[len(members)] = sizes.get(len(members), 0) + 1
    in_any.update(members)
    if len(members) >= 3:
        in_multi.update(members)

print(f"surfaces ruled on by any batch   {len(in_any):>8,}")
print(f"surfaces ruled on by a 3+ batch  {len(in_multi):>8,}")
print("batch sizes:", dict(sorted(sizes.items()))) if len(sizes) < 15 else None

for label, pages in (("all pages", set(page_surfaces)), ("usable band", usable)):
    total = 0
    exposed_multi = 0
    exposed_any = 0
    touched_pages = 0
    for name in pages:
        chunks = page_notes[name]
        total += len(chunks)
        multi_chunks: set[str] = set()
        any_chunks: set[str] = set()
        for surface in page_surfaces[name]:
            if surface in in_multi:
                multi_chunks |= notes_of.get(surface, set())
            if surface in in_any:
                any_chunks |= notes_of.get(surface, set())
        exposed_multi += len(multi_chunks)
        exposed_any += len(any_chunks)
        if multi_chunks:
            touched_pages += 1
    print()
    print(f"{label}: {len(pages):,} pages, {total:,} note assignments")
    print(
        f"  assignments decided by a 3+ batch  {exposed_multi:>8,}  {100 * exposed_multi / total:.2f}%"
    )
    print(
        f"  assignments decided by any batch   {exposed_any:>8,}  {100 * exposed_any / total:.2f}%"
    )
    print(
        f"  pages with any 3+-batch surface    {touched_pages:>8,}  {100 * touched_pages / len(pages):.2f}%"
    )
