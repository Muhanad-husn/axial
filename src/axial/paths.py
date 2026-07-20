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
(`axial.gold`, `axial.polity_canonical`) are unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Mirrors `axial.llm.DEFAULT_PIPELINE_CONFIG_PATH`'s value exactly, kept as
# its own literal rather than imported from `axial.llm` -- which pulls in
# `httpx` -- so this module stays import-light.
DEFAULT_PIPELINE_CONFIG_PATH = Path("config/pipeline.yaml")

VAULT_DIR = Path("data/vault")


def default_vault_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.vault_dir` from `config_path`, falling back to
    `VAULT_DIR` when the file or key is absent."""
    if not config_path.is_file():
        return VAULT_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document: dict[str, Any] = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("vault_dir")
    return Path(configured) if configured else VAULT_DIR
