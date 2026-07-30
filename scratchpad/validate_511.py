"""Read-only validation for issue #511 row B: the per-source back-matter
boundary, measured against the live name layer, before and after.

LLM-free, **zero model calls**, read-only. It reads `data/trees/`,
`data/answers/`, `data/names/inventory.jsonl`, `data/names/alias_map.json`
and `data/names/index.json`, and writes nothing anywhere under `data/`
except its own log directory.

**"Before" is the live layer itself, not a reimplementation of it.**
`inventory.jsonl` on disk IS what `main`'s `iter_name_occurrences` produced
over these same answer records (verified: 61,612 surfaces both ways, zero
either-way difference), and `alias_map.json`/`index.json` are the pages that
inventory actually grew. "After" re-derives the inventory from the same
answer records through THIS WORKTREE's `axial.names`, with row B applied,
then asks which of the live layer's own nodes still have a surviving member
surface. Same counting as `scratchpad/validate_508.py`, so the two tables
are comparable.

**The acceptance is the per-book cut list read by eye, not the aggregate**
(issue #472, and issue #508's round 2, which improved every aggregate while
the content loss got worse). `--diff` prints every cut section with what it
contributed, per book, plus the last section kept before each boundary.

Run it from the orchestrator's main checkout, where `data/` actually exists
(it does not exist inside a worktree):

    cd D:/axial
    uv run python .claude/worktrees/511-back-matter-sections/scratchpad/validate_511.py --diff
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_WORKTREE_ROOT / "src"))

import axial.names as names_module  # noqa: E402
from axial.chunk import _section_nodes, section_order_key  # noqa: E402
from axial.extract import TREES_DIR  # noqa: E402
from axial.interrogate import _default_answers_dir  # noqa: E402
from axial.materialize import load_inventory, member_chunk_ids_for_node  # noqa: E402
from axial.names import (  # noqa: E402
    _section_order_of,
    back_matter_anchor,
    build_inventory,
    collect_occurrences,
    iter_name_occurrences,
    load_answer_records,
    load_back_matter_sections,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH  # noqa: E402

NAMES_DIR = Path("data/names")
DEFAULT_LOG_DIR = Path("data/logs/2026-07-30-validate-511")

GATHER_FLOOR = 10  # config/pipeline.yaml's `gather.min_members`


def _share(count: int, denom: int) -> float:
    return round(100 * count / denom, 1) if denom else 0.0


def main() -> None:
    print(f"axial.names resolved from: {names_module.__file__}")
    if _WORKTREE_ROOT not in Path(names_module.__file__).parents:
        print("refusing to run: axial.names is not this worktree's copy", file=sys.stderr)
        raise SystemExit(1)

    want_diff = "--diff" in sys.argv[1:]
    answers_dir = _default_answers_dir(DEFAULT_PIPELINE_CONFIG_PATH)
    inventory_path = NAMES_DIR / "inventory.jsonl"
    alias_map_path = NAMES_DIR / "alias_map.json"
    index_path = NAMES_DIR / "index.json"
    for path in (answers_dir, TREES_DIR, inventory_path, alias_map_path):
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
    index_before = (
        len(json.loads(index_path.read_text(encoding="utf-8"))["names"])
        if index_path.is_file()
        else len(nodes)
    )

    # --- after: row B applied, over the same answer records -----------------
    back_matter_sections = load_back_matter_sections(TREES_DIR)
    records = load_answer_records(answers_dir)
    entries_after = build_inventory(collect_occurrences(records, back_matter_sections))
    surfaces_after = {entry.surface_form for entry in entries_after}
    inventory_after = {
        entry.surface_form: {"chunk_ids": list(entry.chunk_ids)} for entry in entries_after
    }

    dropped = surfaces_before - surfaces_after
    minted = surfaces_after - surfaces_before  # expected empty; reported if not

    notes_cut = sum(
        1
        for record in records
        if _section_order_of(record.get("chunk_id", ""), record.get("source_id", ""))
        in back_matter_sections.get(record.get("source_id", ""), ())
    )

    # --- pages: which of the live layer's own nodes survive -----------------
    removed_pages = rekeyed_pages = untouched_pages = 0
    big_before = big_removed = big_still_big = big_fell = big_rekeyed = 0
    floor_casualties: list[tuple[str, int, int]] = []
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
            else:
                if after_notes != before_notes:
                    big_rekeyed += 1
                if after_notes >= GATHER_FLOOR:
                    big_still_big += 1
                else:
                    big_fell += 1
                    floor_casualties.append((node["canonical"], before_notes, after_notes))

    index_after = index_before - removed_pages

    # --- per-source attribution + the forgone front-matter prize ------------
    surfaces_by_section: dict[tuple[str, str], set[str]] = defaultdict(set)
    chunks_by_section: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        source_id = record.get("source_id", "")
        chunk_id = record.get("chunk_id", "")
        if not source_id or not chunk_id:
            continue
        key = (source_id, _section_order_of(chunk_id, source_id))
        chunks_by_section[key].add(chunk_id)
        for occurrence in iter_name_occurrences(record):
            surfaces_by_section[key].add(occurrence.surface_form)

    per_source: list[dict[str, Any]] = []
    diff_lines: list[str] = []
    for path in sorted(TREES_DIR.glob("*.json")):
        source_id = path.stem
        sections = _section_nodes(json.loads(path.read_text(encoding="utf-8")))
        cut_orders = back_matter_sections.get(source_id, frozenset())
        anchors = [back_matter_anchor(node.get("text", "")) for node in sections]
        boundary = next(
            (
                i
                for i, node in enumerate(sections)
                if section_order_key(str(node.get("order", ""))) in cut_orders
            ),
            None,
        )
        cut_surfaces = 0
        lost_surfaces = 0
        diff_lines.append(
            f"\n--- {source_id}: {len(sections)} sections, "
            f"{len(anchors) - anchors.count(None)} anchor(s), boundary {boundary}"
        )
        if boundary is None:
            diff_lines.append("    no anchor survived extraction -- nothing cut")
        else:
            if boundary:
                previous = sections[boundary - 1]
                diff_lines.append(
                    f"    last kept: [{previous.get('order', '')}] {previous.get('text', '')!r}"
                )
            for node in sections[boundary:]:
                key = (source_id, section_order_key(str(node.get("order", ""))))
                surfaces = surfaces_by_section.get(key, set())
                lost = {surface for surface in surfaces if surface not in surfaces_after}
                cut_surfaces += len(surfaces)
                lost_surfaces += len(lost)
                diff_lines.append(
                    f"    CUT [{str(node.get('order', '')):>5}] "
                    f"notes={len(chunks_by_section.get(key, ())):<3} "
                    f"surfaces={len(surfaces):<5} lost={len(lost):<5} {node.get('text', '')!r}"
                )
        per_source.append(
            {
                "source_id": source_id,
                "sections": len(sections),
                "boundary": boundary,
                "sections_cut": 0 if boundary is None else len(sections) - boundary,
                "surfaces_in_cut_sections": cut_surfaces,
                "surfaces_lost_corpus_wide": lost_surfaces,
            }
        )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "answers_dir": str(answers_dir.resolve()),
        "trees_dir": str(TREES_DIR.resolve()),
        "rule": "row B: cut every section at or after min(first index anchor, "
        "last bibliography anchor), extended back over contiguous anchors",
        "model_calls": 0,
        "surfaces_before": len(surfaces_before),
        "surfaces_after": len(surfaces_after),
        "surfaces_dropped": len(dropped),
        "surfaces_dropped_share_pct": _share(len(dropped), len(surfaces_before)),
        "surfaces_minted_unexpectedly": sorted(minted)[:20],
        "notes_total": len(records),
        "notes_in_cut_sections": notes_cut,
        "notes_cut_share_pct": _share(notes_cut, len(records)),
        "sources_with_a_boundary": sum(1 for row in per_source if row["boundary"] is not None),
        "sources_total": len(per_source),
        "index_before": index_before,
        "index_after": index_after,
        "index_change_pct": _share(index_after - index_before, index_before),
        "pages_removed": removed_pages,
        "pages_rekeyed": rekeyed_pages,
        "pages_untouched": untouched_pages,
        "pages_at_gather_floor_before": big_before,
        "pages_at_gather_floor_removed": big_removed,
        "pages_at_gather_floor_still_at_floor": big_still_big,
        "pages_at_gather_floor_fell_below": big_fell,
        "pages_at_gather_floor_rekeyed": big_rekeyed,
        "per_source": per_source,
        "floor_casualties": sorted(floor_casualties, key=lambda row: -row[1]),
        "row_b_as_pinned_in_508": {
            "surfaces": 5771,
            "pages_if_cut_alone": 3987,
            "pages_at_10_plus_lost": 0,
            "note": "measured against the pre-#508 layer (78,198 surfaces / 62,704 pages), "
            "so comparable in shape, not in absolute size",
        },
    }

    print("issue #511 row B -- the back-matter boundary, measured over the live name layer")
    print("-" * 82)
    for label, key in [
        ("surfaces before", "surfaces_before"),
        ("surfaces after", "surfaces_after"),
        ("surfaces dropped", "surfaces_dropped"),
        ("notes in cut sections", "notes_in_cut_sections"),
        ("notes total", "notes_total"),
        ("sources with a boundary", "sources_with_a_boundary"),
        ("sources total", "sources_total"),
        ("index before (pages)", "index_before"),
        ("index after (pages)", "index_after"),
        ("pages removed entirely", "pages_removed"),
        ("pages losing members (Gather re-key)", "pages_rekeyed"),
        ("pages untouched (Gather reuse)", "pages_untouched"),
        (f"pages at {GATHER_FLOOR}+ member notes before", "pages_at_gather_floor_before"),
        ("  of those, removed entirely", "pages_at_gather_floor_removed"),
        (f"  of those, still at {GATHER_FLOOR}+", "pages_at_gather_floor_still_at_floor"),
        (f"  of those, fell below {GATHER_FLOOR}", "pages_at_gather_floor_fell_below"),
        ("  of those, member set changed (re-decide)", "pages_at_gather_floor_rekeyed"),
    ]:
        print(f"{label:<46}{report[key]:>10}")
    print(f"{'surfaces dropped, share':<46}{report['surfaces_dropped_share_pct']:>9}%")
    print(f"{'notes cut, share':<46}{report['notes_cut_share_pct']:>9}%")
    print(f"{'index change':<46}{report['index_change_pct']:>9}%")

    if minted:
        print(
            f"\nWARNING: {len(minted)} surface(s) exist after the cut but not before -- "
            "the after inventory must be a subset. First few:"
        )
        for surface in sorted(minted)[:20]:
            print(f"  {surface!r}")

    print(f"\nper source ({len(per_source)}), by surfaces lost corpus-wide:")
    print(f"  {'source':<34}{'cut':>5}{'surfaces':>10}{'lost':>7}")
    for row in sorted(per_source, key=lambda item: -item["surfaces_lost_corpus_wide"]):
        print(
            f"  {row['source_id']:<34}{row['sections_cut']:>5}"
            f"{row['surfaces_in_cut_sections']:>10}{row['surfaces_lost_corpus_wide']:>7}"
        )

    print(f"\nthe {big_fell} pages that fall below Gather's floor of {GATHER_FLOOR} (top 25):")
    for name, before, after in report["floor_casualties"][:25]:
        print(f"  {before:>4} -> {after:<4} {name!r}")

    if want_diff:
        print("\n" + "=" * 82)
        print("PER-BOOK CUT LIST -- this is the acceptance, read it by eye")
        print("=" * 82)
        for line in diff_lines:
            print(line)

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DEFAULT_LOG_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    diff_path = DEFAULT_LOG_DIR / "cut_sections.txt"
    diff_path.write_text("\n".join(diff_lines) + "\n", encoding="utf-8")
    print(f"\nwrote {report_path.resolve()}")
    print(f"wrote {diff_path.resolve()}")


if __name__ == "__main__":
    main()
