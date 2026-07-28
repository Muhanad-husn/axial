"""The two families that work, unioned.

Orthographic and structural miss different things by construction: one folds
`Phelps-Brown and Hopkins 1956` into `... (1956)`, the other folds
`Ostrom, Elinor` into `Elinor Ostrom`. Neither reaches the other's cases, so
the union should gain recall without either one's precision cost -- unless
their false merges chain through transitive closure, which is the thing to
measure rather than assume.

Both are run, their asserted pairs are unioned, and the structural veto set is
applied to the whole union. Closure refuses any union that would put a vetoed
pair in one block, exactly as `structural.build` does.

`without_case_veto` is the same thing minus `veto_case_only`. That veto is
correct against the raw decision log and wrong against the corpus: the log
refuses every case-only merge because `parse_merge_response` drops it, not
because the model judged it (see `repair`). Scored on the raw gold the veto
looks like a 4-point precision gain; scored with the artifact excluded it is
holding back merges that are simply right.
"""

from __future__ import annotations

from itertools import combinations

from experiments.mechanical_merge.harness import Partition, as_partition
from experiments.mechanical_merge.resolvers import orthographic, structural


def _asserted(resolver, members, kinds) -> set[frozenset[str]]:
    return {
        frozenset(pair)
        for block in resolver(members, kinds)
        for pair in combinations(sorted(block), 2)
    }


def _union_resolver(parts, vetoes):
    def resolve(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
        if len(members) < 2:
            return as_partition([], members)
        proposed: set[frozenset[str]] = set()
        for part in parts:
            proposed |= _asserted(part, members, kinds)

        ctx = structural._Context(members, kinds)
        blocked = {
            frozenset({a, b})
            for a, b in combinations(members, 2)
            if any(veto(a, b, ctx) for veto in vetoes)
        }

        blocks = {member: {member} for member in members}
        for pair in sorted(proposed, key=lambda p: sorted(p)):
            left_member, right_member = sorted(pair)
            left, right = blocks[left_member], blocks[right_member]
            if left is right or pair in blocked:
                continue
            if any(frozenset({x, y}) in blocked for x in left for y in right):
                continue
            joined = left | right
            for member in joined:
                blocks[member] = joined
        return as_partition([sorted(block) for block in blocks.values()], members)

    return resolve


_PARTS = (orthographic.citation_cased_passage, structural.wide)
_PARTS_SAFE = (orthographic.citation_cased_passage, structural.balanced)

union = _union_resolver(_PARTS, structural.VETOES)
union_safe = _union_resolver(_PARTS_SAFE, structural.VETOES)
without_case_veto = _union_resolver(
    _PARTS, tuple(v for v in structural.VETOES if v is not structural.veto_case_only)
)


# The parser artifact is the one class no rule above proposes: neither part
# casefolds, so `Janjaweed`/`janjaweed` is left split by both. `alphanumeric`
# folds case and punctuation together, which is right in the corpus and wrong
# against the raw log by exactly the 1,568 pairs `repair` excludes. Scored both
# ways, it is the difference between chasing the bug and fixing it.
union_plus_fold = _union_resolver(
    (*_PARTS, orthographic.alphanumeric),
    tuple(v for v in structural.VETOES if v is not structural.veto_case_only),
)
