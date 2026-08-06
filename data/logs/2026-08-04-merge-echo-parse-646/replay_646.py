"""Replay every recorded merge-parse failure on the corpus of record through
`parse_merge_response`, with the batch's real kinds and evidence rebuilt from
the inventory. Read-only; no model calls.

Usage: uv run python replay_646.py <path-to-src-on-sys.path>
"""

import ast
import json
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SRC))

from axial.merge_names import (  # noqa: E402
    MergeResponseError,
    build_evidence_index,
    parse_merge_response,
)

DATA = Path("D:/axial/data/names")

inventory_kinds: dict[str, str | None] = {}
inventory_chunks: dict[str, tuple[str, ...]] = {}
with (DATA / "inventory.jsonl").open(encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        inventory_kinds[row["surface"]] = row.get("kind") or None
        inventory_chunks[row["surface"]] = tuple(row.get("chunk_ids") or ())

RAW = re.compile(r"length=(\d+) raw=(.*)$", re.DOTALL)

total = 0
replayable = 0
parsed = 0
still_failing = []
recovered = []

with (DATA / "merge_failures.jsonl").open(encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        total += 1
        match = RAW.search(row["reason"])
        if not match:
            continue  # truncated diagnostic (head=/tail=), cannot replay
        raw = ast.literal_eval(match.group(2).strip())
        members = row["members"]
        replayable += 1
        kinds = {m: inventory_kinds.get(m) for m in members}
        evidence = build_evidence_index({m: inventory_chunks.get(m, ()) for m in members})
        try:
            nodes, escalated = parse_merge_response(raw, members, kinds, evidence)
        except MergeResponseError as exc:
            still_failing.append((row["cluster_label"], members, str(exc)[:120]))
            continue
        parsed += 1
        placed = {n["canonical"] for n in nodes} | {a for n in nodes for a in n["aliases"]}
        placed |= set(escalated)
        recovered.append(
            {
                "cluster": row["cluster_label"],
                "members": len(members),
                "placed": len(placed),
                "nodes": [(n["canonical"], n["aliases"]) for n in nodes],
                "escalated": escalated,
            }
        )

print(f"failure rows:        {total}")
print(f"replayable (full raw): {replayable}")
print(f"now parse:           {parsed}")
print(f"still refused:       {len(still_failing)}")
print()
fully = sum(1 for r in recovered if r["placed"] == r["members"])
print(f"of those that parse, all members placed: {fully}/{len(recovered)}")
print()
for r in recovered[:12]:
    print(f"  cluster {r['cluster']}: {r['placed']}/{r['members']} placed -> {r['nodes']}")
print()
for cluster, members, reason in still_failing[:10]:
    print(f"  REFUSED cluster {cluster} {members}: {reason}")
