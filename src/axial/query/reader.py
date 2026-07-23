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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_vault_dir

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
    absence."""

    artifact_id: str
    artifact_role: str
    field: dict[str, Any]
    source_id: str
    section: str
    retrievable: bool
    cited_by: list[str]
    caption: str | None = None


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
        artifact_role=_require(frontmatter, path, "artifact_role"),
        field=_require(frontmatter, path, "field"),
        source_id=_require(frontmatter, path, "source_id"),
        section=_require(frontmatter, path, "section"),
        retrievable=_require(frontmatter, path, "retrievable"),
        cited_by=list(frontmatter.get("cited_by") or []),
        caption=frontmatter.get("caption"),
    )


def get_chunk(chunk_id: str, vault_dir: Path | None = None) -> ChunkNote:
    """Fetch one prose note by id (§7.5). Raises `ChunkNotFoundError`,
    naming `chunk_id`, when no note exists -- never returns `None`."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    path = Path(vault_dir) / "prose" / f"{chunk_id}.md"
    if not path.is_file():
        raise ChunkNotFoundError(chunk_id, path)
    return _parse_chunk_note(path)


def get_artifact(artifact_id: str, vault_dir: Path | None = None) -> ArtifactNote:
    """Fetch one artifact note by id (§7.5). Raises `ArtifactNotFoundError`,
    naming `artifact_id`, when no note exists -- never returns `None`."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    path = Path(vault_dir) / "artifacts" / f"{artifact_id}.md"
    if not path.is_file():
        raise ArtifactNotFoundError(artifact_id, path)
    return _parse_artifact_note(path)


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
    into the result order."""
    unknown_keys = set(filters) - KNOWN_FILTER_KEYS
    if unknown_keys:
        raise UnknownFilterError(unknown_keys)

    if vault_dir is None:
        vault_dir = default_vault_dir()
    prose_dir = Path(vault_dir) / "prose"
    if not prose_dir.is_dir():
        raise MissingVaultDirError(prose_dir)

    matches: list[str] = []
    for path in prose_dir.iterdir():
        if path.suffix != ".md":
            continue
        frontmatter, _body = _read_frontmatter(path)
        chunk_id = _require(frontmatter, path, "chunk_id")
        if all(_FILTER_MATCHERS[name](frontmatter, value) for name, value in filters.items()):
            matches.append(chunk_id)

    return sorted(matches)


# =============================================================================
# Slice 02 (issue #251): query_by_polity, query_by_source / get_envelope,
# follow_backlinks, coverage_count
# =============================================================================


def _iter_chunk_frontmatter(vault_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every `<vault_dir>/prose/*.md` note's `(path, frontmatter)`,
    unsorted -- every caller here sorts its own derived result, so this
    shared scan need not (and directory order is filesystem/OS-dependent
    regardless). Raises `MissingVaultDirError` when `prose/` itself is
    absent, the same rule `query_by_tag` already enforces: a missing or
    typo'd `vault_dir` is a caller bug, not an empty corpus."""
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
    `query_by_tag`."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    matches: list[str] = []
    for path, frontmatter in _iter_chunk_frontmatter(vault_dir):
        touched = frontmatter.get("polities_touched") or []
        if polity in touched:
            matches.append(_require(frontmatter, path, "chunk_id"))
    return sorted(matches)


def _source_id_from_chunk_id(chunk_id: str) -> str:
    """The `source_id` seam within a chunk_id
    (`<source_id>_<section_order>_<section_slug>_<NNN>`,
    `axial.chunk.build_chunk_records`). The three trailing `_`-delimited
    segments never themselves contain a `_`: `section_order` has its dots
    replaced with hyphens, `section_slug` is hyphen-slugified
    (`axial.chunk._slugify`, `[^a-z0-9]+` -> `-`), and `NNN` is a bare
    zero-padded index -- so `source_id` is exactly everything before the
    last three `_`-delimited segments. Raises `MalformedChunkIdError` when
    `chunk_id` has fewer than four `_`-delimited segments to split."""
    parts = chunk_id.rsplit("_", 3)
    if len(parts) != 4 or not parts[0]:
        raise MalformedChunkIdError(chunk_id)
    return parts[0]


def query_by_source(source_id: str, *, vault_dir: Path | None = None) -> list[str]:
    """Every chunk_id belonging to `source_id` (§7.5): matched on the
    chunk_id's own embedded `source_id` seam (`_source_id_from_chunk_id`),
    not a `source_meta` lookup -- `source_meta` carries no `source_id`
    field (`ChunkNote.source_meta` is `{author, title, date, thesis,
    scope}` only). Results are sorted ascending, the same determinism
    contract as every other tool here."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    matches: list[str] = []
    for path, frontmatter in _iter_chunk_frontmatter(vault_dir):
        chunk_id = _require(frontmatter, path, "chunk_id")
        if _source_id_from_chunk_id(chunk_id) == source_id:
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
    which kind it is. An empty link list on either side returns `[]`, not
    an error; only an id that resolves to neither a chunk nor an artifact
    raises `BacklinkTargetNotFoundError`. Results are sorted ascending, the
    same determinism contract as every other tool here."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    vault_dir = Path(vault_dir)
    chunk_path = vault_dir / "prose" / f"{id_}.md"
    if chunk_path.is_file():
        return sorted(_parse_chunk_note(chunk_path).artifact_refs)
    artifact_path = vault_dir / "artifacts" / f"{id_}.md"
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
    applied to a mapping instead of a list."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    counts: dict[str, int] = {}
    for _path, frontmatter in _iter_chunk_frontmatter(vault_dir):
        touched = frontmatter.get("polities_touched") or []
        for polity in set(touched):
            counts[polity] = counts.get(polity, 0) + 1
    return {polity: counts[polity] for polity in sorted(counts)}
