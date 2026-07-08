"""Vault write: persists tagged prose chunks and classified artifacts as
Obsidian notes under `data/vault/prose/` and `data/vault/artifacts/`
respectively (PRD §5 stage 7; §7.2; §8 P0-5/P0-8) -- two separate,
independently queryable surfaces sharing metadata conventions (see
plans/minimal-ingestion/06-vault-write.md, plans/tag/04-tag-vault-frontmatter.md,
and plans/artifacts/02-artifact-pool-write.md).

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

The artifact pool (`<vault_dir>/artifacts/`) is a separate surface (issue
#32 slice 02): this pass also runs the artifact-classification pass
internally via `axial.artifacts.run_artifacts` -- exactly as it runs
`run_chunk` for prose -- and writes one note per classified artifact to
`<vault_dir>/artifacts/<artifact_id>.md`, carrying `artifact_id`,
`artifact_role`, `field`, and source/section provenance in its frontmatter,
plus a `retrievable` boolean that is `False` only for the `discard` role
(PRD §8 P0-5: "discard-tagged artifacts are retained in the pool but
flagged non-retrievable"). Any error from the internal artifacts pass
(`axial.artifacts.ArtifactsError` or `axial.tag.TagError`, e.g. an
out-of-schema `artifact_role`/`field` value) is wrapped into a
`VaultError` subclass here too, so the CLI never renders a bare traceback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from axial.artifacts import (
    ArtifactsError,
    DEFAULT_DOMAIN_DIR as _ARTIFACTS_DEFAULT_DOMAIN_DIR,
    DISCARD_ROLE,
    run_artifacts,
)
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

# Default domain directory for the internal artifacts pass, mirroring
# `axial.artifacts.DEFAULT_DOMAIN_DIR`, overridable via a `domain_dir`
# argument to `run_vault_write`.
DEFAULT_DOMAIN_DIR = _ARTIFACTS_DEFAULT_DOMAIN_DIR

# Frontmatter keys reused verbatim from `axial.artifacts`' own record shape
# (PRD §7.2) for every artifact note.
ARTIFACT_FRONTMATTER_FIELDS = ("artifact_id", "artifact_role", "field", "source_id", "section")


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


class ArtifactClassificationFailedError(VaultError):
    """Raised when the internal artifact-classification pass fails --
    either `axial.artifacts.ArtifactsError` (e.g. a missing schema/codebook)
    or `axial.tag.TagError` (e.g. `TagNotInSchemaError` for an out-of-schema
    `artifact_role`/`field` value, reused by `axial.artifacts` per issue
    #32 slice 02's carry-in convergence). Wrapped here so the CLI always
    renders a clean `error: ...` line, never a bare traceback."""

    def __init__(self, cause: ArtifactsError | TagError):
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


def build_artifact_frontmatter(record: dict[str, Any]) -> dict[str, Any]:
    """Assemble one artifact note's frontmatter mapping: `artifact_id`,
    `artifact_role`, `field`, `source_id`, `section` reused verbatim from
    the artifact record (`axial.artifacts.build_artifact_record`'s shape),
    plus a `retrievable` boolean that is `False` only for the `discard`
    role (PRD §8 P0-5) -- every other in-schema role is retrievable."""
    frontmatter = {field: record.get(field) for field in ARTIFACT_FRONTMATTER_FIELDS}
    frontmatter["retrievable"] = record["artifact_role"] != DISCARD_ROLE
    return frontmatter


def _artifact_note_path(vault_dir: Path, artifact_id: str) -> Path:
    return vault_dir / "artifacts" / f"{artifact_id}.md"


def write_artifact_note(record: dict[str, Any], vault_dir: Path) -> Path:
    """Write one artifact's note under
    `<vault_dir>/artifacts/<artifact_id>.md`, creating parent directories as
    needed -- a surface separate from `<vault_dir>/prose/` (PRD §8 P0-8)."""
    frontmatter = build_artifact_frontmatter(record)
    body = f"# {record['section']}\n\nArtifact `{record['artifact_id']}` ({record['artifact_role']}).\n"
    note_text = render_note(frontmatter, body)

    path = _artifact_note_path(vault_dir, record["artifact_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_text, encoding="utf-8")
    return path


def run_vault_write(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
) -> list[Path]:
    """Run vault write on `source_path`: read the stored envelope (never
    recomputing it), run the tagging pass internally via `axial.tag.run_tag`
    (which itself runs the argumentative-chunking pass internally -- one
    thread from source to tagged prose notes) and write one prose note per
    tagged chunk under `<vault_dir>/prose/`, its frontmatter carrying the axis
    block + `schema_version` (issue #31 slice 04); then run the
    artifact-classification pass internally via `axial.artifacts.run_artifacts`
    and write one note per classified artifact under `<vault_dir>/artifacts/`
    (issue #32 slice 02) -- two separate surfaces sharing metadata conventions
    (PRD §8 P0-8).
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

    try:
        artifact_records = run_artifacts(
            path, client=client, domain_dir=domain_dir, config_path=config_path
        )
    except (ArtifactsError, TagError) as exc:
        raise ArtifactClassificationFailedError(exc) from exc

    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)

    prose_paths = [write_chunk_note(record, envelope, vault_dir) for record in records]
    artifact_paths = [write_artifact_note(record, vault_dir) for record in artifact_records]
    return prose_paths + artifact_paths
