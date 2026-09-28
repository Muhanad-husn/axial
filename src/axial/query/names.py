"""Name-layer query: `find_names`/`get_name` over the store, and the alias
map's own surface resolution (Phase-B stage 3, specs/PHASE-B.md §7.5, §8
P0-2, issue #487; retired down to this shape by DEC-75, issue #853).

`axial.query.reader` is the note layer -- a note or a source by an id the
caller already holds. This module is the layer that lets a caller FIND a
name the corpus carries. It used to also carry four traversal tools
(`name_neighbors`, `who_cites`, `who_argues_against`, `where_names_meet`)
walking either a rendered name page or the prose notes' own answer blocks;
all four, and the name pages themselves, are retired (DEC-75) -- the final
output never read a page, only ever `chunk_id`s and the store. What remains
replaces `query_by_tag`, `query_by_polity` and `follow_backlinks`, which
returned 0 on every axis against the v1 vault because the facets they
filtered were deleted with the tag pass (D1/D5).

Two substrates, two arguments:

- **`names_dir`** (`data/names/`) -- Reconcile's own artifacts: `index.json`
  (the surviving canonical set) and `alias_map.json` (`{canonical, kind,
  aliases}` per node). Surface resolution (`canonical_for_surface` and
  `find_names`' literal routes) reads these.
- **`vault_dir`** (`data/vault/`) -- the note store Materialize wrote
  (`notes.db`, `axial.query.store`, DEC-62). Everything a note says about
  itself is read from here, never recomputed.

**`find_names` and `get_name` are answered from the store alone** (DEC-62,
issue #648; DEC-75 dropped the name-page fallback both used to have): the
door layer is one GROUP BY and one join over `note_names`. A vault with no
store answers `[]`/raises `NameNotFoundError` -- there is nothing else here
to fall back to.

**Zero LLM calls, zero network calls** (§7.5): `find_names` is purely
literal now (exact/alias/folded/contains, issue #632, plus its
compound-query word fallback) -- the embedding-based nearest-neighbour tier
that used to sit past these four is retired along with the name pages it
resolved to (DEC-75). Importing this module costs nothing.

**Determinism** (§7.5, binding on every tool here): every result is sorted
explicitly and every ranked tool states its whole tie-break, so the order is
total and filesystem enumeration order can never leak into an answer.

Import discipline mirrors `axial.query.reader`'s: nothing here imports
`axial.names`, `axial.merge_names` or `axial.materialize`, each of which
pulls the LLM/clustering stack in to define a path constant. The few small
values borrowed from them (the name-layer filenames) are repeated here as
deliberate, stated duplicates -- the same trade `reader._default_
envelopes_dir` already makes. `axial.name_candidates` is the one exception:
it imports only `re`, and its surface fold is reused rather than re-derived
(§7.16, issue #463 -- a second copy of that rule is exactly the drift the
one-shared-copy discipline exists to prevent).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from axial.name_candidates import _normalize_form as fold_surface_form
from axial.paths import default_names_dir, default_vault_dir
from axial.query import store as note_store
from axial.query.reader import QueryError, is_abstention

# Reconcile's own artifact filenames under `names_dir`
# (`axial.merge_names.DEFAULT_INDEX_PATH`/`DEFAULT_ALIAS_MAP_PATH`),
# repeated here rather than imported -- see the module docstring.
INDEX_FILENAME = "index.json"
ALIAS_MAP_FILENAME = "alias_map.json"

# How many hits a tool returns when the caller states no limit of its own.
DEFAULT_LIMIT = 10

# The routes `find_names` unions into its door slate (§7.5, issue #632).
# `exact`/`alias`/`folded` are the three original tiers, each an exact
# lookup over the name layer. `contains` is a name whose folded form carries
# the folded query as a whole-word phrase. `word` marks a hit found by the
# compound-query fallback (resolving one content word of a query that
# matched no name at all) rather than the query's own phrase, so a caller
# can tell "your phrase matched no name; this word did" from a real phrase
# resolution. The embedding-based nearest-neighbour tier that used to sit
# past these four is retired along with the name pages it resolved to
# (DEC-75, issue #853).
TIER_EXACT = "exact"
TIER_ALIAS = "alias"
TIER_FOLDED = "folded"
TIER_CONTAINS = "contains"
TIER_WORD = "word"


# A short list of function words to skip when the compound-query fallback
# (issue #632) splits a query into content words -- tiny and deliberately
# so: the fallback's whole point is that even noisy per-word doors (`party`,
# `de`) are useful once shown with their own numbers, so this only screens
# the words a scholar or concept name never actually is. Checked: no
# dependency this module already carries exposes a stopword list at the
# base-dependency tier (`sklearn`'s is `distill`-group-only, and pulling in
# an NLP library for eleven words would be reinventing this).
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "nor",
        "not",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)

# Whitespace or any hyphen variant (mirrors `axial.name_candidates._HYPHENS`,
# the same characters the surface fold treats as a word separator) --
# splits a query into raw-case content-word tokens for the compound-query
# fallback.
_WORD_SPLIT = re.compile(r"[\s\-‐‑‒–—]+")

class NameNotFoundError(QueryError):
    """No door exists for a `get_name` canonical in the vault's store
    (DEC-75, issue #853: `get_name` answers from `notes.db` alone, never a
    name page). Distinct from `find_names` returning `[]`, which is a real
    answer about the corpus, not a lookup failure."""

    def __init__(self, canonical: str, path: Path):
        self.canonical = canonical
        self.path = path
        super().__init__(f"no door found for {canonical!r} in the store at {path}")


@dataclass(frozen=True)
class NameHit:
    """One `find_names` result: one door in the slate (§7.5, issue #632).
    `matched_on` is the surface form (or, for a `word`-tier hit, the query
    word) that actually matched, and `tier` is which route produced it
    (`exact`/`alias`/`folded`/`contains`/`word`), so a caller can see how
    confident the resolution is. `member_count`/`source_count` are the
    door's own -- the total member notes and the number of distinct sources
    they span (`axial.query.store.doors`) -- or `None` when the store
    carries no door for the name (reported rather than filled in with a 0
    that would read like real, thin coverage)."""

    canonical: str
    kind: str | None
    aliases: list[str]
    member_count: int | None
    matched_on: str
    tier: str
    source_count: int | None = None


@dataclass(frozen=True)
class NameMember:
    """One name's member note, as `axial.query.store.name_members` reads it.
    `author`/`year` are `None` when the store's own columns carry none for
    that source -- stated rather than guessed at, since the real corpus's
    own author rendering is not uniform."""

    chunk_id: str
    source_id: str | None
    author: str | None
    year: str | None
    claim: str


@dataclass(frozen=True)
class Disagreement:
    """Retired (DEC-75, issue #853): Gather, the only writer of a finding in
    this shape, is gone along with the name pages it wrote them onto.
    `NamePage.disagreement` is always `None` now; this class stays only so
    that field's type is still meaningful."""

    text: str
    names: list[str]


@dataclass(frozen=True)
class NamePage:
    """One name's door, joined from the store (§7.17's shape, answered from
    `notes.db` since DEC-75). `disagreement` is always `None`."""

    canonical: str
    kind: str | None
    aliases: list[str]
    member_count: int
    members: list[NameMember]
    disagreement: Disagreement | None


# `NameNeighbor`/`CitationEdge`/`OppositionEdge` -- the result shapes of
# `name_neighbors`/`who_cites`/`who_argues_against` -- are retired with
# those functions (DEC-75, issue #853).


# ---------------------------------------------------------------------------
# The name layer (`names_dir`): index, alias map, folds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NameLayer:
    """Reconcile's alias map and index, indexed for the three exact-lookup
    tiers. Every multi-valued mapping holds a SORTED list, not a single
    value: a dirty map can carry one alias string under two nodes, and
    silently keeping whichever was read last would make the answer depend on
    file order."""

    canonicals: frozenset[str]
    kind_by_canonical: dict[str, str | None]
    aliases_by_canonical: dict[str, list[str]]
    canonicals_by_alias: dict[str, list[str]]
    # folded surface -> [(canonical, the surface form that folded to it), ...]
    folded: dict[str, list[tuple[str, str]]]
    # canonical -> every folded form of its own canonical + aliases
    folds_by_canonical: dict[str, frozenset[str]]


_NAME_LAYER_CACHE: dict[Path, _NameLayer] = {}
_NAME_LAYER_LOCK = threading.Lock()


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_name_layer(names_dir: Path) -> _NameLayer:
    """Read `alias_map.json` and `index.json` into the lookup shapes the
    tiers need. Both absent is not an error here: a caller pointed at a
    vault with no name layer gets a layer that resolves nothing, and every
    tool degrades to "this name is not in the corpus" -- which is exactly
    what it means."""
    alias_map = _read_json(names_dir / ALIAS_MAP_FILENAME) or {}
    nodes = alias_map.get("nodes") or []
    index = _read_json(names_dir / INDEX_FILENAME) or {}
    index_names = index.get("names") or []

    kind_by_canonical: dict[str, str | None] = {}
    aliases_by_canonical: dict[str, list[str]] = {}
    canonicals_by_alias: dict[str, set[str]] = {}
    folded: dict[str, set[tuple[str, str]]] = {}
    folds_by_canonical: dict[str, set[str]] = {}

    def register(canonical: str, surface: str) -> None:
        folded.setdefault(fold_surface_form(surface), set()).add((canonical, surface))
        folds_by_canonical.setdefault(canonical, set()).add(fold_surface_form(surface))

    for node in nodes:
        canonical = node.get("canonical")
        if not isinstance(canonical, str):
            continue
        kind_by_canonical[canonical] = node.get("kind")
        aliases = [alias for alias in (node.get("aliases") or []) if isinstance(alias, str)]
        aliases_by_canonical[canonical] = aliases
        register(canonical, canonical)
        for alias in aliases:
            canonicals_by_alias.setdefault(alias, set()).add(canonical)
            register(canonical, alias)

    # A name in the index with no alias-map node is still a name the corpus
    # carries (§7.16: nothing is dropped), so it resolves as its own
    # canonical with no aliases and no kind.
    for name in index_names:
        if isinstance(name, str) and name not in kind_by_canonical:
            kind_by_canonical[name] = None
            aliases_by_canonical[name] = []
            register(name, name)

    return _NameLayer(
        canonicals=frozenset(kind_by_canonical),
        kind_by_canonical=kind_by_canonical,
        aliases_by_canonical=aliases_by_canonical,
        canonicals_by_alias={
            alias: sorted(values) for alias, values in canonicals_by_alias.items()
        },
        folded={key: sorted(values) for key, values in folded.items()},
        folds_by_canonical={
            canonical: frozenset(values) for canonical, values in folds_by_canonical.items()
        },
    )


def _name_layer(names_dir: Path | None) -> _NameLayer:
    """The process-lifetime name layer for `names_dir`, keyed by resolved
    path so distinct layers (real callers, per-test fixtures) never share an
    entry. Built lazily, at most once, under a lock: the first caller in a
    freshly started many-threaded run is otherwise a near-certain pile-up of
    duplicate cold builds (the same reason `reader._frontmatter_index` holds
    one)."""
    directory = Path(names_dir) if names_dir is not None else default_names_dir()
    key = directory.resolve()
    cached = _NAME_LAYER_CACHE.get(key)
    if cached is not None:
        return cached
    with _NAME_LAYER_LOCK:
        cached = _NAME_LAYER_CACHE.get(key)
        if cached is None:
            cached = _build_name_layer(directory)
            _NAME_LAYER_CACHE[key] = cached
        return cached


def canonical_for_surface(surface: str, layer: _NameLayer) -> str | None:
    """The canonical `surface` belongs to, through the same three exact
    lookups `find_names`' first three tiers use, in the same order. `None`
    when the layer carries no such surface at all -- the caller decides
    whether that means "unknown name" or "an unmerged surface that is its own
    canonical"."""
    if surface in layer.canonicals:
        return surface
    aliased = layer.canonicals_by_alias.get(surface)
    if aliased:
        return aliased[0]
    folded = layer.folded.get(fold_surface_form(surface))
    if folded:
        return folded[0][0]
    return None


def canonical_name_for_surface(surface: str, *, names_dir: Path | None = None) -> str | None:
    """The canonical name `surface` belongs to, resolved **through the alias
    map alone** -- `canonical_for_surface`'s three exact tiers (canonical,
    alias, fold), with the name layer resolved from `names_dir` for a caller
    that holds a surface form and no layer. `None` when the index carries no
    such surface.

    The public wrapper exists for §7.4's `names_touched` (issue #489), which
    resolves a grounds note's own `names` answers to canonicals so the §7.7
    coverage map is computable from the claim graph. It deliberately reaches
    only the three exact tiers, never a fuzzy match: §7.4 drops a surface
    the index does not carry rather than inventing one."""
    return canonical_for_surface(surface, _name_layer(names_dir))


# ---------------------------------------------------------------------------
# The vault's name pages (`vault_dir/names/`)
# ---------------------------------------------------------------------------


# Name pages are gone (DEC-75, issue #853): `find_names`/`get_name` answer
# from the store (`axial.query.store`) alone now, never a page fallback.
# `Disagreement`/`NamePage.disagreement` stay in the return shape below,
# always `None` -- Gather, the one writer of that section, is retired with
# the pages it wrote it onto.


# ---------------------------------------------------------------------------
# The prose notes' answer blocks (`vault_dir/prose/`)
# ---------------------------------------------------------------------------


def as_string_list(value: Any) -> list[str]:
    """A free-text answer that may be a list of strings, one string, or
    absent, read as a list of strings. `arguing_against` is a list on the
    real corpus, but nothing enforces that on a free-text answer, so a bare
    string is accepted as a one-item list rather than silently dropped.
    Kept here for `axial.materialize.build_note_store`, which reuses it
    rather than re-deriving the same rule (DEC-75, issue #853: the retired
    `name_neighbors`/`who_cites`/`who_argues_against` used to be this
    function's other callers, over the prose-note answer index those tools
    walked)."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


# ---------------------------------------------------------------------------
# find_names -- the entry point (§7.5)
# ---------------------------------------------------------------------------


# Name-page resolution's embedding tier is gone (DEC-75, issue #853): a
# fuzzy nearest-neighbour fallback existed to hand back a page when the
# literal routes below found nothing, and with the pages gone there is
# nothing left for it to hand back. `data/names/embeddings.lance` itself
# stays -- `axial.merge_names`'s blocking step still reads it -- only the
# query-time encoder/vector-search path over it is retired.


def _contains_matches(folded_query: str, vault_dir: Path) -> list[str]:
    """Every name whose folded form carries `folded_query` as a whole-word
    phrase (issue #632's `contains` route) -- `Mandate` matches `French
    Mandate` and `mandate period`, never `mandated`.

    One `instr` scan over the store's own `names.folded` column (DEC-62). A
    vault with no store -- one materialized before it existed, or before
    DEC-75 retired the name pages the store superseded -- answers `[]`
    rather than falling back to a page scan that no longer exists."""
    if not folded_query:
        return []
    connection = note_store.connect(vault_dir)
    if connection is None:
        return []
    try:
        return note_store.contains_matches(connection, folded_query)
    finally:
        connection.close()


def _doors(vault_dir: Path, canonicals: list[str]) -> dict[str, note_store.Door]:
    """`canonical -> Door` (kind, member_count, source_count) for the names
    given -- the store's own GROUP BY over `note_names` (DEC-62). A vault
    with no store answers `{}`: every canonical is then reported with an
    unknown count rather than a 0 (DEC-75, issue #853 -- the name-page door
    index this used to fall back to is retired with the pages)."""
    connection = note_store.connect(vault_dir)
    if connection is None:
        return {}
    try:
        return note_store.doors(connection, canonicals)
    finally:
        connection.close()


def _content_words(query: str) -> list[str]:
    """`query` split on whitespace and hyphens (`_WORD_SPLIT`, the same
    separators the surface fold treats as word boundaries), stopwords
    dropped, original casing kept -- the compound-query fallback's own
    tokenizer (issue #632). `"mandate-era institutions Syria"` yields
    `["mandate", "era", "institutions", "Syria"]`."""
    tokens = [token for token in _WORD_SPLIT.split(query) if token]
    return [token for token in tokens if token.casefold() not in _STOPWORDS]


def content_words(query: str) -> list[str]:
    """Public wrapper over `_content_words` (issue #649's intake fork-check
    is the first caller outside this module's own compound-query fallback):
    the same tokenizer and the same stopword list, so a term the intake
    measurement treats as a "concept the question touches" is the identical
    term `find_names`' own word-level fallback would resolve it as."""
    return _content_words(query)


def content_word_runs(text: str) -> list[list[str]]:
    """`text` split into maximal runs of consecutive CONTENT words -- the
    same tokenizer and stopword list `content_words` uses, but grouped by
    TRUE TEXT ADJACENCY rather than flattened into one list (issue #649's
    intake fork-check, which resolves the question's own PHRASES rather
    than every content word in isolation). Two content words separated by
    a stopword are two different runs, never joined into one: "regime" and
    "Syria" in "regime durability in Syria" are not one run, because "in"
    sits between them, and testing "durability Syria" as a phrase would be
    testing an adjacency the question's own words never had. A run ends
    (and a new one starts) at every stopword and at the text's own start
    and end; a lone content word between two stopwords is still a
    (length-1) run of its own."""
    tokens = [token for token in _WORD_SPLIT.split(text) if token]
    runs: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token.casefold() in _STOPWORDS:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(token)
    if current:
        runs.append(current)
    return runs


def _group_one_candidates(
    query: str,
    layer: _NameLayer,
    vault_dir: Path,
    *,
    contains: list[str] | None = None,
) -> list[tuple[str, str, str]]:
    """`(canonical, matched_on, tier)` for every literal route's hit on
    `query` -- the union `exact` ∪ `alias` ∪ `folded` ∪ `contains` (issue
    #632) -- deduplicated by canonical: whichever route below matches a
    canonical FIRST wins its `tier`/`matched_on` (`dict.setdefault`, tried in
    `exact`, `alias`, `folded`, `contains` order), so a canonical that is
    both an exact hit and incidentally contains itself is reported as
    `exact`, never demoted to the vaguer route that also happens to find it.
    Unranked and untruncated: `_rank_group_one` orders the result, and a
    caller decides whether to use it as the phrase-level group or feed one
    query word from the compound-query fallback.

    `contains`, when given, replaces the `contains`-route scan with an
    already-computed page-name list -- the compound-query fallback's own
    per-word frequency count (`_compound_fallback_candidates`) already pays
    for this exact scan, and re-running it here would be a second 49,674-name
    pass for the same word."""
    matches: dict[str, tuple[str, str]] = {}

    if query in layer.canonicals:
        matches[query] = (query, TIER_EXACT)

    for canonical in sorted(layer.canonicals_by_alias.get(query, ())):
        matches.setdefault(canonical, (query, TIER_ALIAS))

    folded_query = fold_surface_form(query)
    # One canonical, one hit: a query can fold onto a canonical AND onto one
    # of that same canonical's aliases (the corpus writes both "bellicist
    # state formation" and "bellicist state-formation"), which is one name,
    # not two. Walked in sorted order, so the surviving `matched_on` is the
    # lowest matching surface form, deterministically.
    for canonical, surface in sorted(layer.folded.get(folded_query, ())):
        matches.setdefault(canonical, (surface, TIER_FOLDED))

    found_contains = (
        contains if contains is not None else _contains_matches(folded_query, vault_dir)
    )
    for name in found_contains:
        matches.setdefault(name, (name, TIER_CONTAINS))

    return [(canonical, matched_on, tier) for canonical, (matched_on, tier) in matches.items()]


def _rank_group_one(
    candidates: list[tuple[str, str, str]],
    layer: _NameLayer,
    doors: dict[str, note_store.Door],
) -> list[tuple[str, str, str]]:
    """Group 1's own order (issue #632): `kind == "work"` last, then
    `source_count` descending, then `member_count` descending, then
    canonical ascending -- a total order. The `work` demotion is measured,
    not taste: 8,583 of the vault's 49,674 pages are book/article titles, and
    for a concept query they crowd out the argument pages a `contains` scan
    also turns up (`sectarianism` pulls five `Culture of Sectarianism`
    variants ahead of nothing) -- a work is a citation target, which
    `who_cites` already serves. `None` counts (an orphan canonical with no
    materialized page) sort as `0`, lowest."""

    def sort_key(candidate: tuple[str, str, str]) -> tuple[bool, int, int, str]:
        canonical, _matched_on, _tier = candidate
        door = doors.get(canonical)
        kind = layer.kind_by_canonical.get(canonical) or (door.kind if door is not None else None)
        source_count = door.source_count if door is not None else None
        member_count = door.member_count if door is not None else None
        return (kind == "work", -(source_count or 0), -(member_count or 0), canonical)

    return sorted(candidates, key=sort_key)


def _compound_fallback_candidates(
    query: str,
    layer: _NameLayer,
    vault_dir: Path,
) -> list[tuple[str, str, str]]:
    """The compound-query fallback (issue #632): when the query's own phrase
    matches no page at all, resolve each content word separately (the same
    group-1 union and ranking, per word) and offer the best door for each --
    `"mandate-era institutions Syria"` -> `mandate -> French Mandate`,
    `syria -> Syria`. Every hit is marked `TIER_WORD`, never the underlying
    route that actually matched the word, so a caller can tell a real
    phrase resolution from "your phrase matched no page; this word did".
    `matched_on` is the query word itself, not the page name, for the same
    reason. Deduplicated by canonical (an earlier word's door is kept over a
    later word's repeat of it).

    **Ordered by vocabulary rarity, rarest word first -- not query order and
    not door size (issue #632, second round).** A generic connective word
    (`Syrian`, `de`, `Robert`, `state`) appears in hundreds of page names, so
    its own biggest same-family door -- `Syrian government`, `Charles de
    Gaulle`, `Robert R. Kaufman`, `nation-state` -- used to lead the slate
    ahead of the word that actually names what the query is about, moving a
    door that was already correct pre-#632 out of first place. `frequency`
    is how many page names contain each word as a whole word (the same
    `contains` scan every word already pays for, its own result length --
    no second pass), and the rarest word's door leads because the rare word
    is the one that names the query's actual topic; a word every third page
    carries is a connective, not a topic. This is a different quantity over
    a different set from #522's own IDF finding: #522 ranked a hub's
    NEIGHBOURS by their own size and found no rarity gradient (a hub's
    neighbours are themselves hubs); this ranks the QUERY'S WORDS by how
    common each is in the page-name vocabulary, which does have a gradient
    -- `jackson` (10 page names) against `states` (306) for the query
    `Robert Jackson quasi-states`, measured on the real vault. Ties (two
    words appearing in equally many page names) break by word ascending, so
    the whole order is total."""
    frequency: dict[str, int] = {}
    contains_by_word: dict[str, list[str]] = {}
    for word in _content_words(query):
        if word in contains_by_word:
            continue
        matches = _contains_matches(fold_surface_form(word), vault_dir)
        contains_by_word[word] = matches
        frequency[word] = len(matches)

    doors: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for word in sorted(frequency, key=lambda w: (frequency[w], w.casefold())):
        candidates = _group_one_candidates(word, layer, vault_dir, contains=contains_by_word[word])
        ranked = _rank_group_one(
            candidates,
            layer,
            _doors(vault_dir, [canonical for canonical, _matched, _tier in candidates]),
        )
        if not ranked:
            continue
        canonical, _matched_on, _tier = ranked[0]
        if canonical in seen:
            continue
        seen.add(canonical)
        doors.append((canonical, word, TIER_WORD))
    return doors


def find_names(
    query: str,
    limit: int = DEFAULT_LIMIT,
    *,
    names_dir: Path | None = None,
    vault_dir: Path | None = None,
) -> list[NameHit]:
    """Resolve `query` to a slate of doors into the corpus (§7.5, issue
    #632), assembled from one ordered group and truncated at `limit`:

    **Literal candidates.** The union of four routes, none stopping the
    others: `exact`/`alias`/`folded` (the original three exact lookups over
    `data/names/index.json`/`alias_map.json`) and `contains` (every name
    whose folded form carries the folded query as a whole-word phrase --
    `Mandate` reaches `French Mandate`, never `mandated`). Ranked
    `work`-kind names last, then by `source_count` descending, then
    `member_count` descending, then canonical ascending (`_rank_group_one`)
    -- **never string equality and never a single stop-at-first-tier
    resolution**: an exact hit on `Mandate` (3 members) no longer suppresses
    `French Mandate` (55 members, 8 sources), which `contains` also finds.

    **The compound-query fallback.** When the literal group is empty -- no
    name contains the query phrase at all, which is what a query like
    `"mandate-era institutions Syria"` does -- each content word of the
    query is resolved separately (the same union and ranking) and the best
    door per word stands in, tagged `tier="word"` so a caller can tell the
    difference from a real phrase match. **The words themselves are ordered
    rarest first**, by how many names each appears in
    (`_compound_fallback_candidates`) -- a connective word (`Syrian`, `de`,
    `state`) appears in hundreds of names and its own door would otherwise
    lead ahead of the word that names the query's actual topic.

    **A query that resolves to nothing returns `[]`, and that is a real
    answer** -- never an exception, never silence. A caller should report it
    as an honest resolution failure. What it does NOT mean is that the
    corpus lacks the entity: name resolution is now purely literal (DEC-75,
    issue #853 retired the embedding-based nearest-neighbour fallback along
    with the name pages it resolved to), so a query whose wording does not
    literally appear in any name can reach nothing where it once might have
    reached one through similarity.

    **Determinism:** the slate is a total order (`_rank_group_one`'s own
    tie-break, canonical ascending as the last word), truncated at `limit`;
    the same query over the same pinned vault returns the same slate on
    every call.

    **The `contains` route and every hit's counts come from the note store**
    (DEC-62): one `instr` scan over its folded name column and one GROUP BY
    over `note_names`. A vault with no store answers `[]`.
    """
    layer = _name_layer(names_dir)
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()

    candidates = _group_one_candidates(query, layer, vault)
    literal = _rank_group_one(
        candidates,
        layer,
        _doors(vault, [canonical for canonical, _matched, _tier in candidates]),
    )
    if not literal:
        literal = _compound_fallback_candidates(query, layer, vault)

    window = literal[:limit]
    # Decorated from one door lookup over the whole window (DEC-62's GROUP BY
    # over `note_names`) -- never a fresh page open per hit.
    window_doors = _doors(vault, [canonical for canonical, _matched, _tier in window])
    hits = []
    for canonical, matched_on, tier in window:
        door = window_doors.get(canonical)
        hits.append(
            NameHit(
                canonical=canonical,
                kind=layer.kind_by_canonical.get(canonical)
                or (door.kind if door is not None else None),
                aliases=list(layer.aliases_by_canonical.get(canonical, ())),
                member_count=door.member_count if door is not None else None,
                source_count=door.source_count if door is not None else None,
                matched_on=matched_on,
                tier=tier,
            )
        )
    return hits


# ---------------------------------------------------------------------------
# get_name
# ---------------------------------------------------------------------------


def source_covering_limit(source_ids: Iterable[str | None], limit: int) -> int:
    """`limit`, raised to the number of distinct sources when it is smaller
    (issue #802).

    A rotation that emits one member per source is only a spread across books
    while the window is wide enough to hold the first full rotation. Cut below
    that, the window is one note from each of the alphabetically first `limit`
    books and nothing at all from the rest -- which is the defect the rotation
    was introduced to remove (issue #562), one rung up.

    Measured on the live corpus before this existed: the `Charles Tilly` page
    draws on 20 sources, `tilly-1978` sorts 16th, and the book the papers
    argue against reached zero of 19 analysis records. Every source sorting in
    the alphabetical first ten was cut on 0.0% of pages; late-sorting ones on
    up to 9.8% (`data/logs/2026-08-19-802-tilly-retrieval/`).

    A member with no `source_id` groups under `""` in the rotation, so it
    occupies a slot and is counted here as one source.

    **Bounded by the corpus**, since a page cannot draw on more sources than
    exist: 35 today, against a default limit of 10, and 0.6% of pages are
    affected at all. There is deliberately no maximum -- a cap would be a
    number nobody chose. At 100+ sources this wants re-asking."""
    return max(limit, len({source_id or "" for source_id in source_ids}))


def _round_robin_by_source(members: list[NameMember]) -> list[NameMember]:
    """`members` regrouped by `source_id`, each group keeping its own
    relative order, then interleaved one member per group in rotation -- a
    source's first member, then every source's second, and so on -- until
    every member has been placed (issue #562). A pure re-ordering, never a
    truncation and never a re-sort WITHIN a group: the caller slices the
    result at whatever `limit` it needs.

    Groups are visited in `source_id` ascending order. A member whose
    `source_id` is `None` (its `chunk_id` did not parse,
    `_parse_name_page_body`) is grouped under `""`, which sorts first --
    the same placement `where_names_meet`'s own round-robin already gave an
    unparsed member (issue #517), reused here rather than invented a second
    time so a caller sees one rule, not two. This is a defensible, stated
    placement, not a claim that an unparsed member matters most: it is rare
    (a malformed chunk_id) and must be reachable and non-crashing, never
    silently dropped.

    Shared by `get_name` (one page's own members, already in the page's own
    written order top to bottom, so each group's relative order IS that
    page's order) and `where_names_meet` (an intersection of two pages,
    which carries no written order of its own -- that caller sorts by
    `(source_id, chunk_id)` first so each group lands in `chunk_id` order)."""
    groups: dict[str, list[NameMember]] = {}
    for member in members:
        groups.setdefault(member.source_id or "", []).append(member)
    keys = sorted(groups)
    ordered: list[NameMember] = []
    round_index = 0
    while len(ordered) < len(members):
        for key in keys:
            bucket = groups[key]
            if round_index < len(bucket):
                ordered.append(bucket[round_index])
        round_index += 1
    return ordered


def _render_claim(value: str | None) -> str:
    """One member line's claim as the name page renders it -- a deliberate,
    stated mirror of `axial.materialize._render_claim` (the same trade this
    module's docstring already makes for the page's own body markers, which
    it cannot import without pulling the interrogation stack into this
    LLM-free module). `None` is a missing answer, never a claim; D7's
    explicit abstention is marked, never shown as an answer."""
    if value is None:
        return "(no claim recorded)"
    if is_abstention(value):
        return "(not stated in the passage)"
    return value


def _name_page_from_store(
    connection: Any, canonical: str, limit: int, layer: _NameLayer, vault_dir: Path
) -> NamePage:
    """`get_name` answered entirely as a join over the store (DEC-62,
    DEC-75): the door row for `kind`/`member_count`, `note_names ⋈ notes ⋈
    sources` for the member lines, and the alias map for the aliases the
    name page used to carry in frontmatter.

    `disagreement` is always `None`: Gather, the one writer of that section,
    is retired along with the pages it appended it to (issue #853)."""
    door = note_store.doors(connection, [canonical]).get(canonical)
    if door is None:
        raise NameNotFoundError(canonical, note_store.store_path(vault_dir))

    all_members = [
        NameMember(
            chunk_id=chunk_id,
            source_id=source_id or None,
            author=author,
            year=date,
            claim=_render_claim(claim),
        )
        for chunk_id, source_id, author, date, claim in note_store.name_members(
            connection, canonical
        )
    ]
    # The window covers every source on the page, whatever `limit` asked for
    # (issue #802): a rotation cut mid-first-round is not a spread across
    # books, it is the alphabetically first `limit` books.
    window = source_covering_limit((member.source_id for member in all_members), limit)
    members = (
        all_members if window >= len(all_members) else _round_robin_by_source(all_members)[:window]
    )
    return NamePage(
        canonical=canonical,
        kind=door.kind,
        aliases=list(layer.aliases_by_canonical.get(canonical, ())),
        member_count=door.member_count,
        members=members,
        disagreement=None,
    )


def get_name(
    canonical: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> NamePage:
    """One name's door by its real name (§7.5): its `kind`, `aliases`,
    `member_count`, its member notes with each one's own author, year and
    one-sentence claim. `disagreement` is always `None` (DEC-75, issue
    #853): Gather, the one thing that ever populated it, is retired.

    `canonical` is itself resolved through the same three exact tiers
    (`canonical_for_surface`) before the store lookup: an alias or a folded
    variant (case, whitespace, punctuation) must resolve to the same door as
    its canonical.

    **When `limit` covers every member, they come back in `chunk_id`
    order.** **When `limit` truncates, the window is spread across sources
    instead of a prefix of that order** (issue #562): `_round_robin_by_source`
    takes each source's first member, then every source's second, and so
    on, and `members` is that interleaving sliced at `limit`. The spread is
    a truncation rule, not a re-sort: it changes nothing about
    `all_members[:limit]` when that slice would already be everything
    (`limit >= len(all_members)`).

    `member_count` is deliberately left UNCAPPED: it is the door's own total
    (`axial.query.store.doors`), so a caller sees both the window
    (`len(members)`) and the true size it is a window onto (issue #505).

    Raises `NameNotFoundError`, naming the resolved canonical, when the
    vault carries no store or the store carries no door for it -- never
    returns `None`.

    **`limit` is a FLOOR on the window, not a ceiling** (issue #802). Every
    source on the door contributes at least one note, so a call asking for 3
    over a 20-source door returns 20. `member_count` is unaffected -- it is
    still the true pre-cap count. The window is still bounded: one
    rotation, never more, so a 962-member door never comes back whole."""
    layer = _name_layer(names_dir)
    canonical = canonical_for_surface(canonical, layer) or canonical
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    connection = note_store.connect(vault)
    if connection is None:
        raise NameNotFoundError(canonical, note_store.store_path(vault))
    try:
        return _name_page_from_store(connection, canonical, limit, layer, vault)
    finally:
        connection.close()


# `name_neighbors`, `who_cites`, `who_argues_against` and `where_names_meet`
# were retired with the vault's name pages (DEC-75, issue #853): all four
# walked either a page's own body or the prose notes' answer index solely to
# serve a page-shaped result. `find_names`/`get_name` (above) are what
# survive, answered from the store alone.


# ---------------------------------------------------------------------------
# coverage_count
# ---------------------------------------------------------------------------


def coverage_count(*, vault_dir: Path | None = None) -> dict[str, int]:
    """`{canonical: member_count}` for every name the store carries a door
    for (DEC-75, issue #853: read off `axial.query.store.all_doors`'s own
    GROUP BY over `note_names`, the same query `find_names`/`get_name`
    already answer from, rather than a name page's frontmatter -- the pages
    this used to read are retired). Never a recount: the denominator already
    exists in the store Materialize wrote.

    A name in the store's own `names` table with no member note still has an
    honest `member_count` of 0 -- `all_doors` reports a door for every row of
    that table, never omitting one. A vault with no store returns `{}`,
    since there is nothing here to read at all.

    **This is strictly wider than the per-polity count it replaces** (D2): a
    polity is one `kind` of name, and concepts, scholars, institutions and
    movements now each get a coverage number too. Nothing special-cases a
    polity.

    Returned as a plain dict built in ascending-canonical order -- the same
    explicit-sort determinism contract as every other tool here, applied to a
    mapping instead of a list.

    **Deliberately NOT a model-facing retrieval tool (issue #505's own
    follow-up).** It stays a query-API function, called only from
    `axial.validators.coverage` (§7.7's coverage map, deterministic, zero
    model calls). On a paid corpus run a real provider's model chose
    to call it unprompted and got all 49,674 canonicals back in one result, holding
    the prompt at over a million characters for 14 turns -- the same whole-
    index-dump hazard §7.2 already ruled out for the interrogation pre-pass.
    Do not re-register this in `axial.retrieve.tools.TOOL_REGISTRY`."""
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    connection = note_store.connect(vault)
    if connection is None:
        return {}
    try:
        doors = note_store.all_doors(connection)
    finally:
        connection.close()
    return {canonical: doors[canonical].member_count for canonical in sorted(doors)}
