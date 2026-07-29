"""Vault query: the read layer over the Obsidian vault's notes (Phase-B
stage 3, specs/PHASE-B.md §7.5, §8 P0-2).

`src/axial/vault.py` is write-only: it renders notes but never reads them
back. This module is the read side, for the tools that take an id the caller
already holds: `get_chunk`, `get_artifact`, `query_by_source` /
`get_envelope`, plus `all_chunk_ids` and the two suffix-repair lookups.
Finding a name, and everything reachable from one, is `axial.query.names`.

`query_by_tag`, `query_by_polity` and `follow_backlinks` lived here until
Phase B v1 slice 02 (issue #487, D1/D5) and are deleted, not repaired: the
facets they filtered (`field`, `claim_type`, `theory_school`,
`role_in_argument`, `empirical_scope`, `polities_touched`, `artifact_refs`,
`cited_by`) were retired with the tag and cross-reference passes, so each
returned 0 or `[]` on every call against the v1 vault. A tool that silently
returns nothing is worse than one that is absent: the caller cannot tell "no
results" from "this axis no longer exists".

LLM-free by construction (§7.5's "zero LLM calls"): every path here is pure
file I/O, YAML/JSON parsing, and
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

# Aliased: `ChunkNote` has a (retired, still-readable) field literally named
# `field`, which would shadow the dataclasses helper inside the class body.
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

import yaml

from axial.paths import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    artifact_note_path,
    chunk_note_path,
    default_vault_dir,
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


class MissingVaultDirError(QueryError):
    """A whole-vault scan's `<vault_dir>/prose/` does not exist -- a missing
    or typo'd vault_dir is a caller bug, not an empty corpus, so it raises
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


