import sqlite3, json, glob, os, collections
con = sqlite3.connect("data/vault/notes.db"); con.row_factory = sqlite3.Row
c = con.cursor()

# author -> source_id, from source_meta
authors = {}
for f in glob.glob("data/source_meta/*.json"):
    m = json.load(open(f, encoding="utf-8"))
    a = (m.get("author") or {}).get("value")
    if a:
        authors.setdefault(a.split(",")[0].strip(), []).append(m["source_id"])

c.execute("""select nn.canonical, n.source_id
             from note_names nn join notes n
               on n.chunk_id=nn.chunk_id and n.source_id=nn.source_id and n.back_matter=0
             group by nn.canonical, n.source_id""")
by_page = collections.defaultdict(list)
for r in c.fetchall():
    by_page[r["canonical"]].append(r["source_id"])

print(f"{'author name page':26} {'srcs':>4} {'own book on page':>16} {'in window(10)':>13}")
hits = 0
for author, sids in sorted(authors.items()):
    for page in (author, author.split()[-1]):
        if page not in by_page:
            continue
        srcs = sorted(by_page[page])
        own = [s for s in sids if s in srcs]
        if not own:
            continue
        in_window = all(srcs.index(s) < 10 for s in own)
        if len(srcs) > 10:
            hits += 1
            print(f"{page:26} {len(srcs):4} {','.join(own):>16} {str(in_window):>13}")
        break
print(f"\nauthor pages over the limit: {hits}")
