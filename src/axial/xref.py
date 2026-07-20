"""Cross-reference detection: for each prose chunk, one LLM call decides
which (if any) of the source's real artifacts (tables or figures) the
chunk's prose text references (e.g. "as Table 3 shows") (PRD §5 stage 7,
§7.2, §8 P0-7).

This pass never invents a second chunk-id or artifact-id scheme: it reads
chunk records from the on-disk chunk artifact (`axial.chunk.read_chunks`,
PRD §7.7 -- never (re)computed here, issue #154) and reuses
`axial.artifacts.run_artifacts` for the source's real artifact records, so
the pairs it emits are usable as a graph over the system's real, addressable
chunk/artifact records. A referenced artifact_id absent from the source's
real artifact set produces no pair -- a dangling link is filtered, not
emitted (PRD §8 P0-7). This slice emits xref pairs to stdout only; writing
bidirectional backlinks into vault notes' frontmatter is slice 02.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from axial.artifacts import (
    ArtifactsError,
    DEFAULT_DOMAIN_DIR,
    run_artifacts,
)
from axial.chunk import ChunkError, read_chunks
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    LLMClient,
    LLMError,
    XREF_PASS_NAME,
    get_client,
)
from axial.nonprose_guard import garble_only_skip_reason
from axial.tag import TagError

# Default xref-pass checkpoint directory, mirroring `axial.artifacts.ARTIFACTS_DIR`
# / `axial.tag.TAGS_DIR` exactly (issue #110).
XREF_DIR = Path("data/xref")

# Input-guard threshold for genuinely garbled prose (issue #111, lifted into
# `axial.nonprose_guard` by issue #132). Demoted from primary gate to
# garble-only backstop by issue #169 (source-router slice 04): the chunk
# artifact this pass reads is now prose-only and size-bounded by the router
# + chunk band (source-router slices 02-03), so only the non-alpha ratio arm
# remains -- size never skips a chunk here. Kept as a module-level alias so
# external references to this exact name keep working.
_XREF_MAX_NON_ALPHA_RATIO = 0.4

_XREF_PROMPT_TEMPLATE = """\
You are deciding which, if any, of the source's known artifacts (tables or \
figures) the CHUNK below explicitly references (e.g. "as Table 3 shows"). \
Respond with ONLY a JSON object (no prose, no markdown fences) with exactly \
one key, "referenced_artifact_ids": a JSON array of artifact_id strings \
drawn from the list below that this chunk references (an empty array if \
none).

Known artifacts:

{artifact_ids}

Chunk:

{chunk_text}
"""

_NO_ARTIFACTS_PLACEHOLDER = "(none)"


class XrefError(Exception):
    """Base class for all cross-reference-detection errors."""


class MissingSourceError(XrefError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, cause: _EnvelopeMissingSourceError):
        self.cause = cause
        super().__init__(str(cause))


class ChunkingFailedError(XrefError):
    """Raised when reading the on-disk chunk artifact (`read_chunks`) fails
    -- e.g. no chunk artifact yet (`axial.chunk.MissingChunkArtifactError`,
    telling the operator to run `axial chunk` first). This pass never
    (re)computes chunk boundaries itself."""

    def __init__(self, cause: ChunkError):
        self.cause = cause
        super().__init__(str(cause))


class ArtifactsFailedError(XrefError):
    """Raised when the underlying artifact-classification pass
    (`run_artifacts`) fails -- either `axial.artifacts.ArtifactsError`
    (e.g. a missing schema/codebook) or `axial.tag.TagError` (e.g.
    `TagNotInSchemaError` for an out-of-schema `artifact_role`/`field`
    value, reused by `axial.artifacts`; a `TagError`, not an
    `ArtifactsError`, so it must be caught here too -- issue #90, mirrors
    `axial.vault.ArtifactClassificationFailedError`'s existing catch of both
    for its own direct `run_artifacts` call)."""

    def __init__(self, cause: ArtifactsError | TagError):
        self.cause = cause
        super().__init__(str(cause))


class LLMFailedError(XrefError):
    """Raised when the LLM client -- selection/config or the completion call
    itself -- fails, so the CLI renders a clean `error: ...` instead of a
    bare traceback."""

    def __init__(self, cause: LLMError | httpx.HTTPError):
        self.cause = cause
        super().__init__(str(cause))


class XrefParseError(XrefError):
    """Raised when the model's xref response is not parseable into a list of
    referenced artifact_id strings."""


class XrefCheckpointCorruptError(XrefError):
    """Raised when an xref-pass checkpoint file has a torn NON-final line --
    genuine corruption unrelated to a hard kill mid-append (a torn final line
    is healed silently). Mirrors `axial.artifacts.ArtifactCheckpointCorruptError`
    exactly (issue #110)."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt xref checkpoint {path}: line {line_no} is not valid JSON: {cause}"
        )


