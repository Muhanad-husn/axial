"""How many notes actually land on a different page when the merge pass flips.

Counting every note of every surface that changed group overstates this badly. A
batch where {'North Africa'(97 notes), 'Northern African countries'(1)} splits in
two scores 98 "moved" under that rule -- but the 97 notes stay on a North Africa
page either way. One note moved.

A note's page is named after the heaviest surface in its group, which is what a
reader actually navigates. So a note moves only when the heaviest surface of its
group changes. That is the number the founder's 5% test needs.

Free: no model calls, no writes. Output is UTF-8 to a file, since several
surfaces carry transliteration diacritics the Windows console cannot encode.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path("data")
PROBE = DATA / "logs" / "2026-08-05-695-usable-band"
OUT = PROBE / "pages-moved.txt"

notes_of: dict[str, set[str]] = {}
for line in (DATA / "names" / "inventory.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        entry = json.loads(line)
        notes_of.setdefault(entry["surface"], set()).update(entry["chunk_ids"])

nodes = json.load((DATA / "names" / "alias_map.json").open(encoding="utf-8"))["nodes"]
usable: set[str] = set()
usable_total = 0
for node in nodes:
    page = [node["canonical"], *(node.get("aliases") or [])]
    chunks: set[str] = set()
    for surface in page:
        chunks |= notes_of.get(surface, set())
    if 30 <= len(chunks) <= 200 and len({c.split("_", 1)[0] for c in chunks}) >= 5:
        usable.update(page)
        usable_total += len(chunks)


def head(group: frozenset[str]) -> str:
    """The surface a group's page is named after: the heaviest, ties by name."""
    return max(sorted(group), key=lambda s: len(notes_of.get(s, ())))


rows = [
    json.loads(line)
    for line in (PROBE / "results-temp1.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
run = [
    json.loads(line)
    for line in (PROBE / "run.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
eligible = next(e for e in run if e["event"] == "eligible")
population = eligible["reproducible"] + eligible["stale_input"]

lines: list[str] = []
moved_total = 0
flips_with_real_movement = 0
for row in rows:
    if row["agrees"]:
        continue
    recorded = {m: frozenset(g) for g in row["recorded_partition"] for m in g}
    fresh = {m: frozenset(g) for g in (row["fresh_partition"] or []) for m in g}
    detail = []
    batch_moved = 0
    for surface in sorted(set(recorded) | set(fresh)):
        if surface not in usable:
            continue
        before = recorded.get(surface)
        after = fresh.get(surface)
        if before is None or after is None or head(before) == head(after):
            continue
        n = len(notes_of.get(surface, ()))
        batch_moved += n
        detail.append(f"{surface!r} ({n} notes): {head(before)!r} -> {head(after)!r}")
    if detail:
        flips_with_real_movement += 1
        moved_total += batch_moved
        lines.append(f"  {batch_moved:>4} notes  {row['member_count']}m")
        lines.extend(f"        {d}" for d in detail)

flips = sum(1 for r in rows if not r["agrees"])
report = [
    f"usable-band assignments in corpus      {usable_total:>8,}",
    f"3+ batches touching the band           {population:>8,}  "
    f"({eligible['reproducible']} reproducible, {eligible['stale_input']} stale)",
    f"sampled                                {len(rows):>8,}",
    f"flips                                  {flips:>8,}  ({100 * flips / len(rows):.1f}%)",
    f"flips that move a note to another page {flips_with_real_movement:>8,}",
    "",
    f"A. measured floor, no extrapolation    {moved_total:>8,} / {usable_total:,} "
    f"= {100 * moved_total / usable_total:.2f}%",
]
for label, scale in (
    ("B. scale to reproducible only", eligible["reproducible"] / len(rows)),
    ("C. scale to all incl. stale", population / len(rows)),
):
    projected = moved_total * scale
    report.append(
        f"{label:<38}{projected:>8,.0f} / {usable_total:,} "
        f"= {100 * projected / usable_total:.2f}%   (x{scale:.2f})"
    )
report += ["", "every usable-band note that changes page:"] + lines

OUT.write_text("\n".join(report), encoding="utf-8")
print("\n".join(report[:12]))
print(f"\nfull listing: {OUT}")
