"""Every name page, before and after. Writes JSON for comparison."""
import json, sqlite3, sys
from axial.query.relations import find_notes

out = sys.argv[1]
con = sqlite3.connect("data/vault/notes.db")
c = con.cursor()
c.execute("""select nn.canonical, count(distinct n.source_id) s
             from note_names nn join notes n
               on n.chunk_id=nn.chunk_id and n.source_id=nn.source_id and n.back_matter=0
             group by nn.canonical""")
pages = c.fetchall()
con.close()

# Every over-limit page, plus a 400-page sample of the rest as the control.
over = [p for p, s in pages if s > 10]
under = [p for p, s in pages if s <= 10]
sample = under[::max(1, len(under) // 400)][:400]

result = {}
for canonical in over + sample:
    rows, total, _ = find_notes(canonical)
    result[canonical] = {
        "ids": [r.chunk_id for r in rows],
        "total": total,
        "sources": sorted({r.source_id for r in rows}),
    }
json.dump({"over": over, "sample": sample, "pages": result}, open(out, "w"), indent=0)
print(f"wrote {out}: {len(over)} over-limit pages, {len(sample)} control pages")
