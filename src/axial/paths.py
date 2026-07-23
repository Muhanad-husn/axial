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
