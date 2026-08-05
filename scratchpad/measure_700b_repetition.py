"""Issue #700 half 2: the repetition figure for the six drafts already on disk.

Runs `axial.paper.shape.compute_repetition` (branch `700b-draft-repetition-metric`,
no model call) over the six Phase C papers from the 2026-08-05 model measurement.
Those six are persisted as rendered markdown, not as paper records with a
`drafts` list, so sections are recovered by splitting on the `## ` headings the
renderer writes -- one heading per planned section. A nested `### ` stays inside
its parent section, which is deliberate: a section that restates its own heading
is part of what the judges were complaining about, not a separate section.

Run from D:\\axial with the branch's code on the path:

    uv run --project ".claude/worktrees/700b-draft-repetition-metric" \
        python scratchpad/measure_700b_repetition.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from axial.paper.shape import compute_repetition

OUTPUTS = Path("data/logs/2026-08-05-luna-vs-glm/outputs")
SHAPE_BAND = "band"
LOG_DIR = Path("data/logs/2026-08-05-700b-draft-repetition")
HEADING = re.compile(r"^## (.+)$", re.MULTILINE)


def sections_of(markdown: str) -> list[dict[str, str]]:
    matches = list(HEADING.finditer(markdown))
    sections: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append(
            {"section_id": f"{index + 1:02d}-{match.group(1)[:60]}", "prose": markdown[start:end]}
        )
    return sections


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(OUTPUTS.glob("paper-*.md")):
        stem = path.stem.removeprefix("paper-")
        sections = sections_of(path.read_text(encoding="utf-8"))
        result = compute_repetition(sections)
        shape_path = OUTPUTS / f"shape-{stem}.json"
        band = None
        if shape_path.exists():
            band = json.loads(shape_path.read_text(encoding="utf-8")).get(SHAPE_BAND)
        worst = max(result.pairs, key=lambda p: p["shared_ngrams"], default=None)
        rows.append(
            {
                "draft": stem,
                "sections": len(sections),
                "repetition": round(result.fraction, 4),
                "shape_band": band,
                "pairs_sharing_ngrams": len(result.pairs),
                "worst_pair": worst,
            }
        )
        print(
            f"{stem:38s} sections={len(sections):2d} "
            f"repetition={result.fraction:7.4f}  shape={band}  "
            f"pairs={len(result.pairs)}"
        )

    (LOG_DIR / "repetition.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fractions = [r["repetition"] for r in rows]
    print(
        f"\nn={len(rows)} min={min(fractions):.4f} max={max(fractions):.4f} "
        f"mean={sum(fractions) / len(fractions):.4f}"
    )
    print(f"wrote {LOG_DIR / 'repetition.json'}")


if __name__ == "__main__":
    main()
