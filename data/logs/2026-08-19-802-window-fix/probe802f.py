from axial.query.relations import find_notes

rows, total, _ = find_notes("Charles Tilly")
srcs = [r.source_id for r in rows]
print(f"find_notes('Charles Tilly') at the DEFAULT limit")
print(f"  total={total}  returned={len(rows)}  distinct sources={len(set(srcs))}")
print(f"  tilly-1978 present: {any('tilly-1978' in s for s in srcs)}")
print()
print("  the tilly-1978 notes it now returns:")
for r in rows:
    if "tilly-1978" in (r.source_id or ""):
        print(f"    {r.chunk_id}")
        print(f"      {r.claim}")
