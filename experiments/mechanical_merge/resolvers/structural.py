"""Resolvers that read a surface form's token structure, not its characters.

The question this family asks is whether the *shape* of two names -- how many
tokens, which are initials, which are years, which side the extra tokens sit on,
and how many other members of the cluster could claim the shorter form -- is
enough to decide a merge without a model.

What the survey of the 18,873 recorded decisions said, before any rule was
written (56,449 candidate pairs, 16,270 of them same-entity):

  * Token containment on its own decides nothing. Every containment bucket sits
    near a coin flip: extras that are one content token, 48.3% same; two to
    three, 39.7%; year-only extras, 36.8%. Conditioning on whether the shorter
    form has exactly one superform in the cluster moves year-only from 36.8% to
    46.7%. Containment is the most common shape in the data and the least
    informative.
  * What separates the containment pairs is not the count of extra tokens but
    their *type*. Extras that are all initials are 88.6% same when the superform
    is unique; extras that are all function words, 69.6%; extras that include a
    content token, 42-54% whatever else you condition on.
  * A bare surname is safely attachable only when the inventory calls both forms
    `person` and exactly one member of the cluster ends in it: 97.8% against
    59.5% without the kind gate. Kind gating is the single largest lever here.
  * Reordering is the most reliable shape in the corpus. Same token multiset,
    different order, a comma somewhere: 96.6% same.
  * Case is never the difference. Of 1,568 pairs that are equal once casefolded,
    the live pass merged zero. `Janjaweed`/`janjaweed`, `Bushido`/`bushido`, and
    `Schlieffen Plan`/`Schlieffen plan` are all recorded as distinct entities.
    That makes case-equality a perfect veto, not a merge signal.
"""

from __future__ import annotations

import re
from itertools import combinations

from experiments.mechanical_merge.harness import Partition, as_partition

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
YEAR = re.compile(r"^\d{4}[a-z]?$")

# The one lexicon in this file. Function words that a citation or a title drops
# or restores without changing what it names.
FUNCTION_WORDS = frozenset(
    """the a an of and or in on at to for as by with
    de la le les el al du des der die das den von van und et dell della di do dos""".split()
)

# `et al.` is a claim about co-authors, so it is the one function-word pair that
# must not fold. The survey found 293 refused function-word-only pairs and this
# marker accounts for the largest share of them.
ET_AL = ("et", "al")


def tokens(surface: str) -> tuple[str, ...]:
    return tuple(t.casefold() for t in TOKEN.findall(surface))


def _is_initial(token: str) -> bool:
    return len(token) == 1


def _content(seq: tuple[str, ...]) -> tuple[str, ...]:
    """The sequence with function words removed. Single letters stay: an initial
    is content, and treating `A. Breton` as `Breton` was the survey's worst
    false merge."""
    return tuple(t for t in seq if t not in FUNCTION_WORDS or _is_initial(t))


class _Context:
    """Everything a rule needs about one cluster, computed once."""

    def __init__(self, members: tuple[str, ...], kinds: dict[str, str | None]):
        self.members = members
        self.kinds = kinds
        self.seq = {m: tokens(m) for m in members}
        self.bag = {m: set(self.seq[m]) for m in members}

    def kind(self, surface: str) -> str | None:
        return self.kinds.get(surface)

    def contains(self, small: str, big: str) -> bool:
        return self.bag[small] < self.bag[big]

    def superforms(self, small: str) -> list[str]:
        return [m for m in self.members if m != small and self.contains(small, m)]

    def ordered(self, a: str, b: str) -> tuple[str, str] | None:
        """`(shorter, longer)` if one form's token bag strictly contains the
        other's, else None."""
        if self.bag[a] < self.bag[b]:
            return a, b
        if self.bag[b] < self.bag[a]:
            return b, a
        return None


# --------------------------------------------------------------------------
# merge rules -- each returns True when the pair should be joined
# --------------------------------------------------------------------------


def rule_inversion(a: str, b: str, ctx: _Context) -> bool:
    """`Ostrom, Elinor` / `Elinor Ostrom`. Same tokens, different order, and a
    comma to say the reordering is a citation convention rather than two
    different names built from the same words."""
    sa, sb = ctx.seq[a], ctx.seq[b]
    if sa == sb or sorted(sa) != sorted(sb):
        return False
    return "," in a or "," in b


def rule_acronym(a: str, b: str, ctx: _Context) -> bool:
    """`KKK` / `Ku Klux Klan`. One form is a single token spelling out the other's
    content initials."""
    for short, long_ in ((a, b), (b, a)):
        ss, ls = ctx.seq[short], ctx.seq[long_]
        if len(ss) != 1 or len(ls) < 2:
            continue
        if len(ss[0]) >= 2 and ss[0] == "".join(t[0] for t in _content(ls)):
            return True
    return False


