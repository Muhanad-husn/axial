import sqlite3, json, glob, collections
con = sqlite3.connect("data/vault/notes.db"); con.row_factory = sqlite3.Row
c = con.cursor()
c.execute("""select nn.canonical, n.source_id
             from note_names nn join notes n
               on n.chunk_id=nn.chunk_id and n.source_id=nn.source_id and n.back_matter=0
             group by nn.canonical, n.source_id""")
by_page = collections.defaultdict(list)
for r in c.fetchall():
    by_page[r["canonical"]].append(r["source_id"])

def name_forms(value):
    v = value.strip()
    if "," in v:
        last, first = [p.strip() for p in v.split(",", 1)]
        return [f"{first} {last}", last, v]
    return [v, v.split()[-1]]

print(f"{'author page':26} {'srcs':>5} {'own rank':>9} {'in top 10':>10}  own book")
rows = []
for f in sorted(glob.glob("data/source_meta/*.json")):
    m = json.load(open(f, encoding="utf-8"))
    a = (m.get("author") or {}).get("value")
    sid = m["source_id"]
    if not a:
        continue
    for page in name_forms(a):
        if page not in by_page:
            continue
        srcs = sorted(by_page[page])
        if sid not in srcs:
            break
        rank = srcs.index(sid) + 1
        rows.append((page, len(srcs), rank, sid))
        break

over = [r for r in rows if r[1] > 10]
for page, n, rank, sid in sorted(over, key=lambda x: -x[1]):
    print(f"{page:26} {n:5} {rank:9} {str(rank <= 10):>10}  {sid}")
print(f"\nauthor pages found at all: {len(rows)}")
print(f"author pages drawing from more than 10 sources: {len(over)}")
cut = [r for r in over if r[2] > 10]
print(f"of those, the author's OWN book falls outside the limit=10 window: {len(cut)}")
