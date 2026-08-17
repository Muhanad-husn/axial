"""Re-render every persisted record through the reader render (issue #783).

No model calls, no retrieval: reads data/papers/*.json and data/analyses/*.json,
resolves citations against data/vault, and writes the reader render beside a
copy of today's audit render for comparison.
"""
from __future__ import annotations

import copy, json, re, sys
from pathlib import Path

from axial.answer.reader import render_reader_answer
from axial.answer.render import render_markdown
from axial.paper.reader import render_reader_paper
from axial.paper.render import render_paper
from axial.query.citations import resolve_record_citations

LOG = Path("data/logs/2026-08-17-783-reader-render")
OUT = LOG / "rendered"
OUT.mkdir(parents=True, exist_ok=True)
VAULT = Path("data/vault")
CHUNK_ID_RE = re.compile(r"[a-z]+-\d{4}-[0-9a-f]{12}_\d+_")
MODE = sys.argv[1] if len(sys.argv) > 1 else "locator"

records = []
for path in sorted(Path("data/papers").glob("*.json")):
    records.append(("paper", path))
for path in sorted(Path("data/analyses").glob("*.json")):
    records.append(("analysis", path))

rows = []
with (LOG / "run.jsonl").open("w", encoding="utf-8") as journal:
    for kind, path in records:
        record = json.loads(path.read_text(encoding="utf-8"))
        audit = render_paper(record) if kind == "paper" else render_markdown(record)
        resolved = resolve_record_citations(
            copy.deepcopy(record), citation_mode=MODE, vault_dir=VAULT
        )
        reader = render_reader_paper(resolved) if kind == "paper" else render_reader_answer(resolved)
        (OUT / f"{path.stem}.reader.md").write_text(reader, encoding="utf-8")
        (OUT / f"{path.stem}.audit.md").write_text(audit, encoding="utf-8")

        grounds = [
            g
            for claim in (record.get("claims") or [])
            for g in (claim.get("grounds") or [])
            if g.get("ref_type") == "chunk"
        ]
        resolved_grounds = [
            g
            for claim in (resolved.get("claims") or [])
            for g in (claim.get("grounds") or [])
            if g.get("ref_type") == "chunk" and isinstance(g.get("citation"), dict)
        ]
        row = {
            "kind": kind,
            "id": path.stem,
            "audit_words": len(audit.split()),
            "reader_words": len(reader.split()),
            "grounds": len(grounds),
            "grounds_resolved": len(resolved_grounds),
            "reader_chunk_ids": len(CHUNK_ID_RE.findall(reader)),
            "reader_usage_ratio": reader.count("usage_ratio"),
            "reader_markers_left": len(re.findall(r"\[pc-\d+\]", reader)),
            "reader_raw_pointers": reader.count("chunk:"),
            "audit_chunk_ids": len(CHUNK_ID_RE.findall(audit)),
        }
        rows.append(row)
        journal.write(json.dumps(row, ensure_ascii=False) + "\n")
        journal.flush()

def total(field):
    return sum(row[field] for row in rows)

print(f"mode={MODE} records={len(rows)}")
print(f"grounds {total('grounds_resolved')}/{total('grounds')} resolved")
print(f"reader: chunk ids {total('reader_chunk_ids')}, usage_ratio {total('reader_usage_ratio')}, "
      f"pc markers left {total('reader_markers_left')}, raw pointers {total('reader_raw_pointers')}")
print(f"audit: chunk ids {total('audit_chunk_ids')}")
print(f"words: audit {total('audit_words')} -> reader {total('reader_words')}")
for row in rows:
    if row["reader_chunk_ids"] or row["reader_markers_left"] or row["reader_raw_pointers"]:
        print("  outlier:", row)
