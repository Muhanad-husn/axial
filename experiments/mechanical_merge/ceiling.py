"""How well could ANY mechanical resolver do? An upper bound, measured.

Every resolver in `resolvers/` sees the same thing: two surface strings and
their kinds. So two pairs that look identical to that view must get the same
answer from any such resolver -- and where the live pass gave them DIFFERENT
answers, one of the two is a forced error. Summing those forced errors gives a
ceiling on pair precision and recall that no amount of rule-writing can beat.

The method is the standard Bayes-error estimate over a feature partition:

  1. Reduce each within-cluster pair to a `signature` -- a tuple of cheap
     string facts, nothing a resolver could not compute.
  2. Group every gold pair by signature.
  3. Within a group, the best any deterministic resolver can do is answer with
     the majority label. Every minority pair is an unavoidable error.

The ceiling is only as tight as the signature is rich, so it is reported for
several signatures of increasing detail: a coarse one bounds every simple rule,
a rich one bounds anything short of reading the passage. A ceiling that stays
low as the signature gets richer is the interesting result -- it means the
information needed to decide is not in the strings at all.

This reads the decision log and writes nothing.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from experiments.mechanical_merge.harness import (
    DEFAULT_DECISIONS,
    DEFAULT_INVENTORY,
    load_gold,
    load_kinds,
    pairs,
)
from experiments.mechanical_merge.repair import collided_pairs

_YEAR = re.compile(r"\b(1[5-9]\d{2}|20[0-4]\d)\b")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _fold(text: str) -> str:
    """Diacritics off, case off, `&` spelled out -- the least controversial
    normalization there is, used only to build signatures."""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    return stripped.replace("&", " and ").casefold()


def _tokens(text: str) -> list[str]:
    return _WORD.findall(_fold(text))


def _stem_tokens(text: str) -> set[str]:
    """Tokens with years removed -- the name without its citation apparatus."""
    return {token for token in _tokens(text) if not _YEAR.fullmatch(token)}


def coarse(left: str, right: str, kinds: dict[str, str | None]) -> tuple:
    """What a plain normalize-and-compare rule can see."""
    lt, rt = _stem_tokens(left), _stem_tokens(right)
    if not lt or not rt:
        return ("empty",)
    if lt == rt:
        return ("same-stem-tokens",)
    if lt < rt or rt < lt:
        return ("stem-containment",)
    if lt & rt:
        return ("stem-overlap",)
    return ("stem-disjoint",)


def rich(left: str, right: str, kinds: dict[str, str | None]) -> tuple:
    """Everything the three resolver families put together can see: token
    relation, year compatibility, what the extra tokens look like, and whether
    the corpus gave the two surfaces the same kind."""
    lt, rt = _stem_tokens(left), _stem_tokens(right)
    ly, ry = set(_YEAR.findall(left)), set(_YEAR.findall(right))
    if not ly or not ry:
        years = "one-or-both-absent"
    elif ly == ry:
        years = "equal"
    else:
        years = "different"

    if not lt or not rt:
        relation = "empty"
    elif lt == rt:
        relation = "equal"
    elif lt < rt or rt < lt:
        relation = "containment"
    elif lt & rt:
        relation = "overlap"
    else:
        relation = "disjoint"

    extra = (lt | rt) - (lt & rt)
    # What distinguishes the two surfaces, described structurally: a
    # conjunction, a capitalised word (likely another proper name), or only
    # lowercase words.
    original = f"{left} {right}"
    capitalised = {
        token
        for token in extra
        if any(word[:1].isupper() and _fold(word) == token for word in _WORD.findall(original))
    }
    if not extra:
        extra_shape = "none"
    elif extra & {"and", "et", "al", "with"}:
        extra_shape = "conjunction"
    elif capitalised:
        extra_shape = "capitalised"
    else:
        extra_shape = "lowercase-only"

    same_kind = (
        "same" if kinds.get(left) and kinds.get(left) == kinds.get(right) else "differ-or-unknown"
    )
    return (relation, years, extra_shape, same_kind, min(len(lt), len(rt)) == 1)


SIGNATURES = {"coarse": coarse, "rich": rich}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--show", type=int, default=14, help="most populous signatures to print")
    parser.add_argument(
        "--repaired",
        action="store_true",
        help="drop the pairs whose 'refused' label came from the parser, not the model",
    )
    args = parser.parse_args()

    clusters = load_gold(args.decisions)
    kinds = load_kinds(args.inventory)

    for name, signature in SIGNATURES.items():
        # label counts per signature: how often the model merged this shape
        table: dict[tuple, Counter] = defaultdict(Counter)
        for cluster in clusters:
            gold = pairs(cluster.gold)
            excluded = collided_pairs(cluster) if args.repaired else set()
            for left, right in combinations(cluster.members, 2):
                if frozenset((left, right)) in excluded:
                    continue
                merged = frozenset((left, right)) in gold
                key = signature(*sorted((left, right)), kinds)
                table[key][merged] += 1

        total = sum(sum(counts.values()) for counts in table.values())
        gold_merges = sum(counts[True] for counts in table.values())
        # Majority-label resolver: for each signature, answer with whichever
        # label the model gave more often.
        tp = fp = fn = 0
        for counts in table.values():
            if counts[True] >= counts[False]:
                tp += counts[True]
                fp += counts[False]
            else:
                fn += counts[True]
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / gold_merges if gold_merges else 1.0
        forced = sum(min(counts[True], counts[False]) for counts in table.values())

        print(f"\n## Ceiling under the `{name}` signature\n")
        print(f"- pairs scored: {total:,} ({gold_merges:,} gold merges)")
        print(f"- distinct signatures: {len(table):,}")
        print(f"- forced errors (minority pairs): {forced:,} = {forced / total:.2%} of all pairs")
        print(f"- **best achievable pair precision {precision:.1%}, recall {recall:.1%}**")
        print("\n| signature | pairs | merged | refused | majority | purity |")
        print("|---|---|---|---|---|---|")
        for key, counts in sorted(table.items(), key=lambda kv: -sum(kv[1].values()))[: args.show]:
            n = sum(counts.values())
            purity = max(counts[True], counts[False]) / n
            majority = "MERGE" if counts[True] >= counts[False] else "refuse"
            print(
                f"| `{key}` | {n:,} | {counts[True]:,} | {counts[False]:,} | "
                f"{majority} | {purity:.1%} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
