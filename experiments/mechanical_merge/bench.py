"""Score one or more resolvers by dotted path, without touching the registry.

    uv run python -m experiments.mechanical_merge.bench \
        experiments.mechanical_merge.resolvers.fuzzy:token_ratio_88 \
        --errors 40 --error-dir errors/fuzzy

Each argument is `module:function` where the function has the resolver
signature `(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition`.
`--hard` additionally prints, for every PR #441 trap, whether the resolver got
it right -- which is the check that actually gates a candidate.
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
    pairs,
    score_all,
)


def load(spec: str):
    module_name, _, func_name = spec.partition(":")
    return getattr(importlib.import_module(module_name), func_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("resolvers", nargs="+", help="module:function")
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--errors", type=int, default=0)
    parser.add_argument("--error-dir", type=Path, default=Path("errors"))
    parser.add_argument("--hard", action="store_true")
    args = parser.parse_args()

    clusters = load_gold(args.decisions)
    if args.limit:
        clusters = clusters[: args.limit]
    kinds = load_kinds(args.inventory)

    print(HEADER)
    for spec in args.resolvers:
        resolver = load(spec)
        name = spec.rsplit(":", 1)[-1]
        score, errors = score_all(name, resolver, clusters, kinds, args.errors)
        print(score.row(), flush=True)
        if errors:
            args.error_dir.mkdir(parents=True, exist_ok=True)
            (args.error_dir / f"{name}.json").write_text(
                json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        if args.hard:
            print(f"\n### hard cases -- {name}\n")
            for label, forms, note in hard_cases.HARD_CASES:
                for cluster in hard_cases.select(clusters, forms):
                    predicted = resolver(cluster.members, kinds)
                    fp = pairs(predicted) - pairs(cluster.gold)
                    fn = pairs(cluster.gold) - pairs(predicted)
                    verdict = (
                        "PASS" if not fp and not fn else ("OVER-MERGE" if fp else "under-merge")
                    )
                    print(f"- **{label}** [{verdict}] {note}")
                    print(f"  - members: {list(cluster.members)}")
                    print(f"  - gold:      {sorted(sorted(b) for b in cluster.gold)}")
                    print(f"  - predicted: {sorted(sorted(b) for b in predicted)}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
