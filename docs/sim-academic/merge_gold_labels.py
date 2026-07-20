"""Merge a simulated gold-labeler's JSON output into a filled label sheet.

Isolated development path (docs/sim-academic/, DEC-29). Reads the generated
``data/gold/label_sheet.xlsx`` and one model's labels JSON, and writes a filled copy
under ``data/sim/gold/labels/<model>/`` that ``axial eval`` can read as the answer
key. This is a format bridge (labels-JSON -> xlsx), not product code, and is torn
down with the rest of the simulated path.

Usage:
    python docs/sim-academic/merge_gold_labels.py <model> <labels.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

SHEET = Path("data/gold/label_sheet.xlsx")
LABEL_FIELDS = ("claim_type", "theory_school", "field", "empirical_scope", "polities_touched")


def main(model: str, labels_path: str) -> None:
    payload = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    labels = payload.get("labels", payload)  # tolerate {_meta, labels} or a bare id->labels map

    wb = load_workbook(SHEET)
    ws = wb["label_sheet"]
    col = {name: i for i, name in enumerate(c.value for c in ws[1])}

    missing = []
    for row in ws.iter_rows(min_row=2):
        chunk_id = row[col["chunk_id"]].value
        entry = labels.get(chunk_id)
        if entry is None:
            missing.append(chunk_id)
            continue
        for field in LABEL_FIELDS:
            if field in entry and field in col:
                row[col[field]].value = entry[field]

    out = Path("data/sim/gold/labels") / model / "label_sheet.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"wrote {out}  ({ws.max_row - 1} rows, {len(missing)} unlabelled)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python merge_gold_labels.py <model> <labels.json>")
    main(sys.argv[1], sys.argv[2])
