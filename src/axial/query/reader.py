"""Vault query: the read layer over the tagged Obsidian vault (Phase-B
stage 3, specs/PHASE-B.md §7.5, §8 P0-2).

`src/axial/vault.py` is write-only: it renders notes but never reads them
back. This module is the read side. Slice 01 (issue #249) landed the note
parser and the first three of the §7.5 tool set -- `get_chunk`,
`get_artifact`, `query_by_tag`. Slice 02 (issue #251) adds the remaining
four: `query_by_polity`, `query_by_source` / `get_envelope`,
`follow_backlinks`, `coverage_count`.

LLM-free and embedding-free by construction (§7.5's "no model and no
embedding model"): every path here is pure file I/O, YAML/JSON parsing, and
in-memory filtering. Nothing here imports OR constructs a provider client --
this module imports `axial.paths` for vault-dir resolution, never
`axial.vault` (whose write-side stack pulls in `axial.llm` and the whole
LLM-backed pipeline, issue #249 F1). `get_envelope` reads
`data/envelopes/<source_id>.json` directly rather than importing
`axial.envelope` for the same reason: that module pulls in `httpx`,
`docling`'s extract stack, and the whole LLM client apparatus to define one
path-resolution helper. `_default_envelopes_dir` below is a deliberate,
small duplicate of `axial.envelope._default_envelopes_dir`'s config-lookup
logic -- not imported, and `axial.paths.py` (the natural home for a shared
version) is owned by another slice this wave.

Read-only by construction (§3 non-goal 5): no function in this module
writes to the vault.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.paths import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    artifact_note_path,
    chunk_note_path,
    default_vault_dir,
)

# The §7.5 fixed axis filter set for `query_by_tag`. `polity` matches
# `empirical_scope`'s nested `polity` sub-field, distinct from the
# `empirical_scope` filter itself (which matches on `value`).
KNOWN_FILTER_KEYS = frozenset(
    {"field", "claim_type", "theory_school", "empirical_scope", "polity", "role_in_argument"}
)


class QueryError(Exception):
    """Base class for all vault-query errors."""


class MalformedNoteError(QueryError):
    """A note's frontmatter is absent, unterminated, not valid YAML, not a
    mapping, or missing a required field."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"malformed vault note at {path}: {reason}")


class ChunkNotFoundError(QueryError):
    """No note exists for a `get_chunk` chunk_id."""

    def __init__(self, chunk_id: str, path: Path):
        self.chunk_id = chunk_id
        self.path = path
        super().__init__(f"no chunk note found for chunk_id {chunk_id!r} (expected at {path})")


class ArtifactNotFoundError(QueryError):
    """No note exists for a `get_artifact` artifact_id."""

    def __init__(self, artifact_id: str, path: Path):
        self.artifact_id = artifact_id
        self.path = path
        super().__init__(
            f"no artifact note found for artifact_id {artifact_id!r} (expected at {path})"
        )


class UnknownFilterError(QueryError):
    """`query_by_tag` was called with a filter key outside
    KNOWN_FILTER_KEYS -- a typo'd axis must not quietly widen a query into
    matching everything."""

    def __init__(self, unknown_keys: set[str]):
        self.unknown_keys = unknown_keys
        super().__init__(
            f"unknown query_by_tag filter key(s) {sorted(unknown_keys)!r}; "
            f"expected only {sorted(KNOWN_FILTER_KEYS)!r}"
        )


class MissingVaultDirError(QueryError):
    """`query_by_tag`'s `<vault_dir>/prose/` does not exist -- a missing or
    typo'd vault_dir is a caller bug, not an empty corpus, so it raises
    rather than silently returning `[]`."""

    def __init__(self, prose_dir: Path):
        self.prose_dir = prose_dir
        super().__init__(f"vault prose directory does not exist: {prose_dir}")


class EnvelopeNotFoundError(QueryError):
    """No envelope JSON exists for a `get_envelope` source_id."""

    def __init__(self, source_id: str, path: Path):
        self.source_id = source_id
        self.path = path
        super().__init__(f"no envelope found for source_id {source_id!r} (expected at {path})")


class MalformedChunkIdError(QueryError):
    """A chunk_id does not match the `<source_id>_<order>_<slug>_<NNN>`
    shape (`axial.chunk.build_chunk_records`) `query_by_source` parses
    `source_id` out of."""

    def __init__(self, chunk_id: str):
        self.chunk_id = chunk_id
        super().__init__(
            f"chunk_id {chunk_id!r} does not match the expected "
            f"<source_id>_<order>_<slug>_<NNN> shape"
        )


