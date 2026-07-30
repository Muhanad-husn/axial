"""Read-only validation for issue #508: the citation channel and the nine
residue shapes, measured against the live name layer, before and after.

LLM-free, zero model calls, read-only. It reads `data/answers/`,
`data/names/inventory.jsonl`, `data/names/alias_map.json` and
`data/names/index.json`, and writes nothing anywhere under `data/` except
its own log directory.

**"Before" is the live layer itself, not a reimplementation of it.**
`inventory.jsonl` on disk IS what `main`'s `iter_name_occurrences` produced
over these same answer records, and `alias_map.json`/`index.json` are the
pages that inventory actually grew, so the before side needs no git-show
trick: it is read off the artifacts. "After" re-derives the inventory from
the same answer records through THIS WORKTREE's `axial.names`, then asks
which of the live layer's own nodes still have a surviving member surface.

**Row B is only measured when `data/names/section_classes.json` exists.**
Classifying a heading is one flash call and this script makes none, so a
run with no cache present reports the other nine rows and says so. To
include row B, build the cache first with one real inventory run
(`uv run axial names build`) and re-run this script; it will pick the cache
up. Either way, the report states which rows are in the number.

Run it from the orchestrator's main checkout, where `data/` actually
exists (it does not exist inside a worktree):

    cd D:/axial
    uv run python .claude/worktrees/03-citation-channel-cut/scratchpad/validate_508.py

Expected published figures to check this script's own numbers against
(issue #508's own measurement): 78,198 surfaces before, 21,666 dropped
(27.7%), index 62,704 -> 46,805 pages (-25.4%), 15,899 pages removed,
1,991 surviving pages losing members, and of the 2,010 pages at 10+ member
notes today, 140 removed / 1,814 still at 10+ / 56 falling below 10. If
this script disagrees, say so rather than tuning the script to match: the
published table was measured per-row in isolation, and rows overlap, so a
union is not the sum of its rows.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_WORKTREE_ROOT / "src"))

from axial.interrogate import _default_answers_dir  # noqa: E402
from axial.materialize import load_inventory, member_chunk_ids_for_node  # noqa: E402
from axial.name_sections import BACK_MATTER_CLASSES, load_section_classes  # noqa: E402
from axial.names import (  # noqa: E402
    build_inventory,
    carries_author_year_citation,
    collect_occurrences,
    is_apparatus_pointer_shaped,
    is_date_shaped,
    is_locator_shaped,
    is_numeral_only_surface,
    is_reference_pointer_shaped,
    is_source_pointer_shaped,
    load_answer_records,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH  # noqa: E402

NAMES_DIR = Path("data/names")
DEFAULT_LOG_DIR = Path("data/logs/2026-07-30-validate-508")

GATHER_FLOOR = 10  # config/pipeline.yaml's `gather.min_members`

# Row -> predicate, for the per-row attribution table only. The cut itself
# is `axial.names.is_cut_from_name_space` plus the two non-shape rows; this
# table exists so a dropped surface can be attributed to a row, and rows
# overlap on purpose (`Table 4.1` is both D and E).
SHAPE_ROWS: dict[str, Any] = {
    "C bare numeral or century": is_numeral_only_surface,
    "D apparatus pointer": is_apparatus_pointer_shaped,
    "E locator": is_locator_shaped,
    "F date or date range": is_date_shaped,
    "G page/volume/ibid reference": is_reference_pointer_shaped,
    "H author-year citation": carries_author_year_citation,
    "P source/reference/[N] pointer": is_source_pointer_shaped,
    "S not-in-passage sentinel": lambda surface: surface == "not-in-passage",
}


def _share(count: int, denom: int) -> float:
    return round(100 * count / denom, 1) if denom else 0.0


def main() -> None:
    answers_dir = _default_answers_dir(DEFAULT_PIPELINE_CONFIG_PATH)
    inventory_path = NAMES_DIR / "inventory.jsonl"
    alias_map_path = NAMES_DIR / "alias_map.json"
    index_path = NAMES_DIR / "index.json"
    for path in (answers_dir, inventory_path, alias_map_path):
        if not path.exists():
            print(
                f"missing {path.resolve()} -- run this from the main checkout (D:/axial), "
                "where `data/` exists, not from a worktree",
                file=sys.stderr,
            )
            raise SystemExit(1)

    # --- before: the live artifacts themselves ------------------------------
    inventory_before = load_inventory(inventory_path)
    surfaces_before = set(inventory_before)
    nodes = json.loads(alias_map_path.read_text(encoding="utf-8")).get("nodes", [])
    # `index.json` is `{version, generated_at, names: [...]}` -- the page count
    # is the length of `names`, never of the wrapper object.
    index_before = (
        len(json.loads(index_path.read_text(encoding="utf-8"))["names"])
        if index_path.is_file()
        else len(nodes)
    )

    # --- after: this branch's own inventory over the same answer records ----
    section_classes = load_section_classes(NAMES_DIR / "section_classes.json")
    back_matter = {
        heading for heading, label in section_classes.items() if label in BACK_MATTER_CLASSES
    }
    row_b_measured = bool(section_classes)
    # The class breakdown is what caught the first run's defect: 11 endnote
    # headings and 15 pieces of argument prose had landed in `front matter`.
    # Every cut heading goes into the report verbatim so the next reader can
    # check the label set by eye rather than by re-deriving it.
    class_counts = Counter(section_classes.values())
    headings_by_class: dict[str, list[str]] = {}
    for heading, label in sorted(section_classes.items()):
        if label != "body":
            headings_by_class.setdefault(label, []).append(heading)

    records = load_answer_records(answers_dir)
    entries_after = build_inventory(
        collect_occurrences(records, is_back_matter_section=back_matter.__contains__)
    )
    surfaces_after = {entry.surface_form for entry in entries_after}
    inventory_after = {
        entry.surface_form: {"chunk_ids": list(entry.chunk_ids)} for entry in entries_after
    }

    dropped = surfaces_before - surfaces_after
    minted = surfaces_after - surfaces_before  # expected empty; reported if not

    # Per-row attribution over the dropped set. A surface can match several
    # rows; `citations only` is what is left once no shape row and no
    # back-matter section explains it.
    row_counts: Counter[str] = Counter()
    for surface in dropped:
        matched = False
        for row, predicate in SHAPE_ROWS.items():
            if predicate(surface):
                row_counts[row] += 1
                matched = True
        if not matched:
            row_counts["A/B citation channel or back-matter section"] += 1

    # --- pages: which of the live layer's own nodes survive -----------------
    removed_pages = 0
    rekeyed_pages = 0
    untouched_pages = 0
    big_before = 0
    big_removed = 0
    big_still_big = 0
    big_fell_below_floor = 0
    for node in nodes:
        members = [node["canonical"], *node.get("aliases", [])]
        surviving = [member for member in members if member in surfaces_after]
        before_notes = len(member_chunk_ids_for_node(node, inventory_before))
        after_notes = (
            len(
                member_chunk_ids_for_node(
                    {"canonical": surviving[0], "aliases": surviving[1:]}, inventory_after
                )
            )
            if surviving
            else 0
        )
        if not surviving:
            removed_pages += 1
        elif len(surviving) != len(members):
            rekeyed_pages += 1
        else:
            untouched_pages += 1
        if before_notes >= GATHER_FLOOR:
            big_before += 1
            if not surviving:
                big_removed += 1
            elif after_notes >= GATHER_FLOOR:
                big_still_big += 1
            else:
                big_fell_below_floor += 1

    index_after = index_before - removed_pages

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "answers_dir": str(answers_dir.resolve()),
        "row_b_measured": row_b_measured,
        "distinct_section_headings_classified": len(section_classes),
        "back_matter_headings": len(back_matter),
        "heading_class_counts": dict(class_counts.most_common()),
        "non_body_headings_by_class": headings_by_class,
        "surfaces_before": len(surfaces_before),
        "surfaces_after": len(surfaces_after),
        "surfaces_dropped": len(dropped),
        "surfaces_dropped_share_pct": _share(len(dropped), len(surfaces_before)),
        "surfaces_minted_unexpectedly": sorted(minted)[:20],
        "row_attribution": dict(row_counts.most_common()),
        "index_before": index_before,
        "index_after": index_after,
        "index_change_pct": _share(index_after - index_before, index_before),
        "pages_removed": removed_pages,
        "pages_rekeyed": rekeyed_pages,
        "pages_untouched": untouched_pages,
        "pages_at_gather_floor_before": big_before,
        "pages_at_gather_floor_removed": big_removed,
        "pages_at_gather_floor_still_at_floor": big_still_big,
        "pages_at_gather_floor_fell_below": big_fell_below_floor,
        "published_for_reference": {
            "surfaces_before": 78198,
            "surfaces_dropped": 21666,
            "surfaces_dropped_share_pct": 27.7,
            "index_before": 62704,
            "index_after": 46805,
            "pages_removed": 15899,
            "pages_rekeyed": 1991,
            "pages_at_gather_floor_before": 2010,
            "pages_at_gather_floor_removed": 140,
            "pages_at_gather_floor_still_at_floor": 1814,
            "pages_at_gather_floor_fell_below": 56,
        },
    }

    print("issue #508 -- the cut set, measured over the live name layer")
    print("-" * 78)
    if not row_b_measured:
        print(
            "NOTE: data/names/section_classes.json is absent, so ROW B IS NOT IN THESE\n"
            "      NUMBERS. Nine of the ten rows are. Run `uv run axial names build` once\n"
            "      to pay for the heading classification, then re-run this script.\n"
        )
    else:
        print(
            f"row B included: {len(section_classes)} distinct heading(s) classified, "
            f"{len(back_matter)} back matter"
        )
        print(
            "  by class: "
            + ", ".join(f"{label}={count}" for label, count in class_counts.most_common())
        )
        print("  (every non-body heading is listed verbatim in the JSON report)\n")
    for label, key in [
        ("surfaces before", "surfaces_before"),
        ("surfaces after", "surfaces_after"),
        ("surfaces dropped", "surfaces_dropped"),
        ("index before (pages)", "index_before"),
        ("index after (pages)", "index_after"),
        ("pages removed entirely", "pages_removed"),
        ("pages losing members (Gather re-key)", "pages_rekeyed"),
        ("pages untouched (Gather reuse)", "pages_untouched"),
        (f"pages at {GATHER_FLOOR}+ member notes before", "pages_at_gather_floor_before"),
        ("  of those, removed entirely", "pages_at_gather_floor_removed"),
        (f"  of those, still at {GATHER_FLOOR}+", "pages_at_gather_floor_still_at_floor"),
        (f"  of those, fell below {GATHER_FLOOR}", "pages_at_gather_floor_fell_below"),
    ]:
        print(f"{label:<52}{report[key]:>10}")
    print(f"{'surfaces dropped, share':<52}{report['surfaces_dropped_share_pct']:>9}%")
    print(f"{'index change':<52}{report['index_change_pct']:>9}%")

    print("\nrow attribution over the dropped set (rows overlap; not a partition):")
    for row, count in row_counts.most_common():
        print(f"  {row:<48}{count:>10}")

    if minted:
        print(
            f"\nWARNING: {len(minted)} surface(s) exist after the cut but not before -- "
            "the after inventory should be a subset. First few:"
        )
        for surface in sorted(minted)[:20]:
            print(f"  {surface!r}")

    print("\npublished, for reference (issue #508):")
    for label, value in report["published_for_reference"].items():
        print(f"  {label:<45} {value}")

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEFAULT_LOG_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {report_path.resolve()}")


if __name__ == "__main__":
    main()
