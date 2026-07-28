"""neo4all's own rule, transplanted and measured.

From `api/services/curation/{similarity,candidates}.py`. The emit rule, in one
line, is:

    JW >= 0.95  OR  (JW >= 0.90 AND token_overlap >= 0.5)  OR  token_containment

with Jaro-Winkler hand-rolled (prefix bonus applied unconditionally, no Jaro
floor), `token_overlap` a Dice coefficient over lowercased alphanumeric tokens,
and `token_containment` true when every content token of the shorter surface
appears in the longer.

One thing has to be said before the numbers: in neo4all this rule does not
decide anything. Since its 1.0.8 release nothing merges mechanically -- the
rule GENERATES CANDIDATES, and an LLM plus a human approves each one. Scoring
it as a decider is therefore not a fair test of neo4all; it is a test of
whether the technique transfers to the job Axial needs done, which is the
decision itself. Axial already has the candidate-generation half: HDBSCAN
clusters are what these functions would produce.

`as_written` reproduces the live behaviour, including the containment guard
bug (`< 1` where the docstring, CHANGELOG and three currently-failing unit
tests all say `< 2`). `guard_fixed` is the same rule with the intended guard.
`no_containment` drops the containment arm entirely.
"""

from __future__ import annotations

import re
from itertools import combinations

from experiments.mechanical_merge.harness import Partition, as_partition

_TOKEN = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """a an and are as at be but by for from had has have he her his how i if in into is
    it its may my no nor not of on or our out own per she so than that the their them then
    there these they this to too up us was we were what when which who why will with would
    you your""".split()
)


def _jaro(s: str, t: str) -> float:
    if s == t:
        return 1.0
    ls, lt = len(s), len(t)
    if not ls or not lt:
        return 0.0
    window = max(max(ls, lt) // 2 - 1, 0)
    s_m, t_m = [False] * ls, [False] * lt
    matches = 0
    for i in range(ls):
        lo, hi = max(0, i - window), min(i + window + 1, lt)
        for j in range(lo, hi):
            if not t_m[j] and s[i] == t[j]:
                s_m[i] = t_m[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions = k = 0
    for i in range(ls):
        if not s_m[i]:
            continue
        while not t_m[k]:
            k += 1
        if s[i] != t[k]:
            transpositions += 1
        k += 1
    return (matches / ls + matches / lt + (matches - transpositions / 2) / matches) / 3.0


def _jaro_winkler(s: str, t: str, p: float = 0.1) -> float:
    jaro = _jaro(s, t)
    prefix = 0
    for a, b in zip(s[:4], t[:4]):
        if a != b:
            break
        prefix += 1
    return jaro + prefix * p * (1.0 - jaro)


def _token_overlap(s: str, t: str) -> float:
    a, b = set(_TOKEN.findall(s.lower())), set(_TOKEN.findall(t.lower()))
    total = len(a) + len(b)
    return 2.0 * len(a & b) / total if total else 0.0


def _content_tokens(s: str) -> set[str]:
    return {t for t in _TOKEN.findall(s.lower()) if t not in _STOPWORDS and len(t) > 1}


def _token_containment(s: str, t: str, min_tokens: int, min_short_len: int = 3) -> bool:
    ts, tt = _content_tokens(s), _content_tokens(t)
    if not ts or not tt or ts == tt:
        return False
    if len(ts) < len(tt):
        shorter, longer, shorter_str = ts, tt, s
    elif len(ts) > len(tt):
        shorter, longer, shorter_str = tt, ts, t
    else:
        return False
    if len(shorter) < min_tokens or len(shorter_str.strip()) < min_short_len:
        return False
    return shorter <= longer


def _build(min_tokens: int | None):
    """`min_tokens=None` drops the containment arm."""

    def resolve(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
        blocks = {member: {member} for member in members}
        for a, b in combinations(members, 2):
            # neo4all compares the lowercased primary value (`_primary_value`).
            left, right = a.lower().strip(), b.lower().strip()
            jw = _jaro_winkler(left, right)
            emit = jw >= 0.95 or (jw >= 0.90 and _token_overlap(left, right) >= 0.5)
            if not emit and min_tokens is not None:
                emit = _token_containment(left, right, min_tokens)
            if not emit or blocks[a] is blocks[b]:
                continue
            joined = blocks[a] | blocks[b]
            for member in joined:
                blocks[member] = joined
        return as_partition([sorted(block) for block in blocks.values()], members)

    return resolve


as_written = _build(1)
guard_fixed = _build(2)
no_containment = _build(None)
