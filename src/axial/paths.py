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

from pathlib import Path
from typing import Any

import yaml

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


def _read_configured_dir(config_path: Path, key: str, fallback: Path) -> Path:
    """Read `paths.<key>` from `config_path`, falling back to `fallback`
    when the file or key is absent -- the one config-then-fallback
    resolution every `default_*_dir` helper in this module shares (issue
    #281: a third module independently re-deriving this same read/parse/
    fallback shape is the hazard `axial.paths` exists to close)."""
    if not config_path.is_file():
        return fallback
    with config_path.open("r", encoding="utf-8") as handle:
        document: dict[str, Any] = yaml.safe_load(handle) or {}
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


def default_analyses_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.analyses_dir` from `config_path`, falling back to
    `ANALYSES_DIR` when the file or key is absent."""
    return _read_configured_dir(config_path, "analyses_dir", ANALYSES_DIR)


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


def budgeted_chunk_filename(directory: Path, source_id: str, chunk_id: str) -> str:
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
    "_" is unambiguous."""
    stem, hash12 = split_source_id(source_id)
    _, order_key, slug, index = chunk_id[len(source_id) :].split("_")

    def build(s: str, sl: str) -> str:
        return f"{s}-{hash12}_{order_key}_{sl}_{index}.md"

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