class BacklinkTargetNotFoundError(QueryError):
    """A `follow_backlinks` id resolves to neither a chunk note nor an
    artifact note -- there is no third kind of vault id to dispatch to, so
    this is always a caller bug (e.g. a typo'd id), distinct from a real
    chunk/artifact whose link list is legitimately empty (`[]`, not an
    error)."""

    def __init__(self, id_: str, chunk_path: Path, artifact_path: Path):
        self.id = id_
        self.chunk_path = chunk_path
        self.artifact_path = artifact_path
        super().__init__(
            f"id {id_!r} resolves to neither a chunk note (expected at "
            f"{chunk_path}) nor an artifact note (expected at {artifact_path})"
        )


@dataclass(frozen=True)
class ChunkNote:
    """One parsed prose note (`<vault_dir>/prose/<chunk_id>.md`): its id,
    text, and full tag-axis frontmatter in their real nested shapes (PRD
    §7.2 / Appendix H's nesting, unflattened -- unlike
    `axial.gold.parse_note`'s flat representative-scalar projection, this is
    the general-purpose read layer every later §7.5 tool builds on, so it
    keeps each axis's whole shape: `field`/`claim_type`/`theory_school`'s
    `{primary, secondary, ...}`, `empirical_scope`'s `{value, polity}`)."""

    chunk_id: str
    section: str
    chunk_text: str
    source_meta: dict[str, Any]
    schema_version: str
    role_in_argument: str
    field: dict[str, Any]
    claim_type: dict[str, Any]
    theory_school: dict[str, Any]
    empirical_scope: dict[str, Any]
    polities_touched: list[str]
    artifact_refs: list[str]


@dataclass(frozen=True)
class ArtifactNote:
    """One parsed artifact note (`<vault_dir>/artifacts/<artifact_id>.md`).
    `caption` is `None` when the note carries none -- mirroring the write
    side's own conditional-inclusion convention (issue #168,
    `axial.vault.build_artifact_frontmatter`), never raising for its
    absence.

    `artifact_role`/`field` are retired (issue #429: the artifacts pass
    makes no LLM call, so a note written under the current pipeline never
    carries either key) but stay as optional fields here, defaulting to
    `None`, rather than being removed outright: an OLDER note written before
    #429 still carries them, and Phase B's callers (`axial.panel.packet`,
    `axial.gates.grounding`) degrade to the artifact's own id when they are
    absent rather than crashing on a required key that no longer exists."""

    artifact_id: str
    source_id: str
    section: str
    retrievable: bool
    cited_by: list[str]
    caption: str | None = None
    artifact_role: str | None = None
    field: dict[str, Any] | None = None


@dataclass(frozen=True)
class Envelope:
    """One parsed source envelope (`<envelopes_dir>/<source_id>.json`,
    `axial.envelope.build_envelope`'s own `{source_id, thesis, toc, scope,
    stated_argument}` shape). `toc` is the post-#235 nested shape: a list of
    `{title: str, children: [str, ...]}` objects, preserved unflattened.
    `author`/`title`/`date` are deliberately absent here too (§7.13, #278):
    the envelope pass never concludes them, so there is nothing to read."""

    source_id: str
    thesis: str
    toc: list[dict[str, Any]]
    scope: str
    stated_argument: str


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Split a note's `---`-delimited YAML frontmatter block from its
    markdown body. Raises `MalformedNoteError`, naming `path`, when the
    opening or closing delimiter is missing, the block is not valid YAML,
    or it does not parse to a mapping."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise MalformedNoteError(path, "missing opening '---' frontmatter delimiter")

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise MalformedNoteError(path, "missing closing '---' frontmatter delimiter")

    block = "\n".join(lines[1:end_index])
    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise MalformedNoteError(path, f"invalid YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise MalformedNoteError(
            path, f"frontmatter must be a mapping, got {type(parsed).__name__}"
        )

    body = "\n".join(lines[end_index + 1 :])
    return parsed, body


def _require(frontmatter: dict[str, Any], path: Path, field_name: str) -> Any:
    if field_name not in frontmatter:
        raise MalformedNoteError(path, f"missing required field {field_name!r}")
    return frontmatter[field_name]


def _parse_chunk_note(path: Path) -> ChunkNote:
    frontmatter, _body = _read_frontmatter(path)
    return ChunkNote(
        chunk_id=_require(frontmatter, path, "chunk_id"),
        section=_require(frontmatter, path, "section"),
        chunk_text=_require(frontmatter, path, "chunk_text"),
        source_meta=_require(frontmatter, path, "source_meta"),
        schema_version=_require(frontmatter, path, "schema_version"),
        role_in_argument=_require(frontmatter, path, "role_in_argument"),
        field=_require(frontmatter, path, "field"),
        claim_type=_require(frontmatter, path, "claim_type"),
        theory_school=_require(frontmatter, path, "theory_school"),
        empirical_scope=_require(frontmatter, path, "empirical_scope"),
        polities_touched=list(frontmatter.get("polities_touched") or []),
        artifact_refs=list(frontmatter.get("artifact_refs") or []),
    )