def _default_xref_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Resolve the xref-checkpoint directory, mirroring
    `axial.artifacts._default_artifacts_dir` exactly: honor
    `config/pipeline.yaml`'s `paths.xref_dir` when declared, else fall back to
    the module-level `XREF_DIR` default (`data/xref`). An absent file/key
    falls back to `XREF_DIR`."""
    if not config_path.is_file():
        return XREF_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("xref_dir")
    return Path(configured) if configured else XREF_DIR


def xref_checkpoint_path(source_id: str, xref_dir: Path = XREF_DIR) -> Path:
    """The resume path for `source_id`'s xref-pass checkpoint (one JSON line
    per processed chunk, appended as each chunk's referenced ids are parsed),
    keyed by the content-hashed source_id -- mirrors
    `axial.artifacts.artifacts_checkpoint_path` exactly (issue #110)."""
    return xref_dir / f"{source_id}.jsonl"


def _non_prose_skip_reason(chunk_text: str) -> str | None:
    """Return a human-readable reason to skip `chunk_text` from the xref pass
    as genuinely garbled prose, or None to process it normally (issue #111;
    demoted from primary prose/non-prose gate to garble-only backstop by
    issue #169, source-router slice 04). An OCR'd index/bibliography that
    slips type classification becomes one mostly-non-alphabetic chunk with
    zero cross-reference value that would otherwise stall the LLM.

    Delegates to the shared `axial.nonprose_guard.garble_only_skip_reason`
    (the non-alpha arm ONLY -- size never skips a chunk here, since the
    chunk artifact this pass reads is prose-only and size-bounded by the
    router + chunk band), passing this module's own threshold name through
    explicitly so behavior is unchanged even if the shared default ever
    diverges from xref's own."""
    return garble_only_skip_reason(
        chunk_text,
        max_non_alpha_ratio=_XREF_MAX_NON_ALPHA_RATIO,
    )


def compose_xref_prompt(chunk_text: str, artifact_records: list[dict[str, Any]]) -> str:
    """Compose the xref-detection prompt from the chunk's own text and the
    source's real, known artifacts -- never a hardcoded list.

    Each known artifact is rendered as its `artifact_id` AND its `caption`
    (`axial.artifacts.build_artifact_record`'s own field), when it has one
    -- not the bare id alone (issue #272). A citing chunk's prose names the
    artifact by its caption ("as Table 8.2 shows"), which an opaque id like
    "src_art_85.8" carries no trace of, so a bare-id list left the model with
    nothing to match against and zero cross-references were ever detected.
    An artifact with no attached caption falls back to its bare id alone,
    never a broken/blank line."""
    lines = []
    for record in artifact_records:
        artifact_id = record["artifact_id"]
        caption = record.get("caption")
        lines.append(f"- {artifact_id}: {caption}" if caption else f"- {artifact_id}")
    ids_block = "\n".join(lines) if lines else _NO_ARTIFACTS_PLACEHOLDER
    return _XREF_PROMPT_TEMPLATE.format(artifact_ids=ids_block, chunk_text=chunk_text)


def parse_referenced_artifact_ids(raw: str) -> list[str]:
    """Parse the model's raw xref response into a list of referenced
    artifact_id strings. Accepts a top-level object with a
    "referenced_artifact_ids" key, or a bare top-level array."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise XrefParseError(f"model response was not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        if "referenced_artifact_ids" not in data:
            raise XrefParseError(
                f"expected a top-level 'referenced_artifact_ids' key, got "
                f"keys: {sorted(data.keys())}"
            )
        ids = data["referenced_artifact_ids"]
    else:
        ids = data

    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise XrefParseError(
            f"expected referenced artifact ids to be a JSON array of strings, got {ids!r}"
        )
    return ids


def build_xref_pairs(
    chunk_id: str, referenced_ids: list[str], known_artifact_ids: set[str]
) -> list[dict[str, str]]:
    """Assemble `{"chunk_id": ..., "artifact_id": ...}` pairs for `chunk_id`,
    filtering `referenced_ids` against `known_artifact_ids` -- an id not
    among the source's real artifacts (a dangling link) produces no pair
    (PRD §8 P0-7)."""
    return [
        {"chunk_id": chunk_id, "artifact_id": artifact_id}
        for artifact_id in referenced_ids
        if artifact_id in known_artifact_ids
    ]


def run_xref(
    source_path: str | Path,
    client: LLMClient | None = None,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    chunks_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    xref_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the cross-reference-detection pass on `source_path`.

    Reads chunk records from the on-disk chunk artifact
    (`axial.chunk.read_chunks`, never (re)computed here -- issue #154) and
    reuses `run_artifacts` for the source's real artifact records (never a
    parallel id scheme for either). For each chunk, calls the LLM once
    (`pass_name="xref"`) with the chunk text and the source's known artifact
    ids, then filters the parsed referenced ids against the real artifact-id
    set before emitting pairs -- a referenced id absent from that set (a
    dangling link) yields no pair.

    `artifacts_dir` (issue #98), when supplied, is threaded straight through
    to this pass's own internal `run_artifacts` call, so it reuses the SAME
    artifacts-pass checkpoint `axial.vault.run_vault_write`'s own direct
    `run_artifacts` call just wrote/reused, instead of reclassifying every
    artifact a second time. Standalone `axial xref` passes none, unchanged.

    `xref_dir` (issue #110), when supplied, turns on per-chunk checkpoint/
    resume: each processed chunk's referenced ids are appended to
    `<xref_dir>/<source_id>.jsonl` as they are parsed, and a later call for
    the same source skips any chunk already checkpointed (by `chunk_id`) --
    reusing its stored result without ever re-calling the LLM for it, so a
    mid-pass stall costs one LLM call on the resume, not the whole source.
    Standalone `axial xref` passes none, unchanged.
    """
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    if client is None:
        try:
            client = get_client(config_path=config_path)
        except LLMError as exc:
            raise LLMFailedError(exc) from exc

    try:
        chunk_records = read_chunks(source_id, chunks_dir=chunks_dir, config_path=config_path)
    except ChunkError as exc:
        raise ChunkingFailedError(exc) from exc

    try:
        artifact_records = run_artifacts(
            path,
            client=client,
            domain_dir=domain_dir,
            config_path=config_path,
            artifacts_dir=artifacts_dir,
        )
    except (ArtifactsError, TagError) as exc:
        raise ArtifactsFailedError(exc) from exc

    known_artifact_ids = {record["artifact_id"] for record in artifact_records}
    # Sorted by artifact_id for a deterministic prompt ordering (mirrors the
    # prior bare-id list's own sort); carries each record's `caption` through
    # to `compose_xref_prompt` (issue #272).
    sorted_artifact_records = sorted(artifact_records, key=lambda record: record["artifact_id"])

    # Per-chunk checkpoint/resume (issue #110), opt-in via `xref_dir`,
    # mirroring the tag/artifacts passes: load already-processed chunks so a
    # resumed run reuses each verbatim and never re-calls the LLM for it.
    checkpoint_path: Path | None = None
    already_xrefed: dict[str, list[str]] = {}
    if xref_dir is not None:
        checkpoint_path = xref_checkpoint_path(source_id, xref_dir)
        already_xrefed = {
            record["chunk_id"]: record.get("referenced_artifact_ids", [])
            for record in load_checkpoint_records(checkpoint_path, XrefCheckpointCorruptError)
        }

    pairs: list[dict[str, Any]] = []
    for chunk in chunk_records:
        chunk_id = chunk["chunk_id"]

        # Resume: a chunk already checkpointed by an earlier run is reused
        # verbatim and never re-sent to the model (issue #110). Its stored
        # referenced ids are re-filtered against the current known-artifact
        # set, exactly as a fresh call would be.
        checkpointed = already_xrefed.get(chunk_id)
        if checkpointed is not None:
            pairs.extend(build_xref_pairs(chunk_id, checkpointed, known_artifact_ids))
            continue

        chunk_text = chunk["text"]

        # Input guard (issue #111): skip non-prose back-matter (a huge OCR'd
        # index/bibliography) -- no LLM call, no pairs, no checkpoint. The
        # skip is a deterministic function of the text, so it re-applies on
        # every resume without ever stalling the model.
        skip_reason = _non_prose_skip_reason(chunk_text)
        if skip_reason is not None:
            print(f"xref: skipping chunk {chunk_id}: {skip_reason}", file=sys.stderr)
            continue

        prompt = compose_xref_prompt(chunk_text, sorted_artifact_records)

        try:
            raw_response = complete_json(client, prompt, pass_name=XREF_PASS_NAME)
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc
        except ModelJsonError as exc:
            raise XrefParseError(f"model response was not valid JSON: {exc}") from exc

        referenced_ids = parse_referenced_artifact_ids(raw_response)

        # Persist this chunk's referenced ids before moving on (write+flush
        # per chunk), so a failure on a later chunk leaves every processed
        # chunk durably checkpointed for the resume run (issue #110).
        if checkpoint_path is not None:
            append_checkpoint_record(
                checkpoint_path,
                {"chunk_id": chunk_id, "referenced_artifact_ids": referenced_ids},
            )
        pairs.extend(build_xref_pairs(chunk_id, referenced_ids, known_artifact_ids))

    return pairs