def rule_surname(a: str, b: str, ctx: _Context) -> bool:
    """A bare surname attaches to a fuller name only when nothing else in the
    cluster could claim it and the inventory calls both `person`. `Huxley`
    beside both `Aldous Huxley` and `Thomas Huxley` fails the uniqueness test and
    is refused."""
    pair = ctx.ordered(a, b)
    if pair is None:
        return False
    small, big = pair
    if len(ctx.seq[small]) != 1 or not ctx.seq[big]:
        return False
    if ctx.seq[big][-1] != ctx.seq[small][0]:
        return False
    if len(ctx.superforms(small)) != 1:
        return False
    return ctx.kind(small) == ctx.kind(big) == "person"


def rule_person_containment(a: str, b: str, ctx: _Context) -> bool:
    """`rule_surname` without the one-token restriction: any contiguous
    containment between two `person` forms, when the shorter has exactly one
    superform in the cluster. The kind gate is what makes this work -- the same
    shape scores 69.3% on `work`, 62.9% on `institution/group`, 54.5% on
    `country/state/place` and 42.2% on `concept`, where it is `dignitas` against
    `dignitas non moritur`."""
    pair = ctx.ordered(a, b)
    if pair is None:
        return False
    small, big = pair
    if ctx.kind(small) != "person" or ctx.kind(big) != "person":
        return False
    if len(ctx.superforms(small)) != 1:
        return False
    ss, bs = ctx.seq[small], ctx.seq[big]
    return bs[: len(ss)] == ss or bs[-len(ss) :] == ss


def rule_initials(a: str, b: str, ctx: _Context) -> bool:
    """`Gladstone` / `W. E. Gladstone`. Containment where every extra token is a
    single letter, and the shorter form has only one place to go."""
    pair = ctx.ordered(a, b)
    if pair is None:
        return False
    small, big = pair
    extra = ctx.bag[big] - ctx.bag[small]
    if not all(_is_initial(t) for t in extra):
        return False
    return len(ctx.superforms(small)) == 1


def rule_initial_expansion(a: str, b: str, ctx: _Context) -> bool:
    """`J. Hutchinson` / `John Hutchinson`. Neither form contains the other; they
    align position for position, with an initial standing in for a forename.

    Refused when the initial has more than one expansion in the cluster: `J.
    Dunn` sits beside both `James Dunn` and `John Dunn`, and joining it to either
    fuses all three."""
    if not _expands(ctx.seq[a], ctx.seq[b]):
        return False
    return all(sum(_expands(ctx.seq[x], ctx.seq[m]) for m in ctx.members) == 1 for x in (a, b))


def _expands(sa: tuple[str, ...], sb: tuple[str, ...]) -> bool:
    if sa == sb or len(sa) != len(sb):
        return False
    for x, y in zip(sa, sb):
        if x == y:
            continue
        if _is_initial(x) and y.startswith(x):
            continue
        if _is_initial(y) and x.startswith(y):
            continue
        return False
    return True


def rule_function_words(a: str, b: str, ctx: _Context) -> bool:
    """`the Dardanelles` / `Dardanelles`, `Faber & Faber` / `Faber and Faber`.
    The sequences agree once function words are dropped."""
    sa, sb = ctx.seq[a], ctx.seq[b]
    return sa != sb and _content(sa) == _content(sb)


def rule_function_words_lowercase(a: str, b: str, ctx: _Context) -> bool:
    """The same rule, dropping a function word only where the surface writes it
    in lower case. `the Dardanelles` folds; `Le Pape` does not become `Pape`,
    because a capitalised `Le` is part of the name. The surviving tokens must
    also agree in case, so `Kaiser` and `the kaiser` stay apart for the same
    reason `Janjaweed` and `janjaweed` do."""
    sa, sb = _lower_content(a), _lower_content(b)
    return ctx.seq[a] != ctx.seq[b] and sa == sb


def _lower_content(surface: str) -> tuple[str, ...]:
    return tuple(
        t
        for t in TOKEN.findall(surface)
        if not (t.islower() and t.casefold() in FUNCTION_WORDS and len(t) > 1)
    )


def rule_year_suffix(a: str, b: str, ctx: _Context) -> bool:
    """`Hendrix & Salehyan` / `Hendrix & Salehyan, 2012`. Containment where the
    extras are years, the shorter form has one superform, and the cluster names
    only one year. Measured at 45.8%: kept in the file as the negative result,
    not shipped in any recommended stack."""
    pair = ctx.ordered(a, b)
    if pair is None:
        return False
    small, big = pair
    extra = ctx.bag[big] - ctx.bag[small]
    if not extra or not all(YEAR.match(t) for t in extra):
        return False
    if len(ctx.superforms(small)) != 1:
        return False
    years = {t for m in ctx.superforms(small) for t in ctx.bag[m] - ctx.bag[small] if YEAR.match(t)}
    return len(years) == 1


# --------------------------------------------------------------------------
# vetoes -- a vetoed pair may never share a block, even through closure
# --------------------------------------------------------------------------


def veto_case_only(a: str, b: str, ctx: _Context) -> bool:
    """Zero of 1,568 casefold-equal pairs were merged by the live pass."""
    return a != b and a.casefold() == b.casefold()