def _parse_artifact_note(path: Path) -> ArtifactNote:
    frontmatter, _body = _read_frontmatter(path)
    return ArtifactNote(
        artifact_id=_require(frontmatter, path, "artifact_id"),
        source_id=_require(frontmatter, path, "source_id"),
        section=_require(frontmatter, path, "section"),
        retrievable=_require(frontmatter, path, "retrievable"),
        cited_by=list(frontmatter.get("cited_by") or []),
        caption=frontmatter.get("caption"),
        # `artifact_role`/`field` (issue #429): read when present (an older
        # note), never required -- a current note carries neither key.
        artifact_role=frontmatter.get("artifact_role"),
        field=frontmatter.get("field"),
    )


def get_chunk(chunk_id: str, vault_dir: Path | None = None) -> ChunkNote:
    """Fetch one prose note by id (§7.5). Raises `ChunkNotFoundError`,
    naming `chunk_id`, when no note exists -- never returns `None`.

    A note's on-disk filename is a display artifact, not its id: a source
    whose readable name would push the path over Windows' MAX_PATH gets its
    note filename shortened at write time (`axial.vault.write_chunk_note`,
    PR #377), while `chunk_id` itself never changes. Resolution here tries
    the direct `<chunk_id>.md` path first (correct for ~97.8% of notes,
    measured on the real corpus), falling back to `axial.paths.chunk_note_path`
    -- the SAME naming function the writer used -- only on a miss, so a
    budgeted note is still reachable by its real, correct chunk_id."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    path = _resolve_chunk_path(chunk_id, Path(vault_dir))
    if not path.is_file():
        raise ChunkNotFoundError(chunk_id, path)
    return _parse_chunk_note(path)


def get_artifact(artifact_id: str, vault_dir: Path | None = None) -> ArtifactNote:
    """Fetch one artifact note by id (§7.5). Raises `ArtifactNotFoundError`,
    naming `artifact_id`, when no note exists -- never returns `None`. Same
    direct-path-then-budgeted-fallback resolution as `get_chunk` (see its
    docstring)."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    path = _resolve_artifact_path(artifact_id, Path(vault_dir))
    if not path.is_file():
        raise ArtifactNotFoundError(artifact_id, path)
    return _parse_artifact_note(path)


def _read_id_only(path: Path, id_field: str) -> str | None:
    """Read just enough of `path` to recover its frontmatter's `id_field`
    value, without loading the rest of the file into memory -- a prose
    note's `chunk_text` can make the full file large, and the suffix index
    below reads every note under `vault_dir` (~18k notes on the real
    corpus), so paying for a full `_read_frontmatter` parse (whole-file
    `read_text`) per note here would be wasteful. Returns `None`, never
    raises, on any malformed note: an index build over the whole corpus
    must not abort on one bad note, and a lookup through this index is
    already a repair-path fallback, not the normal read (`get_chunk`/
    `get_artifact` still raise `MalformedNoteError` on their own reads)."""
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
    value = parsed.get(id_field)
    return value if isinstance(value, str) else None


# Process-lifetime caches for the id -> path indexes `find_chunk_ids_ending_with`
# / `find_artifact_ids_ending_with` use, keyed by resolved vault_dir so
# distinct vaults (real callers, and per-test tmp_path vaults) never share an
# entry. Built lazily, at most once per vault_dir: nothing in this module
# populates these on import or on `get_chunk`/`get_artifact`'s own fast path
# (specs/PHASE-B.md §7.5) -- only a suffix lookup does, and a rebuild-per-call
# would be pathological inside a retrieval loop over the ~18k-note corpus.
_CHUNK_ID_INDEX_CACHE: dict[Path, dict[str, Path]] = {}
_ARTIFACT_ID_INDEX_CACHE: dict[Path, dict[str, Path]] = {}


def _chunk_id_index(vault_dir: Path) -> dict[str, Path]:
    key = Path(vault_dir).resolve()
    if key not in _CHUNK_ID_INDEX_CACHE:
        prose_dir = key / "prose"
        index: dict[str, Path] = {}
        if prose_dir.is_dir():
            for path in prose_dir.glob("*.md"):
                chunk_id = _read_id_only(path, "chunk_id")
                if chunk_id is not None:
                    index[chunk_id] = path
        _CHUNK_ID_INDEX_CACHE[key] = index
    return _CHUNK_ID_INDEX_CACHE[key]


