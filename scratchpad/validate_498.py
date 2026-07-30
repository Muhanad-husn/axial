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
a prediction -- the merge's own evidence check still has to decide each pair,
and the ambiguity refusal below now also drops some of the 151 outright.

An earlier version of this script flagged an "initials do not match" reading
as a likely collision. Retired (2026-07-30): measured against the live
corpus it flagged 85 of 196 pairs -- almost all of them non-English
expansions the initials heuristic cannot read (`AKP` <- `Justice and
Development Party`) -- while missing both real fusions the corpus actually
had (`SDF`, `CDR`). The refusal below is the real signal for those: an
acronym carried by more than one distinct surface form.
"""

from __future__ import annotations

import json
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


def _load_inventory(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


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

    # Every distinct surface form carrying a parenthesized acronym, grouped
    # by the acronym itself -- the same grouping `_family_parenthesized_
    # acronym` does internally, recomputed here only to report it (the
    # production function does not expose which acronyms it refused).
    carriers: dict[str, list[str]] = {}
    for surface, _kind, _count in entries:
        acronym = _extract_parenthesized_acronym(surface)
        if acronym is None or acronym == surface:
            continue
        carriers.setdefault(acronym, []).append(surface)

    surfaces_with_acronym = sum(len(surfaces) for surfaces in carriers.values())
    also_standalone = {
        acronym: surfaces for acronym, surfaces in carriers.items() if acronym in standalone
    }
    refused = {
        acronym: surfaces for acronym, surfaces in also_standalone.items() if len(surfaces) > 1
    }
    dropped_pairs = sum(len(surfaces) for surfaces in refused.values())

    pairs = _family_parenthesized_acronym(entries)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inventory_path": str(DEFAULT_INVENTORY_PATH.resolve()),
        "inventory_rows": len(rows),
        "surfaces_with_parenthesized_acronym": surfaces_with_acronym,
        "distinct_acronyms": len(carriers),
        "distinct_acronyms_also_standalone": len(also_standalone),
        "acronyms_refused_multiple_expansions": len(refused),
        "pairs_dropped_by_refusal": dropped_pairs,
        "new_candidate_pairs": len(pairs),
        "refused_acronym_groups": [
            {"acronym": acronym, "surfaces": sorted(surfaces)}
            for acronym, surfaces in sorted(refused.items())
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
        (
            "  refused: carried by >1 distinct surface",
            report["acronyms_refused_multiple_expansions"],
        ),
        ("  pairs dropped by that refusal", report["pairs_dropped_by_refusal"]),
        ("new candidate pairs the rule generates", report["new_candidate_pairs"]),
    ]
    print("issue #498 (D2) -- parenthesized-acronym candidate rule, measured over the live layer")
    print("-" * 78)
    for label, value in rows_report:
        print(f"{label:<52} {value:>8}")

    if refused:
        print("\nrefused (acronym carried by more than one distinct surface):")
        for acronym, surfaces in sorted(refused.items()):
            print(f"  {acronym!r}:")
            for surface in sorted(surfaces):
                print(f"    - {surface!r}")

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEFAULT_LOG_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {report_path.resolve()}")


if __name__ == "__main__":
    main()
