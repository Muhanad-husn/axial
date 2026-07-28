"""Run every registered resolver over the live pass's own decisions.

    uv run --with rapidfuzz --with unidecode python -m experiments.mechanical_merge.run

Reads `D:/axial/data/names/{merge_decisions,inventory}.jsonl`. Writes nothing
under `data/`; the report goes to stdout and, with `--out`, to a file.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from experiments.mechanical_merge import hard_cases
from experiments.mechanical_merge.harness import (
    DEFAULT_DECISIONS,
    DEFAULT_INVENTORY,
    HEADER,
    load_gold,
    load_kinds,
    score_all,
)

# (display name, "module:function"). Resolvers are imported lazily so a
# missing optional dependency skips one row instead of killing the run.
REGISTRY: list[tuple[str, str]] = [
    ("split-all (never merge)", "experiments.mechanical_merge.resolvers.baselines:split_all"),
    ("merge-all (trust cluster)", "experiments.mechanical_merge.resolvers.baselines:merge_all"),
]


def _load(spec: str):
    module_name, _, func_name = spec.partition(":")
    return getattr(importlib.import_module(module_name), func_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--limit", type=int, default=None, help="score only the first N clusters")
    parser.add_argument("--errors", type=int, default=0, help="dump this many disagreements each")
    parser.add_argument(
        "--only", action="append", help="run only resolvers matching this substring"
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    clusters = load_gold(args.decisions)
    if args.limit:
        clusters = clusters[: args.limit]
    kinds = load_kinds(args.inventory)
    print(f"# Mechanical name-merge, scored against {len(clusters)} live decisions\n")

    lines = [HEADER]
    for name, spec in REGISTRY:
        if args.only and not any(needle in name for needle in args.only):
            continue
        try:
            resolver = _load(spec)
        except Exception as exc:  # noqa: BLE001 -- a skipped row, not a failed run
            lines.append(f"| {name} | UNAVAILABLE: {exc} | | | | | | | | |")
            continue
        score, errors = score_all(name, resolver, clusters, kinds, args.errors)
        lines.append(score.row())
        print(score.row(), flush=True)
        if errors:
            path = Path(f"errors-{name.split()[0]}.json")
            path.write_text(json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8")

    report = "\n".join(lines)
    print("\n" + report)

    # The named traps, scored on their own.
    print("\n## Hard cases (PR #441)\n")
    for label, forms, note in hard_cases.HARD_CASES:
        found = hard_cases.select(clusters, forms)
        print(f"- `{label}` ({note}): {len(found)} matching cluster(s)")

    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