def _artifact_id_index(vault_dir: Path) -> dict[str, Path]:
    key = Path(vault_dir).resolve()
    if key not in _ARTIFACT_ID_INDEX_CACHE:
        artifacts_dir = key / "artifacts"
        index: dict[str, Path] = {}
        if artifacts_dir.is_dir():
            for path in artifacts_dir.glob("*.md"):
                artifact_id = _read_id_only(path, "artifact_id")
                if artifact_id is not None:
                    index[artifact_id] = path
        _ARTIFACT_ID_INDEX_CACHE[key] = index
    return _ARTIFACT_ID_INDEX_CACHE[key]


def find_chunk_ids_ending_with(suffix: str, *, vault_dir: Path | None = None) -> list[str]:
    """Every real `chunk_id` under `vault_dir` ending with `suffix`
    (`str.endswith`). Not part of the §7.5 tool set the model or a caller
    queries with; it exists for `axial.analyze.synthesis`'s grounds-
    resolution fallback, which repairs a citation where the model echoed
    only the tail of a real, long chunk id (DEC-42: `source_id` -- and so
    `chunk_id` -- runs to ~200 chars after the corpus rebuild).

    Candidate discovery is over the `chunk_id` -> path index
    (`_chunk_id_index`, built from frontmatter, cached for the process
    lifetime), never over filenames: the budgeted-filename rule
    (`axial.paths.budgeted_chunk_filename`) can shorten a note's on-disk
    name anywhere, including dropping the very tail a cited suffix names,
    so a filename-keyed scan can miss a real id a frontmatter-keyed one
    finds. Matches are sorted for determinism; returns 0, 1, or 2+ distinct
    ids -- the caller decides what a given count means."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    index = _chunk_id_index(Path(vault_dir))
    return sorted(chunk_id for chunk_id in index if chunk_id.endswith(suffix))


def find_artifact_ids_ending_with(suffix: str, *, vault_dir: Path | None = None) -> list[str]:
    """The artifact-note counterpart of `find_chunk_ids_ending_with` -- same
    frontmatter-indexed candidate discovery, same contract."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    index = _artifact_id_index(Path(vault_dir))
    return sorted(artifact_id for artifact_id in index if artifact_id.endswith(suffix))


def _axis_matches(axis_value: Any, filter_value: str) -> bool:
    """Match a `{primary, secondary, subtags?}`-shaped axis frontmatter
    value (`field`, `claim_type`, `theory_school`) against `filter_value`:
    true on the primary tag, on any secondary tag (whether `secondary` is a
    zero-or-more list -- `field`'s `primary_plus_secondary` cardinality --
    or an optional single scalar -- `claim_type`/`theory_school`'s
    `primary_plus_optional_secondary` cardinality, see `axial.tag`), or on
    any declared `subtags` entry (the "incl. subtags" rule of §7.5)."""
    if not isinstance(axis_value, dict):
        return False
    if axis_value.get("primary") == filter_value:
        return True
    secondary = axis_value.get("secondary")
    if isinstance(secondary, list):
        if filter_value in secondary:
            return True
    elif secondary == filter_value:
        return True
    subtags = axis_value.get("subtags")
    if isinstance(subtags, list) and filter_value in subtags:
        return True
    return False


def _match_empirical_scope(frontmatter: dict[str, Any], filter_value: str) -> bool:
    scope = frontmatter.get("empirical_scope")
    return isinstance(scope, dict) and scope.get("value") == filter_value


def _match_polity(frontmatter: dict[str, Any], filter_value: str) -> bool:
    scope = frontmatter.get("empirical_scope")
    return isinstance(scope, dict) and scope.get("polity") == filter_value


def _match_role_in_argument(frontmatter: dict[str, Any], filter_value: str) -> bool:
    return frontmatter.get("role_in_argument") == filter_value


# One matcher per §7.5 filter key, each `(frontmatter, filter_value) -> bool`.
_FILTER_MATCHERS = {
    "field": lambda fm, value: _axis_matches(fm.get("field"), value),
    "claim_type": lambda fm, value: _axis_matches(fm.get("claim_type"), value),
    "theory_school": lambda fm, value: _axis_matches(fm.get("theory_school"), value),
    "empirical_scope": _match_empirical_scope,
    "polity": _match_polity,
    "role_in_argument": _match_role_in_argument,
}


