"""Similarity-scored resolvers: score every within-cluster pair, merge above a
threshold, and see what precision that buys.

The family exists to answer one question the live pass's decisions can settle
for free: is there any threshold at which character or phonetic similarity
reaches ~99% pair precision, and what recall survives there? Anything less than
that precision fuses entities, and a fused entity is not recoverable the way a
split one is.

Two ways to turn pairwise scores into a partition, both measured:

  * `single` -- transitive closure. A~B and B~C put A with C even when A and C
    score zero against each other. This is the cheap default and the known
    over-merge amplifier.
  * `complete` -- greedy complete linkage. Two blocks join only if EVERY cross
    pair clears the threshold. Same scores, same threshold, no closure.

Preprocessing is measured, not assumed. Every character scorer exists twice:
once on the raw surfaces, once (`cf_`) on `unidecode` + casefold. The live pass
does not treat case and diacritics as noise, so folding them is a scoring
choice with a measurable cost, not a free win.

Resolvers are generated, not hand-written, so a threshold can never be picked
without its curve. Names read `<scorer>_<threshold>_<linkage>`, e.g.
`ratio_92_complete`.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations

import jellyfish
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from unidecode import unidecode

from experiments.mechanical_merge.harness import Partition

THRESHOLDS: tuple[int, ...] = (60, 65, *range(70, 101, 2))


@lru_cache(maxsize=None)
def _norm(surface: str) -> str:
    return unidecode(surface).casefold().strip()


@lru_cache(maxsize=None)
def _tokens(surface: str) -> tuple[str, ...]:
    return tuple(
        part for part in "".join(c if c.isalnum() else " " for c in _norm(surface)).split()
    )


def _phonetic_key(algorithm, surface: str) -> str:
    return algorithm("".join(_tokens(surface)))


def _phonetic_tokens(algorithm, surface: str) -> tuple[str, ...]:
    return tuple(algorithm(token) for token in _tokens(surface))


def _make_scorer(fn):
    """Memoise on the unordered pair. One sweep re-scores the same 56k pairs
    for every threshold, so this is the difference between seconds and minutes."""

    @lru_cache(maxsize=None)
    def cached(a: str, b: str) -> float:
        return float(fn(a, b))

    def scorer(a: str, b: str) -> float:
        return cached(a, b) if a <= b else cached(b, a)

    return scorer


def _jaro(a: str, b: str) -> float:
    return JaroWinkler.similarity(a, b) * 100


BASE = {
    "ratio": fuzz.ratio,
    "partial": fuzz.partial_ratio,
    "token_sort": fuzz.token_sort_ratio,
    "token_set": fuzz.token_set_ratio,
    "jarowinkler": _jaro,
}

CHARACTER = tuple(BASE)

# Both preprocessings, because the gold does not agree that they are free. The
# live pass kept `Janjaweed` apart from `janjaweed` and `Galilee` apart from
# `Galilée`, so folding case and diacritics before scoring manufactures false
# merges the raw scorer would never make. The bare name scores the surfaces as
# stored; `cf_*` folds first.
SCORERS = {name: _make_scorer(fn) for name, fn in BASE.items()}
SCORERS.update(
    {
        f"cf_{name}": _make_scorer(lambda a, b, f=fn: f(_norm(a), _norm(b)))
        for name, fn in BASE.items()
    }
)

PHONETIC = {
    "metaphone": jellyfish.metaphone,
    "soundex": jellyfish.soundex,
    "nysiis": jellyfish.nysiis,
}

for _name, _algorithm in PHONETIC.items():
    SCORERS[_name] = _make_scorer(
        lambda a, b, alg=_algorithm: 100.0 * (_phonetic_key(alg, a) == _phonetic_key(alg, b))
    )
    SCORERS[f"{_name}_tok"] = _make_scorer(
        lambda a, b, alg=_algorithm: 100.0 * (_phonetic_tokens(alg, a) == _phonetic_tokens(alg, b))
    )


def _single_linkage(members: tuple[str, ...], scorer, threshold: float) -> Partition:
    parent = {member: member for member in members}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for a, b in combinations(members, 2):
        if scorer(a, b) >= threshold:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[root_b] = root_a

    blocks: dict[str, set[str]] = {}
    for member in members:
        blocks.setdefault(find(member), set()).add(member)
    return frozenset(frozenset(block) for block in blocks.values())


def _complete_linkage(members: tuple[str, ...], scorer, threshold: float) -> Partition:
    """Join the two blocks whose weakest cross pair is strongest, while that
    weakest pair still clears the threshold. Clusters top out at 16 members, so
    the cubic loop is free."""
    blocks: list[frozenset[str]] = [frozenset({member}) for member in members]
    while True:
        best: tuple[float, int, int] | None = None
        for i, j in combinations(range(len(blocks)), 2):
            weakest = min(scorer(a, b) for a in blocks[i] for b in blocks[j])
            if weakest < threshold:
                continue
            if best is None or weakest > best[0]:
                best = (weakest, i, j)
        if best is None:
            return frozenset(blocks)
        _, i, j = best
        merged = blocks[i] | blocks[j]
        blocks = [block for k, block in enumerate(blocks) if k not in (i, j)]
        blocks.append(merged)


LINKAGES = {"single": _single_linkage, "complete": _complete_linkage}


def make(scorer_name: str, threshold: float, linkage: str):
    scorer = SCORERS[scorer_name]
    build = LINKAGES[linkage]

    def resolver(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
        return build(members, scorer, threshold)

    resolver.__name__ = f"{scorer_name}_{threshold:g}_{linkage}"
    return resolver


for _scorer_name in (*CHARACTER, *(f"cf_{name}" for name in CHARACTER)):
    for _threshold in THRESHOLDS:
        for _linkage in LINKAGES:
            _resolver = make(_scorer_name, _threshold, _linkage)
            globals()[_resolver.__name__] = _resolver

# Phonetic keys are equalities, not scores: there is nothing to sweep, so each
# gets one resolver per linkage at the only threshold that means anything.
for _scorer_name in (
    "metaphone",
    "soundex",
    "nysiis",
    "metaphone_tok",
    "soundex_tok",
    "nysiis_tok",
):
    for _linkage in LINKAGES:
        _resolver = make(_scorer_name, 100, _linkage)
        globals()[_resolver.__name__] = _resolver
