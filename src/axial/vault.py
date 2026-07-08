"""Vault write: persists tagged prose chunks as Obsidian notes under
`data/vault/prose/` (PRD §5 stage 7, prose half only; backlinks and the
artifact pool are out of scope for this slice -- see
plans/minimal-ingestion/06-vault-write.md and plans/tag/04-tag-vault-frontmatter.md).

This pass runs the tagging pass itself, internally, via `axial.tag.run_tag`
-- exactly as `axial tag` does, which itself runs the argumentative-chunking
pass internally -- so chunk_id/section/chunk_text provenance and every axis
tag are computed exactly once, in tag.py (never reimplemented here). This
pass also reuses `axial.envelope.compute_source_id`/`envelope_path`/
`_default_envelopes_dir` to locate and read the source's stored envelope
(never recomputing it, PRD §10 "no recompute"). If no stored envelope
exists yet, this pass raises a typed error telling the caller to run `axial
envelope` first, mirroring `axial.chunk`'s `MissingEnvelopeError`.

Each chunk is written to its own note at `<vault_dir>/prose/<chunk_id>.md`,
opening with a `---`-delimited YAML frontmatter block (PyYAML `safe_dump`)
carrying `chunk_id`, `section`, `chunk_text`, a `source_meta` mapping
(`author`, `title`, `date`, `thesis`, `scope`) reused verbatim from the
envelope, and the chunk-level axis block (`schema_version`,
`role_in_argument`, `field`, `claim_type`, `theory_school`,
`empirical_scope`) carried through from the tagged record and reshaped to
match Appendix H's nesting (PRD §7.2), followed by a readable body
containing the chunk text.

The artifact pool (`<vault_dir>/artifacts/`) is a separate surface and
receives nothing from this pass (PRD §8 P0-8).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
    envelope_path,
    _default_envelopes_dir,
)
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.tag import TagError, run_tag

# Source-level fields reused verbatim from the envelope (PRD §7.2), excluding
# `fields`, a schema-driven axis tag deferred to phase-3 tagging.
SOURCE_META_FIELDS = ("author", "title", "date", "thesis", "scope")

VAULT_DIR = Path("data/vault")


class VaultError(Exception):
    """Base class for all vault-write errors."""


class MissingSourceError(VaultError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, cause: _EnvelopeMissingSourceError):
        self.cause = cause
        super().__init__(str(cause))


class MissingEnvelopeError(VaultError):
    """Raised when no stored envelope exists yet for the source (PRD §7.3,
    "produced once in stage 3; consumed by stages 4 and 6") -- vault write
    never recomputes one; the caller must run `axial envelope` first."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no stored envelope found at {path}; run `axial envelope` on the source first"
        )


class TaggingFailedError(VaultError):
    """Raised when the underlying tagging pass (`axial.tag.run_tag`, which
    itself runs the chunker internally) fails, so the CLI renders a clean
    `error: ...` instead of a bare traceback (mirrors the pre-slice-04
    `ChunkingFailedError` wrapping pattern, one level up the composition)."""

    def __init__(self, cause: TagError):
        self.cause = cause
        super().__init__(str(cause))


