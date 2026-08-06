"""The two dev papers, 2026-08-02 baseline against the smoke-v7 records.

Same paper briefs, same theses, same analysis_ids -- only the underlying
records were re-run. Joins by paper_brief_id.
"""

import json
from pathlib import Path

LOG = Path(__file__).resolve().parent
ROOT = LOG.parents[2]
BEFORE = LOG / "before/paper-baseline/papers"
AFTER = ROOT / "data/papers"

NAMES = {
    "b02d747edc0bb416": "hollow-or-durable",
    "d5f983eafb05f8d6": "the-long-arc",
}


def figures(path: Path) -> dict:
    """A claim carrying `origin: null` is one the PAPER made; a claim carrying
    an `origin` block was lifted from a record. That is the "new (b)/(c)"
    the 2026-08-02 run reported, and it is not the same as the kind totals."""
    d = json.loads(path.read_text(encoding="utf-8"))
    claims = d.get("claims") or []
    kinds: dict[str, int] = {}
    new: dict[str, int] = {}
    for claim in claims:
        kind = claim.get("kind", "?")
        kinds[kind] = kinds.get(kind, 0) + 1
        if claim.get("origin") is None:
            new[kind] = new.get(kind, 0) + 1
    markdown = path.with_suffix(".md")
    words = len(markdown.read_text(encoding="utf-8").split()) if markdown.exists() else 0
    usd = sum(p.get("usd", 0.0) or 0.0 for p in (d.get("cost") or {}).get("by_pass", {}).values())
    return {
        "claims": len(claims),
        "a": kinds.get("a", 0),
        "b": kinds.get("b", 0),
        "c": kinds.get("c", 0),
        "new b": new.get("b", 0),
        "new c": new.get("c", 0),
        "words": words,
        "sources": len(d.get("bibliography") or []),
        "shape": (d.get("shape") or {}).get("band", "-"),
        "defects": len((d.get("shape") or {}).get("defects") or []),
        "confidence": (d.get("confidence") or {}).get("overall_band", "-"),
        "usd": round(usd, 4),
        "pin": d.get("corpus_pin", "?"),
    }


COLS = ["claims", "a", "b", "c", "new b", "new c", "words", "sources", "shape", "defects", "confidence", "usd"]

print("| paper | " + " | ".join(f"{c} b->a" for c in COLS) + " |")
print("|" + "---|" * (len(COLS) + 1))
for paper_id, name in NAMES.items():
    before_path, after_path = BEFORE / f"{paper_id}.json", AFTER / f"{paper_id}.json"
    if not after_path.exists():
        print(f"| {name} | not drafted yet |")
        continue
    b, a = figures(before_path), figures(after_path)
    cells = [f"{b[c]} -> {a[c]}" for c in COLS]
    print(f"| {name} | " + " | ".join(cells) + " |")
