import sqlite3, collections
con = sqlite3.connect("data/vault/notes.db")
c = con.cursor()
c.execute("""select nn.canonical, count(distinct n.source_id) s, count(*) n
             from note_names nn join notes n
               on n.chunk_id=nn.chunk_id and n.source_id=nn.source_id and n.back_matter=0
             group by nn.canonical""")
rows = c.fetchall()
tot = len(rows)
over = [r for r in rows if r[1] > 10]
print(f"name pages: {tot}")
print(f"pages drawing from more than 10 sources (default limit): {len(over)}  ({100*len(over)/tot:.1f}%)")
multi = [r for r in rows if r[1] >= 5]
print(f"pages drawing from 5+ sources (the usable band's floor): {len(multi)}")
print(f"  of those, over the limit: {len([r for r in multi if r[1]>10])}  ({100*len([r for r in multi if r[1]>10])/len(multi):.1f}%)")
print()
# how many sources are cut, and which sit late alphabetically
cut = collections.Counter()
appear = collections.Counter()
c.execute("""select nn.canonical, n.source_id
             from note_names nn join notes n
               on n.chunk_id=nn.chunk_id and n.source_id=nn.source_id and n.back_matter=0
             group by nn.canonical, n.source_id""")
by_page = collections.defaultdict(list)
for canon, src in c.fetchall():
    by_page[canon].append(src)
for canon, srcs in by_page.items():
    srcs = sorted(srcs)
    for s in srcs: appear[s] += 1
    if len(srcs) > 10:
        for s in srcs[10:]: cut[s] += 1
print("== sources most often cut by the limit=10 alphabetical window ==")
print(f"{'source':40} {'pages cut':>9} {'pages on':>9} {'cut %':>7}")
for s, n in cut.most_common(12):
    print(f"{s:40} {n:9} {appear[s]:9} {100*n/appear[s]:6.1f}%")
print()
print("== the same, for sources alphabetically EARLY (never cut) ==")
for s in sorted(appear)[:6]:
    print(f"{s:40} {cut.get(s,0):9} {appear[s]:9} {100*cut.get(s,0)/appear[s]:6.1f}%")
