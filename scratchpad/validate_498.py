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
present as a standalone name node. Those three rows describe the RAW
inventory and are unaffected by anything below. Treat 151 as an upper bound
on folds, never a prediction -- the ambiguity refusal and the fold-away
pruning below both drop some of the 151 before the merge call ever sees them.

**This script replicates `run_merge_names`'s own pre-candidate pruning**
(issue #463's `fold_groups`: only ONE representative per fold group -- the
lexicographically first -- reaches candidate generation), because a first
version of this script measured the raw, unpruned inventory and reported 139
proposed pairs while the real run only ever proposed 131. The missing 8 were
exactly the corpus's most-cited acronyms (`CIA`, `PLO`, `UN`, `USA`, `IRA`,
`FLN`, `PFLP`, `SLA`): each already sits in a fold group with its own dotted
form (`CIA`/`C.I.A.`), and the SURVIVING representative was not the bare
acronym string, so a literal-string match silently missed the pair. The
production rule (`_family_parenthesized_acronym`) now matches through that
same fold, and this script now feeds it the same pruned view the real run
does, so its own count agrees with the run's.

An earlier version of this script also flagged an "initials do not match"
reading as a likely collision. Retired (2026-07-30): measured against the
live corpus it flagged 85 of 196 pairs -- almost all of them non-English
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
    _normalize_form,
    fold_groups,
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


def _prune_to_fold_representatives(
    entries: list[tuple[str, str | None, int]],
) -> list[tuple[str, str | None, int]]:
    """The same pruning `run_merge_names` applies before ANY candidate family
    runs (issue #463): every surface form identical to another once folded
    (`_normalize_form`) is collapsed to one representative, the
    lexicographically first. Only that view is what the real merge run's own
    family 3 ever sees."""
    surface_forms = [surface for surface, _kind, _count in entries]
    folded_away: set[str] = set()
    for group in fold_groups(surface_forms):
        _representative, *duplicates = sorted(group)
        folded_away.update(duplicates)
    return [entry for entry in entries if entry[0] not in folded_away]


def main() -> None:
    if not DEFAULT_INVENTORY_PATH.exists():
        print(
            f"no inventory at {DEFAULT_INVENTORY_PATH.resolve()} -- run this from the main "
            "checkout (D:/axial), where `data/` exists, not from a worktree",
            file=sys.stderr,
        )
        raise SystemExit(1)

    rows = _load_inventory(DEFAULT_INVENTORY_PATH)
    entries_raw = [(row["surface"], row.get("kind"), row.get("count", 0)) for row in rows]

    # Descriptive facts about the raw inventory -- unaffected by pruning.
    carriers_raw: dict[str, list[str]] = {}
    for surface, _kind, _count in entries_raw:
        acronym = _extract_parenthesized_acronym(surface)
        if acronym is None or acronym == surface:
            continue
        carriers_raw.setdefault(acronym, []).append(surface)
    standalone_raw = {surface for surface, _kind, _count in entries_raw}
    surfaces_with_acronym = sum(len(surfaces) for surfaces in carriers_raw.values())
    also_standalone_raw = {acronym for acronym in carriers_raw if acronym in standalone_raw}

    # What the real run's family 3 actually sees: the fold-away-pruned view.
    entries = _prune_to_fold_representatives(entries_raw)
    surface_forms = [surface for surface, _kind, _count in entries]
    folded_index: dict[str, list[str]] = {}
    for surface in surface_forms:
        folded_index.setdefault(_normalize_form(surface), []).append(surface)

    carriers: dict[str, list[str]] = {}
    for surface in surface_forms:
        acronym = _extract_parenthesized_acronym(surface)
        if acronym is None or acronym == surface:
            continue
        carriers.setdefault(_normalize_form(acronym), []).append(surface)

    also_standalone = {
        folded_acronym: surfaces
        for folded_acronym, surfaces in carriers.items()
        if folded_acronym in folded_index
    }
    refused = {
        folded_acronym: surfaces
        for folded_acronym, surfaces in also_standalone.items()
        if len(surfaces) > 1
    }
    dropped_pairs = sum(len(surfaces) for surfaces in refused.values())

    pairs = _family_parenthesized_acronym(entries)

    # Of the pairs actually proposed, how many needed the fold to be found
    # at all -- the count that would have been silently lost by a literal
    # string match (the exact defect this fix closes).
    fold_rescued = [
        (representative, surface)
        for representative, surface in pairs
        if representative != _extract_parenthesized_acronym(surface)
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inventory_path": str(DEFAULT_INVENTORY_PATH.resolve()),
        "inventory_rows": len(rows),
        "surfaces_with_parenthesized_acronym": surfaces_with_acronym,
        "distinct_acronyms": len(carriers_raw),
        "distinct_acronyms_also_standalone": len(also_standalone_raw),
        "acronyms_refused_multiple_expansions": len(refused),
        "pairs_dropped_by_refusal": dropped_pairs,
        "new_candidate_pairs": len(pairs),
        "pairs_resolved_via_folded_representative": len(fold_rescued),
        "refused_acronym_groups": [
            {"folded_acronym": folded_acronym, "surfaces": sorted(surfaces)}
            for folded_acronym, surfaces in sorted(refused.items())
        ],
        "fold_rescued_pairs": [
            {"representative": representative, "surface": surface}
            for representative, surface in sorted(fold_rescued)
        ],
    }

    rows_report = [
        ("inventory rows", report["inventory_rows"]),
        (
            "surfaces carrying a parenthesized acronym (raw)",
            report["surfaces_with_parenthesized_acronym"],
        ),
        ("distinct acronyms among them (raw)", report["distinct_acronyms"]),
        (
            "  also present as a standalone name node (raw)",
            report["distinct_acronyms_also_standalone"],
        ),
        ("", ""),
        ("-- what the run's own family 3 actually sees (pruned) --", ""),
        (
            "  refused: carried by >1 distinct surface",
            report["acronyms_refused_multiple_expansions"],
        ),
        ("  pairs dropped by that refusal", report["pairs_dropped_by_refusal"]),
        ("new candidate pairs the rule generates", report["new_candidate_pairs"]),
        (
            "  of those, resolved via a folded representative",
            report["pairs_resolved_via_folded_representative"],
        ),
    ]
    print("issue #498 (D2) -- parenthesized-acronym candidate rule, measured over the live layer")
    print("-" * 78)
    for label, value in rows_report:
        if label == "":
            print()
            continue
        if value == "":
            print(label)
            continue
        print(f"{label:<52} {value:>8}")

    if refused:
        print("\nrefused (acronym carried by more than one distinct surface):")
        for folded_acronym, surfaces in sorted(refused.items()):
            print(f"  {folded_acronym!r}:")
            for surface in sorted(surfaces):
                print(f"    - {surface!r}")

    if fold_rescued:
        print("\nresolved via a folded representative (would be lost on a literal match):")
        for representative, surface in sorted(fold_rescued):
            print(f"  {representative!r} <- {surface!r}")

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEFAULT_LOG_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {report_path.resolve()}")


if __name__ == "__main__":
    main()
