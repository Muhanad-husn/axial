"""Issue #504 real-corpus measurement -- LLM-free, $0.

Re-reads `D:/axial/data/names/merge_decisions.jsonl` (the live layer) and
measures the one-node-with-omissions shape the issue describes, and the
before/after page count `axial names merge` would write once the fix's fold
runs. No model call: everything here is a pure re-read of what is already on
disk under `merge_decisions.jsonl` and `inventory.jsonl`.

Run from anywhere; every data path below is absolute. `sys.path` is pointed
at the WORKTREE's own `src/` first, so `import axial.merge_names` resolves
to the branch under test, not whatever `main` has installed -- printed below
so that is never silently wrong again (see the brief's own warning: a script
run from `D:/axial` would otherwise import `main`'s `src/`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKTREE_SRC = r"D:\axial\.claude\worktrees\504-one-node-omitted-members\src"
sys.path.insert(0, WORKTREE_SRC)

import axial.merge_names as mn  # noqa: E402
from axial.interrogate import _default_domain_dir  # noqa: E402
from axial.name_candidates import fold_groups  # noqa: E402

print(f"module under test (axial.merge_names): {mn.__file__}")
assert Path(mn.__file__).resolve().is_relative_to(Path(WORKTREE_SRC).resolve()), (
    "refusing to measure against the wrong axial.merge_names -- "
    f"resolved to {mn.__file__}, expected it under {WORKTREE_SRC}"
)

DATA_DIR = Path(r"D:\axial\data\names")
CONFIG_PATH = Path(r"D:\axial\config\pipeline.yaml")
DECISIONS_PATH = DATA_DIR / "merge_decisions.jsonl"
INVENTORY_PATH = DATA_DIR / "inventory.jsonl"
ALIAS_MAP_PATH = DATA_DIR / "alias_map.json"

NAMED_11 = ["WHO", "WB", "NRC", "TCC", "VDC", "UTICA", "AMITH", "EPR", "INDH", "OLA", "SPS"]


def main() -> None:
    decisions = mn.load_decisions(DECISIONS_PATH)
    print(f"total recorded decisions: {len(decisions)}")

    one_node_omission: list[tuple[str, dict, list[str]]] = []
    for key, record in decisions.items():
        nodes = record.get("nodes") or []
        if len(nodes) != 1:
            continue
        node = nodes[0]
        placed = {node["canonical"], *node["aliases"], *(record.get("escalated") or [])}
        members = record.get("members") or []
        omitted = [member for member in members if member not in placed]
        if omitted:
            one_node_omission.append((key, record, omitted))

    print(f"one-node-with-omission decisions: {len(one_node_omission)}")
    total_omitted_members = sum(len(omitted) for _key, _record, omitted in one_node_omission)
    print(f"total omitted members across them: {total_omitted_members}")

    candidate = [
        item for item in one_node_omission if item[1]["cluster_label"] <= mn._CANDIDATE_LABEL_BASE
    ]
    real_cluster = [item for item in one_node_omission if item[1]["cluster_label"] >= 0]
    print(f"  from candidate-generation batches (issue #446 families): {len(candidate)}")
    print(f"  from real HDBSCAN clusters: {len(real_cluster)}")
    assert len(candidate) + len(real_cluster) == len(one_node_omission)

    # The eleven named in the issue.
    print("\nthe eleven named cases:")
    all_omitted_flat = {name for _key, _record, omitted in one_node_omission for name in omitted}
    for name in NAMED_11:
        found = [item for item in one_node_omission if name in item[2]]
        status = (
            "FOLDS"
            if found
            else ("already placed elsewhere" if name not in all_omitted_flat else "MISSING")
        )
        print(f"  {name}: {len(found)} decision(s) omit it -- {status}")

    # Which one-node-omission decisions are NOT an acronym-parenthesized
    # pair shaped like the issue's own worked example (a 2-member batch
    # where one member is the other's parenthesized-acronym form)? A rough,
    # LLM-free shape check: 2-member batch, one member ends in
    # "(<omitted>)" or the omitted member appears literally inside the kept
    # canonical's own parenthetical.
    def _looks_like_acronym_pair(record: dict, omitted: list[str]) -> bool:
        members = record.get("members") or []
        if len(members) != 2 or len(omitted) != 1:
            return False
        kept = [m for m in members if m != omitted[0]]
        if not kept:
            return False
        return f"({omitted[0]})" in kept[0]

    non_acronym_shaped = [
        item for item in one_node_omission if not _looks_like_acronym_pair(item[1], item[2])
    ]
    print(
        f"\ndecisions NOT shaped like a 2-member acronym-parenthesized pair: "
        f"{len(non_acronym_shaped)} of {len(one_node_omission)}"
    )
    for key, record, omitted in non_acronym_shaped[:15]:
        print(
            f"  cluster_label={record['cluster_label']} members={record.get('members')} "
            f"nodes={record.get('nodes')} escalated={record.get('escalated')} omitted={omitted}"
        )
    if len(non_acronym_shaped) > 15:
        print(f"  ... and {len(non_acronym_shaped) - 15} more")

    # Before/after page counts: rebuild the alias map's node set with the
    # OLD (unfolded) decision_nodes vs the NEW (folded) ones -- everything
    # else (inventory, seed, case/whitespace/punctuation fold) held fixed,
    # so the delta isolates exactly what this fix moves.
    rows = [json.loads(line) for line in INVENTORY_PATH.read_text(encoding="utf-8").splitlines()]
    full_entries = [(row["surface"], row.get("kind"), row["count"]) for row in rows]
    all_surface_forms = [surface for surface, _kind, _count in full_entries]
    folded_groups = fold_groups(all_surface_forms)

    domain_dir = _default_domain_dir(CONFIG_PATH)
    seed_groups, seed_note = mn._seed_groups(all_surface_forms, Path(domain_dir))
    print(f"\nseed: {seed_note}")

    decision_nodes_before = [
        node for record in decisions.values() for node in (record.get("nodes") or [])
    ]
    decision_nodes_after = [
        node
        for record in decisions.values()
        for node in mn._fold_omitted_into_single_node(
            record.get("members") or [], record.get("nodes") or [], record.get("escalated") or []
        )
    ]

    nodes_before = mn.build_alias_map_nodes(
        full_entries, decision_nodes_before, seed_groups, folded_groups
    )
    nodes_after = mn.build_alias_map_nodes(
        full_entries, decision_nodes_after, seed_groups, folded_groups
    )

    print(f"\ncanonical pages BEFORE this fix (reconstructed): {len(nodes_before)}")
    print(f"canonical pages AFTER this fix (reconstructed):  {len(nodes_after)}")
    print(f"pages folded away: {len(nodes_before) - len(nodes_after)}")

    if ALIAS_MAP_PATH.is_file():
        on_disk = json.loads(ALIAS_MAP_PATH.read_text(encoding="utf-8"))
        on_disk_count = len(on_disk["nodes"])
        print(f"\non-disk alias_map.json node count (reference, pre-fix code): {on_disk_count}")
        matches = (
            "matches reconstructed BEFORE count"
            if on_disk_count == len(nodes_before)
            else "DOES NOT MATCH reconstructed BEFORE count -- investigate"
        )
        print(f"  {matches}")

    # Confirm the eleven actually land on one page each in the AFTER map.
    print("\nconfirming the eleven fold onto one page in the AFTER map:")
    canonical_of_after: dict[str, str] = {}
    for node in nodes_after:
        for surface in [node["canonical"], *node["aliases"]]:
            canonical_of_after[surface] = node["canonical"]
    for name in NAMED_11:
        canonical = canonical_of_after.get(name)
        print(f"  {name} -> {canonical!r}")

    # Any decision outside the acronym-pair candidate family affected?
    print(
        f"\nsummary: {len(one_node_omission)} total one-node-omission decisions, "
        f"{len(candidate)} from candidate-generation batches, "
        f"{len(real_cluster)} from real HDBSCAN clusters, "
        f"{len(non_acronym_shaped)} not shaped like a 2-member acronym pair."
    )


if __name__ == "__main__":
    main()
