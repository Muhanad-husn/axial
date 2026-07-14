"""Vault write: persists tagged prose chunks and classified artifacts as
Obsidian notes under `data/vault/prose/` and `data/vault/artifacts/`
respectively (PRD §5 stage 7; §7.2; §8 P0-5/P0-8) -- two separate,
independently queryable surfaces sharing metadata conventions (see
plans/minimal-ingestion/06-vault-write.md, plans/tag/04-tag-vault-frontmatter.md,
and plans/artifacts/02-artifact-pool-write.md).

This pass runs the tagging pass itself, internally, via `axial.tag.run_tag`
-- exactly as `axial tag` does, which itself reads chunk records from the
on-disk chunk artifact (`axial.chunk.read_chunks`, never recomputed -- issue
#154) -- so chunk_id/section/chunk_text provenance and every axis tag are
computed exactly once, in tag.py (never reimplemented here). This
pass also reuses `axial.envelope.compute_source_id`/`envelope_path`/
`_default_envelopes_dir` to locate and read the source's stored envelope
(never recomputing it, PRD §10 "no recompute"). If no stored envelope
exists yet, this pass raises its own typed `MissingEnvelopeError` telling
the caller to run `axial envelope` first.

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
internally via `axial.artifacts.run_artifacts` -- exactly as it reads the
on-disk chunk artifact for prose -- and writes one note per classified
artifact to
`<vault_dir>/artifacts/<artifact_id>.md`, carrying `artifact_id`,
`artifact_role`, `field`, and source/section provenance in its frontmatter,
plus a `retrievable` boolean that is `False` only for the `discard` role
(PRD §8 P0-5: "discard-tagged artifacts are retained in the pool but
flagged non-retrievable"), and (issue #168) `caption` when the artifact
record carries one attached (omitted entirely when it does not, so a
pre-#168 artifact note stays byte-for-byte unchanged). Any error from the
internal artifacts pass
(`axial.artifacts.ArtifactsError` or `axial.tag.TagError`, e.g. an
out-of-schema `artifact_role`/`field` value) is wrapped into a
`VaultError` subclass here too, so the CLI never renders a bare traceback.

Once both note sets are known, a final backlink pass (issue #34 slice 02)
runs the already-implemented cross-reference-detection pass internally via
`axial.xref.run_xref` (detection itself is unchanged from slice 01) and
materializes each detected `(chunk_id, artifact_id)` pair as bidirectional
frontmatter: `artifact_refs` (a list of artifact_ids) on the referencing
prose note, `cited_by` (a list of chunk_ids) on the referenced artifact
note (PRD §7.2, §8 P0-7). Both fields are always present as a list --
`[]` when a note carries no references, never absent/null/a dangling bare
scalar. `build_backlink_maps` computes both directions from the xref pairs
up front (deduping via a set, so a repeated pair never doubles an entry),
and every note is written fresh each run with its backlink list already
resolved -- idempotent by construction, never by patching an existing file
on disk. Any error from the internal xref pass (`axial.xref.XrefError`) is
wrapped into a `VaultError` subclass here too.
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
    _default_artifacts_dir,
    run_artifacts,
)
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
    envelope_path,
    _default_envelopes_dir,
)
from axial.chunk import _default_chunks_dir
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.tag import TagError, _default_tags_dir, run_tag
from axial.xref import XrefError, _default_xref_dir, run_xref, xref_checkpoint_path

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


class XrefFailedError(VaultError):
    """Raised when the internal cross-reference-detection pass
    (`axial.xref.run_xref`) fails, so the CLI always renders a clean
    `error: ...` line, never a bare traceback (issue #34 slice 02)."""

    def __init__(self, cause: XrefError):
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


def build_frontmatter(
    record: dict[str, Any],
    envelope: dict[str, Any],
    artifact_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble a chunk note's frontmatter mapping from a tagged record
    (`axial.tag.build_tagged_record`'s shape): `chunk_id`, `section`,
    `chunk_text`, and `source_meta` (the five source-level fields, PRD §7.2)
    reused verbatim from the envelope, plus the chunk-level axis block --
    `schema_version`, `role_in_argument` (flat scalar), `field`/`claim_type`/
    `theory_school` (nested, carried through as the tagger produced them),
    and `empirical_scope` reshaped from the tagger's flat scalar + separate
    top-level `country` into Appendix H's nested `{value, country}` mapping
    (issue #31 slice 04). `artifact_refs` (issue #34 slice 02) is the list of
    artifact_ids the cross-reference pass detected this chunk citing --
    always a list, `[]` when none, never a dangling absent/null field."""
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

    frontmatter["artifact_refs"] = list(artifact_refs) if artifact_refs else []

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


def write_chunk_note(
    record: dict[str, Any],
    envelope: dict[str, Any],
    vault_dir: Path,
    artifact_refs: list[str] | None = None,
) -> Path:
    """Write one chunk's note under `<vault_dir>/prose/<chunk_id>.md`,
    creating parent directories as needed. `artifact_refs` (issue #34 slice
    02) is this chunk's detected backlink list, threaded through to
    `build_frontmatter` verbatim."""
    frontmatter = build_frontmatter(record, envelope, artifact_refs=artifact_refs)
    body = f"# {record['section']}\n\n{record['chunk_text']}\n"
    note_text = render_note(frontmatter, body)

    path = _note_path(vault_dir, record["chunk_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_text, encoding="utf-8")
    return path


def build_artifact_frontmatter(
    record: dict[str, Any], cited_by: list[str] | None = None
) -> dict[str, Any]:
    """Assemble one artifact note's frontmatter mapping: `artifact_id`,
    `artifact_role`, `field`, `source_id`, `section` reused verbatim from
    the artifact record (`axial.artifacts.build_artifact_record`'s shape),
    plus a `retrievable` boolean that is `False` only for the `discard`
    role (PRD §8 P0-5) -- every other in-schema role is retrievable.
    `cited_by` (issue #34 slice 02) is the list of chunk_ids the
    cross-reference pass detected citing this artifact -- always a list,
    `[]` when none, never a dangling absent/null field. `caption` (issue
    #168) is included only when the record itself carries one -- see below."""
    frontmatter = {field: record.get(field) for field in ARTIFACT_FRONTMATTER_FIELDS}
    frontmatter["retrievable"] = record["artifact_role"] != DISCARD_ROLE
    frontmatter["cited_by"] = list(cited_by) if cited_by else []
    # `caption` (issue #168): the text of a caption block attached to this
    # artifact by `axial.artifacts.run_artifacts`/`_attach_captions`, when
    # present -- omitted entirely (never `caption: null`) when this artifact
    # has no attached caption, mirroring `axial.artifacts.build_artifact_record`'s
    # own conditional-`caption`-inclusion pattern, so a pre-#168 artifact
    # record (no `caption` key at all) still produces a byte-for-byte
    # unchanged frontmatter.
    caption = record.get("caption")
    if caption:
        frontmatter["caption"] = caption
    return frontmatter


def _artifact_note_path(vault_dir: Path, artifact_id: str) -> Path:
    return vault_dir / "artifacts" / f"{artifact_id}.md"


def write_artifact_note(
    record: dict[str, Any], vault_dir: Path, cited_by: list[str] | None = None
) -> Path:
    """Write one artifact's note under
    `<vault_dir>/artifacts/<artifact_id>.md`, creating parent directories as
    needed -- a surface separate from `<vault_dir>/prose/` (PRD §8 P0-8).
    `cited_by` (issue #34 slice 02) is this artifact's detected backlink
    list, threaded through to `build_artifact_frontmatter` verbatim."""
    frontmatter = build_artifact_frontmatter(record, cited_by=cited_by)
    body = f"# {record['section']}\n\nArtifact `{record['artifact_id']}` ({record['artifact_role']}).\n"
    note_text = render_note(frontmatter, body)

    path = _artifact_note_path(vault_dir, record["artifact_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_text, encoding="utf-8")
    return path


def build_backlink_maps(
    pairs: list[dict[str, str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build the two backlink maps from `axial.xref.run_xref`'s
    `{"chunk_id", "artifact_id"}` pairs (issue #34 slice 02): chunk_id ->
    sorted unique artifact_ids it references, and artifact_id -> sorted
    unique chunk_ids that reference it. Deduping via a `set` per key before
    sorting guarantees no run can double an entry, even if a pair repeats
    (e.g. the stub's uniform per-run canned response) -- the source of this
    slice's idempotency, independent of how many times `run_vault_write`
    itself is re-run (each run rebuilds these maps from scratch and
    overwrites the notes, never patching them in place)."""
    chunk_to_artifacts: dict[str, set[str]] = {}
    artifact_to_chunks: dict[str, set[str]] = {}
    for pair in pairs:
        chunk_id = pair["chunk_id"]
        artifact_id = pair["artifact_id"]
        chunk_to_artifacts.setdefault(chunk_id, set()).add(artifact_id)
        artifact_to_chunks.setdefault(artifact_id, set()).add(chunk_id)

    return (
        {chunk_id: sorted(ids) for chunk_id, ids in chunk_to_artifacts.items()},
        {artifact_id: sorted(ids) for artifact_id, ids in artifact_to_chunks.items()},
    )


def run_vault_write(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    chunks_dir: Path | None = None,
    tags_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    xref_dir: Path | None = None,
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
    (PRD §8 P0-8); finally, once both note sets are known, run the
    cross-reference-detection pass internally via `axial.xref.run_xref`
    (detection unchanged from issue #34 slice 01) and materialize each
    detected `(chunk_id, artifact_id)` pair as bidirectional frontmatter --
    `artifact_refs` on the referencing prose note, `cited_by` on the
    referenced artifact note (issue #34 slice 02). Every note is written
    fresh with its backlink list computed up front, so a rerun naturally
    overwrites rather than accumulates -- idempotent by construction, never
    by patching an existing file in place.
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

    # Per-chunk / per-artifact checkpoint/resume (issue #81, extended by
    # issue #98): scoped to vault write. Resolve every checkpoint dir here
    # and thread them into the internal passes so the chunk-pass checkpoint
    # is reused (zero chunking LLM calls on a resumed run), the tag-pass
    # checkpoint drives per-chunk resume, and the artifacts-pass checkpoint
    # drives per-artifact resume; the standalone `axial chunk`/`axial tag`/
    # `axial artifacts`/`axial xref` passes, which never receive these, keep
    # their existing recompute-every-run behavior.
    if chunks_dir is None:
        chunks_dir = _default_chunks_dir(config_path)
    if tags_dir is None:
        tags_dir = _default_tags_dir(config_path)
    if artifacts_dir is None:
        artifacts_dir = _default_artifacts_dir(config_path)
    if xref_dir is None:
        xref_dir = _default_xref_dir(config_path)

    try:
        records = run_tag(
            path,
            client=client,
            config_path=config_path,
            tags_dir=tags_dir,
            chunks_dir=chunks_dir,
        )
    except TagError as exc:
        raise TaggingFailedError(exc) from exc

    try:
        artifact_records = run_artifacts(
            path,
            client=client,
            domain_dir=domain_dir,
            config_path=config_path,
            artifacts_dir=artifacts_dir,
        )
    except (ArtifactsError, TagError) as exc:
        raise ArtifactClassificationFailedError(exc) from exc

    # `artifacts_dir` is threaded into `run_xref` too (issue #98): `run_xref`
    # runs `run_artifacts` internally a SECOND time for the same source in
    # this same process (see module docstring) -- without sharing the
    # checkpoint here, that second call would silently reclassify every
    # artifact again (a real double-spend bug this checkpoint also fixes),
    # even on a run that never failed at all.
    try:
        xref_pairs = run_xref(
            path,
            client=client,
            domain_dir=domain_dir,
            config_path=config_path,
            chunks_dir=chunks_dir,
            artifacts_dir=artifacts_dir,
            xref_dir=xref_dir,
        )
    except XrefError as exc:
        raise XrefFailedError(exc) from exc

    chunk_to_artifacts, artifact_to_chunks = build_backlink_maps(xref_pairs)

    if vault_dir is None:
        vault_dir = _default_vault_dir(config_path)

    prose_paths = [
        write_chunk_note(
            record, envelope, vault_dir, artifact_refs=chunk_to_artifacts.get(record["chunk_id"])
        )
        for record in records
    ]
    artifact_paths = [
        write_artifact_note(
            record, vault_dir, cited_by=artifact_to_chunks.get(record["artifact_id"])
        )
        for record in artifact_records
    ]

    # The xref checkpoint (issue #110) is a failure-recovery journal, not a
    # cross-run cache: now that this vault-write invocation has fully
    # completed (xref detected AND every note materialized), clear it so an
    # independent later run recomputes xref fresh. A run that failed before
    # reaching here leaves the checkpoint in place, so its resume is cheap.
    xref_checkpoint_path(source_id, xref_dir).unlink(missing_ok=True)

    return prose_paths + artifact_paths
