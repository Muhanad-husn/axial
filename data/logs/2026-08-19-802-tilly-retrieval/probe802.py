from axial.query.relations import find_notes
for lim in (10, 15, 16, 20, 21, 25, 30):
    rows, total, res = find_notes("Charles Tilly", limit=lim)
    srcs = [r.source_id for r in rows]
    print(f"limit={lim:3}  total={total:4}  returned={len(rows):3}  tilly-1978 present: {any('tilly-1978' in s for s in srcs)}")
    if lim == 10:
        print("   sources returned:", srcs)
