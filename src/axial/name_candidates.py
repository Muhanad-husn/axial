"""Issue #446: candidate-cluster generation for Reconcile (slice 05,
`axial.merge_names`).

The merge pass is not making bad calls -- it is never being asked. Slice 04's
clustering (`axial.names`, D10) is a viewing aid, tuned loose so it does not
fuse things that must stay apart (#442 measured why raising it globally is
wrong: it also fuses distinct entities). But loose has a recall cost: two
surface forms naming the same thing routinely land in different clusters, so
no merge call ever sees them together, and both survive as separate canonical
names (`C. Tilly.md` / `Charles Tilly.md`).

This module is a SECOND, deterministic, LLM-free step, run alongside slice
04's clustering rather than instead of it. It proposes the missing pairs as
additional candidate clusters, handed to the exact same, unchanged merge call
(`axial.merge_names._decide_batch`) -- every proposal is still just a cluster
the model may reject, exactly like an HDBSCAN one. This module decides
nothing and merges nothing itself (§7.16, D10); §7.16's own words: "a merge
pass may fold names, never invent them."

Three rules, all exact string shape -- no fuzzy matching and no similarity
threshold, per #442's own finding that fuzzy matching cannot pass this
corpus's traps at any usable precision:

  1. **Initial vs full forename, same surname, same first letter** --
     `C. Tilly` / `Charles Tilly`. Refused whenever the initial form has more
     than one full-forename candidate: `R. Cohen` matches both `Robin Cohen`
     and `Roger Cohen`, and neither pair is proposed. A form carrying a
     second initial (`A. D. Smith`) is a different shape and is not matched
     by this rule at all -- it is not a two-token initial+surname surface,
     so `Adam Smith` is never a candidate for it.
  2. **A bare (single-token) surname against a full name sharing that
     surname, both `kind == "person"`.** Refused whenever more than one
     full-name candidate exists -- bare `'Ali` against seven distinct people
     is refused entirely (#442's measured 97.8%-reliable gate).
  3. **Case-only and whitespace-only pairs.** Two surface forms whose
     casefolded, whitespace-collapsed forms are identical but whose written
     forms differ (the 230-pair residual #441 left, from the same casefold
     collision that corrupted the merge parser).

Casefold, never strip: this corpus's surnames carry apostrophes, hyphens and
diacritics (`'Ammash`, `Abdo-Katsipis`, `Malešević`), and those characters are
part of the surname's identity, not noise to remove before comparing.
"""

from __future__ import annotations

import re
from typing import Iterable

_WHITESPACE = re.compile(r"\s+")

# `names[]`'s own `kind` value for a person (`axial.interrogate`'s codebook
# example vocabulary) -- the gate issue #446 states for family 2 ("both sides
# kind == person").
_PERSON_KIND = "person"


def _normalize_form(surface: str) -> str:
    """Casefold, collapsing internal whitespace to one space and trimming the
    ends -- never strips accents, hyphens or apostrophes, which this corpus's
    surnames carry as part of the name itself."""
    return _WHITESPACE.sub(" ", surface).strip().casefold()


def _is_initial_token(token: str) -> bool:
    """A single letter followed by a period -- `C.`, `A.` -- family 1's
    short-form half. An exact token shape, not a length heuristic."""
    return len(token) == 2 and token[1] == "." and token[0].isalpha()


def _is_full_forename_token(token: str) -> bool:
    """A forename token that is NOT an initial -- family 1's long-form half."""
    return len(token) > 1 and token[0].isalpha() and token[-1] != "."


def _first_letter(token: str) -> str | None:
    if not token or not token[0].isalpha():
        return None
    return token[0].casefold()