def query_by_tag(*, vault_dir: Path | None = None, **filters: str) -> list[str]:
    """Every chunk_id whose prose note satisfies the **conjunction** of the
    given tag-axis filters (§7.5): `field`, `claim_type` (incl. subtags),
    `empirical_scope` (incl. `polity`), `role_in_argument`, `theory_school`.
    A filter set no note satisfies returns `[]`, not an error; an unknown
    filter key raises `UnknownFilterError` instead of silently matching
    everything. `vault_dir` is keyword-only so a filter value can never be
    mistaken for it positionally.

    A note missing the axis a given filter targets is treated as not
    matching that filter -- excluded, not an error -- so one note with a
    thin frontmatter does not abort an otherwise-good scan. `chunk_id`
    itself is not optional in this sense: every note under `prose/` must
    carry one to be scanned at all (`MalformedNoteError` otherwise), so a
    result id always resolves back through `get_chunk`.

    Results are sorted by `chunk_id` (§7.5's determinism contract) --
    directory iteration order is filesystem/OS-dependent and MUST NOT leak
    into the result order.

    Backed by the same process-lifetime frontmatter index
    `query_by_polity`/`coverage_count` use (`_frontmatter_index`, see its
    docstring): the vault is assumed not to change within one process's
    lifetime, true for every real caller here (a sweep, an agentic
    retrieval loop, a CLI invocation)."""
    unknown_keys = set(filters) - KNOWN_FILTER_KEYS
    if unknown_keys:
        raise UnknownFilterError(unknown_keys)

    if vault_dir is None:
        vault_dir = default_vault_dir()

    matches: list[str] = []
    for entry in _frontmatter_index(vault_dir):
        if entry.chunk_id is _NO_CHUNK_ID:
            raise MalformedNoteError(entry.path, "missing required field 'chunk_id'")
        frontmatter = _entry_to_frontmatter_dict(entry)
        if all(_FILTER_MATCHERS[name](frontmatter, value) for name, value in filters.items()):
            matches.append(entry.chunk_id)

    return sorted(matches)


# =============================================================================
# Slice 02 (issue #251): query_by_polity, query_by_source / get_envelope,
# follow_backlinks, coverage_count
# =============================================================================


# Sentinel distinguishing "frontmatter has no `chunk_id` key at all" from
# "frontmatter has `chunk_id: null`" (`dict.get`'s own default-vs-present
# ambiguity) -- `_require`'s contract only cares about key presence, and the
# cached index below has to reproduce that exactly without re-reading the
# file to check.
_NO_CHUNK_ID = object()


@dataclass(frozen=True)
class _FrontmatterIndexEntry:
    """The subset of one prose note's frontmatter that `query_by_tag`,
    `query_by_polity`, `query_by_source`, and `coverage_count` actually
    read -- never `chunk_text`, `section`, `source_meta`, `schema_version`,
    or `artifact_refs`, which no filter here consults and which would
    otherwise make the process-lifetime index below hold a full copy of
    every note's frontmatter (17,851 notes on the real corpus)."""

    path: Path
    chunk_id: Any  # `_NO_CHUNK_ID` when the note carries no `chunk_id` key.
    field: Any
    claim_type: Any
    theory_school: Any
    empirical_scope: Any
    role_in_argument: Any
    polities_touched: list[str]


def _read_frontmatter_index_entry(path: Path) -> _FrontmatterIndexEntry:
    """Parse `path`'s `---`-delimited frontmatter block only -- never its
    body -- keeping just the `_FrontmatterIndexEntry` field set. Raises
    `MalformedNoteError` exactly where `_read_frontmatter` would (missing
    opening/closing delimiter, invalid YAML, non-mapping): every note under
    `prose/` is still parsed and validated once, up front, the same
    unconditional-per-note contract `query_by_tag`/`_iter_chunk_frontmatter`
    already enforced before this cache existed. `chunk_id` itself is
    deliberately not required here -- callers disagree on when a missing
    `chunk_id` should raise (`query_by_tag` and `query_by_source` require it
    for every note; `query_by_polity` only when a note actually matches;
    `coverage_count` never does), so this stores `_NO_CHUNK_ID` when absent
    and leaves the raise to each caller's own contract."""
    with path.open("r", encoding="utf-8") as handle:
        first_line = handle.readline()
        if first_line.strip() != "---":
            raise MalformedNoteError(path, "missing opening '---' frontmatter delimiter")
        block_lines: list[str] = []
        for line in handle:
            if line.strip() == "---":
                break
            block_lines.append(line)
        else:
            raise MalformedNoteError(path, "missing closing '---' frontmatter delimiter")

    try:
        parsed = yaml.safe_load("".join(block_lines))
    except yaml.YAMLError as exc:
        raise MalformedNoteError(path, f"invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MalformedNoteError(
            path, f"frontmatter must be a mapping, got {type(parsed).__name__}"
        )

    return _FrontmatterIndexEntry(
        path=path,
        chunk_id=parsed.get("chunk_id", _NO_CHUNK_ID),
        field=parsed.get("field"),
        claim_type=parsed.get("claim_type"),
        theory_school=parsed.get("theory_school"),
        empirical_scope=parsed.get("empirical_scope"),
        role_in_argument=parsed.get("role_in_argument"),
        polities_touched=list(parsed.get("polities_touched") or []),
    )


