"""Dependency-light filesystem path resolution for `data/`'s pipeline
directories (PRD §5/§7).

A slice that only needs to know *where* a pipeline directory lives on disk
should not have to import the write-side orchestration stack to find out.
`axial.vault`, for instance, pulls in `axial.artifacts`, `axial.envelope`,
`axial.tag`, `axial.xref`, and `axial.llm` -- and transitively `docling`,
`pypdf`, `python-docx`, `httpx` -- to define one config-lookup helper
(issue #249 F1, measured at ~1s of import cost for query_by_tag's own
10-line need). This module holds that helper instead, importing only
`pathlib` and `yaml`. `axial.vault` re-exports `VAULT_DIR` /
`_default_vault_dir` from here unchanged, so its existing callers
(`axial.gold`, `axial.polity_canonical`) are unaffected. `axial.eval.
corpus_pin` imports `default_sources_dir` the same way (issue #281 --
`_default_sources_dir` had independently re-derived this module's own
config-then-fallback resolution rather than reusing it).

`DEFAULT_PIPELINE_CONFIG_PATH` is owned here, not in `axial.llm` (issue
#249 finding 1): `axial.llm` imports and re-exports it under its original
name, so its eleven existing callers are unaffected, and there is a single
source of truth instead of two literals that happen to agree today.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
from pathlib import Path
from typing import Any

import yaml

from axial.yaml_loader import SAFE_LOADER

DEFAULT_PIPELINE_CONFIG_PATH = Path("config/pipeline.yaml")

VAULT_DIR = Path("data/vault")

# The default location of the raw ingested source files (the "durable
# operator convention" docs/postmortem/gold-run-2026-07/canary-run-runbook.md
# describes -- ingestion reads from here, and operators keep it around
# across runs).
SOURCES_DIR = Path("data/sources")

# The default location of Phase-B analysis records, one JSON per brief run,
# `<brief_id>.json` (specs/PHASE-B.md §7.3). Issue #252 slice 01 persists
# only the §7.2 interrogation result here, ahead of the full record.
ANALYSES_DIR = Path("data/analyses")

# The default location of Phase-B run reports, one JSON per brief run,
# `<brief_id>.json` (specs/PHASE-B.md §7.15, §8 P0-14). A separate artifact
# from the record above rather than a field on it: §7.3's record shape is
# locked and the report is a derived view of it.
RUNS_DIR = Path("data/runs")

# The default domain config directory (PRD §7.1). Lived on `axial.tag`
# (retired, issue #414) before that; every caller that only needed the bare
# constant -- never `axial.tag`'s tagging machinery -- now reaches it here
# instead of duplicating the literal.
DEFAULT_DOMAIN_DIR = Path("config/domains/syria")


# The parsed pipeline config, per file, for the process lifetime -- the same
# shape as `axial.query.names._NAME_LAYER_CACHE` and
# `axial.query.reader._CHUNK_ID_INDEX_CACHE`. Without it every
# `default_*_dir()` call re-read and re-parsed the whole 26.6KB
# `config/pipeline.yaml` (28.7ms a call, measured), and
# `canonical_name_for_surface` resolves `default_names_dir()` per surface per
# pair -- ~4,000 times inside one counter-position check (issue #541).
#
# Keyed on the ABSOLUTE path, because `DEFAULT_PIPELINE_CONFIG_PATH` is
# relative and several suites `monkeypatch.chdir` inside one process, plus
# (mtime, size) so an edited config is noticed rather than needing a reset
# hook the product would have to remember to call. That is the same
# staleness check CPython's own bytecode cache uses, and it inherits the same
# limit: on Windows the filesystem clock ticks every ~15.6ms, so an edit that
# leaves the byte count unchanged AND lands within one tick of the previous
# read is not seen. Nothing operational edits this file mid-process.
_CONFIG_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_CONFIG_CACHE_LOCK = threading.Lock()


def _load_pipeline_config(config_path: Path) -> dict[str, Any] | None:
    """`config_path`, parsed and memoized. `None` when it is not a readable
    regular file. The returned mapping is shared between callers -- read it,
    never mutate it."""
    key = os.path.abspath(config_path)
    try:
        info = os.stat(key)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    stamp = (info.st_mtime_ns, info.st_size)

    cached = _CONFIG_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    with _CONFIG_CACHE_LOCK:
        cached = _CONFIG_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        with open(key, "r", encoding="utf-8") as handle:
            parsed = yaml.load(handle, Loader=SAFE_LOADER)
        document: dict[str, Any] = parsed if isinstance(parsed, dict) else {}
        _CONFIG_CACHE[key] = (stamp, document)
        return document


def _read_configured_dir(config_path: Path, key: str, fallback: Path) -> Path:
    """Read `paths.<key>` from `config_path`, falling back to `fallback`
    when the file or key is absent -- the one config-then-fallback
    resolution every `default_*_dir` helper in this module shares (issue
    #281: a third module independently re-deriving this same read/parse/
    fallback shape is the hazard `axial.paths` exists to close)."""
    document = _load_pipeline_config(config_path)
    if document is None:
        return fallback
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get(key)
    return Path(configured) if configured else fallback


def default_vault_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.vault_dir` from `config_path`, falling back to
    `VAULT_DIR` when the file or key is absent."""
    return _read_configured_dir(config_path, "vault_dir", VAULT_DIR)