def _family_initial_forename(surface_forms: Iterable[str]) -> list[tuple[str, str]]:
    """Family 1 (issue #446): `<initial>. <surname>` against
    `<forename> <surname>`, same surname (casefolded) and same first letter.
    Only exactly-two-token surfaces are considered on either side, which is
    what keeps `A. D. Smith` (three tokens) out of this rule entirely --
    it is a different surface shape, not a family-1 case refused on
    ambiguity."""
    initials: dict[tuple[str, str], list[str]] = {}
    fulls: dict[tuple[str, str], list[str]] = {}
    for surface in surface_forms:
        tokens = surface.split()
        if len(tokens) != 2:
            continue
        forename, surname = tokens
        letter = _first_letter(forename)
        if letter is None:
            continue
        key = (surname.casefold(), letter)
        if _is_initial_token(forename):
            initials.setdefault(key, []).append(surface)
        elif _is_full_forename_token(forename):
            fulls.setdefault(key, []).append(surface)

    pairs: list[tuple[str, str]] = []
    for key, initial_surfaces in initials.items():
        candidates = fulls.get(key, [])
        if len(candidates) != 1:
            # 0: no full form exists, nothing to propose.
            # >1: ambiguous (e.g. `R. Cohen` / `Robin Cohen` / `Roger Cohen`)
            # -- refuse rather than guess.
            continue
        for initial_surface in initial_surfaces:
            pairs.append((initial_surface, candidates[0]))
    return pairs


def _family_bare_surname(
    entries: Iterable[tuple[str, str | None, int]],
) -> list[tuple[str, str]]:
    """Family 2 (issue #446, #442's measured rule): a bare (single-token)
    person surname against a full person name sharing that surname, gated on
    exactly one candidate. Bare `'Ali` against seven distinct people is
    refused entirely -- this is the 2,025-ambiguous-pairs exclusion the issue
    names."""
    bare: dict[str, str] = {}
    candidates: dict[str, list[str]] = {}
    for surface, kind, _count in entries:
        if kind != _PERSON_KIND:
            continue
        tokens = surface.split()
        if len(tokens) == 1:
            bare.setdefault(tokens[0].casefold(), surface)
        elif len(tokens) > 1:
            candidates.setdefault(tokens[-1].casefold(), []).append(surface)

    pairs: list[tuple[str, str]] = []
    for key, bare_surface in bare.items():
        full_candidates = candidates.get(key, [])
        if len(full_candidates) != 1:
            continue
        pairs.append((bare_surface, full_candidates[0]))
    return pairs


def _family_case_or_whitespace(surface_forms: Iterable[str]) -> list[tuple[str, ...]]:
    """Family 3 (issue #446, #441's acknowledged residual): surface forms
    identical once casefolded and whitespace-collapsed, but written
    differently -- proposed as one cluster of however many variants share
    the normalized form."""
    groups: dict[str, list[str]] = {}
    for surface in surface_forms:
        groups.setdefault(_normalize_form(surface), []).append(surface)
    return [tuple(sorted(set(members))) for members in groups.values() if len(set(members)) > 1]


def generate_candidate_clusters(
    entries: Iterable[tuple[str, str | None, int]],
) -> list[tuple[str, ...]]:
    """Every candidate cluster the three families propose, over the whole
    name inventory (`entries`: `(surface_form, kind, count)`, `axial.names.
    InventoryEntry`'s own shape), deduplicated by member set.

    Each returned tuple is >= 2 surface forms that were never handed to the
    merge model together by slice 04's own clustering. This function decides
    nothing: every returned cluster still goes to the same, unchanged merge
    call as any HDBSCAN cluster, and the model may reject it exactly as it
    may reject any other hint (§7.16, D10)."""
    entries = list(entries)
    surface_forms = [surface for surface, _kind, _count in entries]

    candidates: list[tuple[str, ...]] = []
    candidates.extend(_family_initial_forename(surface_forms))
    candidates.extend(_family_bare_surname(entries))
    candidates.extend(_family_case_or_whitespace(surface_forms))

    seen: set[frozenset[str]] = set()
    deduped: list[tuple[str, ...]] = []
    for members in candidates:
        key = frozenset(members)
        if key in seen or len(key) < 2:
            continue
        seen.add(key)
        deduped.append(tuple(sorted(members)))
    return deduped
