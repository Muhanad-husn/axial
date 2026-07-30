"""Name-layer query: retrieval over the graph the interrogation grew
(Phase-B stage 3, specs/PHASE-B.md §7.5, §8 P0-2, issue #487).

`axial.query.reader` is the note layer -- a note or a source by an id the
caller already holds. This module is the layer that lets a caller FIND
something: the names the corpus carries, the notes that meet at each one, and
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
- **`vault_dir`** (`data/vault/`) -- the name pages Materialize wrote and the
  prose notes' own answer blocks. Everything a name page or a note says
  about itself is read from here, never recomputed.

**Zero LLM calls** (§7.5), with exactly one relaxation, D10: `find_names`'
fourth tier embeds the query string with the local sentence-transformer the
store names in its own `similarity_manifest.json`. That import is lazy,
inside the tier-4 path, so tiers 1-3 run with no encoder loaded at all and
importing this module costs nothing. No network call, no LLM, no chunk index.

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

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from axial.name_candidates import _normalize_form as fold_surface_form
from axial.paths import default_names_dir, default_vault_dir, name_page_path
from axial.query.reader import (
    MalformedChunkIdError,
    MalformedNoteError,
    QueryError,
    _read_frontmatter,
    source_id_from_chunk_id,
)

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

# The four tiers, in resolution order (§7.5).
TIER_EXACT = "exact"
TIER_ALIAS = "alias"
TIER_FOLDED = "folded"
TIER_EMBEDDING = "embedding"

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
    """One `find_names` result (§7.5). `matched_on` is the surface form that
    actually matched -- a canonical, an alias, or an inventory surface -- and
    `tier` is which of the four resolution tiers produced it, so a caller can
    see how confident the resolution is. `member_count` is the name page's
    own frontmatter value, or `None` when this vault holds no page for the
    name (an index/vault mismatch, reported rather than filled in with a 0
    that would read like real, thin coverage)."""

    canonical: str
    kind: str | None
    aliases: list[str]
    member_count: int | None
    matched_on: str
    tier: str


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
        parsed = yaml.safe_load("".join(block_lines))
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    name = parsed.get("name")
    if not isinstance(name, str):
        return None
    member_count = parsed.get("member_count")
    return name, parsed.get("kind"), int(member_count) if isinstance(member_count, int) else 0


def _name_page_index(vault_dir: Path) -> dict[str, _NamePageEntry]:
    """`name -> (path, kind, member_count)` over every page under
    `<vault_dir>/names/`, keyed on each page's OWN `name` frontmatter -- the
    sole authoritative id (§7.5). Never keyed on filenames: a canonical
    carries no unique suffix of its own, so two canonicals can sanitize to
    one filename and the writer hash-suffixes whichever it wrote second
    (`axial.paths.name_page_filename`'s `used` set), a write-order fact no
    reader can reproduce.

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
        names_dir = key / "names"
        index: dict[str, _NamePageEntry] = {}
        if names_dir.is_dir():
            for path in sorted(names_dir.glob("*.md")):
                head = _read_name_page_head(path)
                if head is None:
                    continue
                name, kind, member_count = head
                index[name] = _NamePageEntry(path=path, kind=kind, member_count=member_count)
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
    whole-vault index build."""
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
    position = answers["position"] if "position" in answers else answers.get("position_of")
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


def _default_encoder(model_name: str) -> Encoder:
    """The real local sentence-transformer, imported HERE and never at module
    level (D10: tiers 1-3 must run with no encoder loaded at all). A
    deliberate small duplicate of `axial.names._default_encoder`, which
    cannot be imported without pulling the whole interrogation/LLM stack into
    this LLM-free module."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def encode(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, convert_to_numpy=True).tolist()

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


def find_names(
    query: str,
    limit: int = DEFAULT_LIMIT,
    *,
    names_dir: Path | None = None,
    vault_dir: Path | None = None,
    encoder: Encoder | None = None,
) -> list[NameHit]:
    """Resolve `query` to the names the corpus actually carries (§7.5), in
    four tiers, each exhausted before the next is tried:

    1. `exact` -- `query` is a canonical name in `index.json`;
    2. `alias` -- `query` is an alias of a node in `alias_map.json`;
    3. `folded` -- `query` equals either under the fold Phase A already
       applies to surface forms (case, whitespace, punctuation, hyphen to a
       space; §7.16, issue #463 -- reused, never re-derived);
    4. `embedding` -- nearest neighbours among the vectors Reconcile
       persisted, each mapped back through the alias map to its canonical and
       de-duplicated.

    **Resolution is tiered, never string equality**, because exact lookup
    provably fails on the names briefs use: the index holds `Charles Tilly`,
    `Giorgio Agamben` and `Uğur Ümit Üngör` while briefs say Tilly, Agamben,
    Ungor. Measured on the live vault (2026-07-30): `Tilly`, `Agamben`,
    `Bayat`, `Batatu` and `Caspersen` all land through the alias map, and
    `Ungor` reaches `Uğur Ümit Üngör` only through tier 4.

    **A query that resolves to nothing returns `[]`, and that is a real
    answer** -- never an exception, never silence, and never the nearest name
    to hand (which is what `MIN_EMBEDDING_SIMILARITY` exists to prevent). A
    caller should report it as an honest resolution failure. What it does NOT
    mean is that the corpus lacks the entity: an acronym whose expansion the
    index carries can still reach nothing (see `MIN_EMBEDDING_SIMILARITY`),
    which is a name-layer gap rather than an answer about the corpus.

    **Determinism:** tiers 1-3 are exact lookups over committed data, ordered
    by canonical ascending then by the matched surface form. Tier 4 is
    ordered by score descending, ties by canonical ascending. Every tier is
    truncated at `limit`.

    `encoder` replaces the default sentence-transformer (tier 4 only) -- the
    seam a test uses to exercise the ranked tier without loading a model.
    Tiers 1-3 never call it.
    """
    layer = _name_layer(names_dir)
    directory = Path(names_dir) if names_dir is not None else default_names_dir()

    matches: list[tuple[str, str]] = []
    tier = TIER_EXACT
    if query in layer.canonicals:
        matches = [(query, query)]
    else:
        aliased = layer.canonicals_by_alias.get(query)
        if aliased:
            tier = TIER_ALIAS
            matches = [(canonical, query) for canonical in aliased]
        else:
            folded = layer.folded.get(fold_surface_form(query))
            if folded:
                tier = TIER_FOLDED
                # One canonical, one hit: a query can fold onto a canonical
                # AND onto one of that same canonical's aliases (the corpus
                # writes both "bellicist state formation" and "bellicist
                # state-formation"), which is one name, not two. Walked in
                # sorted order, so the surviving `matched_on` is the lowest
                # matching surface form, deterministically.
                seen: set[str] = set()
                for canonical, surface in sorted(folded):
                    if canonical not in seen:
                        seen.add(canonical)
                        matches.append((canonical, surface))
            else:
                tier = TIER_EMBEDDING
                matches = _embedding_tier(query, layer, directory, encoder)

    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    hits = []
    for canonical, matched_on in matches[:limit]:
        # One page read per hit, never the whole-vault index: `find_names` is
        # the first thing a retrieval loop calls, and a 62.8k-page scan to
        # decorate at most `limit` hits with their `member_count` would be
        # paid on every run.
        entry = _resolve_name_page(canonical, vault)
        hits.append(
            NameHit(
                canonical=canonical,
                kind=layer.kind_by_canonical.get(canonical)
                or (entry.kind if entry is not None else None),
                aliases=list(layer.aliases_by_canonical.get(canonical, ())),
                member_count=entry.member_count if entry is not None else None,
                matched_on=matched_on,
                tier=tier,
            )
        )
    return hits


# ---------------------------------------------------------------------------
# get_name
# ---------------------------------------------------------------------------


def get_name(
    canonical: str, limit: int = DEFAULT_LIMIT, *, vault_dir: Path | None = None
) -> NamePage:
    """One name page by its real name (§7.5): its `kind`, `aliases`,
    `member_count`, its member notes with each one's own author, year and
    one-sentence claim, and any Gather disagreement section.

    Members come back in the page's own written order, which is the order
    Materialize wrote and is itself deterministic -- never re-sorted here --
    **truncated at `limit`** (issue #505: a hub name page can carry hundreds
    of members -- `Syria` has 962 -- and an uncapped `members` list is what
    flooded a real retrieval loop's prompt to ~72,000 characters over twelve
    re-sent turns). `member_count` is deliberately left UNCAPPED: it is the
    page's own frontmatter total regardless of `limit`, so a caller sees both
    the window (`len(members)`) and the true size it is a window onto.
    `disagreement` is `None` when the page carries no Gather section, which
    is distinguishable from a section whose text is present.

    Raises `NameNotFoundError`, naming `canonical`, when no page exists --
    never returns `None`. A page whose filename was budgeted down or
    hash-suffixed is still reachable by its real name (§7.5: the `name`
    frontmatter is the sole authoritative id, never the filename)."""
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    entry = _resolve_name_page(canonical, vault)
    if entry is None:
        raise NameNotFoundError(canonical, name_page_path(vault, canonical))

    frontmatter, body = _read_frontmatter(entry.path)
    all_members, disagreement = _parse_name_page_body(body)
    member_count = frontmatter.get("member_count")
    aliases = [alias for alias in (frontmatter.get("aliases") or []) if isinstance(alias, str)]
    return NamePage(
        canonical=frontmatter.get("name") or canonical,
        kind=frontmatter.get("kind"),
        aliases=aliases,
        member_count=member_count if isinstance(member_count, int) else len(all_members),
        members=all_members[:limit],
        disagreement=disagreement,
    )


# ---------------------------------------------------------------------------
# name_neighbors / who_cites / who_argues_against
# ---------------------------------------------------------------------------


def name_neighbors(
    canonical: str,
    limit: int = DEFAULT_LIMIT,
    *,
    vault_dir: Path | None = None,
    names_dir: Path | None = None,
) -> list[NameNeighbor]:
    """The names that co-occur with `canonical` in some note's own `names`
    answers, ranked by how many notes they share (§7.5). This is the cheapest
    real edge the interrogation produced: two names on one note are two
    things one author discussed together -- and it is the traversal
    `follow_backlinks` used to be, over a facet that exists (D5).

    A note counts once per neighbour however many times it names it, and a
    name is never its own neighbour. Every surface form on a note is mapped
    through the alias map to its canonical first, so two spellings of one
    name are one neighbour; a surface the layer does not carry stands as its
    own canonical (§7.16: nothing is dropped).

    **Determinism:** `shared_note_count` descending, ties by canonical
    ascending, truncated at `limit`."""
    layer = _name_layer(names_dir)
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()

    counts: dict[str, int] = {}
    kinds: dict[str, str | None] = {}
    for note in _answers_index(vault):
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

    ordered = sorted(counts, key=lambda name: (-counts[name], name))[:limit]
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
    mapping instead of a list. A vault with no name pages returns `{}`."""
    vault = Path(vault_dir) if vault_dir is not None else default_vault_dir()
    index = _name_page_index(vault)
    return {canonical: index[canonical].member_count for canonical in sorted(index)}
