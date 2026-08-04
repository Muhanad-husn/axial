"""Name-layer query: retrieval over the graph the interrogation grew
(Phase-B stage 3, specs/PHASE-B.md §7.5, §8 P0-2, issue #487).

`axial.query.reader` is the note layer -- a note or a source by an id the
caller already holds. This module is the layer that lets a caller FIND
something: the names the corpus carries, the notes that meet at each one, the
notes at the intersection of two names (`where_names_meet`, issue #517), and
the two traversals the interrogation actually produced (`citations[].cited`
with its stance, and `arguing_against`). It replaces `query_by_tag`,
`query_by_polity` and `follow_backlinks`, which returned 0 on every axis
against the v1 vault because the facets they filtered were deleted with the
tag pass (D1/D5).

Two substrates, two arguments:

- **`names_dir`** (`data/names/`) -- Reconcile's own artifacts: `index.json`
  (the surviving canonical set), `alias_map.json` (`{canonical, kind,
  aliases}` per node), `similarity_manifest.json` and the persisted vector
  table `embeddings.lance`. Resolution reads these.
- **`vault_dir`** (`data/vault/`) -- the note store Materialize wrote
  (`notes.db`, `axial.query.store`, DEC-62), the name pages, and the prose
  notes' own answer blocks. Everything a note says about itself is read from
  here, never recomputed.

**`find_names` and `get_name` are answered from the store** (DEC-62, issue
#648): the door layer is a strict special case of `note_names`, one GROUP BY
and one join, verified byte-identical against the pages on the live vault.
A vault with no store -- one materialized before it existed, or a caller
that writes name pages directly -- still answers from the door index
(`names.jsonl`), unchanged. The alias/fold resolution and the ranking
tie-break are shared by both paths and belong to neither.

**Zero LLM calls** (§7.5), with exactly one relaxation, D10: `find_names`'
embedding group embeds the query string with the local sentence-transformer
the store names in its own `similarity_manifest.json`. That import is lazy,
inside that path, so the literal group (issue #632: exact/alias/folded/
contains, plus its compound-query word fallback) runs with no encoder
loaded at all, and is skipped entirely once it already fills `limit`.
Importing this module costs nothing. No network call, no LLM, no chunk
index.

**Determinism** (§7.5, binding on every tool here): every result is sorted
explicitly and every ranked tool states its whole tie-break, so the order is
total and filesystem enumeration order can never leak into an answer.

Import discipline mirrors `axial.query.reader`'s: nothing here imports
`axial.names`, `axial.merge_names`, `axial.materialize` or `axial.gather`,
each of which pulls the LLM/clustering stack in to define a path constant or
a heading string. The few small values borrowed from them (the name-layer
filenames, Gather's section heading, the encoder factory) are repeated here
as deliberate, stated duplicates -- the same trade `reader._default_
envelopes_dir` already makes. `axial.name_candidates` is the one exception:
it imports only `re`, and its surface fold is reused rather than re-derived
(§7.16, issue #463 -- a second copy of that rule is exactly the drift the
one-shared-copy discipline exists to prevent).
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from axial.name_candidates import _normalize_form as fold_surface_form
from axial.paths import atomic_write_text, default_names_dir, default_vault_dir, name_page_path
from axial.query import store as note_store
from axial.query.reader import (
    MalformedChunkIdError,
    MalformedNoteError,
    QueryError,
    _read_frontmatter,
    is_abstention,
    source_id_from_chunk_id,
    stated_position,
)
from axial.yaml_loader import SAFE_LOADER

# Reconcile's own artifact filenames under `names_dir`
# (`axial.merge_names.DEFAULT_INDEX_PATH`/`DEFAULT_ALIAS_MAP_PATH`,
# `axial.names.DEFAULT_EMBEDDINGS_DIR`/`DEFAULT_MANIFEST_PATH`), repeated
# here rather than imported -- see the module docstring.
INDEX_FILENAME = "index.json"
ALIAS_MAP_FILENAME = "alias_map.json"
SIMILARITY_MANIFEST_FILENAME = "similarity_manifest.json"
EMBEDDINGS_DIRNAME = "embeddings.lance"
DEFAULT_TABLE_NAME = "names"

# Gather's own section heading and its trailing link line
# (`axial.gather.DISAGREEMENT_HEADING` / `render_disagreement_section`).
DISAGREEMENT_HEADING = "## What the authors here disagree about"
_RUNS_BETWEEN_PREFIX = "**Runs between:**"

# Materialize's own name-page body markers
# (`axial.materialize.render_name_page_body`).
_MEMBER_NOTES_MARKER = "**Member notes:**"
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
# One member line: `- [[<chunk_id>]] — <author> (<year>): <claim>`.
_MEMBER_LINE = re.compile(r"^- \[\[(?P<chunk_id>[^\]]+)\]\] — (?P<rest>.*)$")

# Materialize's own door-index filename (`axial.materialize.
# NAME_PAGE_INDEX_FILENAME`, issue #634, specs/PRODUCT.md §7.17): a sibling
# of `vault_dir/names/`, repeated here rather than imported -- see the
# module docstring.
NAME_PAGE_INDEX_FILENAME = "names.jsonl"

# Worker count for `_name_page_index`'s threaded fallback scan, when the
# persisted index above is missing (issue #634). Measured on the live vault
# (49,674 pages, `sim-2026-07-30`): a 48-thread pool reads every page --
# frontmatter and body both, since `source_count` is not in the frontmatter
# -- in ~40s, against 9m22s serial. The cost is per-file-open latency, which
# threading parallelizes; this is the number the measurement used, not a
# knob meant to be retuned.
_INDEX_BUILD_WORKERS = 48

# How many hits a tool returns when the caller states no limit of its own.
DEFAULT_LIMIT = 10

# The cosine-similarity floor tier 4 will not resolve below. A stated tunable
# (§7.5 [TENTATIVE]), inspected on the real store rather than asserted. It
# exists because a nearest-neighbour search always has a nearest neighbour:
# without a floor, an unresolvable query comes back carrying the nearest name
# in the corpus instead of the honest empty result §7.5 and P0-2 both require.
#
# Measured over `data/names/` (2026-07-30,
# `data/logs/2026-07-30-name-query-487/`): an exact surface scores 1.0000 and
# `Charles Tilly`'s own variant surfaces 0.8502-0.8345; `Ungor` reaches
# `Uğur Ümit Üngör` at 0.7752; unrelated text tops out at 0.4518 and is cut.
# That is the whole claim for 0.5 -- it cuts unrelated text and admits every
# transliteration measured.
#
# It deliberately does NOT separate a right name from a plausible wrong one:
# the acronym `AANES` reaches five wrong names topping out at 0.7062, and the
# (0.7062, 0.7752] window that would cut them was REJECTED, not adopted -- a
# 0.07 band read off two cases is a constant fitted to its own evidence, and
# it would also deny an entity the corpus holds (`Autonomous Administration of
# North and East Syria`, an exact hit with 2 members, which the acronym cannot
# reach because an embedding model is not a string matcher). That is a
# name-layer gap filed against Phase A, not a floor to tune.
MIN_EMBEDDING_SIMILARITY = 0.5

# The routes `find_names` unions into its door slate (§7.5, issue #632).
# `exact`/`alias`/`folded` are the three original tiers, each an exact
# lookup over the name layer. `contains` is new: a page whose folded name
# carries the folded query as a whole-word phrase. `word` marks a hit found
# by the compound-query fallback (resolving one content word of a query
# that matched no page at all) rather than the query's own phrase, so a
# caller can tell "your phrase matched no page; this word did" from a real
# phrase resolution. `embedding` is unchanged, the last resort.
TIER_EXACT = "exact"
TIER_ALIAS = "alias"
TIER_FOLDED = "folded"
TIER_CONTAINS = "contains"
TIER_WORD = "word"
TIER_EMBEDDING = "embedding"


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

# `(texts) -> one vector per text`, the same injection seam
# `axial.names.run_names` uses.
Encoder = Callable[[list[str]], list[list[float]]]


class NameNotFoundError(QueryError):
    """No name page exists for a `get_name` canonical -- neither at the
    filename the writer's own naming rule produces nor under any page's own
    `name` frontmatter. Distinct from `find_names` returning `[]`, which is a
    real answer about the corpus, not a lookup failure."""

    def __init__(self, canonical: str, path: Path):
        self.canonical = canonical
        self.path = path
        super().__init__(f"no name page found for {canonical!r} (expected at {path})")


@dataclass(frozen=True)
class NameHit:
    """One `find_names` result: one door in the slate (§7.5, issue #632).
    `matched_on` is the surface form (or, for a `word`-tier hit, the query
    word) that actually matched, and `tier` is which route produced it
    (`exact`/`alias`/`folded`/`contains`/`word`/`embedding`), so a caller can
    see how confident the resolution is. `member_count`/`source_count` are
    the name page's own -- the page's total member notes and the number of
    distinct sources they span -- or `None` when this vault holds no page
    for the name (an index/vault mismatch, reported rather than filled in
    with a 0 that would read like real, thin coverage) or, for
    `source_count` specifically, when only a head read was ever done for it
    (never true from `find_names`, whose slate always decorates from the
    persisted door index; see `_resolve_name_page`'s own docstring for the
    other caller that still leaves it `None`)."""

    canonical: str
    kind: str | None
    aliases: list[str]
    member_count: int | None
    matched_on: str
    tier: str
    source_count: int | None = None


@dataclass(frozen=True)
class NameMember:
    """One member line of a name page, read back as the page wrote it
    (`axial.materialize.render_name_page_body`). `author`/`year` are `None`
    when the line's rendering cannot be split into the two -- stated rather
    than guessed at, since the real corpus's own author rendering is not
    uniform."""

    chunk_id: str
    source_id: str | None
    author: str | None
    year: str | None
    claim: str


@dataclass(frozen=True)
class Disagreement:
    """A Gather finding on a name page (§7.18) and the names it runs between.
    **A retrieval hint, never a citation** (D4): a caller may read one to
    decide where to look, then follows the page's own member `chunk_id`s to
    the real notes and cites only those."""

    text: str
    names: list[str]


@dataclass(frozen=True)
class NamePage:
    """One parsed name page (§7.17). `disagreement` is `None` when Gather
    wrote no section for this name -- a null finding writes no section at
    all, and the two states are distinguishable."""

    canonical: str
    kind: str | None
    aliases: list[str]
    member_count: int
    members: list[NameMember]
    disagreement: Disagreement | None


@dataclass(frozen=True)
class NameNeighbor:
    """One name that co-occurs with another in some note's own `names`
    answers, and how many notes the two share."""

    canonical: str
    kind: str | None
    shared_note_count: int


@dataclass(frozen=True)
class CitationEdge:
    """One author-stated citation edge (§7.15's `citations[]`): the note that
    cites, the surface form it cited, the author's own stance
    (`support`/`foil`/`authority`) and the `about` clause."""

    chunk_id: str
    source_id: str | None
    cited: str
    stance: str | None
    about: str | None


@dataclass(frozen=True)
class OppositionEdge:
    """One author-stated opposition edge (§7.15's `arguing_against`), with
    that note's own stated position and one-sentence `claim` so the
    opposition is legible without a second fetch.

    `position` is the note's own `position` answer where the key is present
    and its `position_of` answer otherwise (§7.5, issue #496's mixed frame --
    see `_read_note_answers`, which is the one place that rule is applied
    here)."""

    chunk_id: str
    source_id: str | None
    arguing_against: str
    position: str | None
    claim: str | None


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
    coverage map is computable from the claim graph. It deliberately does NOT
    reach `find_names`' fourth, embedding tier: §7.4 drops a surface the index
    does not carry rather than inventing one, and a nearest-neighbour match
    here would fabricate coverage of a name the passage never named."""
    return canonical_for_surface(surface, _name_layer(names_dir))


def _surface_matches_canonical(surface: str, canonical: str, layer: _NameLayer) -> bool:
    """Whether `surface` is one of the surface forms the alias map folds into
    `canonical` (§7.5: "never string equality against the canonical alone").
    True on the canonical itself, on any of its aliases, and on anything that
    folds to the same key as either -- so a note citing "C. Tilly 1975" or
    "charles  tilly" is found for "Charles Tilly"."""
    if surface == canonical:
        return True
    if canonical in layer.canonicals_by_alias.get(surface, ()):
        return True
    folds = layer.folds_by_canonical.get(canonical)
    return bool(folds) and fold_surface_form(surface) in folds


# ---------------------------------------------------------------------------
# The vault's name pages (`vault_dir/names/`)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NamePageEntry:
    path: Path
    kind: str | None
    member_count: int
    # The number of distinct `source_id` values the page's members span
    # (issue #634, issue #632's own dependency). `None` on an entry built
    # from a HEAD-only read (`_read_name_page_head`, `_resolve_name_page`'s
    # filename fast path): `source_count` is not in the frontmatter, so
    # answering it costs a body read that fast path is deliberately built to
    # avoid paying. Real on every entry the persisted index or the threaded
    # fallback scan produces. Nothing reads this field yet -- #632 will --
    # but the index the writer persists carries it regardless, because
    # deriving it is the one thing a body scan (not a head scan) buys.
    source_count: int | None = None


_NAME_PAGE_INDEX_CACHE: dict[Path, dict[str, _NamePageEntry]] = {}
_NAME_PAGE_INDEX_LOCK = threading.Lock()


def _read_name_page_head(path: Path) -> tuple[str, str | None, int] | None:
    """`(name, kind, member_count)` off `path`'s frontmatter block alone,
    without reading its body. `None`, never an exception, on any malformed
    page: an index build over the whole vault (~62.8k pages on the real
    corpus) must not abort on one bad page, and `get_name`'s own read still
    raises for the page a caller actually asked for."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            if handle.readline().strip() != "---":
                return None
            block_lines: list[str] = []
            for line in handle:
                if line.strip() == "---":
                    break
                block_lines.append(line)
            else:
                return None
    except OSError:
        return None
    try:
        parsed = yaml.load("".join(block_lines), Loader=SAFE_LOADER)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    name = parsed.get("name")
    if not isinstance(name, str):
        return None
    member_count = parsed.get("member_count")
    return name, parsed.get("kind"), int(member_count) if isinstance(member_count, int) else 0


def _read_name_page_full(path: Path) -> tuple[str, str | None, int, int] | None:
    """`(name, kind, member_count, source_count)` off `path`'s frontmatter
    AND body -- unlike `_read_name_page_head`, which never reads the body at
    all. `source_count` (the number of distinct `source_id` values among the
    page's own member notes) is not carried in frontmatter, so answering it
    is the one thing this function pays for that the head read does not: a
    member whose `chunk_id` does not parse groups under `""`, the same
    placement `_parse_name_page_body` already gives an unparsed member, so
    this and the writer's own `axial.materialize._distinct_source_count`
    never disagree on what counts as one source. `None`, never an exception,
    on any malformed page -- the same never-abort-a-whole-scan rule
    `_read_name_page_head` follows."""
    try:
        frontmatter, body = _read_frontmatter(path)
    except (MalformedNoteError, OSError):
        return None
    name = frontmatter.get("name")
    if not isinstance(name, str):
        return None
    members, _disagreement = _parse_name_page_body(body)
    frontmatter_count = frontmatter.get("member_count")
    member_count = frontmatter_count if isinstance(frontmatter_count, int) else len(members)
    source_count = len({member.source_id or "" for member in members})
    return name, frontmatter.get("kind"), member_count, source_count


def _read_name_page_index_file(vault_dir: Path) -> dict[str, _NamePageEntry] | None:
    """The persisted door index (`<vault_dir>/names.jsonl`, issue #634,
    `axial.materialize.NAME_PAGE_INDEX_FILENAME`), read as `name ->
    _NamePageEntry`, one file read replacing a whole-vault page scan.
    `None` when the file does not exist, so the caller falls back to the
    threaded scan. A malformed row is skipped rather than aborting the whole
    read -- the same never-abort-a-scan rule every other page-index helper
    here follows."""
    path = Path(vault_dir) / NAME_PAGE_INDEX_FILENAME
    if not path.is_file():
        return None
    names_dir = Path(vault_dir) / "names"
    index: dict[str, _NamePageEntry] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        filename = row.get("filename")
        if not isinstance(name, str) or not isinstance(filename, str):
            continue
        member_count = row.get("member_count")
        source_count = row.get("source_count")
        index[name] = _NamePageEntry(
            path=names_dir / filename,
            kind=row.get("kind"),
            member_count=member_count if isinstance(member_count, int) else 0,
            source_count=source_count if isinstance(source_count, int) else None,
        )
    return index


def _write_name_page_index_file(vault_dir: Path, index: dict[str, _NamePageEntry]) -> None:
    """Persist a freshly-built index (the threaded-scan fallback below) so
    the next process reads it in one file read instead of scanning again.
    Written atomically (`atomic_write_text`, issue #637) so a concurrent
    reader of `NAME_PAGE_INDEX_FILENAME` never observes a truncated or
    partial file. **Degrades silently on a read-only vault directory** -- a
    caller that reached this point already has the in-memory `index` to
    return, and a failed write here must not turn a successful build into a
    raised error."""
    path = Path(vault_dir) / NAME_PAGE_INDEX_FILENAME
    lines = (
        json.dumps(
            {
                "name": name,
                "filename": entry.path.name,
                "kind": entry.kind,
                "member_count": entry.member_count,
                "source_count": entry.source_count,
            },
            ensure_ascii=False,
        )
        for name, entry in sorted(index.items())
    )
    try:
        atomic_write_text(path, "".join(line + "\n" for line in lines))
    except OSError:
        pass


def _name_page_index(vault_dir: Path) -> dict[str, _NamePageEntry]:
    """`name -> (path, kind, member_count, source_count)` over every page
    under `<vault_dir>/names/`, keyed on each page's OWN `name` frontmatter
    -- the sole authoritative id (§7.5). Never keyed on filenames: a
    canonical carries no unique suffix of its own, so two canonicals can
    sanitize to one filename and the writer hash-suffixes whichever it wrote
    second (`axial.paths.name_page_filename`'s `used` set), a write-order
    fact no reader can reproduce.

    **Reads the persisted door index when Materialize wrote one**
    (`<vault_dir>/names.jsonl`, issue #634) -- one file read over the whole
    vault, ~3 MB on the real corpus, rather than opening 49,674 files.
    **Absent that file, falls back to a threaded scan of `names/` itself**
    (`_INDEX_BUILD_WORKERS`-wide, ~40s measured against 9m22s serial: the
    cost is per-file-open latency, which parallelizes), reading each page's
    body as well as its frontmatter -- `source_count` is not in the
    frontmatter -- and then writes the index back so the next call in a
    fresh process reads the file instead of scanning again. An
    already-materialized vault with no index file therefore self-heals on
    its first read; a vault directory that will not accept the write
    degrades to the in-memory result rather than raising. Both writers of
    this file (this self-heal and Materialize's) write it atomically (issue
    #637), so a concurrent read of `<vault_dir>/names.jsonl` never observes
    a truncated or partial file.

    Built lazily, at most once per resolved `vault_dir` for the process
    lifetime -- never on import. `get_name`'s fast path (the writer's own
    naming function, plus a check that the page found really carries the
    requested name) never touches this index; a miss and `coverage_count`
    are what build it. A vault with no `names/` directory yields `{}`: a
    vault that was never materialized holds no name pages, and every tool
    here then honestly reports no names rather than raising."""
    key = Path(vault_dir).resolve()
    cached = _NAME_PAGE_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    with _NAME_PAGE_INDEX_LOCK:
        cached = _NAME_PAGE_INDEX_CACHE.get(key)
        if cached is not None:
            return cached
        index = _read_name_page_index_file(key)
        if index is None:
            names_dir = key / "names"
            index = {}
            if names_dir.is_dir():
                paths = sorted(names_dir.glob("*.md"))
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=_INDEX_BUILD_WORKERS
                ) as pool:
                    for path, head in zip(paths, pool.map(_read_name_page_full, paths)):
                        if head is None:
                            continue
                        name, kind, member_count, source_count = head
                        index[name] = _NamePageEntry(
                            path=path,
                            kind=kind,
                            member_count=member_count,
                            source_count=source_count,
                        )
            _write_name_page_index_file(key, index)
        _NAME_PAGE_INDEX_CACHE[key] = index
        return index


def _resolve_name_page(canonical: str, vault_dir: Path) -> _NamePageEntry | None:
    """`canonical`'s page, as `(path, kind, member_count)`: the filename the
    writer's own naming function produces when that file exists AND carries
    this canonical in its `name` frontmatter, else the lazily-built name index
    (see `_name_page_index`). The frontmatter check is not belt-and-braces: on
    a sanitization collision the un-suffixed filename belongs to a DIFFERENT
    canonical, so trusting file existence alone returns the wrong page's
    content under the requested name.

    Returns the head alongside the path so a caller wanting only `kind`/
    `member_count` (`find_names`, per hit) pays one file read rather than the
    whole-vault index build. This fast path is deliberately unchanged by
    issue #634: it stays a frontmatter-only read, so the entry it returns
    carries `source_count=None` (unknown, not read) even when the index built
    from `_name_page_index` would carry a real one for the same name."""
    direct = name_page_path(vault_dir, canonical)
    if direct.is_file():
        head = _read_name_page_head(direct)
        if head is not None and head[0] == canonical:
            return _NamePageEntry(path=direct, kind=head[1], member_count=head[2])
    return _name_page_index(vault_dir).get(canonical)


def _split_member_line(rest: str) -> tuple[str | None, str | None, str]:
    """`<author> (<year>): <claim>` -- the rendering
    `axial.materialize.render_name_page_body` writes -- split back into its
    three parts. Splits at the FIRST `): `, so a claim containing one of its
    own is safe, then takes the last ` (` before it as the author/year seam.
    A line that does not carry the shape at all yields `(None, None, rest)`:
    the claim is what the page says, and author/year are honestly unknown
    rather than guessed at (the real corpus renders authors as both
    "Michael Mann" and "Ayubi, Nazih N.;")."""
    head, separator, claim = rest.partition("): ")
    if not separator:
        return None, None, rest
    author, seam, year = head.rpartition(" (")
    if not seam:
        return None, None, rest
    return author, year, claim


def _parse_name_page_body(body: str) -> tuple[list[NameMember], Disagreement | None]:
    """A name page's members, in the page's own written order, and its Gather
    section when it has one. Members are read only from the lines after
    `**Member notes:**`, so the `**Artifacts:**` links above it (253 real
    pages carry them) are never mistaken for member notes."""
    head, separator, tail = body.partition(DISAGREEMENT_HEADING)

    members: list[NameMember] = []
    _, marker, member_block = head.partition(_MEMBER_NOTES_MARKER)
    if marker:
        for line in member_block.splitlines():
            match = _MEMBER_LINE.match(line.strip())
            if match is None:
                if line.strip().startswith("- [["):
                    continue  # a link line in some other shape: not a member
                if members:
                    break  # the member list ended
                continue
            chunk_id = match.group("chunk_id")
            author, year, claim = _split_member_line(match.group("rest"))
            try:
                source_id = source_id_from_chunk_id(chunk_id)
            except MalformedChunkIdError:
                source_id = None
            members.append(
                NameMember(
                    chunk_id=chunk_id,
                    source_id=source_id,
                    author=author,
                    year=year,
                    claim=claim,
                )
            )

    disagreement = None
    if separator:
        text_lines: list[str] = []
        runs_between: list[str] = []
        for line in tail.splitlines():
            if line.startswith(_RUNS_BETWEEN_PREFIX):
                runs_between = _WIKILINK.findall(line)
                break
            text_lines.append(line)
        disagreement = Disagreement(text="\n".join(text_lines).strip(), names=runs_between)

    return members, disagreement


# ---------------------------------------------------------------------------
# The prose notes' answer blocks (`vault_dir/prose/`)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NoteAnswers:
    """The answer fields the three traversal tools read off one prose note
    (§7.15, Appendix H) -- never `chunk_text`, `section` or `source_meta`,
    which none of them consult and which would make the process-lifetime
    index below hold a full copy of every note.

    `position` is already resolved across issue #496's mixed frame (see
    `_read_note_answers`): the index stores the answer a reader should use,
    not both keys, since no tool here needs to tell the two frames apart."""

    chunk_id: str
    source_id: str | None
    claim: str | None
    position: str | None
    arguing_against: list[str] = field(default_factory=list)
    names: list[tuple[str, str | None]] = field(default_factory=list)
    citations: list[tuple[str, str | None, str | None]] = field(default_factory=list)


_ANSWERS_INDEX_CACHE: dict[Path, list[_NoteAnswers]] = {}
_ANSWERS_INDEX_LOCK = threading.Lock()


def as_string_list(value: Any) -> list[str]:
    """A free-text answer that may be a list of strings, one string, or
    absent, read as a list of strings. `arguing_against` is a list on the
    real corpus, but nothing enforces that on a free-text answer, so a bare
    string is accepted as a one-item list rather than silently dropped."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _read_note_answers(path: Path) -> _NoteAnswers | None:
    """One prose note's answer block, or `None` on any malformed note (same
    never-abort-a-whole-corpus-scan rule as `_read_name_page_head`).

    **The stated position is read across a mixed frame** (§7.5/§7.15, issue
    #496): a note interrogated before frame 0.2 carries `position_of` and no
    `position` key, a note interrogated after carries both, and no re-run is
    planned. So `position` is read when the KEY IS PRESENT and `position_of`
    is the fallback otherwise -- key presence, never truthiness (a note that
    genuinely answered `position: null` has been asked the frame-0.2 question
    and its answer is that null, not the older question's answer), and never
    `frame_version` (a note's own keys say what it was asked; a version
    string is a second source of truth that can disagree). This is the one
    place the rule is applied in this module."""
    try:
        frontmatter, _body = _read_frontmatter(path)
    except (MalformedNoteError, OSError):
        return None
    chunk_id = frontmatter.get("chunk_id")
    if not isinstance(chunk_id, str):
        return None
    answers = frontmatter.get("answers")
    if not isinstance(answers, dict):
        answers = {}
    try:
        source_id = source_id_from_chunk_id(chunk_id)
    except MalformedChunkIdError:
        source_id = None

    names: list[tuple[str, str | None]] = []
    for entry in answers.get("names") or []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append((entry["name"], entry.get("kind")))
        elif isinstance(entry, str):
            names.append((entry, None))

    citations: list[tuple[str, str | None, str | None]] = []
    for entry in answers.get("citations") or []:
        if isinstance(entry, dict) and isinstance(entry.get("cited"), str):
            citations.append((entry["cited"], entry.get("stance"), entry.get("about")))

    claim = answers.get("claim")
    position = stated_position(answers)
    return _NoteAnswers(
        chunk_id=chunk_id,
        source_id=source_id,
        claim=claim if isinstance(claim, str) else None,
        position=position if isinstance(position, str) else None,
        arguing_against=as_string_list(answers.get("arguing_against")),
        names=names,
        citations=citations,
    )


def _answers_index(vault_dir: Path) -> list[_NoteAnswers]:
    """Every prose note's answer block under `<vault_dir>/prose/`, built
    lazily at most once per resolved `vault_dir` for the process lifetime --
    never on import, and never per call: `name_neighbors`, `who_cites` and
    `who_argues_against` are called repeatedly inside one retrieval loop over
    the same unchanging vault (~6,150 notes on the real corpus), and a
    rebuild per call would be pathological. A vault with no `prose/`
    directory yields `[]`."""
    key = Path(vault_dir).resolve()
    cached = _ANSWERS_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    with _ANSWERS_INDEX_LOCK:
        cached = _ANSWERS_INDEX_CACHE.get(key)
        if cached is not None:
            return cached
        prose_dir = key / "prose"
        notes: list[_NoteAnswers] = []
        if prose_dir.is_dir():
            for path in sorted(prose_dir.glob("*.md")):
                note = _read_note_answers(path)
                if note is not None:
                    notes.append(note)
        _ANSWERS_INDEX_CACHE[key] = notes
        return notes


# ---------------------------------------------------------------------------
# find_names -- the entry point (§7.5, four tiers)
# ---------------------------------------------------------------------------


def resolve_encoder_model_name(names_dir: Path | None = None) -> str | None:
    """The sentence-transformer the vector store itself names
    (`similarity_manifest.json`'s `model_name`), or `None` when there is no
    manifest. Never a string hardcoded here: the vectors tier 4 searches were
    written by one specific model, and embedding a query with a different one
    compares points in two unrelated spaces."""
    directory = Path(names_dir) if names_dir is not None else default_names_dir()
    manifest = _read_json(directory / SIMILARITY_MANIFEST_FILENAME) or {}
    model_name = manifest.get("model_name")
    return model_name if isinstance(model_name, str) else None


# Process-lifetime cache of the loaded sentence-transformer, keyed by model
# name: a retrieval loop reaching tier 4 repeatedly would otherwise construct
# a fresh one per call, and each construction round-trips to huggingface.co to
# check for a newer revision of weights already on disk (2.9s online against
# 0.28s offline, measured 2026-07-30, issue #524). Keyed by name rather than
# held as a single slot because the vector store names which model wrote it,
# and two stores can name two.
_ENCODER_CACHE: dict[str, Encoder] = {}
_ENCODER_LOCK = threading.Lock()


def _default_encoder(model_name: str) -> Encoder:
    """The real local sentence-transformer, imported HERE and never at module
    level (D10: tiers 1-3 must run with no encoder loaded at all). A
    deliberate small duplicate of `axial.names._default_encoder`, which
    cannot be imported without pulling the whole interrogation/LLM stack into
    this LLM-free module.

    Built at most once per model name for the process lifetime, and
    `local_files_only` so construction never reaches the network: §7.5 is a
    zero-LLM-call, zero-network read path, and the weights are already on disk
    by the time a query runs -- building the vector table is what downloads
    them."""
    cached = _ENCODER_CACHE.get(model_name)
    if cached is not None:
        return cached
    with _ENCODER_LOCK:
        cached = _ENCODER_CACHE.get(model_name)
        if cached is not None:
            return cached

        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name, local_files_only=True)

        def encode(texts: list[str]) -> list[list[float]]:
            return model.encode(texts, convert_to_numpy=True).tolist()

        _ENCODER_CACHE[model_name] = encode
        return encode


# Process-lifetime cache of the persisted vector table, keyed by resolved
# `names_dir`: `(surface forms, L2-normalized float32 matrix)`. Read at most
# once per directory, on the first tier-4 query and never before -- a
# retrieval loop calling `find_names` repeatedly would otherwise re-read the
# whole table per call. 78,198 x 384 float32 is ~115 MB on the real store,
# paid only by a process that actually reaches tier 4.
_VECTOR_STORE_CACHE: dict[Path, tuple[list[str], Any] | None] = {}
_VECTOR_STORE_LOCK = threading.Lock()


def _read_vector_store(names_dir: Path) -> tuple[list[str], Any] | None:
    """The persisted name table as `(surface forms, normalized matrix)`
    (`axial.names.run_names`'s own row schema: `surface_form`, `vector`).
    `None` when the store or its table is absent -- tier 4 then contributes
    no candidates and `find_names` still answers from tiers 1-3.

    Rows are L2-normalized once, here, so scoring a query is one matrix
    product rather than a per-row cosine in Python (30M multiply-adds over the
    real store, which interpreted Python does in seconds and numpy in
    milliseconds). Both `lancedb` and `numpy` are imported lazily, inside this
    function: nothing on tiers 1-3 loads either."""
    embeddings_dir = names_dir / EMBEDDINGS_DIRNAME
    if not embeddings_dir.exists():
        return None
    manifest = _read_json(names_dir / SIMILARITY_MANIFEST_FILENAME) or {}
    table_name = manifest.get("table_name") or DEFAULT_TABLE_NAME

    import lancedb
    import numpy

    db = lancedb.connect(embeddings_dir)
    if table_name not in db.list_tables().tables:
        return None
    rows = [
        (row["surface_form"], row["vector"])
        for row in db.open_table(table_name).to_arrow().to_pylist()
        if isinstance(row.get("surface_form"), str)
    ]
    if not rows:
        return None
    matrix = numpy.asarray([vector for _surface, vector in rows], dtype=numpy.float32)
    norms = numpy.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return [surface for surface, _vector in rows], matrix / norms


def _vector_store(names_dir: Path) -> tuple[list[str], Any] | None:
    key = Path(names_dir).resolve()
    if key in _VECTOR_STORE_CACHE:
        return _VECTOR_STORE_CACHE[key]
    with _VECTOR_STORE_LOCK:
        if key not in _VECTOR_STORE_CACHE:
            _VECTOR_STORE_CACHE[key] = _read_vector_store(Path(names_dir))
        return _VECTOR_STORE_CACHE[key]


def _embedding_tier(
    query: str, layer: _NameLayer, names_dir: Path, encoder: Encoder | None
) -> list[tuple[str, str]]:
    """Tier 4: `(canonical, matched_on)` for every name whose nearest vector
    clears `MIN_EMBEDDING_SIMILARITY`, ordered by score descending and ties
    broken by canonical ascending. Each row's surface form is mapped back
    through the alias map to its canonical and de-duplicated, keeping the
    best-scoring surface as `matched_on` (ties by surface ascending).

    An exact scan over every persisted vector, not an approximate one: the
    store carries no ANN index (`axial.names.run_names` creates the table and
    stops), so this is the same brute-force comparison a vector search would
    do, and it returns the same ranking on every call."""
    store = _vector_store(names_dir)
    if store is None:
        return []
    surfaces, matrix = store
    if encoder is None:
        model_name = resolve_encoder_model_name(names_dir)
        if model_name is None:
            return []
        encoder = _default_encoder(model_name)

    import numpy

    query_vector = numpy.asarray(encoder([query])[0], dtype=numpy.float32)
    query_norm = float(numpy.linalg.norm(query_vector))
    if query_norm == 0:
        return []
    scores = matrix @ (query_vector / query_norm)

    best: dict[str, tuple[float, str]] = {}
    for index in numpy.nonzero(scores >= MIN_EMBEDDING_SIMILARITY)[0]:
        surface_form = surfaces[int(index)]
        score = float(scores[index])
        canonical = canonical_for_surface(surface_form, layer) or surface_form
        current = best.get(canonical)
        # A higher score wins; an equal score keeps the LOWER surface form,
        # so `matched_on` is total either way.
        if (
            current is None
            or score > current[0]
            or (score == current[0] and surface_form < current[1])
        ):
            best[canonical] = (score, surface_form)
    return [
        (canonical, best[canonical][1])
        for canonical in sorted(best, key=lambda name: (-best[name][0], name))
    ]


# Folded page names, cached alongside the door index they are derived from
# (issue #632): `[(canonical, " <folded name> ")]`, padded with a leading and
# trailing space so a substring check against a padded query
# (` <folded query> `) is a correct whole-word match without a regex per
# candidate -- folding punctuation to nothing and hyphens to a space
# (`fold_surface_form`) already leaves single-space-separated words with no
# leading/trailing space of their own. Built at most once per resolved
# `vault_dir` for the process lifetime, from `_name_page_index`'s own result:
# measured over the real vault (49,674 pages), folding all of them once costs
# 0.16s, against 40ms if it were repeated on every `find_names` call in a
# retrieval loop that calls it many times over one vault.
_FOLDED_PAGE_NAMES_CACHE: dict[Path, list[tuple[str, str]]] = {}
_FOLDED_PAGE_NAMES_LOCK = threading.Lock()


def _folded_page_names(vault_dir: Path) -> list[tuple[str, str]]:
    key = Path(vault_dir).resolve()
    cached = _FOLDED_PAGE_NAMES_CACHE.get(key)
    if cached is not None:
        return cached
    with _FOLDED_PAGE_NAMES_LOCK:
        cached = _FOLDED_PAGE_NAMES_CACHE.get(key)
        if cached is None:
            cached = [(name, f" {fold_surface_form(name)} ") for name in _name_page_index(key)]
            _FOLDED_PAGE_NAMES_CACHE[key] = cached
        return cached


def _contains_matches(folded_query: str, vault_dir: Path) -> list[str]:
    """Every name whose folded form carries `folded_query` as a whole-word
    phrase (issue #632's `contains` route) -- `Mandate` matches `French
    Mandate` and `mandate period`, never `mandated`.

    One `instr` scan over the store's own `names.folded` column when the
    vault has a store (DEC-62), else the same scan over the folded page
    names, for a vault materialized before the store existed."""
    if not folded_query:
        return []
    connection = note_store.connect(vault_dir)
    if connection is not None:
        try:
            return note_store.contains_matches(connection, folded_query)
        finally:
            connection.close()
    needle = f" {folded_query} "
    return [name for name, padded in _folded_page_names(vault_dir) if needle in padded]


def _doors(vault_dir: Path, canonicals: list[str]) -> dict[str, note_store.Door]:
    """`canonical -> Door` (kind, member_count, source_count) for the names
    given -- the store's own GROUP BY over `note_names` (DEC-62), else the
    name-page door index for a vault materialized before the store existed.
    A canonical neither carries is absent from the result, which the caller
    reports as an unknown count rather than a 0."""
    connection = note_store.connect(vault_dir)
    if connection is not None:
        try:
            return note_store.doors(connection, canonicals)
        finally:
            connection.close()
    index = _name_page_index(vault_dir)
    found = {}
    for canonical in canonicals:
        entry = index.get(canonical)
        if entry is not None:
            found[canonical] = note_store.Door(
                canonical, entry.kind, entry.member_count, entry.source_count
            )
    return found


def _content_words(query: str) -> list[str]:
    """`query` split on whitespace and hyphens (`_WORD_SPLIT`, the same
    separators the surface fold treats as word boundaries), stopwords
    dropped, original casing kept -- the compound-query fallback's own
    tokenizer (issue #632). `"mandate-era institutions Syria"` yields
    `["mandate", "era", "institutions", "Syria"]`."""
    tokens = [token for token in _WORD_SPLIT.split(query) if token]
    return [token for token in tokens if token.casefold() not in _STOPWORDS]


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
    encoder: Encoder | None = None,
) -> list[NameHit]:
    """Resolve `query` to a slate of doors into the corpus (§7.5, issue
    #632), assembled in two ordered groups and truncated at `limit`:

    **Group 1 -- literal candidates.** The union of four routes, none
    stopping the others: `exact`/`alias`/`folded` (the original three exact
    lookups over `data/names/index.json`/`alias_map.json`) and `contains`
    (new: every page whose folded name carries the folded query as a
    whole-word phrase -- `Mandate` reaches `French Mandate`, never
    `mandated`). Ranked `work`-kind pages last, then by `source_count`
    descending, then `member_count` descending, then canonical ascending
    (`_rank_group_one`) -- **never string equality and never a single
    stop-at-first-tier resolution**: an exact hit on `Mandate` (3 members) no
    longer suppresses `French Mandate` (55 members, 8 sources), which
    `contains` also finds.

    **The compound-query fallback.** When group 1 is empty -- no page name
    contains the query phrase at all, which is what a query like
    `"mandate-era institutions Syria"` does -- each content word of the
    query is resolved separately (the same group-1 union and ranking) and
    the best door per word stands in for group 1, tagged `tier="word"` so a
    caller can tell the difference from a real phrase match. **The words
    themselves are ordered rarest first**, by how many page names each
    appears in (`_compound_fallback_candidates`) -- a connective word
    (`Syrian`, `de`, `state`) appears in hundreds of page names and its own
    door would otherwise lead ahead of the word that names the query's
    actual topic.

    **Group 2 -- embedding candidates**, not already in group 1, in the
    existing similarity order -- appended only when group 1 (or its
    compound-query stand-in) has not already filled `limit`.
    **Never re-ranked by size**: ranking an embedding hit by `member_count`/
    `source_count` drifts to the corpus's biggest pages regardless of
    relevance (measured: `Syria` then outranks the query `Ugor`'s own best
    match), because a nearest-neighbour search's candidate set carries no
    guarantee any member actually names the query -- only `contains`'
    candidates, which literally carry the query's own words, can be ranked
    that way. Same nearest-neighbour lookup as before: the vectors
    Reconcile persisted (`data/names/embeddings.lance`), each mapped back
    through the alias map to its canonical and de-duplicated.

    **A query that resolves to nothing returns `[]`, and that is a real
    answer** -- never an exception, never silence, and never the nearest name
    to hand (which is what `MIN_EMBEDDING_SIMILARITY` exists to prevent). A
    caller should report it as an honest resolution failure. What it does NOT
    mean is that the corpus lacks the entity: an acronym whose expansion the
    index carries can still reach nothing (see `MIN_EMBEDDING_SIMILARITY`),
    which is a name-layer gap rather than an answer about the corpus.

    **Determinism:** group 1 (or its compound-query stand-in) is a total
    order (`_rank_group_one`'s own tie-break, canonical ascending as the
    last word); group 2 is ordered by score descending, ties by canonical
    ascending. The slate is that order, truncated at `limit`; the same query
    over the same pinned vault returns the same slate on every call.

    `encoder` replaces the default sentence-transformer (the embedding group
    only) -- the seam a test uses to exercise the ranked group without
    loading a model. Group 1 and the compound-query fallback never call it,
    and the embedding group is skipped entirely (no vector store read, no
    encoder built) once group 1 already fills `limit`.

    **The `contains` route and every hit's counts come from the note store**
    (DEC-62): one `instr` scan over its folded name column and one GROUP BY
    over `note_names`, replacing the whole-vault door-index read a fresh
    process used to pay for (1.97s and 6.6 MB on the live vault, against
    23-45ms per query now). A store-less vault answers from that index
    instead, with the same result.
    """
    layer = _name_layer(names_dir)
    names_directory = Path(names_dir) if names_dir is not None else default_names_dir()
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()

    candidates = _group_one_candidates(query, layer, vault)
    literal = _rank_group_one(
        candidates,
        layer,
        _doors(vault, [canonical for canonical, _matched, _tier in candidates]),
    )
    if not literal:
        literal = _compound_fallback_candidates(query, layer, vault)

    slate = list(literal)
    if len(slate) < limit:
        already = {canonical for canonical, _matched_on, _tier in slate}
        for canonical, matched_on in _embedding_tier(query, layer, names_directory, encoder):
            if canonical not in already:
                slate.append((canonical, matched_on, TIER_EMBEDDING))
                already.add(canonical)

    window = slate[:limit]
    # Decorated from one door lookup over the whole window (DEC-62's GROUP BY
    # over `note_names`, or the door index for a store-less vault) -- never a
    # fresh page open per hit.
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
    """`get_name` answered as a join over the store (DEC-62): the door row
    for `kind`/`member_count`, `note_names ⋈ notes ⋈ sources` for the member
    lines, and the alias map for the aliases the page's own frontmatter
    carries.

    **The Gather section is still read from the page**, and is the one thing
    here that is: Gather appends its finding to the rendered name page after
    Materialize has already written the store, so the page is where that
    finding lives. Resolving the page also keeps `NameNotFoundError` meaning
    exactly what it meant before -- no page, no answer."""
    door = note_store.doors(connection, [canonical]).get(canonical)
    entry = _resolve_name_page(canonical, vault_dir)
    if door is None or entry is None:
        raise NameNotFoundError(canonical, name_page_path(vault_dir, canonical))
    _frontmatter, body = _read_frontmatter(entry.path)
    _page_members, disagreement = _parse_name_page_body(body)

    all_members = []
    for chunk_id, source_id, author, date, claim in note_store.name_members(connection, canonical):
        # Rendered and split back exactly as the page writes and the reader
        # reads a member line -- including the `rstrip`, which is not
        # cosmetic: the page reader strips the whole line, so a claim the
        # corpus wrote with trailing whitespace comes back without it, and
        # this path has to say the same thing. Round-tripping (rather than
        # returning the store's author/date columns directly) is what keeps
        # both paths agreeing where the corpus's own author rendering does
        # not split cleanly into author and year.
        rest = f"{author} ({date}): {_render_claim(claim)}".rstrip()
        parsed_author, year, text = _split_member_line(rest)
        all_members.append(
            NameMember(
                chunk_id=chunk_id,
                source_id=source_id or None,
                author=parsed_author,
                year=year,
                claim=text,
            )
        )
    members = (
        all_members if limit >= len(all_members) else _round_robin_by_source(all_members)[:limit]
    )
    return NamePage(
        canonical=canonical,
        kind=door.kind,
        aliases=list(layer.aliases_by_canonical.get(canonical, ())),
        member_count=door.member_count,
        members=members,
        disagreement=disagreement,
    )


def get_name(
    canonical: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> NamePage:
    """One name page by its real name (§7.5): its `kind`, `aliases`,
    `member_count`, its member notes with each one's own author, year and
    one-sentence claim, and any Gather disagreement section.

    `canonical` is itself resolved through the same three exact tiers
    (`canonical_for_surface`) before the page lookup, the same shape
    `name_neighbors` uses on its own argument: an alias or a folded variant
    (case, whitespace, punctuation) must land the same page as its canonical,
    matching the alias-map matching `who_cites` and `who_argues_against`
    already apply on the note side. Never tier 4 -- an embedding match here
    would hand back a DIFFERENT name's page for a query the index does not
    carry, which is worse than the honest `NameNotFoundError` below.

    **When `limit` covers every member, they come back in the page's own
    written order, unchanged** -- the order Materialize wrote and is itself
    deterministic. **When `limit` truncates, the window is spread across
    sources instead of a prefix of that order** (issue #562):
    `_round_robin_by_source` takes each source's first member, then every
    source's second, and so on, and `members` is that interleaving sliced at
    `limit`. The page's own written order groups members by `source_id`
    alphabetically, so the old plain-prefix truncation handed every window
    to whichever source's `source_id` happened to sort first -- measured on
    the real vault, `Charles Tilly`'s own book sat at member 108 of 154 and
    a default `limit` of 10 could never reach it. The spread is a truncation
    rule, not a re-sort: it changes nothing about `all_members[:limit]` when
    that slice would already be everything (`limit >= len(all_members)`),
    matching the rule's own first sentence.

    `member_count` is deliberately left UNCAPPED regardless of either path:
    it is the page's own frontmatter total, so a caller sees both the window
    (`len(members)`) and the true size it is a window onto (issue #505).
    `disagreement` is `None` when the page carries no Gather section, which
    is distinguishable from a section whose text is present.

    Raises `NameNotFoundError`, naming the resolved canonical, when no page
    exists -- never returns `None`. A page whose filename was budgeted down
    or hash-suffixed is still reachable by its real name (§7.5: the `name`
    frontmatter is the sole authoritative id, never the filename).

    **Answered as a join over the note store when the vault has one**
    (`_name_page_from_store`, DEC-62) -- byte-identical to the page read
    below, which still answers for a vault materialized before the store
    existed."""
    layer = _name_layer(names_dir)
    canonical = canonical_for_surface(canonical, layer) or canonical
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    connection = note_store.connect(vault)
    if connection is not None:
        try:
            return _name_page_from_store(connection, canonical, limit, layer, vault)
        finally:
            connection.close()
    entry = _resolve_name_page(canonical, vault)
    if entry is None:
        raise NameNotFoundError(canonical, name_page_path(vault, canonical))

    frontmatter, body = _read_frontmatter(entry.path)
    all_members, disagreement = _parse_name_page_body(body)
    member_count = frontmatter.get("member_count")
    aliases = [alias for alias in (frontmatter.get("aliases") or []) if isinstance(alias, str)]
    members = (
        all_members if limit >= len(all_members) else _round_robin_by_source(all_members)[:limit]
    )
    return NamePage(
        canonical=frontmatter.get("name") or canonical,
        kind=frontmatter.get("kind"),
        aliases=aliases,
        member_count=member_count if isinstance(member_count, int) else len(all_members),
        members=members,
        disagreement=disagreement,
    )


# ---------------------------------------------------------------------------
# name_neighbors / who_cites / who_argues_against
# ---------------------------------------------------------------------------


def _idf(df: int, n: int) -> float:
    """`ln(N / df)`, the inverse-document-frequency weight `name_neighbors`
    ranks by (issue #521): `df` is a neighbour's own `member_count` (how many
    notes in the WHOLE corpus carry that name at all), `n` is the number of
    prose notes carrying a `names` answer. A neighbour that turns up
    everywhere -- a hub like `Syria` or `the state` -- gets a weight near
    zero; a neighbour specific to this anchor gets a weight close to `ln(n)`.

    Two degenerate cases are guarded rather than left to raise or return NaN.
    `df == 0`: a neighbour `canonical_for_surface` folds a note's own surface
    onto can carry no materialized page of its own and still be a real
    neighbour (§7.16, nothing is dropped) -- floored to `df=1`, the one
    occurrence the note itself attests, rather than dividing by zero.
    `df >= n`: a name at least as common as the note count is not rare, and
    `math.log` returns a finite, non-positive weight for it, not an error --
    it just ranks low, which is the honest answer for a name that common."""
    if n <= 0:
        return 0.0
    return math.log(n / max(df, 1))


def name_neighbors(
    canonical: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> list[NameNeighbor]:
    """The names that co-occur with `canonical` in some note's own `names`
    answers, ranked by shared note count weighted by each neighbour's
    inverse document frequency (§7.5, issue #521). This is the cheapest real
    edge the interrogation produced: two names on one note are two things one
    author discussed together -- and it is the traversal `follow_backlinks`
    used to be, over a facet that exists (D5).

    A note counts once per neighbour however many times it names it, and a
    name is never its own neighbour. Every surface form on a note is mapped
    through the alias map to its canonical first, so two spellings of one
    name are one neighbour; a surface the layer does not carry stands as its
    own canonical (§7.16: nothing is dropped).

    `canonical` itself is resolved through the same three exact tiers
    (`canonical_for_surface`) before it is compared -- an alias or a folded
    variant (case, whitespace, punctuation) must land the same result as its
    canonical, matching the alias-map matching `who_cites` and
    `who_argues_against` already apply on their side. Never tier 4: an
    embedding match here would invent a neighbour list for a name the caller
    never actually asked about.

    **Ranked by count * idf, not raw count (issue #521).** Raw
    `shared_note_count` puts the corpus's hub names -- the ones that
    co-occur with almost anything -- at the top of every anchor's neighbour
    list, answering "what is this corpus about" instead of "what does this
    author discuss alongside `canonical`". Each neighbour's count is
    multiplied by `_idf(df, n)`, `df` the neighbour's own `member_count`
    (read off the already-loaded name-page index) and `n` the number of
    prose notes carrying a `names` answer at all. `shared_note_count` on the
    returned `NameNeighbor` is untouched -- the true count, never the
    weighted one; only the order changes.

    **Determinism:** `shared_note_count * idf` descending, ties by canonical
    ascending, truncated at `limit`."""
    layer = _name_layer(names_dir)
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    canonical = canonical_for_surface(canonical, layer) or canonical

    counts: dict[str, int] = {}
    kinds: dict[str, str | None] = {}
    total_notes = 0
    for note in _answers_index(vault):
        if note.names:
            total_notes += 1
        resolved = [
            (canonical_for_surface(surface, layer) or surface, kind) for surface, kind in note.names
        ]
        if not any(name == canonical for name, _kind in resolved):
            continue
        for name, kind in dict(resolved).items():
            if name == canonical:
                continue
            counts[name] = counts.get(name, 0) + 1
            kinds.setdefault(name, layer.kind_by_canonical.get(name) or kind)

    page_index = _name_page_index(vault)

    def weight(name: str) -> float:
        entry = page_index.get(name)
        df = entry.member_count if entry is not None else 0
        return counts[name] * _idf(df, total_notes)

    ordered = sorted(counts, key=lambda name: (-weight(name), name))[:limit]
    return [
        NameNeighbor(canonical=name, kind=kinds.get(name), shared_note_count=counts[name])
        for name in ordered
    ]


def who_cites(
    canonical: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> tuple[list[CitationEdge], int]:
    """Every prose note whose `citations[].cited` resolves to `canonical`
    (§7.5), carrying the author's own stance (`support`/`foil`/`authority`)
    and the `about` clause. These are **author-stated cross-book edges** and
    the closest thing the corpus has to a citation graph.

    Matching is against every surface form the alias map folds into
    `canonical`, never string equality against the canonical alone
    (`_surface_matches_canonical`).

    **Determinism:** sorted by `chunk_id` ascending, then by the cited
    surface form, stance and `about` -- one note can carry two citations of
    the same name, so `chunk_id` alone is not a total order. Truncated at
    `limit`, so the returned prefix is the head of that same total order.

    **Returns `(edges, total)`** (issue #505), not a bare list: `Max Weber`
    carries 165 citation edges on the real vault, so a caller capped at
    `limit` still needs the true pre-cap count to know it saw a window and
    widen `limit` deliberately rather than mistake 10 edges for all of them.
    `total` is `len(edges)` before truncation -- equal to `len(edges)` after
    it when nothing was capped."""
    layer = _name_layer(names_dir)
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()

    edges = [
        CitationEdge(
            chunk_id=note.chunk_id,
            source_id=note.source_id,
            cited=cited,
            stance=stance,
            about=about,
        )
        for note in _answers_index(vault)
        for cited, stance, about in note.citations
        if _surface_matches_canonical(cited, canonical, layer)
    ]
    edges = sorted(
        edges, key=lambda edge: (edge.chunk_id, edge.cited, edge.stance or "", edge.about or "")
    )
    return edges[:limit], len(edges)


def who_argues_against(
    canonical: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> tuple[list[OppositionEdge], int]:
    """Every prose note whose `arguing_against` answers name `canonical`
    (§7.5), carrying that note's own stated `position` and one-sentence
    `claim` so the opposition is legible without a second fetch. This is what
    feeds contested detection and the counter-position whitelist (§7.8) -- a
    relation the author stated, not a label a tagger picked.

    `position` is the note's own `position` answer where that key is present
    and its `position_of` answer otherwise, so one result set can carry both
    frames (§7.15, issue #496; the rule lives in `_read_note_answers`). No
    note in the live corpus carries a `position` key yet, so every real call
    still falls back.

    Same alias-map matching as `who_cites`.

    **Determinism:** sorted by `chunk_id` ascending, then by the matched
    `arguing_against` string (one note can name two surfaces of one name).
    Truncated at `limit`, so the returned prefix is the head of that same
    total order.

    **Returns `(edges, total)`**, same shape and same reason as `who_cites`
    (issue #505): `total` is `len(edges)` before truncation."""
    layer = _name_layer(names_dir)
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()

    edges = [
        OppositionEdge(
            chunk_id=note.chunk_id,
            source_id=note.source_id,
            arguing_against=opposed,
            position=note.position,
            claim=note.claim,
        )
        for note in _answers_index(vault)
        for opposed in note.arguing_against
        if _surface_matches_canonical(opposed, canonical, layer)
    ]
    edges = sorted(edges, key=lambda edge: (edge.chunk_id, edge.arguing_against))
    return edges[:limit], len(edges)


# ---------------------------------------------------------------------------
# where_names_meet
# ---------------------------------------------------------------------------


def where_names_meet(
    canonical: str,
    other: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> tuple[list[NameMember], int]:
    """The notes that are members of BOTH `canonical`'s and `other`'s name
    pages (§7.5, issue #517) -- the co-occurrence edge `name_neighbors`
    already computes, returned as the shared notes themselves rather than as
    a ranked name list. Exists because a brief's `case` anchor is specified
    to be a polity and a polity page is often the largest one in the corpus:
    intersecting it with the intellectual name a brief is actually about (a
    concept, scholar or event) turns a huge, single-source hub read into a
    small, source-diverse set, with no diversity heuristic needed at all --
    the anchor filters, the intellectual name carries the query.

    Both `canonical` and `other` are resolved through the same three exact
    tiers `get_name` uses (`canonical_for_surface`: canonical, alias, fold --
    never tier 4) before either page is read, so an alias or a folded
    variant of either name reaches the same page as its canonical.

    **Reads both pages' full, uncapped member lists and intersects on
    `chunk_id`** -- never `get_name`, whose own `limit` would truncate a page
    before the intersection could see the whole thing. The two helpers this
    reuses (`_resolve_name_page`, `_parse_name_page_body`) are exactly the
    ones `get_name` calls; nothing here re-parses a page by hand. A shared
    member's `author`/`year`/`claim` is read off `canonical`'s own page --
    both pages render the same note identically, so which side supplies it
    is immaterial. This also never touches `_answers_index` (measured
    139.7s cold over the real corpus, issue #520 item 7): reading two name
    pages is O(pages), not O(corpus).

    **A name that resolves to no page raises `NameNotFoundError`**, naming
    whichever of the two failed first (`canonical` checked before `other`),
    exactly like `get_name`. **An empty intersection is an honest answer**,
    returned as `([], 0)` -- both pages existing and sharing no member is
    real information about the corpus, never an error.

    **Determinism, and why it is not `chunk_id` ascending.** The intersecting
    members are sorted by `(source_id, chunk_id)` (a member whose `chunk_id`
    did not parse sorts under `""`, first) and interleaved one member per
    source in rotation by `_round_robin_by_source` (issue #562, shared with
    `get_name`'s own truncation) -- a total order, fully deterministic. Plain
    `chunk_id` ascending is not used because a `chunk_id` begins with its
    `source_id`, so ascending order **is** alphabetical-by-source -- the
    exact defect #517 was filed on: a 104-note intersection truncated to a
    25-note alphabetical prefix came back drawn from 2 sources instead of
    the 11 the true intersection spans. This tool is new, so it states its
    own order here rather than inheriting `get_name`'s page-order contract,
    which nothing in this function reads.

    Returns `(members, total)` (issue #505's own precedent): `members` is
    the round-robin order above, truncated at `limit`; `total` is the true,
    uncapped intersection size."""
    layer = _name_layer(names_dir)
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()

    resolved_canonical = canonical_for_surface(canonical, layer) or canonical
    entry_a = _resolve_name_page(resolved_canonical, vault)
    if entry_a is None:
        raise NameNotFoundError(resolved_canonical, name_page_path(vault, resolved_canonical))

    resolved_other = canonical_for_surface(other, layer) or other
    entry_b = _resolve_name_page(resolved_other, vault)
    if entry_b is None:
        raise NameNotFoundError(resolved_other, name_page_path(vault, resolved_other))

    _frontmatter_a, body_a = _read_frontmatter(entry_a.path)
    members_a, _disagreement_a = _parse_name_page_body(body_a)
    _frontmatter_b, body_b = _read_frontmatter(entry_b.path)
    members_b, _disagreement_b = _parse_name_page_body(body_b)

    other_chunk_ids = {member.chunk_id for member in members_b}
    intersecting = sorted(
        (member for member in members_a if member.chunk_id in other_chunk_ids),
        key=lambda member: (member.source_id or "", member.chunk_id),
    )
    ordered = _round_robin_by_source(intersecting)

    return ordered[:limit], len(ordered)


# ---------------------------------------------------------------------------
# coverage_count
# ---------------------------------------------------------------------------


def coverage_count(*, vault_dir: Path | None = None) -> dict[str, int]:
    """`{canonical: member_count}` for every name the vault carries a page
    for, read off each page's own `member_count` frontmatter (§7.5) -- the
    raw material of the §7.7 per-name coverage map. Never a recount: the
    denominator already exists and Materialize wrote it (D2).

    Read off the name PAGES rather than `index.json`, because the two are the
    same set by construction -- Materialize writes one page per surviving
    canonical and deletes any page whose canonical no longer survives -- and
    a page's own `member_count` is the value §7.5 names. A name in the index
    with no page therefore has no honest count to report, and is absent here
    rather than carried at a fabricated 0 that would read as real, thin
    coverage.

    **This is strictly wider than the per-polity count it replaces** (D2): a
    polity is one `kind` of name, and concepts, scholars, institutions and
    movements now each get a coverage number too. Nothing special-cases a
    polity.

    Returned as a plain dict built in ascending-canonical order -- the same
    explicit-sort determinism contract as every other tool here, applied to a
    mapping instead of a list. A vault with no name pages returns `{}`.

    **Deliberately NOT a model-facing retrieval tool (issue #505's own
    follow-up).** It stays a query-API function, called only from
    `axial.validators.coverage` (§7.7's coverage map, deterministic, zero
    model calls). On a paid corpus run a real provider's model chose
    to call it unprompted and got all 49,674 canonicals back in one result, holding
    the prompt at over a million characters for 14 turns -- the same whole-
    index-dump hazard §7.2 already ruled out for the interrogation pre-pass.
    Do not re-register this in `axial.retrieve.tools.TOOL_REGISTRY`."""
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    index = _name_page_index(vault)
    return {canonical: index[canonical].member_count for canonical in sorted(index)}