def default_sources_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.sources_dir` from `config_path`, falling back to
    `SOURCES_DIR` when the file or key is absent."""
    return _read_configured_dir(config_path, "sources_dir", SOURCES_DIR)


# The default location of the name layer (§7.16): `index.json`,
# `alias_map.json`, `disagreements.jsonl` -- retrieval substrate, and (issue
# #486, specs/PHASE-B.md §7.12, D6) part of what the corpus-pin manifest's
# `vault_snapshot_hash` covers. `axial.names`/`axial.merge_names`/
# `axial.gather` each already assume this same literal for their own default
# path constants; this module doesn't import any of them (their own import
# chains pull in the LLM/clustering stack this dependency-light module
# exists to avoid -- see the module docstring), so the value is repeated
# here rather than re-exported, the same way `axial.reconcile`/`axial.run`
# already repeat `SOURCES_DIR`'s own literal.
NAMES_DIR = Path("data/names")


def default_names_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.names_dir` from `config_path`, falling back to
    `NAMES_DIR` when the file or key is absent."""
    return _read_configured_dir(config_path, "names_dir", NAMES_DIR)


def default_analyses_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.analyses_dir` from `config_path`, falling back to
    `ANALYSES_DIR` when the file or key is absent."""
    return _read_configured_dir(config_path, "analyses_dir", ANALYSES_DIR)