def veto_cross_kind(a: str, b: str, ctx: _Context) -> bool:
    """Cross-kind pairs are 7.2% same against 39.6% for same-kind. Fires only
    when the inventory knows both kinds."""
    ka, kb = ctx.kind(a), ctx.kind(b)
    return ka is not None and kb is not None and ka != kb


def veto_et_al(a: str, b: str, ctx: _Context) -> bool:
    """`Steven Levitsky` is not `Steven Levitsky et al.`"""
    return _has_et_al(ctx.seq[a]) != _has_et_al(ctx.seq[b])


def _has_et_al(seq: tuple[str, ...]) -> bool:
    return any(seq[i : i + 2] == ET_AL for i in range(len(seq) - 1))


def veto_conjunction(a: str, b: str, ctx: _Context) -> bool:
    """One form joins two names and the other does not: `Reese` against
    `Wright & Reese`, `Robert Mendick` against `Robert Mendick and Harry Yorke`.
    Across all containment pairs, an added conjunction drops the same-entity rate
    from 47.2% to 21.1%.

    It fires only under containment. `Farrar Straus Giroux` and `Farrar, Straus
    and Giroux` name the same publisher, and there the conjunction is
    punctuation, not a second author."""
    if ctx.ordered(a, b) is None:
        return False
    return _joins(a, ctx.seq[a]) != _joins(b, ctx.seq[b])


CONJUNCTIONS = frozenset({"and", "et", "und", "e"})


def _joins(surface: str, seq: tuple[str, ...]) -> bool:
    return "&" in surface or any(t in CONJUNCTIONS for t in seq)


def veto_numeric_locator(a: str, b: str, ctx: _Context) -> bool:
    """`Thucydides` / `Thucydides 3`, `UNMIK Pillar I` / `UNMIK Pillar IV`. A
    difference that is only a number or a roman numeral is a pointer into a work,
    not a spelling variant."""
    da = ctx.bag[a] - ctx.bag[b]
    db = ctx.bag[b] - ctx.bag[a]
    diff = da | db
    if not diff:
        return False
    return all(_is_locator(t) for t in diff)


ROMAN = re.compile(r"^[ivxlcdm]+$")


def _is_locator(token: str) -> bool:
    if YEAR.match(token):
        return False
    return token.isdigit() or bool(ROMAN.match(token))


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------


def build(merges, vetoes=()):
    """A resolver that joins every pair some rule in `merges` accepts, subject to
    `vetoes`, then closes transitively -- refusing any union that would put a
    vetoed pair in one block."""

    def resolve(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
        if len(members) < 2:
            return as_partition([], members)
        ctx = _Context(members, kinds)
        blocked = set()
        candidates = []
        for a, b in combinations(members, 2):
            if any(veto(a, b, ctx) for veto in vetoes):
                blocked.add(frozenset({a, b}))
            elif any(rule(a, b, ctx) for rule in merges):
                candidates.append((a, b))

        blocks = {m: {m} for m in members}
        for a, b in candidates:
            left, right = blocks[a], blocks[b]
            if left is right:
                continue
            if any(frozenset({x, y}) in blocked for x in left for y in right):
                continue
            joined = left | right
            for member in joined:
                blocks[member] = joined
        return as_partition([sorted(block) for block in blocks.values()], members)

    return resolve


VETOES = (
    veto_case_only,
    veto_cross_kind,
    veto_et_al,
    veto_conjunction,
    veto_numeric_locator,
)

# each rule on its own, no vetoes
inversion = build([rule_inversion])
acronym = build([rule_acronym])
surname = build([rule_surname])
person_containment = build([rule_person_containment])
initials = build([rule_initials])
initial_expansion = build([rule_initial_expansion])
function_words = build([rule_function_words])
function_words_lowercase = build([rule_function_words_lowercase])
year_suffix = build([rule_year_suffix])

# the same rules with the veto set, to isolate what the vetoes buy
surname_vetoed = build([rule_surname], VETOES)
person_containment_vetoed = build([rule_person_containment], VETOES)
initials_vetoed = build([rule_initials], VETOES)
initial_expansion_vetoed = build([rule_initial_expansion], VETOES)
function_words_vetoed = build([rule_function_words], VETOES)
function_words_lowercase_vetoed = build([rule_function_words_lowercase], VETOES)
year_suffix_vetoed = build([rule_year_suffix], VETOES)

CORE = [rule_inversion, rule_acronym, rule_person_containment, rule_initials]
WIDE = CORE + [rule_initial_expansion, rule_function_words_lowercase]

core = build(CORE)
core_vetoed = build(CORE, VETOES)
balanced = build(CORE + [rule_initial_expansion], VETOES)
wide = build(WIDE, VETOES)
wide_loose_functions = build(CORE + [rule_initial_expansion, rule_function_words], VETOES)
wide_plus_years = build(WIDE + [rule_year_suffix], VETOES)


def merge_all_vetoed(members: tuple[str, ...], kinds: dict[str, str | None]) -> Partition:
    """The other direction: trust the clusterer, then subtract what the vetoes
    forbid. Measures how much of `merge-all`'s 40,179 false pairs are structural
    rather than semantic."""
    return build([lambda a, b, ctx: True], VETOES)(members, kinds)
