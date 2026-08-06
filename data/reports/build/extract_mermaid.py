"""Extract fenced ```mermaid blocks from a report into individual .mmd files.

Writes `build/diagrams/<stem>-NN.mmd` for each diagram, in document order, and
prints the count. A separate step (render via mmdc, see README) turns those
into PNGs; `assemble_docx_source.py` then swaps the fences for image links.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1]
DIAGRAMS = REPORTS / "build" / "diagrams"

MERMAID = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)


def main() -> None:
    stem = sys.argv[1] if len(sys.argv) > 1 else "axial-technical-report"
    src = REPORTS / f"{stem}.md"
    text = src.read_text(encoding="utf-8")
    DIAGRAMS.mkdir(parents=True, exist_ok=True)

    matches = list(MERMAID.finditer(text))
    for i, m in enumerate(matches, start=1):
        mmd = DIAGRAMS / f"{stem}-{i:02d}.mmd"
        mmd.write_text(m.group(1), encoding="utf-8")

    print(f"{len(matches)} diagrams extracted to {DIAGRAMS}")


if __name__ == "__main__":
    main()
