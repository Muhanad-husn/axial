"""Vault query: the read layer over the tagged Obsidian vault (Phase-B
stage 3, specs/PHASE-B.md §7.5, §8 P0-2).

`src/axial/vault.py` is write-only: it renders notes but never reads them
back. This module is the read side, built from scratch (issue #249, slice
01): a note parser plus the first three of the §7.5 tool set --
`get_chunk`, `get_artifact`, and `query_by_tag`. The rest of the tool set
(`query_by_polity`, `query_by_source`/`get_envelope`, `follow_backlinks`,
`coverage_count`) is a later slice.

LLM-free and embedding-free by construction (§7.5's "no model and no
embedding model"): every path here is pure file I/O, YAML parsing, and
in-memory filtering. Nothing here imports or constructs a provider client.

Read-only by construction (§3 non-goal 5): no function in this module
writes to the vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.vault import _default_vault_dir

# The §7.5 fixed axis filter set for `query_by_tag`: the frontmatter axes a
# conjunction of filters may name. `polity` filters on `empirical_scope`'s
# nested `polity` sub-field, distinct from the `empirical_scope` filter
# itself (which matches on `value`) -- both are listed here, neither is a
# top-level frontmatter key of its own. An unknown key is rejected rather
# than silently matching everything (a typo'd axis must not quietly widen a
# query).
KNOWN_FILTER_KEYS = frozenset(
    {"field", "claim_type", "theory_school", "empirical_scope", "polity", "role_in_argument"}
)


class QueryError(Exception):
    """Base class for all vault-query errors."""


class MalformedNoteError(QueryError):
    """Raised when a note's frontmatter is absent, unterminated, not valid
    YAML, not a mapping, or missing a required field -- always naming the
    offending file, never returning a partially-parsed result."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"malformed vault note at {path}: {reason}")


class ChunkNotFoundError(QueryError):
    """Raised when `get_chunk` is asked for a chunk_id with no note under
    `<vault_dir>/prose/` -- never returns `None` into a caller that will not
    check it."""

    def __init__(self, chunk_id: str, path: Path):
        self.chunk_id = chunk_id
        self.path = path
        super().__init__(f"no chunk note found for chunk_id {chunk_id!r} (expected at {path})")


class ArtifactNotFoundError(QueryError):
    """Raised when `get_artifact` is asked for an artifact_id with no note
    under `<vault_dir>/artifacts/` -- never returns `None`."""

    def __init__(self, artifact_id: str, path: Path):
        self.artifact_id = artifact_id
        self.path = path
        super().__init__(
            f"no artifact note found for artifact_id {artifact_id!r} (expected at {path})"
        )


class UnknownFilterError(QueryError):
    """Raised when `query_by_tag` is called with a filter key outside
    KNOWN_FILTER_KEYS -- a typo'd axis must not quietly widen a query into
    matching everything."""

    def __init__(self, unknown_keys: set[str]):
        self.unknown_keys = unknown_keys
        super().__init__(
            f"unknown query_by_tag filter key(s) {sorted(unknown_keys)!r}; "
            f"expected only {sorted(KNOWN_FILTER_KEYS)!r}"
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
        vault_dir = _default_vault_dir()
    path = Path(vault_dir) / "prose" / f"{chunk_id}.md"
    if not path.is_file():
        raise ChunkNotFoundError(chunk_id, path)
    return _parse_chunk_note(path)


def get_artifact(artifact_id: str, vault_dir: Path | None = None) -> ArtifactNote:
    """Fetch one artifact note by id (§7.5). Raises `ArtifactNotFoundError`,
    naming `artifact_id`, when no note exists -- never returns `None`."""
    if vault_dir is None:
        vault_dir = _default_vault_dir()
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
    # A note whose empirical_scope.polity is null (a cross-case/comparative
    # note) never matches a polity filter -- `None == filter_value` is
    # already False for any non-null filter_value, so no extra guard is
    # needed here.
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


def query_by_tag(vault_dir: Path | None = None, **filters: str) -> list[str]:
    """Every chunk_id whose prose note satisfies the **conjunction** of the
    given tag-axis filters (§7.5): `field`, `claim_type` (incl. subtags),
    `empirical_scope` (incl. `polity`), `role_in_argument`, `theory_school`.
    A filter set no note satisfies returns `[]`, not an error; an unknown
    filter key raises `UnknownFilterError` instead of silently matching
    everything.

    Results are sorted by `chunk_id` (§7.5's determinism contract) --
    directory iteration order is filesystem/OS-dependent and MUST NOT leak
    into the result order."""
    unknown_keys = set(filters) - KNOWN_FILTER_KEYS
    if unknown_keys:
        raise UnknownFilterError(unknown_keys)

    if vault_dir is None:
        vault_dir = _default_vault_dir()
    prose_dir = Path(vault_dir) / "prose"

    matches: list[str] = []
    if prose_dir.is_dir():
        for path in prose_dir.iterdir():
            if path.suffix != ".md":
                continue
            frontmatter, _body = _read_frontmatter(path)
            if all(_FILTER_MATCHERS[name](frontmatter, value) for name, value in filters.items()):
                matches.append(frontmatter.get("chunk_id", path.stem))

    return sorted(matches)
