"""Build a .docx from a report whose ```mermaid fences render natively on
GitHub but need a rasterised stand-in for Word.

Pipeline: extract each fenced mermaid block (extract_mermaid.py, run first,
separately, since it shells out to `npx @mermaid-js/mermaid-cli` and that
step is slow and network-dependent on a cold cache) -> this script splices
the already-rendered PNGs (`build/diagrams/<stem>-NN.png`) back into a copy
of the markdown as image links -> hands that copy to md_to_docx.convert().

    uv run python data/reports/build/extract_mermaid.py axial-technical-report
    # then render build/diagrams/*.mmd -> *.png with mmdc (see README)
    uv run python data/reports/build/build_docx_with_diagrams.py axial-technical-report

The canonical .md is never modified -- the substituted copy is a build
artifact under build/, regenerated every run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from md_to_docx import convert  # noqa: E402

REPORTS = Path(__file__).resolve().parents[1]
DIAGRAMS = REPORTS / "build" / "diagrams"

MERMAID = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)


def splice(stem: str) -> Path:
    src = REPORTS / f"{stem}.md"
    text = src.read_text(encoding="utf-8")

    def replace(match: re.Match, counter: list[int] = [0]) -> str:
        counter[0] += 1
        png = DIAGRAMS / f"{stem}-{counter[0]:02d}.png"
        if not png.exists():
            raise FileNotFoundError(
                f"missing {png} -- run extract_mermaid.py and render the .mmd files first"
            )
        return f"![diagram](build/diagrams/{png.name})"

    spliced = MERMAID.sub(replace, text)
    out = REPORTS / "build" / f"{stem}.docx-source.md"
    out.write_text(spliced, encoding="utf-8")
    return out


def main() -> None:
    stem = sys.argv[1] if len(sys.argv) > 1 else "axial-technical-report"
    spliced = splice(stem)
    convert(spliced, REPORTS / f"{stem}.docx")


if __name__ == "__main__":
    main()