# Process-lifetime cache of the frontmatter index every prose-note scan in
# this module now reads from, keyed by resolved vault_dir (same convention
# as `_CHUNK_ID_INDEX_CACHE`/`_ARTIFACT_ID_INDEX_CACHE` above). Measured on
# the real corpus: an uncached scan over 17,851 notes costs ~93s; a sweep
# that calls `query_by_tag`/`query_by_polity`/`coverage_count` repeatedly
# against an unchanging vault (true for the lifetime of any one process --
# nothing in this read-only module ever writes to the vault) paid that cost
# on every call. Guarded by `_FRONTMATTER_INDEX_LOCK` (unlike the two id
# indexes above, which have no lock): those are read on a cache hit far more
# often than built, but this index's first caller in a freshly started, many-
# threaded sweep is a near-certain pile-up -- without a lock, N threads can
# each kick off their own ~93s cold build concurrently instead of one thread
# building it once for all.
#
# Consequence of the "vault does not change within one process" assumption:
# a cache HIT returns before `prose_dir.is_dir()` is ever re-checked, so a
# vault whose `prose/` directory is removed mid-process (after this index
# already built once) stops raising `MissingVaultDirError` on later calls --
# it keeps serving the last-known-good index instead. This is the same
# assumption `_CHUNK_ID_INDEX_CACHE`/`_ARTIFACT_ID_INDEX_CACHE` already make
# (a "does this id now exist" recheck is exactly as stale), stated here
# because a missing-directory check reads more like a live guard than a
# cached lookup does -- a future caller relying on this index to detect a
# vault disappearing out from under a long-running process should build
# their own fresh check, not assume one hides in here.
_FRONTMATTER_INDEX_CACHE: dict[Path, list[_FrontmatterIndexEntry]] = {}
_FRONTMATTER_INDEX_LOCK = threading.Lock()


def _frontmatter_index(vault_dir: Path) -> list[_FrontmatterIndexEntry]:
    key = Path(vault_dir).resolve()
    cached = _FRONTMATTER_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    with _FRONTMATTER_INDEX_LOCK:
        # Re-check inside the lock: another thread may have finished the
        # cold build while this one was waiting to acquire it.
        cached = _FRONTMATTER_INDEX_CACHE.get(key)
        if cached is not None:
            return cached
        prose_dir = Path(vault_dir) / "prose"
        if not prose_dir.is_dir():
            raise MissingVaultDirError(prose_dir)
        entries: list[_FrontmatterIndexEntry] = []
        for path in prose_dir.iterdir():
            if path.suffix != ".md":
                continue
            entries.append(_read_frontmatter_index_entry(path))
        _FRONTMATTER_INDEX_CACHE[key] = entries
        return entries


def _entry_to_frontmatter_dict(entry: _FrontmatterIndexEntry) -> dict[str, Any]:
    """Rehydrate one cached index entry into the small frontmatter-dict
    shape `query_by_tag`'s `_FILTER_MATCHERS` and the slice-02 tools
    already expect -- carrying only the fields the index itself stores, and
    omitting the `chunk_id` key entirely (rather than setting it to
    `_NO_CHUNK_ID` or `None`) when the note had none, so `_require`'s own
    `field_name not in frontmatter` presence check still means what it always
    meant."""
    frontmatter: dict[str, Any] = {
        "field": entry.field,
        "claim_type": entry.claim_type,
        "theory_school": entry.theory_school,
        "empirical_scope": entry.empirical_scope,
        "role_in_argument": entry.role_in_argument,
        "polities_touched": entry.polities_touched,
    }
    if entry.chunk_id is not _NO_CHUNK_ID:
        frontmatter["chunk_id"] = entry.chunk_id
    return frontmatter


