import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path("D:/axial")
DATA = ROOT / "data" / "names"


def source_id_from_chunk_id(chunk_id: str):
    parts = chunk_id.rsplit("_", 3)
    if len(parts) != 4 or not parts[0]:
        return None
    return parts[0]


# ---- load inventory ----
inventory = {}  # surface -> {kind, count, chunk_ids}
with open(DATA / "inventory.jsonl", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        inventory[row["surface"]] = {
            "kind": row.get("kind"),
            "count": row.get("count", 0),
            "chunk_ids": row.get("chunk_ids", []),
        }

print(f"inventory surfaces: {len(inventory)}", file=sys.stderr)

total_inventory_count = sum(v["count"] for v in inventory.values())
all_chunk_ids = set()
for v in inventory.values():
    all_chunk_ids.update(v["chunk_ids"])
print(
    f"total inventory occurrence count (sum of 'count'): {total_inventory_count}", file=sys.stderr
)
print(
    f"total distinct chunk_ids referenced anywhere in inventory: {len(all_chunk_ids)}",
    file=sys.stderr,
)

# ---- load merge_decisions and replicate list_escalations ----
decisions = {}
with open(DATA / "merge_decisions.jsonl", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        decisions[row["batch_key"]] = row

entries = []  # (surface_form, kind, cluster_label, co_members, source_ids, chunk_ids, batch_key)
for bk, record in decisions.items():
    escalated = record.get("escalated") or []
    if not escalated:
        continue
    members = record.get("members", [])
    for surface_form in escalated:
        inv = inventory.get(surface_form)
        if inv is None:
            kind, chunk_ids = None, ()
        else:
            kind, chunk_ids = inv["kind"], tuple(inv["chunk_ids"])
        source_ids = []
        for cid in chunk_ids:
            sid = source_id_from_chunk_id(cid)
            if sid and sid not in source_ids:
                source_ids.append(sid)
        entries.append(
            {
                "surface": surface_form,
                "kind": kind,
                "cluster_label": record["cluster_label"],
                "co_members": tuple(m for m in members if m != surface_form),
                "source_ids": tuple(sorted(source_ids)),
                "chunk_ids": chunk_ids,
                "batch_key": bk,
                "live": surface_form in inventory,
            }
        )

print(f"\ntotal escalation entries: {len(entries)}", file=sys.stderr)
distinct_surfaces = set(e["surface"] for e in entries)
print(f"distinct escalated surfaces: {len(distinct_surfaces)}", file=sys.stderr)

stale_entries = [e for e in entries if not e["live"]]
live_entries = [e for e in entries if e["live"]]
print(
    f"stale entries (surface not in inventory): {len(stale_entries)} ({len(stale_entries) / len(entries) * 100:.1f}%)",
    file=sys.stderr,
)
print(
    f"live entries: {len(live_entries)} ({len(live_entries) / len(entries) * 100:.1f}%)",
    file=sys.stderr,
)

stale_batches = set(e["batch_key"] for e in stale_entries)
all_batches_with_escalation = set(e["batch_key"] for e in entries)
print(f"stale batches: {len(stale_batches)} of {len(all_batches_with_escalation)}", file=sys.stderr)

live_distinct_surfaces = set(e["surface"] for e in live_entries)
stale_distinct_surfaces = distinct_surfaces - live_distinct_surfaces
print(f"live distinct surfaces: {len(live_distinct_surfaces)}", file=sys.stderr)
print(
    f"stale distinct surfaces (not even in ANY entry live): {len(stale_distinct_surfaces)}",
    file=sys.stderr,
)

assert live_distinct_surfaces.isdisjoint(stale_distinct_surfaces)
assert len(live_distinct_surfaces) + len(stale_distinct_surfaces) == len(distinct_surfaces)

# ---- weight in notes: live escalated surfaces vs corpus total ----
live_surface_chunk_ids = set()
live_surface_occurrence_sum = 0
for s in live_distinct_surfaces:
    inv = inventory[s]
    live_surface_chunk_ids.update(inv["chunk_ids"])
    live_surface_occurrence_sum += inv["count"]

print(
    f"\nlive escalated surfaces' distinct chunk_ids (notes touched): {len(live_surface_chunk_ids)}",
    file=sys.stderr,
)
print(
    f"  as % of all chunk_ids referenced anywhere in inventory ({len(all_chunk_ids)}): {len(live_surface_chunk_ids) / len(all_chunk_ids) * 100:.2f}%",
    file=sys.stderr,
)
print(
    f"live escalated surfaces' summed occurrence count: {live_surface_occurrence_sum}",
    file=sys.stderr,
)
print(
    f"  as % of total inventory occurrence count ({total_inventory_count}): {live_surface_occurrence_sum / total_inventory_count * 100:.2f}%",
    file=sys.stderr,
)

# ---- corpus total notes (answers checkpoints) ----
answers_dir = ROOT / "data" / "answers"
total_notes = 0
sources_checked = 0
if answers_dir.is_dir():
    for f in answers_dir.glob("*.jsonl"):
        sources_checked += 1
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    total_notes += 1
print(
    f"\ncorpus total notes (answers checkpoints, {sources_checked} sources): {total_notes}",
    file=sys.stderr,
)
if total_notes:
    print(
        f"  live escalated chunk_ids as % of corpus total notes: {len(live_surface_chunk_ids) / total_notes * 100:.2f}%",
        file=sys.stderr,
    )

# ---- load alias_map for page composition ----
with open(DATA / "alias_map.json", encoding="utf-8") as f:
    alias_map = json.load(f)
nodes = alias_map["nodes"]
surface_to_canonical = {}
canonical_to_members = {}
for node in nodes:
    canon = node["canonical"]
    members = [canon] + node.get("aliases", [])
    canonical_to_members[canon] = members
    for m in members:
        surface_to_canonical[m] = canon

print(f"\nalias_map nodes (pages): {len(nodes)}", file=sys.stderr)

page_stats_cache = {}


def get_page_stats(canonical):
    if canonical not in page_stats_cache:
        members = canonical_to_members.get(canonical, [canonical])
        chunk_ids = set()
        for m in members:
            inv = inventory.get(m)
            if inv:
                chunk_ids.update(inv["chunk_ids"])
        source_ids = set()
        for cid in chunk_ids:
            sid = source_id_from_chunk_id(cid)
            if sid:
                source_ids.add(sid)
        page_stats_cache[canonical] = (len(chunk_ids), len(source_ids))
    return page_stats_cache[canonical]


USABLE_MIN_NOTES = 30
USABLE_MAX_NOTES = 200
USABLE_MIN_SOURCES = 5

band_counts = Counter()
not_in_alias_map = 0
page_of_surface = {}
for s in live_distinct_surfaces:
    canon = surface_to_canonical.get(s)
    if canon is None:
        not_in_alias_map += 1
        continue
    notes, srcs = get_page_stats(canon)
    page_of_surface[s] = (canon, notes, srcs)
    if notes == 0:
        band = "empty"
    elif notes > USABLE_MAX_NOTES:
        band = "hub(>200)"
    elif notes < USABLE_MIN_NOTES:
        band = "small(<30)"
    elif srcs < USABLE_MIN_SOURCES:
        band = "mid-notes-but-<5-sources"
    else:
        band = "usable(30-200,5+src)"
    band_counts[band] += 1

print(
    f"\nlive escalated surfaces NOT found in alias_map at all: {not_in_alias_map}", file=sys.stderr
)
print("band distribution of live escalated surfaces' OWN current page:", file=sys.stderr)
for band, count in band_counts.most_common():
    print(f"  {band}: {count} ({count / len(live_distinct_surfaces) * 100:.1f}%)", file=sys.stderr)

already_grouped = sum(
    1
    for s in live_distinct_surfaces
    if surface_to_canonical.get(s) == s and len(canonical_to_members.get(s, [s])) > 1
)
print(
    f"live escalated surfaces that ARE the canonical of a page with other members already (fold/seed, not the escalation): {already_grouped}",
    file=sys.stderr,
)

singleton_pages = sum(
    1 for s in live_distinct_surfaces if get_page_stats(surface_to_canonical.get(s, s))[0] <= 1
)
print(
    f"live escalated surfaces whose current page has <=1 note: {singleton_pages}", file=sys.stderr
)

# ---- top by occurrence ----
print("\n--- TOP 30 live-escalated surfaces by occurrence weight ---", file=sys.stderr)
surface_weight = [
    (
        s,
        inventory[s]["count"],
        len(
            set(
                source_id_from_chunk_id(c)
                for c in inventory[s]["chunk_ids"]
                if source_id_from_chunk_id(c)
            )
        ),
    )
    for s in live_distinct_surfaces
]
surface_weight.sort(key=lambda x: -x[1])
for s, cnt, nsrc in surface_weight[:30]:
    canon, notes, srcs = page_of_surface.get(s, (None, 0, 0))
    print(
        f"  {s!r}: count={cnt} sources={nsrc} | own-page canonical={canon!r} page_notes={notes} page_sources={srcs}",
        file=sys.stderr,
    )

out = {
    "total_entries": len(entries),
    "distinct_surfaces": len(distinct_surfaces),
    "stale_entries": len(stale_entries),
    "live_entries": len(live_entries),
    "live_distinct_surfaces": len(live_distinct_surfaces),
    "stale_distinct_surfaces": len(stale_distinct_surfaces),
    "stale_batches": len(stale_batches),
    "total_batches_with_escalation": len(all_batches_with_escalation),
}
print("\nSUMMARY_JSON:" + json.dumps(out), file=sys.stderr)