def default_runs_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.runs_dir` from `config_path`, falling back to `RUNS_DIR`
    when the file or key is absent."""
    return _read_configured_dir(config_path, "runs_dir", RUNS_DIR)


# The default location of the argument map (issue #572): one pin directory
# per corpus content hash, each holding positions.jsonl, map.json, and the
# reads.jsonl resume ledger.
MAP_DIR = Path("data/map")


def default_map_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.map_dir` from `config_path`, falling back to `MAP_DIR`
    when the file or key is absent."""
    return _read_configured_dir(config_path, "map_dir", MAP_DIR)


# =============================================================================
# Note filename budgeting -- shared by `axial.vault` (the writer) and
# `axial.query.reader` (the reader).
#
# A note's on-disk filename is `<chunk_id>.md`/`<artifact_id>.md` verbatim
# whenever the resulting absolute path fits Windows' documented MAX_PATH
# (260 characters); PR #377 found a real 31-source ingestion rerun losing
# 165/484 and 59/483 notes of two long-titled sources to `FileNotFoundError`
# from oversized paths and added the shortened-filename fallback below.
# `chunk_id`/`artifact_id` themselves are NEVER touched by this -- only the
# filename on disk.
#
# This lives here, not in `axial.vault`, so the read side
# (`axial.query.reader`) can resolve a note's real on-disk path without
# importing `axial.vault`'s LLM-backed write stack (mirrors this module's
# own rationale above) -- and so there is exactly one copy of the budgeting
# rule, not a writer copy and an independently-reasoned reader copy (the
# long-chunk-id grounds-resolution bug: a filename got shortened at write
# time, and the reader assumed filename == id and could never find the note
# again by its real, correct chunk_id).

_WINDOWS_MAX_PATH = 260

# Slack reserved below `_WINDOWS_MAX_PATH`: one char for the path separator
# between the directory and the filename, plus a few chars of rounding
# safety. The directory portion itself (`vault_dir` resolved to its real
# absolute path, plus "prose"/"artifacts") is measured for real at call
# time below, never guessed -- so this margin is the only guessed constant
# in the budget, and it is small on purpose.
_PATH_SAFETY_MARGIN = 10


def path_overage(directory: Path, filename: str) -> int:
    """How many characters `<directory>/<filename>`'s absolute path is over
    budget (`_WINDOWS_MAX_PATH` minus `_PATH_SAFETY_MARGIN`); zero or
    negative means it fits."""
    return (
        len(str(directory.resolve()))
        + 1
        + len(filename)
        - (_WINDOWS_MAX_PATH - _PATH_SAFETY_MARGIN)
    )


def split_source_id(source_id: str) -> tuple[str, str]:
    """Split `source_id` (`axial.envelope.compute_source_id`'s
    `<stem>-<hash12>`) into its human-readable stem and its trailing
    12-hex-char content hash -- the only two pieces a note filename ever
    needs to tell apart, since the hash is source_id's own uniqueness
    guarantee and the stem is purely for humans."""
    hash12 = source_id[-12:]
    stem = source_id[: -(len(hash12) + 1)]
    return stem, hash12


def _shrink_pieces(pieces: list[str], overage: int) -> list[str]:
    """Trim `overage` characters off `pieces`, in order, each piece down to
    empty before the next is touched -- used to shave a note filename's
    purely-human-readable components (the source stem, then the section
    slug) down to budget. The small, uniqueness-bearing components (the
    content-hash suffix, the section order, the per-section chunk index)
    are never passed in here at all, so they can never be shortened."""
    shrunk = []
    for piece in pieces:
        if overage <= 0:
            shrunk.append(piece)
            continue
        take = min(overage, len(piece))
        shrunk.append(piece[: len(piece) - take])
        overage -= take
    return shrunk


def budgeted_chunk_filename(
    directory: Path, source_id: str, chunk_id: str, extension: str = ".md"
) -> str:
    """Shorten `chunk_id`'s note filename to fit under `directory`'s path
    budget, touching only `source_id`'s readable stem prefix and (if that
    alone is not enough) the section slug -- never the hash suffix, the
    section order, or the per-section index, which is where chunk_id's own
    on-disk uniqueness lives (`axial.chunk.build_chunk_records`). Relies on
    `chunk_id`'s locked grammar (`<source_id>_<order_key>_<slug>_<NNN>`,
    PRD §7.7): `order_key` and `slug` are guaranteed underscore-free
    (`axial.chunk._slugify` maps every non-alphanumeric run, including
    underscores, to a single hyphen; `order_key` is `section_order` with
    "." replaced by "-"), so splitting the `source_id`-stripped suffix on
    "_" is unambiguous.

    `extension` defaults to `.md` (the vault note case, via
    `chunk_note_path`); `axial.gold.run_gold_sample` passes `.json` for its
    chunk records, which live under a different directory and format but
    share the exact same oversized-source_id problem."""
    stem, hash12 = split_source_id(source_id)
    _, order_key, slug, index = chunk_id[len(source_id) :].split("_")

    def build(s: str, sl: str) -> str:
        return f"{s}-{hash12}_{order_key}_{sl}_{index}{extension}"

    filename = build(stem, slug)
    overage = path_overage(directory, filename)
    if overage > 0:
        stem, slug = _shrink_pieces([stem, slug], overage)
        filename = build(stem, slug)
    return filename


def budgeted_artifact_filename(directory: Path, source_id: str, artifact_id: str) -> str:
    """Shorten `artifact_id`'s note filename to fit under `directory`'s
    path budget, touching only `source_id`'s readable stem prefix -- never
    the hash suffix or the artifact's own dotted order
    (`axial.artifacts.artifact_id_for_node`'s `<source_id>_art_<order>`),
    which is where artifact_id's on-disk uniqueness lives."""
    stem, hash12 = split_source_id(source_id)
    suffix = artifact_id[len(source_id) :]

    def build(s: str) -> str:
        return f"{s}-{hash12}{suffix}.md"

    filename = build(stem)
    overage = path_overage(directory, filename)
    if overage > 0:
        (stem,) = _shrink_pieces([stem], overage)
        filename = build(stem)
    return filename


def chunk_note_path(vault_dir: Path, source_id: str, chunk_id: str) -> Path:
    """The on-disk path for `chunk_id`'s note. The filename is `chunk_id`
    verbatim whenever the resulting absolute path fits Windows' MAX_PATH
    budget (the common case) -- only a source whose readable stem/slug
    combination would push the path over budget gets its filename
    shortened, via `budgeted_chunk_filename`; `chunk_id` itself (used
    everywhere else: tag records, xref pairs, this note's own frontmatter)
    is never touched. This is the SAME function both the writer
    (`axial.vault.write_chunk_note`) and the reader
    (`axial.query.reader.get_chunk`) call -- there is no second, independently
    -reasoned copy of this rule."""
    directory = Path(vault_dir) / "prose"
    filename = f"{chunk_id}.md"
    if path_overage(directory, filename) > 0:
        filename = budgeted_chunk_filename(directory, source_id, chunk_id)
    return directory / filename


def artifact_note_path(vault_dir: Path, source_id: str, artifact_id: str) -> Path:
    """The on-disk path for `artifact_id`'s note -- `artifact_id` verbatim
    whenever the path fits Windows' MAX_PATH budget (the common case),
    mirroring `chunk_note_path`'s filename-only fallback for the rare
    oversized case (`budgeted_artifact_filename`). The same function both
    `axial.vault.write_artifact_note` and `axial.query.reader.get_artifact`
    call."""
    directory = Path(vault_dir) / "artifacts"
    filename = f"{artifact_id}.md"
    if path_overage(directory, filename) > 0:
        filename = budgeted_artifact_filename(directory, source_id, artifact_id)
    return directory / filename


# =============================================================================
# Name-page filenames (issue #411, Materialize) -- a canonical name, unlike
# `chunk_id`/`artifact_id`, carries no built-in unique suffix (no source_id,
# no dotted order) to fall back on, so this budgets AND de-duplicates in one
# helper rather than reusing `budgeted_chunk_filename`'s shrink-only shape.

# Characters Windows forbids in a filename, plus C0 control characters.
# Real corpus names carry '/' routinely (`country/state/place`-joined kinds
# land in `kind`, not `name`, but a name itself can still read like
# "Israel/Palestine") and colons, quotes and the rest are common in titles
# and citations -- each is replaced with '-', never dropped silently.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_name_filename(name: str) -> str:
    """A canonical name, made safe as a bare filename stem: illegal
    characters replaced with '-', trailing dots/spaces stripped (both
    forbidden by Windows), never emptied entirely."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("-", name).strip().rstrip(". ")
    return cleaned or "unnamed"


def name_page_filename(directory: Path, canonical: str, used: set[str] | None = None) -> str:
    """The on-disk filename for `canonical`'s name page: the sanitized name
    verbatim (`.md`) whenever it BOTH fits Windows' MAX_PATH budget under
    `directory` AND -- when `used` is given -- is not already claimed by an
    earlier name this same run processed.

    The second condition exists because a bare canonical name, unlike
    `chunk_id`/`artifact_id`, carries no unique id of its own: two different
    canonical names can sanitize to the identical filename (an illegal
    character folded to the same '-', or two names differing only by case,
    which Windows filenames treat as the same file). Either failure falls
    back to the sanitized name plus an 8-hex-char content hash of the FULL
    canonical string -- shrinking the sanitized part first, same as
    `budgeted_chunk_filename`, only if that combination is itself over
    budget -- which only collides on an actual hash collision.

    `used`, when given, is a case-folded set of filenames already claimed
    this run and is updated in place with whichever filename this call
    returns. A caller processing a whole node set in one deterministic
    order (sorted by canonical) gets a stable, collision-free filename set
    across repeated runs over unchanged input."""
    base = _sanitize_name_filename(canonical)
    filename = f"{base}.md"
    collides = used is not None and filename.casefold() in used
    if not collides and path_overage(directory, filename) <= 0:
        if used is not None:
            used.add(filename.casefold())
        return filename

    hash8 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    suffix = f"-{hash8}.md"
    overage = path_overage(directory, base + suffix)
    if overage > 0:
        (base,) = _shrink_pieces([base], overage)
    filename = base + suffix
    if used is not None:
        used.add(filename.casefold())
    return filename


def name_page_path(vault_dir: Path, canonical: str, used: set[str] | None = None) -> Path:
    """The on-disk path for `canonical`'s name page (§7.17):
    `<vault_dir>/names/<budgeted filename>.md`. See `name_page_filename`."""
    directory = Path(vault_dir) / "names"
    return directory / name_page_filename(directory, canonical, used)