def _default_vault_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.vault_dir` from `config/pipeline.yaml` (mirrors
    `axial.envelope._default_envelopes_dir`), falling back to `VAULT_DIR`
    when the file/key is absent."""
    if not config_path.is_file():
        return VAULT_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("vault_dir")
    return Path(configured) if configured else VAULT_DIR


# Axis blocks carried through verbatim from the tagged record's own nested
# shape (issue #29 slice 03), which already matches Appendix H's illustrated
# nesting keys exactly -- no reshaping needed for these three.
_VERBATIM_AXIS_BLOCKS = ("field", "claim_type", "theory_school")


def build_frontmatter(record: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    """Assemble a chunk note's frontmatter mapping from a tagged record
    (`axial.tag.build_tagged_record`'s shape): `chunk_id`, `section`,
    `chunk_text`, and `source_meta` (the five source-level fields, PRD §7.2)
    reused verbatim from the envelope, plus the chunk-level axis block --
    `schema_version`, `role_in_argument` (flat scalar), `field`/`claim_type`/
    `theory_school` (nested, carried through as the tagger produced them),
    and `empirical_scope` reshaped from the tagger's flat scalar + separate
    top-level `country` into Appendix H's nested `{value, country}` mapping
    (issue #31 slice 04)."""
    frontmatter: dict[str, Any] = {
        "chunk_id": record["chunk_id"],
        "section": record["section"],
        "chunk_text": record["chunk_text"],
        "source_meta": {field: envelope.get(field) for field in SOURCE_META_FIELDS},
        "schema_version": record["schema_version"],
        "role_in_argument": record["role_in_argument"],
    }

    for axis_name in _VERBATIM_AXIS_BLOCKS:
        if axis_name in record:
            frontmatter[axis_name] = record[axis_name]

    if "empirical_scope" in record:
        empirical_scope: dict[str, Any] = {"value": record["empirical_scope"]}
        if record.get("country") is not None:
            empirical_scope["country"] = record["country"]
        frontmatter["empirical_scope"] = empirical_scope

    return frontmatter


def render_note(frontmatter: dict[str, Any], body: str) -> str:
    """Render a note's full text: a `---`-delimited YAML frontmatter block
    followed by the body (standard Obsidian/Jekyll convention).

    `default_style='"'` forces every scalar (including multi-line chunk
    text) into a single double-quoted line with embedded newlines escaped
    as `\\n`. Without it, PyYAML's default folded/plain scalar style can
    fold a long chunk_text value across multiple lines, and if that value
    itself contains a line that is exactly `---` (a plausible Markdown
    horizontal rule or table border in real docling/Unstructured output),
    the folded output would place that embedded `---` on its own line
    inside the frontmatter block -- indistinguishable from the closing
    delimiter to a splitter that scans for the first bare `---` line
    (exactly what the locked outer test's frontmatter parser does). Forcing
    double-quoted scalars guarantees no `---` line can ever appear inside
    the frontmatter body itself.
    """
    frontmatter_yaml = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_style='"'
    )
    return f"---\n{frontmatter_yaml}---\n{body}"


def _note_path(vault_dir: Path, chunk_id: str) -> Path:
    return vault_dir / "prose" / f"{chunk_id}.md"


def write_chunk_note(record: dict[str, Any], envelope: dict[str, Any], vault_dir: Path) -> Path:
    """Write one chunk's note under `<vault_dir>/prose/<chunk_id>.md`,
    creating parent directories as needed."""
    frontmatter = build_frontmatter(record, envelope)
    body = f"# {record['section']}\n\n{record['chunk_text']}\n"
    note_text = render_note(frontmatter, body)

    path = _note_path(vault_dir, record["chunk_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_text, encoding="utf-8")
    return path


def run_vault_write(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[Path]:
    """Run vault write on `source_path`: read the stored envelope (never
    recomputing it), run the tagging pass internally via `axial.tag.run_tag`
    (which itself runs the argumentative-chunking pass internally -- one
    thread from source to tagged prose notes), and write one prose note per
    tagged chunk under `<vault_dir>/prose/`, its frontmatter carrying the
    axis block + `schema_version` (issue #31 slice 04). The artifact pool
    receives nothing (PRD §8 P0-8).
    """
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)

    env_path = envelope_path(source_id, envelopes_dir)
    if not env_path.exists():
        raise MissingEnvelopeError(env_path)
    envelope = json.loads(env_path.read_text(encoding="utf-8"))

    try:
        records = run_tag(path, client=client, envelopes_dir=envelopes_dir, config_path=config_path)
    except TagError as exc:
        raise TaggingFailedError(exc) from exc

    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)

    return [write_chunk_note(record, envelope, vault_dir) for record in records]