@dataclass(frozen=True)
class ChunkNote:
    """One parsed prose note (`<vault_dir>/prose/<chunk_id>.md`): its id,
    text, `source_meta`, and the interrogation's own answer block
    (`specs/PRODUCT.md` §7.15, Appendix H), which is what a note's
    frontmatter carries in place of the retired tag axes.

    `claim`/`move`/`position_of`/`position`/`arguing_against`/`names`/
    `citations` are read out of the frontmatter's nested `answers` mapping
    (issue #487): they are what `axial.query.names`' traversals and Phase B's
    synthesis read, so the general-purpose note reader exposes them directly
    rather than making every caller re-dig into `answers`. A note that carries
    no `answers` block at all still parses, with all of them at their defaults
    -- a note written before issue #411, or one whose interrogation abstained,
    is not a malformed note.

    **`position_of` and `position` are a mixed frame, and both are exposed
    raw** (§7.5/§7.15, issue #496): frame 0.2 split "whose position is this?"
    (`position_of`) from "what is the position?" (`position`), a note
    interrogated before it carries only the former, a note interrogated after
    carries both, and no re-run is planned. A consumer wanting the stated
    position reads `position` when that KEY IS PRESENT and falls back to
    `position_of` otherwise -- key presence, never truthiness, and never
    `frame_version`. This reader deliberately does not resolve that for the
    caller: it reports what the note carries, and `absent key` is information
    a resolved single field would destroy. `axial.query.names.
    who_argues_against` applies the rule and returns the resolved `position`;
    it is the worked example.

    `polities_touched`/`artifact_refs` and the `schema_version`/
    `role_in_argument`/`field`/`claim_type`/`theory_school`/
    `empirical_scope` block are all retired (issues #414/#487, D4/D9/D1): a
    note `axial.materialize` wrote carries none of them, so every one of them
    defaults rather than being required -- the same "keep it compiling with
    the smallest honest change" treatment issue #429 gave `ArtifactNote`'s own
    retired `artifact_role`/`field`. They stay readable because an OLDER note
    still carries them and `axial.analyze.assembly` still reads
    `polities_touched`."""

    chunk_id: str
    section: str
    chunk_text: str
    source_meta: dict[str, Any]
    claim: str | None = None
    move: str | None = None
    position_of: str | None = None
    position: str | None = None
    arguing_against: list[Any] = dataclass_field(default_factory=list)
    names: list[Any] = dataclass_field(default_factory=list)
    citations: list[Any] = dataclass_field(default_factory=list)
    polities_touched: list[str] = dataclass_field(default_factory=list)
    artifact_refs: list[str] = dataclass_field(default_factory=list)
    schema_version: str | None = None
    role_in_argument: str | None = None
    field: dict[str, Any] | None = None
    claim_type: dict[str, Any] | None = None
    theory_school: dict[str, Any] | None = None
    empirical_scope: dict[str, Any] | None = None


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
    # The interrogation answer block (issue #487, `specs/PRODUCT.md` §7.15):
    # nested under `answers`, absent entirely on a note written before issue
    # #411, so read with `.get()` and never `_require`.
    answers = frontmatter.get("answers")
    if not isinstance(answers, dict):
        answers = {}
    arguing_against = answers.get("arguing_against")
    return ChunkNote(
        chunk_id=_require(frontmatter, path, "chunk_id"),
        section=_require(frontmatter, path, "section"),
        chunk_text=_require(frontmatter, path, "chunk_text"),
        source_meta=_require(frontmatter, path, "source_meta"),
        claim=answers.get("claim"),
        move=answers.get("move"),
        # Both halves of issue #496's mixed frame, raw: a note carrying no
        # `position` key reads `None` here exactly as one answering
        # `position: null` does, so a consumer that needs to tell them apart
        # checks the block itself. See `ChunkNote`'s own docstring.
        position_of=answers.get("position_of"),
        position=answers.get("position"),
        # A list on every real note, but nothing enforces that on a free-text
        # answer, so a bare string reads as a one-item list rather than being
        # silently dropped (`axial.query.names.as_string_list`'s own rule).
        arguing_against=[arguing_against]
        if isinstance(arguing_against, str)
        else list(arguing_against or []),
        names=list(answers.get("names") or []),
        citations=list(answers.get("citations") or []),
        polities_touched=list(frontmatter.get("polities_touched") or []),
        artifact_refs=list(frontmatter.get("artifact_refs") or []),
        # The retired axis block (issue #414): present, required, on a
        # pre-#411 note; absent entirely on a note `axial.materialize`
        # wrote. `.get()`, never `_require`, so a v1 note parses instead of
        # raising `MalformedNoteError` on a field the pipeline stopped
        # writing (see `ChunkNote`'s own docstring).
        schema_version=frontmatter.get("schema_version"),
        role_in_argument=frontmatter.get("role_in_argument"),
        field=frontmatter.get("field"),
        claim_type=frontmatter.get("claim_type"),
        theory_school=frontmatter.get("theory_school"),
        empirical_scope=frontmatter.get("empirical_scope"),
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


def _iter_chunk_frontmatter(vault_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every `<vault_dir>/prose/*.md` note's full `(path, frontmatter)`,
    unsorted -- every caller here sorts its own derived result, so this
    shared scan need not (and directory order is filesystem/OS-dependent
    regardless). Raises `MissingVaultDirError` when `prose/` itself is
    absent: a missing or typo'd `vault_dir` is a caller bug, not an empty
    corpus.

    Deliberately uncached. Its callers here (`query_by_source`,
    `all_chunk_ids`) only ever scan a vault once per process, and
    `axial.distill.embed`/`axial.distill.classify` also import this exact
    private function for their own one-shot, whole-corpus reads and need the
    FULL frontmatter dict, including `chunk_text`. A cache over that would
    hold a full-text copy of every note (~6,150 on the real corpus) for a
    speed win no caller here repeats often enough to need -- the repeatedly-
    hit scans are the name layer's, and `axial.query.names` keeps its own
    lean, cached projections for them."""
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
    """The `get_artifact` counterpart of `_resolve_chunk_path` -- same
    rationale, same contract."""
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


def all_chunk_ids(*, vault_dir: Path | None = None) -> list[str]:
    """Every prose note's `chunk_id` under `vault_dir`, ascending.

    This is the one capability `query_by_tag` had that outlived it: called
    with no filters it meant "every prose id in `chunk_id` order", which
    `axial.answer.record.vault_schema_version` uses to read the vault's own
    schema version off its first note. The tag filters are deleted (issue
    #487, D1); the enumeration is not, so it keeps its own honest name.

    Raises `MalformedNoteError` on a note carrying no `chunk_id` -- every
    note under `prose/` must have one to be enumerable at all, so every id
    returned resolves back through `get_chunk` -- and `MissingVaultDirError`
    when `prose/` itself is absent."""
    if vault_dir is None:
        vault_dir = default_vault_dir()
    return sorted(
        _require(frontmatter, path, "chunk_id")
        for path, frontmatter in _iter_chunk_frontmatter(vault_dir)
    )


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
