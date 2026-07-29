"""Read-only validation for issue #498 (D2): the parenthesized-acronym merge
candidate, measured against the live `data/names/inventory.jsonl` layer.

LLM-free, zero model calls, read-only. It never writes into `data/names/` (or
anywhere else under `data/`) and never invokes `axial names merge` -- it only
runs `axial.name_candidates`' own deterministic string rule over the
inventory already on disk.

It inserts THIS WORKTREE's own `src/` at the front of `sys.path` before
importing anything from `axial`, so it always measures this branch's rule
regardless of which checkout the interpreter itself came from. Run it from
the orchestrator's main checkout, where `data/` actually exists (it does not
exist inside a worktree):

    cd D:/axial
    uv run python .claude/worktrees/02-acronym-lookup-key/scratchpad/validate_498.py

Expected published counts to check this script's own output against (the
plan's own measurement, `plans/name-layer-rekey/README.md`): 301 surfaces
carrying a parenthesized acronym, 260 distinct acronyms, 151 of them also
present as a standalone name node. Treat 151 as an upper bound on folds, never
a prediction -- the merge's own evidence check still has to decide each pair.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_WORKTREE_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_WORKTREE_SRC))

from axial.name_candidates import (  # noqa: E402
    _extract_parenthesized_acronym,
    _family_parenthesized_acronym,
)

DEFAULT_INVENTORY_PATH = Path("data/names/inventory.jsonl")
DEFAULT_LOG_DIR = Path("data/logs/2026-07-30-validate-498")

# Common English function words, stripped before comparing an acronym's own
# letters against the initials of the words around it -- this is a REPORTING
# heuristic for this script alone (never a production gate): `AANES` skips
# "of" and folds "and" into its own letter, so a bare initials-of-every-word
# check would flag it as a mismatch even though it is a real (if
# stopword-skipping) initialism. Good enough to separate an obvious
# collision from an obvious expansion for a human to read, not a decider.
_STOPWORDS = {"of", "the", "and", "in", "for", "a", "an", "to", "on", "at", "&"}


def _load_inventory(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _expected_initials(surface: str) -> str:
    """The initials of `surface`'s own non-stopword words, with its
    parenthetical removed -- compared against the acronym itself to flag a
    likely collision (`ABC`-shaped: the letters do not match) versus a
    likely expansion (`AANS`-shaped: they do)."""
    without_parens = re.sub(r"\([^()]*\)", "", surface)
    words = [w for w in re.findall(r"[A-Za-z]+", without_parens) if w.lower() not in _STOPWORDS]
    return "".join(word[0] for word in words).upper()


def main() -> None:
    if not DEFAULT_INVENTORY_PATH.exists():
        print(
            f"no inventory at {DEFAULT_INVENTORY_PATH.resolve()} -- run this from the main "
            "checkout (D:/axial), where `data/` exists, not from a worktree",
            file=sys.stderr,
        )
        raise SystemExit(1)

    rows = _load_inventory(DEFAULT_INVENTORY_PATH)
    entries = [(row["surface"], row.get("kind"), row.get("count", 0)) for row in rows]
    standalone = {surface for surface, _kind, _count in entries}

    acronym_surfaces: list[tuple[str, str]] = []
    acronyms_seen: set[str] = set()
    for surface, _kind, _count in entries:
        acronym = _extract_parenthesized_acronym(surface)
        if acronym is not None:
            acronym_surfaces.append((surface, acronym))
            acronyms_seen.add(acronym)

    also_standalone = {acronym for _surface, acronym in acronym_surfaces if acronym in standalone}

    pairs = _family_parenthesized_acronym(entries)

    expansions: list[tuple[str, str]] = []
    collisions: list[tuple[str, str, str]] = []
    for acronym, surface in pairs:
        expected = _expected_initials(surface)
        if expected == acronym:
            expansions.append((acronym, surface))
        else:
            collisions.append((acronym, surface, expected))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inventory_path": str(DEFAULT_INVENTORY_PATH.resolve()),
        "inventory_rows": len(rows),
        "surfaces_with_parenthesized_acronym": len(acronym_surfaces),
        "distinct_acronyms": len(acronyms_seen),
        "distinct_acronyms_also_standalone": len(also_standalone),
        "new_candidate_pairs": len(pairs),
        "expansion_shaped_pairs": len(expansions),
        "collision_shaped_pairs": len(collisions),
        "collision_pairs": [
            {"acronym": acronym, "surface": surface, "expected_initials": expected}
            for acronym, surface, expected in collisions
        ],
    }

    rows_report = [
        ("inventory rows", report["inventory_rows"]),
        (
            "surfaces carrying a parenthesized acronym",
            report["surfaces_with_parenthesized_acronym"],
        ),
        ("distinct acronyms among them", report["distinct_acronyms"]),
        ("  also present as a standalone name node", report["distinct_acronyms_also_standalone"]),
        ("new candidate pairs the rule generates", report["new_candidate_pairs"]),
        ("  expansion-shaped (initials match)", report["expansion_shaped_pairs"]),
        ("  collision-shaped (initials do not match)", report["collision_shaped_pairs"]),
    ]
    print("issue #498 (D2) -- parenthesized-acronym candidate rule, measured over the live layer")
    print("-" * 78)
    for label, value in rows_report:
        print(f"{label:<52} {value:>8}")

    if collisions:
        print("\ncollision-shaped pairs (acronym vs surface, expected initials):")
        for acronym, surface, expected in collisions:
            print(f"  {acronym!r} vs {surface!r} (expected {expected!r})")

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEFAULT_LOG_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {report_path.resolve()}")


if __name__ == "__main__":
    main()