def _iter_chunk_frontmatter(vault_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every `<vault_dir>/prose/*.md` note's full `(path, frontmatter)`,
    unsorted -- every caller here sorts its own derived result, so this
    shared scan need not (and directory order is filesystem/OS-dependent
    regardless). Raises `MissingVaultDirError` when `prose/` itself is
    absent, the same rule `query_by_tag` already enforces: a missing or
    typo'd `vault_dir` is a caller bug, not an empty corpus.

    Deliberately uncached and NOT backed by `_frontmatter_index`: its other
    callers here (`query_by_source`) only ever scan a vault once per
    process, but `axial.distill.embed`/`axial.distill.classify` also import
    this exact private function for their own one-shot, whole-corpus reads
    and need the FULL frontmatter dict, including `chunk_text` -- the one
    field `_frontmatter_index` deliberately excludes to keep its own,
    repeatedly-hit process-lifetime cache small (see that function's
    docstring). Caching a full-text copy of all ~18k notes for those single-
    use callers would trade the memory `_frontmatter_index` was built to
    avoid for a speed win neither of them repeats calls often enough to
    need."""
    prose_dir = Path(vault_dir) / "prose"
    if not prose_dir.is_dir():
        raise MissingVaultDirError(prose_dir)
    notes = []
    for path in prose_dir.iterdir():
        if path.suffix != ".md":
            continue
        frontmatter, _body = _read_frontmatter(path)
        notes.append((path, frontmatter))
    return notes


def query_by_polity(polity: str, *, vault_dir: Path | None = None) -> list[str]:
    """Every chunk_id whose `polities_touched` list includes `polity`
    (§7.5): exact-string match against the faithful-naming values Phase A
    wrote, no normalization or aliasing, and a chunk with an empty or
    absent list never matches. This is the cross-case facet the
    single-valued `empirical_scope.polity` filter (`query_by_tag`'s
    `polity` key) cannot serve: a chunk *scoped* to one polity but
    *touching* another is matched here, not there.

    Results are sorted by chunk_id, the same determinism contract as
    `query_by_tag`. Backed by the same process-lifetime `_frontmatter_index`
    cache `query_by_tag`/`coverage_count` use (see that function's
    docstring): the vault is assumed not to change within one process's
    lifetime."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    matches: list[str] = []
    for entry in _frontmatter_index(vault_dir):
        if polity in entry.polities_touched:
            if entry.chunk_id is _NO_CHUNK_ID:
                raise MalformedNoteError(entry.path, "missing required field 'chunk_id'")
            matches.append(entry.chunk_id)
    return sorted(matches)


def source_id_from_chunk_id(chunk_id: str) -> str:
    """The `source_id` seam within a chunk_id
    (`<source_id>_<section_order>_<section_slug>_<NNN>`,
    `axial.chunk.build_chunk_records`). The three trailing `_`-delimited
    segments never themselves contain a `_`: `section_order` has its dots
    replaced with hyphens, `section_slug` is hyphen-slugified
    (`axial.chunk._slugify`, `[^a-z0-9]+` -> `-`), and `NNN` is a bare
    zero-padded index -- so `source_id` is exactly everything before the
    last three `_`-delimited segments. Raises `MalformedChunkIdError` when
    `chunk_id` has fewer than four `_`-delimited segments to split.

    Public (no leading underscore): `axial.answer.source_usage` (§7.13)
    reuses this exact parse rule to resolve a chunk grounds pointer to its
    `source_id`, so it is a parse shared across modules, not a
    query_by_source-only implementation detail."""
    parts = chunk_id.rsplit("_", 3)
    if len(parts) != 4 or not parts[0]:
        raise MalformedChunkIdError(chunk_id)
    return parts[0]


# `artifact_id`'s own `<source_id>_art_<order>` grammar
# (`axial.artifacts.artifact_id_for_node`), with `order` locked to a
# dotted-digits shape -- unlike `source_id_from_chunk_id`, this never raises:
# it exists only to drive the budgeted-filename fallback below, where "this
# id doesn't parse" and "this id parses but the note is missing" both end in
# the same not-found outcome, so a `None` return is all a caller needs.
_ARTIFACT_ORDER_SUFFIX = re.compile(r"_art_[0-9]+(?:\.[0-9]+)*$")


def _source_id_from_artifact_id(artifact_id: str) -> str | None:
    match = _ARTIFACT_ORDER_SUFFIX.search(artifact_id)
    if not match or match.start() == 0:
        return None
    return artifact_id[: match.start()]


def _resolve_chunk_path(chunk_id: str, vault_dir: Path) -> Path:
    """The on-disk path for `chunk_id`'s note: the direct `<chunk_id>.md`
    path when it exists (the common case), falling back to
    `axial.paths.chunk_note_path` -- the same naming function
    `axial.vault.write_chunk_note` used -- when it does not, so a note whose
    filename was shortened to fit Windows' MAX_PATH is still reachable by
    its real chunk_id. Returns the direct path unresolved when `chunk_id`
    doesn't even parse (`MalformedChunkIdError`), so a genuinely bad id
    still reports a sensible "expected at" path rather than raising a
    different, unexpected error."""
    direct = vault_dir / "prose" / f"{chunk_id}.md"
    if direct.is_file():
        return direct
    try:
        source_id = source_id_from_chunk_id(chunk_id)
    except MalformedChunkIdError:
        return direct
    return chunk_note_path(vault_dir, source_id, chunk_id)


def _resolve_artifact_path(artifact_id: str, vault_dir: Path) -> Path:
    """The `get_artifact`/`follow_backlinks` counterpart of
    `_resolve_chunk_path` -- same rationale, same contract."""
    direct = vault_dir / "artifacts" / f"{artifact_id}.md"
    if direct.is_file():
        return direct
    source_id = _source_id_from_artifact_id(artifact_id)
    if source_id is None:
        return direct
    return artifact_note_path(vault_dir, source_id, artifact_id)


def query_by_source(source_id: str, *, vault_dir: Path | None = None) -> list[str]:
    """Every chunk_id belonging to `source_id` (§7.5): matched on the
    chunk_id's own embedded `source_id` seam (`source_id_from_chunk_id`),
    not a `source_meta` lookup -- `source_meta` carries no `source_id`
    field (`ChunkNote.source_meta` is `{author, title, date, thesis,
    scope}` only). Results are sorted ascending, the same determinism
    contract as every other tool here."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    matches: list[str] = []
    for path, frontmatter in _iter_chunk_frontmatter(vault_dir):
        chunk_id = _require(frontmatter, path, "chunk_id")
        if source_id_from_chunk_id(chunk_id) == source_id:
            matches.append(chunk_id)
    return sorted(matches)


ENVELOPES_DIR = Path("data/envelopes")


def _default_envelopes_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.envelopes_dir` from `config/pipeline.yaml`, falling back
    to `ENVELOPES_DIR` when the file or key is absent -- a small local
    duplicate of `axial.envelope._default_envelopes_dir`'s own logic (see
    the module docstring for why it is not imported instead)."""
    if not config_path.is_file():
        return ENVELOPES_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("envelopes_dir")
    return Path(configured) if configured else ENVELOPES_DIR


def get_envelope(source_id: str, *, envelopes_dir: Path | None = None) -> Envelope:
    """Fetch one source's envelope by id (§7.5): `thesis`, the nested
    `toc`, `scope`, and `stated_argument`, read straight off
    `<envelopes_dir>/<source_id>.json` (`axial.envelope.write_envelope`'s
    own write side). Raises `EnvelopeNotFoundError`, naming `source_id`,
    when no envelope file exists -- never returns `None`."""
    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir()
    path = Path(envelopes_dir) / f"{source_id}.json"
    if not path.is_file():
        raise EnvelopeNotFoundError(source_id, path)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return Envelope(
        source_id=data.get("source_id", source_id),
        thesis=data["thesis"],
        toc=data["toc"],
        scope=data["scope"],
        stated_argument=data["stated_argument"],
    )


def follow_backlinks(id_: str, *, vault_dir: Path | None = None) -> list[str]:
    """One-hop bidirectional traversal (§7.5): a chunk id resolves to its
    `artifact_refs`; an artifact id resolves to its `cited_by`. Dispatches
    on which kind of note `id_` names, by file existence -- chunk_id and
    artifact_id are both opaque strings, nothing in the id itself says
    which kind it is. Resolution is the same direct-then-budgeted-fallback
    lookup as `get_chunk`/`get_artifact` (`_resolve_chunk_path`/
    `_resolve_artifact_path`), so a budgeted note is reachable here too. An
    empty link list on either side returns `[]`, not an error; only an id
    that resolves to neither a chunk nor an artifact raises
    `BacklinkTargetNotFoundError`. Results are sorted ascending, the same
    determinism contract as every other tool here."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    vault_dir = Path(vault_dir)
    chunk_path = _resolve_chunk_path(id_, vault_dir)
    if chunk_path.is_file():
        return sorted(_parse_chunk_note(chunk_path).artifact_refs)
    artifact_path = _resolve_artifact_path(id_, vault_dir)
    if artifact_path.is_file():
        return sorted(_parse_artifact_note(artifact_path).cited_by)
    raise BacklinkTargetNotFoundError(id_, chunk_path, artifact_path)


def coverage_count(*, vault_dir: Path | None = None) -> dict[str, int]:
    """The count of substantive chunks per polity across the whole vault
    (§7.5; the raw material of the §7.7 coverage map): each chunk counted
    once per *distinct* polity in its own `polities_touched` -- a chunk
    touching two polities counts toward both, never toward only one. A
    vault where no chunk carries `polities_touched` returns `{}`, not an
    error.

    Returned as a plain dict built in ascending-polity-name order -- the
    same explicit-sort determinism contract as every other tool here,
    applied to a mapping instead of a list.

    Backed by the same process-lifetime `_frontmatter_index` cache
    `query_by_tag`/`query_by_polity` use (see that function's docstring)."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    counts: dict[str, int] = {}
    for entry in _frontmatter_index(vault_dir):
        for polity in set(entry.polities_touched):
            counts[polity] = counts.get(polity, 0) + 1
    return {polity: counts[polity] for polity in sorted(counts)}
