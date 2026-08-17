"""Essay vs claim list, both citation modes, over the six single-record
papers in `data/papers/` (issue #784).

Zero model calls: both renders run over records already on disk, resolved
against the real vault. The first cut of this measurement compared a
`locator`-rendered essay against a `passage`-mode claim-list figure quoted
from DEC-72 -- two different modes in one comparison, which the verifier
caught. This renders all four cells.
"""

from __future__ import annotations

import glob
import json
import os

from axial.answer.reader import render_reader_answer
from axial.paper.reader import render_reader_paper
from axial.query.citations import LOCATOR, PASSAGE
from axial.paths import default_vault_dir
from axial.service.citation import render_record_for_serving

VAULT = default_vault_dir()

rows = []
for path in sorted(glob.glob("data/papers/*.json")):
    paper = json.load(open(path, encoding="utf-8"))
    if len(paper.get("source_analyses") or []) != 1:
        continue
    analysis_id = paper["source_analyses"][0]
    analysis = json.load(open(f"data/analyses/{analysis_id}.json", encoding="utf-8"))

    cells = {}
    for mode in (LOCATOR, PASSAGE):
        essay = render_reader_paper(
            render_record_for_serving(paper, citation_mode=mode, vault_dir=VAULT)
        )
        answer = render_reader_answer(
            render_record_for_serving(analysis, citation_mode=mode, vault_dir=VAULT)
        )
        cells[mode] = (len(essay.split()), len(answer.split()))
    rows.append((os.path.basename(path)[:8], cells))

header = f"{'paper':10}{'essay loc':>11}{'answer loc':>12}{'essay pas':>11}{'answer pas':>12}"
print(header)
print("-" * len(header))
totals = [0, 0, 0, 0]
for name, cells in rows:
    values = [cells[LOCATOR][0], cells[LOCATOR][1], cells[PASSAGE][0], cells[PASSAGE][1]]
    totals = [running + value for running, value in zip(totals, values)]
    print(f"{name:10}{values[0]:>11}{values[1]:>12}{values[2]:>11}{values[3]:>12}")
print("-" * len(header))
print(f"{'total':10}{totals[0]:>11}{totals[1]:>12}{totals[2]:>11}{totals[3]:>12}")
print(f"\npapers: {len(rows)}")
print(f"essay, passage vs locator : x{totals[2] / totals[0]:.2f}")
print(f"answer, passage vs locator: x{totals[3] / totals[1]:.2f}")
print(f"passage mode, answer vs essay: x{totals[3] / totals[2]:.2f}")
